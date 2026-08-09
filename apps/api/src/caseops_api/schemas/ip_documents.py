from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from caseops_api.schemas.document_processing import DocumentProcessingJobRecord


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


IpDocumentTargetType = Literal["docket", "application", "proceeding", "event", "deadline"]
IpDocumentState = Literal[
    "draft",
    "review",
    "approved",
    "filed",
    "served",
    "accepted",
    "rejected",
    "superseded",
]


class IpDocumentLinkTarget(BaseModel):
    target_type: IpDocumentTargetType
    target_id: str = Field(min_length=1, max_length=36)


class IpDocumentUploadMetadata(BaseModel):
    taxonomy_key: str = Field(min_length=2, max_length=80)
    title: str | None = Field(default=None, max_length=255)
    confidentiality: Literal["internal", "confidential", "restricted"] = "internal"
    is_privileged: bool = False
    client_code: str | None = Field(default=None, max_length=80)
    asset_type: str | None = Field(default=None, max_length=80)
    mark: str | None = Field(default=None, max_length=160)
    jurisdiction: str | None = Field(default=None, max_length=80)
    application_no: str | None = Field(default=None, max_length=120)
    proceeding_type: str | None = Field(default=None, max_length=80)
    proceeding_no: str | None = Field(default=None, max_length=120)
    document_date: date | None = None
    links: list[IpDocumentLinkTarget] = Field(default_factory=list, max_length=100)


class IpDocumentNewVersionMetadata(BaseModel):
    expected_current_version: int = Field(ge=1)
    client_code: str | None = Field(default=None, max_length=80)
    asset_type: str | None = Field(default=None, max_length=80)
    mark: str | None = Field(default=None, max_length=160)
    jurisdiction: str | None = Field(default=None, max_length=80)
    application_no: str | None = Field(default=None, max_length=120)
    proceeding_type: str | None = Field(default=None, max_length=80)
    proceeding_no: str | None = Field(default=None, max_length=120)
    document_date: date | None = None


class IpDocumentLinkRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_id: str | None
    target_type: IpDocumentTargetType
    target_id: str
    created_by_membership_id: str
    created_at: datetime


class IpDocumentVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    original_filename: str
    display_name: str
    content_type: str | None
    size_bytes: int
    sha256_hex: str
    processing_status: str
    extracted_char_count: int
    extraction_error: str | None
    ocr_quality_score: float | None
    low_ocr_quality: bool
    ai_eligible: bool
    state: IpDocumentState
    uploaded_by_membership_id: str
    locked_by_membership_id: str | None
    locked_at: datetime | None
    created_at: datetime
    latest_processing_job: DocumentProcessingJobRecord | None = None


class IpDocumentRecord(BaseModel):
    id: str
    taxonomy_key: str
    taxonomy_label: str
    title: str
    confidentiality: Literal["internal", "confidential", "restricted"]
    is_privileged: bool
    current_version: int
    created_by_membership_id: str
    created_at: datetime
    updated_at: datetime
    versions: list[IpDocumentVersionRecord]
    links: list[IpDocumentLinkRecord]


class IpDocumentListResponse(BaseModel):
    items: list[IpDocumentRecord]
    total: int


class IpDocumentDuplicateCandidate(BaseModel):
    document_id: str
    version_id: str
    display_name: str
    sha256_hex: str
    size_bytes: int
    content_type: str | None
    reuse_action: Literal["link_existing_document"] = "link_existing_document"


class IpDocumentUploadResponse(BaseModel):
    outcome: Literal["created", "duplicate_found"]
    document: IpDocumentRecord | None = None
    duplicate_candidates: list[IpDocumentDuplicateCandidate] = Field(default_factory=list)
    processing_job: DocumentProcessingJobRecord | None = None


class IpDocumentAddLinksRequest(BaseModel):
    expected_current_version: int = Field(ge=1)
    version_id: str | None = Field(default=None, max_length=36)
    links: list[IpDocumentLinkTarget] = Field(min_length=1, max_length=100)


class IpDocumentStateTransitionRequest(BaseModel):
    expected_current_version: int = Field(ge=1)
    expected_state: IpDocumentState
    target_state: IpDocumentState


class IpDocumentPolicyResponse(BaseModel):
    ai_retrieval_allowed: bool
    portal_share_allowed: bool
    export_allowed: bool
    notification_content_allowed: bool
    reasons: list[str]


class IpDocumentPolicyActionRequest(BaseModel):
    action: Literal["ai_retrieval", "portal_share", "export", "notification_content"]


class IpDocumentPolicyActionResponse(BaseModel):
    action: Literal["ai_retrieval", "portal_share", "export", "notification_content"]
    allowed: bool
    reasons: list[str]


class IpDocumentBulkItem(BaseModel):
    document_id: str = Field(min_length=1, max_length=36)
    expected_current_version: int = Field(ge=1)
    expected_taxonomy_key: str = Field(min_length=2, max_length=80)
    taxonomy_key: str = Field(min_length=2, max_length=80)
    naming: IpDocumentNamingPreviewRequest


class IpDocumentBulkPreviewItem(BaseModel):
    document_id: str
    taxonomy_key: str
    current_display_name: str
    proposed_display_name: str
    conflict_detected: bool
    warnings: list[str]


class IpDocumentBulkPreviewRequest(BaseModel):
    items: list[IpDocumentBulkItem] = Field(min_length=1, max_length=200)


class IpDocumentBulkPreviewResponse(BaseModel):
    preview_token: str
    items: list[IpDocumentBulkPreviewItem]
    conflict_count: int


class IpDocumentBulkApplyRequest(IpDocumentBulkPreviewRequest):
    preview_token: str = Field(min_length=64, max_length=64)


class IpDocumentAliasImportEntry(BaseModel):
    taxonomy_key: str = Field(min_length=2, max_length=80)
    aliases: list[str] = Field(min_length=1, max_length=500)

    @field_validator("aliases")
    @classmethod
    def validate_import_aliases(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("aliases cannot contain blank values")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("aliases cannot contain duplicates")
        return cleaned


class IpDocumentAliasImportRequest(BaseModel):
    dry_run: bool = True
    entries: list[IpDocumentAliasImportEntry] = Field(min_length=1, max_length=100)


class IpDocumentAliasImportConflict(BaseModel):
    alias: str
    normalized_alias: str
    existing_taxonomy_key: str
    requested_taxonomy_key: str


class IpDocumentAliasImportResponse(BaseModel):
    dry_run: bool
    imported_count: int
    unchanged_count: int
    conflicts: list[IpDocumentAliasImportConflict]
