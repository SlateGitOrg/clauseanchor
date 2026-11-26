"""Assemble one synthetic contract from planted issue instances."""

from __future__ import annotations

import random

from .templates import (
    COMPANIES,
    FILLER,
    ClauseSpec,
    Ctx,
    Instance,
    SectionSpec,
    Style,
    assignment_clause,
    breach_clauses,
    cap_clause,
    convenience_clause,
    definitions,
    governing_law_clauses,
    indemnity_clause,
    override_clause,
    payment_clause,
    render,
    renewal_clause,
)

MSA_HEADINGS = {
    "definitions": ["Definitions", "Definitions and Interpretation"],
    "services": ["Services", "Provision of the Services"],
    "fees": ["Fees and Payment", "Charges and Payment", "Payment"],
    "term": ["Term and Renewal", "Term"],
    "termination": ["Termination", "Termination and Suspension"],
    "confidentiality": ["Confidentiality"],
    "data": ["Data Protection", "Data Protection and Security"],
    "ip": ["Intellectual Property and Indemnification", "Intellectual Property", "Indemnification"],
    "liability": ["Limitation of Liability", "Liability", "Limitation and Exclusion of Liability"],
    "precedence": ["Order of Precedence"],
    "general": ["General Provisions", "Miscellaneous", "General"],
}
DPA_HEADINGS = {
    "definitions": ["Definitions", "Definitions and Interpretation"],
    "roles": ["Scope and Roles of the Parties"],
    "instructions": ["Processing Instructions"],
    "security": ["Security Measures"],
    "incidents": ["Security Incidents", "Security Incidents and Breach Notification"],
    "subprocessors": ["Sub-processors"],
    "audit": ["Audit Rights"],
    "transfers": ["International Transfers"],
    "term": ["Term, Renewal and Termination", "Term and Renewal"],
    "fees": ["Fees and Payment", "Commercial Terms and Payment"],
    "liability": ["Liability and Indemnification", "Limitation of Liability and Indemnification"],
    "precedence": ["Order of Precedence"],
    "general": ["General Provisions", "Miscellaneous"],
}


def _fill(ctx: Ctx, key: str, count: int) -> list[ClauseSpec]:
    pool = FILLER.get(key, [])
    picks = ctx.rng.sample(pool, min(count, len(pool)))
    return [
        ClauseSpec(t.replace("{S}", ctx.S).replace("{C}", ctx.C).replace("{term}", ctx.breach_term))
        for t in picks
    ]


def _definition_clauses(ctx: Ctx) -> list[ClauseSpec]:
    items = definitions(ctx, ctx.rng)
    if ctx.rng.random() < 0.4:
        children = [
            ClauseSpec(text.rstrip(".") + (";" if i < len(items) - 1 else "."))
            for i, (_, text) in enumerate(items)
        ]
        return [ClauseSpec("In this Agreement:", children=children)]
    return [ClauseSpec(text) for _, text in items]


def build_contract(
    doc_id: str, doc_type: str, instances: dict[str, Instance], rng: random.Random
) -> str:
    labels = rng.choice([("Supplier", "Customer"), ("Provider", "Client")])
    ctx = Ctx(
        rng=rng,
        doc_type=doc_type,
        supplier=labels[0],
        customer=labels[1],
        breach_term="Security Incident" if doc_type == "msa" else "Personal Data Breach",
    )
    heads = MSA_HEADINGS if doc_type == "msa" else DPA_HEADINGS
    pick = {k: rng.choice(v) for k, v in heads.items()}
    cap = instances["liability_cap_months"]
    carve = "carve_out" in cap.tags
    override_home = rng.choice(
        ["data", "precedence"] if doc_type == "msa" else ["incidents", "precedence"]
    )

    body: dict[str, list[ClauseSpec]] = {k: [] for k in heads}
    body["definitions"] = _definition_clauses(ctx)

    # liability
    liability: list[ClauseSpec] = []
    if cap.present:
        subject_to = "override" if carve and rng.random() < 0.6 else None
        liability.append(cap_clause(cap, ctx, subject_to))
    liability.extend(_fill(ctx, "liability", 2))
    if not cap.present:
        # the uncapped-liability decoy refers to the cap, which is absent here
        liability = [c for c in liability if "{ref:cap}" not in c.text]
    body["liability"] = liability
    if carve:
        body[override_home].append(override_clause(cap, ctx))

    # governing law, assignment
    gl, asg = instances["governing_law"], instances["assignment_consent"]
    general = _fill(ctx, "general", 4)
    if gl.present:
        general = governing_law_clauses(gl, ctx) + general
    if asg.present:
        general.insert(rng.randrange(len(general) + 1), assignment_clause(asg, ctx))
    body["general"] = general

    # term, renewal, convenience
    ren, pay = instances["auto_renewal_notice_days"], instances["payment_terms_days"]
    tfc, brk = instances["termination_for_convenience"], instances["breach_notice_hours"]
    ind = instances["indemnity_ip"]
    body["term"] = _fill(ctx, "term", 1)
    if ren.present:
        body["term"].append(renewal_clause(ren, ctx))
    body["fees"] = _fill(ctx, "fees", 3)
    if pay.present:
        body["fees"].insert(rng.randrange(len(body["fees"]) + 1), payment_clause(pay, ctx))

    if doc_type == "msa":
        body["services"] = _fill(ctx, "services", 3)
        body["termination"] = _fill(ctx, "termination", 3)
        if tfc.present:
            body["termination"].insert(1, convenience_clause(tfc, ctx))
        body["confidentiality"] = _fill(ctx, "confidentiality", 3)
        body["data"] = _fill(ctx, "data", 4) + body["data"]
        if brk.present:
            body["data"].insert(rng.randrange(len(body["data"]) + 1), *breach_clauses(brk, ctx))
        body["ip"] = _fill(ctx, "ip", 3)
        if ind.present:
            body["ip"].insert(rng.randrange(len(body["ip"]) + 1), indemnity_clause(ind, ctx))
        order = ["definitions", "services", "fees", "term", "termination", "confidentiality",
                 "data", "ip", "liability", "precedence", "general"]  # fmt: skip
        title = "MASTER SERVICES AGREEMENT"
    else:
        body["roles"] = _fill(ctx, "roles", 2)
        body["instructions"] = _fill(ctx, "instructions", 2)
        body["security"] = _fill(ctx, "data", 3)
        body["incidents"] = _fill(ctx, "data", 2) + body["incidents"]
        if brk.present:
            body["incidents"].insert(0, *breach_clauses(brk, ctx))
        body["subprocessors"] = _fill(ctx, "subprocessors", 2)
        body["audit"] = _fill(ctx, "audit", 2)
        body["transfers"] = _fill(ctx, "transfers", 1)
        body["term"] += _fill(ctx, "termination", 2)
        if tfc.present:
            body["term"].insert(1, convenience_clause(tfc, ctx))
        if ind.present:
            body["liability"].append(indemnity_clause(ind, ctx))
        order = ["definitions", "roles", "instructions", "security", "incidents",
                 "subprocessors", "audit", "transfers", "term", "fees", "liability",
                 "precedence", "general"]  # fmt: skip
        title = "DATA PROCESSING AGREEMENT"

    sections = []
    for key in order:
        clauses = body[key]
        if key == "precedence" and not (carve and override_home == "precedence"):
            continue
        if key == "precedence":
            clauses = _fill(ctx, "precedence", 1) + clauses
        if not clauses:
            continue
        sections.append(SectionSpec(key, pick[key], clauses))

    style = Style(
        numbering=rng.choice(["decimal", "decimal", "article"]),
        wrap=rng.choice([None, None, 78, 92]),
        indent=rng.random() < 0.5,
        blank_between=rng.random() < 0.6,
        curly=rng.random() < 0.3,
        xref_word=rng.choice(["Section", "Section", "Clause"]),
    )
    a, b = rng.sample(COMPANIES, 2)
    date = f"{rng.randint(1, 28)} {rng.choice(['March', 'June', 'September', 'November'])} 2026"
    preamble = (
        f'This {title.title()} is made on {date} between {a} ("{ctx.S}") and {b} ("{ctx.C}").'
    )
    return render(sections, style, f"{title} ({doc_id.upper()})", preamble, rng)
