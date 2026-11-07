"""Schema-free synchronous report adapters over canonical IP readers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpJournalPublication,
    IpWatchHit,
    IpWatchProfile,
    Matter,
    MatterStatus,
    TrademarkApplication,
)
from caseops_api.schemas.ip_reports import (
    IpReportDefinitionRecord,
    IpReportFoundationContract,
    IpReportFreshness,
    IpReportPreviewRequest,
    IpReportPreviewResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.connector_health import read_tenant_connector_health
from caseops_api.services.ip_lifecycle import (
    TERMINAL_APPLICATION_PHASES,
    TERMINAL_IP_DOCKET_STATUSES,
)
from caseops_api.services.ip_operations import ip_daily_docket, ip_docket_control_report
from caseops_api.services.ip_portfolio import list_ip_portfolio
from caseops_api.services.ip_renewals import list_renewal_portfolio
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.session_context import SessionContext

_DEFINITIONS = (
    IpReportDefinitionRecord(
        key="portfolio_register",
        schema_version="ip-portfolio-register-v1",
        canonical_sources=[
            "trademark_applications",
            "ip_assets",
            "ip_docket_records",
            "ip_identifiers",
            "ip_deadlines",
        ],
    ),
    IpReportDefinitionRecord(
        key="application_status",
        schema_version="ip-application-status-v1",
        canonical_sources=[
            "trademark_applications",
            "ip_docket_records",
            "ip_identifiers",
        ],
    ),
    IpReportDefinitionRecord(
        key="opposition_status",
        schema_version="ip-opposition-status-v1",
        canonical_sources=[
            "trademark_applications",
            "ip_docket_records",
            "ip_identifiers",
        ],
    ),
    IpReportDefinitionRecord(
        key="deadline_control",
        schema_version="ip-deadline-control-v1",
        canonical_sources=[
            "ip_docket_records",
            "ip_deadline_coverages",
            "ip_deadline_incidents",
            "calendar_event_syncs",
        ],
    ),
    IpReportDefinitionRecord(
        key="renewal",
        schema_version="ip-renewal-report-v1",
        canonical_sources=[
            "ip_renewal_terms",
            "ip_client_instructions",
            "ip_deadlines",
            "ip_cost_items",
            "notification_delivery_intents",
        ],
    ),
    IpReportDefinitionRecord(
        key="watch",
        schema_version="ip-watch-report-v1",
        canonical_sources=["ip_watch_profiles", "ip_watch_hits", "ip_journal_publications"],
    ),
    IpReportDefinitionRecord(
        key="workload",
        schema_version="ip-workload-report-v1",
        canonical_sources=[
            "ip_docket_records",
            "ip_deadline_coverages",
            "company_memberships",
        ],
    ),
    IpReportDefinitionRecord(
        key="data_quality",
        schema_version="ip-data-quality-v1",
        canonical_sources=[
            "trademark_applications",
            "ip_assets",
            "ip_docket_records",
            "ip_identifiers",
            "ip_deadlines",
        ],
    ),
    IpReportDefinitionRecord(
        key="integration_freshness",
        schema_version="ip-integration-freshness-v1",
        canonical_sources=["connector_health_records"],
    ),
)
_RENEWAL_REPORT_SCAN_LIMIT = 1000


def ip_report_foundation_contract() -> IpReportFoundationContract:
    return IpReportFoundationContract(definitions=list(_DEFINITIONS))


def _definition(kind: str) -> IpReportDefinitionRecord:
    return next(row for row in _DEFINITIONS if row.key == kind)


def _snapshot_sha256(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _portfolio_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    generated_at = datetime.now(UTC)
    portfolio = list_ip_portfolio(
        session,
        context=context,
        filters=payload.filters,
        limit=payload.row_limit,
    )
    rows = [row.model_dump(mode="json") for row in portfolio.rows]
    counts = portfolio.counts
    registry_incomplete = counts.synchronized_records < counts.total
    registry_current = counts.total == 0 or (
        not registry_incomplete and counts.stale_sync_records == 0
    )
    freshness = IpReportFreshness(
        status="current" if registry_current else "mixed",
        generated_at=generated_at,
        source_cutoffs={
            "portfolio_records": portfolio.latest_record_updated_at,
            "registry_sync": portfolio.latest_registry_success_at,
        },
        unavailable_sources=["registry_sync"] if registry_incomplete else [],
    )
    summary = counts.model_dump(mode="json")
    summary.update({"returned": len(rows), "counts_are_complete": True})
    return (
        generated_at,
        summary,
        rows,
        counts.total > len(rows),
        freshness,
    )


def _status_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
    opposition_only: bool,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    filters = payload.filters.model_copy(
        update={"opposition_only": True} if opposition_only else {}
    )
    scoped_payload = payload.model_copy(update={"filters": filters})
    generated_at, counts, rows, truncated, freshness = _portfolio_payload(
        session,
        context=context,
        payload=scoped_payload,
    )
    by_phase: dict[str, int] = {}
    for row in rows:
        phase = str(row["filing_phase"])
        by_phase[phase] = by_phase.get(phase, 0) + 1
    summary = {
        "total": counts["total"],
        "returned": len(rows),
        "returned_by_filing_phase": dict(sorted(by_phase.items())),
    }
    if opposition_only:
        summary["returned_opposition_numbered"] = sum(
            bool(row["opposition_numbers"]) for row in rows
        )
    else:
        summary["returned_application_numbered"] = sum(
            bool(row["application_numbers"]) for row in rows
        )
    return generated_at, summary, rows, truncated, freshness


def _deadline_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    report = ip_docket_control_report(
        session,
        context=context,
        limit=payload.row_limit,
    )
    freshness = IpReportFreshness(
        status="mixed",
        generated_at=report.generated_at,
        source_cutoffs={
            "docket_control": report.source_cutoff,
            "provider_freshness": None,
        },
        unavailable_sources=["provider_freshness"],
    )
    return (
        report.generated_at,
        report.model_dump(mode="json", exclude={"generated_at", "rows"}),
        [row.model_dump(mode="json") for row in report.rows],
        not report.counts_are_complete or len(report.rows) < report.docket_count,
        freshness,
    )


def _renewal_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    scan_limit = _RENEWAL_REPORT_SCAN_LIMIT if payload.renewal_states else payload.row_limit
    portfolio = list_renewal_portfolio(
        session,
        context=context,
        limit=scan_limit,
        include_instruction_history=False,
        include_reminder_history=False,
    )
    selected = [
        row
        for row in portfolio.items
        if not payload.renewal_states or row.reporting_state in payload.renewal_states
    ]
    visible = selected[: payload.row_limit]
    latest = max((row.term.updated_at for row in portfolio.items), default=None)
    summary = {
        "total": len(selected),
        "returned": len(visible),
        "scanned": len(portfolio.items),
        "counts_are_complete": portfolio.counts_are_complete,
        "due": 0,
        "instructed": 0,
        "filing_in_progress": 0,
        "filed": 0,
        "accepted": 0,
        "grace": 0,
        "overdue": 0,
        "completed": 0,
        "cancelled": 0,
        "action_required": 0,
    }
    for row in selected:
        summary[row.reporting_state] += 1
        if row.action_required != "none":
            summary["action_required"] += 1
    freshness = IpReportFreshness(
        status="mixed",
        generated_at=portfolio.generated_at,
        source_cutoffs={"renewal_terms": latest, "registry_freshness": None},
        unavailable_sources=["registry_freshness"],
    )
    rows = [row.model_dump(mode="json") for row in visible]
    for row in rows:
        # The report needs current instruction-derived state, not an unbounded
        # instruction-history export. Full history remains with the canonical
        # renewal workspace rather than being copied into this projection.
        row["term"].pop("instructions", None)
        row.pop("reminders", None)
    return (
        portfolio.generated_at,
        summary,
        rows,
        portfolio.has_more or len(selected) > len(visible),
        freshness,
    )


def _data_quality_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    generated_at = datetime.now(UTC)
    portfolio = list_ip_portfolio(
        session,
        context=context,
        filters=payload.filters,
        limit=1,
    )
    counts = portfolio.counts.model_dump(mode="json")
    counts.update({"counts_are_complete": True})
    rows = [
        {"metric": key, "value": value, "available": value is not None}
        for key, value in counts.items()
        if key not in {"registry_sync_state", "counts_are_complete"}
    ]
    visible = rows[: payload.row_limit]
    registry_incomplete = portfolio.counts.synchronized_records < portfolio.counts.total
    unavailable = ["registry_sync"] if registry_incomplete else []
    freshness = IpReportFreshness(
        status=(
            "current"
            if not registry_incomplete and portfolio.counts.stale_sync_records == 0
            else "mixed"
        ),
        generated_at=generated_at,
        source_cutoffs={
            "portfolio_records": portfolio.latest_record_updated_at,
            "registry_sync": portfolio.latest_registry_success_at,
        },
        unavailable_sources=unavailable,
    )
    return generated_at, counts, visible, len(rows) > len(visible), freshness


def _watch_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    generated_at = datetime.now(UTC)
    visible_dockets = (
        select(IpDocketRecord.id, IpDocketRecord.title)
        .outerjoin(
            Matter,
            (Matter.id == IpDocketRecord.matter_id)
            & (Matter.company_id == IpDocketRecord.company_id),
        )
        .where(
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.status.notin_(TERMINAL_IP_DOCKET_STATUSES),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            or_(
                IpDocketRecord.matter_id.is_(None),
                Matter.is_active.is_(True)
                & Matter.status.in_(
                    (MatterStatus.INTAKE, MatterStatus.ACTIVE, MatterStatus.ON_HOLD)
                ),
            ),
            visible_ip_dockets_filter(session, context=context),
        )
        .cte("watch_report_visible_dockets")
    )
    visible_applications = select(TrademarkApplication.id).where(
        TrademarkApplication.company_id == context.company.id,
        TrademarkApplication.docket_id.in_(select(visible_dockets.c.id)),
        TrademarkApplication.is_active.is_(True),
        TrademarkApplication.filing_phase.notin_(TERMINAL_APPLICATION_PHASES),
    )
    visible_publications = (
        select(IpJournalPublication.id)
        .where(
            IpJournalPublication.company_id == context.company.id,
            or_(
                IpJournalPublication.application_id.is_(None),
                IpJournalPublication.application_id.in_(visible_applications),
            ),
        )
        .correlate(None)
    )
    # Authorize both the watched docket and any linked source application.
    # Filtering hits in the join preserves a visible zero-hit profile without
    # disclosing whether it also has hits whose source is now inaccessible.
    statement = (
        select(
            IpWatchProfile,
            IpWatchHit,
            visible_dockets.c.title,
            IpJournalPublication.source_retrieved_at,
            IpJournalPublication.provider_key,
        )
        .join(visible_dockets, visible_dockets.c.id == IpWatchProfile.docket_id)
        .outerjoin(
            IpWatchHit,
            (IpWatchHit.profile_id == IpWatchProfile.id)
            & (IpWatchHit.company_id == IpWatchProfile.company_id)
            & IpWatchHit.publication_id.in_(visible_publications),
        )
        .outerjoin(
            IpJournalPublication,
            (IpJournalPublication.id == IpWatchHit.publication_id)
            & (IpJournalPublication.company_id == IpWatchHit.company_id),
        )
        .where(IpWatchProfile.company_id == context.company.id)
    )
    records = statement.with_only_columns(
        IpWatchProfile.id.label("profile_id"),
        IpWatchProfile.updated_at.label("profile_updated_at"),
        IpWatchHit.id.label("hit_id"),
        IpWatchHit.updated_at.label("hit_updated_at"),
        IpWatchHit.disposition,
        IpWatchHit.reviewed_at,
        IpJournalPublication.source_retrieved_at,
    ).subquery()
    totals = session.execute(
        select(
            func.count().label("total"),
            func.count(func.distinct(records.c.profile_id)).label("profile_total"),
            func.count(records.c.hit_id).label("hit_total"),
            func.count(case((records.c.disposition == "new", 1))).label("new_hits"),
            func.count(case((records.c.disposition == "relevant", 1))).label("relevant_hits"),
            func.count(records.c.reviewed_at).label("reviewed_hits"),
            func.count(
                case((records.c.disposition.in_(("new", "reviewing")), 1))
            ).label("pending_assessment"),
            func.max(records.c.profile_updated_at).label("profiles_cutoff"),
            func.max(records.c.hit_updated_at).label("hits_cutoff"),
            func.max(records.c.source_retrieved_at).label("capture_cutoff"),
        )
    ).one()
    rows = []
    for profile, hit, title, retrieved_at, provider_key in session.execute(
        statement.order_by(
            IpWatchHit.hit_date.desc().nulls_last(),
            IpWatchHit.created_at.desc().nulls_last(),
            IpWatchHit.id.desc().nulls_last(),
            IpWatchProfile.updated_at.desc(),
            IpWatchProfile.id.desc(),
        ).limit(payload.row_limit)
    ):
        rows.append(
            {
                "docket_title": title,
                "watch_name": profile.name,
                "watch_criteria": {
                    "word_terms": profile.word_terms_json,
                    "phonetic_terms": profile.phonetic_terms_json,
                    "device_references": profile.device_references_json,
                    "classes": profile.class_numbers_json,
                    "proprietors": profile.proprietor_terms_json,
                    "jurisdictions": profile.jurisdictions_json,
                },
                "profile_status": profile.poll_status,
                "compared_mark": hit.compared_mark_json if hit else None,
                "candidate_mark": hit.candidate_mark_json if hit else None,
                "assessment": {
                    "disposition": hit.disposition,
                    "reason": hit.disposition_reason,
                    "reviewed_at": hit.reviewed_at,
                    "decision": hit.reviewer_decision_json,
                } if hit else None,
                "source": {
                    "provider": provider_key,
                    "url": hit.source_url,
                    "status": hit.source_status,
                    "hit_date": hit.hit_date,
                    "captured_at": retrieved_at,
                    "stale_source_alert": hit.stale_source_alert,
                    "deadline_confirmation_state": hit.deadline_confirmation_state,
                } if hit else None,
                "classes_goods": hit.classes_goods_json if hit else None,
                "similarity_evidence": {
                    "evidence": hit.similarity_evidence_json,
                    "ai_advisory": hit.ai_advisory,
                    "notice": hit.advisory_notice,
                } if hit else None,
                "profile_id": profile.id,
                "docket_id": profile.docket_id,
                "hit_id": hit.id if hit else None,
                "publication_id": hit.publication_id if hit else None,
                "source_snapshot": hit.source_snapshot_json if hit else None,
                "profile_version": profile.version,
                "hit_version": hit.version if hit else None,
            }
        )
    rows = jsonable_encoder(rows)
    summary = {
        "available": True,
        "reason": (
            "Only retained journal-watch records are included; automated journal coverage "
            "is unavailable."
            if totals.profile_total
            else "No retained journal-watch records match your access; automated journal "
            "coverage is unavailable."
        ),
        "automated_coverage_available": False,
        "total": totals.total,
        "returned": len(rows),
        "profile_total": totals.profile_total,
        "hit_total": totals.hit_total,
        "new_hits": totals.new_hits,
        "relevant_hits": totals.relevant_hits,
        "reviewed_hits": totals.reviewed_hits,
        "pending_assessment": totals.pending_assessment,
        "counts_are_complete": True,
    }
    freshness = IpReportFreshness(
        status="mixed",
        generated_at=generated_at,
        source_cutoffs={
            "watch_profiles": totals.profiles_cutoff,
            "watch_hits": totals.hits_cutoff,
            "journal_capture": totals.capture_cutoff,
            "ip_watch_provider": None,
        },
        unavailable_sources=["ip_watch_provider"],
    )
    return generated_at, summary, rows, totals.total > len(rows), freshness


def _workload_payload(
    session: Session,
    *,
    context: SessionContext,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    report = ip_daily_docket(session, context=context)
    rows = [row.model_dump(mode="json") for row in report.queues]
    summary = {
        "queue_count": len(rows),
        "escalation_count": len(report.escalations),
        "counts_are_complete": report.counts_are_complete,
    }
    freshness = IpReportFreshness(
        status="current" if report.counts_are_complete else "mixed",
        generated_at=report.generated_at,
        source_cutoffs={"daily_docket": report.generated_at},
        unavailable_sources=list(report.stale_sources),
    )
    return report.generated_at, summary, rows, False, freshness


def _integration_freshness_payload(
    session: Session,
    *,
    context: SessionContext,
    row_limit: int,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    generated_at = datetime.now(UTC)
    report = read_tenant_connector_health(session, context=context)
    selected = report.health[:row_limit]
    cutoffs = [row.last_checked_at for row in report.health if row.last_checked_at is not None]
    unavailable = sorted(
        {
            row.provider
        for row in report.health
        if row.freshness_state in {"never_succeeded", "blocked", "unknown"}
        }
    )
    if not report.health:
        unavailable = ["connector_health"]
    freshness = IpReportFreshness(
        status=(
            "unavailable"
            if not report.health or len(unavailable) == len(report.health)
            else "mixed"
            if unavailable or report.stale_count
            else "current"
        ),
        generated_at=generated_at,
        source_cutoffs={"connector_health": max(cutoffs, default=None)},
        unavailable_sources=unavailable,
    )
    summary = {
        "total": len(report.health),
        "healthy": report.healthy_count,
        "unhealthy": report.unhealthy_count,
        "stale": report.stale_count,
        "disabled": report.disabled_count,
    }
    return (
        generated_at,
        summary,
        [row.model_dump(mode="json") for row in selected],
        len(report.health) > len(selected),
        freshness,
    )


def preview_ip_report(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> IpReportPreviewResponse:
    if payload.report_kind == "portfolio_register":
        generated_at, summary, rows, truncated, freshness = _portfolio_payload(
            session, context=context, payload=payload
        )
    elif payload.report_kind == "application_status":
        generated_at, summary, rows, truncated, freshness = _status_payload(
            session, context=context, payload=payload, opposition_only=False
        )
    elif payload.report_kind == "opposition_status":
        generated_at, summary, rows, truncated, freshness = _status_payload(
            session, context=context, payload=payload, opposition_only=True
        )
    elif payload.report_kind == "deadline_control":
        generated_at, summary, rows, truncated, freshness = _deadline_payload(
            session, context=context, payload=payload
        )
    elif payload.report_kind == "renewal":
        generated_at, summary, rows, truncated, freshness = _renewal_payload(
            session, context=context, payload=payload
        )
    elif payload.report_kind == "watch":
        generated_at, summary, rows, truncated, freshness = _watch_payload(
            session, context=context, payload=payload
        )
    elif payload.report_kind == "workload":
        generated_at, summary, rows, truncated, freshness = _workload_payload(
            session, context=context
        )
    elif payload.report_kind == "data_quality":
        generated_at, summary, rows, truncated, freshness = _data_quality_payload(
            session, context=context, payload=payload
        )
    else:
        generated_at, summary, rows, truncated, freshness = _integration_freshness_payload(
            session,
            context=context,
            row_limit=payload.row_limit,
        )

    definition = _definition(payload.report_kind)
    filters: dict[str, Any] = {"row_limit": payload.row_limit}
    if payload.report_kind in {
        "portfolio_register",
        "application_status",
        "opposition_status",
        "data_quality",
    }:
        filters["portfolio"] = payload.filters.model_dump(mode="json")
        if payload.report_kind == "opposition_status":
            filters["portfolio"]["opposition_only"] = True
    elif payload.report_kind == "renewal":
        filters["renewal_states"] = payload.renewal_states
    snapshot = {
        "report_kind": payload.report_kind,
        "schema_version": definition.schema_version,
        "audience": payload.audience,
        "confidentiality": payload.confidentiality,
        "filters": filters,
        # The review fingerprint must remain stable when unchanged content is
        # rendered twice. Source cutoffs remain part of the fingerprint, while
        # the wall-clock render instant is response metadata only.
        "freshness": freshness.model_dump(mode="json", exclude={"generated_at"}),
        "summary": summary,
        "rows": rows,
        "truncated": truncated,
    }
    response = IpReportPreviewResponse(
        report_kind=payload.report_kind,
        schema_version=definition.schema_version,
        generated_at=generated_at,
        confidentiality=payload.confidentiality,
        filters=filters,
        freshness=freshness,
        row_count=len(rows),
        truncated=truncated,
        summary=summary,
        rows=rows,
        snapshot_sha256=_snapshot_sha256(snapshot),
    )
    record_from_context(
        session,
        context,
        action="ip.report.previewed",
        target_type="ip_report_definition",
        target_id=payload.report_kind,
        metadata={
            "schema_version": definition.schema_version,
            "audience": payload.audience,
            "confidentiality": payload.confidentiality,
            "row_count": response.row_count,
            "truncated": response.truncated,
            "freshness_status": response.freshness.status,
            "snapshot_sha256": response.snapshot_sha256,
        },
    )
    session.commit()
    return response


__all__ = ["ip_report_foundation_contract", "preview_ip_report"]
