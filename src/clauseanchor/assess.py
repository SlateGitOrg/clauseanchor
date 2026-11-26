"""Verdicts, and the model-independent scan for overriding clauses.

A clause that says "notwithstanding ..." overrides what it refers to; a clause that says
"subject to Section N" yields to Section N. The scan reads every clause in the issue's
allowed sections, so a carve-out is found even when the model never looked at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .playbook import Issue
from .results import Conflict, Span
from .segment import XREF, Clause, Contract, split_sentences
from .values import parse_value, same_value

_NOTWITHSTANDING = re.compile(r"\bnotwithstanding\b", re.IGNORECASE)
_SUBJECT_TO = re.compile(
    r"\bsubject to\s+(?:Sections?|Clauses?|Articles?)\s+(?P<ref>\d+(?:\.\d+)*(?:\([a-z]{1,4}\))*)",
    re.IGNORECASE,
)
_REF = re.compile(r"\d+(?:\.\d+)*(?:\([a-z]{1,4}\))*")


@dataclass(frozen=True)
class Touch:
    """A sentence in an allowed section that states the issue's value."""

    clause: Clause
    start: int
    end: int
    value: Any
    text: str

    def span(self, mode: str | None = "exact") -> Span:
        return Span(
            section=self.clause.number, start=self.start, end=self.end, text=self.text, mode=mode
        )


def scan(contract: Contract, issue: Issue) -> list[Touch]:
    """Every sentence in an allowed section that matches the issue and yields a value."""
    touches = []
    for clause in contract.clauses:
        if not issue.allows(clause.section):
            continue
        body = clause.body
        for s, e in split_sentences(body):
            sentence = body[s:e]
            if not issue.matches(sentence):
                continue
            value = parse_value(issue, sentence)
            if value is not None:
                start = clause.body_start + s
                touches.append(Touch(clause, start, clause.body_start + e, value, sentence))
    return touches


def _within(clause: Clause, number: str) -> bool:
    return clause.number == number or clause.number.startswith((f"{number}.", f"{number}("))


def find_conflict(touches: list[Touch], finding_offset: int | None = None) -> Conflict | None:
    """Return the CONFLICT between an overriding clause and the clause it overrides."""
    overriders: list[Touch] = [t for t in touches if _NOTWITHSTANDING.search(t.text)]
    for touch in touches:
        for m in _SUBJECT_TO.finditer(touch.text):
            for other in touches:
                if _within(other.clause, m.group("ref")) and other not in overriders:
                    overriders.append(other)
    if not overriders:
        return None
    overriders.sort(key=lambda t: t.start)
    override = overriders[0]
    bases = [t for t in touches if t not in overriders]
    if not bases:
        return None
    referenced = {r for m in XREF.finditer(override.text) for r in _REF.findall(m.group("refs"))}
    yielding = [
        t
        for t in bases
        for m in _SUBJECT_TO.finditer(t.text)
        if _within(override.clause, m.group("ref"))
    ]
    ordered = [
        *[t for t in bases if any(_within(t.clause, r) for r in referenced)],
        *yielding,
        *[t for t in bases if finding_offset is not None and t.start <= finding_offset < t.end],
        *bases,
    ]
    base = ordered[0]
    if same_value(base.value, override.value):
        return None
    return Conflict(
        base=base.span(),
        base_value=base.value,
        override=override.span(),
        override_value=override.value,
    )
