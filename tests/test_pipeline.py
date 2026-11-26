from clauseanchor.model import ModelError, Proposal
from clauseanchor.pipeline import review_text

TEXT = (
    "1. Limitation of Liability\n"
    "1.1 Supplier's aggregate liability shall not exceed twelve (12) months of the Fees.\n"
    "2. Fees and Payment\n"
    "2.1 Customer shall pay each invoice within thirty (30) days of receipt.\n"
    "3. Definitions\n"
    '3.1 "Fees" means the amounts payable by Customer.\n'
)
GOOD = "Supplier's aggregate liability shall not exceed twelve (12) months of the Fees"


class Scripted:
    """Returns queued proposals in order and records the feedback it was given."""

    def __init__(self, *proposals):
        self.queue = list(proposals)
        self.feedback = []

    def find(self, issue, clauses, feedback=None):
        self.feedback.append(feedback)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _review(playbook, model, issue="liability_cap_months"):
    only = playbook.model_copy(update={"issues": {issue: playbook.issues[issue]}})
    return review_text(TEXT, "t", only, model).results[0]


def test_correct_finding_is_anchored_and_graded(playbook):
    r = _review(playbook, Scripted(Proposal(value=12, quote=GOOD, section="1.1")))
    assert (r.status, r.verdict, r.value, r.flags) == ("FOUND", "GREEN", 12, [])
    assert TEXT[r.anchor.start : r.anchor.end] == GOOD
    assert r.anchor.section == "1.1"


def test_unanchored_quote_triggers_exactly_one_reask_with_feedback(playbook):
    model = Scripted(
        Proposal(value=12, quote="a made-up quote about the cap"), Proposal(value=12, quote=GOOD)
    )
    r = _review(playbook, model)
    assert r.flags == ["UNANCHORED"] and r.reasked
    assert r.first.anchor_status == "UNANCHORED"
    assert model.feedback[0] is None and "does not appear" in model.feedback[1]
    assert (r.status, r.verdict) == ("FOUND", "GREEN")


def test_wrong_section_is_caught_and_reasked(playbook):
    defn = 'Fees" means the amounts payable by Customer'
    model = Scripted(Proposal(value=12, quote=defn), Proposal(value=12, quote=GOOD))
    r = _review(playbook, model)
    assert r.flags == ["WRONG_SECTION"] and r.first.anchor_status == "WRONG_SECTION"
    assert r.verdict == "GREEN"


def test_second_failure_marks_the_issue_needs_review(playbook):
    bad = Proposal(value=12, quote="still invented")
    r = _review(playbook, Scripted(bad, bad))
    assert r.status == "NEEDS_REVIEW" and r.verdict is None
    assert r.flags == ["UNANCHORED", "UNANCHORED"]


def test_value_mismatch_parsed_value_wins(playbook):
    r = _review(playbook, Scripted(Proposal(value=36, quote=GOOD)))
    assert r.flags == ["VALUE_MISMATCH"]
    assert (r.value, r.verdict) == (12, "GREEN")
    assert r.first.value == 36


def test_model_that_finds_nothing_but_term_exists_is_rescued(playbook):
    r = _review(playbook, Scripted(Proposal()), issue="payment_terms_days")
    assert r.flags == ["MISSED_TERM"] and r.value == 30 and r.verdict == "AMBER"


def test_absent_term_is_missing_and_red(playbook):
    r = _review(playbook, Scripted(Proposal()), issue="governing_law")
    assert (r.status, r.verdict, r.anchor) == ("MISSING", "RED", None)


def test_model_errors_become_needs_review(playbook):
    r = _review(playbook, Scripted(ModelError("boom")))
    assert r.status == "NEEDS_REVIEW" and "boom" in r.note


def test_carve_out_in_another_clause_is_reported_even_if_the_model_missed_it(playbook):
    text = TEXT.replace(
        "2. Fees",
        "1.2 Notwithstanding Section 1.1, Supplier's liability shall not exceed "
        "three (3) months of the Fees.\n2. Fees",
    )
    only = playbook.model_copy(
        update={"issues": {"liability_cap_months": playbook.issues["liability_cap_months"]}}
    )
    r = review_text(text, "t", only, Scripted(Proposal(value=12, quote=GOOD))).results[0]
    assert r.flags == ["CONFLICT"]
    assert (r.value, r.verdict) == (3, "RED")
    assert (r.conflict.base.section, r.conflict.override.section) == ("1.1", "1.2")
    assert r.anchor == r.conflict.override


CAP_TWICE = (
    "1. Limitation of Liability\n"
    "1.1 Supplier's aggregate liability shall not exceed one and a half times the Fees paid "
    "in the preceding twelve (12) months.\n"
    "1.2 Notice periods: twelve (12) months before expiry, Supplier shall give a reminder.\n"
)


def _review_text(playbook, text, model, issue="liability_cap_months"):
    only = playbook.model_copy(update={"issues": {issue: playbook.issues[issue]}})
    return review_text(text, "t", only, model).results[0]


def test_partial_quote_cannot_downgrade_the_value(playbook):
    model = Scripted(Proposal(value=18, quote="twelve (12) months", section="1.1"))
    r = _review_text(playbook, CAP_TWICE, model)
    assert r.flags == []
    assert (r.value, r.verdict) == (18, "GREEN")
    assert r.anchor.text == "twelve (12) months"  # the anchor stays the evidence
    assert CAP_TWICE[r.anchor.start : r.anchor.end] == "twelve (12) months"


def test_partial_quote_still_flags_a_genuinely_wrong_value(playbook):
    model = Scripted(Proposal(value=3, quote="twelve (12) months", section="1.1"))
    r = _review_text(playbook, CAP_TWICE, model)
    assert r.flags == ["VALUE_MISMATCH"] and r.value == 18


def test_cited_section_selects_the_matching_occurrence(playbook):
    text = TEXT.replace(
        "2. Fees",
        "1.2 Supplier's aggregate liability for audits shall not exceed twelve (12) months "
        "of the Fees.\n2. Fees",
    )
    model = Scripted(Proposal(value=12, quote="twelve (12) months", section="1.2"))
    r = _review_text(playbook, text, model)
    assert r.flags == [] and r.anchor.section == "1.2"


def test_section_mismatch_is_flagged_and_reasked(playbook):
    model = Scripted(
        Proposal(value=12, quote=GOOD, section="2.1"),
        Proposal(value=12, quote=GOOD, section="1.1"),
    )
    r = _review(playbook, model)
    assert r.flags == ["SECTION_MISMATCH"] and r.reasked
    assert r.first.anchor_status == "SECTION_MISMATCH"
    assert "cited section 2.1" in model.feedback[1] and "section 1.1" in model.feedback[1]
    assert (r.status, r.verdict) == ("FOUND", "GREEN")


def test_section_mismatch_that_persists_needs_review(playbook):
    wrong = Proposal(value=12, quote=GOOD, section="2.1")
    r = _review(playbook, Scripted(wrong, wrong))
    assert r.status == "NEEDS_REVIEW"
    assert r.flags == ["SECTION_MISMATCH", "SECTION_MISMATCH"]


def test_citing_a_parent_section_is_accepted(playbook):
    r = _review(playbook, Scripted(Proposal(value=12, quote=GOOD, section="Section 1")))
    assert r.flags == []
