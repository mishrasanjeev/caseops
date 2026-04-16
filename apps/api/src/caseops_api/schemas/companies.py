from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

CompanyTypeLiteral = Literal["law_firm", "corporate_legal"]
MembershipRoleLiteral = Literal["owner", "admin", "member"]


class BootstrapCompanyRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=255)
    company_slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    company_type: CompanyTypeLiteral
    owner_full_name: str = Field(min_length=2, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(min_length=12, max_length=128)


class CompanyUserCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "member"] = "member"


class CompanyUserUpdateRequest(BaseModel):
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None


class CompanyUserRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: str
    role: MembershipRoleLiteral
    membership_active: bool
    user_id: str
    email: EmailStr
    full_name: str
    user_active: bool
    created_at: datetime


class CompanyUsersResponse(BaseModel):
    company_id: str
    company_slug: str
    users: list[CompanyUserRecord]


class CompanyProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    company_type: CompanyTypeLiteral
    tenant_key: str
    primary_contact_email: EmailStr | None
    billing_contact_name: str | None
    billing_contact_email: EmailStr | None
    headquarters: str | None
    timezone: str
    website_url: HttpUrl | None
    practice_summary: str | None
    is_active: bool
    created_at: datetime


class CompanyProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    primary_contact_email: EmailStr | None = None
    billing_contact_name: str | None = Field(default=None, min_length=2, max_length=255)
    billing_contact_email: EmailStr | None = None
    headquarters: str | None = Field(default=None, min_length=2, max_length=255)
    timezone: str | None = Field(default=None, min_length=2, max_length=64)
    website_url: HttpUrl | None = None
    practice_summary: str | None = Field(default=None, max_length=4000)
