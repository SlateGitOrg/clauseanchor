"""Locate a model's quote in the contract and return character offsets.

Order of attempts: exact match, normalised match (whitespace, curly quotes, dashes, case,
end-of-line hyphenation) mapped back to original offsets, then a fuzzy sliding window with a
difflib ratio of at least 0.97. Anything else is UNANCHORED. A quote that anchors outside the
issue's allowed sections is WRONG_SECTION.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .playbook import Issue
from .segment import Contract

Status = Literal["ANCHORED", "UNANCHORED", "WRONG_SECTION"]
Mode = Literal["exact", "normalized", "fuzzy"]

FUZZY_THRESHOLD = 0.97
MIN_FUZZY_LENGTH = 20

_CHAR_MAP = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)
_LINE_HYPHEN = re.compile(r"-[ \t]*\r?\n[ \t]*(?=[a-z])")


@dataclass(frozen=True)
class AnchorResult:
    status: Status
    mode: Mode | None = None
    start: int = -1
    end: int = -1
    ratio: float = 0.0
    clause: str | None = None
    section: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ANCHORED"

    @property
    def fuzzy(self) -> bool:
        return self.mode == "fuzzy"


def normalize_with_map(text: str, dehyphenate: bool = True) -> tuple[str, list[int]]:
    """Normalised text plus, for every output character, its offset in the original."""
    out: list[str] = []
    index: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if dehyphenate and ch == "-" and i > 0 and text[i - 1].isalpha():
            m = _LINE_HYPHEN.match(text, i)
            if m:
                i = m.end()
                continue
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                index.append(i)
            i += 1
            continue
        low = ch.translate(_CHAR_MAP).lower()
        out.append(low if len(low) == 1 else ch)
        index.append(i)
        i += 1
    return "".join(out), index


def section_matches(contract: Contract, claimed: str | None, number: str | None) -> bool:
    """True when the cited section is the anchored clause or one of its ancestors."""
    if claimed is None or number is None:
        return False
    cited = re.sub(r"^(?:sections?|clauses?|articles?)\s*", "", claimed.strip(), flags=re.I)
    cited = re.sub(r"\s+", "", cited).rstrip(".")
    clause = contract.by_number.get(number)
    while clause is not None:
        if clause.number == cited:
            return True
        clause = contract.by_number.get(clause.parent) if clause.parent else None
    return False


def normalize(text: str) -> str:
    return normalize_with_map(text, dehyphenate=False)[0].strip()


class Anchorer:
    """Anchors quotes in one contract; the normalised text is built once and reused."""

    def __init__(self, contract: Contract) -> None:
        self.contract = contract
        self.text = contract.text
        self._views = [normalize_with_map(self.text, True), normalize_with_map(self.text, False)]

    def locate(self, quote: str, issue: Issue, claimed: str | None = None) -> AnchorResult:
        """Anchor `quote`; positions are checked against the issue's allowed sections.

        When the quote occurs more than once, the occurrence inside the clause the model
        cited (`claimed`) is preferred, then any occurrence in an allowed section.
        """
        if not quote or not quote.strip():
            return AnchorResult("UNANCHORED")
        hits = self._exact(quote) or self._normalized(quote) or self._fuzzy(quote)
        if not hits:
            return AnchorResult("UNANCHORED")
        allowed = [h for h in hits if self._section_ok(h[1], issue)]
        cited = [h for h in allowed if self._cites(claimed, h[1])]
        chosen = (cited or allowed or [None])[0]
        status: Status = "ANCHORED"
        if chosen is None:
            chosen, status = hits[0], "WRONG_SECTION"
        mode, start, end, ratio = chosen
        clause = self.contract.clause_at(start)
        return AnchorResult(
            status,
            mode,
            start,
            end,
            ratio,
            clause.number if clause else None,
            self.contract.top_of(clause).heading if clause else "",
        )

    def _cites(self, claimed: str | None, start: int) -> bool:
        clause = self.contract.clause_at(start)
        return clause is not None and section_matches(self.contract, claimed, clause.number)

    def _section_ok(self, start: int, issue: Issue) -> bool:
        clause = self.contract.clause_at(start)
        return clause is not None and issue.allows(clause.section)

    def _exact(self, quote: str) -> list[tuple[Mode, int, int, float]]:
        hits = []
        start = self.text.find(quote)
        while start != -1:
            hits.append(("exact", start, start + len(quote), 1.0))
            start = self.text.find(quote, start + 1)
        return hits  # type: ignore[return-value]

    def _normalized(self, quote: str) -> list[tuple[Mode, int, int, float]]:
        for dehyphenate, (norm, index) in zip((True, False), self._views, strict=True):
            needle = normalize_with_map(quote, dehyphenate)[0].strip()
            if not needle:
                continue
            hits = []
            at = norm.find(needle)
            while at != -1:
                start = index[at]
                end = index[at + len(needle) - 1] + 1
                hits.append(("normalized", start, end, 1.0))
                at = norm.find(needle, at + 1)
            if hits:
                return hits  # type: ignore[return-value]
        return []

    def _fuzzy(self, quote: str) -> list[tuple[Mode, int, int, float]]:
        norm, index = self._views[0]
        needle = normalize_with_map(quote, True)[0].strip()
        found = fuzzy_find(needle, norm)
        if found is None:
            return []
        i, j, ratio = found
        return [("fuzzy", index[i], index[j - 1] + 1, ratio)]


def fuzzy_find(
    needle: str, haystack: str, threshold: float = FUZZY_THRESHOLD
) -> tuple[int, int, float] | None:
    """Best window of `haystack` whose difflib ratio against `needle` is >= threshold.

    A ratio of at least 0.97 allows only about 6% of the characters to be edited, and each
    edit breaks at most one piece of the needle. Splitting the needle into more pieces than
    that guarantees one piece survives intact, so only windows around exact piece hits need
    scoring. That keeps the search linear instead of quadratic.
    """
    length = len(needle)
    if length < MIN_FUZZY_LENGTH or not haystack:
        return None
    longest = length * (2 - threshold) / threshold  # longest window that can still qualify
    edits = int((1 - threshold) * (length + longest)) + 1
    pieces = min(edits + 1, length // 6)
    size = length // pieces
    pad = edits + 2
    seen: set[int] = set()
    best: tuple[float, int, int] | None = None
    for p in range(pieces):
        offset = p * size
        piece = needle[offset : offset + size]
        at = haystack.find(piece)
        while at != -1:
            anchor = at - offset
            bucket = anchor // pad
            if bucket not in seen:
                seen.add(bucket)
                lo = max(0, anchor - pad)
                region = haystack[lo : anchor + length + pad]
                blocks = SequenceMatcher(None, needle, region, autojunk=False).get_matching_blocks()
                blocks = [b for b in blocks if b.size >= 3]
                if blocks:
                    s, e = blocks[0].b, blocks[-1].b + blocks[-1].size
                    ratio = SequenceMatcher(None, needle, region[s:e], autojunk=False).ratio()
                    if ratio >= threshold and (best is None or ratio > best[0]):
                        best = (ratio, lo + s, lo + e)
            at = haystack.find(piece, at + 1)
    if best is None:
        return None
    return best[1], best[2], best[0]
