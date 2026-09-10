"""Independent specialist intake facts; no inferred rights or legal deadlines."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500, pattern=r"^[^\x00]*$"),
]
Narrative = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, pattern=r"^[^\x00]*$"),
]
Domain = Literal[
    "design",
    "copyright",
    "domain_name",
    "licensing",
    "enforcement",
    "geographical_indication",
    "plant_variety",
    "semiconductor_layout",
    "trade_secret",
    "customs_enforcement",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DesignFacts(StrictModel):
    domain: Literal["design"] = "design"
    applicant: Text
    article: Text
    classification_as_supplied: Text | None = None
    novelty_statement: Narrative | None = None
    representation_description: Narrative | None = None
    publication_instruction: Literal["unknown", "confidential", "published"] = "unknown"


class CopyrightFacts(StrictModel):
    domain: Literal["copyright"] = "copyright"
    work_type_as_supplied: Text
    author: Text
    claimant: Text
    ownership_claim: Narrative
    created_on: date | None = None
    published_on: date | None = None
    ownership_disputed: bool = False


class DomainNameFacts(StrictModel):
    domain: Literal["domain_name"] = "domain_name"
    domain_name: Text
    registrar: Text | None = None
    registrant_as_supplied: Text
    expiry_as_supplied: date | None = None
    dispute_channel_as_supplied: Text | None = None


class LicensingFacts(StrictModel):
    domain: Literal["licensing"] = "licensing"
    grantor: Text
    grantee: Text
    affected_rights_as_supplied: Narrative
    territory: Text
    field_of_use: Text | None = None
    exclusivity: Literal["not_reviewed", "exclusive", "non_exclusive", "sole"] = "not_reviewed"
    term_as_supplied: Text | None = None
    royalty_terms_confidential: Narrative | None = None
    interpretation_issue: Narrative | None = None


class EnforcementFacts(StrictModel):
    domain: Literal["enforcement"] = "enforcement"
    represented_party: Text
    asserted_right_as_supplied: Narrative
    allegation: Narrative
    proposed_channel: Literal[
        "investigation", "notice", "platform", "customs", "opposition", "cancellation", "litigation"
    ]
    alleged_party: Text | None = None


class GeographicalIndicationFacts(StrictModel):
    domain: Literal["geographical_indication"] = "geographical_indication"
    applicant_or_association: Text
    geographical_area: Narrative
    goods: Text
    specification_as_supplied: Narrative | None = None
    authorised_user_claim: Text | None = None


class PlantVarietyFacts(StrictModel):
    domain: Literal["plant_variety"] = "plant_variety"
    denomination: Text
    category_as_supplied: Text
    crop_species: Text
    applicant: Text
    breeder_as_supplied: Text | None = None
    farmer_claim_as_supplied: Text | None = None
    material_custodian: Text
    material_access_instructions: Narrative


class SemiconductorLayoutFacts(StrictModel):
    domain: Literal["semiconductor_layout"] = "semiconductor_layout"
    creator: Text
    proprietor_as_supplied: Text
    layout_description: Narrative
    first_commercial_exploitation: date | None = None
    exploitation_territory: Text | None = None


class TradeSecretFacts(StrictModel):
    domain: Literal["trade_secret"] = "trade_secret"
    owner_as_supplied: Text
    custodian: Text
    asset_reference: Text
    protective_controls: Narrative
    permitted_access_as_supplied: Narrative
    # The register stores references and controls, never the secret substance.


class CustomsFacts(StrictModel):
    domain: Literal["customs_enforcement"] = "customs_enforcement"
    right_holder: Text
    asserted_right_as_supplied: Narrative
    products: Narrative
    authority_or_channel_as_supplied: Text
    authentication_guide_custodian: Text
    authorised_importer_policy: Narrative
    instruction_reference: Text


DomainFacts = Annotated[
    DesignFacts
    | CopyrightFacts
    | DomainNameFacts
    | LicensingFacts
    | EnforcementFacts
    | GeographicalIndicationFacts
    | PlantVarietyFacts
    | SemiconductorLayoutFacts
    | TradeSecretFacts
    | CustomsFacts,
    Field(discriminator="domain"),
]


class SpecialistFacts(StrictModel):
    title: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=255, pattern=r"^[^\x00]*$"
        ),
    ]
    client_id: UUID
    jurisdiction_as_supplied: Text
    details: DomainFacts


class SpecialistCorrection(StrictModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    reason: Text
    facts: SpecialistFacts


class SpecialistSource(StrictModel):
    document_id: UUID
    document_version_id: UUID
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: Text


class SpecialistObservation(StrictModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    kind: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    occurred_on: date
    account: Narrative
    source: SpecialistSource
    supersedes_id: UUID | None = None


class SpecialistRecord(StrictModel):
    id: UUID
    docket_id: UUID
    asset_id: UUID
    contract_version: str
    version: int
    lifecycle_version: int
    lifecycle_status: str
    is_active: bool
    created_at: datetime
    facts: SpecialistFacts


class SpecialistSummary(StrictModel):
    id: UUID
    domain: Domain
    title: str
    lifecycle_status: str
    version: int


class SpecialistList(StrictModel):
    records: list[SpecialistSummary]
    next_cursor: UUID | None


class SpecialistObservationRecord(StrictModel):
    id: UUID
    sequence: int
    kind: str
    occurred_on: date
    account: str
    source: SpecialistSource
    supersedes_id: UUID | None
    recorded_at: datetime
    legal_effect: Literal["not_determined"] = "not_determined"


class SpecialistObservationList(StrictModel):
    observations: list[SpecialistObservationRecord]
    next_cursor: int | None


class SpecialistField(StrictModel):
    key: str
    label: str
    kind: Literal["text", "textarea", "date", "boolean", "select"]
    required: bool
    max_length: int | None = None
    options: list[str] = Field(default_factory=list)


class SpecialistContract(StrictModel):
    domain: Domain
    label: str
    contract_version: str
    contract_path: str
    child_prd_sha256: str
    intake_available: bool
    fields: list[SpecialistField]
    observation_kinds: list[str]
    blockers: list[str]
