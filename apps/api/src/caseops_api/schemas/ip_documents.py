from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IpDocumentTaxonomyAliasRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alias: str
    normalized_alias: str
    source: str
    created_at: datetime


class IpDocumentTaxonomyEntryRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    label: str
    description: str | None
    sort_order: int
    is_seeded: bool
    is_active: bool
    version: int
    aliases: list[IpDocumentTaxonomyAliasRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class IpDocumentTaxonomyResponse(BaseModel):
    taxonomy_version: str
    entries: list[IpDocumentTaxonomyEntryRecord]


class IpDocumentTaxonomyUpsertRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    label: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=10000)
    is_active: bool = True
    aliases: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 2:
            raise ValueError("label cannot be blank")
        return stripped

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        stripped = [value.strip() for value in values]
        if any(not value for value in stripped):
            raise ValueError("aliases cannot contain blank values")
        folded = [value.casefold() for value in stripped]
        if len(folded) != len(set(folded)):
            raise ValueError("aliases cannot contain duplicates")
        return stripped


class IpDocumentNamingPreviewRequest(BaseModel):
    client_code: str | None = Field(default=None, max_length=80)
    asset_type: str | None = Field(default=None, max_length=80)
    mark: str | None = Field(default=None, max_length=160)
    jurisdiction: str | None = Field(default=None, max_length=80)
    application_no: str | None = Field(default=None, max_length=120)
    proceeding_type: str | None = Field(default=None, max_length=80)
    proceeding_no: str | None = Field(default=None, max_length=120)
    document_type: str | None = Field(default=None, max_length=160)
    document_date: date | None = None
    version: int = Field(ge=1)
    extension: str | None = Field(default=None, max_length=20)
    existing_names: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("existing_names")
    @classmethod
    def validate_existing_names(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("existing_names cannot contain blank values")
        return values


class IpDocumentNamingPreviewResponse(BaseModel):
    pattern: str
    requested_name: str
    resolved_name: str
    conflict_detected: bool
    conflict_suffix: int | None
    sanitized_components: list[str]
    omitted_components: list[str]
    warnings: list[str]
    export_safe_name: str


class IpDocumentFoundationContract(BaseModel):
    identity_owner: Literal["ip_documents"] = "ip_documents"
    version_owner: Literal["ip_document_versions"] = "ip_document_versions"
    link_owner: Literal["ip_document_links"] = "ip_document_links"
    binary_storage_owner: Literal["shared_document_storage"] = "shared_document_storage"
    processing_queue_owner: Literal["document_processing_jobs"] = "document_processing_jobs"
    processing_target_type: Literal["ip_document_version"] = "ip_document_version"
    taxonomy_version: str
    naming_pattern: str
    supported_link_targets: list[str]
