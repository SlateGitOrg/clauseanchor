from clauseanchor.assess import find_conflict, scan
from clauseanchor.segment import segment


def test_notwithstanding_clause_overrides_the_base_cap(playbook, sample_text):
    contract = segment(sample_text, "doc")
    issue = playbook.issues["liability_cap_months"]
    touches = scan(contract, issue)
    assert [(t.clause.number, t.value) for t in touches] == [("2.1", 24), ("2.3", 6)]
    conflict = find_conflict(touches)
    assert (conflict.base_value, conflict.override_value) == (24, 6)
    assert conflict.base.section == "2.1" and conflict.override.section == "2.3"
    for span in (conflict.base, conflict.override):
        assert sample_text[span.start : span.end] == span.text


def test_subject_to_direction_makes_the_referenced_clause_win(playbook):
    text = (
        "1. Liability\n"
        "1.1 Subject to Section 1.2, liability shall not exceed twelve (12) months of Fees.\n"
        "1.2 Liability for data loss shall not exceed three (3) months of Fees.\n"
    )
    contract = segment(text, "d")
    conflict = find_conflict(scan(contract, playbook.issues["liability_cap_months"]))
    assert (conflict.base.section, conflict.override.section) == ("1.1", "1.2")
    assert conflict.override_value == 3


def test_notwithstanding_without_a_value_is_not_a_conflict(playbook):
    text = (
        "1. Liability\n"
        "1.1 Liability shall not exceed twelve (12) months of Fees.\n"
        "1.2 Notwithstanding Section 1.1, nothing limits liability for fraud.\n"
    )
    touches = scan(segment(text, "d"), playbook.issues["liability_cap_months"])
    assert len(touches) == 1
    assert find_conflict(touches) is None


def test_override_with_the_same_value_is_not_a_conflict(playbook):
    text = (
        "1. Liability\n"
        "1.1 Liability shall not exceed twelve (12) months of Fees.\n"
        "1.2 Notwithstanding Section 1.1, liability shall not exceed one (1) year of Fees.\n"
    )
    assert find_conflict(scan(segment(text, "d"), playbook.issues["liability_cap_months"])) is None


def test_scan_ignores_sections_the_issue_does_not_allow(playbook):
    text = "1. Definitions\n1.1 Liability shall not exceed twelve (12) months of Fees.\n"
    assert scan(segment(text, "d"), playbook.issues["liability_cap_months"]) == []
