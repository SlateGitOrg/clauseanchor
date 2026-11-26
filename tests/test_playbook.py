import pytest
from pydantic import ValidationError

from clauseanchor.playbook import ISSUE_ORDER, Issue


def test_default_playbook_has_the_eight_issues(playbook):
    assert tuple(playbook.issues) == ISSUE_ORDER
    assert {i.value_type for i in playbook.issues.values()} == {
        "months",
        "days",
        "hours",
        "enum",
        "bool",
    }


@pytest.mark.parametrize(
    ("issue", "value", "verdict"),
    [
        ("liability_cap_months", 24, "GREEN"),
        ("liability_cap_months", 12, "GREEN"),
        ("liability_cap_months", 9, "AMBER"),
        ("liability_cap_months", 3, "RED"),
        ("governing_law", "new york", "GREEN"),
        ("governing_law", "Ireland", "AMBER"),
        ("governing_law", "Texas", "RED"),
        ("auto_renewal_notice_days", 30, "GREEN"),
        ("auto_renewal_notice_days", 60, "AMBER"),
        ("auto_renewal_notice_days", 90, "RED"),
        ("payment_terms_days", 45, "GREEN"),
        ("payment_terms_days", 30, "AMBER"),
        ("payment_terms_days", 14, "RED"),
        ("breach_notice_hours", 72, "GREEN"),
        ("breach_notice_hours", 96, "AMBER"),
        ("breach_notice_hours", 168, "RED"),
        ("termination_for_convenience", True, "GREEN"),
        ("termination_for_convenience", False, "RED"),
        ("indemnity_ip", None, "RED"),
    ],
)
def test_verdicts(playbook, issue, value, verdict):
    assert playbook.verdict(issue, value) == verdict


def test_section_keywords_match_word_starts(playbook):
    cap = playbook.issues["liability_cap_months"]
    assert cap.allows("Limitation and Exclusion of Liability")
    assert cap.allows("Data Protection and Security")
    assert not cap.allows("Definitions and Interpretation")
    renewal = playbook.issues["auto_renewal_notice_days"]
    assert renewal.allows("Term, Renewal and Termination")
    assert not renewal.allows("Determinations")


def test_bool_issue_without_rules_is_rejected():
    with pytest.raises(ValidationError):
        Issue(
            title="x",
            value_type="bool",
            standard="x",
            hints=["x"],
            sections=["x"],
            pattern="x",
            positions={"GREEN": True},
        )
