"""Registry-format work-product bundle for trademark pleadings."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Buffer
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.settings import get_settings
from caseops_api.db.models import DraftStatus
from caseops_api.services.drafting import (
    get_ip_draft,
    load_draft_record,
    render_ip_version_docx,
    validate_ip_draft,
)
from caseops_api.services.session_context import SessionContext

IP_FILING_BUNDLE_TOO_LARGE_PROBLEM = "ip_filing_bundle_too_large"


@dataclass(frozen=True)
class IpDraftBundle:
    body: bytes
    filename: str


class _BundleSizeExceeded(Exception):
    pass


class _CappedZipBuffer(io.BytesIO):
    """In-memory zip target that refuses any write past ``max_bytes``, so an
    oversized bundle stops while it is being built, not after."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes

    def write(self, data: Buffer, /) -> int:
        if self.tell() + memoryview(data).nbytes > self._max_bytes:
            raise _BundleSizeExceeded
        return super().write(data)


def render_ip_draft_bundle(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    proceeding_id: str,
    draft_id: str,
) -> IpDraftBundle:
    draft = get_ip_draft(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        draft_id=draft_id,
    )
    if draft.status not in {
        DraftStatus.FINALIZED,
        DraftStatus.FILED,
        DraftStatus.FILING_REJECTED,
        DraftStatus.SERVED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Finalize the approved revision before creating a filing bundle.",
        )
    validation = validate_ip_draft(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        draft_id=draft_id,
    )
    if validation.blocker_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The filing bundle is blocked by pleading validation.",
                "validation": validation.as_dict(),
            },
        )
    docx, docx_filename = render_ip_version_docx(
        session,
        context=context,
        docket_id=docket_id,
        proceeding_id=proceeding_id,
        draft_id=draft_id,
    )
    record = load_draft_record(draft)
    current = next(
        row for row in record["versions"] if row["id"] == record["current_version_id"]
    )
    internal_manifest = {
        "schema": "caseops.ip-filing-bundle.v1",
        "draft_id": draft.id,
        "version_id": current["id"],
        "revision": current["revision"],
        "status": draft.status,
        "template_manifest": current["template_manifest"],
        "context_manifest": current["context_manifest"],
        "source_manifest": current["source_manifest"],
        "validation": validation.as_dict(),
        "lifecycle_events": record["reviews"],
    }
    checklist = {
        "schema": "caseops.ip-filing-checklist.v1",
        "items": [
            {"key": "approved_revision", "passed": True},
            {"key": "no_unresolved_placeholders", "passed": validation.placeholder_count == 0},
            {"key": "current_sources_verified", "passed": validation.blocker_count == 0},
            {
                "key": "registry_format_selected",
                "passed": bool(current["template_manifest"].get("format_profile")),
            },
            {"key": "filing_and_service_are_human_events", "passed": True},
        ],
    }
    # A bundle is one file, so it gets the same ceiling as any file CaseOps
    # accepts (max_attachment_size_bytes, 25 MiB by default).
    max_bytes = get_settings().max_attachment_size_bytes
    buffer = _CappedZipBuffer(max_bytes)
    try:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"filed-document/{docx_filename}", docx)
            archive.writestr(
                "internal/generation-manifest.json",
                json.dumps(internal_manifest, indent=2, default=str, sort_keys=True),
            )
            archive.writestr(
                "internal/filing-checklist.json",
                json.dumps(checklist, indent=2, sort_keys=True),
            )
    except _BundleSizeExceeded:
        raise ProblemHTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            problem_type=IP_FILING_BUNDLE_TOO_LARGE_PROBLEM,
            detail=(
                f"This filing bundle would be larger than {max_bytes / (1024 * 1024):g} MiB, "
                "the limit for a single file, so it was not created. Download the "
                "DOCX instead, or shorten the pleading and finalize a new revision."
            ),
            extras={"max_bundle_bytes": max_bytes},
        ) from None
    safe_title = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in draft.title
    ).strip("-")[:60] or "trademark-pleading"
    return IpDraftBundle(body=buffer.getvalue(), filename=f"{safe_title}-filing-bundle.zip")


__all__ = ["IpDraftBundle", "render_ip_draft_bundle"]
