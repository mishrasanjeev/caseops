from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

ForumAliasType = Literal[
    "court_complex",
    "abbreviation",
    "legacy_name",
    "local_name",
    "spelling_variant",
    "provider_label",
    "other",
]
ForumAliasVerificationStatus = Literal["pending", "verified", "rejected"]


class ForumCatalogAliasCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forum_catalog_entry_id: str = Field(min_length=1, max_length=120)
    alias: str = Field(min_length=1, max_length=255)
    alias_type: ForumAliasType
    source_name: str = Field(min_length=3, max_length=160)
    source_url: AnyHttpUrl | None = Field(default=None, max_length=500)
    verification_status: ForumAliasVerificationStatus = "pending"
    is_active: bool = True
    reason: str = Field(min_length=5, max_length=500)

    @field_validator(
        "forum_catalog_entry_id",
        "alias",
        "source_name",
        "reason",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ForumCatalogAliasUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None = Field(default=None, min_length=1, max_length=255)
    alias_type: ForumAliasType | None = None
    source_name: str | None = Field(default=None, min_length=3, max_length=160)
    source_url: AnyHttpUrl | None = Field(default=None, max_length=500)
    verification_status: ForumAliasVerificationStatus | None = None
    is_active: bool | None = None
    expected_record_version: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("alias", "source_name", "reason", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_non_null_update(self) -> ForumCatalogAliasUpdateRequest:
        mutable_fields = {
            "alias",
            "alias_type",
            "source_name",
            "source_url",
            "verification_status",
            "is_active",
        }
        supplied = self.model_fields_set & mutable_fields
        if not supplied:
            raise ValueError("At least one alias field must be supplied for update.")
        non_nullable = supplied - {"source_url"}
        if any(getattr(self, field) is None for field in non_nullable):
            raise ValueError("Alias update fields other than source_url cannot be null.")
        return self


class ForumCatalogAliasRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    forum_catalog_entry_id: str
    canonical_name: str
    forum_type: str
    forum_level: str
    state: str | None
    district: str | None
    city: str | None
    lineage: str
    alias: str
    normalized_alias: str
    alias_type: ForumAliasType
    source_name: str
    source_url: str | None
    verification_status: ForumAliasVerificationStatus
    is_active: bool
    reviewed_at: datetime | None
    record_version: int
    created_by_platform_admin_id: str | None
    reviewed_by_platform_admin_id: str | None
    updated_by_platform_admin_id: str | None
    created_at: datetime
    updated_at: datetime


class ForumCatalogAliasListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: list[ForumCatalogAliasRecord]
    returned_count: int
    limit: int
    has_more: bool
