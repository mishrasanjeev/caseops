"""PAT-2026-09-06.1 typed facts; these contracts do not activate patent intake.

Source pins reference existing document/registry owners. A schema-valid pin is
not authorization or verified legal evidence: writers must resolve it under the
current tenant, docket access and immutable content hash before persistence.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

PatentApplicationKind = Literal[
    "provisional",
    "complete",
    "convention",
    "pct_international",
    "national_phase",
    "divisional",
    "patent_of_addition",
]
PatentProsecutionPhase = Literal[
    "disclosure",
    "filing_preparation",
    "filed",
    "published",
    "examination_requested",
    "examination",
    "response_filed",
    "hearing",
    "granted",
    "refused",
    "withdrawn",
    "abandoned",
    "closed",
]
PatentIdentifierKind = Literal["application", "publication", "grant"]
PatentPartyRole = Literal["inventor", "applicant", "proprietor", "agent", "licensee"]
PatentRelationKind = Literal[
    "priority",
    "divisional_parent",
    "addition_parent",
    "national_phase_parent",
]
PatentPriorityReviewFlag = Literal[
    "office_names_differ",
    "jurisdictions_differ",
    "filing_dates_incomplete",
    "priority_date_precedes_parent_filing",
]
PatentProceedingKind = Literal[
    "pre_grant_opposition",
    "post_grant_opposition",
    "revocation",
    "compulsory_licence",
]


def _no_null_character(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Text cannot contain a null character.")
    return value


NonBlankText = Annotated[str, StringConstraints(pattern=r"\S"), AfterValidator(_no_null_character)]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
PositiveVersion = Annotated[int, Field(strict=True, ge=1)]


class PatentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PatentDocumentSource(PatentContract):
    kind: Literal["document_version"] = "document_version"
    document_id: UUID
    document_version_id: UUID
    content_sha256: Sha256


class PatentRegistrySource(PatentContract):
    kind: Literal["registry_snapshot"] = "registry_snapshot"
    snapshot_id: UUID
    raw_sha256: Sha256
    normalized_sha256: Sha256


PatentSourcePin = Annotated[
    PatentDocumentSource | PatentRegistrySource, Field(discriminator="kind")
]


class PatentIdentifierFact(PatentContract):
    identifier_kind: PatentIdentifierKind
    raw_value: NonBlankText = Field(min_length=1, max_length=120)
    source: PatentSourcePin


class PatentAddressSnapshot(PatentContract):
    address_lines: tuple[Annotated[NonBlankText, Field(max_length=255)], ...] = Field(
        min_length=1,
        max_length=5,
    )
    city: NonBlankText = Field(max_length=120)
    region: NonBlankText | None = Field(default=None, max_length=120)
    postal_code: NonBlankText | None = Field(default=None, max_length=40)
    country_code: CountryCode


class PatentPartyFact(PatentContract):
    role: PatentPartyRole
    name: NonBlankText = Field(max_length=255)
    client_id: UUID | None = None
    address: PatentAddressSnapshot
    effective_from: date
    effective_until: date | None = None
    source: PatentSourcePin

    @model_validator(mode="after")
    def ordered_effective_range(self) -> Self:
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("A party's effective end cannot precede its start.")
        return self


class PatentFamilyFacts(PatentContract):
    title: NonBlankText = Field(max_length=255)
    client_id: UUID
    disclosure_date: date
    disclosure_narrative: NonBlankText = Field(max_length=30_000)
    confidentiality: Literal["restricted"] = "restricted"
    source: PatentSourcePin | None = None


class PatentFamilyCreateRequest(PatentFamilyFacts):
    pass


class PatentFamilyCorrectionRequest(PatentContract):
    expected_version: PositiveVersion
    expected_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    reason: NonBlankText = Field(min_length=8, max_length=1000)
    facts: PatentFamilyFacts


class PatentFamilyLifecycleEvent(PatentContract):
    id: UUID
    sequence: PositiveVersion
    from_status: str | None
    to_status: str | None
    effective_at: AwareDatetime
    entered_at: AwareDatetime
    reason: str | None
    evidence_refs: list[str] = Field(max_length=100)


class PatentFamilyLifecycleHistory(PatentContract):
    events: list[PatentFamilyLifecycleEvent] = Field(max_length=100)
    next_cursor: PositiveVersion | None


class PatentApplicationFacts(PatentContract):
    title: NonBlankText = Field(max_length=255)
    application_kind: PatentApplicationKind
    jurisdiction: CountryCode
    office: NonBlankText = Field(max_length=80)
    filing_date: date | None = None
    publication_date: date | None = None
    identifiers: tuple[PatentIdentifierFact, ...] = Field(default=(), max_length=20)
    source_pending_identifier_allocation: StrictBool = False
    source: PatentSourcePin

    @model_validator(mode="after")
    def consistent_recorded_facts(self) -> Self:
        if (
            self.publication_date is not None
            and self.filing_date is not None
            and self.publication_date < self.filing_date
        ):
            raise ValueError("Publication cannot precede the recorded filing date.")
        if self.source_pending_identifier_allocation and any(
            identifier.identifier_kind == "application" for identifier in self.identifiers
        ):
            raise ValueError("An allocated application number cannot also be pending allocation.")
        raw_keys = {(row.identifier_kind, row.raw_value) for row in self.identifiers}
        if len(raw_keys) != len(self.identifiers):
            raise ValueError("An identifier fact may appear only once.")
        return self


class PatentApplicationCreateRequest(PatentContract):
    family_id: UUID
    expected_family_version: PositiveVersion
    expected_family_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    facts: PatentApplicationFacts


class PatentApplicationCorrectionRequest(PatentContract):
    expected_version: PositiveVersion
    expected_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    reason: NonBlankText = Field(min_length=8, max_length=1000)
    facts: PatentApplicationFacts


class PatentPriorityCreateRequest(PatentContract):
    parent_application_id: UUID
    expected_application_version: PositiveVersion
    expected_parent_version: PositiveVersion
    expected_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    expected_parent_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    expected_priority_sequence: Annotated[int, Field(strict=True, ge=0)]
    supersedes_priority_id: UUID | None = None
    withdrawn: StrictBool = False
    relation_kind: PatentRelationKind
    priority_date: date
    source: PatentSourcePin
    reason: NonBlankText = Field(min_length=8, max_length=1000)

    @model_validator(mode="after")
    def withdrawal_requires_predecessor(self) -> Self:
        if self.withdrawn and self.supersedes_priority_id is None:
            raise ValueError("Withdrawing a recorded link requires its current predecessor.")
        return self


class PatentPartyCreateRequest(PatentContract):
    expected_version: PositiveVersion
    expected_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    expected_party_sequence: Annotated[int, Field(strict=True, ge=0)]
    supersedes_party_id: UUID | None = None
    reason: NonBlankText = Field(min_length=8, max_length=1000)
    fact: PatentPartyFact


class PatentAnchorRecord(PatentContract):
    id: UUID
    docket_id: UUID
    version: PositiveVersion
    lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    lifecycle_status: NonBlankText = Field(max_length=32)
    is_active: StrictBool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class PatentFamilyRecord(PatentAnchorRecord):
    record_kind: Literal["patent_family"] = "patent_family"
    asset_id: UUID
    facts: PatentFamilyFacts


class PatentApplicationRecord(PatentAnchorRecord):
    record_kind: Literal["patent_application"] = "patent_application"
    family_id: UUID
    prosecution_phase: PatentProsecutionPhase
    facts: PatentApplicationFacts


class PatentPartyRecord(PatentContract):
    id: UUID
    docket_id: UUID
    sequence: PositiveVersion
    anchor_version: PositiveVersion
    lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    supersedes_party_id: UUID | None = None
    is_current: StrictBool
    fact: PatentPartyFact
    reason: NonBlankText = Field(min_length=8, max_length=1000)
    created_at: AwareDatetime


class PatentPartyListResponse(PatentContract):
    docket_id: UUID
    collection_sequence: Annotated[int, Field(strict=True, ge=0)]
    parties: tuple[PatentPartyRecord, ...] = Field(max_length=100)
    next_cursor: PositiveVersion | None = None


class PatentPriorityRecord(PatentContract):
    id: UUID
    canonical_relationship_id: UUID
    application_id: UUID
    parent_application_id: UUID
    current_application_title: NonBlankText = Field(max_length=255)
    current_parent_title: NonBlankText = Field(max_length=255)
    sequence: PositiveVersion
    application_version: PositiveVersion
    parent_version: PositiveVersion
    lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    parent_lifecycle_version: Annotated[int, Field(strict=True, ge=0)]
    supersedes_priority_id: UUID | None = None
    withdrawn: StrictBool
    is_current: StrictBool
    review_flags: tuple[PatentPriorityReviewFlag, ...] = Field(max_length=4)
    relation_kind: PatentRelationKind
    priority_date: date
    source: PatentSourcePin
    reason: NonBlankText = Field(min_length=8, max_length=1000)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def no_self_priority(self) -> Self:
        if self.application_id == self.parent_application_id:
            raise ValueError("An application cannot claim priority from itself.")
        return self


class PatentPriorityListResponse(PatentContract):
    application_id: UUID
    collection_sequence: Annotated[int, Field(strict=True, ge=0)]
    priorities: tuple[PatentPriorityRecord, ...] = Field(max_length=100)
    next_cursor: PositiveVersion | None = None


class PatentFamilyListResponse(PatentContract):
    families: tuple[PatentFamilyRecord, ...] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=512)


class PatentApplicationListResponse(PatentContract):
    applications: tuple[PatentApplicationRecord, ...] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=512)


class PatentFamilyGraphResponse(PatentContract):
    family_id: UUID
    applications: tuple[PatentApplicationRecord, ...] = Field(max_length=100)
    priorities: tuple[PatentPriorityRecord, ...] = Field(max_length=500)
    applications_next_cursor: NonBlankText | None = Field(default=None, max_length=512)
    priorities_next_cursor: NonBlankText | None = Field(default=None, max_length=512)
    has_more_applications: StrictBool
    has_more_relationships: StrictBool

    @model_validator(mode="after")
    def explicit_independent_continuation(self) -> Self:
        if self.has_more_applications != (self.applications_next_cursor is not None):
            raise ValueError("An incomplete application page requires its own continuation.")
        if self.has_more_relationships != (self.priorities_next_cursor is not None):
            raise ValueError("An incomplete priority page requires its own continuation.")
        if any(row.family_id != self.family_id for row in self.applications):
            raise ValueError("A family page cannot contain another family's applications.")
        for rows in (self.applications, self.priorities):
            if len({row.id for row in rows}) != len(rows):
                raise ValueError("A graph page cannot repeat the same record identity.")
        return self
