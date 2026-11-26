from clauseanchor.model import FakeReviewer, FaultPlan
from clauseanchor.pipeline import review_text
from clauseanchor.report import render_review

LONG = (
    "1. Limitation of Liability\n"
    "1.1 Subject to Section 3.1, the aggregate liability of Supplier arising out of or in "
    "connection with this Agreement, whether in contract, tort (including negligence) or "
    "otherwise, shall not exceed an amount equal to the Fees paid or payable in the "
    "twenty-four (24) months preceding the event giving rise to the claim.\n"
    "2. Data Protection\n"
    "2.1 Notwithstanding Section 1.1, the total liability of Supplier for every claim and "
    "every loss of whatever kind relating to Customer Data, including any Security Incident, "
    "shall not exceed six (6) months of the Fees.\n"
)


def _report(playbook):
    only = playbook.model_copy(
        update={"issues": {"liability_cap_months": playbook.issues["liability_cap_months"]}}
    )
    plan = FaultPlan.model_validate(
        {"faults": {"t": {"liability_cap_months": {"fault": "missed_carveout"}}}}
    )
    return render_review(review_text(LONG, "t", only, FakeReviewer(plan)), only)


def test_conflict_anchors_are_printed_in_full(playbook):
    report = _report(playbook)
    base = " ".join(LONG.split("1.1 ", 1)[1].split("\n2.")[0].split())
    override = " ".join(LONG.split("2.1 ", 1)[1].split())
    assert len(base) > 150 and len(override) > 150
    assert f'"{base[: base.rindex(".")]}"' in report
    assert f'"{override[: override.rindex(".")]}"' in report
    assert "…" not in report.split("## Details")[1]


def test_table_cell_is_truncated_but_details_hold_the_full_text(playbook):
    only = playbook.model_copy(
        update={"issues": {"liability_cap_months": playbook.issues["liability_cap_months"]}}
    )
    text = LONG.split("2. Data")[0]
    report = render_review(review_text(text, "t", only, FakeReviewer()), only)
    table, details = report.split("## Details")
    assert "…" in table
    assert "giving rise to the claim" in details
    assert "giving rise to the claim" not in table
