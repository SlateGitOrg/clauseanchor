import json
from collections import Counter

from clauseanchor.model import FaultPlan
from clauseanchor.seed import write_dataset
from clauseanchor.segment import segment


def test_dataset_shape(dataset, gold):
    assert len(list((dataset / "contracts").glob("*.txt"))) == 120
    assert Counter(g.doc_type for g in gold.values()) == {"msa": 70, "dpa": 50}
    assert sum(len(g.labels) for g in gold.values()) == 960


def test_verdict_mix_and_missing_share(gold):
    labels = [lab for g in gold.values() for lab in g.labels.values()]
    verdicts = Counter(lab.verdict for lab in labels)
    assert verdicts["RED"] == 336 and verdicts["AMBER"] == 145 and verdicts["GREEN"] == 479
    missing = [lab for lab in labels if not lab.present]
    assert len(missing) == 96 and all(lab.verdict == "RED" for lab in missing)


def test_planted_carve_outs_and_fee_multipliers(gold):
    caps = [g.labels["liability_cap_months"] for g in gold.values()]
    carve = [c for c in caps if "carve_out" in c.tags]
    fees = [c for c in caps if "fees_multiplier" in c.tags]
    assert len(carve) == 20 and len(fees) == 25
    assert all(c.base_value >= 12 and c.value < c.base_value for c in carve)
    assert all(c.verdict != "GREEN" for c in carve)


def test_carve_out_text_lives_in_a_different_section_from_the_cap(dataset, gold):
    doc = next(d for d, g in gold.items() if "carve_out" in g.labels["liability_cap_months"].tags)
    contract = segment((dataset / "contracts" / f"{doc}.txt").read_text(), doc)
    notwithstanding = [c for c in contract.clauses if "Notwithstanding Section" in c.body]
    caps = [c for c in contract.clauses if "liability" in c.body and "months" in c.body]
    assert notwithstanding and caps
    override = notwithstanding[0]
    base = next(c for c in caps if c is not override)
    assert override.section != base.section


def test_numbering_styles_vary(dataset):
    texts = [p.read_text() for p in (dataset / "contracts").glob("*.txt")]
    assert any("ARTICLE 1" in t for t in texts) and any("\n1. " in t for t in texts)
    assert any("(a)" in t for t in texts) and any("“" in t for t in texts)
    assert any("\n    (a)" in t for t in texts)  # indented sub-clauses
    assert max(len(line) for t in texts for line in t.splitlines()) > 150  # unwrapped contracts
    assert any(max(len(line) for line in t.splitlines()) <= 92 for t in texts)  # wrapped ones


def test_fault_plan_counts_and_placement(plan, gold):
    assert plan.counts() == {
        "paraphrased_quote": 40,
        "value_mismatch": 20,
        "definition_section": 15,
        "missed_carveout": 10,
    }
    from clauseanchor.playbook import load_playbook

    pb = load_playbook()
    for doc, per_issue in plan.faults.items():
        for issue, fault in per_issue.items():
            label = gold[doc].labels[issue]
            assert label.present
            if fault.fault == "value_mismatch":
                assert pb.verdict(issue, fault.value) != label.verdict  # trusting it flips
            if fault.fault == "missed_carveout":
                assert pb.verdict(issue, label.base_value) != label.verdict


def test_same_seed_is_identical_and_other_seed_differs(tmp_path):
    write_dataset(tmp_path / "a", seed=3)
    write_dataset(tmp_path / "b", seed=3)
    write_dataset(tmp_path / "c", seed=4)
    for name in ("gold.json", "fault_plan.yaml", "contracts/msa-001.txt", "contracts/dpa-050.txt"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert (tmp_path / "a/contracts/msa-001.txt").read_text() != (
        tmp_path / "c/contracts/msa-001.txt"
    ).read_text()
    assert FaultPlan.load(tmp_path / "a/fault_plan.yaml") == FaultPlan.load(
        tmp_path / "b/fault_plan.yaml"
    )
    assert json.loads((tmp_path / "a/gold.json").read_text())["msa-001"]["doc_type"] == "msa"
