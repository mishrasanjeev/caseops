"""Pydantic schemas for the Clients module (MOD-TS-009)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ClientTypeLiteral = Literal["individual", "corporate", "government", "nonprofit"]
ClientVerificationStatusLiteral = Literal[
    "not_required",
    "required",
    "requested",
    "submitted",
    "under_review",
    "verified",
    "rejected",
    "expired",
]
ClientKycStatusLiteral = ClientVerificationStatusLiteral
ClientKycStatusInputLiteral = ClientVerificationStatusLiteral
KycDocumentStatusLiteral = Literal[
    "required",
    "requested",
    "submitted",
    "received",
    "verified",
    "rejected",
    "expired",
    "pending",
]


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
    kyc_status: ClientKycStatusInputLiteral = "not_required"


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
    kyc_status: ClientKycStatusInputLiteral | None = None
    is_active: bool | None = None


class ClientMatterLink(BaseModel):
    """Minimal per-matter summary surfaced on the client profile."""
    matter_id: str
    matter_code: str
    matter_title: str
    role: str | None
    is_primary: bool
    status: str


class KycDocumentRecord(BaseModel):
    """One tracked verification document.

    Stored as JSON on the client. ``attachment_id`` is an optional
    reference to an existing matter attachment; services validate it
    against the matter before accepting it. Payloads, storage keys,
    hashes, and OCR/document text are intentionally not surfaced here.
    """

    name: str = Field(min_length=1, max_length=120)
    document_type: str | None = Field(default=None, max_length=80)
    status: KycDocumentStatusLiteral = "required"
    note: str | None = Field(default=None, max_length=400)
    attachment_id: str | None = Field(default=None, min_length=10, max_length=64)
    expires_on: date | None = None


class KycSubmitRequest(BaseModel):
    """Submit a KYC pack - moves the client into ``submitted``."""

    documents: list[KycDocumentRecord] = Field(default_factory=list)


class KycRejectRequest(BaseModel):
    reason: str = Field(min_length=4, max_length=1000)


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
    # Phase B M11 slice 3 — KYC audit trail surface.
    kyc_submitted_at: datetime | None = None
    kyc_verified_at: datetime | None = None
    kyc_verified_by_membership_id: str | None = None
    kyc_rejection_reason: str | None = None
    kyc_documents: list[KycDocumentRecord] = Field(default_factory=list)
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


class ClientVerificationUpdateRequest(BaseModel):
    status: ClientKycStatusInputLiteral | None = None
    documents: list[KycDocumentRecord] | None = Field(default=None, max_length=20)
    rejection_reason: str | None = Field(default=None, max_length=1000)


class MatterClientVerificationRecord(BaseModel):
    client_id: str
    client_name: str
    client_type: ClientTypeLiteral
    role: str | None = None
    is_primary: bool = False
    status: ClientVerificationStatusLiteral
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewer_membership_id: str | None = None
    rejection_reason: str | None = None
    documents: list[KycDocumentRecord] = Field(default_factory=list)


class MatterClientVerificationListResponse(BaseModel):
    matter_id: str
    clients: list[MatterClientVerificationRecord] = Field(default_factory=list)


__all__ = [
    "ClientCreateRequest",
    "ClientKycStatusLiteral",
    "ClientKycStatusInputLiteral",
    "ClientListResponse",
    "ClientMatterLink",
    "ClientRecord",
    "ClientTypeLiteral",
    "ClientVerificationStatusLiteral",
    "ClientVerificationUpdateRequest",
    "ClientUpdateRequest",
    "KycDocumentRecord",
    "KycRejectRequest",
    "KycSubmitRequest",
    "MatterClientAssignRequest",
    "MatterClientAssignmentRecord",
    "MatterClientVerificationListResponse",
    "MatterClientVerificationRecord",
]
