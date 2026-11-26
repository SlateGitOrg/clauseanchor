"""YAML playbook: the issues, how to find them, and how values map to verdicts."""

from __future__ import annotations

import re
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Verdict = Literal["GREEN", "AMBER", "RED"]
ValueType = Literal["months", "days", "hours", "enum", "bool"]

ISSUE_ORDER = (
    "liability_cap_months",
    "governing_law",
    "auto_renewal_notice_days",
    "payment_terms_days",
    "termination_for_convenience",
    "breach_notice_hours",
    "assignment_consent",
    "indemnity_ip",
)

_COMPARATORS = {
    "gte": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "lte": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}


class Rule(BaseModel):
    """One boolean reading rule: the first rule whose regex matches the span decides."""

    when: str
    value: bool


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = ""
    title: str
    value_type: ValueType
    standard: str
    hints: list[str]
    sections: list[str]
    pattern: str
    positions: dict[Verdict, Any]
    rules: list[Rule] = Field(default_factory=list)
    missing: Verdict = "RED"

    @model_validator(mode="after")
    def _check(self) -> Issue:
        re.compile(self.pattern)
        if self.value_type == "bool" and not self.rules:
            raise ValueError(f"bool issue {self.name or self.title!r} needs reading rules")
        return self

    @cached_property
    def regex(self) -> re.Pattern[str]:
        """Finds the sentence that states the term."""
        return re.compile(self.pattern, re.IGNORECASE | re.DOTALL)

    @cached_property
    def section_regex(self) -> re.Pattern[str]:
        keys = "|".join(re.escape(k) for k in self.sections)
        return re.compile(rf"\b(?:{keys})", re.IGNORECASE)

    def matches(self, sentence: str) -> bool:
        """True when the sentence states this term (line wraps are ignored)."""
        return self.regex.search(" ".join(sentence.split())) is not None

    def allows(self, heading: str) -> bool:
        """True when a section heading is one this issue may be anchored in."""
        return bool(heading) and self.section_regex.search(heading) is not None

    def verdict(self, value: Any) -> Verdict:
        """Map a parsed value to GREEN, AMBER or RED; a missing term uses `missing`."""
        if value is None:
            return self.missing
        for verdict in ("GREEN", "AMBER"):
            rule = self.positions.get(verdict)
            if rule is not None and _matches(rule, value):
                return verdict  # type: ignore[return-value]
        return "RED"

    def format_value(self, value: Any) -> str:
        if value is None:
            return "not found"
        if self.value_type == "bool":
            return "yes" if value else "no"
        if self.value_type in ("months", "days", "hours"):
            return f"{value} {self.value_type}"
        return str(value)


def _matches(rule: Any, value: Any) -> bool:
    if isinstance(rule, bool):
        return value is rule
    if isinstance(rule, list):
        return str(value).strip().lower() in {str(item).strip().lower() for item in rule}
    if isinstance(rule, dict):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        return all(_COMPARATORS[op](value, bound) for op, bound in rule.items())
    return False


class Playbook(BaseModel):
    version: int = 1
    issues: dict[str, Issue]

    @model_validator(mode="after")
    def _name_issues(self) -> Playbook:
        self.issues = {k: v.model_copy(update={"name": k}) for k, v in self.issues.items()}
        return self

    def verdict(self, name: str, value: Any) -> Verdict:
        return self.issues[name].verdict(value)


def load_playbook(path: str | Path | None = None) -> Playbook:
    """Load a playbook file, or the bundled default when no path is given."""
    if path is None:
        raw = resources.files("clauseanchor").joinpath("playbook.yaml").read_text("utf-8")
    else:
        raw = Path(path).read_text("utf-8")
    return Playbook.model_validate(yaml.safe_load(raw))


def default_playbook_text() -> str:
    return resources.files("clauseanchor").joinpath("playbook.yaml").read_text("utf-8")
