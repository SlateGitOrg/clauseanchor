from clauseanchor.segment import segment, split_sentences


def test_tree_numbers_and_levels(sample_text):
    c = segment(sample_text, "doc")
    numbers = [(x.number, x.level) for x in c.clauses]
    assert numbers == [
        ("1", 1),
        ("1.1", 2),
        ("1.1(a)", 3),
        ("1.1(b)", 3),
        ("1.1(c)", 3),
        ("2", 1),
        ("2.1", 2),
        ("2.2", 2),
        ("2.2(a)", 3),
        ("2.2(b)", 3),
        ("2.2(b)(i)", 4),
        ("2.2(b)(ii)", 4),
        ("2.2(c)", 3),
        ("2.3", 2),
    ]
    assert c.by_number["2.2(b)(ii)"].parent == "2.2(b)"
    assert c.by_number["2.2(b)"].children == ["2.2(b)(i)", "2.2(b)(ii)"]
    assert c.by_number["2.1"].section == "Limitation of Liability"


def test_offsets_slice_back_to_exact_text(sample_text):
    c = segment(sample_text, "doc")
    for clause in c.clauses:
        assert sample_text[clause.start : clause.end] == clause.text
    two_one = c.by_number["2.1"]
    assert two_one.text.startswith("2.1 Subject to Section 2.3")
    assert "\n" in two_one.text  # the wrapped continuation line belongs to the clause
    assert two_one.text.endswith("of the Fees.")


def test_signature_block_after_blank_line_is_not_a_clause(sample_text):
    c = segment(sample_text, "doc")
    assert "WITNESS" not in c.by_number["2.3"].text


def test_defined_terms_and_cross_references(sample_text):
    c = segment(sample_text, "doc")
    assert set(c.definitions) == {"Fees", "Security Incident", "Initial Term"}
    assert c.definitions["Fees"].number == "1.1(a)"
    assert c.xrefs == {"2.1": ["2.3"], "2.3": ["2.1"]}
    assert c.used_terms(c.by_number["2.1"]) == ["Fees"]


def test_letter_i_after_h_is_a_letter_not_a_roman_numeral():
    items = "".join(f"({ch}) item {ch};\n" for ch in "abcdefghi")
    c = segment(f"1. Lists\n1.1 Lead:\n{items}", "doc")
    assert c.by_number["1.1(i)"].level == 3
    assert "1.1(h)(i)" not in c.by_number


def test_article_style_and_indented_sub_clauses():
    text = "ARTICLE 3 – FEES AND PAYMENT\n3.1 Pay.\n    (a) first\n        (i) deep\n"
    c = segment(text, "doc")
    assert [x.number for x in c.clauses] == ["3", "3.1", "3.1(a)", "3.1(a)(i)"]
    assert c.by_number["3"].heading == "FEES AND PAYMENT"
    assert text[c.by_number["3.1(a)"].start :].startswith("(a) first")


def test_clause_at_and_top_of(sample_text):
    c = segment(sample_text, "doc")
    offset = sample_text.index("seventy-two")
    clause = c.clause_at(offset)
    assert clause.number == "2.2(a)"
    assert c.top_of(clause).heading == "Limitation of Liability"
    assert c.clause_at(0) is None  # title line is not part of any clause


def test_split_sentences_trims_list_punctuation():
    text = "Pay within 30 days. Late fees apply; and see Section 9.1. Last item;"
    spans = split_sentences(text)
    assert [text[s:e] for s, e in spans] == [
        "Pay within 30 days",
        "Late fees apply; and see Section 9.1",
        "Last item",
    ]


def test_sentence_context_widens_a_partial_span_to_its_sentence(sample_text):
    c = segment(sample_text, "doc")
    start = sample_text.index("twenty-four (24) months")
    context = c.sentence_context(start, start + len("twenty-four (24) months"))
    assert context.startswith("Subject to Section 2.3")  # clause marker excluded
    assert context.endswith("of the Fees")
    assert context in sample_text
    assert c.sentence_context(0, 5) == sample_text[0:5]  # outside any clause
