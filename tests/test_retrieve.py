from clauseanchor.retrieve import BM25, Retriever, tokenize
from clauseanchor.segment import segment


def test_bm25_ranks_the_matching_document_first_and_idf_is_rare_weighted():
    docs = [tokenize(t) for t in ["liability cap months fees", "payment invoice days", "law"]]
    bm = BM25(docs)
    scores = bm.scores(tokenize("liability cap"))
    assert scores.argmax() == 0
    assert scores[1] == 0 and scores[2] == 0
    assert bm.idf("law") > 0
    assert bm.idf("liability") == bm.idf("payment")  # both appear in one document of three


def test_bm25_length_normalisation_prefers_the_shorter_document():
    short, long = tokenize("cap fees"), tokenize("cap fees " + "filler " * 40)
    scores = BM25([short, long]).scores(tokenize("cap"))
    assert scores[0] > scores[1]


def test_stemming_joins_inflections():
    assert tokenize("renews renewed renewing")[0] == tokenize("renew")[0]
    assert tokenize("months") == tokenize("month")
    assert tokenize("the and of") == []  # stop words are dropped


def test_retrieval_adds_cross_references_and_definitions(playbook, sample_text):
    contract = segment(sample_text, "doc")
    hits = Retriever(contract, top_k=1).retrieve(playbook.issues["liability_cap_months"])
    numbers = [(h.clause.number, h.reason) for h in hits]
    assert numbers[0][1] == "bm25"
    reasons = dict(numbers)
    assert reasons["2.3"] == "xref" or reasons["2.3"] == "bm25"
    assert reasons["1.1(a)"] == "definition"  # "Fees" is used by the candidate


def test_top_k_limits_primary_hits(playbook, sample_text):
    contract = segment(sample_text, "doc")
    hits = Retriever(contract, top_k=3).retrieve(playbook.issues["breach_notice_hours"])
    assert sum(h.reason == "bm25" for h in hits) == 3
