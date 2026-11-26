"""Result types shared by the pipeline, the report and the evaluation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .playbook import Verdict

Status = Literal["FOUND", "MISSING", "NEEDS_REVIEW"]
Flag = Literal[
    "UNANCHORED",
    "WRONG_SECTION",
    "SECTION_MISMATCH",
    "VALUE_MISMATCH",
    "CONFLICT",
    "FUZZY",
    "MISSED_TERM",
    "UNPARSEABLE",
]


class Span(BaseModel):
    """A verbatim stretch of the contract: `text` is always `contract[start:end]`."""

    section: str
    start: int
    end: int
    text: str
    mode: str | None = None


class Conflict(BaseModel):
    """An overriding clause that changes the value the base clause states."""

    base: Span
    base_value: Any
    override: Span
    override_value: Any


class FirstAttempt(BaseModel):
    """The model's first proposal and how it fared, kept for the trust-model baseline."""

    value: Any = None
    quote: str | None = None
    anchor_status: str = (
        "NOT_FOUND"  # ANCHORED, UNANCHORED, WRONG_SECTION, SECTION_MISMATCH or NOT_FOUND
    )


class IssueResult(BaseModel):
    issue: str
    status: Status
    verdict: Verdict | None = None
    value: Any = None
    anchor: Span | None = None
    flags: list[Flag] = Field(default_factory=list)
    reasked: bool = False
    conflict: Conflict | None = None
    first: FirstAttempt = Field(default_factory=FirstAttempt)
    note: str = ""


class ContractReview(BaseModel):
    doc_id: str
    results: list[IssueResult]

    def by_issue(self) -> dict[str, IssueResult]:
        return {r.issue: r for r in self.results}
