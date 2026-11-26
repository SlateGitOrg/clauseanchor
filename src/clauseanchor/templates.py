"""Clause templates and the renderer that turns them into numbered plain-text contracts."""

from __future__ import annotations

import random
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

from .numwords import to_words

ROMAN = ["i", "ii", "iii", "iv", "v", "vi"]

# Fee-multiplier caps: (phrase, period in months, resulting months), by verdict.
FEES_MULT: dict[str, list[tuple[str, int, int]]] = {
    "GREEN": [
        ("one and a half (1.5) times", 12, 18),
        ("two (2) times", 12, 24),
        ("twice", 12, 24),
        ("two (2) times", 6, 12),
        ("one and a half (1.5) times", 24, 36),
    ],
    "AMBER": [("one half (0.5) times", 12, 6), ("one and a half (1.5) times", 6, 9)],
    "RED": [("one half (0.5) times", 6, 3), ("one half (0.5) times", 8, 4)],
}

PLACES = {
    "New York": "the State of New York",
    "Delaware": "the State of Delaware",
    "California": "the State of California",
    "Texas": "the State of Texas",
    "Nevada": "the State of Nevada",
    "Cayman Islands": "the Cayman Islands",
}

COMPANIES = [
    "Halcyon Systems Ltd",
    "Brightwater Logistics Inc.",
    "Northgate Analytics Ltd",
    "Verdant Health Corp.",
    "Kestrel Mobility GmbH",
    "Lumen Harbour LLC",
    "Ashgrove Retail plc",
    "Tidewell Energy Inc.",
    "Pinecrest Education Ltd",
    "Marlow Freight Co.",
    "Quarry Lane Software Ltd",
    "Redfield Insurance plc",
    "Sable Peak Media Inc.",
    "Windmere Foods Ltd",
    "Ironbridge Capital LLC",
    "Oakhaven Dental Group",
]


@dataclass
class Instance:
    """The planted state of one issue in one contract."""

    issue: str
    present: bool
    value: Any
    verdict: str
    tags: list[str] = field(default_factory=list)
    base_value: Any = None
    multiplier: tuple[str, int, int] | None = None


@dataclass
class ClauseSpec:
    text: str
    key: str | None = None
    children: list[ClauseSpec] = field(default_factory=list)


@dataclass
class SectionSpec:
    key: str
    heading: str
    clauses: list[ClauseSpec] = field(default_factory=list)


@dataclass
class Style:
    numbering: str  # "decimal" or "article"
    wrap: int | None
    indent: bool
    blank_between: bool
    curly: bool
    xref_word: str


@dataclass
class Ctx:
    rng: random.Random
    doc_type: str
    supplier: str
    customer: str
    breach_term: str

    @property
    def S(self) -> str:  # noqa: N802
        return self.supplier

    @property
    def C(self) -> str:  # noqa: N802
        return self.customer


def qty(n: int, unit: str, rng: random.Random) -> str:
    """'twelve (12) months' most of the time, sometimes '12 months' or 'twelve months'."""
    label = unit if n == 1 else f"{unit}s"
    form = rng.choices(["both", "digits", "words"], [78, 14, 8])[0]
    if form == "digits":
        return f"{n} {label}"
    if form == "words":
        return f"{to_words(n)} {label}"
    return f"{to_words(n)} ({n}) {label}"


def hours_phrase(n: int, rng: random.Random) -> str:
    if n % 24 == 0 and n >= 96 and rng.random() < 0.7:
        return qty(n // 24, "day", rng)
    return qty(n, "hour", rng)


def place(name: str) -> str:
    return PLACES.get(name, name)


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:]


# --- issue clauses -------------------------------------------------------------------------


def cap_clause(inst: Instance, ctx: Ctx, subject_to_key: str | None = None) -> ClauseSpec:
    rng, S, C = ctx.rng, ctx.S, ctx.C
    lead = f"Subject to {{ref:{subject_to_key}}}, " if subject_to_key else ""
    if inst.multiplier is not None:
        phrase, period, _ = inst.multiplier
        forms = [
            (f"{S}'s aggregate liability under this Agreement shall not exceed {phrase} the Fees "
             f"paid or payable in the preceding {qty(period, 'month', rng)}.", False),
            (f"The aggregate liability of {S} arising out of this Agreement shall not exceed "
             f"{phrase} the Fees paid by {C} in the {qty(period, 'month', rng)} immediately "
             "preceding the claim.", True),
        ]  # fmt: skip
    else:
        months = inst.base_value if "carve_out" in inst.tags else inst.value
        m = qty(months, "month", rng)
        forms = [
            (f"{S}'s total aggregate liability arising out of or in connection with this "
             "Agreement, whether in contract, tort (including negligence) or otherwise, shall not "
             f"exceed an amount equal to the Fees paid or payable in the {m} preceding the event "
             "giving rise to the claim.", False),
            (f"Each party's aggregate liability under this Agreement shall be limited to {m} of "
             "the Fees.", True),
            (f"The maximum aggregate liability of either party under or in connection with this "
             f"Agreement shall not exceed {m} of fees paid by {C}.", True),
            (f"In no event shall {S}'s cumulative liability exceed the amounts paid by {C} in the "
             f"{m} immediately preceding the claim.", True),
        ]  # fmt: skip
    text, lowerable = rng.choice(forms)
    if lead:
        text = lead + (_lower_first(text) if lowerable else text)
    return ClauseSpec(text, key="cap")


def override_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, S = ctx.rng, ctx.S
    m = qty(inst.value, "month", rng)
    forms = [
        f"Notwithstanding {{ref:cap}} or any other provision of this Agreement, {S}'s total "
        f"liability in respect of any claim relating to Customer Data shall not exceed {m} of "
        "the Fees.",
        f"Notwithstanding anything to the contrary in this Agreement, {S}'s aggregate liability "
        f"for all claims arising from a {ctx.breach_term} shall be limited to {m} of the Fees.",
        f"Notwithstanding {{ref:cap}}, the liability of {S} under this Agreement shall in no "
        f"event exceed {m} of fees paid.",
    ]
    return ClauseSpec(rng.choice(forms), key="override")


def governing_law_clauses(inst: Instance, ctx: Ctx) -> list[ClauseSpec]:
    where = place(inst.value)
    forms = [
        "This Agreement and any dispute or claim arising out of or in connection with it shall "
        f"be governed by and construed in accordance with the laws of {where}, without regard to "
        "its conflict of laws principles.",
        f"This Agreement is governed by the laws of {where}, and each party submits to the "
        f"exclusive jurisdiction of the courts of {where}.",
        f"The laws of {where} govern this Agreement and all matters arising from it.",
    ]
    clauses = [ClauseSpec(ctx.rng.choice(forms))]
    if ctx.rng.random() < 0.4:
        clauses.append(
            ClauseSpec(f"Each party submits to the courts of {where} for any proceedings.")
        )
    return clauses


def renewal_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, S, C = ctx.rng, ctx.S, ctx.C
    d = qty(inst.value, "day", rng)
    forms = [
        "This Agreement shall automatically renew for successive renewal terms of "
        f"{qty(rng.choice([12, 12, 12, 24, 6]), 'month', rng)} each unless either party gives the "
        f"other at least {d}' written notice of non-renewal before the end of the then-current "
        "term.",
        "Unless terminated earlier, this Agreement renews automatically at the end of the "
        f"Initial Term and each renewal term, and {C} may prevent renewal by giving {S} not less "
        f"than {d}' prior written notice.",
        "This Agreement will renew automatically for successive one (1) year periods unless a "
        f"party notifies the other in writing {d} before the expiry of the then-current term.",
    ]
    return ClauseSpec(rng.choice(forms))


def payment_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, C = ctx.rng, ctx.C
    d = qty(inst.value, "day", rng)
    forms = [
        f"{C} shall pay each undisputed invoice within {d} of the date of receipt of the invoice.",
        f"All invoices are due and payable net {inst.value} days from the invoice date.",
        f"The Fees are payable in arrears and {C} shall remit payment within {d} of receiving a "
        "correct invoice.",
    ]
    return ClauseSpec(rng.choice(forms))


def convenience_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, S, C = ctx.rng, ctx.S, ctx.C
    d = qty(rng.choice([30, 60, 90]), "day", rng)
    if inst.value:
        forms = [
            f"{C} may terminate this Agreement for convenience at any time by giving {S} {d}' "
            "prior written notice.",
            f"Either party may terminate this Agreement without cause upon {d}' prior written "
            "notice to the other party.",
        ]
    else:
        forms = [
            f"{C} has no right to terminate this Agreement for convenience during the Initial "
            "Term or any renewal term.",
            "Neither party may terminate this Agreement for convenience.",
            "The parties waive any right to terminate this Agreement without cause.",
        ]
    return ClauseSpec(rng.choice(forms))


def breach_clauses(inst: Instance, ctx: Ctx) -> list[ClauseSpec]:
    rng, S, C, term = ctx.rng, ctx.S, ctx.C, ctx.breach_term
    h = hours_phrase(inst.value, rng)
    choice = rng.randrange(3)
    if choice == 0:
        return [
            ClauseSpec(
                f"{S} shall notify {C} of any {term} without undue delay and in any event within "
                f"{h} of becoming aware of it."
            )
        ]
    if choice == 1:
        return [
            ClauseSpec(f"{S} will inform {C} in writing within {h} after discovering a {term}.")
        ]
    return [
        ClauseSpec(
            f"In relation to any {term}, {S} shall:",
            children=[
                ClauseSpec(
                    f"notify {C} without undue delay and in any event within {h} of becoming "
                    f"aware of the {term};"
                ),
                ClauseSpec(f"take reasonable steps to contain and remediate the {term}; and"),
                ClauseSpec(
                    f"provide {C} with the information it reasonably requires to meet its own "
                    "obligations."
                ),
            ],
        )
    ]


def assignment_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, S, C = ctx.rng, ctx.S, ctx.C
    if inst.value:
        forms = [
            "Neither party may assign or transfer this Agreement, in whole or in part, without "
            "the prior written consent of the other party.",
            f"{S} shall not assign, novate or otherwise transfer any of its rights or "
            f"obligations under this Agreement without {C}'s prior written consent.",
        ]
    else:
        forms = [
            f"{S} may assign this Agreement without {C}'s consent to any affiliate or to a "
            "successor in connection with a merger, acquisition or sale of all or substantially "
            "all of its assets.",
            "Either party may freely assign this Agreement to any third party on written notice "
            "to the other.",
        ]
    return ClauseSpec(rng.choice(forms))


def indemnity_clause(inst: Instance, ctx: Ctx) -> ClauseSpec:
    rng, S, C = ctx.rng, ctx.S, ctx.C
    if inst.value:
        forms = [
            f"{S} shall defend and indemnify {C} against any third-party claim that the Services "
            "infringe or misappropriate any intellectual property right, and shall pay any "
            "damages finally awarded.",
            f"{S} will indemnify, defend and hold harmless {C} from any claim alleging that the "
            "Services infringe a patent, copyright or trade secret of a third party.",
        ]
    else:
        forms = [
            f"{S} has no obligation to indemnify {C} for any claim that the Services infringe "
            "the intellectual property rights of a third party.",
            f"{S} excludes all liability for infringement of third-party intellectual property "
            "rights by the Services.",
        ]
    return ClauseSpec(rng.choice(forms))


# --- filler (clauses that carry no playbook term; some are deliberate decoys) ---------------

FILLER: dict[str, list[str]] = {
    "services": [
        "{S} shall provide the Services in accordance with this Agreement and each Order Form, "
        "using reasonable skill and care.",
        "{S} shall use commercially reasonable efforts to make the Services available at least "
        "99.5% of the time in each calendar month, excluding scheduled maintenance.",
        "{C} shall give {S} the cooperation and information that {S} reasonably requires to "
        "perform the Services.",
        "Either party may propose changes to an Order Form, and no change is effective until "
        "both parties have signed it.",
        "{S} may use subcontractors to perform the Services and remains responsible for their "
        "acts and omissions.",
    ],
    "fees": [
        "Fees are set out in the applicable Order Form and are exclusive of value added tax and "
        "similar taxes.",
        "{S} shall invoice the Fees monthly in arrears and each invoice shall itemise the "
        "Services provided.",
        "Overdue amounts accrue interest at 1.5% per month from the date payment was missed "
        "until the date it is made.",
        "{C} may dispute an invoice in good faith by telling {S} which amount is disputed and why.",
        "Each party is responsible for its own taxes.",
    ],
    "term": [
        "This Agreement commences on the Effective Date and continues for the Initial Term, "
        "unless terminated earlier in accordance with its terms.",
    ],
    "termination": [
        "Either party may terminate this Agreement for material breach by the other party that "
        "remains uncured thirty (30) days after written notice of the breach.",
        "Either party may terminate this Agreement immediately by written notice if the other "
        "party becomes insolvent or enters administration or bankruptcy proceedings.",
        "On termination, {C} shall pay all Fees accrued up to the date of termination and each "
        "party shall return or delete the other's Confidential Information.",
        "Provisions that by their nature should survive termination, including confidentiality "
        "and the allocation of liability, shall survive.",
    ],
    "confidentiality": [
        "Each party shall keep the other party's Confidential Information confidential and use "
        "it only to perform or receive the Services.",
        "Confidential Information does not include information that is public, already known to "
        "the recipient, or independently developed by it.",
        "Notwithstanding the foregoing, a party may disclose Confidential Information to the "
        "extent required by law or to its professional advisers who are bound by duties of "
        "confidence.",
        "The obligations in this section continue for five (5) years after termination.",
    ],
    "data": [
        "{S} shall process Customer Data only on {C}'s documented instructions and in "
        "accordance with applicable Data Protection Laws.",
        "{S} shall maintain administrative, technical and physical safeguards appropriate to the "
        "sensitivity of Customer Data.",
        "{S} shall not engage a sub-processor without informing {C}, and remains responsible "
        "for each sub-processor.",
        "On termination, {S} shall return or delete Customer Data within thirty (30) days of "
        "{C}'s written request.",
        "{S} shall maintain a record of each {term}, including its effects and the remedial "
        "action taken.",
        "{C} shall notify {S} promptly of any suspected unauthorised use of its accounts.",
    ],
    "ip": [
        "{S} retains all rights in the Services and {C} retains all rights in Customer Data.",
        "{S} grants {C} a non-exclusive right to use the Services during the term for its "
        "internal business purposes.",
        "{C} shall indemnify {S} against third-party claims arising from {C}'s breach of the "
        "acceptable use rules in the Order Form.",
    ],
    "liability": [
        "Neither party shall be liable to the other for any indirect, incidental or "
        "consequential loss, or for loss of profits or revenue.",
        "Nothing in this Agreement limits or excludes liability for death or personal injury "
        "caused by negligence, for fraud, or for any liability that cannot be limited by law, "
        "and {ref:cap} does not apply to such liability.",
    ],
    "general": [
        "This Agreement, with its Order Forms, is the entire agreement between the parties on "
        "its subject matter.",
        "Notices must be in writing and are deemed received two (2) business days after posting "
        "or on the day of delivery by email.",
        "Neither party is liable for delay caused by events beyond its reasonable control, "
        "including natural disasters, war and failures of public utilities.",
        "If any provision is held unenforceable, the remainder of this Agreement continues in "
        "effect.",
        "This Agreement may be signed in counterparts, each of which is an original.",
        "Waiver of a breach is not a waiver of any later breach.",
    ],
    "roles": [
        "{C} is the controller and {S} is the processor of the Personal Data processed under "
        "this Agreement.",
        "The subject matter, duration and purpose of the processing are described in the "
        "applicable Order Form.",
    ],
    "instructions": [
        "{S} shall process Personal Data only on {C}'s documented instructions, unless "
        "applicable law requires otherwise.",
        "{S} shall tell {C} if it believes an instruction breaches Data Protection Laws.",
    ],
    "audit": [
        "{C} may audit {S}'s compliance with this Agreement on thirty (30) days' written notice, "
        "no more than once in any twelve (12) month period.",
        "{S} shall give {C} the information reasonably necessary to demonstrate compliance with "
        "Data Protection Laws.",
    ],
    "transfers": [
        "{S} shall not move Personal Data outside the approved regions listed in the Order Form "
        "without {C}'s written approval.",
    ],
    "subprocessors": [
        "{S} shall impose data protection terms on each sub-processor that are no less "
        "protective than those in this Agreement.",
        "{S} shall give {C} advance written notice of any new sub-processor and {C} may object "
        "on reasonable grounds.",
    ],
    "precedence": [
        "If there is a conflict between this Agreement and an Order Form, this Agreement "
        "prevails unless the Order Form expressly refers to the provision it overrides.",
    ],
}


def definitions(ctx: Ctx, rng: random.Random) -> list[tuple[str, str]]:
    title = "Master Services Agreement" if ctx.doc_type == "msa" else "Data Processing Agreement"
    S, C = ctx.S, ctx.C
    data = "Customer Data" if ctx.doc_type == "msa" else "Personal Data"
    items = [
        ("Agreement", f'"Agreement" means this {title}, including each Order Form.'),
        (
            "Fees",
            rng.choice(
                [
                    f'"Fees" means the amounts payable by {C} to {S} for the Services under '
                    "each Order Form.",
                    f'"Fees" means all charges payable by {C} for the Services as set out in '
                    "each Order Form.",
                ]
            ),
        ),
        (
            "Services",
            f'"Services" means the hosted software and related support that {S} provides '
            "under an Order Form.",
        ),
        (
            data,
            f'"{data}" means information submitted to or processed by the Services by or on '
            f"behalf of {C}.",
        ),
        (
            ctx.breach_term,
            f'"{ctx.breach_term}" means a breach of security leading to the accidental or '
            f"unlawful destruction, loss, alteration or unauthorised disclosure of {data}.",
        ),
        (
            "Effective Date",
            '"Effective Date" means the date on which this Agreement is signed by both parties.',
        ),
        (
            "Initial Term",
            f'"Initial Term" means the period of {qty(rng.choice([12, 24, 36]), "month", rng)} '
            "starting on the Effective Date.",
        ),
        (
            "Order Form",
            '"Order Form" means a document signed by both parties that describes the Services '
            "and the Fees.",
        ),
    ]
    if ctx.doc_type == "dpa":
        items.append(
            (
                "Data Protection Laws",
                '"Data Protection Laws" means all laws applicable to the processing of Personal '
                "Data under this Agreement.",
            )
        )
    return items


# --- rendering -------------------------------------------------------------------------------


def _curly(text: str) -> str:
    return re.sub(r'"([^"]*)"', "“\\1”", text)


def render(
    sections: list[SectionSpec], style: Style, title: str, preamble: str, rng: random.Random
) -> str:
    """Number the sections, resolve {ref:key} placeholders and lay the text out."""
    numbers: dict[str, str] = {}

    def number_clauses(owner: str, clauses: list[ClauseSpec], depth: int) -> None:
        for index, clause in enumerate(clauses):
            if depth == 2:
                num = f"{owner}.{index + 1}"
            elif depth == 3:
                num = f"{owner}({chr(97 + index)})"
            else:
                num = f"{owner}({ROMAN[index]})"
            if clause.key:
                numbers[clause.key] = num
            number_clauses(num, clause.children, depth + 1)

    for i, section in enumerate(sections, 1):
        numbers[section.key] = str(i)
        number_clauses(str(i), section.clauses, 2)

    def resolve(text: str) -> str:
        text = re.sub(r"\{ref:(\w+)\}", lambda m: f"{style.xref_word} {numbers[m.group(1)]}", text)
        return _curly(text) if style.curly else text

    indent_for = {2: "", 3: "    " if style.indent else "", 4: "        " if style.indent else ""}
    intro = resolve(preamble)
    if style.wrap:
        intro = "\n".join(textwrap.wrap(intro, width=style.wrap))
    lines: list[str] = [title, "", intro, ""]

    def emit(marker: str, text: str, depth: int) -> None:
        pad = indent_for[depth]
        body = f"{marker} {resolve(text)}"
        if style.wrap:
            wrapped = textwrap.wrap(
                body,
                width=style.wrap,
                initial_indent=pad,
                subsequent_indent=pad,
                break_long_words=False,
                break_on_hyphens=False,
            )
            lines.extend(wrapped)
        else:
            lines.append(pad + body)
        if style.blank_between:
            lines.append("")

    def emit_children(owner: str, clauses: list[ClauseSpec], depth: int) -> None:
        for index, clause in enumerate(clauses):
            if depth == 2:
                marker = f"{owner}.{index + 1}"
            elif depth == 3:
                marker = f"({chr(97 + index)})"
            else:
                marker = f"({ROMAN[index]})"
            num = (
                f"{owner}.{index + 1}"
                if depth == 2
                else f"{owner}({chr(97 + index)})"
                if depth == 3
                else f"{owner}({ROMAN[index]})"
            )
            emit(marker, clause.text, depth)
            emit_children(num, clause.children, depth + 1)

    for i, section in enumerate(sections, 1):
        heading = section.heading
        if style.numbering == "article":
            lines.append(f"ARTICLE {i} – {heading.upper()}")
        else:
            lines.append(f"{i}. {heading}")
        if style.blank_between:
            lines.append("")
        emit_children(str(i), section.clauses, 2)
    closing = [
        "",
        "Signed by the parties' authorised representatives on the dates stated in the Order Form.",
    ]
    lines.extend(closing)
    return "\n".join(lines).rstrip() + "\n"
