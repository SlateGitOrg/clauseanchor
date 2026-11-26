"""English number words: parsing for the value parser, rendering for the contract generator."""

from __future__ import annotations

import re

_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}

_WORD_VALUES: dict[str, int] = {w: i for i, w in enumerate(_UNITS)}
_WORD_VALUES.update({w: n for n, w in _TENS.items()})

# One number word, and a run of them ("seventy-two", "one hundred and twenty").
WORD = r"(?:" + "|".join(sorted([*_WORD_VALUES, "hundred"], key=len, reverse=True)) + r")"
WORDS = rf"{WORD}(?:(?:[-\s]+|\s+and\s+){WORD})*"
_WORDS_RE = re.compile(rf"^{WORDS}$", re.IGNORECASE)


def to_words(n: int) -> str:
    """Render 0..999 in words: 72 -> 'seventy-two', 120 -> 'one hundred twenty'."""
    if not 0 <= n < 1000:
        raise ValueError(f"out of range: {n}")
    if n < 20:
        return _UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        base = _TENS[tens * 10]
        return base if unit == 0 else f"{base}-{_UNITS[unit]}"
    hundreds, rest = divmod(n, 100)
    head = f"{_UNITS[hundreds]} hundred"
    return head if rest == 0 else f"{head} {to_words(rest)}"


def words_to_int(text: str) -> int | None:
    """Parse number words; returns None when the text is not made of number words."""
    cleaned = text.strip().lower()
    if not _WORDS_RE.match(cleaned):
        return None
    current = 0
    for token in re.split(r"[-\s]+", cleaned):
        if token == "and":
            continue
        if token == "hundred":
            current = max(current, 1) * 100
        else:
            current += _WORD_VALUES[token]
    return current
