"""Schema-free synchronous report adapters over canonical IP readers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from caseops_api.schemas.ip_reports import (
    IpReportDefinitionRecord,
    IpReportFoundationContract,
    IpReportFreshness,
    IpReportPreviewRequest,
    IpReportPreviewResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.connector_health import read_tenant_connector_health
from caseops_api.services.ip_operations import ip_daily_docket, ip_docket_control_report
from caseops_api.services.ip_portfolio import list_ip_portfolio
from caseops_api.services.ip_renewals import list_renewal_portfolio
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
        canonical_sources=["ip_watch_provider"],
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
    latest = max((row.updated_at for row in portfolio.rows), default=None)
    registry_cutoffs = [
        row.registry_last_success_at
        for row in portfolio.rows
        if row.registry_last_success_at is not None
    ]
    registry_cutoff = max(registry_cutoffs, default=None)
    registry_current = bool(portfolio.rows) and all(
        row.registry_sync_state == "current" and row.registry_last_success_at is not None
        for row in portfolio.rows
    )
    registry_unavailable = registry_cutoff is None
    freshness = IpReportFreshness(
        status="current" if registry_current else "mixed",
        generated_at=generated_at,
        source_cutoffs={"portfolio_records": latest, "registry_sync": registry_cutoff},
        unavailable_sources=["registry_sync"] if registry_unavailable else [],
    )
    return (
        generated_at,
        portfolio.counts.model_dump(mode="json"),
        rows,
        portfolio.counts.total > len(rows),
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
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    report = ip_docket_control_report(session, context=context)
    freshness = IpReportFreshness(
        status="mixed",
        generated_at=report.generated_at,
        source_cutoffs={"docket_control": report.generated_at, "provider_freshness": None},
        unavailable_sources=["provider_freshness"],
    )
    return (
        report.generated_at,
        report.model_dump(mode="json"),
        [],
        False,
        freshness,
    )


def _renewal_payload(
    session: Session,
    *,
    context: SessionContext,
    payload: IpReportPreviewRequest,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness]:
    portfolio = list_renewal_portfolio(session, context=context)
    selected = [
        row
        for row in portfolio.items
        if not payload.renewal_states or row.reporting_state in payload.renewal_states
    ]
    visible = selected[: payload.row_limit]
    latest = max((row.term.updated_at for row in selected), default=None)
    summary = {
        "total": len(selected),
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
    return (
        portfolio.generated_at,
        summary,
        [row.model_dump(mode="json") for row in visible],
        len(selected) > len(visible),
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
    rows = [
        {"metric": key, "value": value, "available": value is not None}
        for key, value in counts.items()
        if key != "registry_sync_state"
    ]
    visible = rows[: payload.row_limit]
    unavailable = ["registry_sync"] if portfolio.counts.registry_sync_state == "unavailable" else []
    freshness = IpReportFreshness(
        status="mixed" if unavailable else "current",
        generated_at=generated_at,
        source_cutoffs={
            "portfolio_records": (portfolio.rows[0].updated_at if portfolio.rows else None),
            "registry_sync": None,
        },
        unavailable_sources=unavailable,
    )
    return generated_at, counts, visible, len(rows) > len(visible), freshness


def _watch_payload() -> tuple[
    datetime, dict[str, Any], list[dict[str, Any]], bool, IpReportFreshness
]:
    generated_at = datetime.now(UTC)
    freshness = IpReportFreshness(
        status="unavailable",
        generated_at=generated_at,
        source_cutoffs={"ip_watch_provider": None},
        unavailable_sources=["ip_watch_provider"],
    )
    return (
        generated_at,
        {
            "available": False,
            "reason": "IP watch operations are not activated for this workspace.",
        },
        [],
        False,
        freshness,
    )


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
            session, context=context
        )
    elif payload.report_kind == "renewal":
        generated_at, summary, rows, truncated, freshness = _renewal_payload(
            session, context=context, payload=payload
        )
    elif payload.report_kind == "watch":
        generated_at, summary, rows, truncated, freshness = _watch_payload()
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
        "generated_at": generated_at.isoformat(),
        "audience": payload.audience,
        "confidentiality": payload.confidentiality,
        "filters": filters,
        "freshness": freshness.model_dump(mode="json"),
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
