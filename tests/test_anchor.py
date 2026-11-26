import pytest

from clauseanchor.anchor import Anchorer, fuzzy_find, normalize
from clauseanchor.segment import segment

QUOTE = (
    "Supplier's aggregate liability under this Agreement shall not exceed twenty-four (24) months"
)


@pytest.fixture
def doc(playbook):
    text = (
        "1. Definitions\n"
        "1.1 “Fees” means the amounts payable by Customer under each Order Form.\n"
        "2. Limitation of Liability\n"
        "2.1 Subject to Section 2.3, Supplier's aggregate liability under this Agreement\n"
        "shall not exceed twenty-four (24) months of the Fees.\n"
        "2.2 Customer shall pay each invoice within thirty (30) days.\n"
    )
    contract = segment(text, "doc")
    return text, Anchorer(contract), playbook.issues["liability_cap_months"]


def test_exact_match_returns_offsets_that_slice_to_the_quote(doc):
    text, anchorer, issue = doc
    quote = "shall not exceed twenty-four (24) months of the Fees"
    r = anchorer.locate(quote, issue)
    assert (r.status, r.mode, r.clause) == ("ANCHORED", "exact", "2.1")
    assert text[r.start : r.end] == quote


def test_whitespace_variant_anchors_with_original_offsets(doc):
    text, anchorer, issue = doc
    r = anchorer.locate(QUOTE, issue)  # the document has a newline inside this sentence
    assert (r.status, r.mode) == ("ANCHORED", "normalized")
    assert text[r.start : r.end].replace("\n", " ") == QUOTE
    assert text[r.start : r.end].endswith("(24) months")


def test_curly_quotes_case_and_dashes_anchor(doc):
    text, anchorer, issue = doc
    r = anchorer.locate("Supplier’s AGGREGATE liability under this Agreement", issue)
    assert r.ok and r.mode == "normalized"
    assert text[r.start : r.end] == "Supplier's aggregate liability under this Agreement"
    r2 = anchorer.locate("twenty–four (24) months", issue)
    assert r2.ok and text[r2.start : r2.end] == "twenty-four (24) months"


def test_end_of_line_hyphenation_is_undone():
    text = "2. Limitation of Liability\n2.1 The aggregate liabil-\nity of Supplier is limited.\n"
    contract = segment(text, "d")
    from clauseanchor.playbook import load_playbook

    issue = load_playbook().issues["liability_cap_months"]
    r = Anchorer(contract).locate("The aggregate liability of Supplier is limited", issue)
    assert r.ok and r.mode == "normalized"
    assert text[r.start : r.end].startswith("The aggregate liabil-\nity")


def test_paraphrase_is_unanchored(doc):
    _, anchorer, issue = doc
    r = anchorer.locate(
        "In summary, the supplier's total liability must not be greater than 24 months", issue
    )
    assert r.status == "UNANCHORED"
    assert r.start == -1


def test_quote_in_a_disallowed_section_is_wrong_section(doc):
    text, anchorer, issue = doc
    quote = "“Fees” means the amounts payable by Customer under each Order Form"
    r = anchorer.locate(quote, issue)
    assert r.status == "WRONG_SECTION"
    assert r.section == "Definitions"
    assert text[r.start : r.end] == quote


def test_fuzzy_match_with_a_typo_is_flagged(doc):
    text, anchorer, issue = doc
    r = anchorer.locate("shall not exceed twenty-four (24) monhts of the Fees", issue)
    assert (r.status, r.mode) == ("ANCHORED", "fuzzy")
    assert r.ratio >= 0.97
    assert text[r.start : r.end] == "shall not exceed twenty-four (24) months of the Fees"


def test_fuzzy_threshold_rejects_a_moderate_rewrite():
    haystack = "the supplier shall provide the services with reasonable skill and care at all times"
    assert (
        fuzzy_find(
            "the supplier shall deliver the services with reasonable skill and care", haystack
        )
        is None
    )
    near = fuzzy_find(
        "the supplier shall provide the services with reasonable skill and cares", haystack
    )
    assert near is not None and near[2] >= 0.97


def test_repeated_quote_prefers_the_allowed_section(playbook):
    text = (
        "1. Definitions\n1.1 Liability shall not exceed twelve (12) months of Fees.\n"
        "2. Limitation of Liability\n2.1 Liability shall not exceed twelve (12) months of Fees.\n"
    )
    anchorer = Anchorer(segment(text, "d"))
    r = anchorer.locate(
        "Liability shall not exceed twelve (12) months of Fees",
        playbook.issues["liability_cap_months"],
    )
    assert r.ok and r.clause == "2.1"


def test_empty_quote_is_unanchored(doc):
    assert doc[1].locate("   ", doc[2]).status == "UNANCHORED"


def test_normalize_collapses_whitespace_and_case():
    assert normalize("  A  B\n\tC ") == "a b c"


def test_section_matches_accepts_the_clause_and_its_ancestors(doc):
    from clauseanchor.anchor import section_matches

    contract = doc[1].contract
    assert section_matches(contract, "2.1", "2.1")
    assert section_matches(contract, "Section 2", "2.1")
    assert not section_matches(contract, "2.2", "2.1")
    assert not section_matches(contract, None, "2.1")
