from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AITokenQuotaState = Literal["unlimited", "ok", "warning", "hard_limit"]


class AITokenGovernancePolicy(BaseModel):
    company_id: str
    period_start: datetime
    period_end: datetime
    firm_quota_tokens: int | None
    user_quota_tokens: int | None
    warning_threshold_percent: int
    firm_used_tokens: int
    firm_remaining_tokens: int | None
    firm_state: AITokenQuotaState


class AITokenUserUsage(BaseModel):
    actor_membership_id: str
    user_label: str
    used_tokens: int
    run_count: int
    state: AITokenQuotaState
    remaining_tokens: int | None


class AITokenMatterUsage(BaseModel):
    matter_id: str
    matter_code: str
    matter_title: str
    used_tokens: int
    run_count: int


class AITokenPurposeModelUsage(BaseModel):
    purpose: str
    provider: str
    model: str
    used_tokens: int
    run_count: int


class AITokenGovernanceSummary(AITokenGovernancePolicy):
    top_users: list[AITokenUserUsage]
    usage_by_matter: list[AITokenMatterUsage]
    usage_by_purpose_model: list[AITokenPurposeModelUsage]


class AITokenGovernancePatchRequest(BaseModel):
    firm_quota_tokens: int | None = Field(ge=0)
    user_quota_tokens: int | None = Field(ge=0)
    warning_threshold_percent: int = Field(ge=1, le=100)
