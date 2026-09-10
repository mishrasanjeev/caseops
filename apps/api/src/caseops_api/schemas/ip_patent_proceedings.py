"""Patent pre-grant opposition facts, without inferred statutory deadlines."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from caseops_api.schemas.ip_patent_prosecution import PatentWorkPreconditions
from caseops_api.schemas.ip_patents import (
    NonBlankText,
    PatentContract,
    PatentDocumentSource,
    Sha256,
)
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier

PatentOppositionStage = Literal[
    "notice_recorded",
    "response_preparation",
    "response_filed",
    "hearing_recorded",
    "decided",
    "withdrawn",
]


class PatentProceedingCommand(PatentWorkPreconditions):
    source: PatentDocumentSource
    received_on: date
    effective_on: date
    proceeding_number: NonBlankText | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def number_is_real(self) -> Self:
        if self.proceeding_number and not normalize_ip_identifier(self.proceeding_number):
            raise ValueError("A proceeding number must contain a letter or number.")
        return self


class PatentProceedingCreateRequest(PatentProceedingCommand):
    proceeding_kind: Literal["patent_pre_grant_opposition"] = "patent_pre_grant_opposition"
    title: NonBlankText = Field(min_length=2, max_length=255)
    counterparty: NonBlankText = Field(min_length=2, max_length=255)
    side: Literal["applicant", "opponent"]
    source_pending_identifier_allocation: bool = Field(strict=True)

    @model_validator(mode="after")
    def identifier_state(self) -> Self:
        if bool(self.proceeding_number) == self.source_pending_identifier_allocation:
            raise ValueError("Supply the sourced number or explicitly mark allocation pending.")
        return self


class PatentProceedingTransitionRequest(PatentProceedingCommand):
    expected_proceeding_version: int = Field(strict=True, ge=1)
    to_stage: PatentOppositionStage
    evidence_id: UUID | None = None
    outcome: NonBlankText | None = Field(default=None, min_length=5, max_length=1000)
    exceptional_transition_reason: NonBlankText | None = Field(
        default=None, min_length=5, max_length=1000
    )
    preview_sha256: Sha256 | None = None
    acknowledged_exception_codes: tuple[
        Literal["backdated_source_review", "exceptional_stage_review"], ...
    ] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def terminal_outcome(self) -> Self:
        if (self.to_stage in {"decided", "withdrawn"}) != bool(self.outcome):
            raise ValueError("An outcome is required only for decision or withdrawal.")
        if self.to_stage == "response_filed" and self.evidence_id is None:
            raise ValueError("A filed response requires an exact response manifest.")
        return self


class PatentProceedingPreview(PatentContract):
    proceeding_id: UUID
    current_stage: PatentOppositionStage
    proposed_stage: PatentOppositionStage
    required_acknowledgements: tuple[str, ...]
    preview_sha256: Sha256
    changes_application_phase: Literal[False] = False
    changes_deadlines: Literal[False] = False


class PatentProceedingEventRecord(PatentContract):
    id: UUID
    revision: int
    sequence: int
    anchor_version: int
    lifecycle_version: int
    before_stage: PatentOppositionStage | None
    after_stage: PatentOppositionStage
    source: PatentDocumentSource
    received_on: date
    effective_on: date
    proceeding_number: str | None
    evidence_id: UUID | None
    reason: str
    outcome: str | None
    exceptional_transition_reason: str | None
    impact: PatentProceedingPreview | None
    created_at: AwareDatetime


class PatentProceedingRecord(PatentContract):
    id: UUID
    application_id: UUID
    docket_id: UUID
    proceeding_kind: Literal["patent_pre_grant_opposition"]
    title: str
    counterparty: str
    side: Literal["applicant", "opponent"]
    office: str
    jurisdiction: str
    version: int
    stage: PatentOppositionStage
    lifecycle_version: int
    operational: bool
    allowed_stages: tuple[PatentOppositionStage, ...]
    latest: PatentProceedingEventRecord


class PatentProceedingPage(PatentContract):
    application_id: UUID
    work_sequence: int
    records: list[PatentProceedingRecord]
    next_cursor: str | None


class PatentProceedingHistory(PatentContract):
    proceeding: PatentProceedingRecord
    events: list[PatentProceedingEventRecord]
