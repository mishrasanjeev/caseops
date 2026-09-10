"""Source-pinned patent work product and prosecution, not legal automation."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from caseops_api.schemas.ip_patents import (
    NonBlankText,
    PatentContract,
    PatentDocumentSource,
    PatentProsecutionPhase,
    Sha256,
)

PatentDocumentKind = Literal[
    "claims",
    "specification",
    "drawings",
    "abstract",
    "sequence_listing",
    "translation",
    "amendment",
    "response",
    "filing_package",
]
PatentEventKind = Literal[
    "filing_preparation",
    "filing",
    "publication",
    "examination_request",
    "office_action",
    "response",
    "hearing",
    "amendment",
    "grant",
    "restoration",
]


class PatentWorkPreconditions(PatentContract):
    expected_version: int = Field(strict=True, ge=1)
    expected_lifecycle_version: int = Field(strict=True, ge=0)
    expected_work_sequence: int = Field(strict=True, ge=0)
    reason: NonBlankText = Field(min_length=5, max_length=1000)


class PatentManifestItem(PatentContract):
    document_kind: PatentDocumentKind
    source: PatentDocumentSource


class PatentEvidenceCreateRequest(PatentWorkPreconditions):
    title: NonBlankText = Field(min_length=1, max_length=255)
    document_kind: PatentDocumentKind
    predecessor_id: UUID | None = None
    source: PatentDocumentSource
    documents: tuple[PatentManifestItem, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        versions = [item.source.document_version_id for item in self.documents]
        if len(set(versions)) != len(versions):
            raise ValueError("A manifest cannot repeat a document version.")
        if self.document_kind != "filing_package" and (
            len(self.documents) != 1 or self.documents[0].document_kind != self.document_kind
        ):
            raise ValueError("A document edition pins one document of its declared kind.")
        if any(item.document_kind == "filing_package" for item in self.documents):
            raise ValueError("A filing manifest contains documents, not nested packages.")
        return self


class PatentEvidenceRecord(PatentContract):
    id: UUID
    application_id: UUID
    root_id: UUID
    predecessor_id: UUID | None
    sequence: int
    edition: int
    is_current: bool
    anchor_version: int
    lifecycle_version: int
    title: str
    document_kind: PatentDocumentKind
    source: PatentDocumentSource
    documents: tuple[PatentManifestItem, ...]
    manifest_sha256: Sha256
    reason: str
    created_at: AwareDatetime


class PatentProsecutionCreateRequest(PatentWorkPreconditions):
    event_kind: PatentEventKind
    received_on: date
    effective_on: date
    source: PatentDocumentSource
    evidence_id: UUID | None = None
    expected_phase: PatentProsecutionPhase
    exceptional_transition_reason: NonBlankText | None = Field(default=None, max_length=1000)
    preview_sha256: Sha256 | None = None
    acknowledged_exception_codes: tuple[
        Literal[
            "backdated_recalculation_review_required", "exceptional_transition_review_required"
        ],
        ...,
    ] = Field(default=(), max_length=2)


class PatentProsecutionPreview(PatentContract):
    application_id: UUID
    work_sequence: int
    current_phase: PatentProsecutionPhase
    proposed_phase: PatentProsecutionPhase
    backdated: bool
    affected_deadline_ids: tuple[UUID, ...]
    required_acknowledgements: tuple[str, ...]
    preview_sha256: Sha256
    changes_deadlines: Literal[False] = False
    authoritative_calculation_available: Literal[False] = False


class PatentProsecutionRecord(PatentContract):
    id: UUID
    application_id: UUID
    sequence: int
    anchor_version: int
    lifecycle_version: int
    event_kind: PatentEventKind
    received_on: date
    effective_on: date
    source: PatentDocumentSource
    evidence_id: UUID | None
    before_phase: PatentProsecutionPhase
    after_phase: PatentProsecutionPhase
    reason: str
    exceptional_transition_reason: str | None
    impact: PatentProsecutionPreview
    created_at: AwareDatetime


class PatentEvidencePage(PatentContract):
    application_id: UUID
    work_sequence: int
    records: list[PatentEvidenceRecord]
    next_cursor: int | None


class PatentProsecutionPage(PatentContract):
    application_id: UUID
    work_sequence: int
    records: list[PatentProsecutionRecord]
    next_cursor: int | None
