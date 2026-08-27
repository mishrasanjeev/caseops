from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    JudgeAppointment,
    Matter,
    MatterAttachment,
    SourceLinkReport,
    StatuteSection,
)
from caseops_api.schemas.source_actions import (
    SourceActionRecord,
    SourceIssueType,
    SourceLinkReportCreateRequest,
    SourceLinkReportRecord,
    SourceOriginSurface,
    SourceTargetType,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_document_workflow import assert_ip_document_access
from caseops_api.services.matter_access import assert_access
from caseops_api.services.session_context import SessionContext

_OFFICIAL_HOST_SUFFIXES = (".gov.in", ".nic.in", ".judiciary.gov.in")
_OFFICIAL_HOSTS = {
    "gov.in",
    "indiacode.nic.in",
    "main.sci.gov.in",
    "www.sci.gov.in",
    "sci.gov.in",
}
_LICENSED_SOURCE_HOSTS = {"indiankanoon.org", "www.indiankanoon.org"}


@dataclass(frozen=True, slots=True)
class ResolvedSourceTarget:
    target_type: SourceTargetType
    target_id: str
    source_reference: str | None
    verified: bool
    quarantined: bool
    source_version: str
    provider: str | None
    ip_docket_id: str | None = None


def _is_official_host(hostname: str) -> bool:
    hostname = hostname.rstrip(".").lower()
    return hostname in _OFFICIAL_HOSTS or any(
        hostname.endswith(suffix) for suffix in _OFFICIAL_HOST_SUFFIXES
    )


def _is_approved_source_host(hostname: str) -> bool:
    hostname = hostname.rstrip(".").lower()
    return _is_official_host(hostname) or hostname in _LICENSED_SOURCE_HOSTS


def authority_source_verified(source: str | None, source_reference: str | None) -> bool:
    """Whether an authority document's source can be trusted enough to open.

    FMB-01/FMB-02: the previous predicate compared a source field against the
    literal ``"official"``, a value no ingest path ever writes - the two writers
    store adapter source keys (``corpus_ingest.py`` writes ``ecourts-hc`` /
    ``ecourts-sc``; ``authorities.py`` copies the adapter's ``source_key``). The
    check was therefore statically dead: it could never be satisfied by real
    data, while a test fixture using the fake value kept the suite green.

    The verdict is now derived from two things the ingest path really does
    record, and both must hold:

    1. the ``source`` key resolves to a registry entry classified official or
       licensed, and
    2. the ``source_reference`` is an approved official HTTPS URL.

    Conjunctive on purpose. A trusted source key with a bare PDF filename fails,
    because there is nothing to open; a good URL under an unknown source key
    fails, because we cannot say where it came from.

    Note this classification is *derived*, so editing the static registry
    retroactively re-classifies historical rows. Bulk-mirror keys are
    deliberately absent from the registry, so those rows read untrusted - which
    is the honest answer, since they came from public mirrors rather than a
    court registry.
    """
    from caseops_api.services.authority_sources import (
        LEGAL_SOURCE_REGISTRY_BY_KEY,
        SOURCE_TYPE_LICENSED,
        SOURCE_TYPE_OFFICIAL,
    )

    entry = LEGAL_SOURCE_REGISTRY_BY_KEY.get((source or "").strip())
    if entry is None or entry.source_type not in {SOURCE_TYPE_OFFICIAL, SOURCE_TYPE_LICENSED}:
        return False
    return is_approved_legal_source_reference(source_reference)


def judge_appointment_source_verified(source_url: str | None) -> bool:
    """Whether a judge appointment's source URL is an approved official one.

    FMB-02: this branch previously hardcoded ``verified=True``, so an
    appointment carrying any URL - or none - was reported as verified.
    """
    return is_official_source_reference(source_url)


def is_official_source_reference(source_reference: str | None) -> bool:
    """Return whether a URL is an approved official HTTPS source reference."""

    return _is_safe_source_reference(source_reference, approved_host=_is_official_host)


def is_approved_legal_source_reference(source_reference: str | None) -> bool:
    """Return whether a URL is an approved official or licensed legal source."""

    return _is_safe_source_reference(source_reference, approved_host=_is_approved_source_host)


def _is_safe_source_reference(
    source_reference: str | None,
    *,
    approved_host: Callable[[str], bool],
) -> bool:

    reference = (source_reference or "").strip()
    if not reference:
        return False
    parsed = urlsplit(reference)
    return bool(
        parsed.scheme.lower() == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.port in {None, 443}
        and approved_host(parsed.hostname)
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
            open_url=open_url or reference,
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
    if not _is_approved_source_host(parsed.hostname):
        return SourceActionRecord(
            state="unverified",
            source_reference=reference,
            reason="Source host is not verified in the CaseOps legal-source policy.",
        )
    if not verified:
        return SourceActionRecord(
            state="unverified",
            source_reference=reference,
            reason="Source metadata has not completed curator verification.",
        )
    return SourceActionRecord(
        state="available",
        open_url=open_url or f"/api/source-actions/open?url={quote(reference, safe='')}",
        source_reference=reference,
    )


def source_target_open_url(target_type: SourceTargetType, target_id: str) -> str:
    return f"/api/source-actions/targets/{target_type}/{quote(target_id, safe='')}/open"


def inspect_source_target_action(
    source_reference: str | None,
    *,
    target_type: SourceTargetType,
    target_id: str,
    verified: bool = False,
    quarantined: bool = False,
) -> SourceActionRecord:
    action = inspect_source_action(
        source_reference,
        verified=verified,
        quarantined=quarantined,
        open_url=source_target_open_url(target_type, target_id),
    )
    return action.model_copy(
        update={"target_type": target_type, "target_id": target_id}
    )


def resolve_source_target(
    session: Session,
    *,
    target_type: SourceTargetType,
    target_id: str,
    context: SessionContext | None = None,
) -> ResolvedSourceTarget | None:
    if target_type == "authority_document":
        row = session.get(AuthorityDocument, target_id)
        if row is None:
            return None
        source_reference = row.canonical_url or row.source_reference
        return ResolvedSourceTarget(
            target_type=target_type,
            target_id=row.id,
            source_reference=source_reference,
            # FMB-02: was hardcoded True, which made this the fail-open half of
            # a predicate the display surfaces failed closed on.
            verified=authority_source_verified(row.source, source_reference),
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
    if target_type == "matter_attachment":
        row = session.get(MatterAttachment, target_id)
        if row is None or context is None:
            return None
        matter = session.get(Matter, row.matter_id)
        if matter is None or matter.company_id != context.company.id:
            return None
        assert_access(session, context=context, matter=matter)
        return ResolvedSourceTarget(
            target_type=target_type,
            target_id=row.id,
            source_reference=(
                f"/api/matters/{matter.id}/attachments/{row.id}/download"
            ),
            verified=True,
            quarantined=False,
            source_version=row.sha256_hex,
            provider="caseops_matter_document",
        )
    if target_type == "ip_document_version":
        row = session.get(IpDocumentVersion, target_id)
        if row is None or context is None or row.company_id != context.company.id:
            return None
        document = session.get(IpDocument, row.document_id)
        if document is None or document.company_id != context.company.id:
            return None
        assert_ip_document_access(
            session,
            context=context,
            document_id=document.id,
        )
        docket_ids = set(
            session.scalars(
                select(IpDocumentLink.docket_id).where(
                    IpDocumentLink.company_id == context.company.id,
                    IpDocumentLink.document_id == document.id,
                    IpDocumentLink.docket_id.is_not(None),
                )
            ).all()
        )
        return ResolvedSourceTarget(
            target_type=target_type,
            target_id=row.id,
            source_reference=(
                f"/api/ip/documents/{document.id}/versions/{row.version}/download"
            ),
            verified=True,
            quarantined=False,
            source_version=row.sha256_hex,
            provider="caseops_ip_document",
            ip_docket_id=(
                str(next(iter(docket_ids))) if len(docket_ids) == 1 else None
            ),
        )
    row = session.get(JudgeAppointment, target_id)
    if row is None:
        return None
    return ResolvedSourceTarget(
        target_type=target_type,
        target_id=row.id,
        source_reference=row.source_url,
        # FMB-02: was hardcoded True in an unguarded trailing branch.
        verified=judge_appointment_source_verified(row.source_url),
        quarantined=False,
        source_version=row.updated_at.isoformat(),
        provider="court_registry",
    )


def inspect_resolved_source_target(target: ResolvedSourceTarget) -> SourceActionRecord:
    return inspect_source_target_action(
        target.source_reference,
        target_type=target.target_type,
        target_id=target.target_id,
        verified=target.verified,
        quarantined=target.quarantined,
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
        ip_docket_id=target.ip_docket_id,
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


def queue_source_health_check(
    session: Session,
    *,
    context: SessionContext,
    target: ResolvedSourceTarget,
    action: SourceActionRecord,
    origin_surface: SourceOriginSurface,
) -> SourceLinkReport:
    """Idempotently queue an unavailable canonical source for investigation."""

    issue_by_state: dict[str, SourceIssueType] = {
        "missing": "broken",
        "unverified": "stale",
        "blocked": "access_denied",
        "quarantined": "wrong_document",
    }
    issue_type = issue_by_state.get(action.state, "other")
    existing = session.scalar(
        select(SourceLinkReport)
        .where(
            SourceLinkReport.company_id == context.company.id,
            SourceLinkReport.target_type == target.target_type,
            SourceLinkReport.target_id == target.target_id,
            SourceLinkReport.origin_surface == origin_surface,
            SourceLinkReport.issue_type == issue_type,
            SourceLinkReport.status.in_(("queued", "investigating")),
        )
        .order_by(SourceLinkReport.created_at.desc())
    )
    if existing is not None:
        return existing

    destination_class = source_destination_class(action)
    report = SourceLinkReport(
        company_id=context.company.id,
        reported_by_membership_id=context.membership.id,
        target_type=target.target_type,
        target_id=target.target_id,
        origin_surface=origin_surface,
        issue_type=issue_type,
        description="Automatically queued after a failed source-open check.",
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
        result="failed",
        metadata={
            "report_id": report.id,
            "origin_surface": origin_surface,
            "issue_type": issue_type,
            "destination_class": destination_class,
            "source_state": action.state,
            "source_version": target.source_version,
            "provider": target.provider,
            "source_reference_sha256": report.source_reference_sha256,
            "health_check_requested": True,
            "automatic": True,
        },
    )
    return report


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
        context=context,
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
    # This helper validates the destination URL itself for the explicit
    # generic redirect endpoint. Record-level verification is enforced by
    # ``inspect_resolved_source_target`` before opaque target redirects call
    # it; an approved official HTTPS host is sufficient at this final hop.
    action = inspect_source_action(source_reference, verified=True)
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
    "inspect_source_target_action",
    "queue_source_health_check",
    "resolve_source_target",
    "source_destination_class",
    "source_reference_sha256",
    "source_target_open_url",
]
