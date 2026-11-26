"""Review models: the protocol, a deterministic fake with injectable faults, and an HTTP adapter."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import yaml
from pydantic import BaseModel

from .playbook import Issue
from .segment import Clause, split_sentences
from .values import parse_value

FaultKind = Literal["paraphrased_quote", "value_mismatch", "definition_section", "missed_carveout"]
FAULT_KINDS: tuple[FaultKind, ...] = (
    "paraphrased_quote",
    "value_mismatch",
    "definition_section",
    "missed_carveout",
)

_NOTWITHSTANDING = re.compile(r"\bnotwithstanding\b", re.IGNORECASE)


class ModelError(RuntimeError):
    """The model could not be reached or returned something unusable."""


class Proposal(BaseModel):
    """What a model reports for one issue: a value, the quote it rests on, and where."""

    value: Any = None
    quote: str | None = None
    section: str | None = None


class ReviewModel(Protocol):
    def find(
        self, issue: Issue, clauses: Sequence[Clause], feedback: str | None = None
    ) -> Proposal:
        """Propose a value and a verbatim quote. `feedback` is set on the one re-ask."""
        ...


class Fault(BaseModel):
    fault: FaultKind
    value: Any = None  # the wrong value, for value_mismatch


class FaultPlan(BaseModel):
    """Faults per (contract, issue). They only apply to a model's first attempt."""

    faults: dict[str, dict[str, Fault]] = {}

    def get(self, doc_id: str, issue: str) -> Fault | None:
        return self.faults.get(doc_id, {}).get(issue)

    def counts(self) -> dict[str, int]:
        totals = dict.fromkeys(FAULT_KINDS, 0)
        for per_issue in self.faults.values():
            for fault in per_issue.values():
                totals[fault.fault] += 1
        return totals

    @classmethod
    def load(cls, path: str | Path) -> FaultPlan:
        raw = yaml.safe_load(Path(path).read_text("utf-8")) or {}
        return cls(faults=raw)

    def dump(self, path: str | Path) -> None:
        payload = {
            doc: {issue: f.model_dump(exclude_none=True) for issue, f in per.items()}
            for doc, per in self.faults.items()
        }
        Path(path).write_text(yaml.safe_dump(payload, sort_keys=True), "utf-8")


_SWAPS = [
    (r"\bshall not exceed\b", "must not be greater than"),
    (r"\bshall be limited to\b", "is capped at"),
    (r"\bshall\b", "will"),
    (r"\baggregate\b", "total"),
    (r"\bwithin\b", "no later than"),
    (r"\bwritten notice\b", "notification in writing"),
    (r"\bnotify\b", "inform"),
    (r"\bagreement\b", "contract"),
    (r"\bAgreement\b", "contract"),
    (r"\bmay terminate\b", "is entitled to end"),
    (r"\bgoverned by\b", "subject to"),
    (r"\bassign\b", "pass on"),
]


def paraphrase(sentence: str) -> str:
    """Reword a sentence the way a summarising model does: same meaning, different words."""
    out = " ".join(sentence.split())
    for pattern, replacement in _SWAPS:
        out = re.sub(pattern, replacement, out)
    out = f"In summary, {out[0].lower()}{out[1:]}"
    if SequenceMatcher(None, " ".join(sentence.split()), out).ratio() > 0.85:
        out = f"{out} as the contract provides"
    return out


def _first_term(clause: Clause) -> str | None:
    m = re.search(r"[\"“]([A-Z][^\"”]{0,40})[\"”]", clause.body)
    return m.group(1) if m else None


class FakeReviewer:
    """Deterministic reviewer: first clause matching the issue's pattern, quoted verbatim.

    It reads the value the way a careful model would and prefers an overriding
    "notwithstanding" clause. A fault plan then breaks chosen first attempts the way real
    models break; re-asks (`feedback` set) are always clean.
    """

    def __init__(self, plan: FaultPlan | None = None) -> None:
        self.plan = plan or FaultPlan()

    def find(
        self, issue: Issue, clauses: Sequence[Clause], feedback: str | None = None
    ) -> Proposal:
        if not clauses:
            return Proposal()
        fault = None if feedback else self.plan.get(clauses[0].doc_id, issue.name)
        matches = self._matches(issue, clauses)
        if not matches:
            return Proposal()
        overriding = [m for m in matches if _NOTWITHSTANDING.search(m[1])]
        if fault and fault.fault == "missed_carveout":
            chosen = next((m for m in matches if m not in overriding), matches[0])
        else:
            chosen = overriding[0] if overriding else matches[0]
        clause, sentence, value = chosen
        quote = " ".join(sentence.split())
        proposal = Proposal(value=value, quote=quote, section=clause.number)
        if fault is None:
            return proposal
        if fault.fault == "paraphrased_quote":
            proposal.quote = paraphrase(sentence)
        elif fault.fault == "value_mismatch":
            proposal.value = fault.value
        elif fault.fault == "definition_section":
            definition = self._definition(clauses, clause)
            if definition is not None:
                body = definition.body
                s, e = split_sentences(body)[0]
                proposal.quote = " ".join(body[s:e].split())
                proposal.section = definition.number
        return proposal

    @staticmethod
    def _matches(issue: Issue, clauses: Sequence[Clause]) -> list[tuple[Clause, str, Any]]:
        found = []
        for clause in clauses:
            if not issue.allows(clause.section):
                continue
            body = clause.body
            for s, e in split_sentences(body):
                sentence = body[s:e]
                if issue.matches(sentence):
                    value = parse_value(issue, sentence)
                    if value is not None:
                        found.append((clause, sentence, value))
                        break
        return found

    @staticmethod
    def _definition(clauses: Sequence[Clause], operative: Clause) -> Clause | None:
        definitions = [c for c in clauses if re.search(r"\bdefinition", c.section, re.IGNORECASE)]
        for candidate in definitions:
            term = _first_term(candidate)
            if term and re.search(rf"\b{re.escape(term)}\b", operative.body):
                return candidate
        return None


class OpenAICompatModel:
    """Any OpenAI-compatible chat-completions endpoint, configured through the environment."""

    ENV_BASE_URL = "CLAUSEANCHOR_LLM_BASE_URL"
    ENV_API_KEY = "CLAUSEANCHOR_LLM_API_KEY"
    ENV_MODEL = "CLAUSEANCHOR_LLM_MODEL"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, client: httpx.Client | None = None
    ) -> OpenAICompatModel:
        env = os.environ if env is None else env
        missing = [k for k in (cls.ENV_BASE_URL, cls.ENV_API_KEY, cls.ENV_MODEL) if not env.get(k)]
        if missing:
            raise ModelError(f"set {', '.join(missing)} to use the OpenAI-compatible model")
        return cls(env[cls.ENV_BASE_URL], env[cls.ENV_API_KEY], env[cls.ENV_MODEL], client=client)

    def find(
        self, issue: Issue, clauses: Sequence[Clause], feedback: str | None = None
    ) -> Proposal:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _user_prompt(issue, clauses, feedback)},
            ],
        }
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(_strip_fence(content))
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ModelError(f"model call failed: {exc}") from exc
        if not isinstance(data, dict):
            raise ModelError("model reply was not a JSON object")
        return Proposal(
            value=data.get("value"), quote=data.get("quote"), section=_as_text(data.get("section"))
        )


_SYSTEM = (
    "You review a contract against one playbook issue. Reply with a JSON object "
    '{"value": ..., "quote": "...", "section": "..."}. The quote must be copied word for word '
    "from the clause that states the term, never paraphrased and never taken from the "
    "definitions. If an overriding clause (for example one beginning 'Notwithstanding') "
    "changes the value, use that clause. If the contract does not state the term, reply "
    'with {"value": null, "quote": null, "section": null}.'
)


def _user_prompt(issue: Issue, clauses: Sequence[Clause], feedback: str | None) -> str:
    lines = [
        f"Issue: {issue.title} ({issue.value_type}). Playbook standard: {issue.standard}.",
        f"Look in sections about: {', '.join(issue.sections)}.",
        "Clauses:",
    ]
    for clause in clauses:
        lines.append(f"[{clause.number}] ({clause.section}) {' '.join(clause.body.split())}")
    if feedback:
        lines.append(f"Correction: {feedback}")
    return "\n".join(lines)


def _strip_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    return text


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)
