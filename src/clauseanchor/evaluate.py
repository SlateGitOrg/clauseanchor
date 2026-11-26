"""Evaluate the anchored pipeline against gold labels, next to a trust-the-model baseline."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .model import FakeReviewer, FaultPlan, ReviewModel
from .pipeline import review_contract
from .playbook import ISSUE_ORDER, Playbook, load_playbook
from .results import ContractReview
from .seed import GoldContract, load_gold
from .segment import segment
from .values import same_value


class Counts(BaseModel):
    """Raw counts for one issue (or all issues); rates are derived."""

    present: int = 0
    gold_red: int = 0
    gold_total: int = 0
    # RED confusion, anchored pipeline and baseline
    tp: int = 0
    fp: int = 0
    fn: int = 0
    b_tp: int = 0
    b_fp: int = 0
    b_fn: int = 0
    verdict_ok: int = 0
    b_verdict_ok: int = 0
    anchored: int = 0
    b_anchored: int = 0
    value_ok: int = 0
    b_value_ok: int = 0
    quote_faults: int = 0
    quote_caught: int = 0
    mismatch_faults: int = 0
    mismatch_caught: int = 0
    conflicts: int = 0
    conflicts_found: int = 0
    needs_review: int = 0


def _rate(num: int, den: int) -> float:
    return num / den if den else 1.0


class EvalResult(BaseModel):
    issues: dict[str, Counts]
    total: Counts
    faults: dict[str, dict[str, int]]
    bad_offsets: int = 0
    false_flags: int = 0
    contracts: int = 0

    @staticmethod
    def red_recall(c: Counts) -> float:
        return _rate(c.tp, c.tp + c.fn)

    @staticmethod
    def red_precision(c: Counts) -> float:
        return _rate(c.tp, c.tp + c.fp)

    @staticmethod
    def baseline_recall(c: Counts) -> float:
        return _rate(c.b_tp, c.b_tp + c.b_fn)

    @staticmethod
    def baseline_precision(c: Counts) -> float:
        return _rate(c.b_tp, c.b_tp + c.b_fp)

    def to_markdown(self, playbook: Playbook) -> str:
        head = (
            "| Issue | Gold RED | RED recall | RED precision | Baseline recall "
            "| Baseline precision | Anchor rate | Baseline anchor rate | Quote faults caught "
            "| Value accuracy | Baseline value accuracy | Conflicts detected |"
        )
        lines = [head, "|" + " --- |" * 12]

        def row(label: str, c: Counts) -> str:
            return (
                f"| {label} | {c.gold_red} | {self.red_recall(c):.3f} | "
                f"{self.red_precision(c):.3f} | {self.baseline_recall(c):.3f} | "
                f"{self.baseline_precision(c):.3f} | {_rate(c.anchored, c.present):.3f} | "
                f"{_rate(c.b_anchored, c.present):.3f} | {c.quote_caught}/{c.quote_faults} | "
                f"{_rate(c.value_ok, c.present):.3f} | {_rate(c.b_value_ok, c.present):.3f} | "
                f"{c.conflicts_found}/{c.conflicts} |"
            )

        for name in ISSUE_ORDER:
            lines.append(row(playbook.issues[name].title, self.issues[name]))
        lines.append(row("All issues", self.total))
        return "\n".join(lines) + "\n"


_FAULT_FLAG = {
    "paraphrased_quote": "UNANCHORED",
    "definition_section": "WRONG_SECTION",
    "value_mismatch": "VALUE_MISMATCH",
    "missed_carveout": "CONFLICT",
}


def evaluate_reviews(
    reviews: dict[str, ContractReview],
    texts: dict[str, str],
    gold: dict[str, GoldContract],
    plan: FaultPlan,
    playbook: Playbook,
) -> EvalResult:
    per = {name: Counts() for name in ISSUE_ORDER}
    faults = {k: {"injected": 0, "caught": 0} for k in _FAULT_FLAG}
    bad_offsets = false_flags = 0
    for doc_id, review in reviews.items():
        by_issue = review.by_issue()
        for name in ISSUE_ORDER:
            issue, c = playbook.issues[name], per[name]
            label, res = gold[doc_id].labels[name], by_issue[name]
            fault = plan.get(doc_id, name)
            c.gold_total += 1
            gold_red = label.verdict == "RED"
            c.gold_red += gold_red
            pred_red = res.verdict == "RED"
            c.tp += gold_red and pred_red
            c.fp += (not gold_red) and pred_red
            c.fn += gold_red and not pred_red
            c.verdict_ok += res.verdict == label.verdict
            first = res.first
            if first.quote is None and first.value is None:
                base_verdict = issue.missing
            else:
                base_verdict = issue.verdict(first.value)
            b_red = base_verdict == "RED"
            c.b_tp += gold_red and b_red
            c.b_fp += (not gold_red) and b_red
            c.b_fn += gold_red and not b_red
            c.b_verdict_ok += base_verdict == label.verdict
            c.needs_review += res.status == "NEEDS_REVIEW"
            if label.present:
                c.present += 1
                c.anchored += res.status == "FOUND" and res.anchor is not None
                c.b_anchored += first.anchor_status == "ANCHORED"
                c.value_ok += res.status == "FOUND" and same_value(res.value, label.value)
                c.b_value_ok += same_value(first.value, label.value)
            if res.anchor is not None:
                a = res.anchor
                if texts[doc_id][a.start : a.end] != a.text:
                    bad_offsets += 1
            if "carve_out" in label.tags:
                c.conflicts += 1
                c.conflicts_found += "CONFLICT" in res.flags and same_value(res.value, label.value)
            if fault is not None:
                faults[fault.fault]["injected"] += 1
                caught = _FAULT_FLAG[fault.fault] in res.flags
                faults[fault.fault]["caught"] += caught
                if fault.fault in ("paraphrased_quote", "definition_section"):
                    c.quote_faults += 1
                    c.quote_caught += caught
                elif fault.fault == "value_mismatch":
                    c.mismatch_faults += 1
                    c.mismatch_caught += caught
            expected = {_FAULT_FLAG[fault.fault]} if fault else set()
            if "carve_out" in label.tags:
                expected.add("CONFLICT")
            false_flags += sum(
                1
                for f in res.flags
                if f
                in (
                    "UNANCHORED",
                    "WRONG_SECTION",
                    "SECTION_MISMATCH",
                    "VALUE_MISMATCH",
                    "CONFLICT",
                    "MISSED_TERM",
                )
                and f not in expected
            )
    total = Counts()
    for c in per.values():
        for field_name in Counts.model_fields:
            setattr(total, field_name, getattr(total, field_name) + getattr(c, field_name))
    return EvalResult(
        issues=per,
        total=total,
        faults=faults,
        bad_offsets=bad_offsets,
        false_flags=false_flags,
        contracts=len(reviews),
    )


def load_data(data_dir: str | Path) -> tuple[dict[str, str], dict[str, GoldContract]]:
    root = Path(data_dir)
    texts = {p.stem: p.read_text("utf-8") for p in sorted((root / "contracts").glob("*.txt"))}
    return texts, load_gold(root / "gold.json")


def run_eval(
    data_dir: str | Path,
    model: ReviewModel | None = None,
    playbook: Playbook | None = None,
    plan: FaultPlan | None = None,
) -> tuple[EvalResult, dict[str, ContractReview], Playbook]:
    """Review every contract under `data_dir` and score the result against gold."""
    root = Path(data_dir)
    texts, gold = load_data(root)
    playbook = playbook or load_playbook(root / "playbook.yaml")
    if plan is None:
        plan_path = root / "fault_plan.yaml"
        plan = FaultPlan.load(plan_path) if plan_path.exists() else FaultPlan()
    model = model or FakeReviewer(plan)
    reviews = {
        doc_id: review_contract(segment(text, doc_id), playbook, model)
        for doc_id, text in texts.items()
    }
    return evaluate_reviews(reviews, texts, gold, plan, playbook), reviews, playbook
