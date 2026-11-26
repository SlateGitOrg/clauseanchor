"""Parse a plain-text contract into a clause tree that keeps character offsets.

Recognised numbering: `1.` headings (or `ARTICLE 1 - HEADING`), `1.1` clauses, `(a)` and
`(i)` sub-clauses. A clause's span covers its own text only (marker through the last line
of its paragraph); child clauses have their own spans, so `text[start:end]` is always the
clause's exact text.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

_ARTICLE = re.compile(r"^(?:ARTICLE|Article)[ ]+(?P<n>\d+)[ ]*[-–—:.][ ]*(?P<rest>\S.*)$")
_DECIMAL_HEADING = re.compile(r"^(?P<n>\d+)\.[ \t]+(?P<rest>\S.*)$")
_CLAUSE = re.compile(r"^(?P<n>\d+\.\d+)\.?[ \t]+(?P<rest>\S.*)$")
_PAREN = re.compile(r"^\((?P<label>[a-z]{1,4})\)[ \t]+(?P<rest>\S.*)$")
_ROMAN = re.compile(r"^(?=[ivx])x{0,3}(?:ix|iv|v?i{0,3})$")

_NUM = r"\d+(?:\.\d+)*(?:\([a-z]{1,4}\))*"
_SUB_NUM = r"(?:\d+(?:\.\d+)+(?:\([a-z]{1,4}\))*|\d+(?:\.\d+)*\([a-z]{1,4}\)(?:\([a-z]{1,4}\))*)"
XREF = re.compile(
    rf"\b(?:Sections?|Clauses?|Articles?|paragraphs?)\s+(?P<refs>{_NUM}"
    rf"(?:\s*(?:,|and|or|&)\s*{_SUB_NUM})*)",
    re.IGNORECASE,
)
_DEF_MEANS = re.compile(
    r"[\"“](?P<term>[A-Z][A-Za-z0-9\- ]{0,40}?)[\"”]\s+"
    r"(?:means|shall mean|has the meaning|refers to|is defined as)"
)
_DEF_PAREN = re.compile(
    r"\((?:the |a |an |each, a |together, the )?[\"“](?P<term>[A-Z][A-Za-z\- ]{0,40}?)[\"”]\)"
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
_TRAILING = re.compile(r"(?:[;,]\s*(?:and|or))?[;,.:\s]*$")


@dataclass
class Clause:
    doc_id: str
    number: str
    level: int
    label: str
    heading: str
    start: int
    end: int
    body_start: int
    text: str
    parent: str | None
    section: str
    children: list[str] = field(default_factory=list)
    subtree_end: int = 0

    @property
    def body(self) -> str:
        return self.text[self.body_start - self.start :]


@dataclass
class Definition:
    term: str
    number: str
    start: int
    end: int


@dataclass
class Contract:
    doc_id: str
    text: str
    clauses: list[Clause]
    by_number: dict[str, Clause]
    definitions: dict[str, Definition]
    xrefs: dict[str, list[str]]

    def __post_init__(self) -> None:
        self._starts = [c.start for c in self.clauses]

    def clause_at(self, offset: int) -> Clause | None:
        """The deepest clause whose own text contains `offset`."""
        i = bisect.bisect_right(self._starts, offset) - 1
        if i >= 0 and offset < self.clauses[i].end:
            return self.clauses[i]
        return None

    def top_of(self, clause: Clause) -> Clause:
        while clause.parent is not None:
            clause = self.by_number[clause.parent]
        return clause

    def descendants(self, clause: Clause) -> list[Clause]:
        found: list[Clause] = []
        for child in clause.children:
            node = self.by_number[child]
            found.append(node)
            found.extend(self.descendants(node))
        return found

    def sentence_context(self, start: int, end: int) -> str:
        """The full sentence(s) of the clause around [start, end), as exact contract text.

        A partial quote ("twelve (12) months") is read in the sentence that gives it meaning
        ("one and a half times the Fees paid in the preceding twelve (12) months"). Falls back
        to the span itself when it lies outside any clause.
        """
        clause = self.clause_at(start)
        if clause is None:
            return self.text[start:end]
        lo, hi = start, end
        offset = clause.body_start
        for s, e in split_sentences(clause.body):
            if s + offset < end and e + offset > start:
                lo, hi = min(lo, s + offset), max(hi, e + offset)
        return self.text[lo:hi]

    def used_terms(self, clause: Clause) -> list[str]:
        """Defined terms the clause relies on (excluding the clause that defines them)."""
        body = clause.body
        used = []
        for term, definition in self.definitions.items():
            if definition.number == clause.number:
                continue
            if re.search(rf"\b{re.escape(term)}\b", body):
                used.append(term)
        return used


def _is_roman(label: str) -> bool:
    return _ROMAN.match(label) is not None


def _next_letter(label: str | None) -> str:
    return "a" if label is None else chr(ord(label) + 1)


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) relative to `text`, without trailing list punctuation."""
    spans = []
    pos = 0
    for m in [*_SENTENCE_BREAK.finditer(text), None]:
        end = m.start() if m else len(text)
        chunk = text[pos:end]
        trimmed = _TRAILING.sub("", chunk)
        lead = len(chunk) - len(chunk.lstrip())
        if trimmed.strip():
            spans.append((pos + lead, pos + len(trimmed)))
        pos = m.end() if m else len(text)
    return spans


def _classify(stripped: str) -> tuple[str, re.Match[str]] | None:
    m = _ARTICLE.match(stripped)
    if m:
        return "article", m
    m = _CLAUSE.match(stripped)
    if m:
        return "clause", m
    m = _DECIMAL_HEADING.match(stripped)
    if m:
        rest = m.group("rest").strip()
        if len(rest) <= 80 and rest[0].isupper() and not rest.endswith((".", ";", ",")):
            return "heading", m
    m = _PAREN.match(stripped)
    if m:
        return "paren", m
    return None


def segment(text: str, doc_id: str = "contract") -> Contract:
    """Build the clause tree for one contract."""
    clauses: list[Clause] = []
    by_number: dict[str, Clause] = {}
    top: Clause | None = None
    owner: Clause | None = None  # last level 1/2 clause: owns (a) lists
    letter: Clause | None = None  # last level 3 clause: owns (i) lists
    last_letter: dict[str, str] = {}
    current: Clause | None = None
    extendable = False

    def open_clause(level: int, label: str, heading: str, start: int, body_start: int) -> Clause:
        nonlocal top, owner, letter
        parent: Clause | None
        if level == 1:
            number, parent = label, None
        elif level == 2:
            number, parent = label, top
        elif level == 3:
            assert owner is not None
            number, parent = f"{owner.number}({label})", owner
        else:
            assert letter is not None
            number, parent = f"{letter.number}({label})", letter
        clause = Clause(
            doc_id=doc_id,
            number=number,
            level=level,
            label=label,
            heading=heading,
            start=start,
            end=start,
            body_start=body_start,
            text="",
            parent=parent.number if parent else None,
            section=heading if level == 1 else (parent.section if parent else ""),
        )
        if parent:
            parent.children.append(number)
        clauses.append(clause)
        by_number[number] = clause
        if level == 1:
            top, owner, letter = clause, clause, None
        elif level == 2:
            owner, letter = clause, None
        elif level == 3:
            letter = clause
        return clause

    pos = 0
    for raw in text.splitlines(keepends=True):
        line_start = pos
        pos += len(raw)
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            extendable = False
            continue
        indent = len(line) - len(line.lstrip())
        start = line_start + indent
        kind = _classify(stripped)
        new: Clause | None = None
        if kind:
            tag, m = kind
            body_start = start + m.start("rest")
            if tag in ("article", "heading"):
                new = open_clause(1, m.group("n"), m.group("rest").strip(), start, body_start)
            elif tag == "clause":
                new = open_clause(2, m.group("n"), "", start, body_start)
            else:
                label = m.group("label")
                owner_key = owner.number if owner else ""
                if owner is None:
                    new = None
                elif label == _next_letter(last_letter.get(owner_key)):
                    last_letter[owner_key] = label
                    new = open_clause(3, label, "", start, body_start)
                elif letter is not None and _is_roman(label):
                    new = open_clause(4, label, "", start, body_start)
                elif len(label) == 1:
                    last_letter[owner_key] = label
                    new = open_clause(3, label, "", start, body_start)
            if new is not None:
                current = new
                extendable = True
        if new is None:
            if current is not None and extendable:
                current.end = line_start + len(line.rstrip())
            continue
        new.end = line_start + len(line.rstrip())

    for clause in clauses:
        clause.text = text[clause.start : clause.end]
        clause.subtree_end = clause.end
    for clause in reversed(clauses):
        if clause.parent is not None:
            parent = by_number[clause.parent]
            parent.subtree_end = max(parent.subtree_end, clause.subtree_end)

    definitions: dict[str, Definition] = {}
    for clause in clauses:
        body = clause.body
        for pattern in (_DEF_MEANS, _DEF_PAREN):
            for m in pattern.finditer(body):
                term = m.group("term").strip()
                if term not in definitions:
                    s = clause.body_start + m.start()
                    definitions[term] = Definition(term, clause.number, s, clause.end)

    xrefs: dict[str, list[str]] = {}
    for clause in clauses:
        targets: list[str] = []
        for m in XREF.finditer(clause.body):
            for ref in re.findall(_NUM, m.group("refs")):
                if ref in by_number and ref != clause.number and ref not in targets:
                    targets.append(ref)
        if targets:
            xrefs[clause.number] = targets

    return Contract(doc_id, text, clauses, by_number, definitions, xrefs)
