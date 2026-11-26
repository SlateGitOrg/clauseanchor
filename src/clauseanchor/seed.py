"""Seeded generator: 120 contracts, gold labels for every issue, and a fault plan."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .contracts import build_contract
from .model import FakeReviewer, Fault, FaultPlan
from .playbook import ISSUE_ORDER, default_playbook_text, load_playbook
from .retrieve import Retriever
from .segment import segment
from .templates import FEES_MULT, Instance
from .values import same_value

N_MSA, N_DPA = 70, 50
N_CONTRACTS = N_MSA + N_DPA
FAULT_COUNTS = {
    "paraphrased_quote": 40,
    "value_mismatch": 20,
    "definition_section": 15,
    "missed_carveout": 10,
}

DOMAINS: dict[str, dict[str, list[Any]]] = {
    "liability_cap_months": {"GREEN": [12, 18, 24, 36], "AMBER": [6, 9], "RED": [2, 3, 4]},
    "governing_law": {
        "GREEN": ["England and Wales", "New York", "Delaware"],
        "AMBER": ["California", "Ireland", "Singapore"],
        "RED": ["Texas", "Nevada", "Cayman Islands"],
    },
    "auto_renewal_notice_days": {"GREEN": [15, 30], "AMBER": [45, 60], "RED": [90, 120]},
    "payment_terms_days": {"GREEN": [45, 60], "AMBER": [30, 35], "RED": [14, 15, 21]},
    "termination_for_convenience": {"GREEN": [True], "AMBER": [], "RED": [False]},
    "breach_notice_hours": {"GREEN": [24, 48, 72], "AMBER": [96], "RED": [120, 168]},
    "assignment_consent": {"GREEN": [True], "AMBER": [], "RED": [False]},
    "indemnity_ip": {"GREEN": [True], "AMBER": [], "RED": [False]},
}
GRADED = {k for k, v in DOMAINS.items() if v["AMBER"]}
N_MISSING, N_RED, N_AMBER = 12, 30, 29


class GoldLabel(BaseModel):
    value: Any = None
    verdict: str
    present: bool
    tags: list[str] = []
    base_value: Any = None


class GoldContract(BaseModel):
    doc_type: str
    labels: dict[str, GoldLabel]


def _plan_issue(issue: str, rng: random.Random) -> list[Instance]:
    """120 planted instances for one issue with exact verdict quotas."""
    dom = DOMAINS[issue]
    amber = N_AMBER if issue in GRADED else 0
    plan: list[Instance] = []

    def add(verdict: str, count: int, tags: list[str] | None = None) -> None:
        for _ in range(count):
            plan.append(Instance(issue, True, rng.choice(dom[verdict]), verdict, list(tags or [])))

    if issue == "liability_cap_months":
        for verdict, count in (("RED", 14), ("AMBER", 6)):
            for _ in range(count):
                inst = Instance(issue, True, rng.choice(dom[verdict]), verdict, ["carve_out"])
                inst.base_value = rng.choice(dom["GREEN"])
                plan.append(inst)
        for verdict, count in (("RED", 6), ("AMBER", 5), ("GREEN", 14)):
            for _ in range(count):
                mult = rng.choice(FEES_MULT[verdict])
                plan.append(
                    Instance(issue, True, mult[2], verdict, ["fees_multiplier"], None, mult)
                )
        add("RED", N_RED - 20)
        add("AMBER", amber - 11)
        add("GREEN", N_CONTRACTS - N_MISSING - 20 - 25 - (N_RED - 20) - (amber - 11))
    else:
        add("RED", N_RED)
        add("AMBER", amber)
        add("GREEN", N_CONTRACTS - N_MISSING - N_RED - amber)
    for _ in range(N_MISSING):
        plan.append(Instance(issue, False, None, "RED", ["missing"]))
    rng.shuffle(plan)
    return plan


def _flip(issue: str, gold: Any, target: str, rng: random.Random) -> Any:
    options = [v for v in DOMAINS[issue][target] if not same_value(v, gold)]
    return rng.choice(options)


def build_dataset(seed: int = 7) -> tuple[dict[str, str], dict[str, GoldContract], FaultPlan]:
    """All contract texts, gold labels and the fault plan for a seed."""
    rng = random.Random(seed)
    plans = {issue: _plan_issue(issue, rng) for issue in ISSUE_ORDER}
    texts: dict[str, str] = {}
    gold: dict[str, GoldContract] = {}
    instances: dict[str, dict[str, Instance]] = {}
    for index in range(N_CONTRACTS):
        doc_type = "msa" if index < N_MSA else "dpa"
        doc_id = f"{doc_type}-{index + 1 if doc_type == 'msa' else index - N_MSA + 1:03d}"
        inst = {issue: plans[issue][index] for issue in ISSUE_ORDER}
        texts[doc_id] = build_contract(doc_id, doc_type, inst, random.Random(f"{seed}:{doc_id}"))
        instances[doc_id] = inst
        gold[doc_id] = GoldContract(
            doc_type=doc_type,
            labels={
                issue: GoldLabel(
                    value=i.value,
                    verdict=i.verdict,
                    present=i.present,
                    tags=i.tags,
                    base_value=i.base_value,
                )
                for issue, i in inst.items()
            },
        )
    plan = _plan_faults(texts, instances, rng)
    return texts, gold, plan


def _plan_faults(
    texts: dict[str, str], instances: dict[str, dict[str, Instance]], rng: random.Random
) -> FaultPlan:
    playbook = load_playbook()
    clean = FakeReviewer()
    eligible: dict[str, dict[str, list[tuple[str, str]]]] = {
        k: defaultdict(list) for k in FAULT_COUNTS
    }
    for doc_id, text in texts.items():
        contract = segment(text, doc_id)
        retriever = Retriever(contract)
        for issue_name, inst in instances[doc_id].items():
            if not inst.present:
                continue
            issue = playbook.issues[issue_name]
            clauses = [h.clause for h in retriever.retrieve(issue)]
            base = clean.find(issue, clauses)
            if not same_value(base.value, inst.value):
                raise AssertionError(f"{doc_id} {issue_name}: clean model gave {base.value!r}")
            carve = "carve_out" in inst.tags
            if carve:
                fault = FaultPlan(faults={doc_id: {issue_name: Fault(fault="missed_carveout")}})
                got = FakeReviewer(fault).find(issue, clauses)
                if same_value(got.value, inst.base_value):
                    eligible["missed_carveout"][inst.verdict].append((doc_id, issue_name))
                continue
            eligible["paraphrased_quote"][issue_name].append((doc_id, issue_name))
            eligible["value_mismatch"][inst.verdict].append((doc_id, issue_name))
            fault = FaultPlan(faults={doc_id: {issue_name: Fault(fault="definition_section")}})
            got = FakeReviewer(fault).find(issue, clauses)
            if got.section and re_definition(contract, got.section):
                eligible["definition_section"][issue_name].append((doc_id, issue_name))

    used: set[tuple[str, str]] = set()
    faults: dict[str, dict[str, Fault]] = defaultdict(dict)

    def take(kind: str, pool: list[tuple[str, str]], n: int, **extra: Any) -> None:
        pool = [p for p in pool if p not in used]
        rng.shuffle(pool)
        for doc_id, issue_name in pool[:n]:
            used.add((doc_id, issue_name))
            faults[doc_id][issue_name] = Fault(fault=kind, **extra)  # type: ignore[arg-type]

    def spread(kind: str, by_key: dict[str, list[tuple[str, str]]], n: int) -> None:
        """Take n faults round-robin across issues so every issue is exercised."""
        queues = {k: [p for p in v if p not in used] for k, v in sorted(by_key.items())}
        for q in queues.values():
            rng.shuffle(q)
        taken = 0
        while taken < n and any(queues.values()):
            for key in list(queues):
                if taken < n and queues[key]:
                    doc_id, issue_name = queues[key].pop()
                    used.add((doc_id, issue_name))
                    faults[doc_id][issue_name] = Fault(fault=kind)  # type: ignore[arg-type]
                    taken += 1

    red_carve = [p for p in eligible["missed_carveout"]["RED"]]
    take("missed_carveout", red_carve, 8)
    take("missed_carveout", eligible["missed_carveout"]["AMBER"], 2)
    spread("definition_section", eligible["definition_section"], FAULT_COUNTS["definition_section"])
    # value mismatches: 14 flip RED to GREEN (misses), 6 flip GREEN to RED (false alarms)
    for verdict, target, n in (("RED", "GREEN", 14), ("GREEN", "RED", 6)):
        pool = [p for p in eligible["value_mismatch"][verdict] if p not in used]
        by_issue: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for p in pool:
            by_issue[p[1]].append(p)
        chosen: list[tuple[str, str]] = []
        queues = {k: rng.sample(v, len(v)) for k, v in sorted(by_issue.items())}
        while len(chosen) < n:
            for key in list(queues):
                if len(chosen) < n and queues[key]:
                    chosen.append(queues[key].pop())
        for doc_id, issue_name in chosen:
            used.add((doc_id, issue_name))
            gold_value = instances[doc_id][issue_name].value
            wrong = _flip(issue_name, gold_value, target, rng)
            faults[doc_id][issue_name] = Fault(fault="value_mismatch", value=wrong)
    spread("paraphrased_quote", eligible["paraphrased_quote"], FAULT_COUNTS["paraphrased_quote"])
    return FaultPlan(faults={k: dict(v) for k, v in sorted(faults.items())})


def re_definition(contract: Any, number: str) -> bool:
    clause = contract.by_number.get(number)
    return clause is not None and "definition" in clause.section.lower()


def write_dataset(out: str | Path, seed: int = 7) -> dict[str, int]:
    """Write contracts, gold labels, playbook and fault plan under `out`."""
    out = Path(out)
    (out / "contracts").mkdir(parents=True, exist_ok=True)
    texts, gold, plan = build_dataset(seed)
    for doc_id, text in texts.items():
        (out / "contracts" / f"{doc_id}.txt").write_text(text, "utf-8")
    payload = {doc: g.model_dump() for doc, g in gold.items()}
    (out / "gold.json").write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", "utf-8")
    (out / "playbook.yaml").write_text(default_playbook_text(), "utf-8")
    plan.dump(out / "fault_plan.yaml")
    return {"contracts": len(texts), "labels": sum(len(g.labels) for g in gold.values())}


def load_gold(path: str | Path) -> dict[str, GoldContract]:
    raw = json.loads(Path(path).read_text("utf-8"))
    return {doc: GoldContract.model_validate(g) for doc, g in raw.items()}


__all__ = ["build_dataset", "write_dataset", "load_gold", "GoldContract", "GoldLabel"]
