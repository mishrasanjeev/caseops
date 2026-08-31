from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AssistantScopeType = Literal[
    "tenant",
    "client",
    "matter",
    "ip_docket",
    "ip_asset",
    "trademark_application",
    "ip_proceeding",
    "matter_document",
    "ip_document",
]


class AssistantScopeInput(BaseModel):
    scope_type: AssistantScopeType
    scope_id: str = Field(min_length=1, max_length=36)

    @field_validator("scope_id")
    @classmethod
    def normalize_scope_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("scope_id cannot be blank")
        return normalized


class AssistantSessionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    scopes: list[AssistantScopeInput] = Field(min_length=1, max_length=24)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title cannot be blank")
        return normalized


class AssistantScopeReplaceRequest(BaseModel):
    expected_version: int = Field(ge=1)
    scopes: list[AssistantScopeInput] = Field(min_length=1, max_length=24)


class AssistantSessionArchiveRequest(BaseModel):
    expected_version: int = Field(ge=1)


class AssistantScopeRecord(BaseModel):
    scope_type: AssistantScopeType
    scope_id: str
    resource_version: str | None
    ordinal: int


class AssistantSessionRecord(BaseModel):
    id: str
    title: str
    status: Literal["active", "archived"]
    version: int
    policy_version: int
    scope_state: Literal["current", "permission_changed"]
    scopes: list[AssistantScopeRecord]
    retention_expires_at: datetime
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssistantSessionSummary(BaseModel):
    id: str
    title: str
    status: Literal["active", "archived"]
    version: int
    retention_expires_at: datetime
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssistantSessionListResponse(BaseModel):
    items: list[AssistantSessionSummary]
    limit: int
    offset: int
    has_more: bool


class AssistantScopeOption(BaseModel):
    scope_type: AssistantScopeType
    scope_id: str
    label: str
    secondary_text: str | None
    href: str
    resource_version: str


class AssistantScopeSearchResponse(BaseModel):
    query: str
    items: list[AssistantScopeOption]
    truncated: bool


class AssistantAskRequest(BaseModel):
    expected_version: int = Field(ge=1)
    question: str = Field(min_length=2, max_length=2000)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("question must contain at least two characters")
        return normalized


class AssistantCitationRecord(BaseModel):
    id: str
    ordinal: int
    source_type: str
    source_id: str
    source_version: str
    source_sha256: str | None
    source_url: str | None
    label: str
    excerpt: str | None
    verified_at: datetime | None


class AssistantCitationOpenResponse(BaseModel):
    citation_id: str
    source_url: str


class AssistantModelMetadata(BaseModel):
    run_id: str
    provider: str
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    status: str


class AssistantProposedAction(BaseModel):
    proposal_id: str
    action_type: Literal["navigation", "search", "draft", "task", "field_update"]
    label: str
    href: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_version: str | None = None
    target_label: str | None = None
    instruction: str | None = None
    requires_confirmation: bool
    execution_available: bool = False
    unavailable_reason: str | None = None


AssistantActionType = Literal["draft", "task", "field_update"]
AssistantMatterField = Literal[
    "title",
    "description",
    "matter_type",
    "client_name",
    "opposing_party",
    "opposing_counsel",
    "practice_area",
    "court_name",
    "judge_name",
]


class AssistantActionInput(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_on: date | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    draft_type: Literal["brief", "notice", "reply", "memo", "other"] = "memo"
    template_key: str | None = Field(default=None, min_length=3, max_length=60)
    field_name: AssistantMatterField | None = None
    field_value: str | None = Field(default=None, max_length=4000)


class AssistantActionPreviewRequest(BaseModel):
    expected_version: int = Field(ge=1)
    turn_id: str = Field(min_length=1, max_length=36)
    proposal_id: str = Field(min_length=1, max_length=64)
    input: AssistantActionInput


class AssistantActionConfirmRequest(BaseModel):
    expected_version: int = Field(ge=1)
    preview_token: str = Field(min_length=64, max_length=64)


class AssistantActionChangeRecord(BaseModel):
    field: str
    before: str | None
    after: str | None


class AssistantActionPreviewResponse(BaseModel):
    preview_id: str
    proposal_id: str
    action_type: AssistantActionType
    status: Literal["pending", "superseded", "confirmed"]
    session_version: int
    resulting_session_version: int | None = None
    target_type: str
    target_id: str
    target_label: str
    summary: str
    changes: list[AssistantActionChangeRecord]
    warnings: list[str]
    required_capabilities: list[str]
    preview_token: str
    expires_at: datetime
    result_type: str | None = None
    result_id: str | None = None
    result_href: str | None = None


class AssistantTurnRecord(BaseModel):
    id: str
    sequence: int
    role: Literal["user", "assistant"]
    status: Literal["queued", "completed", "abstained", "failed", "cancelled"]
    render_status: Literal["visible", "permission_changed"]
    content: str
    citations: list[AssistantCitationRecord]
    model: AssistantModelMetadata | None
    suggested_searches: list[str]
    proposed_actions: list[AssistantProposedAction]
    created_at: datetime


class AssistantAskResponse(BaseModel):
    session: AssistantSessionRecord
    user_turn: AssistantTurnRecord
    assistant_turn: AssistantTurnRecord


class AssistantTurnListResponse(BaseModel):
    items: list[AssistantTurnRecord]
    limit: int
    offset: int
    has_more: bool


class AssistantSessionExportResponse(BaseModel):
    schema_version: int
    exported_at: datetime
    session: AssistantSessionRecord
    turns: list[AssistantTurnRecord]
    retention_disposition: str
