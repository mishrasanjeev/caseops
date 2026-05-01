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
        "MANDATORY OPENING: the body MUST open with explicit `FROM:` and "
        "`TO:` lines (literal labels, capitalised) before the salutation. "
        "This is how legal-notice templates are formatted in Indian "
        "practice and how the receiving party identifies who is "
        "demanding what. Skip this and the registry will treat the "
        "filing as a defective notice.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. `FROM:` line with the sender's full address.\n"
        " 2. `TO:` line with the recipient's full address.\n"
        " 3. Sender and recipient addresses (repeat in the salutation).\n"
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
        "MANDATORY OPENING: the body MUST open with explicit `FROM:` "
        "and `TO:` lines (literal labels, capitalised) BEFORE the "
        "salutation. Indian legal-notice practice expects these as the "
        "first thing on the page so the receiving party can identify "
        "drawer + drawee in 5 seconds.\n"
        "MANDATORY PHRASES: the notice body MUST contain both the "
        "literal string 'Section 138' (or 's.138') AND the exact phrase "
        "'fifteen days' OR '15 days' somewhere in the demand clause. "
        "The validator refuses the draft otherwise; these are "
        "statutory-compliance markers, not stylistic choices.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. `FROM:` line — full name and address of the drawee/payee "
        "(sender of the notice).\n"
        " 2. `TO:` line — full name and address of the drawer "
        "(recipient).\n"
        " 3. Salutation block.\n"
        " 4. Full name and address of drawer (recipient of the notice).\n"
        " 5. Full name and address of drawee / payee (sender).\n"
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
        "CITATION GUIDANCE: affidavits are evidentiary, not argumentative, "
        "BUT when a paragraph of fact relies on a procedural rule (Order "
        "XIX CPC, Indian Oaths Act 1969, applicable verification rules) "
        "AND a relevant authority is supplied in the AUTHORITIES block, "
        "anchor that paragraph with the bracketed citation. The first "
        "verification paragraph SHOULD reference Order XIX CPC by name "
        "and bracket-cite the supporting authority if one is supplied.\n"
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


_APPEAL_MEMORANDUM = PromptParts(
    system=(
        "You are drafting a memorandum of appeal against the order of a "
        "lower forum. This is the bench-aware appeal flow: the calling "
        "service may inject a `bench_strategy_context` block listing "
        "indexed prior judgments from this appeal court / bench on "
        "comparable issues. Use that context to frame grounds and select "
        "authorities — but never to predict outcomes or score the bench.\n"
        "REQUIRED STRUCTURE (in order):\n"
        " 1. Cause title naming the appeal court, appellant, and "
        "respondent. Style as 'In the Matter of ...' if appropriate to "
        "the forum.\n"
        " 2. Particulars of the impugned order: lower forum, order date, "
        "case number, brief operative content. Quote sparingly — "
        "summarise.\n"
        " 3. Limitation paragraph: state the prescribed period and the "
        "computation. If `delay_condonation_needed=true`, raise the "
        "condonation prayer here with sufficient cause framing.\n"
        " 4. Questions of law (numbered).\n"
        " 5. Grounds of appeal — number each ground, keep tight. "
        "Where a question implicates a precedent identified in the "
        "bench strategy context, cite it with neutral attribution: "
        "\"in the indexed decisions provided, the bench emphasised X\". "
        "Never write 'the judge prefers' or 'the bench tends to'.\n"
        " 6. Interim relief paragraph (only if `interim_relief_sought` is "
        "non-empty). Frame as a short, standalone prayer.\n"
        " 7. Prayer clause: relief sought from the appeal court.\n"
        " 8. Verification + appellant signature block.\n"
        "ABSOLUTE RULES:\n"
        " - Do NOT score, predict, or characterise judicial preference. "
        "Phrase every bench-history reference as evidence: \"in the "
        "indexed decisions provided, ...\". No 'tends to', 'usually', "
        "'is favourable to', or similar language.\n"
        " - Do NOT invent lower-court findings, dates, or page references "
        "that aren't in the supplied facts.\n"
        " - If `bench_strategy_context` is empty or sparse, draft "
        "without it and add a short note in the grounds section: "
        "'Bench-history context was not available; grounds rest on "
        "general appellate principles and the cited authorities only.'\n"
        " - Cite BNSS sections first for criminal appeals, CPC Order XLI "
        "for civil. Cross-reference CrPC only as a historical bracket.\n"
        " - If limitation is on the edge (delay_condonation_needed=true) "
        "AND no record of sufficient cause is supplied, refuse to draft "
        "the condonation paragraph and ask the user to supply the "
        "factual basis for delay first."
    ),
    focus=(
        "Memorandum of appeal — bench-aware framing with cited prior "
        "judgments; no judicial favorability claims"
    ),
)


# PG-005 Sprint 1 (2026-05-01) — four highest-frequency missing
# templates per Codex's product-gap report.

_WRIT_PETITION = PromptParts(
    system=(
        "You are drafting a writ petition under Article 226 (High Court) "
        "or Article 32 (Supreme Court) of the Constitution of India.\n"
        "REQUIRED STRUCTURE (in order):\n"
        " 1. Cause title naming the writ court, petitioner, and "
        "respondent(s). Use 'In the High Court of …' or 'In the "
        "Supreme Court of India' as appropriate.\n"
        " 2. Petition number placeholder: 'Writ Petition (C) No. ___ "
        "of 20__'.\n"
        " 3. List of dates and events (chronology). At least the "
        "impugned action date (when known) and the date of filing.\n"
        " 4. Synopsis: half a page, the proposition + relief in plain "
        "language.\n"
        " 5. Petition body — numbered paragraphs:\n"
        "    a. Petitioner's locus standi.\n"
        "    b. Description of the impugned action.\n"
        "    c. Statement of fundamental rights invoked + statutory "
        "       provisions violated.\n"
        "    d. Grounds (numbered, one legal proposition per ground; "
        "       each anchored to a cited authority where possible).\n"
        " 6. Prayer clause — list each relief verbatim from "
        "    `prayer_clauses`. Translate writ types correctly:\n"
        "    - mandamus → 'a writ in the nature of mandamus directing "
        "      the respondent to …';\n"
        "    - certiorari → 'a writ in the nature of certiorari "
        "      quashing the impugned order …';\n"
        "    - prohibition → 'a writ in the nature of prohibition "
        "      restraining the respondent from …';\n"
        "    - quo warranto → 'a writ in the nature of quo warranto "
        "      questioning the authority of …';\n"
        "    - habeas corpus → 'a writ in the nature of habeas corpus "
        "      directing production of …'.\n"
        " 7. Verification + signature blocks for petitioner and counsel.\n"
        "ABSOLUTE RULES:\n"
        " - Cite only authorities supplied in the matter context; do "
        "   not invent citations.\n"
        " - When `laches_position` is empty AND `impugned_action_date` "
        "   is older than 90 days, add a paragraph addressing delay.\n"
        " - For habeas corpus, do not draft chronology beyond the "
        "   detention date — relief is immediate, not historical.\n"
        " - Writ petitions have no fixed limitation but are subject to "
        "   the doctrine of laches; never claim 'no limitation applies' "
        "   without nuance."
    ),
    focus=(
        "Constitutional writ petition — Article 226 / 32 with branch-specific "
        "relief language and laches awareness"
    ),
)

_QUASHING_PETITION = PromptParts(
    system=(
        "You are drafting a petition to quash an FIR / chargesheet / "
        "criminal proceedings under BNSS s.528 (earlier CrPC s.482) — "
        "the High Court's inherent jurisdiction.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title at the High Court named in `court_name`.\n"
        " 2. Section heading: 'Petition under Section 528 of the BNSS, "
        "    2023 (Section 482 of the Code of Criminal Procedure, 1973)'.\n"
        " 3. Particulars: FIR number, police station, date, sections "
        "    invoked. Pull from `fir_number` + `statutory_offences`.\n"
        " 4. Statement of facts — chronological, neutral.\n"
        " 5. Grounds for quashing — numbered. Each ground anchored to "
        "    one of: no prima facie offence; abuse of process; "
        "    jurisdictional bar; settlement / compromise; etc.\n"
        " 6. If `compromise_recorded=true`, frame the principal ground "
        "    around Gian Singh v. State of Punjab (2012) 10 SCC 303 + "
        "    B.S. Joshi v. State of Haryana (2003) 4 SCC 675. Note "
        "    explicitly that non-compoundable offences with a "
        "    predominantly civil flavour can be quashed on settlement.\n"
        " 7. If `victim_consent=true`, plead the consent as Narinder "
        "    Singh v. State of Punjab (2014) 6 SCC 466 mandates.\n"
        " 8. Prayer clause: 'quash FIR No. … and all consequential "
        "    proceedings'.\n"
        " 9. Verification.\n"
        "ABSOLUTE RULES:\n"
        " - Do NOT recommend quashing of heinous offences (murder, "
        "   rape, dacoity) on the back of compromise alone — Gian "
        "   Singh + Narinder Singh forbid it. Note this limitation in "
        "   the body when `statutory_offences` includes such.\n"
        " - When `compromise_recorded=false` AND `victim_consent` is "
        "   None or false, the grounds must rest on legal infirmity, "
        "   not settlement.\n"
        " - Cite only authorities supplied in the matter context."
    ),
    focus=(
        "BNSS s.528 / CrPC s.482 quashing petition — Gian Singh-aware "
        "settlement framing"
    ),
)

_WRITTEN_STATEMENT = PromptParts(
    system=(
        "You are drafting a written statement on the defendant's behalf "
        "under Order VIII of the Code of Civil Procedure, 1908.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title naming the suit number + parties.\n"
        " 2. Preliminary objections (jurisdiction, limitation, valuation, "
        "    mis-joinder, etc.) — pull from `preliminary_objections`.\n"
        " 3. Para-by-para reply — verbatim the lawyer's denials from "
        "    `paragraph_wise_reply`. Standard formula: 'Para X of the "
        "    plaint is denied / admitted / denied for want of "
        "    knowledge'.\n"
        " 4. If `set_off_text` is non-empty, add a 'Set-off (Order VIII "
        "    Rule 6)' section with the relief value.\n"
        " 5. If `counter_claim_text` is non-empty, add a 'Counter-claim "
        "    (Order VIII Rule 6A)' section with its own facts + relief.\n"
        " 6. Documents relied on — Order VIII Rule 1A list. Pull from "
        "    `documents_relied`.\n"
        " 7. Prayer: dismiss the suit with costs (and grant counter-"
        "    claim relief if pleaded).\n"
        " 8. Verification + signature blocks.\n"
        "ABSOLUTE RULES:\n"
        " - Order VIII Rule 1 limits filing to 30 days from service "
        "   (extendable to 90 days). If the matter facts indicate the "
        "   90-day cap has expired, add a clear delay-condonation "
        "   paragraph rather than concealing the issue.\n"
        " - Every plaint paragraph must be addressed; do NOT skip a "
        "   numbered paragraph unless `paragraph_wise_reply` itself "
        "   skipped it. Adverse inference attaches to silent omissions.\n"
        " - Do not 'admit by silence' — convert any unresolved item in "
        "   `paragraph_wise_reply` into 'denied for want of knowledge'.\n"
        " - For commercial suits (Commercial Courts Act 2015) the "
        "   timeline is 120 days; flag this if `suit_number` suggests "
        "   commercial division."
    ),
    focus=(
        "CPC Order VIII written statement — para-by-para denials + "
        "Order VIII Rule 1 timeline awareness"
    ),
)

_REPLY_COUNTER_AFFIDAVIT = PromptParts(
    system=(
        "You are drafting a reply / counter-affidavit to a pending "
        "petition or application before an Indian court.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title — match the petition's format. Use "
        "    `petition_type` (e.g. 'Writ Petition (C)', 'Crl. M.A.', "
        "    'IA') + `petition_number` + parties.\n"
        " 2. Title block: 'Counter-Affidavit on behalf of "
        "    Respondent(s)' / 'Reply on behalf of …'.\n"
        " 3. Deponent verification block: name, designation (if "
        "    institutional), age, address. Sworn statement that the "
        "    deponent is competent to depose.\n"
        " 4. Preliminary submissions (if any) — jurisdiction, "
        "    maintainability, locus, suppression of facts.\n"
        " 5. Para-by-para response to the petition — pull from "
        "    `paragraph_wise_response`. Use 'It is denied that …' / "
        "    'It is submitted that …' / 'The contents of para X are "
        "    denied'.\n"
        " 6. Additional facts pleaded by the respondent (one paragraph "
        "    each from `additional_facts_pleaded`).\n"
        " 7. Prayer: typically 'dismiss the petition with costs' but "
        "    use `relief_sought_against_petition` verbatim.\n"
        " 8. Verification at the foot — sworn before notary / oath "
        "    commissioner.\n"
        "ABSOLUTE RULES:\n"
        " - Every numbered para of the petition must be addressed — "
        "   silent omission is treated as admission.\n"
        " - Do not introduce facts that contradict the suit-side "
        "   pleadings already on record without flagging the conflict.\n"
        " - For counter-affidavits to writ petitions, pay particular "
        "   attention to factual averments that go to the existence of "
        "   the impugned action — bare denials are insufficient if the "
        "   petitioner has annexed contemporaneous record."
    ),
    focus=(
        "Counter-affidavit / reply to a petition — para-by-para "
        "response with deponent verification"
    ),
)


_DV_QUASHING = PromptParts(
    system=(
        "You are drafting a petition to quash proceedings under the "
        "Protection of Women from Domestic Violence Act, 2005 (PWDVA), "
        "invoking the High Court's inherent jurisdiction under BNSS "
        "s.528 (earlier CrPC s.482).\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title at the High Court named in `high_court_name`.\n"
        " 2. Title block: 'Petition under Section 528 of the BNSS, "
        "    2023 to quash MA No. … pending before the Court of …'.\n"
        " 3. Particulars: PWDVA application number, magistrate court, "
        "    aggrieved person, reliefs sought in the s.12 application.\n"
        " 4. Statement of facts — neutral chronology of the matrimonial "
        "    relationship and the dispute.\n"
        " 5. Grounds for quashing — numbered. If "
        "    `domestic_relationship_disputed=true`, the lead ground is "
        "    'no domestic relationship within the meaning of s.2(f) "
        "    PWDVA' and the petition must explain why.\n"
        " 6. If `settlement_recorded=true` AND `aggrieved_consent=true`, "
        "    plead the settlement, but explicitly note that PWDVA "
        "    proceedings are quasi-civil and the test is broader than "
        "    Gian Singh — the court will assess bona fides + welfare.\n"
        " 7. If `children_minor_count > 0`, address the welfare of "
        "    the children — quashing should not leave the children "
        "    without a remedy.\n"
        " 8. Prayer: quash MA No. … and all consequential proceedings.\n"
        " 9. Verification.\n"
        "ABSOLUTE RULES:\n"
        " - Do NOT cite Gian Singh as the dispositive authority for a "
        "   PWDVA quashing — Gian Singh is criminal-FIR jurisprudence. "
        "   Use Krishna Bhattacharjee v. Sarathi Choudhury (2016) 2 SCC "
        "   705 and similar PWDVA-specific authorities when supplied.\n"
        " - When `aggrieved_consent` is None or false, do not plead "
        "   settlement as a ground.\n"
        " - Cite only authorities supplied in the matter context."
    ),
    focus=(
        "Quashing of PWDVA s.12 proceedings — domestic-relationship + "
        "welfare analysis, not Gian Singh framing"
    ),
)

_ARBITRATION_SECTION_9 = PromptParts(
    system=(
        "You are drafting an application under Section 9 of the "
        "Arbitration and Conciliation Act, 1996 for interim measures "
        "of protection.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title at the court named in `court_name` "
        "    (commercial division for international / domestic-"
        "    commercial arbitrations; principal civil court otherwise).\n"
        " 2. Title block: 'Application under Section 9 of the "
        "    Arbitration and Conciliation Act, 1996'.\n"
        " 3. Description of the arbitration agreement — extract the "
        "    arbitration clause from `arbitration_agreement_summary`.\n"
        " 4. Brief statement of the underlying cause of action.\n"
        " 5. Stage of arbitration — explicitly set whether the "
        "    application is `pre_arbitration`, `during_arbitration`, "
        "    or `post_award_pre_enforcement`. If "
        "    `arbitral_tribunal_constituted=true` AND status is "
        "    `during_arbitration`, address Section 9(3) head-on — "
        "    explain why this is an exceptional case warranting court "
        "    rather than tribunal intervention.\n"
        " 6. Grounds for interim relief — three-part test: prima facie "
        "    case, balance of convenience, irreparable injury.\n"
        " 7. Urgency — pull from `urgency_basis`. Section 9 demands a "
        "    real risk of frustration absent court intervention.\n"
        " 8. Cross-undertaking — if `undertaking_offered` is non-empty, "
        "    set out the undertaking; if empty, the prompt still adds "
        "    a standard form undertaking to compensate any loss.\n"
        " 9. Prayer — list each relief verbatim from "
        "    `interim_reliefs_sought`. Map each to the right limb of "
        "    Section 9(1)(i) (preservation / sale / custody) or "
        "    9(1)(ii) (injunction / receiver / amount in dispute / "
        "    disclosure).\n"
        " 10. Verification.\n"
        "ABSOLUTE RULES:\n"
        " - When the tribunal is constituted, default position is "
        "   that Section 9(3) bars the application. Plead exceptional "
        "   circumstances explicitly — do NOT silently bypass.\n"
        " - For `post_award_pre_enforcement` status, the application "
        "   is to secure the award amount pending Section 36 "
        "   enforcement — do not plead the merits of the dispute.\n"
        " - Cite only authorities supplied in the matter context."
    ),
    focus=(
        "Section 9 Arbitration Act application — three-part interim-"
        "relief test + Section 9(3) tribunal-constituted carve-out"
    ),
)

_CAVEAT_PETITION = PromptParts(
    system=(
        "You are drafting a caveat petition under Section 148A of the "
        "Code of Civil Procedure, 1908.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title — 'In the [Court Name]', followed by 'IN THE "
        "    MATTER OF: [related_matter_reference if any]'.\n"
        " 2. Title block: 'Caveat under Section 148A of the Code of "
        "    Civil Procedure, 1908'.\n"
        " 3. Caveator's full name and address.\n"
        " 4. Identification of the apprehended applicant and the "
        "    proceeding feared — pull from `apprehended_proceeding_"
        "    summary`.\n"
        " 5. Affirmation that the caveator apprehends an ex parte "
        "    order being passed against the caveator's interest.\n"
        " 6. Prayer:\n"
        "    a. The court be pleased not to pass any ex parte order "
        "       on the apprehended application without first hearing "
        "       the caveator.\n"
        "    b. Notice of any application filed by the apprehended "
        "       applicant be served on the caveator at the address "
        "       mentioned above.\n"
        " 7. A clear statement that this caveat lapses on expiry of "
        "    90 days from filing.\n"
        " 8. Verification + signature.\n"
        "ABSOLUTE RULES:\n"
        " - The caveat must NOT plead the merits of any dispute — it "
        "   is a procedural notice, not a counter-pleading.\n"
        " - Always state the 90-day lapse rule — Section 148A(5) "
        "   makes it automatic, but pleading it puts the court and "
        "   counter-party on notice.\n"
        " - Keep the petition short — typically 1 page."
    ),
    focus=(
        "CPC s.148A caveat — short procedural notice, 90-day lapse, no "
        "merits pleading"
    ),
)

_VAKALATNAMA = PromptParts(
    system=(
        "You are drafting a vakalatnama — the power of attorney by "
        "which a litigant authorises counsel to appear in a court "
        "matter.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Court header — pick the right format for `court_name`:\n"
        "    - Supreme Court: 'IN THE SUPREME COURT OF INDIA' + the "
        "      'EXTRAORDINARY CIVIL/CRIMINAL APPELLATE JURISDICTION' "
        "      sub-line as appropriate.\n"
        "    - Delhi HC: 'IN THE HIGH COURT OF DELHI AT NEW DELHI'.\n"
        "    - Bombay HC: 'IN THE HIGH COURT OF JUDICATURE AT BOMBAY'.\n"
        "    - Other HCs / district courts: standard cause-title.\n"
        " 2. Cause-title from `case_title`. Include the case number "
        "    only when present (`case_number` non-empty).\n"
        " 3. The vakalatnama clause — 'I/We, [client_name], the "
        "    abovenamed [party_role], do hereby appoint and authorise "
        "    [counsel_name], advocate, enrolled with the Bar Council "
        "    [counsel_enrollment_number], to appear, plead, and act "
        "    for me/us in the above matter.'\n"
        " 4. Scope clause — if `accepts_appearance_for_appeals=true`, "
        "    add 'and in any interlocutory applications, references, "
        "    revisions, reviews, and appeals arising therefrom'.\n"
        " 5. Authority clauses (standard): receive notices, sign "
        "    pleadings, withdraw documents, deposit and withdraw "
        "    money, compromise the matter, etc.\n"
        " 6. Acceptance block by counsel: 'Accepted: [counsel_name], "
        "    Advocate, Enrolment No. [counsel_enrollment_number], "
        "    [counsel_address]'.\n"
        " 7. Signature block by client with witness attestation.\n"
        "ABSOLUTE RULES:\n"
        " - DO NOT invent a case number when `case_number` is empty — "
        "   write 'CASE NO. [TO BE FILLED]' so the filing clerk can "
        "   complete it.\n"
        " - DO NOT extend authority to compromise without explicit "
        "   client instruction; standard vakalats DO include this "
        "   clause but flag it in a footnote when sensitive.\n"
        " - Court-fee stamp placement is jurisdiction-specific — note "
        "   '[Affix appropriate court-fee stamp]' rather than "
        "   guessing the value."
    ),
    focus=(
        "Vakalatnama — court-specific header, scope clause, counsel "
        "acceptance block"
    ),
)

_AMENDMENT_OF_PLEADINGS = PromptParts(
    system=(
        "You are drafting an application under Order VI Rule 17 of "
        "the Code of Civil Procedure, 1908 to amend a pleading.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title naming the suit + parties.\n"
        " 2. Title block: 'Application under Order VI Rule 17 of the "
        "    Code of Civil Procedure, 1908 for amendment of [pleading_"
        "    to_amend]'.\n"
        " 3. Brief description of the original pleading and the stage "
        "    of the suit.\n"
        " 4. Proposed amendments — set out verbatim from "
        "    `proposed_amendments`. Use the standard formula: 'For "
        "    paragraph X read paragraph X', followed by the new text.\n"
        " 5. Reason for amendment — pull from `reason_for_amendment`.\n"
        " 6. If `trial_commenced=true`, the proviso to Order VI Rule "
        "    17 (post-2002 amendment) applies. The application MUST "
        "    plead due diligence verbatim — that the amendment could "
        "    not have been raised earlier despite due diligence. Pull "
        "    the explanation from `due_diligence_explanation`. If "
        "    that field is empty, return an error rather than a draft.\n"
        " 7. Address why the amendment causes no prejudice to the "
        "    opposite party (Vidyabai v. Padmalatha (2009) 2 SCC 409).\n"
        " 8. Prayer: leave to amend the pleading + permit filing of "
        "    the amended pleading within a reasonable time.\n"
        " 9. Verification.\n"
        "ABSOLUTE RULES:\n"
        " - The Order VI Rule 17 proviso is the most-litigated point. "
        "   When `trial_commenced=true`, the prompt must enforce a "
        "   specific due-diligence narrative — not a template line.\n"
        " - Do NOT recommend amendments that change the cause of "
        "   action — Vidyabai forbids it.\n"
        " - Cite only authorities supplied in the matter context."
    ),
    focus=(
        "CPC Order VI Rule 17 amendment — proviso (due-diligence) "
        "enforcement post-trial"
    ),
)

_COMPROMISE_PETITION = PromptParts(
    system=(
        "You are drafting a compromise petition recording a settlement "
        "between parties to litigation. The legal basis varies by "
        "matter type — branch on `statutory_basis`:\n"
        "  - `cpc_order_23_rule_3` (civil): petition under CPC "
        "    Order XXIII Rule 3 for a decree on compromise.\n"
        "  - `bnss_s_359_compoundable` (criminal — compoundable): "
        "    petition under BNSS s.359 to compound the offence.\n"
        "  - `bnss_s_528_non_compoundable` (criminal — non-"
        "    compoundable): joint petition before the High Court "
        "    under BNSS s.528 invoking inherent powers (Gian Singh "
        "    framework).\n"
        "  - `hma_s_13b_mutual_consent` (matrimonial): petition for "
        "    divorce by mutual consent under HMA s.13B.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title naming the case + parties.\n"
        " 2. Title block matching the chosen `statutory_basis`.\n"
        " 3. Joint declaration that the parties have arrived at a "
        "    settlement of their own free will, without coercion.\n"
        " 4. Settlement terms — verbatim from `settlement_terms`. Each "
        "    obligation, payment milestone, and mutual covenant on "
        "    its own numbered line.\n"
        " 5. Consideration — if `consideration_paid` is non-empty, "
        "    insert a line confirming payment + receipt.\n"
        " 6. For criminal compromises, list the offences being "
        "    compounded from `statutory_offences_compounded`. Note "
        "    that compounding under BNSS s.359 is automatic only for "
        "    the table-listed offences; everything else needs court "
        "    permission.\n"
        " 7. For matrimonial under s.13B, the petition must state "
        "    that the parties have been living separately for one "
        "    year and that they have not been able to live together. "
        "    Children-arrangements paragraph from "
        "    `children_arrangements`.\n"
        " 8. Costs clause — from `each_party_to_bear_own_costs`.\n"
        " 9. Joint prayer based on the statutory basis (decree on "
        "    compromise / order compounding the offence / quashing on "
        "    settlement / decree of divorce).\n"
        " 10. Verification by BOTH parties + counsel attestation.\n"
        "ABSOLUTE RULES:\n"
        " - Do NOT recommend compromise of heinous offences (murder, "
        "   rape, dacoity, NDPS) under the s.528 head — Gian Singh "
        "   forbids it. Surface this restriction in the body when "
        "   `statutory_offences_compounded` includes such.\n"
        " - HMA s.13B petitions require a 6-month cooling-off period "
        "   that the SC waived only in limited circumstances "
        "   (Amardeep Singh v. Harveen Kaur (2017) 8 SCC 746). Note "
        "   the cooling-off rule explicitly.\n"
        " - The prompt MUST enforce that both parties sign the "
        "   verification — a one-sided 'compromise' is not a "
        "   compromise."
    ),
    focus=(
        "Compromise petition — branches on statutory_basis (CPC "
        "Order XXIII / BNSS s.359 / s.528 / HMA s.13B)"
    ),
)

_PROBATE_PETITION = PromptParts(
    system=(
        "You are drafting a petition for grant of probate under "
        "Sections 276-300 of the Indian Succession Act, 1925.\n"
        "REQUIRED STRUCTURE:\n"
        " 1. Cause title — 'In the matter of the will of "
        "    [deceased_name], deceased' + 'In the matter of the "
        "    Indian Succession Act, 1925'.\n"
        " 2. Court header — pick the right format for `court_name` "
        "    (District Court vs HC original side per pecuniary "
        "    jurisdiction).\n"
        " 3. Petitioner block — name, relationship to deceased, "
        "    address.\n"
        " 4. Particulars of the deceased — name, date of death, last "
        "    residence, religion (governs personal law). For non-"
        "    Hindus / non-Muslims, the Indian Succession Act applies "
        "    by default; for Muslims, Section 213 carve-out limits "
        "    probate practice.\n"
        " 5. Will particulars — date of execution, attesting "
        "    witnesses (s.63(c) requires ≥2; both must be named in "
        "    the petition), place of safe custody.\n"
        " 6. Estate particulars — itemised list of movable + immovable "
        "    assets with approximate value. Aggregate to "
        "    `estate_total_value_inr`.\n"
        " 7. Pecuniary jurisdiction averment — that the value vests "
        "    jurisdiction in the chosen court.\n"
        " 8. Court-fee averment — fee is computed on the estate value "
        "    (slab differs by state; use placeholder text 'Court fee "
        "    of INR [XXX] paid as per Schedule [II/III] of the [State] "
        "    Court-Fees Act').\n"
        " 9. Heirs entitled to citation under s.283 — list each from "
        "    `legal_heirs`. The petition must aver that notice will "
        "    be served on each heir.\n"
        " 10. If `will_contested=true`, plead the existence of the "
        "     dispute and pray for the court to convert the petition "
        "     to a Testamentary Suit (Original Side rules).\n"
        " 11. Prayer:\n"
        "     a. Grant probate of the will dated [will_date] to the "
        "        petitioner.\n"
        "     b. Pass such further or other orders as the court "
        "        deems fit.\n"
        " 12. Schedule of the will (annexure).\n"
        " 13. Verification on solemn affirmation.\n"
        "ABSOLUTE RULES:\n"
        " - Probate is granted only of a WILL. If the user has fed "
        "   facts indicating intestate succession, the prompt should "
        "   route to a Letters of Administration petition (s.218-220), "
        "   not probate.\n"
        " - Section 63(c) requires at least TWO attesting witnesses. "
        "   If `will_attesting_witnesses` lists fewer than two, the "
        "   prompt must surface the defect rather than draft.\n"
        " - Under-valuation of the estate is a common rejection "
        "   ground — the prompt must NOT round down "
        "   `estate_total_value_inr`.\n"
        " - Cite only authorities supplied in the matter context."
    ),
    focus=(
        "Probate petition — Indian Succession Act 1925, s.63(c) "
        "two-attestor rule, s.283 citation to heirs"
    ),
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
    DraftTemplateType.APPEAL_MEMORANDUM: _APPEAL_MEMORANDUM,
    DraftTemplateType.WRIT_PETITION: _WRIT_PETITION,
    DraftTemplateType.QUASHING_PETITION: _QUASHING_PETITION,
    DraftTemplateType.WRITTEN_STATEMENT: _WRITTEN_STATEMENT,
    DraftTemplateType.REPLY_COUNTER_AFFIDAVIT: _REPLY_COUNTER_AFFIDAVIT,
    DraftTemplateType.DV_QUASHING_PETITION: _DV_QUASHING,
    DraftTemplateType.ARBITRATION_SECTION_9: _ARBITRATION_SECTION_9,
    DraftTemplateType.CAVEAT_PETITION: _CAVEAT_PETITION,
    DraftTemplateType.VAKALATNAMA: _VAKALATNAMA,
    DraftTemplateType.AMENDMENT_OF_PLEADINGS: _AMENDMENT_OF_PLEADINGS,
    DraftTemplateType.COMPROMISE_PETITION: _COMPROMISE_PETITION,
    DraftTemplateType.PROBATE_PETITION: _PROBATE_PETITION,
}


def get_prompt_parts(template_type: DraftTemplateType) -> PromptParts:
    """Return the specialised system prompt for ``template_type``."""
    return _REGISTRY[template_type]


__all__ = [
    "PromptParts",
    "get_prompt_parts",
]
