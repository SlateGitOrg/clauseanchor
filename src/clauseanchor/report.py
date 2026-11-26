"""Markdown review report: one row per issue, then the details of every flagged finding."""

from __future__ import annotations

from .playbook import Playbook
from .results import ContractReview, IssueResult, Span

_QUOTE_LIMIT = 150


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _flat(text: str) -> str:
    """Whitespace-collapsed full text (line wraps become spaces; nothing is cut)."""
    return " ".join(text.split())


def _short(text: str, limit: int = _QUOTE_LIMIT) -> str:
    """Table-cell version of a quote; the full anchored text is always in Details."""
    flat = _flat(text)
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _truncated(result: IssueResult) -> bool:
    return result.anchor is not None and len(_flat(result.anchor.text)) > _QUOTE_LIMIT


def _where(span: Span) -> str:
    return f"{span.section} [{span.start}:{span.end}]"


def _row(playbook: Playbook, result: IssueResult) -> str:
    issue = playbook.issues[result.issue]
    if result.status == "NEEDS_REVIEW":
        verdict, value = "NEEDS REVIEW", "-"
    else:
        verdict, value = result.verdict or "-", issue.format_value(result.value)
    if result.anchor is not None:
        quote, section, offsets = (
            _short(result.anchor.text),
            result.anchor.section,
            (f"{result.anchor.start}-{result.anchor.end}"),
        )
    else:
        quote, section, offsets = "-", "-", "-"
    flags = ", ".join(result.flags) or "-"
    return (
        f"| {issue.title} | {verdict} | {_cell(value)} | {_cell(quote)} | {section} "
        f"| {offsets} | {flags} |"
    )


def render_review(review: ContractReview, playbook: Playbook) -> str:
    counts = {"RED": 0, "AMBER": 0, "GREEN": 0, "NEEDS REVIEW": 0}
    for r in review.results:
        counts[r.verdict if r.status != "NEEDS_REVIEW" and r.verdict else "NEEDS REVIEW"] += 1
    lines = [
        f"# Contract review: {review.doc_id}",
        "",
        "RED {RED} | AMBER {AMBER} | GREEN {GREEN} | NEEDS REVIEW {NEEDS REVIEW}".format(**counts),
        "",
        "| Issue | Verdict | Value | Quote | Section | Offsets | Flags |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_row(playbook, r) for r in review.results]
    details = [
        r for r in review.results if r.conflict or r.status != "FOUND" or r.flags or _truncated(r)
    ]
    if details:
        lines += ["", "## Details", ""]
    for r in details:
        issue = playbook.issues[r.issue]
        lines.append(f"### {issue.title}")
        if r.status == "MISSING":
            lines.append(
                f"- No clause states this term; verdict {r.verdict} (playbook requires it)."
            )
        if r.status == "NEEDS_REVIEW":
            lines.append(f"- Needs review: {r.note}")
        if r.anchor is not None and r.conflict is None:
            lines.append(f'- Anchored text {_where(r.anchor)}: "{_flat(r.anchor.text)}"')
        if r.reasked:
            lines.append("- The first quote was rejected and the model was asked once more.")
        for flag in r.flags:
            lines.append(f"- {flag}: {_FLAG_TEXT[flag]}")
        if r.conflict:
            c = r.conflict
            lines += [
                f"- Base clause {_where(c.base)} states {issue.format_value(c.base_value)}: "
                f'"{_flat(c.base.text)}"',
                f"- Overriding clause {_where(c.override)} states "
                f'{issue.format_value(c.override_value)}: "{_flat(c.override.text)}"',
                f"- Operative value: {issue.format_value(c.override_value)} "
                "(the overriding clause).",
            ]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_FLAG_TEXT = {
    "UNANCHORED": "the model's quote was not found in the contract.",
    "WRONG_SECTION": "the quote came from a section that cannot hold this term.",
    "SECTION_MISMATCH": "the quote is not in the section the model cited.",
    "VALUE_MISMATCH": "the model's value differs from its own quote; the value parsed from the "
    "anchored text is used.",
    "CONFLICT": "another clause overrides the value; both anchors are shown below.",
    "FUZZY": "the quote matched only approximately (difflib ratio of at least 0.97).",
    "MISSED_TERM": "the model reported no term, but the contract states one.",
    "UNPARSEABLE": "no value could be read from the anchored text.",
}
