"""Pydantic schemas for the Clients module (MOD-TS-009)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ClientTypeLiteral = Literal["individual", "corporate", "government", "nonprofit"]
ClientKycStatusLiteral = Literal["not_started", "pending", "verified", "rejected"]


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    client_type: ClientTypeLiteral = "individual"
    primary_contact_name: str | None = Field(default=None, max_length=255)
    primary_contact_email: EmailStr | None = None
    primary_contact_phone: str | None = Field(default=None, max_length=40)
    # Strict Ledger #4 (BUG-022): full street address. Hari's bug
    # treated "address" as a single concept — we model it as
    # line_1 + line_2 + city + state + postal_code + country so the
    # detail page can render every piece of what the user typed.
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default="India", max_length=120)
    pan: str | None = Field(default=None, max_length=20)
    gstin: str | None = Field(default=None, max_length=20)
    internal_notes: str | None = Field(default=None, max_length=4000)
    kyc_status: ClientKycStatusLiteral = "not_started"


class ClientUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    client_type: ClientTypeLiteral | None = None
    primary_contact_name: str | None = Field(default=None, max_length=255)
    primary_contact_email: EmailStr | None = None
    primary_contact_phone: str | None = Field(default=None, max_length=40)
    address_line_1: str | None = Field(default=None, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=120)
    pan: str | None = Field(default=None, max_length=20)
    gstin: str | None = Field(default=None, max_length=20)
    internal_notes: str | None = Field(default=None, max_length=4000)
    kyc_status: ClientKycStatusLiteral | None = None
    is_active: bool | None = None


class ClientMatterLink(BaseModel):
    """Minimal per-matter summary surfaced on the client profile."""
    matter_id: str
    matter_code: str
    matter_title: str
    role: str | None
    is_primary: bool
    status: str


class ClientRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    name: str
    client_type: ClientTypeLiteral
    primary_contact_name: str | None
    primary_contact_email: str | None
    primary_contact_phone: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    pan: str | None
    gstin: str | None
    internal_notes: str | None
    kyc_status: ClientKycStatusLiteral
    is_active: bool
    active_matters_count: int = 0
    total_matters_count: int = 0
    matters: list[ClientMatterLink] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ClientListResponse(BaseModel):
    clients: list[ClientRecord]
    next_cursor: str | None = None


class MatterClientAssignRequest(BaseModel):
    client_id: str
    role: str | None = Field(default=None, max_length=60)
    is_primary: bool = True


class MatterClientAssignmentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    client_id: str
    role: str | None
    is_primary: bool
    created_at: datetime


__all__ = [
    "ClientCreateRequest",
    "ClientUpdateRequest",
    "ClientMatterLink",
    "ClientRecord",
    "ClientListResponse",
    "MatterClientAssignRequest",
    "MatterClientAssignmentRecord",
    "ClientTypeLiteral",
    "ClientKycStatusLiteral",
]
