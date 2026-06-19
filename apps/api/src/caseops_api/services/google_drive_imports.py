from __future__ import annotations

import re
from pathlib import PurePosixPath

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditResult
from caseops_api.schemas.google_drive_imports import (
    GoogleDriveFileMetadata,
    GoogleDriveImportDryRunRequest,
    GoogleDriveImportDryRunResponse,
    GoogleDriveImportDryRunSummary,
    GoogleDriveImportFilePlan,
    GoogleDriveProviderConfigStatus,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.google_workspace import google_workspace_oauth_config
from caseops_api.services.matter_access import _load_matter_or_404, assert_access
from caseops_api.services.session_context import SessionContext

GOOGLE_DRIVE_IMPORT_MAX_FILES = 200
GOOGLE_DRIVE_IMPORT_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/rtf",
        "text/plain",
        "text/csv",
        "text/markdown",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }
)

_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "pleadings",
        (
            "pleading",
            "petition",
            "plaint",
            "rejoinder",
            "reply",
            "writ",
            "complaint",
        ),
    ),
    (
        "orders",
        ("order", "judgment", "judgement", "decree", "ruling", "award"),
    ),
    (
        "evidence",
        (
            "evidence",
            "exhibit",
            "annexure",
            "annexture",
            "deposition",
            "affidavit",
        ),
    ),
    (
        "notices",
        ("notice", "summons", "subpoena"),
    ),
    (
        "contracts",
        (
            "contract",
            "agreement",
            "mou",
            "nda",
            "deed",
            "lease",
        ),
    ),
    (
        "correspondence",
        ("email", "letter", "memo", "correspondence"),
    ),
)


def _safe_drive_filename(value: str) -> str | None:
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or len(cleaned) > 500:
        return None
    if any(ord(char) < 32 for char in cleaned):
        return None
    path = PurePosixPath(cleaned)
    if path.is_absolute() or ".." in path.parts:
        return None
    if cleaned.endswith("/"):
        return None
    return cleaned


def _categorize(filename: str, mime_type: str) -> str | None:
    haystack = re.sub(r"[^a-z0-9]+", " ", filename.lower())
    tokens = set(haystack.split())
    for category, keywords in _CATEGORY_KEYWORDS:
        for keyword in keywords:
            if keyword in tokens:
                return category
    lowered_mime = mime_type.lower()
    if lowered_mime in {"application/pdf"}:
        return "other"
    if lowered_mime.startswith("image/"):
        return "evidence"
    if lowered_mime in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/rtf",
        "text/plain",
        "text/markdown",
    }:
        return "other"
    return None


def _missing_google_drive_config_names(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> list[str]:
    workspace_config = google_workspace_oauth_config(
        session,
        context=context,
        connector="drive",
    )
    if workspace_config.source in {"tenant_admin", "missing"}:
        return list(workspace_config.missing_config_names)
    settings = get_settings()
    missing: list[str] = []
    if not settings.google_drive_client_id:
        missing.append("GOOGLE_DRIVE_CLIENT_ID")
    if not settings.google_drive_client_secret:
        missing.append("GOOGLE_DRIVE_CLIENT_SECRET")
    if not settings.google_drive_redirect_uri:
        missing.append("GOOGLE_DRIVE_REDIRECT_URI")
    return missing


def google_drive_provider_config_status(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GoogleDriveProviderConfigStatus:
    missing = _missing_google_drive_config_names(session, context=context)
    return GoogleDriveProviderConfigStatus(
        configured=not missing,
        missing_config_names=missing,
    )


def _plan_file(
    file: GoogleDriveFileMetadata,
    *,
    seen_ids: dict[str, int],
) -> GoogleDriveImportFilePlan:
    provider_file_id = file.provider_file_id.strip()
    errors: list[str] = []
    safe_name = _safe_drive_filename(file.name)
    if safe_name is None:
        errors.append("Drive filename is unsafe or path-traversal-shaped.")

    seen_count = seen_ids.get(provider_file_id, 0)
    if seen_count >= 1:
        return GoogleDriveImportFilePlan(
            provider_file_id=provider_file_id,
            name=file.name[:120],
            safe_name=safe_name,
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            modified_time=file.modified_time,
            category=None,
            status="skipped_duplicate",
            errors=["Duplicate Drive provider_file_id within this import payload."],
        )

    mime_type = file.mime_type.strip()
    mime_supported = mime_type.lower() in _SUPPORTED_MIME_TYPES
    if file.size_bytes > GOOGLE_DRIVE_IMPORT_MAX_FILE_SIZE_BYTES:
        errors.append(
            "Drive file exceeds the "
            f"{GOOGLE_DRIVE_IMPORT_MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB "
            "manual-import dry-run limit."
        )
    if file.size_bytes == 0:
        errors.append("Drive file is empty; refusing to plan import.")

    if not mime_supported:
        return GoogleDriveImportFilePlan(
            provider_file_id=provider_file_id,
            name=file.name[:200],
            safe_name=safe_name,
            mime_type=mime_type,
            size_bytes=file.size_bytes,
            modified_time=file.modified_time,
            category=None,
            status="unsupported_mime",
            errors=errors + ["Drive MIME type is not supported by manual import."],
        )

    category = _categorize(file.name, mime_type) if safe_name is not None else None
    status = "invalid" if errors else "valid"
    return GoogleDriveImportFilePlan(
        provider_file_id=provider_file_id,
        name=file.name[:200],
        safe_name=safe_name,
        mime_type=mime_type,
        size_bytes=file.size_bytes,
        modified_time=file.modified_time,
        category=category,
        status=status,
        errors=errors,
    )


def dry_run_google_drive_import(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: GoogleDriveImportDryRunRequest,
) -> GoogleDriveImportDryRunResponse:
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    assert_access(session, context=context, matter=matter)

    if len(payload.files) > GOOGLE_DRIVE_IMPORT_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google Drive manual import dry-run supports at most "
                f"{GOOGLE_DRIVE_IMPORT_MAX_FILES} files per request."
            ),
        )

    seen_ids: dict[str, int] = {}
    plans: list[GoogleDriveImportFilePlan] = []
    for file in payload.files:
        plan = _plan_file(file, seen_ids=seen_ids)
        seen_ids[file.provider_file_id.strip()] = (
            seen_ids.get(file.provider_file_id.strip(), 0) + 1
        )
        plans.append(plan)

    valid_files = sum(1 for plan in plans if plan.status == "valid")
    invalid_files = sum(1 for plan in plans if plan.status == "invalid")
    duplicate_files = sum(1 for plan in plans if plan.status == "skipped_duplicate")
    unsupported_mime_files = sum(
        1 for plan in plans if plan.status == "unsupported_mime"
    )

    summary = GoogleDriveImportDryRunSummary(
        total_files=len(plans),
        valid_files=valid_files,
        invalid_files=invalid_files,
        duplicate_files=duplicate_files,
        unsupported_mime_files=unsupported_mime_files,
    )

    record_from_context(
        session,
        context,
        action="matter.google_drive_import.dry_run",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        result=AuditResult.SUCCESS,
        metadata={
            "provider": "google_drive",
            "dry_run": True,
            "folder_id_present": bool(payload.folder_id),
            "folder_name_present": bool(payload.folder_name),
            "total_files": summary.total_files,
            "valid_files": summary.valid_files,
            "invalid_files": summary.invalid_files,
            "duplicate_files": summary.duplicate_files,
            "unsupported_mime_files": summary.unsupported_mime_files,
            "will_create_attachment_count": 0,
            "storage_writes": 0,
            "corpus_jobs_queued": 0,
        },
    )
    session.commit()

    return GoogleDriveImportDryRunResponse(
        company_id=context.company.id,
        matter_id=matter.id,
        folder_id=payload.folder_id,
        folder_name=payload.folder_name,
        summary=summary,
        files=plans,
        limitations=[
            "Dry-run only: no attachments, storage objects, OCR jobs, corpus " +
            "jobs, or embeddings are created.",
            "No external Google Drive API call is made; the planner validates " +
            "user-supplied Drive metadata only.",
            "Durable Drive sync, webhook ingestion, OAuth token storage, and " +
            "commit execution are deferred to ADP-21 / future milestones.",
            "Cross-import provider_file_id idempotency requires persisted " +
            "attachments and is not enforced in this foundation.",
        ],
    )


__all__ = [
    "GOOGLE_DRIVE_IMPORT_MAX_FILES",
    "GOOGLE_DRIVE_IMPORT_MAX_FILE_SIZE_BYTES",
    "dry_run_google_drive_import",
    "google_drive_provider_config_status",
]
