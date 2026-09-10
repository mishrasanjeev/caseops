"""Source-reported specialist workflows; no inferred legal dates or entitlements."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from caseops_api.schemas.ip_specialist import SpecialistSource, StrictModel

Label = Annotated[str, Field(min_length=1, max_length=255)]
Note = Annotated[str, Field(min_length=1, max_length=4000)]


class SourceMember(StrictModel):
    role: Label
    source: SpecialistSource


class SourceSet(StrictModel):
    kind: Literal["source_set"] = "source_set"
    purpose: Literal[
        "representations", "deposit", "instrument", "proceeding_evidence", "layout_deposit"
    ]
    title: Label
    members: list[SourceMember] = Field(min_length=1, max_length=25)
    confidentiality: Literal["restricted", "publication_authorized"] = "restricted"
    publication_instruction: Note | None = None
    publication_on_as_supplied: date | None = None

    @model_validator(mode="after")
    def validate_members(self):
        keys = [(m.source.document_version_id, m.source.locator, m.role) for m in self.members]
        if len(keys) != len(set(keys)):
            raise ValueError("A source member may appear only once in a set.")
        if self.confidentiality == "publication_authorized" and not self.publication_instruction:
            raise ValueError("Retain the explicit publication instruction.")
        return self


class SetReference(StrictModel):
    id: UUID
    version: int = Field(ge=1)


class Sourced(StrictModel):
    title: Label
    source_set: SetReference
    occurred_on: date
    account: Note


class DesignApplication(Sourced):
    kind: Literal["design_application"] = "design_application"
    registry: Label
    jurisdiction: Annotated[str, Field(min_length=1, max_length=40)]
    identifier_as_supplied: Label | None = None
    stage: Literal[
        "prepared",
        "filed",
        "examination",
        "objection",
        "response",
        "hearing",
        "accepted",
        "registered",
        "refused",
        "withdrawn",
    ] = "prepared"
    publication: Literal["not_recorded", "deferred", "published"] = "not_recorded"
    publication_on: date | None = None
    registration_identifier: Label | None = None
    registration_on: date | None = None
    protection_from: date | None = None
    protection_until: date | None = None
    period_action: Literal["none", "renewal", "extension"] = "none"
    variant_of: UUID | None = None
    variant_basis: SpecialistSource | None = None

    @model_validator(mode="after")
    def validate_design(self):
        if self.stage != "prepared" and not self.identifier_as_supplied:
            raise ValueError("Supply the source-reported application identifier.")
        if self.stage == "registered" and not (
            self.registration_identifier and self.registration_on
        ):
            raise ValueError("Registration requires its own identifier and date.")
        if self.publication == "published" and self.publication_on is None:
            raise ValueError("Supply the publication date from the source.")
        if self.period_action != "none" and not (self.protection_from and self.protection_until):
            raise ValueError("Renewal/extension requires the source-reported protection period.")
        if (
            self.protection_until
            and self.protection_from
            and self.protection_until < self.protection_from
        ):
            raise ValueError("The protection period is reversed.")
        if (self.variant_of is None) != (self.variant_basis is None):
            raise ValueError(
                "A variant requires its parent and jurisdiction-specific source basis."
            )
        return self


class CopyrightRegistration(Sourced):
    kind: Literal["copyright_registration"] = "copyright_registration"
    registry: Label
    jurisdiction: Annotated[str, Field(min_length=1, max_length=40)]
    identifier_as_supplied: Label | None = None
    stage: Literal[
        "prepared",
        "filed",
        "deficiency",
        "objection",
        "response",
        "hearing",
        "registered",
        "correction",
        "expunged",
        "refused",
        "withdrawn",
    ] = "prepared"
    registration_identifier: Label | None = None
    registration_on: date | None = None
    rights_effect: Literal["not_determined_by_registration"] = "not_determined_by_registration"

    @model_validator(mode="after")
    def validate_registration(self):
        if self.stage != "prepared" and not self.identifier_as_supplied:
            raise ValueError("Supply the application identifier from the source.")
        if self.stage == "registered" and not (
            self.registration_identifier and self.registration_on
        ):
            raise ValueError("Registration requires its own identifier and date.")
        return self


class LayoutApplication(Sourced):
    kind: Literal["layout_application"] = "layout_application"
    registry: Label
    jurisdiction: Annotated[str, Field(min_length=1, max_length=40)]
    identifier_as_supplied: Label | None = None
    stage: Literal[
        "prepared",
        "filed",
        "examination",
        "objection",
        "response",
        "hearing",
        "registered",
        "refused",
        "withdrawn",
    ] = "prepared"
    registration_identifier: Label | None = None
    registration_on: date | None = None
    first_exploitation_on_as_supplied: date | None = None
    exploitation_territory_as_supplied: Label | None = None
    publication: Literal["not_recorded", "reported_published"] = "not_recorded"
    publication_on: date | None = None
    registry_source: SpecialistSource | None = None
    cost_item_id: UUID | None = None
    legal_eligibility: Literal["not_determined"] = "not_determined"
    rights_effect: Literal["not_determined_by_registration"] = "not_determined_by_registration"

    @model_validator(mode="after")
    def validate_layout(self):
        if self.stage != "prepared" and not self.identifier_as_supplied:
            raise ValueError("Supply the layout application identifier from the source.")
        if self.stage == "registered" and not (
            self.registration_identifier and self.registration_on
        ):
            raise ValueError("Layout registration requires its own identifier and date.")
        if (self.first_exploitation_on_as_supplied is None) != (
            self.exploitation_territory_as_supplied is None
        ):
            raise ValueError("Retain both the supplied exploitation date and territory.")
        if self.publication == "reported_published" and not (
            self.publication_on and self.registry_source
        ):
            raise ValueError(
                "Registry publication requires a supplied date and separate exact source."
            )
        if self.publication == "not_recorded" and (self.publication_on or self.registry_source):
            raise ValueError(
                "Unrecorded publication cannot retain a publication date or registry source."
            )
        return self


class RightsClaim(Sourced):
    kind: Literal["rights_claim"] = "rights_claim"
    claimant: Label
    interest: Literal["authorship", "ownership", "assignment", "licence", "permission"]
    rights: Note
    territory: Label
    effective_from: date
    effective_until: date | None = None
    predecessor: UUID | None = None
    competing_claims: list[UUID] = Field(default_factory=list, max_length=25)
    review: Literal["unreviewed", "unresolved", "supported", "rejected"] = "unreviewed"
    review_reason: Note | None = None

    @model_validator(mode="after")
    def validate_claim(self):
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("The interest period is reversed.")
        if self.review in {"supported", "rejected"} and not self.review_reason:
            raise ValueError("Retain the review rationale and supporting source set.")
        if len(set(self.competing_claims)) != len(self.competing_claims):
            raise ValueError("Competing claims must be distinct.")
        return self


class ReviewIssue(StrictModel):
    clause: Label
    question: Note
    resolution: Note | None = None
    source: SpecialistSource


class FinancialTerms(StrictModel):
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    royalty: Note | None = None
    fee_minor: int | None = Field(default=None, ge=0)
    minimum_minor: int | None = Field(default=None, ge=0)
    reporting: Note | None = None
    audit: Note | None = None


class Licence(Sourced):
    kind: Literal["licence"] = "licence"
    grantor: Label
    grantee: Label
    transaction: Literal["licence", "assignment", "permission", "security_interest"]
    exclusivity: Literal["exclusive", "nonexclusive", "sole", "not_stated"]
    rights: Note
    territory: Label
    field_of_use: Note
    sublicensing: Note
    quality_control: Note
    prosecution_control: Note
    enforcement_control: Note
    renewal_terms: Note
    termination_terms: Note
    notice_terms: Note
    effective_from: date
    effective_until: date | None = None
    extracted_by: Literal["manual", "document_extraction"] = "manual"
    interpretation: Literal["unreviewed", "issues_open", "reviewed"] = "unreviewed"
    review_reason: Note | None = None
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=25)
    financial_terms: FinancialTerms | None = None
    financial_terms_withheld: bool = False
    status: Literal["draft", "active", "terminated"] = "draft"
    recordal: Literal[
        "not_determined",
        "not_required_as_reviewed",
        "required",
        "filed",
        "deficiency",
        "accepted",
        "rejected",
        "withdrawn",
    ] = "not_determined"
    recordal_identifier: Label | None = None
    recordal_on: date | None = None
    termination_on: date | None = None

    @model_validator(mode="after")
    def validate_licence(self):
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("The grant period is reversed.")
        if self.interpretation == "reviewed" and (
            not self.review_reason or any(not i.resolution for i in self.issues)
        ):
            raise ValueError("Review requires a rationale and resolution of every issue.")
        if self.status != "draft" and self.interpretation != "reviewed":
            raise ValueError("Review the extracted terms before activating the grant.")
        if self.status == "terminated" and self.termination_on is None:
            raise ValueError("Retain the termination date from the source.")
        if self.termination_on and self.termination_on < self.effective_from:
            raise ValueError("Termination precedes the retained grant period.")
        if (
            self.recordal in {"filed", "deficiency", "accepted", "rejected", "withdrawn"}
            and not self.recordal_identifier
        ):
            raise ValueError("Recordal requires its source-reported identifier.")
        if self.recordal == "accepted" and self.recordal_on is None:
            raise ValueError("Retain the accepted recordal date.")
        return self


class SpecialistProceeding(Sourced):
    kind: Literal["proceeding"] = "proceeding"
    channel: Literal[
        "design_cancellation",
        "copyright_registry",
        "platform_takedown",
        "court",
        "settlement",
        "layout_opposition",
        "layout_cancellation",
        "layout_infringement",
    ]
    authority: Annotated[str, Field(min_length=1, max_length=80)]
    jurisdiction: Annotated[str, Field(min_length=1, max_length=40)]
    identifier_as_supplied: Label
    related_workflow: UUID | None = None
    stage: Literal["opened", "notice", "response", "hearing", "decision", "appeal", "closed"] = (
        "opened"
    )
    disposition: Literal[
        "pending",
        "platform_removed",
        "platform_declined",
        "allowed",
        "dismissed",
        "settled",
        "withdrawn",
    ] = "pending"

    @model_validator(mode="after")
    def validate_disposition(self):
        platform = self.disposition in {"platform_removed", "platform_declined"}
        if platform and self.channel != "platform_takedown":
            raise ValueError("A platform response cannot be a court or registry disposition.")
        if self.channel == "platform_takedown" and self.disposition in {"allowed", "dismissed"}:
            raise ValueError("Record the platform response, not a judicial disposition.")
        if (
            self.channel
            in {
                "design_cancellation",
                "layout_opposition",
                "layout_cancellation",
                "layout_infringement",
            }
            and self.related_workflow is None
        ):
            raise ValueError("Identify the separate application under challenge.")
        return self


WorkflowFacts = Annotated[
    SourceSet
    | DesignApplication
    | CopyrightRegistration
    | LayoutApplication
    | RightsClaim
    | Licence
    | SpecialistProceeding,
    Field(discriminator="kind"),
]


class WorkflowSave(StrictModel):
    expected_version: int = Field(ge=0)
    expected_lifecycle_version: int = Field(ge=0)
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    facts: WorkflowFacts


class WorkflowRecord(StrictModel):
    id: UUID
    record_id: UUID
    version: int
    lifecycle_version: int
    canonical_proceeding_id: UUID | None
    canonical_title_interest_id: UUID | None
    recorded_at: datetime
    facts: WorkflowFacts


class WorkflowList(StrictModel):
    records: list[WorkflowRecord]
    next_cursor: UUID | None = None


class ContractObligation(StrictModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    kind: Literal[
        "royalty",
        "reporting",
        "audit",
        "quality_control",
        "recordal",
        "notice",
        "renewal",
        "termination",
        "filing",
        "office_response",
        "hearing",
    ]
    title: Label
    due_on_as_supplied: date
    source: SpecialistSource
    cost_item_id: UUID | None = None


class ContractObligationRecord(StrictModel):
    id: UUID
    task_id: UUID
    deadline_id: UUID
    due_on: date
    kind: str
    title: str
    status: str
    source: SpecialistSource
    cost_item_id: UUID | None


class ContractPerformance(StrictModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_status: Literal["open"] = "open"
    action: Literal["complete", "cancel", "notice_recorded"]
    occurred_on: date
    account: Note
    source: SpecialistSource
    replacement_cost_item_id: UUID | None = None


class ContractPerformanceRecord(StrictModel):
    id: UUID
    obligation_id: UUID
    action: str
    occurred_on: date
    account: str
    source: SpecialistSource
    cost_item_id: UUID | None
    recorded_at: datetime


class ContractObligationList(StrictModel):
    records: list[ContractObligationRecord] = Field(max_length=10)
    next_cursor: UUID | None


class ContractPerformanceList(StrictModel):
    records: list[ContractPerformanceRecord] = Field(max_length=10)
    next_cursor: UUID | None


class ContractCostOption(StrictModel):
    id: UUID
    description: Annotated[str, Field(max_length=500)]


class ContractCostOptions(StrictModel):
    records: list[ContractCostOption] = Field(max_length=10)
    next_cursor: UUID | None


class ContractCostCreate(StrictModel):
    expected_lifecycle_version: int = Field(ge=0)
    description: Annotated[str, Field(min_length=1, max_length=500)]
    amount_minor: int = Field(ge=0)
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    cost_nature: Literal["actual", "estimate"] = "actual"
    source: SpecialistSource


class ContractCostVoid(StrictModel):
    expected_lifecycle_version: int = Field(ge=0)
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    source: SpecialistSource
