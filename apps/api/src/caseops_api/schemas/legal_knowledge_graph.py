from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LegalKnowledgeGraphRunStatusLiteral = Literal["completed", "no_source_records"]
LegalKnowledgeGraphNodeTypeLiteral = Literal[
    "matter",
    "proceeding_signal",
    "affidavit_statement",
    "affidavit_question",
    "mock_hearing_question",
    "mock_hearing_response",
    "predictive_signal",
    "bench_context",
    "legal_source",
    "statute_or_issue",
    "review_action",
]
LegalKnowledgeGraphEdgeTypeLiteral = Literal[
    "supports",
    "contradicts",
    "references",
    "derived_from",
    "prompts",
    "relates_to",
    "has_limitation",
]
LegalKnowledgeGraphSourceTypeLiteral = Literal[
    "matter",
    "matter_court_order",
    "matter_proceeding_signal",
    "matter_document",
    "matter_attachment_chunk",
    "affidavit_statement",
    "affidavit_question",
    "mock_hearing_session",
    "mock_hearing_question",
    "mock_hearing_response",
    "predictive_signal_item",
    "predictive_signal_run",
    "authority_document",
    "aggregate_snapshot",
    "litigation_intelligence_review_action",
    "unavailable",
]


class LegalKnowledgeGraphNodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    node_key: str
    node_type: LegalKnowledgeGraphNodeTypeLiteral
    label: str
    description: str | None = None
    source_type: LegalKnowledgeGraphSourceTypeLiteral
    source_id: str
    source_quote: str | None = None
    confidence_label: str | None = None
    review_status: str | None = None
    limitation_note: str
    created_at: datetime


class LegalKnowledgeGraphEdgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    edge_type: LegalKnowledgeGraphEdgeTypeLiteral
    label: str
    from_node_id: str
    to_node_id: str
    source_type: LegalKnowledgeGraphSourceTypeLiteral
    source_id: str
    source_quote: str | None = None
    confidence_label: str | None = None
    limitation_note: str
    created_at: datetime


class LegalKnowledgeGraphSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LegalKnowledgeGraphRunStatusLiteral | Literal["not_materialized"]
    source_record_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    by_node_type: dict[str, int] = Field(default_factory=dict)
    by_edge_type: dict[str, int] = Field(default_factory=dict)
    missing_data: list[str] = Field(default_factory=list)


class LegalKnowledgeGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter_id: str
    generated_at: datetime
    run_id: str | None = None
    disclaimer: str
    limitation_note: str
    summary: LegalKnowledgeGraphSummary
    nodes: list[LegalKnowledgeGraphNodeRecord] = Field(default_factory=list)
    edges: list[LegalKnowledgeGraphEdgeRecord] = Field(default_factory=list)
