"""Review one contract: retrieve, ask the model, anchor, re-parse, resolve conflicts, judge."""

from __future__ import annotations

from .anchor import Anchorer, AnchorResult, section_matches
from .assess import find_conflict, scan
from .model import ModelError, Proposal, ReviewModel
from .playbook import Issue, Playbook
from .results import ContractReview, FirstAttempt, Flag, IssueResult, Span
from .retrieve import Retriever
from .segment import Contract, segment
from .values import parse_value, same_value

_FEEDBACK = {
    "UNANCHORED": (
        "Your quote does not appear in the contract. Copy the exact words of the clause "
        "that states the term."
    ),
    "WRONG_SECTION": (
        "Your quote is from a section that cannot hold this term (for example the "
        "definitions). Quote the operative clause instead."
    ),
    "SECTION_MISMATCH": (
        "You cited section {cited} but your quote is in section {found}. Cite the section "
        "the quote comes from."
    ),
}


def review_contract(
    contract: Contract, playbook: Playbook, model: ReviewModel, top_k: int = 5
) -> ContractReview:
    retriever = Retriever(contract, top_k=top_k)
    anchorer = Anchorer(contract)
    results = [
        review_issue(issue, contract, retriever, anchorer, model)
        for issue in playbook.issues.values()
    ]
    return ContractReview(doc_id=contract.doc_id, results=results)


def review_text(
    text: str, doc_id: str, playbook: Playbook, model: ReviewModel, top_k: int = 5
) -> ContractReview:
    return review_contract(segment(text, doc_id), playbook, model, top_k)


def _check(
    proposal: Proposal, anchorer: Anchorer, contract: Contract, issue: Issue
) -> tuple[AnchorResult, str]:
    """Anchor the quote and compare the clause it lands in with the section the model cited."""
    anchor = anchorer.locate(proposal.quote or "", issue, claimed=proposal.section)
    if not anchor.ok:
        return anchor, anchor.status
    if proposal.section is not None and not section_matches(
        contract, proposal.section, anchor.clause
    ):
        return anchor, "SECTION_MISMATCH"
    return anchor, "ANCHORED"


def _span(contract: Contract, anchor: AnchorResult) -> Span:
    return Span(
        section=anchor.clause or "",
        start=anchor.start,
        end=anchor.end,
        text=contract.text[anchor.start : anchor.end],
        mode=anchor.mode,
    )


def review_issue(
    issue: Issue,
    contract: Contract,
    retriever: Retriever,
    anchorer: Anchorer,
    model: ReviewModel,
) -> IssueResult:
    clauses = [hit.clause for hit in retriever.retrieve(issue)]
    touches = scan(contract, issue)
    flags: list[Flag] = []
    result = IssueResult(issue=issue.name, status="FOUND")

    try:
        proposal = model.find(issue, clauses)
    except ModelError as exc:
        return result.model_copy(update={"status": "NEEDS_REVIEW", "note": str(exc)})
    result.first = FirstAttempt(value=proposal.value, quote=proposal.quote)

    anchor: AnchorResult | None = None
    span: Span | None = None
    if proposal.quote is not None:
        anchor, status = _check(proposal, anchorer, contract, issue)
        result.first.anchor_status = status
        if status != "ANCHORED":
            flags.append(status)  # type: ignore[arg-type]
            result.reasked = True
            feedback = _FEEDBACK[status].format(
                cited=proposal.section, found=anchor.clause if anchor else None
            )
            try:
                proposal = model.find(issue, clauses, feedback=feedback)
            except ModelError as exc:
                return _needs_review(result, flags, f"re-ask failed: {exc}")
            anchor, status = (
                _check(proposal, anchorer, contract, issue) if proposal.quote else (None, "")
            )
            if status != "ANCHORED":
                if status:
                    flags.append(status)  # type: ignore[arg-type]
                return _needs_review(result, flags, "finding still not anchored after one re-ask")
        assert anchor is not None
        span = _span(contract, anchor)
    elif touches:
        # The model reported no term, but the contract states one in an allowed section.
        flags.append("MISSED_TERM")
        span = touches[0].span()
        proposal = Proposal(value=None, quote=span.text, section=span.section)
    else:
        return result.model_copy(
            update={"status": "MISSING", "verdict": issue.missing, "flags": flags}
        )

    if anchor is not None and anchor.fuzzy:
        flags.append("FUZZY")
    # Read the value in the whole sentence around the anchor, so a partial quote cannot
    # change it; the anchor offsets stay the evidence.
    parsed = parse_value(issue, contract.sentence_context(span.start, span.end))
    if parsed is None:
        flags.append("UNPARSEABLE")
        return _needs_review(result, flags, "no value could be read from the anchored span")
    if proposal.value is not None and not same_value(parsed, proposal.value):
        flags.append("VALUE_MISMATCH")
    elif proposal.value is None and "MISSED_TERM" not in flags:
        flags.append("VALUE_MISMATCH")

    value = parsed
    conflict = find_conflict(touches, span.start)
    if conflict is not None:
        flags.append("CONFLICT")
        value = conflict.override_value
        span = conflict.override
    return result.model_copy(
        update={
            "verdict": issue.verdict(value),
            "value": value,
            "anchor": span,
            "flags": flags,
            "conflict": conflict,
        }
    )


def _needs_review(result: IssueResult, flags: list[Flag], note: str) -> IssueResult:
    return result.model_copy(update={"status": "NEEDS_REVIEW", "flags": flags, "note": note})
