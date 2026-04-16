from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    company_type: str
    tenant_key: str
    is_active: bool
    created_at: datetime


class MembershipSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    is_active: bool
    created_at: datetime


class AuthSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    company: CompanySummary
    user: UserSummary
    membership: MembershipSummary


class AuthContextResponse(BaseModel):
    company: CompanySummary
    user: UserSummary
    membership: MembershipSummary


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_slug: str | None = Field(default=None, min_length=2, max_length=80)
