import json

import httpx
import pytest

from clauseanchor.anchor import Anchorer
from clauseanchor.model import (
    FakeReviewer,
    FaultPlan,
    ModelError,
    OpenAICompatModel,
    Proposal,
    paraphrase,
)
from clauseanchor.retrieve import Retriever
from clauseanchor.segment import segment


def _clauses(playbook, text, issue):
    contract = segment(text, "doc")
    return contract, [h.clause for h in Retriever(contract).retrieve(playbook.issues[issue])]


def _plan(kind, **kw):
    return FaultPlan.model_validate(
        {"faults": {"doc": {"liability_cap_months": {"fault": kind, **kw}}}}
    )


def test_clean_fake_quotes_the_overriding_clause_verbatim(playbook, sample_text):
    contract, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    p = FakeReviewer().find(playbook.issues["liability_cap_months"], clauses)
    assert (p.value, p.section) == (6, "2.3")
    assert " ".join(sample_text.split()).count(p.quote) == 1


def test_missed_carveout_returns_the_base_clause(playbook, sample_text):
    _, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    p = FakeReviewer(_plan("missed_carveout")).find(
        playbook.issues["liability_cap_months"], clauses
    )
    assert (p.value, p.section) == (24, "2.1")


def test_value_mismatch_keeps_the_quote_but_changes_the_value(playbook, sample_text):
    _, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    issue = playbook.issues["liability_cap_months"]
    clean = FakeReviewer().find(issue, clauses)
    bad = FakeReviewer(_plan("value_mismatch", value=36)).find(issue, clauses)
    assert bad.quote == clean.quote and bad.value == 36


def test_paraphrased_quote_does_not_anchor(playbook, sample_text):
    contract, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    issue = playbook.issues["liability_cap_months"]
    p = FakeReviewer(_plan("paraphrased_quote")).find(issue, clauses)
    assert Anchorer(contract).locate(p.quote, issue).status == "UNANCHORED"


def test_definition_fault_quotes_the_definitions_clause(playbook, sample_text):
    contract, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    issue = playbook.issues["liability_cap_months"]
    p = FakeReviewer(_plan("definition_section")).find(issue, clauses)
    assert p.section == "1.1(a)" and p.value == 6
    assert Anchorer(contract).locate(p.quote, issue).status == "WRONG_SECTION"


def test_faults_apply_to_first_attempts_only(playbook, sample_text):
    _, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    issue = playbook.issues["liability_cap_months"]
    fake = FakeReviewer(_plan("value_mismatch", value=36))
    assert fake.find(issue, clauses, feedback="try again").value == 6


def test_fake_reports_nothing_when_no_clause_states_the_term(playbook, sample_text):
    _, clauses = _clauses(playbook, sample_text, "governing_law")
    assert FakeReviewer().find(playbook.issues["governing_law"], clauses) == Proposal()


def test_paraphrase_is_always_far_from_the_original():
    from difflib import SequenceMatcher

    s = "Provider shall notify Client within forty-eight (48) hours of any Security Incident"
    assert SequenceMatcher(None, s, paraphrase(s)).ratio() < 0.85


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compat_posts_a_chat_request_and_parses_json(playbook, sample_text):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        reply = '```json\n{"value": 6, "quote": "q", "section": "2.3"}\n```'
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    model = OpenAICompatModel("https://llm.example/v1/", "k", "m", client=_client(handler))
    _, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    p = model.find(playbook.issues["liability_cap_months"], clauses, feedback="fix it")
    assert p == Proposal(value=6, quote="q", section="2.3")
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer k" and seen["body"]["model"] == "m"
    assert "fix it" in seen["body"]["messages"][1]["content"]
    assert "[2.3]" in seen["body"]["messages"][1]["content"]


def test_openai_compat_errors_become_model_errors(playbook, sample_text):
    _, clauses = _clauses(playbook, sample_text, "liability_cap_months")
    issue = playbook.issues["liability_cap_months"]
    down = OpenAICompatModel("http://x", "k", "m", client=_client(lambda r: httpx.Response(500)))
    with pytest.raises(ModelError):
        down.find(issue, clauses)
    junk = OpenAICompatModel(
        "http://x",
        "k",
        "m",
        client=_client(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no"}}]})
        ),
    )
    with pytest.raises(ModelError):
        junk.find(issue, clauses)


def test_from_env_reads_the_three_variables_and_complains_when_missing():
    env = {
        "CLAUSEANCHOR_LLM_BASE_URL": "http://h/v1",
        "CLAUSEANCHOR_LLM_API_KEY": "secret",
        "CLAUSEANCHOR_LLM_MODEL": "small",
    }
    model = OpenAICompatModel.from_env(env)
    assert (model.base_url, model.api_key, model.model) == ("http://h/v1", "secret", "small")
    with pytest.raises(ModelError, match="CLAUSEANCHOR_LLM_MODEL"):
        OpenAICompatModel.from_env({k: v for k, v in env.items() if "MODEL" not in k})
