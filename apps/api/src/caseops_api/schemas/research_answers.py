"""Typed contracts for source-verified three-part research answers (J05/M04)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from caseops_api.schemas.source_actions import SourceActionRecord

ResearchAnswerStatus = Literal["queued", "running", "answered", "abstained", "failed"]
ResearchSectionKey = Literal[
    "issues",
    "applicable_law",
    "ingredients",
    "time_limits",
    "procedure",
    "jurisdiction",
    "evidence",
    "defences",
    "application",
]
ResearchSourceKind = Literal["statute_section", "judgment"]


class ResearchAnswerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
    # When research starts from a matter, only that matter's recorded facts are
    # added, labelled separately from legal authority.
    context_matter_id: str | None = Field(default=None, max_length=36)


class ResearchAnswerSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter_id: str = Field(min_length=1, max_length=36)


class ResearchCitedText(BaseModel):
    """Answer text with inline ``[n]`` markers that resolve to ``sources``."""

    text: str
    citations: list[int] = Field(default_factory=list)
    # True when the text states law but carries no verified source marker.
    unsupported: bool = False


class ResearchTimelineRow(BaseModel):
    period: str
    starts: str
    detail: ResearchCitedText


class ResearchSection(BaseModel):
    key: ResearchSectionKey
    title: str
    paragraphs: list[ResearchCitedText] = Field(default_factory=list)
    steps: list[ResearchCitedText] = Field(default_factory=list)
    timeline: list[ResearchTimelineRow] = Field(default_factory=list)


class ResearchAuthorityEntry(BaseModel):
    source: int
    disposition: Literal["supporting", "contrary", "context"]
    proposition: str | None = None
    relevance: str | None = None
    # A verbatim passage from the source text, present only when verified.
    passage: str | None = None
    passage_verified: bool = False
    # Paragraph number located in the source text immediately before the
    # verified passage. Never model-supplied.
    paragraph: str | None = None
    cited_inline: bool = False


class ResearchMatterFact(BaseModel):
    label: str
    value: str


class ResearchVerification(BaseModel):
    removed_citation_markers: int = 0
    unverified_passages: int = 0
    uncited_paragraphs: int = 0
    removed_unverified_mentions: int = 0
    # Retrieved judgments left out of the authorities because the answer
    # neither cited them inline nor quoted a passage found in their text.
    unlinked_authorities: int = 0
    notes: list[str] = Field(default_factory=list)


class ResearchAnswerBody(BaseModel):
    short_answer: ResearchCitedText
    key_points: list[ResearchCitedText] = Field(default_factory=list)
    facts_insufficient: bool = False
    missing_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sections: list[ResearchSection] = Field(default_factory=list)
    authorities: list[ResearchAuthorityEntry] = Field(default_factory=list)
    matter_facts: list[ResearchMatterFact] = Field(default_factory=list)
    # The provisions CaseOps identified as the subject of the question, e.g.
    # "Section 138, Negotiable Instruments Act, 1881". Shown so a lawyer can
    # see what was researched before reading the answer.
    question_focus: list[str] = Field(default_factory=list)
    # Material topics (ingredients, time limits, procedure, jurisdiction) the
    # retrieved sources did not support, so the answer does not cover them.
    coverage_gaps: list[str] = Field(default_factory=list)
    verification: ResearchVerification = Field(default_factory=ResearchVerification)
    law_checked_as_of: date
    sources_retrieved_from: datetime | None = None
    sources_retrieved_to: datetime | None = None
    disclaimer: str


class ResearchTreatmentSignal(BaseModel):
    worst_treatment: str | None = None
    adverse_count: int = 0


class ResearchSource(BaseModel):
    number: int
    kind: ResearchSourceKind
    id: str
    title: str
    citation: str | None = None
    court: str | None = None
    bench: str | None = None
    decision_date: date | None = None
    # Deterministic, from the forum level: never model-supplied.
    weight: str
    source_action: SourceActionRecord | None = None
    in_app_href: str | None = None
    # For a judgment, against the question's focus provision: "cites" (its
    # recorded citations include it), "names" (its retrieved text names it) or
    # "context_only" (it does neither; kept only because nothing else did).
    focus_engagement: Literal["cites", "names", "context_only"] | None = None
    treatment_signal: ResearchTreatmentSignal | None = None
    retrieved_at: datetime | None = None


class ResearchMatterRef(BaseModel):
    id: str
    title: str


class ResearchAnswerRecord(BaseModel):
    id: str
    status: ResearchAnswerStatus
    query: str
    error_code: str | None = None
    message: str | None = None
    analysis_version: str
    created_at: datetime
    completed_at: datetime | None = None
    context_matter: ResearchMatterRef | None = None
    saved_matter: ResearchMatterRef | None = None
    saved_at: datetime | None = None
    answer: ResearchAnswerBody | None = None
    sources: list[ResearchSource] = Field(default_factory=list)
    # For an abstained answer: rephrased questions the user can run instead,
    # built from the question and the matter record. Never model-generated.
    suggestions: list[str] = Field(default_factory=list)


class ResearchAnswerSummary(BaseModel):
    id: str
    status: ResearchAnswerStatus
    query: str
    created_at: datetime
    saved_at: datetime | None = None


class ResearchAnswerListResponse(BaseModel):
    items: list[ResearchAnswerSummary]
