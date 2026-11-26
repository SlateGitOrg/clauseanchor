"""Parse an issue's value out of the anchored span itself.

The model's own stated value is never used here: whatever it claims, the value is read
again from the exact words of the contract.
"""

from __future__ import annotations

import re
from typing import Any

from .numwords import WORDS, words_to_int
from .playbook import Issue

_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?P<unit>months?|days?|hours?|weeks?|years?)\b"

# "twelve (12) months", "12 months", "ninety days"
_QTY = re.compile(
    rf"(?:(?P<w1>{WORDS})\s*\(\s*(?P<d1>{_NUM})\s*\)|(?P<d2>{_NUM})|(?P<w2>{WORDS}))"
    rf"\s*-?\s*{_UNIT}",
    re.IGNORECASE,
)

# "one and a half (1.5) times the Fees", "twice the Fees"
_MULT = re.compile(
    rf"(?:(?P<tok>one\s+half|a\s+half|half|{WORDS}\s+and\s+a\s+half|{WORDS}|{_NUM})"
    rf"(?:\s*\(\s*(?P<dig>{_NUM})\s*\))?\s+times|(?P<twice>twice))"
    r"\s+(?:the\s+)?(?:annual\s+)?(?:Fees|fees|charges)\b",
    re.IGNORECASE,
)

_NET = re.compile(rf"\bnet\s+(?P<d>{_NUM})\b", re.IGNORECASE)

_LAW = re.compile(
    r"\blaws?\s+of\s+(?:the\s+)?(?:(?:State|Commonwealth|Province|Republic)\s+of\s+)?"
    r"(?P<name>[A-Z][a-z]+(?:\s+(?:and\s+)?[A-Z][a-z]+){0,3})"
)

_PERIOD_UNITS = {"month": 1, "year": 12}
_DAY_UNITS = {"day": 1, "week": 7}


def _number(word_group: str | None, digits: str | None) -> float | None:
    """A quantity written as words, digits, or both (digits win when both are given)."""
    if digits is not None:
        return float(digits)
    if word_group is not None:
        number = words_to_int(word_group)
        return None if number is None else float(number)
    return None


def _quantities(text: str) -> list[tuple[float, str, int]]:
    """Every quantity-with-unit in the text as (amount, singular unit, start offset)."""
    found = []
    for m in _QTY.finditer(text):
        qty = _number(m.group("w1") or m.group("w2"), m.group("d1") or m.group("d2"))
        if qty is None:
            continue
        found.append((qty, m.group("unit").lower().rstrip("s"), m.start()))
    return found


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 4)


def _multiplier(m: re.Match[str]) -> float | None:
    if m.group("twice"):
        return 2.0
    if m.group("dig"):
        return float(m.group("dig"))
    token = re.sub(r"\s+", " ", m.group("tok").lower())
    if token in ("one half", "a half", "half"):
        return 0.5
    if token.endswith(" and a half"):
        base = words_to_int(token[: -len(" and a half")])
        return None if base is None else base + 0.5
    if re.fullmatch(_NUM, token):
        return float(token)
    number = words_to_int(token)
    return None if number is None else float(number)


def parse_months(text: str) -> int | float | None:
    mult = _MULT.search(text)
    if mult:
        factor = _multiplier(mult)
        tail = text[mult.end() :]
        for qty, unit, _ in _quantities(tail):
            if unit in _PERIOD_UNITS and factor is not None:
                return _tidy(factor * qty * _PERIOD_UNITS[unit])
        if factor is not None and re.search(r"\bannual\b", mult.group(0), re.IGNORECASE):
            return _tidy(factor * 12)
        return None
    for qty, unit, _ in _quantities(text):
        if unit in _PERIOD_UNITS:
            return _tidy(qty * _PERIOD_UNITS[unit])
    return None


def parse_days(text: str) -> int | float | None:
    """The first notice or payment period in days; 'net 45' counts as 45 days."""
    options = [
        (start, qty * _DAY_UNITS[unit])
        for qty, unit, start in _quantities(text)
        if unit in _DAY_UNITS
    ]
    net = _NET.search(text)
    if net:
        options.append((net.start(), float(net.group("d"))))
    return _tidy(min(options)[1]) if options else None


def parse_hours(text: str) -> int | float | None:
    for qty, unit, _ in _quantities(text):
        if unit == "hour":
            return _tidy(qty)
        if unit == "day":
            return _tidy(qty * 24)
        if unit == "week":
            return _tidy(qty * 168)
    return None


def parse_enum(text: str) -> str | None:
    """Governing-law jurisdiction: the place named after 'laws of'."""
    m = _LAW.search(text)
    return m.group("name").strip() if m else None


def parse_bool(issue: Issue, text: str) -> bool | None:
    for rule in issue.rules:
        if re.search(rule.when, text, re.IGNORECASE):
            return rule.value
    return None


def parse_value(issue: Issue, span: str) -> Any:
    """Read the issue's value from the words of `span`; None when the span states none."""
    text = " ".join(span.split())
    kind = issue.value_type
    if kind == "months":
        return parse_months(text)
    if kind == "days":
        return parse_days(text)
    if kind == "hours":
        return parse_hours(text)
    if kind == "enum":
        return parse_enum(text)
    return parse_bool(issue, text)


def same_value(a: Any, b: Any) -> bool:
    """Equality that ignores int/float noise and the case of enum values."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return a == b
