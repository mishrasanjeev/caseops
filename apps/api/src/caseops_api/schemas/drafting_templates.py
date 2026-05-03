"""Sprint R1 — per-draft-type form schemas.

Each ``DraftTemplate`` captures the fact-pattern a lawyer must supply
before the drafting pipeline can generate a first-cut pleading. The
fields double as:

1. the React Hook Form + Zod stepper fields on the web (R3), and
2. the fact-block fed into the matching per-type system prompt in
   ``services/drafting_prompts.py`` (R2).

Each field uses a ``DraftingField`` that carries both the Pydantic
type and the UX hints (step, placeholder, example). The stepper reads
the JSON schema emitted by ``to_form_schema()``; nothing is duplicated.

We keep the enum separate from ``db.models.DraftType`` on purpose.
The DB column stays at the existing high-level grouping
(brief / notice / reply / memo / other) so we don't need a migration;
the template type layers on top at the application edge.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftTemplateType(StrEnum):
    """Specialised drafting templates.

    Ordered roughly by how frequently Indian litigators use them (bail
    applications dominate HC criminal-side work).
    """

    BAIL = "bail"
    ANTICIPATORY_BAIL = "anticipatory_bail"
    DIVORCE_PETITION = "divorce_petition"
    PROPERTY_DISPUTE_NOTICE = "property_dispute_notice"
    CHEQUE_BOUNCE_NOTICE = "cheque_bounce_notice"
    AFFIDAVIT = "affidavit"
    CRIMINAL_COMPLAINT = "criminal_complaint"
    CIVIL_SUIT = "civil_suit"
    # BAAD-001 (Sprint P5, 2026-04-25). Appeal memorandum: the
    # bench-aware drafting flow's anchor template. Covers HC appeals
    # under Letters Patent / civil + criminal appellate-side practice.
    APPEAL_MEMORANDUM = "appeal_memorandum"
    # PG-005 Sprint 1 (2026-05-01). Four highest-frequency missing
    # templates per Codex's product-gap report.
    WRIT_PETITION = "writ_petition"
    QUASHING_PETITION = "quashing_petition"
    WRITTEN_STATEMENT = "written_statement"
    REPLY_COUNTER_AFFIDAVIT = "reply_counter_affidavit"
    # PG-005 Sprint 2 (2026-05-01). Seven additional templates covering
    # daily Indian-litigation filings — DV-quashing, arbitration interim
    # measures, caveat, vakalatnama, amendment of pleadings, compromise,
    # and probate.
    DV_QUASHING_PETITION = "dv_quashing_petition"
    ARBITRATION_SECTION_9 = "arbitration_section_9"
    CAVEAT_PETITION = "caveat_petition"
    VAKALATNAMA = "vakalatnama"
    AMENDMENT_OF_PLEADINGS = "amendment_of_pleadings"
    COMPROMISE_PETITION = "compromise_petition"
    PROBATE_PETITION = "probate_petition"
    # MOD-LSE-3 (2026-05-03) — Supreme Court and escalation pack. Eleven
    # templates that cover the SC appellate ladder + the procedural
    # accompaniments that must be filed alongside an SLP / appeal.
    SPECIAL_LEAVE_PETITION = "special_leave_petition"
    SUPREME_COURT_APPEAL = "supreme_court_appeal"
    REVIEW_PETITION = "review_petition"
    CURATIVE_PETITION = "curative_petition"
    TRANSFER_PETITION = "transfer_petition"
    CONTEMPT_PETITION = "contempt_petition"
    INTERIM_RELIEF_APPLICATION = "interim_relief_application"
    CONDONATION_OF_DELAY = "condonation_of_delay"
    EXEMPTION_APPLICATION = "exemption_application"
    SYNOPSIS_LIST_OF_DATES = "synopsis_list_of_dates"
    FILING_INDEX_CHECKLIST = "filing_index_checklist"


DraftTemplateTypeLiteral = Literal[
    "bail",
    "anticipatory_bail",
    "divorce_petition",
    "property_dispute_notice",
    "cheque_bounce_notice",
    "affidavit",
    "criminal_complaint",
    "civil_suit",
    "appeal_memorandum",
    "writ_petition",
    "quashing_petition",
    "written_statement",
    "reply_counter_affidavit",
    "dv_quashing_petition",
    "arbitration_section_9",
    "caveat_petition",
    "vakalatnama",
    "amendment_of_pleadings",
    "compromise_petition",
    "probate_petition",
    # MOD-LSE-3 (2026-05-03) — SC + escalation pack.
    "special_leave_petition",
    "supreme_court_appeal",
    "review_petition",
    "curative_petition",
    "transfer_petition",
    "contempt_petition",
    "interim_relief_application",
    "condonation_of_delay",
    "exemption_application",
    "synopsis_list_of_dates",
    "filing_index_checklist",
]


class DraftingFieldSpec(BaseModel):
    """UX-facing description of one input on the stepper form.

    The stepper consumes this shape directly; do not add rendering
    logic here. The Pydantic model below each enum branch gives the
    authoritative *type* check — this spec gives the *presentation*.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    kind: Literal["string", "text", "date", "number", "boolean", "enum"] = "string"
    required: bool = True
    placeholder: str | None = None
    help_text: str | None = None
    example: str | None = None
    enum_options: list[str] | None = None
    step_group: str = "facts"


# ---------------------------------------------------------------
# Per-template Pydantic fact models.
#
# Each inherits ``_TemplateFactsBase`` so the drafting_prompts layer
# can rely on the common shape (matter_id + optional focus_note).
# ---------------------------------------------------------------


class _TemplateFactsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter_id: str = Field(min_length=1, max_length=36)
    focus_note: str | None = Field(default=None, max_length=4000)


class BailFacts(_TemplateFactsBase):
    """Regular bail under BNSS s.483 (earlier CrPC s.439)."""

    accused_name: str = Field(min_length=2, max_length=255)
    fir_number: str = Field(min_length=1, max_length=120)
    police_station: str = Field(min_length=2, max_length=255)
    sections_charged: list[str] = Field(default_factory=list, max_length=40)
    custody_since: str = Field(
        min_length=10,
        max_length=10,
        description="ISO date the accused entered custody (yyyy-mm-dd).",
    )
    court_name: str = Field(min_length=2, max_length=255)
    prior_bail_applications: int = Field(default=0, ge=0, le=20)
    grounds_brief: str = Field(min_length=40, max_length=4000)


class AnticipatoryBailFacts(_TemplateFactsBase):
    """Anticipatory bail under BNSS s.482 (earlier CrPC s.438)."""

    applicant_name: str = Field(min_length=2, max_length=255)
    fir_number: str | None = Field(default=None, max_length=120)
    apprehended_sections: list[str] = Field(default_factory=list, max_length=40)
    police_station: str = Field(min_length=2, max_length=255)
    court_name: str = Field(min_length=2, max_length=255)
    apprehension_grounds: str = Field(min_length=40, max_length=4000)
    has_received_notice: bool = False


class DivorcePetitionFacts(_TemplateFactsBase):
    """Hindu Marriage Act / Special Marriage Act petition."""

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=255)
    marriage_date: str = Field(min_length=10, max_length=10)
    marriage_place: str = Field(min_length=2, max_length=255)
    separation_date: str | None = Field(default=None, max_length=10)
    grounds: list[str] = Field(default_factory=list, max_length=10)
    act_governing: Literal["HMA", "SMA", "INDIAN_CHRISTIAN", "OTHER"] = "HMA"
    children_details: str | None = Field(default=None, max_length=2000)
    court_name: str = Field(min_length=2, max_length=255)


class PropertyDisputeNoticeFacts(_TemplateFactsBase):
    """Pre-litigation demand notice in a property dispute."""

    sender_name: str = Field(min_length=2, max_length=255)
    recipient_name: str = Field(min_length=2, max_length=255)
    property_address: str = Field(min_length=10, max_length=1000)
    property_type: Literal["land", "flat", "house", "commercial", "other"] = "flat"
    title_basis: Literal["sale_deed", "inheritance", "will", "gift_deed", "other"] = "sale_deed"
    relief_sought: str = Field(min_length=40, max_length=4000)
    response_deadline_days: int = Field(default=15, ge=7, le=60)


class ChequeBounceNoticeFacts(_TemplateFactsBase):
    """Demand notice under s.138 of the Negotiable Instruments Act."""

    drawer_name: str = Field(min_length=2, max_length=255)
    drawee_name: str = Field(min_length=2, max_length=255)
    cheque_number: str = Field(min_length=1, max_length=40)
    cheque_date: str = Field(min_length=10, max_length=10)
    cheque_amount_inr: float = Field(gt=0)
    bank_name: str = Field(min_length=2, max_length=255)
    bank_memo_date: str = Field(min_length=10, max_length=10)
    dishonour_reason: Literal[
        "insufficient_funds", "exceeds_arrangement", "payment_stopped", "other"
    ] = "insufficient_funds"
    demand_statutory_deadline_days: Literal[15] = 15


class AffidavitFacts(_TemplateFactsBase):
    """Generic evidentiary affidavit."""

    deponent_name: str = Field(min_length=2, max_length=255)
    deponent_age: int = Field(ge=18, le=120)
    deponent_occupation: str = Field(min_length=2, max_length=255)
    deponent_address: str = Field(min_length=10, max_length=1000)
    statement_paragraphs: list[str] = Field(min_length=1, max_length=40)
    sworn_place: str = Field(min_length=2, max_length=255)
    sworn_date: str = Field(min_length=10, max_length=10)


class CriminalComplaintFacts(_TemplateFactsBase):
    """Private complaint under BNSS s.223 (earlier CrPC s.200)."""

    complainant_name: str = Field(min_length=2, max_length=255)
    accused_name: str = Field(min_length=2, max_length=255)
    alleged_sections: list[str] = Field(default_factory=list, max_length=40)
    incident_date: str = Field(min_length=10, max_length=10)
    incident_place: str = Field(min_length=2, max_length=1000)
    narrative: str = Field(min_length=80, max_length=6000)
    witness_count: int = Field(default=0, ge=0, le=50)
    prior_fir_filed: bool = False
    court_name: str = Field(min_length=2, max_length=255)


class CivilSuitFacts(_TemplateFactsBase):
    """Plaint in a civil suit (CPC / Commercial Courts Act)."""

    plaintiff_name: str = Field(min_length=2, max_length=255)
    defendant_name: str = Field(min_length=2, max_length=255)
    cause_of_action_date: str = Field(min_length=10, max_length=10)
    cause_of_action_place: str = Field(min_length=2, max_length=1000)
    suit_valuation_inr: float = Field(gt=0)
    relief_sought: list[str] = Field(min_length=1, max_length=12)
    is_commercial_suit: bool = False
    court_name: str = Field(min_length=2, max_length=255)
    facts_brief: str = Field(min_length=80, max_length=6000)


class AppealMemorandumFacts(_TemplateFactsBase):
    """BAAD-001 (Sprint P5, 2026-04-25) — appeal memorandum.

    Field set per the bench-aware appeal drafting brief
    (`docs/BENCH_AWARE_APPEAL_DRAFTING_TASKLIST_2026-04-24.md`).
    Captures everything the prompt needs to frame an evidence-backed
    appeal — and crucially captures the appeal court so the bench
    strategy context service can fetch the right judge / bench history.
    """

    appellant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=255)
    impugned_order_summary: str = Field(min_length=40, max_length=4000)
    impugned_order_date: str = Field(
        min_length=10,
        max_length=10,
        description="ISO date of the impugned order (yyyy-mm-dd).",
    )
    lower_forum_name: str = Field(min_length=2, max_length=255)
    appeal_court_name: str = Field(
        min_length=2,
        max_length=255,
        description="Forum the appeal will be filed in (HC division, SC, etc.).",
    )
    questions_of_law: list[str] = Field(default_factory=list, max_length=20)
    grounds_brief: str = Field(min_length=80, max_length=6000)
    interim_relief_sought: str | None = Field(default=None, max_length=2000)
    delay_condonation_needed: bool = False
    delay_condonation_days: int | None = Field(default=None, ge=0, le=10000)
    record_references: str | None = Field(default=None, max_length=4000)


class WritPetitionFacts(_TemplateFactsBase):
    """Article 226 (HC) / Article 32 (SC) writ petition.

    The shape covers all five writ types; the prompt branches on
    `writ_type` to enforce the right relief language (mandamus
    compels, certiorari quashes, prohibition stops, quo warranto
    questions office, habeas corpus produces the body).
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(
        min_length=2,
        max_length=500,
        description="Usually 'State of X' / 'Union of India'; multi-respondent supported.",
    )
    writ_court: Literal["high_court", "supreme_court"] = "high_court"
    writ_type: Literal[
        "mandamus", "certiorari", "prohibition", "quo_warranto", "habeas_corpus",
    ] = "mandamus"
    impugned_action: str = Field(
        min_length=20,
        max_length=4000,
        description="The order / act / policy / inaction under challenge.",
    )
    impugned_action_date: str | None = Field(
        default=None,
        max_length=10,
        description="ISO yyyy-mm-dd; omit when challenging continuing inaction.",
    )
    fundamental_rights_invoked: list[str] = Field(
        default_factory=list,
        max_length=15,
        description="e.g. ['Article 14', 'Article 21'].",
    )
    statutory_violations: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Statutory provisions the impugned action violates.",
    )
    prayer_clauses: list[str] = Field(
        min_length=1,
        max_length=15,
        description="Reliefs sought, one per line. Mandamus → 'direct respondent to…' etc.",
    )
    interim_relief_sought: str | None = Field(default=None, max_length=2000)
    laches_position: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Explanation if filed late (writs have no fixed "
            "limitation but laches matters)."
        ),
    )


class QuashingPetitionFacts(_TemplateFactsBase):
    """Quashing petition under BNSS s.528 (earlier CrPC s.482).

    Per Gian Singh + B.S. Joshi + Narinder Singh, compromise +
    victim_consent are dispositive on whether a non-compoundable
    matter can be quashed. The prompt enforces that framing.
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    fir_number: str | None = Field(
        default=None,
        max_length=120,
        description="FIR / chargesheet number being challenged.",
    )
    police_station: str | None = Field(default=None, max_length=255)
    impugned_proceedings_summary: str = Field(
        min_length=40,
        max_length=4000,
        description="The investigation / chargesheet / order under challenge.",
    )
    statutory_offences: list[str] = Field(
        default_factory=list,
        max_length=40,
        description="BNS / IPC sections the petitioner is charged under.",
    )
    grounds_for_quashing: str = Field(min_length=40, max_length=4000)
    compromise_recorded: bool = Field(
        default=False,
        description="Has the matter been compromised between parties? Triggers Gian Singh framing.",
    )
    victim_consent: bool | None = Field(
        default=None,
        description=(
            "Has the victim explicitly consented to quashing? "
            "None when not yet ascertained."
        ),
    )
    court_name: str = Field(min_length=2, max_length=255)


class WrittenStatementFacts(_TemplateFactsBase):
    """Written statement under CPC Order VIII.

    Defendant-side response to a plaint. Order VIII Rule 1 sets a
    30-day default with a 90-day cap; the prompt flags this as a
    drop-dead deadline.
    """

    defendant_name: str = Field(min_length=2, max_length=255)
    plaintiff_name: str = Field(min_length=2, max_length=255)
    suit_number: str = Field(min_length=1, max_length=120)
    court_name: str = Field(min_length=2, max_length=255)
    preliminary_objections: list[str] = Field(
        default_factory=list,
        max_length=15,
        description="Jurisdiction, limitation, mis-joinder, valuation, etc.",
    )
    paragraph_wise_reply: str = Field(
        min_length=80,
        max_length=8000,
        description=(
            "Para-by-para denials of the plaint. Use 'Para X is denied' / "
            "'Para X is admitted' / 'Para X is denied for want of knowledge'."
        ),
    )
    counter_claim_text: str | None = Field(default=None, max_length=4000)
    set_off_text: str | None = Field(default=None, max_length=4000)
    limitation_defence: str | None = Field(default=None, max_length=2000)
    documents_relied: list[str] = Field(
        default_factory=list,
        max_length=40,
        description="List of docs relied on by defendant; goes into the Order VIII Rule 1A list.",
    )


class ReplyCounterAffidavitFacts(_TemplateFactsBase):
    """Reply / counter-affidavit to any pending petition or application.

    Generic shape covering writ counter-affidavits, IA replies, MA
    replies, etc. The prompt branches on petition_type when supplied.
    """

    deponent_name: str = Field(min_length=2, max_length=255)
    deponent_designation: str | None = Field(default=None, max_length=255)
    deponent_address: str = Field(min_length=10, max_length=1000)
    petition_number: str = Field(min_length=1, max_length=120)
    petition_type: str | None = Field(
        default=None,
        max_length=120,
        description="Writ Petition (C) / Crl. M.A. / IA / MA — for the cause-title hint.",
    )
    main_petition_summary: str = Field(
        min_length=40,
        max_length=4000,
        description="Short summary of what the original petition seeks.",
    )
    court_name: str = Field(min_length=2, max_length=255)
    paragraph_wise_response: str = Field(
        min_length=80,
        max_length=8000,
        description="Para-by-para reply to the petition's averments.",
    )
    additional_facts_pleaded: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="New facts the respondent introduces.",
    )
    preliminary_submissions: str | None = Field(default=None, max_length=4000)
    relief_sought_against_petition: str = Field(
        min_length=20,
        max_length=2000,
        description="Typically 'dismiss the petition' but may include conditional relief.",
    )


class DvQuashingPetitionFacts(_TemplateFactsBase):
    """Quashing of proceedings under the Protection of Women from
    Domestic Violence Act, 2005 (PWDVA).

    The application is filed in the High Court under BNSS s.528 / CrPC
    s.482, and the framing is materially different from a regular
    quashing petition because the impugned proceedings are quasi-civil
    (PWDVA s.12 application before a magistrate) rather than a pure
    criminal FIR. Compromise + the aggrieved person's consent are
    relevant but do not have the same dispositive weight as in a
    Gian Singh setting; courts typically demand bona fides + welfare-
    of-children analysis.
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    aggrieved_person_name: str = Field(
        min_length=2,
        max_length=255,
        description="Original PWDVA s.12 applicant (the aggrieved person).",
    )
    pwdva_application_number: str = Field(
        min_length=1,
        max_length=120,
        description="Magistrate-court PWDVA application number being challenged.",
    )
    magistrate_court_name: str = Field(min_length=2, max_length=255)
    high_court_name: str = Field(min_length=2, max_length=255)
    impugned_reliefs_in_pwdva_app: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Which PWDVA s.18-22 reliefs the aggrieved person sought "
            "(protection / residence / monetary / custody / compensation)."
        ),
    )
    grounds_for_quashing: str = Field(min_length=40, max_length=4000)
    domestic_relationship_disputed: bool = Field(
        default=False,
        description=(
            "Has the petitioner pleaded that no domestic relationship "
            "exists (s.2(f) PWDVA)? Goes to maintainability."
        ),
    )
    settlement_recorded: bool = Field(default=False)
    aggrieved_consent: bool | None = Field(default=None)
    children_minor_count: int = Field(
        default=0,
        ge=0,
        le=20,
        description="Welfare of children is a factor in PWDVA quashing.",
    )


class ArbitrationSection9Facts(_TemplateFactsBase):
    """Application under Section 9 of the Arbitration & Conciliation
    Act, 1996 for interim measures of protection.

    Filed in the High Court (commercial division) for international /
    domestic-commercial arbitrations, otherwise in the principal civil
    court of original jurisdiction. Section 9 can be invoked
    pre-arbitration, during arbitration (subject to s.9(3)), or after
    the award but before enforcement under s.36.
    """

    applicant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    court_name: str = Field(min_length=2, max_length=255)
    arbitration_status: Literal[
        "pre_arbitration", "during_arbitration", "post_award_pre_enforcement",
    ] = "pre_arbitration"
    arbitration_agreement_summary: str = Field(
        min_length=40,
        max_length=2000,
        description="Clause / agreement that triggers Section 9 jurisdiction.",
    )
    arbitral_tribunal_constituted: bool = Field(default=False)
    interim_reliefs_sought: list[str] = Field(
        min_length=1,
        max_length=15,
        description=(
            "Reliefs under s.9(1)(i) (preservation / custody / sale of "
            "goods) or s.9(1)(ii) (interim injunction / receiver / "
            "amount in dispute / disclosure)."
        ),
    )
    underlying_cause_of_action: str = Field(min_length=40, max_length=4000)
    urgency_basis: str = Field(
        min_length=20,
        max_length=2000,
        description="Why interim relief cannot await arbitral tribunal.",
    )
    undertaking_offered: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Cross-undertaking the applicant offers; standard practice "
            "is an undertaking to compensate for any loss caused by "
            "interim relief."
        ),
    )


class CaveatPetitionFacts(_TemplateFactsBase):
    """Caveat petition under CPC Section 148A — filed by a person who
    apprehends an ex parte order against them.

    Short, formal pleading. The court must not pass any order without
    first hearing the caveator. Caveat lapses after 90 days unless
    renewed.
    """

    caveator_name: str = Field(min_length=2, max_length=255)
    caveator_address: str = Field(min_length=10, max_length=1000)
    apprehended_applicant_name: str = Field(
        min_length=2,
        max_length=500,
        description="The person likely to file an application against the caveator.",
    )
    apprehended_proceeding_summary: str = Field(
        min_length=40,
        max_length=2000,
        description=(
            "What the caveator apprehends — e.g. anticipatory injunction, "
            "stay application, contempt petition."
        ),
    )
    court_name: str = Field(min_length=2, max_length=255)
    related_matter_reference: str | None = Field(
        default=None,
        max_length=300,
        description="Existing case number, FIR, or contract dispute reference.",
    )
    counsel_name: str | None = Field(default=None, max_length=255)


class VakalatnamaFacts(_TemplateFactsBase):
    """Power-of-attorney / vakalatnama executed by a litigant
    authorising counsel to appear and conduct the case.

    Trivial in legal substance but every fee-earner files one with
    every appearance. Court-specific formats exist (Delhi HC, Bombay HC,
    SC) — the prompt picks the right header based on `court_name`.
    """

    client_name: str = Field(min_length=2, max_length=255)
    client_address: str = Field(min_length=10, max_length=1000)
    counsel_name: str = Field(min_length=2, max_length=255)
    counsel_enrollment_number: str = Field(
        min_length=2,
        max_length=120,
        description="Bar council enrollment number — court-rule requirement.",
    )
    counsel_address: str = Field(min_length=10, max_length=1000)
    case_title: str = Field(
        min_length=2,
        max_length=500,
        description="A v. B — appears in the cause title.",
    )
    case_number: str | None = Field(
        default=None,
        max_length=120,
        description="Empty when filing fresh; vakalat goes with the plaint.",
    )
    court_name: str = Field(min_length=2, max_length=255)
    party_role: Literal[
        "plaintiff", "defendant", "petitioner", "respondent",
        "appellant", "applicant", "objector",
    ] = "petitioner"
    accepts_appearance_for_appeals: bool = Field(
        default=True,
        description=(
            "Standard vakalat extends to interim applications + appeals; "
            "set false to limit scope."
        ),
    )


class AmendmentOfPleadingsFacts(_TemplateFactsBase):
    """Application under CPC Order VI Rule 17 to amend a plaint or
    written statement.

    Post-2002 CPC amendment, applications after trial commences are
    barred unless the proviso (`due diligence`) is satisfied. The
    prompt enforces that test.
    """

    applicant_name: str = Field(min_length=2, max_length=255)
    applicant_role: Literal[
        "plaintiff", "defendant", "petitioner", "respondent",
    ] = "plaintiff"
    suit_number: str = Field(min_length=1, max_length=120)
    court_name: str = Field(min_length=2, max_length=255)
    pleading_to_amend: Literal[
        "plaint", "written_statement", "petition", "counter_affidavit",
    ] = "plaint"
    proposed_amendments: str = Field(
        min_length=40,
        max_length=8000,
        description=(
            "Verbatim text of the additions / deletions sought, "
            "paragraph-numbered."
        ),
    )
    reason_for_amendment: str = Field(min_length=40, max_length=4000)
    trial_commenced: bool = Field(
        default=False,
        description=(
            "Triggers the Order VI Rule 17 proviso (due-diligence test "
            "post-2002 amendment)."
        ),
    )
    due_diligence_explanation: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Required when `trial_commenced=true`. Explain why the "
            "amendment could not have been raised earlier despite due "
            "diligence."
        ),
    )
    prejudice_to_opposite_party: str | None = Field(
        default=None,
        max_length=2000,
        description="Address why the amendment causes no prejudice.",
    )


class CompromisePetitionFacts(_TemplateFactsBase):
    """Compromise petition recording a settlement between parties.

    Civil — under CPC Order XXIII Rule 3 (compromise decree). Criminal
    — under BNSS s.359 (CrPC s.320 historical) for compoundable
    offences, or under BNSS s.528 / CrPC s.482 (Gian Singh framework)
    for non-compoundable settlements.
    """

    matter_type: Literal["civil", "criminal", "matrimonial"] = "civil"
    party_a_name: str = Field(min_length=2, max_length=500)
    party_b_name: str = Field(min_length=2, max_length=500)
    case_number: str = Field(min_length=1, max_length=120)
    court_name: str = Field(min_length=2, max_length=255)
    statutory_basis: Literal[
        "cpc_order_23_rule_3",
        "bnss_s_359_compoundable",
        "bnss_s_528_non_compoundable",
        "hma_s_13b_mutual_consent",
    ] = "cpc_order_23_rule_3"
    settlement_terms: str = Field(
        min_length=80,
        max_length=8000,
        description=(
            "Verbatim terms of the compromise — payment schedule, "
            "withdrawal of allegations, mutual obligations, etc."
        ),
    )
    consideration_paid: str | None = Field(
        default=None,
        max_length=500,
        description="E.g. 'INR 5,00,000 paid via NEFT on 2026-04-15'.",
    )
    each_party_to_bear_own_costs: bool = Field(default=True)
    children_arrangements: str | None = Field(
        default=None,
        max_length=2000,
        description="For matrimonial settlements only.",
    )
    statutory_offences_compounded: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="For criminal compromises — sections being compounded.",
    )


class ProbatePetitionFacts(_TemplateFactsBase):
    """Probate petition under Sections 276-300 of the Indian
    Succession Act, 1925.

    Filed in the District Court (or HC original side, depending on
    pecuniary jurisdiction). Probate is granted only of a will. For
    intestate succession the lawyer files Letters of Administration
    (s.218-220).
    """

    petitioner_name: str = Field(
        min_length=2,
        max_length=255,
        description="The executor named in the will (or the LR if no executor).",
    )
    petitioner_relationship_to_deceased: str = Field(
        min_length=2,
        max_length=255,
    )
    deceased_name: str = Field(min_length=2, max_length=255)
    deceased_date_of_death: str = Field(
        min_length=10,
        max_length=10,
        description="ISO yyyy-mm-dd.",
    )
    deceased_last_residence: str = Field(min_length=10, max_length=500)
    deceased_religion: Literal[
        "hindu", "muslim", "christian", "parsi", "jew", "other",
    ] = "hindu"
    will_date: str = Field(
        min_length=10,
        max_length=10,
        description="ISO yyyy-mm-dd of will execution.",
    )
    will_attesting_witnesses: list[str] = Field(
        min_length=2,
        max_length=10,
        description=(
            "Indian Succession Act s.63(c) requires at least two "
            "attesting witnesses; both must be named here."
        ),
    )
    estate_assets_summary: str = Field(
        min_length=40,
        max_length=8000,
        description=(
            "Movable + immovable assets with approximate value. Court "
            "fee is computed on this — under-valuation is a common "
            "rejection ground."
        ),
    )
    estate_total_value_inr: float = Field(
        gt=0,
        description="Aggregate value drives pecuniary jurisdiction + court fee.",
    )
    legal_heirs: list[str] = Field(
        min_length=1,
        max_length=30,
        description="Each LR who would inherit under intestacy — they get notice.",
    )
    will_contested: bool = Field(default=False)
    court_name: str = Field(min_length=2, max_length=255)


# ---------------------------------------------------------------
# MOD-LSE-3 (2026-05-03) — Supreme Court and escalation pack
# (11 templates). Each is appellate or accompaniment-grade.
# ---------------------------------------------------------------


class SpecialLeavePetitionFacts(_TemplateFactsBase):
    """SLP under Article 136 (civil + criminal).

    Article 136 SLPs are the highest-volume SC filing. The shape
    captures the impugned-order anchor, questions of law, and the
    common accompaniment fields (delay, stay, exemption) so the
    drafting prompt can branch on them.
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    slp_kind: Literal["civil", "criminal"] = "civil"
    impugned_order_summary: str = Field(min_length=40, max_length=4000)
    impugned_order_date: str = Field(min_length=10, max_length=10)
    high_court_name: str = Field(
        min_length=2,
        max_length=255,
        description="HC whose order is challenged (or other lower forum).",
    )
    high_court_case_number: str | None = Field(default=None, max_length=120)
    questions_of_law: list[str] = Field(
        min_length=1,
        max_length=10,
        description=(
            "SC entertains SLPs only on substantial questions; list "
            "each question on a separate line."
        ),
    )
    grounds_brief: str = Field(min_length=80, max_length=8000)
    interim_relief_sought: str | None = Field(default=None, max_length=2000)
    delay_days: int | None = Field(default=None, ge=0, le=10000)
    exemption_from_certified_copy: bool = Field(default=False)


class SupremeCourtAppealFacts(_TemplateFactsBase):
    """SC appeal under Articles 132 / 133 / 134 — substantial-question
    appeals from the High Court (as distinct from Article 136 SLP)."""

    appellant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    constitutional_basis: Literal[
        "article_132", "article_133", "article_134", "article_134A",
    ] = "article_133"
    impugned_order_summary: str = Field(min_length=40, max_length=4000)
    impugned_order_date: str = Field(min_length=10, max_length=10)
    high_court_name: str = Field(min_length=2, max_length=255)
    high_court_case_number: str | None = Field(default=None, max_length=120)
    certificate_of_fitness_granted: bool = Field(
        default=False,
        description=(
            "Article 132/133/134 appeals require a HC certificate of "
            "fitness. If false, the appeal must address why the SC "
            "should grant leave."
        ),
    )
    substantial_question: str = Field(min_length=40, max_length=2000)
    grounds_brief: str = Field(min_length=80, max_length=8000)


class ReviewPetitionFacts(_TemplateFactsBase):
    """Review petition under Article 137 (SC) or Order XLVII Rule 1
    CPC (HC). The forum field selects the format."""

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    review_court: Literal["supreme_court", "high_court"] = "supreme_court"
    impugned_judgment_date: str = Field(min_length=10, max_length=10)
    impugned_judgment_citation: str | None = Field(default=None, max_length=400)
    error_apparent_on_face_of_record: str = Field(
        min_length=40,
        max_length=4000,
        description=(
            "Review jurisdiction is narrow — the petition must point to "
            "an error apparent on the face of the record, not a "
            "rehearing of the merits."
        ),
    )
    new_evidence_summary: str | None = Field(default=None, max_length=4000)
    grounds_brief: str = Field(min_length=80, max_length=6000)
    open_court_hearing_requested: bool = Field(default=False)


class CurativePetitionFacts(_TemplateFactsBase):
    """Curative petition under the Rupa Ashok Hurra (2002) framework.

    Curative jurisdiction is post-review — invoked only when review
    has been dismissed. Requires a senior advocate's certification.
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    impugned_order_date: str = Field(min_length=10, max_length=10)
    review_dismissed_date: str = Field(min_length=10, max_length=10)
    senior_advocate_name: str = Field(
        min_length=2,
        max_length=255,
        description=(
            "Per Rupa Ashok Hurra v. Ashok Hurra (2002) 4 SCC 388, "
            "a curative petition must be certified by a Senior Advocate."
        ),
    )
    grounds_brief: str = Field(min_length=80, max_length=8000)
    natural_justice_violation: str | None = Field(default=None, max_length=4000)
    bias_grounds: str | None = Field(default=None, max_length=4000)


class TransferPetitionFacts(_TemplateFactsBase):
    """Transfer petition.

    Branches on the constitutional / statutory basis:

    - Article 139A: SC transfer between HCs / consolidation
    - Section 25 CPC: SC inter-state civil transfer
    - Section 406 BNSS / 527 CrPC: SC inter-state criminal transfer
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    transfer_basis: Literal[
        "article_139A",
        "cpc_s_25",
        "bnss_s_406",
        "crpc_s_406",
    ] = "cpc_s_25"
    case_number_in_transferor_court: str = Field(
        min_length=1, max_length=120,
    )
    transferor_court_name: str = Field(min_length=2, max_length=255)
    transferee_court_proposed: str = Field(min_length=2, max_length=255)
    grounds_for_transfer: str = Field(min_length=40, max_length=4000)
    convenience_reasons: str | None = Field(default=None, max_length=2000)
    safety_or_threat_reasons: str | None = Field(default=None, max_length=2000)


class ContemptPetitionFacts(_TemplateFactsBase):
    """Civil / criminal contempt under the Contempt of Courts Act 1971.

    Article 129 vests contempt jurisdiction in the SC; Article 215 in
    the HC. The forum field selects the cause-title format.
    """

    petitioner_name: str = Field(min_length=2, max_length=255)
    contemnor_name: str = Field(min_length=2, max_length=500)
    contempt_court: Literal["supreme_court", "high_court"] = "high_court"
    contempt_kind: Literal["civil", "criminal"] = "civil"
    underlying_order_date: str = Field(min_length=10, max_length=10)
    underlying_order_summary: str = Field(min_length=40, max_length=4000)
    breach_facts: str = Field(min_length=40, max_length=8000)
    notice_to_contemnor_served: bool = Field(default=False)
    relief_sought: str = Field(min_length=20, max_length=2000)


class InterimReliefApplicationFacts(_TemplateFactsBase):
    """Interim relief application — stay, status quo, ad-interim
    injunction. Used at SC, HC, or trial court alongside the principal
    proceeding."""

    applicant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    main_proceeding_number: str = Field(min_length=1, max_length=120)
    main_proceeding_summary: str = Field(min_length=40, max_length=4000)
    court_name: str = Field(min_length=2, max_length=255)
    relief_kind: Literal[
        "stay", "status_quo", "ad_interim_injunction",
        "interim_mandatory_injunction", "exemption", "other",
    ] = "stay"
    prima_facie_case: str = Field(min_length=40, max_length=4000)
    balance_of_convenience: str = Field(min_length=40, max_length=4000)
    irreparable_injury: str = Field(min_length=40, max_length=4000)
    undertaking_offered: str | None = Field(default=None, max_length=2000)


class CondonationOfDelayFacts(_TemplateFactsBase):
    """Application under Section 5 of the Limitation Act, 1963 to
    condone delay in filing an appeal / SLP / petition."""

    applicant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    main_filing_kind: str = Field(
        min_length=2,
        max_length=120,
        description="What is being filed late? e.g. 'SLP', 'appeal', 'review'.",
    )
    main_filing_court: str = Field(min_length=2, max_length=255)
    delay_days: int = Field(ge=0, le=20000)
    cause_of_delay: str = Field(min_length=40, max_length=4000)
    diligence_explanation: str = Field(min_length=40, max_length=4000)
    impugned_order_date: str = Field(min_length=10, max_length=10)


class ExemptionApplicationFacts(_TemplateFactsBase):
    """SC exemption application — typically filed alongside an SLP
    seeking exemption from filing certified copy / from page-limit
    rules / from official translation."""

    applicant_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    main_filing_reference: str = Field(
        min_length=2,
        max_length=200,
        description="Reference to the principal proceeding (e.g. 'SLP filed alongside').",
    )
    exemption_kind: Literal[
        "certified_copy", "official_translation", "page_limit",
        "court_fee", "filing_in_person", "other",
    ] = "certified_copy"
    grounds: str = Field(min_length=40, max_length=4000)
    undertaking_offered: str | None = Field(default=None, max_length=2000)


class SynopsisListOfDatesFacts(_TemplateFactsBase):
    """Synopsis + list of dates accompaniment. Mandatory with every SC
    SLP / appeal."""

    case_title: str = Field(min_length=2, max_length=500)
    petitioner_name: str = Field(min_length=2, max_length=255)
    respondent_name: str = Field(min_length=2, max_length=500)
    questions_of_law: list[str] = Field(min_length=1, max_length=10)
    case_summary: str = Field(min_length=80, max_length=8000)
    chronology: list[str] = Field(
        min_length=2,
        max_length=80,
        description=(
            "List of dates entries in 'YYYY-MM-DD: event' format, "
            "chronological. The drafter pretty-prints these."
        ),
    )


class FilingIndexChecklistFacts(_TemplateFactsBase):
    """SC / HC filing index + paginated checklist. Drives the
    registry-acceptance pre-flight."""

    case_title: str = Field(min_length=2, max_length=500)
    court_name: str = Field(min_length=2, max_length=255)
    filing_kind: str = Field(
        min_length=2,
        max_length=120,
        description="e.g. 'SLP', 'Writ Petition', 'Civil Appeal'.",
    )
    documents_to_index: list[str] = Field(
        min_length=1,
        max_length=80,
        description=(
            "Each document on its own line — the index is generated in "
            "the same order. Include certified copies, vakalatnama, "
            "court-fee receipt, etc."
        ),
    )
    total_pages_estimate: int = Field(ge=1, le=10000)


class DraftTemplateSchema(BaseModel):
    """Endpoint response for ``/api/drafting/templates/{type}``."""

    template_type: DraftTemplateTypeLiteral
    display_name: str
    summary: str
    statutory_basis: list[str]
    step_groups: list[str]
    fields: list[DraftingFieldSpec]
    facts_model_json_schema: dict[str, Any]


# ---------------------------------------------------------------
# Field specs per template — the stepper reads these directly.
# ---------------------------------------------------------------


_BAIL_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="accused_name", label="Accused's full name"),
    DraftingFieldSpec(
        name="fir_number",
        label="FIR number",
        placeholder="FIR No. 123/2026",
    ),
    DraftingFieldSpec(name="police_station", label="Police station"),
    DraftingFieldSpec(
        name="sections_charged",
        label="Sections charged",
        kind="string",
        help_text="Comma-separated list, e.g. 'BNS s.303, BNS s.318'.",
    ),
    DraftingFieldSpec(
        name="custody_since",
        label="Date accused entered custody",
        kind="date",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="prior_bail_applications",
        label="Prior bail applications filed",
        kind="number",
        required=False,
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds for bail (parity, duration, co-accused, triple test)",
        kind="text",
        step_group="grounds",
    ),
]


_ANTICIPATORY_BAIL_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant's full name"),
    DraftingFieldSpec(
        name="fir_number",
        label="FIR number (if registered)",
        required=False,
    ),
    DraftingFieldSpec(
        name="apprehended_sections",
        label="Sections apprehended",
        help_text="BNS sections the applicant expects to be booked under.",
    ),
    DraftingFieldSpec(name="police_station", label="Police station"),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="apprehension_grounds",
        label="Grounds for apprehension of arrest",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="has_received_notice",
        label="Has the applicant received a s.41A notice?",
        kind="boolean",
        required=False,
    ),
]


_DIVORCE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner's full name"),
    DraftingFieldSpec(name="respondent_name", label="Respondent's full name"),
    DraftingFieldSpec(name="marriage_date", label="Date of marriage", kind="date"),
    DraftingFieldSpec(name="marriage_place", label="Place of marriage"),
    DraftingFieldSpec(
        name="separation_date", label="Date of separation", kind="date", required=False
    ),
    DraftingFieldSpec(
        name="grounds",
        label="Grounds",
        help_text="Cruelty, desertion, adultery, conversion, mental illness, etc.",
    ),
    DraftingFieldSpec(
        name="act_governing",
        label="Governing Act",
        kind="enum",
        enum_options=["HMA", "SMA", "INDIAN_CHRISTIAN", "OTHER"],
    ),
    DraftingFieldSpec(
        name="children_details",
        label="Children / custody details",
        kind="text",
        required=False,
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
]


_PROPERTY_NOTICE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="sender_name", label="Sender's full name"),
    DraftingFieldSpec(name="recipient_name", label="Recipient's full name"),
    DraftingFieldSpec(
        name="property_address",
        label="Property address",
        kind="text",
    ),
    DraftingFieldSpec(
        name="property_type",
        label="Property type",
        kind="enum",
        enum_options=["land", "flat", "house", "commercial", "other"],
    ),
    DraftingFieldSpec(
        name="title_basis",
        label="Basis of title",
        kind="enum",
        enum_options=["sale_deed", "inheritance", "will", "gift_deed", "other"],
    ),
    DraftingFieldSpec(
        name="relief_sought", label="Relief demanded", kind="text", step_group="relief"
    ),
    DraftingFieldSpec(
        name="response_deadline_days",
        label="Response deadline (days)",
        kind="number",
    ),
]


_CHEQUE_BOUNCE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="drawer_name", label="Drawer's full name"),
    DraftingFieldSpec(name="drawee_name", label="Drawee / payee's full name"),
    DraftingFieldSpec(name="cheque_number", label="Cheque number"),
    DraftingFieldSpec(name="cheque_date", label="Cheque date", kind="date"),
    DraftingFieldSpec(name="cheque_amount_inr", label="Cheque amount (INR)", kind="number"),
    DraftingFieldSpec(name="bank_name", label="Drawer's bank"),
    DraftingFieldSpec(name="bank_memo_date", label="Bank memo date", kind="date"),
    DraftingFieldSpec(
        name="dishonour_reason",
        label="Dishonour reason",
        kind="enum",
        enum_options=[
            "insufficient_funds",
            "exceeds_arrangement",
            "payment_stopped",
            "other",
        ],
    ),
]


_AFFIDAVIT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="deponent_name", label="Deponent's full name"),
    DraftingFieldSpec(name="deponent_age", label="Age", kind="number"),
    DraftingFieldSpec(name="deponent_occupation", label="Occupation"),
    DraftingFieldSpec(name="deponent_address", label="Address", kind="text"),
    DraftingFieldSpec(
        name="statement_paragraphs",
        label="Sworn statement paragraphs",
        kind="text",
        help_text="One point per line; the drafter numbers them automatically.",
    ),
    DraftingFieldSpec(name="sworn_place", label="Place of swearing"),
    DraftingFieldSpec(name="sworn_date", label="Date of swearing", kind="date"),
]


_CRIMINAL_COMPLAINT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="complainant_name", label="Complainant's full name"),
    DraftingFieldSpec(name="accused_name", label="Accused's full name"),
    DraftingFieldSpec(
        name="alleged_sections",
        label="Sections alleged",
        help_text="BNS sections the accused is alleged to have committed.",
    ),
    DraftingFieldSpec(name="incident_date", label="Date of incident", kind="date"),
    DraftingFieldSpec(name="incident_place", label="Place of incident", kind="text"),
    DraftingFieldSpec(
        name="narrative",
        label="Facts / chronology",
        kind="text",
        step_group="facts",
    ),
    DraftingFieldSpec(
        name="witness_count", label="Witnesses to be examined", kind="number", required=False
    ),
    DraftingFieldSpec(
        name="prior_fir_filed",
        label="Was an FIR already filed?",
        kind="boolean",
        required=False,
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
]


_CIVIL_SUIT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="plaintiff_name", label="Plaintiff's full name"),
    DraftingFieldSpec(name="defendant_name", label="Defendant's full name"),
    DraftingFieldSpec(
        name="cause_of_action_date", label="Date cause of action arose", kind="date"
    ),
    DraftingFieldSpec(
        name="cause_of_action_place",
        label="Place cause of action arose",
        kind="text",
    ),
    DraftingFieldSpec(
        name="suit_valuation_inr", label="Suit valuation (INR)", kind="number"
    ),
    DraftingFieldSpec(
        name="relief_sought",
        label="Relief(s) sought",
        help_text="One per line.",
    ),
    DraftingFieldSpec(
        name="is_commercial_suit",
        label="Commercial suit?",
        kind="boolean",
        required=False,
        help_text="Governs whether the Commercial Courts Act, 2015 timelines apply.",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="facts_brief", label="Facts (brief)", kind="text", step_group="facts"
    ),
]


_APPEAL_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="appellant_name", label="Appellant's full name"),
    DraftingFieldSpec(name="respondent_name", label="Respondent's full name"),
    DraftingFieldSpec(
        name="impugned_order_summary",
        label="What the impugned order said",
        kind="text",
        help_text="Brief summary of the lower forum's order being appealed.",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="impugned_order_date",
        label="Date of impugned order",
        kind="date",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="lower_forum_name",
        label="Lower forum (court that passed the order)",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="appeal_court_name",
        label="Appeal court (where this appeal will be filed)",
        help_text=(
            "Used by bench strategy context to surface this court's prior "
            "decisions on similar issues."
        ),
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="questions_of_law",
        label="Questions of law raised",
        kind="string",
        help_text="One per line — keep each tight and answerable.",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds of appeal",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="interim_relief_sought",
        label="Interim relief sought (stay, status quo, etc.)",
        kind="text",
        required=False,
        step_group="relief",
    ),
    DraftingFieldSpec(
        name="delay_condonation_needed",
        label="Delay condonation required?",
        kind="boolean",
        required=False,
        step_group="limitation",
    ),
    DraftingFieldSpec(
        name="delay_condonation_days",
        label="Days of delay (if condonation needed)",
        kind="number",
        required=False,
        step_group="limitation",
    ),
    DraftingFieldSpec(
        name="record_references",
        label="Record references (page nos. of the impugned order, exhibits)",
        kind="text",
        required=False,
        step_group="record",
    ),
]


_WRIT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner's full name"),
    DraftingFieldSpec(
        name="respondent_name",
        label="Respondent(s)",
        help_text=(
            "Usually 'State of X' or 'Union of India'; multiple "
            "respondents in one field separated by commas."
        ),
    ),
    DraftingFieldSpec(
        name="writ_court",
        label="Forum",
        kind="enum",
        enum_options=["high_court", "supreme_court"],
    ),
    DraftingFieldSpec(
        name="writ_type",
        label="Type of writ",
        kind="enum",
        enum_options=[
            "mandamus", "certiorari", "prohibition", "quo_warranto", "habeas_corpus",
        ],
    ),
    DraftingFieldSpec(
        name="impugned_action",
        label="Impugned order / action / inaction",
        kind="text",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="impugned_action_date",
        label="Date of impugned action (optional)",
        kind="date",
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="fundamental_rights_invoked",
        label="Fundamental rights invoked",
        help_text="One per line — e.g. Article 14, Article 19(1)(g), Article 21.",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="statutory_violations",
        label="Statutory provisions violated",
        help_text="One per line.",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="prayer_clauses",
        label="Prayer clauses",
        help_text=(
            "One per line. Mandamus → 'direct respondent to…'; "
            "Certiorari → 'quash the impugned order…'."
        ),
        step_group="relief",
    ),
    DraftingFieldSpec(
        name="interim_relief_sought",
        label="Interim relief (optional)",
        kind="text",
        required=False,
        step_group="relief",
    ),
    DraftingFieldSpec(
        name="laches_position",
        label="Laches / delay explanation (if filed late)",
        kind="text",
        required=False,
        step_group="limitation",
    ),
]


_QUASHING_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner's full name"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="fir_number",
        label="FIR / chargesheet number",
        required=False,
        placeholder="FIR No. 234/2025",
    ),
    DraftingFieldSpec(
        name="police_station", label="Police station", required=False,
    ),
    DraftingFieldSpec(
        name="impugned_proceedings_summary",
        label="Impugned proceedings (FIR / chargesheet / order)",
        kind="text",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="statutory_offences",
        label="Statutory offences alleged",
        help_text="One per line — e.g. BNS s.318, BNS s.351.",
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="grounds_for_quashing",
        label="Grounds for quashing",
        kind="text",
        step_group="grounds",
        help_text="No prima facie offence, abuse of process, jurisdictional bar, settlement, etc.",
    ),
    DraftingFieldSpec(
        name="compromise_recorded",
        label="Matter compromised between parties?",
        kind="boolean",
        required=False,
        step_group="grounds",
        help_text="Triggers Gian Singh / B.S. Joshi framing if true.",
    ),
    DraftingFieldSpec(
        name="victim_consent",
        label="Victim has consented to quashing?",
        kind="boolean",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(name="court_name", label="High Court"),
]


_WS_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="defendant_name", label="Defendant's full name"),
    DraftingFieldSpec(name="plaintiff_name", label="Plaintiff's full name"),
    DraftingFieldSpec(
        name="suit_number",
        label="Suit number",
        placeholder="CS (OS) 123/2025",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="preliminary_objections",
        label="Preliminary objections",
        help_text="Jurisdiction, limitation, mis-joinder, valuation, suppression — one per line.",
        required=False,
        step_group="objections",
    ),
    DraftingFieldSpec(
        name="paragraph_wise_reply",
        label="Para-by-para reply to plaint",
        kind="text",
        step_group="reply",
        help_text=(
            "'Para 1 is denied' / 'Para 2 is admitted' / 'Para 3 "
            "is denied for want of knowledge'."
        ),
    ),
    DraftingFieldSpec(
        name="counter_claim_text",
        label="Counter-claim (Order VIII Rule 6A) — optional",
        kind="text",
        required=False,
        step_group="affirmative",
    ),
    DraftingFieldSpec(
        name="set_off_text",
        label="Set-off (Order VIII Rule 6) — optional",
        kind="text",
        required=False,
        step_group="affirmative",
    ),
    DraftingFieldSpec(
        name="limitation_defence",
        label="Limitation defence (optional)",
        kind="text",
        required=False,
        step_group="affirmative",
    ),
    DraftingFieldSpec(
        name="documents_relied",
        label="Documents relied on (Order VIII Rule 1A list)",
        help_text="One per line.",
        required=False,
        step_group="documents",
    ),
]


_REPLY_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="deponent_name", label="Deponent's full name"),
    DraftingFieldSpec(
        name="deponent_designation",
        label="Designation (if institutional respondent)",
        required=False,
    ),
    DraftingFieldSpec(name="deponent_address", label="Deponent's address", kind="text"),
    DraftingFieldSpec(
        name="petition_number",
        label="Petition number being replied to",
        placeholder="W.P. (C) 1234/2025",
    ),
    DraftingFieldSpec(
        name="petition_type",
        label="Type of petition (optional)",
        required=False,
        placeholder="Writ Petition (C) / Crl. M.A. / IA",
    ),
    DraftingFieldSpec(
        name="main_petition_summary",
        label="Summary of the petition being replied to",
        kind="text",
        step_group="impugned",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="preliminary_submissions",
        label="Preliminary submissions (optional)",
        kind="text",
        required=False,
        step_group="objections",
    ),
    DraftingFieldSpec(
        name="paragraph_wise_response",
        label="Para-by-para response to the petition",
        kind="text",
        step_group="reply",
    ),
    DraftingFieldSpec(
        name="additional_facts_pleaded",
        label="Additional facts pleaded by the respondent",
        help_text="One per line.",
        required=False,
        step_group="reply",
    ),
    DraftingFieldSpec(
        name="relief_sought_against_petition",
        label="Relief sought (typically 'dismiss the petition')",
        kind="text",
        step_group="relief",
    ),
]


_DV_QUASHING_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner's full name"),
    DraftingFieldSpec(
        name="aggrieved_person_name",
        label="Aggrieved person (PWDVA s.12 applicant)",
    ),
    DraftingFieldSpec(
        name="pwdva_application_number",
        label="PWDVA application number",
        placeholder="MA No. 123/2025",
    ),
    DraftingFieldSpec(name="magistrate_court_name", label="Magistrate court"),
    DraftingFieldSpec(name="high_court_name", label="High Court"),
    DraftingFieldSpec(
        name="impugned_reliefs_in_pwdva_app",
        label="Reliefs sought in PWDVA application",
        help_text=(
            "One per line — protection / residence / monetary / "
            "custody / compensation."
        ),
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="grounds_for_quashing",
        label="Grounds for quashing",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="domestic_relationship_disputed",
        label="No domestic relationship (s.2(f) PWDVA)?",
        kind="boolean",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="settlement_recorded",
        label="Settlement recorded between parties?",
        kind="boolean",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="aggrieved_consent",
        label="Aggrieved person consents to quashing?",
        kind="boolean",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="children_minor_count",
        label="Number of minor children (welfare factor)",
        kind="number",
        required=False,
        step_group="grounds",
    ),
]


_ARBITRATION_S9_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="arbitration_status",
        label="Stage of arbitration",
        kind="enum",
        enum_options=[
            "pre_arbitration", "during_arbitration", "post_award_pre_enforcement",
        ],
    ),
    DraftingFieldSpec(
        name="arbitration_agreement_summary",
        label="Arbitration clause / agreement",
        kind="text",
        step_group="agreement",
    ),
    DraftingFieldSpec(
        name="arbitral_tribunal_constituted",
        label="Tribunal already constituted?",
        kind="boolean",
        required=False,
        step_group="agreement",
        help_text="Triggers s.9(3) — court will not entertain except in exceptional cases.",
    ),
    DraftingFieldSpec(
        name="interim_reliefs_sought",
        label="Interim reliefs sought",
        help_text=(
            "One per line — preservation / receiver / injunction / "
            "amount in dispute / disclosure."
        ),
        step_group="relief",
    ),
    DraftingFieldSpec(
        name="underlying_cause_of_action",
        label="Underlying cause of action",
        kind="text",
        step_group="cause",
    ),
    DraftingFieldSpec(
        name="urgency_basis",
        label="Why interim relief cannot await tribunal",
        kind="text",
        step_group="urgency",
    ),
    DraftingFieldSpec(
        name="undertaking_offered",
        label="Cross-undertaking (optional)",
        kind="text",
        required=False,
        step_group="urgency",
    ),
]


_CAVEAT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="caveator_name", label="Caveator"),
    DraftingFieldSpec(
        name="caveator_address",
        label="Caveator's address",
        kind="text",
    ),
    DraftingFieldSpec(
        name="apprehended_applicant_name",
        label="Person apprehended to file against caveator",
    ),
    DraftingFieldSpec(
        name="apprehended_proceeding_summary",
        label="Apprehended proceeding (what relief is feared?)",
        kind="text",
        step_group="apprehension",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="related_matter_reference",
        label="Related matter (case number / FIR / contract — optional)",
        required=False,
    ),
    DraftingFieldSpec(
        name="counsel_name",
        label="Counsel for caveator (optional)",
        required=False,
    ),
]


_VAKALAT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="client_name", label="Client / litigant name"),
    DraftingFieldSpec(name="client_address", label="Client's address", kind="text"),
    DraftingFieldSpec(name="counsel_name", label="Counsel's name"),
    DraftingFieldSpec(
        name="counsel_enrollment_number",
        label="Counsel's bar enrollment number",
        placeholder="D/12345/2018",
    ),
    DraftingFieldSpec(name="counsel_address", label="Counsel's address", kind="text"),
    DraftingFieldSpec(
        name="case_title",
        label="Case title (A v. B)",
        placeholder="Sharma v. State of Delhi",
    ),
    DraftingFieldSpec(
        name="case_number",
        label="Case number (leave blank for fresh filings)",
        required=False,
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="party_role",
        label="Client's role",
        kind="enum",
        enum_options=[
            "plaintiff", "defendant", "petitioner", "respondent",
            "appellant", "applicant", "objector",
        ],
    ),
    DraftingFieldSpec(
        name="accepts_appearance_for_appeals",
        label="Vakalat extends to appeals + IAs?",
        kind="boolean",
        required=False,
    ),
]


_AMENDMENT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant"),
    DraftingFieldSpec(
        name="applicant_role",
        label="Applicant's role in suit",
        kind="enum",
        enum_options=["plaintiff", "defendant", "petitioner", "respondent"],
    ),
    DraftingFieldSpec(
        name="suit_number",
        label="Suit / petition number",
        placeholder="CS 412/2025",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="pleading_to_amend",
        label="Pleading to be amended",
        kind="enum",
        enum_options=[
            "plaint", "written_statement", "petition", "counter_affidavit",
        ],
    ),
    DraftingFieldSpec(
        name="proposed_amendments",
        label="Proposed amendments (verbatim text)",
        kind="text",
        step_group="amendments",
        help_text="Number each addition / deletion. Use 'add para X-A' / 'delete para Y'.",
    ),
    DraftingFieldSpec(
        name="reason_for_amendment",
        label="Reason for amendment",
        kind="text",
        step_group="reason",
    ),
    DraftingFieldSpec(
        name="trial_commenced",
        label="Has trial commenced?",
        kind="boolean",
        required=False,
        step_group="reason",
        help_text="If true, the Order VI Rule 17 proviso (due diligence) applies.",
    ),
    DraftingFieldSpec(
        name="due_diligence_explanation",
        label="Due-diligence explanation (required if trial commenced)",
        kind="text",
        required=False,
        step_group="reason",
    ),
    DraftingFieldSpec(
        name="prejudice_to_opposite_party",
        label="Why no prejudice to opposite party (optional)",
        kind="text",
        required=False,
        step_group="reason",
    ),
]


_COMPROMISE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(
        name="matter_type",
        label="Matter type",
        kind="enum",
        enum_options=["civil", "criminal", "matrimonial"],
    ),
    DraftingFieldSpec(name="party_a_name", label="Party A (e.g. plaintiff / complainant)"),
    DraftingFieldSpec(name="party_b_name", label="Party B (e.g. defendant / accused)"),
    DraftingFieldSpec(name="case_number", label="Case number"),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="statutory_basis",
        label="Statutory basis",
        kind="enum",
        enum_options=[
            "cpc_order_23_rule_3",
            "bnss_s_359_compoundable",
            "bnss_s_528_non_compoundable",
            "hma_s_13b_mutual_consent",
        ],
    ),
    DraftingFieldSpec(
        name="settlement_terms",
        label="Settlement terms (verbatim)",
        kind="text",
        step_group="terms",
    ),
    DraftingFieldSpec(
        name="consideration_paid",
        label="Consideration paid (optional)",
        required=False,
        step_group="terms",
    ),
    DraftingFieldSpec(
        name="each_party_to_bear_own_costs",
        label="Each party bears own costs?",
        kind="boolean",
        required=False,
        step_group="terms",
    ),
    DraftingFieldSpec(
        name="children_arrangements",
        label="Children arrangements (matrimonial only — optional)",
        kind="text",
        required=False,
        step_group="terms",
    ),
    DraftingFieldSpec(
        name="statutory_offences_compounded",
        label="Offences being compounded (criminal only — optional)",
        help_text="One per line.",
        required=False,
        step_group="terms",
    ),
]


_PROBATE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner (executor / LR)"),
    DraftingFieldSpec(
        name="petitioner_relationship_to_deceased",
        label="Petitioner's relationship to deceased",
    ),
    DraftingFieldSpec(name="deceased_name", label="Deceased's name"),
    DraftingFieldSpec(
        name="deceased_date_of_death",
        label="Date of death",
        kind="date",
    ),
    DraftingFieldSpec(
        name="deceased_last_residence",
        label="Deceased's last residence",
        kind="text",
    ),
    DraftingFieldSpec(
        name="deceased_religion",
        label="Religion of deceased (governs personal law)",
        kind="enum",
        enum_options=["hindu", "muslim", "christian", "parsi", "jew", "other"],
    ),
    DraftingFieldSpec(
        name="will_date",
        label="Date of will",
        kind="date",
        step_group="will",
    ),
    DraftingFieldSpec(
        name="will_attesting_witnesses",
        label="Attesting witnesses (s.63(c) requires ≥2)",
        help_text="One per line — name + father's name + address.",
        step_group="will",
    ),
    DraftingFieldSpec(
        name="estate_assets_summary",
        label="Estate assets (movable + immovable)",
        kind="text",
        step_group="estate",
    ),
    DraftingFieldSpec(
        name="estate_total_value_inr",
        label="Aggregate estate value (INR)",
        kind="number",
        step_group="estate",
        help_text=(
            "Drives pecuniary jurisdiction + court fee. "
            "Under-valuation is a rejection ground."
        ),
    ),
    DraftingFieldSpec(
        name="legal_heirs",
        label="Legal heirs (for notice under s.283)",
        help_text="One per line — each heir entitled to intestate share.",
        step_group="heirs",
    ),
    DraftingFieldSpec(
        name="will_contested",
        label="Will contested by any heir?",
        kind="boolean",
        required=False,
        step_group="heirs",
    ),
    DraftingFieldSpec(name="court_name", label="Court (District / HC original side)"),
]


# ---------------------------------------------------------------
# MOD-LSE-3 (2026-05-03) — SC + escalation pack field specs.
# Kept compact; the stepper renders them straight.
# ---------------------------------------------------------------


_SLP_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="slp_kind",
        label="SLP kind",
        kind="enum",
        enum_options=["civil", "criminal"],
    ),
    DraftingFieldSpec(
        name="impugned_order_summary",
        label="Impugned order — summary",
        kind="text",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="impugned_order_date",
        label="Impugned order date",
        kind="date",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="high_court_name",
        label="High Court (or other lower forum)",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="high_court_case_number",
        label="HC case number (optional)",
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="questions_of_law",
        label="Questions of law (one per line)",
        help_text="Article 136 SLPs are entertained on substantial questions only.",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds (brief)",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="interim_relief_sought",
        label="Interim relief (optional)",
        kind="text",
        required=False,
        step_group="relief",
    ),
    DraftingFieldSpec(
        name="delay_days",
        label="Delay days (if condonation needed)",
        kind="number",
        required=False,
        step_group="limitation",
    ),
    DraftingFieldSpec(
        name="exemption_from_certified_copy",
        label="Seek exemption from certified copy?",
        kind="boolean",
        required=False,
        step_group="limitation",
    ),
]

_SC_APPEAL_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="appellant_name", label="Appellant"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="constitutional_basis",
        label="Constitutional basis",
        kind="enum",
        enum_options=[
            "article_132", "article_133", "article_134", "article_134A",
        ],
    ),
    DraftingFieldSpec(
        name="impugned_order_summary",
        label="Impugned order — summary",
        kind="text",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="impugned_order_date",
        label="Impugned order date",
        kind="date",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="high_court_name", label="High Court", step_group="impugned",
    ),
    DraftingFieldSpec(
        name="high_court_case_number",
        label="HC case number (optional)",
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="certificate_of_fitness_granted",
        label="HC granted certificate of fitness?",
        kind="boolean",
        required=False,
        step_group="impugned",
        help_text="Required for Article 132/133/134 appeals.",
    ),
    DraftingFieldSpec(
        name="substantial_question",
        label="Substantial question of law",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds (brief)",
        kind="text",
        step_group="grounds",
    ),
]

_REVIEW_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="review_court",
        label="Review court",
        kind="enum",
        enum_options=["supreme_court", "high_court"],
    ),
    DraftingFieldSpec(
        name="impugned_judgment_date",
        label="Impugned judgment date",
        kind="date",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="impugned_judgment_citation",
        label="Impugned judgment citation (optional)",
        required=False,
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="error_apparent_on_face_of_record",
        label="Error apparent on face of record",
        kind="text",
        step_group="grounds",
        help_text="Review jurisdiction is narrow — point to the error, not a rehearing.",
    ),
    DraftingFieldSpec(
        name="new_evidence_summary",
        label="New evidence (optional)",
        kind="text",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds (brief)",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="open_court_hearing_requested",
        label="Open-court hearing requested?",
        kind="boolean",
        required=False,
    ),
]

_CURATIVE_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="impugned_order_date",
        label="Impugned order date",
        kind="date",
        step_group="impugned",
    ),
    DraftingFieldSpec(
        name="review_dismissed_date",
        label="Review-petition dismissal date",
        kind="date",
        step_group="impugned",
        help_text="Curative jurisdiction is post-review.",
    ),
    DraftingFieldSpec(
        name="senior_advocate_name",
        label="Certifying Senior Advocate",
        help_text="Per Rupa Ashok Hurra (2002) 4 SCC 388, certification is mandatory.",
    ),
    DraftingFieldSpec(
        name="grounds_brief",
        label="Grounds (brief)",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="natural_justice_violation",
        label="Natural justice violation (optional)",
        kind="text",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="bias_grounds",
        label="Bias / disqualification grounds (optional)",
        kind="text",
        required=False,
        step_group="grounds",
    ),
]

_TRANSFER_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="transfer_basis",
        label="Statutory basis",
        kind="enum",
        enum_options=[
            "article_139A", "cpc_s_25", "bnss_s_406", "crpc_s_406",
        ],
    ),
    DraftingFieldSpec(
        name="case_number_in_transferor_court",
        label="Case number in transferor court",
        step_group="origin",
    ),
    DraftingFieldSpec(
        name="transferor_court_name",
        label="Transferor court (where the case currently sits)",
        step_group="origin",
    ),
    DraftingFieldSpec(
        name="transferee_court_proposed",
        label="Transferee court (proposed)",
        step_group="destination",
    ),
    DraftingFieldSpec(
        name="grounds_for_transfer",
        label="Grounds for transfer",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="convenience_reasons",
        label="Convenience reasons (optional)",
        kind="text",
        required=False,
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="safety_or_threat_reasons",
        label="Safety / threat reasons (optional)",
        kind="text",
        required=False,
        step_group="grounds",
    ),
]

_CONTEMPT_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="contemnor_name", label="Contemnor"),
    DraftingFieldSpec(
        name="contempt_court",
        label="Court",
        kind="enum",
        enum_options=["supreme_court", "high_court"],
    ),
    DraftingFieldSpec(
        name="contempt_kind",
        label="Contempt kind",
        kind="enum",
        enum_options=["civil", "criminal"],
    ),
    DraftingFieldSpec(
        name="underlying_order_date",
        label="Underlying order date",
        kind="date",
        step_group="underlying",
    ),
    DraftingFieldSpec(
        name="underlying_order_summary",
        label="Underlying order — summary",
        kind="text",
        step_group="underlying",
    ),
    DraftingFieldSpec(
        name="breach_facts",
        label="Breach facts",
        kind="text",
        step_group="breach",
    ),
    DraftingFieldSpec(
        name="notice_to_contemnor_served",
        label="Notice to contemnor served?",
        kind="boolean",
        required=False,
        step_group="breach",
    ),
    DraftingFieldSpec(
        name="relief_sought",
        label="Relief sought",
        kind="text",
        step_group="relief",
    ),
]

_INTERIM_RELIEF_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="main_proceeding_number",
        label="Main proceeding number",
        step_group="main",
    ),
    DraftingFieldSpec(
        name="main_proceeding_summary",
        label="Main proceeding — summary",
        kind="text",
        step_group="main",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="relief_kind",
        label="Relief kind",
        kind="enum",
        enum_options=[
            "stay", "status_quo", "ad_interim_injunction",
            "interim_mandatory_injunction", "exemption", "other",
        ],
    ),
    DraftingFieldSpec(
        name="prima_facie_case",
        label="Prima facie case",
        kind="text",
        step_group="three_factor",
    ),
    DraftingFieldSpec(
        name="balance_of_convenience",
        label="Balance of convenience",
        kind="text",
        step_group="three_factor",
    ),
    DraftingFieldSpec(
        name="irreparable_injury",
        label="Irreparable injury",
        kind="text",
        step_group="three_factor",
    ),
    DraftingFieldSpec(
        name="undertaking_offered",
        label="Cross-undertaking (optional)",
        kind="text",
        required=False,
    ),
]

_CONDONATION_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="main_filing_kind",
        label="What is being filed late?",
        placeholder="SLP / appeal / review",
    ),
    DraftingFieldSpec(name="main_filing_court", label="Filing court"),
    DraftingFieldSpec(
        name="delay_days",
        label="Days of delay",
        kind="number",
        step_group="delay",
    ),
    DraftingFieldSpec(
        name="cause_of_delay",
        label="Cause of delay",
        kind="text",
        step_group="delay",
    ),
    DraftingFieldSpec(
        name="diligence_explanation",
        label="Diligence explanation",
        kind="text",
        step_group="delay",
    ),
    DraftingFieldSpec(
        name="impugned_order_date",
        label="Impugned order date",
        kind="date",
    ),
]

_EXEMPTION_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(name="applicant_name", label="Applicant"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="main_filing_reference",
        label="Main filing reference",
        placeholder="e.g. 'SLP filed alongside'",
    ),
    DraftingFieldSpec(
        name="exemption_kind",
        label="Exemption kind",
        kind="enum",
        enum_options=[
            "certified_copy", "official_translation", "page_limit",
            "court_fee", "filing_in_person", "other",
        ],
    ),
    DraftingFieldSpec(
        name="grounds",
        label="Grounds for exemption",
        kind="text",
        step_group="grounds",
    ),
    DraftingFieldSpec(
        name="undertaking_offered",
        label="Cross-undertaking (optional)",
        kind="text",
        required=False,
    ),
]

_SYNOPSIS_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(
        name="case_title",
        label="Case title (A v. B)",
        placeholder="Sharma v. State of Delhi",
    ),
    DraftingFieldSpec(name="petitioner_name", label="Petitioner"),
    DraftingFieldSpec(name="respondent_name", label="Respondent(s)"),
    DraftingFieldSpec(
        name="questions_of_law",
        label="Questions of law (one per line)",
        step_group="questions",
    ),
    DraftingFieldSpec(
        name="case_summary",
        label="Case summary",
        kind="text",
        step_group="summary",
    ),
    DraftingFieldSpec(
        name="chronology",
        label="List of dates",
        help_text="One entry per line in 'YYYY-MM-DD: event' format.",
        step_group="dates",
    ),
]

_FILING_INDEX_FIELDS: list[DraftingFieldSpec] = [
    DraftingFieldSpec(
        name="case_title",
        label="Case title (A v. B)",
    ),
    DraftingFieldSpec(name="court_name", label="Court"),
    DraftingFieldSpec(
        name="filing_kind",
        label="Filing kind",
        placeholder="SLP / Writ Petition / Civil Appeal",
    ),
    DraftingFieldSpec(
        name="documents_to_index",
        label="Documents (one per line, in filing order)",
        help_text="Include vakalatnama, certified copies, court-fee receipt, etc.",
        step_group="documents",
    ),
    DraftingFieldSpec(
        name="total_pages_estimate",
        label="Total pages (estimate)",
        kind="number",
    ),
]


# ---------------------------------------------------------------
# Registry — the template route reads this; nothing else should.
# ---------------------------------------------------------------


_REGISTRY: dict[DraftTemplateType, tuple[type[_TemplateFactsBase], DraftTemplateSchema]] = {}


def _register(
    template_type: DraftTemplateType,
    *,
    display_name: str,
    summary: str,
    statutory_basis: list[str],
    fields: list[DraftingFieldSpec],
    facts_model: type[_TemplateFactsBase],
) -> None:
    step_groups = list(
        dict.fromkeys(f.step_group for f in fields)
    ) or ["facts"]
    schema = DraftTemplateSchema(
        template_type=template_type.value,  # type: ignore[arg-type]
        display_name=display_name,
        summary=summary,
        statutory_basis=statutory_basis,
        step_groups=step_groups,
        fields=fields,
        facts_model_json_schema=facts_model.model_json_schema(),
    )
    _REGISTRY[template_type] = (facts_model, schema)


_register(
    DraftTemplateType.BAIL,
    display_name="Regular Bail Application",
    summary="Application under BNSS s.483 (earlier CrPC s.439) seeking regular bail.",
    statutory_basis=["BNSS s.483", "CrPC s.439 (historical)"],
    fields=_BAIL_FIELDS,
    facts_model=BailFacts,
)
_register(
    DraftTemplateType.ANTICIPATORY_BAIL,
    display_name="Anticipatory Bail Application",
    summary="Application under BNSS s.482 (earlier CrPC s.438) apprehending arrest.",
    statutory_basis=["BNSS s.482", "CrPC s.438 (historical)"],
    fields=_ANTICIPATORY_BAIL_FIELDS,
    facts_model=AnticipatoryBailFacts,
)
_register(
    DraftTemplateType.DIVORCE_PETITION,
    display_name="Divorce Petition",
    summary="Petition for dissolution of marriage under the governing Act.",
    statutory_basis=["HMA s.13", "SMA s.27", "Indian Divorce Act s.10"],
    fields=_DIVORCE_FIELDS,
    facts_model=DivorcePetitionFacts,
)
_register(
    DraftTemplateType.PROPERTY_DISPUTE_NOTICE,
    display_name="Property Dispute Demand Notice",
    summary="Pre-litigation notice demanding possession / damages / relief.",
    statutory_basis=["TPA 1882", "Specific Relief Act 1963", "Registration Act 1908"],
    fields=_PROPERTY_NOTICE_FIELDS,
    facts_model=PropertyDisputeNoticeFacts,
)
_register(
    DraftTemplateType.CHEQUE_BOUNCE_NOTICE,
    display_name="Cheque Bounce Statutory Notice",
    summary="Statutory notice under s.138 of the Negotiable Instruments Act.",
    statutory_basis=["NI Act s.138", "NI Act s.142"],
    fields=_CHEQUE_BOUNCE_FIELDS,
    facts_model=ChequeBounceNoticeFacts,
)
_register(
    DraftTemplateType.AFFIDAVIT,
    display_name="Affidavit",
    summary="Sworn evidentiary affidavit for filing alongside a pleading.",
    statutory_basis=["CPC Order XIX", "Indian Oaths Act 1969"],
    fields=_AFFIDAVIT_FIELDS,
    facts_model=AffidavitFacts,
)
_register(
    DraftTemplateType.CRIMINAL_COMPLAINT,
    display_name="Private Criminal Complaint",
    summary="Complaint under BNSS s.223 (earlier CrPC s.200).",
    statutory_basis=["BNSS s.223", "CrPC s.200 (historical)"],
    fields=_CRIMINAL_COMPLAINT_FIELDS,
    facts_model=CriminalComplaintFacts,
)
_register(
    DraftTemplateType.CIVIL_SUIT,
    display_name="Civil Suit / Plaint",
    summary="Plaint under the Code of Civil Procedure (or Commercial Courts Act).",
    statutory_basis=["CPC Order VII", "Commercial Courts Act 2015"],
    fields=_CIVIL_SUIT_FIELDS,
    facts_model=CivilSuitFacts,
)
_register(
    DraftTemplateType.APPEAL_MEMORANDUM,
    display_name="Appeal Memorandum",
    summary=(
        "Memorandum of appeal against an order of a lower forum. The "
        "drafting service injects bench strategy context (cited prior "
        "judgments from the appeal court) when available."
    ),
    statutory_basis=[
        "CPC Order XLI (civil appeals)",
        "BNSS s.415-431 (criminal appeals)",
        "Letters Patent (HC division benches)",
    ],
    fields=_APPEAL_FIELDS,
    facts_model=AppealMemorandumFacts,
)
_register(
    DraftTemplateType.WRIT_PETITION,
    display_name="Writ Petition",
    summary=(
        "Article 226 (HC) / Article 32 (SC) writ petition — covers "
        "mandamus, certiorari, prohibition, quo warranto, and habeas "
        "corpus. The drafting prompt branches on the writ_type field "
        "to enforce the right relief language."
    ),
    statutory_basis=[
        "Constitution Article 226 (HC writ jurisdiction)",
        "Constitution Article 32 (SC writ jurisdiction)",
        "Constitution Articles 14, 19, 21 (commonly invoked)",
    ],
    fields=_WRIT_FIELDS,
    facts_model=WritPetitionFacts,
)
_register(
    DraftTemplateType.QUASHING_PETITION,
    display_name="Quashing Petition",
    summary=(
        "Petition under BNSS s.528 (earlier CrPC s.482) to quash an "
        "FIR / chargesheet / proceedings. Prompt enforces Gian Singh / "
        "B.S. Joshi framing when compromise + victim consent are present."
    ),
    statutory_basis=[
        "BNSS s.528 (inherent powers of HC)",
        "CrPC s.482 (historical equivalent)",
        "Gian Singh v. State of Punjab (2012) 10 SCC 303",
        "B.S. Joshi v. State of Haryana (2003) 4 SCC 675",
    ],
    fields=_QUASHING_FIELDS,
    facts_model=QuashingPetitionFacts,
)
_register(
    DraftTemplateType.WRITTEN_STATEMENT,
    display_name="Written Statement",
    summary=(
        "Defendant-side written statement under CPC Order VIII. "
        "Order VIII Rule 1 sets a 30-day default with a 90-day cap; "
        "the prompt flags this as a drop-dead deadline."
    ),
    statutory_basis=[
        "CPC Order VIII Rules 1, 1A, 6, 6A",
        "Commercial Courts Act 2015 (timeline modifications)",
    ],
    fields=_WS_FIELDS,
    facts_model=WrittenStatementFacts,
)
_register(
    DraftTemplateType.REPLY_COUNTER_AFFIDAVIT,
    display_name="Reply / Counter-Affidavit",
    summary=(
        "Reply / counter-affidavit to a pending petition or "
        "application — covers writ counter-affidavits, IA replies, "
        "MA replies, and similar respondent-side filings."
    ),
    statutory_basis=[
        "CPC Order XIX (affidavits)",
        "Indian Oaths Act 1969",
        "Court rules on counter-affidavit timelines (HC-specific)",
    ],
    fields=_REPLY_FIELDS,
    facts_model=ReplyCounterAffidavitFacts,
)
_register(
    DraftTemplateType.DV_QUASHING_PETITION,
    display_name="Quashing of PWDVA Proceedings",
    summary=(
        "Petition under BNSS s.528 / CrPC s.482 to quash PWDVA s.12 "
        "proceedings before a magistrate. Distinct from a regular "
        "criminal-FIR quashing because the impugned proceedings are "
        "quasi-civil in flavour."
    ),
    statutory_basis=[
        "BNSS s.528 (HC inherent powers)",
        "CrPC s.482 (historical)",
        "PWDVA s.12 (the impugned application)",
        "PWDVA s.2(f) (domestic relationship)",
    ],
    fields=_DV_QUASHING_FIELDS,
    facts_model=DvQuashingPetitionFacts,
)
_register(
    DraftTemplateType.ARBITRATION_SECTION_9,
    display_name="Section 9 Arbitration Application (Interim Measures)",
    summary=(
        "Application under Section 9 of the Arbitration & Conciliation "
        "Act, 1996 for interim measures of protection — pre-arbitration, "
        "during arbitration (subject to s.9(3)), or post-award before "
        "enforcement under s.36."
    ),
    statutory_basis=[
        "Arbitration & Conciliation Act 1996 s.9",
        "Arbitration & Conciliation Act 1996 s.9(3)",
        "Commercial Courts Act 2015",
    ],
    fields=_ARBITRATION_S9_FIELDS,
    facts_model=ArbitrationSection9Facts,
)
_register(
    DraftTemplateType.CAVEAT_PETITION,
    display_name="Caveat Petition",
    summary=(
        "Caveat under CPC Section 148A. Lapses after 90 days unless "
        "renewed. The court must hear the caveator before passing any "
        "ex parte order on the apprehended application."
    ),
    statutory_basis=["CPC s.148A"],
    fields=_CAVEAT_FIELDS,
    facts_model=CaveatPetitionFacts,
)
_register(
    DraftTemplateType.VAKALATNAMA,
    display_name="Vakalatnama",
    summary=(
        "Power-of-attorney executed by the litigant authorising "
        "counsel to appear and conduct the case. The drafting prompt "
        "selects the right court-specific format (Delhi HC, Bombay HC, "
        "SC) when known."
    ),
    statutory_basis=[
        "Advocates Act 1961 s.30",
        "Bar Council of India Rules",
        "Court-specific civil rules (Delhi HC / Bombay HC / SC)",
    ],
    fields=_VAKALAT_FIELDS,
    facts_model=VakalatnamaFacts,
)
_register(
    DraftTemplateType.AMENDMENT_OF_PLEADINGS,
    display_name="Application for Amendment of Pleadings",
    summary=(
        "Application under CPC Order VI Rule 17 to amend a plaint or "
        "written statement. Post-2002 amendment, applications after "
        "trial commences require a due-diligence showing under the "
        "proviso."
    ),
    statutory_basis=[
        "CPC Order VI Rule 17",
        "CPC Order VI Rule 17 proviso (post-2002 due-diligence test)",
    ],
    fields=_AMENDMENT_FIELDS,
    facts_model=AmendmentOfPleadingsFacts,
)
_register(
    DraftTemplateType.COMPROMISE_PETITION,
    display_name="Compromise Petition",
    summary=(
        "Petition recording a settlement between parties. Civil — "
        "CPC Order XXIII Rule 3. Criminal — BNSS s.359 (compoundable) "
        "or BNSS s.528 (Gian Singh framework for non-compoundable)."
    ),
    statutory_basis=[
        "CPC Order XXIII Rule 3",
        "BNSS s.359 (CrPC s.320 historical)",
        "BNSS s.528 (CrPC s.482 historical)",
        "HMA s.13B (matrimonial mutual consent)",
    ],
    fields=_COMPROMISE_FIELDS,
    facts_model=CompromisePetitionFacts,
)
_register(
    DraftTemplateType.PROBATE_PETITION,
    display_name="Probate Petition",
    summary=(
        "Petition for grant of probate of a will under the Indian "
        "Succession Act, 1925. Filed in the District Court or HC "
        "original side per pecuniary jurisdiction. Notice issues to "
        "all legal heirs under s.283."
    ),
    statutory_basis=[
        "Indian Succession Act 1925 s.276 (form of petition)",
        "Indian Succession Act 1925 s.281 (verification)",
        "Indian Succession Act 1925 s.283 (citation to heirs)",
        "Indian Succession Act 1925 s.63(c) (attestation of will)",
    ],
    fields=_PROBATE_FIELDS,
    facts_model=ProbatePetitionFacts,
)


_register(
    DraftTemplateType.SPECIAL_LEAVE_PETITION,
    display_name="Special Leave Petition (Article 136)",
    summary=(
        "SLP under Article 136 of the Constitution — civil or criminal "
        "side. The drafting prompt enforces the substantial-question "
        "framing and pulls condonation / stay / exemption boilerplate "
        "where the facts call for it."
    ),
    statutory_basis=[
        "Constitution Article 136",
        "Supreme Court Rules 2013 Order XXI",
        "Limitation Act 1963 Article 116 / Article 132 (where applicable)",
    ],
    fields=_SLP_FIELDS,
    facts_model=SpecialLeavePetitionFacts,
)
_register(
    DraftTemplateType.SUPREME_COURT_APPEAL,
    display_name="Supreme Court Appeal (Article 132 / 133 / 134)",
    summary=(
        "Substantial-question appeal to the SC under Articles 132 / "
        "133 / 134. Distinct from an Article 136 SLP — entry is by "
        "right (with HC certificate) rather than by leave."
    ),
    statutory_basis=[
        "Constitution Article 132 (constitutional appeals)",
        "Constitution Article 133 (civil appeals)",
        "Constitution Article 134 (criminal appeals)",
        "Constitution Article 134A (HC certificate of fitness)",
        "Supreme Court Rules 2013 Order XIX",
    ],
    fields=_SC_APPEAL_FIELDS,
    facts_model=SupremeCourtAppealFacts,
)
_register(
    DraftTemplateType.REVIEW_PETITION,
    display_name="Review Petition",
    summary=(
        "Review under Article 137 (SC) or Order XLVII Rule 1 CPC (HC). "
        "Narrow jurisdiction — error apparent on the face of the "
        "record, not a rehearing of the merits."
    ),
    statutory_basis=[
        "Constitution Article 137 (SC review)",
        "Supreme Court Rules 2013 Order XLVII",
        "CPC Order XLVII Rule 1 (HC review)",
    ],
    fields=_REVIEW_FIELDS,
    facts_model=ReviewPetitionFacts,
)
_register(
    DraftTemplateType.CURATIVE_PETITION,
    display_name="Curative Petition",
    summary=(
        "Curative petition under the Rupa Ashok Hurra (2002) framework. "
        "Post-review jurisdiction; requires Senior Advocate "
        "certification."
    ),
    statutory_basis=[
        "Rupa Ashok Hurra v. Ashok Hurra (2002) 4 SCC 388",
        "Supreme Court Rules 2013 Order XLVIII",
    ],
    fields=_CURATIVE_FIELDS,
    facts_model=CurativePetitionFacts,
)
_register(
    DraftTemplateType.TRANSFER_PETITION,
    display_name="Transfer Petition",
    summary=(
        "Transfer petition. Branches on the statutory basis: Article "
        "139A (SC inter-HC consolidation), Section 25 CPC (civil), or "
        "Section 406 BNSS / 527 CrPC (criminal)."
    ),
    statutory_basis=[
        "Constitution Article 139A",
        "CPC Section 25",
        "BNSS Section 406 (CrPC s.406 historical)",
    ],
    fields=_TRANSFER_FIELDS,
    facts_model=TransferPetitionFacts,
)
_register(
    DraftTemplateType.CONTEMPT_PETITION,
    display_name="Contempt Petition",
    summary=(
        "Civil / criminal contempt under the Contempt of Courts Act "
        "1971. Forum is the SC (Article 129) or the HC (Article 215). "
        "Branches on contempt_kind."
    ),
    statutory_basis=[
        "Constitution Article 129 (SC contempt)",
        "Constitution Article 215 (HC contempt)",
        "Contempt of Courts Act 1971 sections 2, 12, 14, 15",
    ],
    fields=_CONTEMPT_FIELDS,
    facts_model=ContemptPetitionFacts,
)
_register(
    DraftTemplateType.INTERIM_RELIEF_APPLICATION,
    display_name="Interim Relief Application",
    summary=(
        "Application for stay / status quo / ad-interim injunction. "
        "Walks the three-factor test (prima facie case, balance of "
        "convenience, irreparable injury) per Dalpat Kumar."
    ),
    statutory_basis=[
        "CPC Order XXXIX Rules 1, 2 (civil interim injunction)",
        "Supreme Court Rules 2013 Order XLVII (stay alongside SLP)",
        "Dalpat Kumar v. Prahlad Singh (1992) 1 SCC 719",
    ],
    fields=_INTERIM_RELIEF_FIELDS,
    facts_model=InterimReliefApplicationFacts,
)
_register(
    DraftTemplateType.CONDONATION_OF_DELAY,
    display_name="Application for Condonation of Delay",
    summary=(
        "Application under Section 5 of the Limitation Act, 1963 "
        "seeking condonation of delay in filing an appeal / SLP / "
        "review."
    ),
    statutory_basis=[
        "Limitation Act 1963 Section 5",
        "Collector, Land Acquisition v. Mst. Katiji (1987) 2 SCC 107 (sufficient cause test)",
    ],
    fields=_CONDONATION_FIELDS,
    facts_model=CondonationOfDelayFacts,
)
_register(
    DraftTemplateType.EXEMPTION_APPLICATION,
    display_name="Exemption Application (SC)",
    summary=(
        "Application seeking exemption from filing certified copy / "
        "official translation / page-limit / court-fee. Filed "
        "alongside an SLP / appeal."
    ),
    statutory_basis=[
        "Supreme Court Rules 2013 Order V (filing requirements)",
        "Supreme Court Rules 2013 Order XV Rule 5 (certified copies)",
    ],
    fields=_EXEMPTION_FIELDS,
    facts_model=ExemptionApplicationFacts,
)
_register(
    DraftTemplateType.SYNOPSIS_LIST_OF_DATES,
    display_name="Synopsis and List of Dates",
    summary=(
        "Mandatory accompaniment to every SC SLP / appeal — synopsis "
        "of the case + chronological list of dates. Drives bench-"
        "reading time."
    ),
    statutory_basis=[
        "Supreme Court Rules 2013 Order V Rule 1(3)",
        "Supreme Court Practice Directions on synopsis + list of dates",
    ],
    fields=_SYNOPSIS_FIELDS,
    facts_model=SynopsisListOfDatesFacts,
)
_register(
    DraftTemplateType.FILING_INDEX_CHECKLIST,
    display_name="Filing Index and Checklist",
    summary=(
        "Paginated index + filing checklist — drives the registry-"
        "acceptance pre-flight. Used at SC + HC."
    ),
    statutory_basis=[
        "Supreme Court Rules 2013 Order IV (registrar's office)",
        "Court-specific civil rules (HC paginated-index requirement)",
    ],
    fields=_FILING_INDEX_FIELDS,
    facts_model=FilingIndexChecklistFacts,
)


def get_template_schema(template_type: DraftTemplateType) -> DraftTemplateSchema:
    """Return the form schema for ``template_type``.

    Caller should wrap the ``KeyError`` in a 404 at the route layer.
    """
    return _REGISTRY[template_type][1]


def get_template_facts_model(
    template_type: DraftTemplateType,
) -> type[_TemplateFactsBase]:
    return _REGISTRY[template_type][0]


def list_template_schemas() -> list[DraftTemplateSchema]:
    return [schema for _, schema in _REGISTRY.values()]


__all__ = [
    "AffidavitFacts",
    "AmendmentOfPleadingsFacts",
    "AnticipatoryBailFacts",
    "AppealMemorandumFacts",
    "ArbitrationSection9Facts",
    "BailFacts",
    "CaveatPetitionFacts",
    "ChequeBounceNoticeFacts",
    "CivilSuitFacts",
    "CompromisePetitionFacts",
    "CondonationOfDelayFacts",
    "ContemptPetitionFacts",
    "CriminalComplaintFacts",
    "CurativePetitionFacts",
    "DivorcePetitionFacts",
    "DraftTemplateSchema",
    "DraftTemplateType",
    "DraftTemplateTypeLiteral",
    "DraftingFieldSpec",
    "DvQuashingPetitionFacts",
    "ExemptionApplicationFacts",
    "FilingIndexChecklistFacts",
    "InterimReliefApplicationFacts",
    "ProbatePetitionFacts",
    "PropertyDisputeNoticeFacts",
    "QuashingPetitionFacts",
    "ReplyCounterAffidavitFacts",
    "ReviewPetitionFacts",
    "SpecialLeavePetitionFacts",
    "SupremeCourtAppealFacts",
    "SynopsisListOfDatesFacts",
    "TransferPetitionFacts",
    "VakalatnamaFacts",
    "WritPetitionFacts",
    "WrittenStatementFacts",
    "get_template_facts_model",
    "get_template_schema",
    "list_template_schemas",
]
