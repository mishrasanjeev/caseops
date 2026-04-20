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
    """The eight specialised templates covered in Sprint R.

    Ordered by how frequently Indian litigators use them (bail
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


DraftTemplateTypeLiteral = Literal[
    "bail",
    "anticipatory_bail",
    "divorce_petition",
    "property_dispute_notice",
    "cheque_bounce_notice",
    "affidavit",
    "criminal_complaint",
    "civil_suit",
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
    "AnticipatoryBailFacts",
    "BailFacts",
    "ChequeBounceNoticeFacts",
    "CivilSuitFacts",
    "CriminalComplaintFacts",
    "DivorcePetitionFacts",
    "DraftTemplateSchema",
    "DraftTemplateType",
    "DraftTemplateTypeLiteral",
    "DraftingFieldSpec",
    "PropertyDisputeNoticeFacts",
    "get_template_facts_model",
    "get_template_schema",
    "list_template_schemas",
]
