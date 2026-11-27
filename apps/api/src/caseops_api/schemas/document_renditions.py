"""Typed contracts for Matter Documents "OCR & Translate"."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RenditionLanguage = Literal[
    "en", "hi", "mr", "gu", "ta", "te", "kn", "bn", "ml", "pa", "od", "ur", "as"
]
RenditionKindLiteral = Literal["ocr", "translation"]
RenditionStatusLiteral = Literal[
    "queued",
    "inspecting",
    "ocr_processing",
    "ocr_completed",
    "translation_processing",
    "translation_completed",
    "review_required",
    "failed",
]
RenditionReviewStatusLiteral = Literal["unreviewed", "reviewed", "needs_correction"]

# Languages Google's Translation LLM officially supports to and from English
# (Cloud Translation language table, checked 2026-11-27). Odia, Urdu and
# Assamese are OCR-only: Google lists Odia as experimental and Assamese as
# unsupported for the Translation LLM, and an Urdu translation PDF needs a
# right-to-left font CaseOps does not ship yet. Others stay off until added here.
TRANSLATION_LANGUAGES: tuple[str, ...] = ("hi", "mr", "gu", "ta", "te", "kn", "bn", "ml", "pa")
SUPPORTED_TRANSLATION_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {(language, "en") for language in TRANSLATION_LANGUAGES}
    | {("en", language) for language in TRANSLATION_LANGUAGES}
)


def _assert_pair(source: str, target: str) -> None:
    if (source, target) not in SUPPORTED_TRANSLATION_PAIRS:
        raise ValueError(
            f"Translation from {source} to {target} is not supported. Translation runs "
            "between English and Hindi, Marathi, Gujarati, Tamil, Telugu, Kannada, "
            "Bengali, Malayalam or Punjabi; Odia, Urdu and Assamese are OCR only."
        )


class RenditionCreateRequest(BaseModel):
    """Run OCR, and optionally translate the OCR result when it is ready."""

    model_config = ConfigDict(extra="forbid")

    source_language: RenditionLanguage
    target_language: RenditionLanguage | None = None

    @model_validator(mode="after")
    def _pair(self) -> RenditionCreateRequest:
        if self.target_language is not None:
            _assert_pair(self.source_language, self.target_language)
        return self


class TranslationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_language: RenditionLanguage


class RenditionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: Literal["reviewed", "needs_correction"]
    note: str | None = Field(default=None, max_length=2000)


class LanguagePair(BaseModel):
    source: RenditionLanguage
    target: RenditionLanguage


class ProviderReadiness(BaseModel):
    ocr_provider_available: bool
    ocr_unavailable_reason: str | None = None
    translation_available: bool
    translation_unavailable_reason: str | None = None
    third_party_processing_permitted: bool
    ocr_languages: list[RenditionLanguage]
    translation_pairs: list[LanguagePair]


class RenditionBlock(BaseModel):
    tag: str
    text: str
    confidence: float | None = None


class RenditionParagraph(BaseModel):
    index: int
    kind: str
    source: str
    translated: str | None = None
    source_unavailable: bool = False
    flags: list[str] = Field(default_factory=list)
    missing_numbers: list[str] = Field(default_factory=list)
    added_numbers: list[str] = Field(default_factory=list)
    missing_identifiers: list[str] = Field(default_factory=list)
    missing_abbreviations: list[str] = Field(default_factory=list)


class RenditionPage(BaseModel):
    page: int
    source: Literal["native", "ocr", "none"]
    # "pending": not read yet, either still in progress or stopped before it.
    status: Literal["ok", "review", "failed", "pending"]
    reasons: list[str] = Field(default_factory=list)
    text: str | None = None
    char_count: int = 0
    min_confidence: float | None = None
    blocks: list[RenditionBlock] = Field(default_factory=list)
    paragraphs: list[RenditionParagraph] = Field(default_factory=list)


class RenditionSummary(BaseModel):
    id: str
    company_id: str
    matter_id: str
    attachment_id: str
    source_rendition_id: str | None
    kind: RenditionKindLiteral
    version: int
    status: RenditionStatusLiteral
    review_status: RenditionReviewStatusLiteral
    source_language: RenditionLanguage
    target_language: RenditionLanguage | None
    chain_target_language: RenditionLanguage | None
    provider: str | None
    model: str | None
    page_count: int
    pages_ok: int
    pages_review: int
    pages_failed: int
    error_code: str | None
    error_message: str | None
    has_output_file: bool
    output_size_bytes: int | None
    requested_by_name: str | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    review_note: str | None
    retry_allowed: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class RenditionDetail(RenditionSummary):
    attachment_filename: str
    failed_pages: list[int]
    review_pages: list[int]
    pages: list[RenditionPage]


class RenditionMutationResponse(BaseModel):
    created: bool
    rendition: RenditionSummary


class AttachmentRenditionsResponse(BaseModel):
    attachment_id: str
    providers: ProviderReadiness
    renditions: list[RenditionSummary]


class MatterRenditionsResponse(BaseModel):
    matter_id: str
    renditions: list[RenditionSummary]
