"""Sprint R2 — per-draft-type system prompts.

The generic drafting service already ships a single prompt that works
for every pleading. It works, but it treats every draft as a generic
legal document — so a Bail prompt doesn't push the triple-test, a
Cheque Bounce notice doesn't enforce the s.138 boilerplate, and a
Civil Suit plaint doesn't push Order VII Rule 1 compliance.

This module adds one specialised prompt per ``DraftTemplateType``.
Each prompt:

- cites the correct governing statutes (BNSS for new matters, with a
  CrPC cross-reference only where the client expects it),
- enforces the procedural scaffolding expected at Indian courts,
- calls out the most common review-rejection reasons for that draft
  type.

Prompts are returned as ``PromptParts`` (system + user) so the calling
service can combine them with its own ABSOLUTE-RULES header without
re-parsing strings.
"""
from __future__ import annotations

from dataclasses import dataclass

from caseops_api.schemas.drafting_templates import DraftTemplateType


@dataclass(frozen=True)
class PromptParts:
    """Structured prompt pair for a specific template.

    ``system`` is the domain-specific instruction block; ``focus``
    is the one-line summary we surface to the user in the UI.
    """

    system: str
    focus: str


# ---------------------------------------------------------------
# Per-template prompts. Keep each block short and testable: one idea
# per line, specific section numbers, no marketing language.
# ---------------------------------------------------------------


_BAIL = PromptParts(
    system=(
        "You are drafting a regular bail application under BNSS s.483 "
        "(earlier CrPC s.439). Follow Indian High Court / Sessions "
        "Court practice.\n"
        "REQUIRED STRUCTURE (in order):\n"
        " 1. Cause title + memo of parties (accused as Applicant).\n"
        " 2. Jurisdiction paragraph citing BNSS s.483.\n"
        " 3. Brief facts of the FIR, sections charged, and custody duration.\n"
        " 4. Grounds for bail — ALWAYS walk the triple test: flight "
        "risk, tampering with evidence, influencing witnesses. "
        "Reference the Sanjay Chandra, Dataram Singh, and Arnab Goswami "
        "lines of precedent where relevant.\n"
        " 5. Parity arguments if a co-accused is already on bail — "
        "name them explicitly.\n"
        " 6. Custody duration argument under Satender Kumar Antil / "
        "Sundeep Kumar Bafna principles.\n"
        " 7. Prayer: enlarge on bail subject to conditions u/s BNSS "
        "s.491 (bond + surety + reporting).\n"
        "RULES:\n"
        " - Cite BNSS sections first, CrPC only as a historical bracket.\n"
        " - Do NOT claim factual innocence; bail is about liberty pending "
        "trial, not merits.\n"
        " - Do NOT invent parity cases or co-accused names.\n"
        " - If custody duration is < 7 days, soften the custody-duration "
        "ground rather than omitting it."
    ),
    focus="Regular bail under BNSS s.483 — triple test + parity + custody",
)

_ANTICIPATORY_BAIL = PromptParts(
    system=(
        "You are drafting an anticipatory bail application under BNSS "
        "s.482 (earlier CrPC s.438).\n"
        "MANDATORY OPENING: the first paragraph of the application "
        "MUST cite 'BNSS Section 482' (or 'BNSS s.482') by name — "
        "this is the statutory basis of the petition and the "
        "validator will refuse the draft without it.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title with applicant as Applicant.\n"
        " 2. Jurisdiction paragraph citing BNSS s.482 (the statutory "
        "basis — do not omit this).\n"
        " 3. Reasonable apprehension of arrest — specific facts, not "
        "generic fear.\n"
        " 4. Why custodial interrogation is unnecessary (cooperate, "
        "documents already produced, s.41A notice compliance).\n"
        " 5. Precedents: Gurbaksh Singh Sibbia, Sushila Aggarwal, Arnesh "
        "Kumar (where applicable to s.41A).\n"
        " 6. Prayer — pre-arrest bail under BNSS s.482 with conditions.\n"
        "RULES:\n"
        " - ALWAYS include the literal string 'BNSS s.482' in the "
        "body. Never skip the statute citation.\n"
        " - Anchor the apprehension in the FIR text or specific "
        "communications; do not invent facts.\n"
        " - If the applicant has received an s.41A notice, address "
        "compliance explicitly.\n"
        " - Keep the prayer tight: name the conditions you accept "
        "(no-contact, passport surrender, reporting)."
    ),
    focus="Anticipatory bail under BNSS s.482 — Sibbia + Sushila Aggarwal",
)

_DIVORCE = PromptParts(
    system=(
        "You are drafting a petition for dissolution of marriage. The "
        "governing Act is specified in the facts (HMA / SMA / Indian "
        "Christian Marriage Act / other). DO NOT GUESS — use the Act the "
        "user picked.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title: petitioner v. respondent.\n"
        " 2. Jurisdiction paragraph — last residence + court's territorial "
        "competence under s.19 HMA / s.31 SMA.\n"
        " 3. Marriage: when, where, how solemnised (ceremony / "
        "registration).\n"
        " 4. Cohabitation timeline + children born of the marriage.\n"
        " 5. Grounds — cruelty / desertion / adultery / conversion / "
        "mental illness / non-consummation. One ground per "
        "sub-paragraph; cite the clause of s.13 HMA / s.27 SMA.\n"
        " 6. Maintenance + custody + interim relief paragraph if "
        "children are involved.\n"
        " 7. Prayer — dissolution + reliefs sought.\n"
        "RULES:\n"
        " - Do not merge cruelty + desertion into one paragraph; courts "
        "reject sloppy framing.\n"
        " - If under HMA, add the statutory cooling-off if s.13B applies.\n"
        " - Keep children references factual; do not argue fitness here."
    ),
    focus="Divorce petition under HMA s.13 / SMA s.27 — strict ground-per-para",
)

_PROPERTY_NOTICE = PromptParts(
    system=(
        "You are drafting a pre-litigation demand notice in a property "
        "dispute.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Sender and recipient addresses.\n"
        " 2. Reference to the specific property (address + survey / "
        "plot number + area).\n"
        " 3. Sender's title chain — cite the sale deed / will / gift "
        "deed / inheritance with registration details.\n"
        " 4. Alleged encroachment / obstruction / trespass — specific "
        "dates.\n"
        " 5. Legal position: s.5 TPA (transfer), Specific Relief Act "
        "provisions (s.5 possession / s.6 summary recovery), "
        "Registration Act where mutation is disputed.\n"
        " 6. Demand: specific relief within the response deadline the "
        "user supplied.\n"
        " 7. Consequences clause — civil + criminal remedies if the "
        "recipient fails to comply.\n"
        "RULES:\n"
        " - Use the exact property address the user provided.\n"
        " - Do not threaten criminal action unless the facts disclose "
        "a cognisable offence.\n"
        " - Match the response deadline the user picked — do not "
        "substitute a default."
    ),
    focus="Property-dispute demand notice — title chain + Specific Relief Act",
)

_CHEQUE_BOUNCE = PromptParts(
    system=(
        "You are drafting a statutory demand notice under s.138 of the "
        "Negotiable Instruments Act, 1881. This notice is the "
        "pre-condition for a s.138 complaint — it must be perfect.\n"
        "MANDATORY PHRASES: the notice body MUST contain both the "
        "literal string 'Section 138' (or 's.138') AND the exact phrase "
        "'fifteen days' OR '15 days' somewhere in the demand clause. "
        "The validator refuses the draft otherwise; these are "
        "statutory-compliance markers, not stylistic choices.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Full name and address of drawer (recipient of the notice).\n"
        " 2. Full name and address of drawee / payee (sender).\n"
        " 3. Cheque particulars — number, date, amount in figures AND "
        "words, bank, branch.\n"
        " 4. Presentation date + dishonour memo date + dishonour reason "
        "(verbatim from the bank memo).\n"
        " 5. Demand: pay the exact cheque amount 'within fifteen (15) "
        "days of receipt of this notice'. Write that phrase verbatim. "
        "NEVER substitute a different period — the statute mandates 15 "
        "days and the validator searches for the exact 'fifteen days' "
        "or '15 days' string.\n"
        " 6. Warning: on non-payment, the sender will prosecute under "
        "s.138 of the Negotiable Instruments Act, 1881 + may claim "
        "double the cheque amount under s.142.\n"
        "RULES:\n"
        " - Amount in figures AND words, EVERY TIME. A mismatch is a "
        "standard review-rejection reason.\n"
        " - The 15-day statutory window is non-negotiable. Do not use "
        "'at the earliest' or 'within a reasonable time'.\n"
        " - Do not include interest claims or penalty clauses — s.138 "
        "is limited to the cheque amount + compensation under s.142."
    ),
    focus="s.138 NI Act statutory notice — 15-day window, amount in figures + words",
)

_AFFIDAVIT = PromptParts(
    system=(
        "You are drafting a sworn affidavit for filing alongside a "
        "pleading in an Indian court.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Title of proceedings + court.\n"
        " 2. Deponent block — name, age, occupation, address.\n"
        " 3. 'I, [Deponent], do hereby solemnly affirm and state as "
        "under:'.\n"
        " 4. Numbered paragraphs of fact — one fact per paragraph, "
        "personal knowledge vs. information belief distinguished.\n"
        " 5. Verification clause: which paragraphs are true to "
        "personal knowledge, which on information believed to be "
        "true, which on legal advice.\n"
        " 6. Sworn at (place), on (date), before a Notary / Oath "
        "Commissioner.\n"
        "RULES:\n"
        " - Never mix personal-knowledge paragraphs with "
        "information-belief paragraphs without the verification "
        "distinguishing them. This is the single most common reason "
        "affidavits are returned by the registry.\n"
        " - Do not include legal arguments — affidavits are evidentiary.\n"
        " - Deponent's age and occupation must match ID — do not "
        "invent plausible values."
    ),
    focus="Sworn affidavit — CPC Order XIX + verification block",
)

_CRIMINAL_COMPLAINT = PromptParts(
    system=(
        "You are drafting a private criminal complaint under BNSS "
        "s.223 (earlier CrPC s.200).\n"
        "MANDATORY OPENING: the first substantive paragraph MUST "
        "cite 'BNSS Section 223' (or 'BNSS s.223') by name — this "
        "is the procedural basis the Magistrate looks for when "
        "taking cognisance. The validator refuses drafts without it.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title: Complainant v. Accused (1..n).\n"
        " 2. Jurisdiction paragraph — territorial + BNSS s.223 competence "
        "(cite the statute by number here).\n"
        " 3. Parties paragraph — address + identifier for each.\n"
        " 4. Facts in chronological order, paragraph-numbered. Every "
        "factual paragraph must answer who / when / where / what.\n"
        " 5. Sections allegedly committed — BNS sections, each mapped "
        "to a specific factual paragraph.\n"
        " 6. Prior FIR position — if an FIR was filed, cite number + "
        "date + status; if not, explain why.\n"
        " 7. List of witnesses with identifiers.\n"
        " 8. Prayer: cognisance under BNSS s.223, summon the accused, "
        "proceed in accordance with law.\n"
        "RULES:\n"
        " - ALWAYS include the literal string 'BNSS s.223' in the "
        "body. Never skip the statute citation.\n"
        " - Never allege a section the facts don't disclose — courts "
        "dismiss at cognisance stage.\n"
        " - BNS sections, not IPC — unless the incident predates "
        "2024-07-01.\n"
        " - Witness list is a HARD requirement; do not leave it blank."
    ),
    focus="Private criminal complaint BNSS s.223 — BNS mapping per fact",
)

_CIVIL_SUIT = PromptParts(
    system=(
        "You are drafting a plaint in a civil suit. If the user has "
        "marked it a commercial suit, apply Commercial Courts Act, "
        "2015 requirements (pre-institution mediation under s.12A, "
        "strict timelines, specified Commercial Division).\n"
        "MANDATORY TERMINAL BLOCK: the plaint MUST end with a "
        "'PRAYER' heading (the literal word 'Prayer' or 'PRAYER' or "
        "'Reliefs Sought') followed by numbered relief clauses — "
        "(a), (b), (c)... — otherwise the registry rejects the filing. "
        "The validator searches for that heading; do not substitute "
        "'We request...' prose.\n"
        "REQUIRED STRUCTURE (CPC Order VII):\n"
        " 1. Court + suit number slot.\n"
        " 2. Cause title: Plaintiff v. Defendant.\n"
        " 3. Jurisdiction — territorial (s.20 CPC) + pecuniary + "
        "subject-matter.\n"
        " 4. Cause of action paragraph — date + place (mandatory).\n"
        " 5. Facts paragraph-numbered.\n"
        " 6. Legal grounds with statute references.\n"
        " 7. PRAYER block — the literal word 'Prayer' on its own line, "
        "followed by numbered relief clauses (a), (b), (c). One relief "
        "per clause; do NOT merge reliefs into a paragraph.\n"
        " 8. Valuation + court fee paragraph.\n"
        " 9. Verification block (CPC Order VI Rule 15).\n"
        "RULES:\n"
        " - Always include the cause-of-action date AND place.\n"
        " - Relief prayer must be in numbered clauses; a bundled "
        "relief paragraph is rejected at filing.\n"
        " - For commercial suits, DO include the s.12A pre-institution "
        "mediation recital (exempt only for urgent interim relief).\n"
        " - Valuation and court-fee paragraph: state the figure + the "
        "provision under which it is computed."
    ),
    focus="Civil plaint under CPC Order VII — s.12A if commercial",
)


_REGISTRY: dict[DraftTemplateType, PromptParts] = {
    DraftTemplateType.BAIL: _BAIL,
    DraftTemplateType.ANTICIPATORY_BAIL: _ANTICIPATORY_BAIL,
    DraftTemplateType.DIVORCE_PETITION: _DIVORCE,
    DraftTemplateType.PROPERTY_DISPUTE_NOTICE: _PROPERTY_NOTICE,
    DraftTemplateType.CHEQUE_BOUNCE_NOTICE: _CHEQUE_BOUNCE,
    DraftTemplateType.AFFIDAVIT: _AFFIDAVIT,
    DraftTemplateType.CRIMINAL_COMPLAINT: _CRIMINAL_COMPLAINT,
    DraftTemplateType.CIVIL_SUIT: _CIVIL_SUIT,
}


def get_prompt_parts(template_type: DraftTemplateType) -> PromptParts:
    """Return the specialised system prompt for ``template_type``."""
    return _REGISTRY[template_type]


__all__ = [
    "PromptParts",
    "get_prompt_parts",
]
