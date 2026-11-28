"""ENH-001: firm branding for billing PDFs and public document verification."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BrandingImageKind = Literal["logo", "signature"]


def _clean_optional_text(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    cleaned = " ".join(value.split())
    if any(unicodedata.category(char) == "Cc" for char in cleaned):
        raise ValueError("Control characters are not allowed.")
    return cleaned or None


class DocumentLetterheadPreview(BaseModel):
    """What the letterhead prints today, read from the default billing profile."""

    issuer_name: str
    detail_lines: list[str]
    source: Literal["billing_profile", "workspace"]


class DocumentBrandingRecord(BaseModel):
    signatory_name: str | None
    signatory_designation: str | None
    watermark_enabled: bool
    watermark_text: str | None
    effective_watermark_text: str | None
    has_logo: bool
    logo_width: int | None
    logo_height: int | None
    logo_sha256: str | None
    has_signature: bool
    signature_width: int | None
    signature_height: int | None
    signature_sha256: str | None
    updated_at: datetime | None
    letterhead: DocumentLetterheadPreview


class DocumentBrandingUpdateRequest(BaseModel):
    """Only the fields sent are changed (PATCH)."""

    model_config = ConfigDict(extra="forbid")

    signatory_name: str | None = Field(default=None, max_length=160)
    signatory_designation: str | None = Field(default=None, max_length=160)
    watermark_enabled: bool | None = None
    watermark_text: str | None = Field(default=None, max_length=60)

    @field_validator(
        "signatory_name", "signatory_designation", "watermark_text", mode="before"
    )
    @classmethod
    def _clean(cls, value: object) -> object:
        return _clean_optional_text(value)

    @field_validator("signatory_name", "signatory_designation", "watermark_text")
    @classmethod
    def _printable(cls, value: str | None) -> str | None:
        # These print on every billing PDF; a character the fonts lack would
        # make every later download fail, so it is refused here instead.
        from caseops_api.services.pdf_fonts import UNPRINTABLE_TEXT_MESSAGE, pdf_text_supported

        if value is not None and not pdf_text_supported(value):
            raise ValueError(UNPRINTABLE_TEXT_MESSAGE)
        return value


VerificationState = Literal["valid", "not_issued", "revoked"]


class BillingDocumentVerificationResponse(BaseModel):
    """Public, minimal facts about one generated billing PDF.

    Deliberately omits the client, the matter, line items and any tenant
    identifier: a verifier learns only whether the copy in hand is genuine.
    """

    # valid: an issued document. not_issued: a draft or review copy; the
    # fingerprint still identifies the file, but it is not an issued document.
    # revoked: void, or no longer held by the issuer.
    state: VerificationState
    document_type: str
    document_number: str
    issued_on: date
    issuer_name: str
    # The issuer name was typed by the outside counsel who submitted the
    # invoice; the firm did not check it.
    issuer_supplied_by_counsel: bool
    amount_minor: int
    currency: str
    status_at_generation: str
    current_status: str
    generated_at: datetime
    pdf_sha256: str | None
    revoked_at: datetime | None
    revoked_reason: str | None
