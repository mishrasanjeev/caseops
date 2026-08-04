from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    JudgeAppointment,
    SourceLinkReport,
    StatuteSection,
)
from caseops_api.schemas.source_actions import (
    SourceActionRecord,
    SourceLinkReportCreateRequest,
    SourceLinkReportRecord,
    SourceOriginSurface,
    SourceTargetType,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

_OFFICIAL_HOST_SUFFIXES = (".gov.in", ".nic.in", ".judiciary.gov.in")
_OFFICIAL_HOSTS = {
    "gov.in",
    "indiacode.nic.in",
    "main.sci.gov.in",
    "www.sci.gov.in",
    "sci.gov.in",
}


@dataclass(frozen=True, slots=True)
class ResolvedSourceTarget:
    target_type: SourceTargetType
    target_id: str
    source_reference: str | None
    verified: bool
    quarantined: bool
    source_version: str
    provider: str | None


def _is_official_host(hostname: str) -> bool:
    hostname = hostname.rstrip(".").lower()
    return hostname in _OFFICIAL_HOSTS or any(
        hostname.endswith(suffix) for suffix in _OFFICIAL_HOST_SUFFIXES
    )


def inspect_source_action(
    source_reference: str | None,
    *,
    verified: bool = False,
    quarantined: bool = False,
    open_url: str | None = None,
) -> SourceActionRecord:
    reference = (source_reference or "").strip()
    if quarantined:
        return SourceActionRecord(
            state="quarantined",
            source_reference=reference or None,
            reason="Source content is quarantined pending curator verification.",
        )
    if not reference:
        return SourceActionRecord(
            state="missing",
            reason="No source reference is available for this record.",
        )
    if reference.startswith("/api/"):
        return SourceActionRecord(
            state="available",
            open_url=reference,
            source_reference=reference,
        )

    parsed = urlsplit(reference)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return SourceActionRecord(
            state="blocked",
            source_reference=reference,
            reason="Only authenticated CaseOps paths and HTTPS sources may be opened.",
        )
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        return SourceActionRecord(
            state="blocked",
            source_reference=reference,
            reason="Source URL contains credentials or a non-standard port.",
        )
    if not _is_official_host(parsed.hostname):
        return SourceActionRecord(
            state="unverified",
            source_reference=reference,
            reason="Source host is not verified in the CaseOps legal-source policy.",
        )
    return SourceActionRecord(
        state="available",
        open_url=open_url or f"/api/source-actions/open?url={quote(reference, safe='')}",
        source_reference=reference,
    )


def source_target_open_url(target_type: SourceTargetType, target_id: str) -> str:
    return f"/api/source-actions/targets/{target_type}/{quote(target_id, safe='')}/open"


def resolve_source_target(
    session: Session,
    *,
    target_type: SourceTargetType,
    target_id: str,
) -> ResolvedSourceTarget | None:
    if target_type == "authority_document":
        row = session.get(AuthorityDocument, target_id)
        if row is None:
            return None
        return ResolvedSourceTarget(
            target_type=target_type,
            target_id=row.id,
            source_reference=row.source_reference,
            verified=True,
            quarantined=False,
            source_version=row.updated_at.isoformat(),
            provider=row.source,
        )
    if target_type == "statute_section":
        row = session.get(StatuteSection, target_id)
        if row is None:
            return None
        return ResolvedSourceTarget(
            target_type=target_type,
            target_id=row.id,
            source_reference=row.section_url,
            verified=row.verification_status in {"verified_official", "verified_licensed"},
            quarantined=row.verification_status == "quarantined",
            source_version=str(row.source_version),
            provider=row.source_publisher,
        )
    row = session.get(JudgeAppointment, target_id)
    if row is None:
        return None
    return ResolvedSourceTarget(
        target_type=target_type,
        target_id=row.id,
        source_reference=row.source_url,
        verified=True,
        quarantined=False,
        source_version=row.updated_at.isoformat(),
        provider="court_registry",
    )


def inspect_resolved_source_target(target: ResolvedSourceTarget) -> SourceActionRecord:
    return inspect_source_action(
        target.source_reference,
        verified=target.verified,
        quarantined=target.quarantined,
        open_url=source_target_open_url(target.target_type, target.target_id),
    )


def source_destination_class(action: SourceActionRecord) -> str:
    reference = action.source_reference or ""
    if action.state != "available":
        return f"unavailable_{action.state}"
    if reference.startswith("/api/"):
        return "caseops_protected"
    return "verified_public"


def source_reference_sha256(reference: str | None) -> str | None:
    normalized = (reference or "").strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def audit_source_open(
    session: Session,
    *,
    context: SessionContext,
    target: ResolvedSourceTarget,
    action: SourceActionRecord,
    origin_surface: SourceOriginSurface,
    outcome: str,
) -> None:
    record_from_context(
        session,
        context,
        action="source_access.opened",
        target_type=target.target_type,
        target_id=target.target_id,
        result=outcome,
        metadata={
            "origin_surface": origin_surface,
            "permission_decision": "allowed",
            "destination_class": source_destination_class(action),
            "source_state": action.state,
            "source_version": target.source_version,
            "provider": target.provider,
            "source_reference_sha256": source_reference_sha256(
                target.source_reference
            ),
        },
    )


def create_source_link_report(
    session: Session,
    *,
    context: SessionContext,
    payload: SourceLinkReportCreateRequest,
) -> SourceLinkReportRecord:
    target = resolve_source_target(
        session,
        target_type=payload.target_type,
        target_id=payload.target_id,
    )
    if target is None:
        raise LookupError("Source target was not found.")
    action = inspect_resolved_source_target(target)
    destination_class = source_destination_class(action)
    report = SourceLinkReport(
        company_id=context.company.id,
        reported_by_membership_id=context.membership.id,
        target_type=target.target_type,
        target_id=target.target_id,
        origin_surface=payload.origin_surface,
        issue_type=payload.issue_type,
        description=payload.description,
        source_reference_sha256=source_reference_sha256(target.source_reference),
        destination_class=destination_class,
        source_state=action.state,
        status="queued",
    )
    session.add(report)
    session.flush()
    record_from_context(
        session,
        context,
        action="source_access.defect_reported",
        target_type=target.target_type,
        target_id=target.target_id,
        metadata={
            "report_id": report.id,
            "origin_surface": payload.origin_surface,
            "issue_type": payload.issue_type,
            "destination_class": destination_class,
            "source_state": action.state,
            "source_version": target.source_version,
            "provider": target.provider,
            "source_reference_sha256": report.source_reference_sha256,
            "health_check_requested": True,
        },
    )
    session.commit()
    session.refresh(report)
    return SourceLinkReportRecord.model_validate(report, from_attributes=True)


def assert_safe_source_redirect(source_reference: str) -> str:
    action = inspect_source_action(source_reference)
    if action.state != "available" or not action.source_reference:
        raise ValueError(action.reason or "Source cannot be opened safely.")
    return action.source_reference


__all__ = [
    "ResolvedSourceTarget",
    "assert_safe_source_redirect",
    "audit_source_open",
    "create_source_link_report",
    "inspect_resolved_source_target",
    "inspect_source_action",
    "resolve_source_target",
    "source_destination_class",
    "source_reference_sha256",
    "source_target_open_url",
]
