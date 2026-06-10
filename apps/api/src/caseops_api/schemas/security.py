from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MFAMethodLiteral = Literal["totp", "recovery_code"]


class MFASecurityStatusResponse(BaseModel):
    mfa_status: Literal["not_enrolled", "pending", "enrolled", "disabled"]
    mfa_required: bool
    mfa_enforced_at: datetime | None = None
    grace_period_ends_at: datetime | None = None
    recent_step_up_expires_at: datetime | None = None
    recovery_codes_remaining: int
    platform_admin_required: bool = False
    tenant_admin_required: bool = False
    all_users_required: bool = False


class MFAEnrollmentStartResponse(BaseModel):
    enrollment_id: str
    secret: str
    otpauth_url: str
    qr_svg: str
    status: Literal["pending"]


class MFAVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MFAEnrollmentVerifyResponse(BaseModel):
    status: Literal["enrolled"]
    recovery_codes: list[str]


class MFAStepUpRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)
    purpose: str = Field(default="step_up", min_length=3, max_length=80)
    method: MFAMethodLiteral = "totp"


class MFAStepUpResponse(BaseModel):
    status: Literal["verified"]
    expires_at: datetime


class MFARecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
    generated_at: datetime


class MFADisableRequest(BaseModel):
    code: str | None = Field(default=None, min_length=6, max_length=32)
    reason: str = Field(min_length=3, max_length=1000)


class MFADisableResponse(BaseModel):
    status: Literal["disabled"]


class TenantSecurityPolicyRecord(BaseModel):
    tenant_admin_mfa_required: bool
    all_users_mfa_required: bool
    mfa_grace_period_days: int
    mfa_enforced_at: datetime | None = None
    updated_at: datetime


class TenantSecurityPolicyUpdateRequest(BaseModel):
    tenant_admin_mfa_required: bool | None = None
    all_users_mfa_required: bool | None = None
    mfa_grace_period_days: int | None = Field(default=None, ge=0, le=90)
    reason: str = Field(min_length=3, max_length=1000)
