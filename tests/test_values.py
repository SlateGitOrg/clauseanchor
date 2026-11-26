import pytest

from clauseanchor.numwords import to_words, words_to_int
from clauseanchor.values import parse_value, same_value


@pytest.mark.parametrize(
    ("issue", "span", "expected"),
    [
        ("liability_cap_months", "twelve (12) months", 12),
        ("breach_notice_hours", "seventy-two (72) hours", 72),
        (
            "liability_cap_months",
            "one and a half times the Fees paid in the preceding twelve (12) months",
            18,
        ),
        ("auto_renewal_notice_days", "sixty (60) days' written notice", 60),
        ("liability_cap_months", "twice the Fees paid in the preceding six (6) months", 12),
        (
            "liability_cap_months",
            "one half (0.5) times the Fees paid or payable in the preceding eight (8) months",
            4,
        ),
        ("liability_cap_months", "the Fees paid in the 24 month period", 24),
        ("liability_cap_months", "an amount equal to one (1) year of Fees", 12),
        ("breach_notice_hours", "within seven (7) days of becoming aware", 168),
        ("payment_terms_days", "payable net 45 days from the invoice date", 45),
        ("payment_terms_days", "within thirty (30) days of receipt", 30),
        (
            "auto_renewal_notice_days",
            "renew for twelve (12) month periods unless 90 days' notice",
            90,
        ),
        ("liability_cap_months", "liability is excluded for fraud", None),
    ],
)
def test_numeric_values(playbook, issue, span, expected):
    assert parse_value(playbook.issues[issue], span) == expected


def test_value_parsing_ignores_line_wraps(playbook):
    span = "within seventy-two\n  (72) hours"
    assert parse_value(playbook.issues["breach_notice_hours"], span) == 72


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        ("governed by the laws of the State of New York, without regard to conflicts", "New York"),
        ("The laws of England and Wales govern this Agreement", "England and Wales"),
        ("governed by the laws of the Cayman Islands.", "Cayman Islands"),
    ],
)
def test_governing_law(playbook, span, expected):
    assert parse_value(playbook.issues["governing_law"], span) == expected


@pytest.mark.parametrize(
    ("issue", "span", "expected"),
    [
        ("termination_for_convenience", "Neither party may terminate for convenience.", False),
        ("termination_for_convenience", "Customer may terminate for convenience on notice", True),
        ("assignment_consent", "Neither party may assign this Agreement without consent", True),
        ("assignment_consent", "Supplier may assign this Agreement without consent", False),
        ("indemnity_ip", "Supplier shall defend and indemnify Customer for infringement", True),
        ("indemnity_ip", "Supplier has no obligation to indemnify for infringement", False),
    ],
)
def test_boolean_rules(playbook, issue, span, expected):
    assert parse_value(playbook.issues[issue], span) is expected


def test_number_words_round_trip():
    for n in (0, 7, 12, 19, 20, 45, 72, 99, 100, 120, 365):
        assert words_to_int(to_words(n)) == n
    assert words_to_int("one hundred and eighty") == 180
    assert words_to_int("banana") is None


def test_same_value_tolerates_types_and_case():
    assert same_value(18, 18.0)
    assert same_value("New York", "new york")
    assert not same_value(True, 1)
