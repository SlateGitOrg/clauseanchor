import json

from typer.testing import CliRunner

from clauseanchor.cli import app
from clauseanchor.evaluate import EvalResult, run_eval


def test_every_injected_fault_is_caught(eval_run):
    result, _, _ = eval_run
    assert result.faults["paraphrased_quote"] == {"injected": 40, "caught": 40}
    assert result.faults["definition_section"] == {"injected": 15, "caught": 15}
    assert result.faults["value_mismatch"] == {"injected": 20, "caught": 20}
    assert result.faults["missed_carveout"] == {"injected": 10, "caught": 10}
    assert result.false_flags == 0


def test_paraphrase_and_definition_issues_end_with_correct_verdicts(eval_run, plan, gold):
    _, reviews, _ = eval_run
    checked = 0
    for doc, per_issue in plan.faults.items():
        for issue, fault in per_issue.items():
            if fault.fault in ("paraphrased_quote", "definition_section"):
                res = reviews[doc].by_issue()[issue]
                assert res.reasked and res.status == "FOUND"
                assert res.verdict == gold[doc].labels[issue].verdict
                checked += 1
    assert checked == 55


def test_all_carve_outs_are_conflicts_with_the_overriding_value(eval_run, gold):
    _, reviews, _ = eval_run
    carve = [d for d, g in gold.items() if "carve_out" in g.labels["liability_cap_months"].tags]
    assert len(carve) == 20
    for doc in carve:
        res = reviews[doc].by_issue()["liability_cap_months"]
        label = gold[doc].labels["liability_cap_months"]
        assert "CONFLICT" in res.flags
        assert res.value == label.value and res.value != label.base_value
        assert res.conflict.base_value == label.base_value
        assert res.conflict.base.section != res.conflict.override.section


def test_fee_multiplier_caps_resolve_to_the_gold_months(eval_run, gold):
    _, reviews, _ = eval_run
    fees = [
        d for d, g in gold.items() if "fees_multiplier" in g.labels["liability_cap_months"].tags
    ]
    assert len(fees) == 25
    for doc in fees:
        assert (
            reviews[doc].by_issue()["liability_cap_months"].value
            == gold[doc].labels["liability_cap_months"].value
        )


def test_accepted_findings_slice_to_their_anchored_text(eval_run, dataset):
    result, reviews, _ = eval_run
    assert result.bad_offsets == 0
    from clauseanchor.anchor import normalize

    for doc, review in reviews.items():
        text = (dataset / "contracts" / f"{doc}.txt").read_text()
        for res in review.results:
            if res.anchor is None:
                continue
            assert text[res.anchor.start : res.anchor.end] == res.anchor.text
            assert res.status == "FOUND" and normalize(res.anchor.text)


def test_red_metrics_meet_targets_and_baseline_is_worse(eval_run):
    result, _, _ = eval_run
    t = result.total
    assert EvalResult.red_recall(t) >= 0.95 and EvalResult.red_precision(t) >= 0.90
    assert EvalResult.baseline_recall(t) < EvalResult.red_recall(t)
    assert t.needs_review == 0 and t.anchored == t.present == 864
    for c in result.issues.values():
        assert EvalResult.baseline_recall(c) < EvalResult.red_recall(c)


def test_eval_is_deterministic(dataset, eval_run):
    again, _, _ = run_eval(dataset)
    assert again.model_dump_json() == eval_run[0].model_dump_json()


def test_cli_seed_review_eval(tmp_path):
    runner = CliRunner()
    out = tmp_path / "d"
    assert runner.invoke(app, ["seed", "--out", str(out)]).exit_code == 0
    contract = next(iter(sorted((out / "contracts").glob("msa-0*.txt"))))
    res = runner.invoke(
        app,
        ["review", str(contract), "--playbook", str(out / "playbook.yaml"),
         "--fault-plan", str(out / "fault_plan.yaml")],
    )  # fmt: skip
    assert res.exit_code == 0 and res.output.startswith("# Contract review: msa-001")
    assert "| Issue | Verdict | Value | Quote | Section | Offsets | Flags |" in res.output
    res = runner.invoke(app, ["eval", "--data", str(out), "--out", str(tmp_path / "r")])
    assert res.exit_code == 0 and "caught 40 of 40" in res.output
    payload = json.loads((tmp_path / "r" / "eval.json").read_text())
    assert payload["faults"]["missed_carveout"]["caught"] == 10
