from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from caseops_api.schemas.source_actions import SourceActionRecord

MatterFileQAAnswerMode = Literal[
    "direct",
    "summary",
    "sections",
    "allegations",
    "evidence",
    "chronology",
    "gaps",
]
MatterFileQAStatus = Literal[
    "answered",
    "partial_answer",
    "insufficient_evidence",
    "processing_required",
    "no_documents",
    "error",
]
MatterFileQAConfidence = Literal["high", "medium", "low", "insufficient"]
MatterFileQAAnalysisLanguage = Literal["en", "hi", "mr", "gu", "ta", "te", "kn", "bn"]
MatterFileQATranslationStatus = Literal[
    "not_requested",
    "provided",
    "not_available",
    "failed_closed",
]
MatterFileQAStructuredItemType = Literal[
    "section",
    "allegation",
    "evidence",
    "chronology",
    "gap",
]
MatterFileQAEvidenceStatus = Literal["supported", "partial", "insufficient_evidence"]


class MatterFileQARequest(BaseModel):
    question: str = Field(min_length=4, max_length=800)
    document_type_filter: list[str] | None = Field(default=None, max_length=12)
    answer_mode: MatterFileQAAnswerMode = "direct"
    analysis_language: MatterFileQAAnalysisLanguage = "en"
    limit: int = Field(default=8, ge=3, le=12)


class MatterFileQASource(BaseModel):
    source_id: str = Field(min_length=1)
    attachment_id: str = Field(min_length=1)
    attachment_name: str
    chunk_id: str = Field(min_length=1)
    chunk_index: int
    document_type: str | None = None
    page_number: int | None = None
    snippet: str = Field(max_length=800)
    score: int
    matched_terms: list[str] = Field(default_factory=list)
    source_action: SourceActionRecord | None = None


class MatterFileQAStructuredItem(BaseModel):
    item_type: MatterFileQAStructuredItemType
    label: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=800)
    source_ids: list[str] = Field(min_length=1, max_length=12)
    confidence: MatterFileQAConfidence
    evidence_status: MatterFileQAEvidenceStatus


class MatterFileQAResponse(BaseModel):
    matter_id: str
    question: str
    status: MatterFileQAStatus
    answer: str | None = None
    analysis_language: MatterFileQAAnalysisLanguage = "en"
    local_language_analysis: str | None = Field(default=None, max_length=5000)
    translation_status: MatterFileQATranslationStatus = "not_requested"
    translation_warning: str | None = Field(default=None, max_length=320)
    confidence: MatterFileQAConfidence
    sources: list[MatterFileQASource] = Field(default_factory=list)
    structured_items: list[MatterFileQAStructuredItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provider: str
    generated_at: datetime
    model_run_id: str | None = None
    history_entry_id: str | None = None


class MatterFileQAHistoryEntry(BaseModel):
    id: str
    matter_id: str
    question: str
    answer_status: MatterFileQAStatus
    answer: str | None = None
    analysis_language: MatterFileQAAnalysisLanguage = "en"
    local_language_analysis: str | None = Field(default=None, max_length=5000)
    translation_status: MatterFileQATranslationStatus = "not_requested"
    translation_warning: str | None = Field(default=None, max_length=320)
    confidence: MatterFileQAConfidence
    answer_mode: MatterFileQAAnswerMode
    sources: list[MatterFileQASource] = Field(default_factory=list)
    structured_items: list[MatterFileQAStructuredItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_run_id: str | None = None
    exported_note_id: str | None = None
    exported_at: datetime | None = None
    created_at: datetime


class MatterFileQAHistoryResponse(BaseModel):
    matter_id: str
    entries: list[MatterFileQAHistoryEntry] = Field(default_factory=list)


class MatterFileQAExportNoteResponse(BaseModel):
    matter_id: str
    entry_id: str
    note_id: str
    already_exported: bool
    exported_at: datetime
