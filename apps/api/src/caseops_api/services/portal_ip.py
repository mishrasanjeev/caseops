"""IP extensions for the canonical CaseOps client portal owner."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditActorType,
    AuditResult,
    IpClientInstruction,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpIdentifier,
    IpProceeding,
    IpRenewalTerm,
    MatterPortalGrant,
    NotificationDeliveryIntent,
    PortalPublication,
    PortalPublicationTarget,
    PortalUser,
    ReportArtifact,
    TrademarkApplication,
)
from caseops_api.schemas.ip_reports import IpReportPreviewRequest
from caseops_api.schemas.portal_ip import (
    PortalDocumentPublicationCreate,
    PortalGrantRevokeRequest,
    PortalInstructionAcknowledgeRequest,
    PortalInstructionListResponse,
    PortalInstructionRecord,
    PortalInstructionSubmitRequest,
    PortalIpDeadlineRecord,
    PortalIpEventRecord,
    PortalIpGrantListResponse,
    PortalIpGrantRecord,
    PortalIpRecord,
    PortalIpRecordListResponse,
    PortalIpScope,
    PortalPublicationListResponse,
    PortalPublicationRecord,
    PortalPublicationTargetRecord,
    PortalReportPublicationCreate,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.ip_reports import preview_ip_report
from caseops_api.services.matter_access import can_access_ip_docket
from caseops_api.services.notification_delivery import (
    cancel_pending_notification_intents,
    enqueue_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext

_CLIENT_REPORT_KINDS = {
    "portfolio_register",
    "application_status",
    "opposition_status",
    "renewal",
}
_CLIENT_PORTFOLIO_FIELDS = (
    "docket_id",
    "asset_title",
    "docket_title",
    "docket_status",
    "primary_identifier",
    "application_numbers",
    "opposition_numbers",
    "nice_classes",
    "goods_services",
    "office",
    "jurisdiction",
    "filing_phase",
    "open_deadline_count",
    "overdue_deadline_count",
    "registry_sync_state",
    "registry_last_success_at",
    "updated_at",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _actor_label(context: SessionContext) -> str:
    return str(context.user.full_name or context.user.email or context.membership.id)[:255]


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _scope(grant: MatterPortalGrant) -> PortalIpScope:
    try:
        return PortalIpScope.model_validate(grant.scope_json or {})
    except Exception as exc:  # noqa: BLE001 - persisted policy must fail closed
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "portal_grant_scope_invalid",
                "message": "The portal grant policy is invalid and requires firm review.",
            },
        ) from exc


def _grant_is_active(grant: MatterPortalGrant, *, now: datetime | None = None) -> bool:
    current = now or _now()
    return bool(
        grant.revoked_at is None
        and (grant.expires_at is None or _aware(grant.expires_at) > current)
    )


def _active_grant_statement(*, portal_user_id: str, docket_id: str | None = None):
    now = _now()
    statement = select(MatterPortalGrant).where(
        MatterPortalGrant.portal_user_id == portal_user_id,
        MatterPortalGrant.ip_docket_record_id.is_not(None),
        MatterPortalGrant.revoked_at.is_(None),
        or_(MatterPortalGrant.expires_at.is_(None), MatterPortalGrant.expires_at > now),
    )
    if docket_id is not None:
        statement = statement.where(MatterPortalGrant.ip_docket_record_id == docket_id)
    return statement


def _portal_grant(
    session: Session,
    *,
    portal_user: PortalUser,
    docket_id: str,
    lock: bool = False,
) -> tuple[MatterPortalGrant, IpDocketRecord]:
    statement = _active_grant_statement(portal_user_id=portal_user.id, docket_id=docket_id)
    if lock:
        statement = statement.with_for_update(of=MatterPortalGrant)
    grant = session.scalar(statement.execution_options(populate_existing=lock))
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == portal_user.company_id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
        )
    )
    if grant is None or docket is None or grant.company_id != portal_user.company_id:
        raise HTTPException(status_code=404, detail="IP record not found.")
    return grant, docket


def list_admin_ip_grants(session: Session, *, context: SessionContext) -> PortalIpGrantListResponse:
    rows = session.execute(
        select(MatterPortalGrant, PortalUser, IpDocketRecord)
        .join(PortalUser, PortalUser.id == MatterPortalGrant.portal_user_id)
        .join(IpDocketRecord, IpDocketRecord.id == MatterPortalGrant.ip_docket_record_id)
        .where(
            MatterPortalGrant.company_id == context.company.id,
            PortalUser.company_id == context.company.id,
            IpDocketRecord.company_id == context.company.id,
        )
        .order_by(MatterPortalGrant.granted_at.desc(), MatterPortalGrant.id)
        .limit(500)
    ).all()
    now = _now()
    return PortalIpGrantListResponse(
        grants=[
            PortalIpGrantRecord(
                id=grant.id,
                portal_user_id=user.id,
                portal_user_name=user.full_name,
                portal_user_email=user.email,
                ip_docket_record_id=docket.id,
                docket_title=docket.title,
                scope=_scope(grant),
                granted_at=grant.granted_at,
                expires_at=grant.expires_at,
                revoked_at=grant.revoked_at,
                row_version=grant.row_version,
                active=_grant_is_active(grant, now=now),
            )
            for grant, user, docket in rows
        ]
    )


def revoke_ip_grant(
    session: Session,
    *,
    context: SessionContext,
    grant_id: str,
    payload: PortalGrantRevokeRequest,
) -> PortalIpGrantRecord:
    row = session.execute(
        select(MatterPortalGrant, PortalUser, IpDocketRecord)
        .join(PortalUser, PortalUser.id == MatterPortalGrant.portal_user_id)
        .join(IpDocketRecord, IpDocketRecord.id == MatterPortalGrant.ip_docket_record_id)
        .where(
            MatterPortalGrant.id == grant_id,
            MatterPortalGrant.company_id == context.company.id,
        )
        .with_for_update(of=MatterPortalGrant)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Portal grant not found.")
    grant, user, docket = row
    if grant.revoked_at is not None:
        raise _conflict("portal_grant_already_revoked", "The portal grant is already revoked.")
    if grant.row_version != payload.expected_row_version:
        raise _conflict(
            "portal_grant_stale", "The portal grant changed; refresh before revoking it."
        )
    now = _now()
    actor_label = _actor_label(context)
    grant.revoked_at = now
    grant.revoked_by_membership_id = context.membership.id
    grant.revoked_by_label_snapshot = actor_label
    grant.revoked_reason = payload.reason
    grant.row_version += 1
    user.sessions_valid_after = now
    cancelled = 0
    publication_ids = list(
        session.scalars(
            select(PortalPublicationTarget.publication_id).where(
                PortalPublicationTarget.company_id == context.company.id,
                PortalPublicationTarget.portal_grant_id == grant.id,
            )
        )
    )
    for publication_id in publication_ids:
        cancelled += cancel_pending_notification_intents(
            session,
            company_id=context.company.id,
            schedule_source_type="portal_publication",
            schedule_source_id=publication_id,
            cancellation_reason="portal_grant_revoked",
        )
    record_from_context(
        session,
        context,
        action="portal.ip_grant.revoked",
        target_type="portal_grant",
        target_id=grant.id,
        ip_docket_id=docket.id,
        metadata={
            "portal_user_id": user.id,
            "reason": payload.reason,
            "cancelled_delivery_count": cancelled,
            "row_version": grant.row_version,
        },
    )
    session.commit()
    return PortalIpGrantRecord(
        id=grant.id,
        portal_user_id=user.id,
        portal_user_name=user.full_name,
        portal_user_email=user.email,
        ip_docket_record_id=docket.id,
        docket_title=docket.title,
        scope=_scope(grant),
        granted_at=grant.granted_at,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        row_version=grant.row_version,
        active=False,
    )


def _portal_record(
    session: Session,
    *,
    grant: MatterPortalGrant,
    docket: IpDocketRecord,
) -> PortalIpRecord:
    scope = _scope(grant)
    identifiers = []
    if scope.show_identifiers:
        identifiers = list(
            session.scalars(
                select(IpIdentifier.raw_value)
                .where(
                    IpIdentifier.company_id == docket.company_id,
                    IpIdentifier.docket_id == docket.id,
                    IpIdentifier.effective_until.is_(None),
                    IpIdentifier.reconciliation_status == "confirmed",
                )
                .order_by(IpIdentifier.is_primary.desc(), IpIdentifier.identifier_kind)
                .limit(50)
            )
        )
    events: list[PortalIpEventRecord] = []
    if scope.event_kinds:
        event_rows = list(
            session.scalars(
                select(IpDocketEvent)
                .where(
                    IpDocketEvent.company_id == docket.company_id,
                    IpDocketEvent.docket_id == docket.id,
                    IpDocketEvent.event_kind.in_(scope.event_kinds),
                    IpDocketEvent.candidate_status == "confirmed",
                    IpDocketEvent.supersedes_event_id.is_(None),
                )
                .order_by(IpDocketEvent.effective_at.desc())
                .limit(100)
            )
        )
        events = [
            PortalIpEventRecord(
                id=row.id,
                event_kind=row.event_kind,
                effective_at=row.effective_at,
                resulting_stage=row.resulting_stage,
                source=row.source,
            )
            for row in event_rows
        ]
    deadlines: list[PortalIpDeadlineRecord] = []
    if scope.deadline_kinds:
        deadline_rows = list(
            session.scalars(
                select(IpDeadline)
                .where(
                    IpDeadline.company_id == docket.company_id,
                    IpDeadline.docket_id == docket.id,
                    IpDeadline.deadline_kind.in_(scope.deadline_kinds),
                    IpDeadline.state.in_(("confirmed", "overdue")),
                )
                .order_by(IpDeadline.result_on, IpDeadline.result_at)
                .limit(100)
            )
        )
        deadlines = [
            PortalIpDeadlineRecord(
                id=row.id,
                deadline_kind=row.deadline_kind,
                title=row.title,
                due_on=row.result_on.isoformat() if row.result_on else None,
                due_at=row.result_at,
                certainty=row.certainty,
                state=row.state,
            )
            for row in deadline_rows
        ]
    return PortalIpRecord(
        id=docket.id,
        title=docket.title,
        record_type=docket.record_type,
        status=docket.status if scope.show_status else None,
        primary_identifier=(docket.primary_identifier if scope.show_identifiers else None),
        identifiers=identifiers,
        events=events,
        upcoming_dates=deadlines,
        grant_expires_at=grant.expires_at,
    )


def _portal_records(
    session: Session,
    *,
    rows: list[tuple[MatterPortalGrant, IpDocketRecord]],
) -> list[PortalIpRecord]:
    if not rows:
        return []

    scopes = {grant.id: _scope(grant) for grant, _docket in rows}
    identifier_dockets = {docket.id for grant, docket in rows if scopes[grant.id].show_identifiers}
    event_dockets = {docket.id for grant, docket in rows if scopes[grant.id].event_kinds}
    deadline_dockets = {docket.id for grant, docket in rows if scopes[grant.id].deadline_kinds}
    event_kinds = {kind for grant, _docket in rows for kind in scopes[grant.id].event_kinds}
    deadline_kinds = {kind for grant, _docket in rows for kind in scopes[grant.id].deadline_kinds}

    identifiers_by_docket: dict[str, list[str]] = defaultdict(list)
    if identifier_dockets:
        identifier_rows = session.execute(
            select(IpIdentifier.docket_id, IpIdentifier.raw_value)
            .where(
                IpIdentifier.company_id == rows[0][1].company_id,
                IpIdentifier.docket_id.in_(identifier_dockets),
                IpIdentifier.effective_until.is_(None),
                IpIdentifier.reconciliation_status == "confirmed",
            )
            .order_by(
                IpIdentifier.docket_id,
                IpIdentifier.is_primary.desc(),
                IpIdentifier.identifier_kind,
            )
            .limit(len(identifier_dockets) * 50)
        ).all()
        for docket_id, raw_value in identifier_rows:
            if len(identifiers_by_docket[docket_id]) < 50:
                identifiers_by_docket[docket_id].append(raw_value)

    events_by_docket: dict[str, list[IpDocketEvent]] = defaultdict(list)
    if event_dockets and event_kinds:
        event_rows = list(
            session.scalars(
                select(IpDocketEvent)
                .where(
                    IpDocketEvent.company_id == rows[0][1].company_id,
                    IpDocketEvent.docket_id.in_(event_dockets),
                    IpDocketEvent.event_kind.in_(event_kinds),
                    IpDocketEvent.candidate_status == "confirmed",
                    IpDocketEvent.supersedes_event_id.is_(None),
                )
                .order_by(IpDocketEvent.docket_id, IpDocketEvent.effective_at.desc())
                .limit(len(event_dockets) * 100)
            )
        )
        for event in event_rows:
            if len(events_by_docket[event.docket_id]) < 100:
                events_by_docket[event.docket_id].append(event)

    deadlines_by_docket: dict[str, list[IpDeadline]] = defaultdict(list)
    if deadline_dockets and deadline_kinds:
        deadline_rows = list(
            session.scalars(
                select(IpDeadline)
                .where(
                    IpDeadline.company_id == rows[0][1].company_id,
                    IpDeadline.docket_id.in_(deadline_dockets),
                    IpDeadline.deadline_kind.in_(deadline_kinds),
                    IpDeadline.state.in_(("confirmed", "overdue")),
                )
                .order_by(IpDeadline.docket_id, IpDeadline.result_on, IpDeadline.result_at)
                .limit(len(deadline_dockets) * 100)
            )
        )
        for deadline in deadline_rows:
            if len(deadlines_by_docket[deadline.docket_id]) < 100:
                deadlines_by_docket[deadline.docket_id].append(deadline)

    records: list[PortalIpRecord] = []
    for grant, docket in rows:
        scope = scopes[grant.id]
        records.append(
            PortalIpRecord(
                id=docket.id,
                title=docket.title,
                record_type=docket.record_type,
                status=docket.status if scope.show_status else None,
                primary_identifier=(docket.primary_identifier if scope.show_identifiers else None),
                identifiers=identifiers_by_docket[docket.id],
                events=[
                    PortalIpEventRecord(
                        id=event.id,
                        event_kind=event.event_kind,
                        effective_at=event.effective_at,
                        resulting_stage=event.resulting_stage,
                        source=event.source,
                    )
                    for event in events_by_docket[docket.id]
                    if event.event_kind in scope.event_kinds
                ],
                upcoming_dates=[
                    PortalIpDeadlineRecord(
                        id=deadline.id,
                        deadline_kind=deadline.deadline_kind,
                        title=deadline.title,
                        due_on=deadline.result_on.isoformat() if deadline.result_on else None,
                        due_at=deadline.result_at,
                        certainty=deadline.certainty,
                        state=deadline.state,
                    )
                    for deadline in deadlines_by_docket[docket.id]
                    if deadline.deadline_kind in scope.deadline_kinds
                ],
                grant_expires_at=grant.expires_at,
            )
        )
    return records


def list_portal_ip_records(
    session: Session, *, portal_user: PortalUser
) -> PortalIpRecordListResponse:
    rows = session.execute(
        _active_grant_statement(portal_user_id=portal_user.id)
        .join(
            IpDocketRecord,
            IpDocketRecord.id == MatterPortalGrant.ip_docket_record_id,
        )
        .add_columns(IpDocketRecord)
        .where(
            MatterPortalGrant.company_id == portal_user.company_id,
            IpDocketRecord.company_id == portal_user.company_id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
        )
        .order_by(MatterPortalGrant.granted_at.desc())
        .limit(50)
    ).all()
    return PortalIpRecordListResponse(records=_portal_records(session, rows=rows))


def get_portal_ip_record(
    session: Session, *, portal_user: PortalUser, docket_id: str
) -> PortalIpRecord:
    grant, docket = _portal_grant(session, portal_user=portal_user, docket_id=docket_id)
    return _portal_record(session, grant=grant, docket=docket)


def _publication_grants(
    session: Session,
    *,
    context: SessionContext,
    portal_user_id: str,
    grant_ids: list[str],
) -> tuple[PortalUser, list[tuple[MatterPortalGrant, IpDocketRecord]]]:
    user = session.scalar(
        select(PortalUser).where(
            PortalUser.id == portal_user_id,
            PortalUser.company_id == context.company.id,
            PortalUser.role == "client",
            PortalUser.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Client portal user not found.")
    rows = session.execute(
        select(MatterPortalGrant, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == MatterPortalGrant.ip_docket_record_id)
        .where(
            MatterPortalGrant.id.in_(grant_ids),
            MatterPortalGrant.company_id == context.company.id,
            MatterPortalGrant.portal_user_id == user.id,
            MatterPortalGrant.revoked_at.is_(None),
            or_(
                MatterPortalGrant.expires_at.is_(None),
                MatterPortalGrant.expires_at > _now(),
            ),
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
        )
        .order_by(MatterPortalGrant.id)
    ).all()
    if len(rows) != len(grant_ids):
        raise HTTPException(status_code=404, detail="Active IP portal grant not found.")
    for _grant, docket in rows:
        if not can_access_ip_docket(session, context=context, docket=docket):
            raise HTTPException(status_code=404, detail="IP record not found.")
    return user, list(rows)


def _safe_report_rows(
    *, report_kind: str, rows: list[dict], docket_ids: set[str]
) -> tuple[list[dict], list[str]]:
    selected = [row for row in rows if str(row.get("docket_id")) in docket_ids]
    safe: list[dict] = []
    excluded_fields: set[str] = set()
    for row in selected:
        if report_kind == "renewal":
            deadline = row.get("renewal_deadline") or {}
            grace = row.get("grace_deadline") or {}
            clean = {
                "docket_id": row.get("docket_id"),
                "docket_title": row.get("docket_title"),
                "primary_identifier": row.get("primary_identifier"),
                "record_type": row.get("record_type"),
                "reporting_state": row.get("reporting_state"),
                "renewal_due_on": deadline.get("result_on"),
                "grace_due_on": grace.get("result_on"),
                "calendar_phase": row.get("calendar_phase"),
                "action_required": row.get("action_required"),
            }
            excluded_fields.update(set(row) - set(clean))
        else:
            clean = {key: row.get(key) for key in _CLIENT_PORTFOLIO_FIELDS}
            excluded_fields.update(set(row) - set(_CLIENT_PORTFOLIO_FIELDS))
        safe.append(clean)
    return safe, sorted(excluded_fields)


def _snapshot_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _publication_status(scheduled_for: datetime | None) -> tuple[str, datetime | None]:
    now = _now()
    if scheduled_for is not None and _aware(scheduled_for) > now:
        return "scheduled", None
    return "published", now


def _enqueue_publication(
    session: Session,
    *,
    context: SessionContext,
    publication: PortalPublication,
    portal_user: PortalUser,
    first_docket: IpDocketRecord,
) -> NotificationDeliveryIntent | None:
    return enqueue_notification_delivery_intent(
        session,
        context=context,
        recipient_portal_user=portal_user,
        channel="email",
        event_type="portal_report_published",
        source_type="portal_publication",
        source_id=publication.id,
        ip_docket=first_docket,
        title="A client portal update is available",
        body="Open your CaseOps client portal to review the approved update.",
        scheduled_for=publication.scheduled_for,
        critical=True,
        escalation_membership=context.membership,
        schedule_source_type="portal_publication",
        schedule_source_id=publication.id,
    )


def publish_report_to_portal(
    session: Session,
    *,
    context: SessionContext,
    payload: PortalReportPublicationCreate,
) -> PortalPublicationRecord:
    if payload.report_kind not in _CLIENT_REPORT_KINDS:
        raise HTTPException(
            status_code=422,
            detail=(
                "This report contains firm-operational data and cannot be published "
                "to the client portal."
            ),
        )
    user, grant_rows = _publication_grants(
        session,
        context=context,
        portal_user_id=payload.portal_user_id,
        grant_ids=payload.grant_ids,
    )
    preview = preview_ip_report(
        session,
        context=context,
        payload=IpReportPreviewRequest(
            report_kind=payload.report_kind,
            filters=payload.filters,
            renewal_states=payload.renewal_states,
            row_limit=payload.row_limit,
        ),
    )
    if preview.snapshot_sha256 != payload.expected_snapshot_sha256:
        raise _conflict(
            "portal_report_preview_stale",
            "The report data changed; regenerate and review the preview before publishing.",
        )
    docket_ids = {docket.id for _grant, docket in grant_rows}
    safe_rows, excluded_fields = _safe_report_rows(
        report_kind=payload.report_kind,
        rows=preview.rows,
        docket_ids=docket_ids,
    )
    if not safe_rows:
        raise _conflict(
            "portal_report_has_no_granted_rows",
            "The reviewed report contains no rows covered by the selected portal grants.",
        )
    safe_summary = {
        "published_record_count": len(safe_rows),
        "report_kind": payload.report_kind,
    }
    snapshot = {
        "report_kind": payload.report_kind,
        "schema_version": preview.schema_version,
        "audience": "client_portal",
        "confidentiality": "client_shared",
        "filters": preview.filters,
        "freshness": preview.freshness.model_dump(mode="json"),
        "summary": safe_summary,
        "rows": safe_rows,
        "targets": sorted(docket_ids),
    }
    client_hash = _snapshot_hash(snapshot)
    artifact = session.scalar(
        select(ReportArtifact).where(
            ReportArtifact.company_id == context.company.id,
            ReportArtifact.snapshot_sha256 == client_hash,
        )
    )
    actor_label = _actor_label(context)
    if artifact is None:
        artifact = ReportArtifact(
            id=str(uuid4()),
            company_id=context.company.id,
            report_kind=payload.report_kind,
            schema_version=preview.schema_version,
            audience="client_portal",
            confidentiality="client_shared",
            filters_json=preview.filters,
            freshness_json=preview.freshness.model_dump(mode="json"),
            summary_json=safe_summary,
            rows_json=safe_rows,
            exclusions_json=[
                {"reason": "client_field_policy", "fields": excluded_fields},
                {"reason": "ungranted_targets_omitted_without_count"},
            ],
            source_versions_json={
                "internal_preview_snapshot_sha256": preview.snapshot_sha256,
                "target_versions": {
                    docket.id: {
                        "current_version": docket.current_version,
                        "lifecycle_version": docket.lifecycle_version,
                        "access_policy_version": docket.access_policy_version,
                    }
                    for _grant, docket in grant_rows
                },
            },
            row_count=len(safe_rows),
            truncated=preview.truncated,
            snapshot_sha256=client_hash,
            generated_at=preview.generated_at,
            generated_by_membership_id=context.membership.id,
            generated_by_label_snapshot=actor_label,
            approved_by_membership_id=context.membership.id,
            approved_by_label_snapshot=actor_label,
            approved_at=_now(),
        )
        session.add(artifact)
        session.flush()
    publication_status, published_at = _publication_status(payload.scheduled_for)
    publication = PortalPublication(
        id=str(uuid4()),
        company_id=context.company.id,
        portal_user_id=user.id,
        report_artifact_id=artifact.id,
        title=payload.title.strip(),
        status=publication_status,
        scheduled_for=payload.scheduled_for,
        published_at=published_at,
        approved_by_membership_id=context.membership.id,
        approved_by_label_snapshot=actor_label,
        approved_at=_now(),
    )
    session.add(publication)
    session.flush()
    for grant, docket in grant_rows:
        session.add(
            PortalPublicationTarget(
                id=str(uuid4()),
                company_id=context.company.id,
                publication_id=publication.id,
                portal_grant_id=grant.id,
                ip_docket_record_id=docket.id,
                docket_version=docket.current_version,
                lifecycle_version=docket.lifecycle_version,
                access_policy_version=docket.access_policy_version,
            )
        )
    intent = _enqueue_publication(
        session,
        context=context,
        publication=publication,
        portal_user=user,
        first_docket=grant_rows[0][1],
    )
    publication.delivery_intent_id = intent.id if intent is not None else None
    record_from_context(
        session,
        context,
        action="portal.report.published",
        target_type="portal_publication",
        target_id=publication.id,
        ip_docket_id=grant_rows[0][1].id,
        metadata={
            "portal_user_id": user.id,
            "grant_ids": payload.grant_ids,
            "report_artifact_id": artifact.id,
            "snapshot_sha256": artifact.snapshot_sha256,
            "excluded_fields": excluded_fields,
            "delivery_intent_id": publication.delivery_intent_id,
            "scheduled_for": (payload.scheduled_for.isoformat() if payload.scheduled_for else None),
        },
    )
    session.commit()
    return _publication_record(session, publication=publication, portal_user=user)


def _document_docket_id(session: Session, *, link: IpDocumentLink) -> str | None:
    if link.docket_id:
        return link.docket_id
    model_and_id = (
        (TrademarkApplication, link.application_id)
        if link.application_id
        else (IpProceeding, link.proceeding_id)
        if link.proceeding_id
        else (IpDocketEvent, link.event_id)
        if link.event_id
        else (IpDeadline, link.deadline_id)
        if link.deadline_id
        else (None, None)
    )
    model, target_id = model_and_id
    if model is None or target_id is None:
        return None
    row = session.get(model, target_id)
    return str(row.docket_id) if row is not None else None


def publish_document_to_portal(
    session: Session,
    *,
    context: SessionContext,
    payload: PortalDocumentPublicationCreate,
) -> PortalPublicationRecord:
    user, grant_rows = _publication_grants(
        session,
        context=context,
        portal_user_id=payload.portal_user_id,
        grant_ids=[payload.grant_id],
    )
    grant, docket = grant_rows[0]
    scope = _scope(grant)
    row = session.execute(
        select(IpDocument, IpDocumentVersion, IpDocumentTaxonomyEntry)
        .join(IpDocumentVersion, IpDocumentVersion.document_id == IpDocument.id)
        .join(
            IpDocumentTaxonomyEntry,
            IpDocumentTaxonomyEntry.id == IpDocument.taxonomy_entry_id,
        )
        .where(
            IpDocument.id == payload.document_id,
            IpDocument.company_id == context.company.id,
            IpDocumentVersion.version == payload.version_number,
            IpDocumentVersion.company_id == context.company.id,
            IpDocumentTaxonomyEntry.company_id == context.company.id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Approved IP document not found.")
    document, version, taxonomy = row
    if (
        document.is_privileged
        or document.confidentiality != "internal"
        or version.state not in {"approved", "filed", "served", "accepted"}
    ):
        raise _conflict(
            "portal_document_not_shareable",
            "Only an approved, non-privileged internal document version may be shared.",
        )
    if taxonomy.key.lower() not in scope.document_categories:
        raise _conflict(
            "portal_document_category_not_granted",
            "This document category is not enabled on the selected portal grant.",
        )
    links = list(
        session.scalars(
            select(IpDocumentLink).where(
                IpDocumentLink.company_id == context.company.id,
                IpDocumentLink.document_id == document.id,
                or_(IpDocumentLink.version_id.is_(None), IpDocumentLink.version_id == version.id),
            )
        )
    )
    if docket.id not in {
        resolved for link in links if (resolved := _document_docket_id(session, link=link))
    }:
        raise HTTPException(status_code=404, detail="Approved IP document not found.")
    actor_label = _actor_label(context)
    publication_status, published_at = _publication_status(payload.scheduled_for)
    publication = PortalPublication(
        id=str(uuid4()),
        company_id=context.company.id,
        portal_user_id=user.id,
        document_version_id=version.id,
        title=payload.title.strip(),
        status=publication_status,
        scheduled_for=payload.scheduled_for,
        published_at=published_at,
        approved_by_membership_id=context.membership.id,
        approved_by_label_snapshot=actor_label,
        approved_at=_now(),
    )
    session.add(publication)
    session.flush()
    session.add(
        PortalPublicationTarget(
            id=str(uuid4()),
            company_id=context.company.id,
            publication_id=publication.id,
            portal_grant_id=grant.id,
            ip_docket_record_id=docket.id,
            docket_version=docket.current_version,
            lifecycle_version=docket.lifecycle_version,
            access_policy_version=docket.access_policy_version,
        )
    )
    intent = _enqueue_publication(
        session,
        context=context,
        publication=publication,
        portal_user=user,
        first_docket=docket,
    )
    publication.delivery_intent_id = intent.id if intent is not None else None
    record_from_context(
        session,
        context,
        action="portal.document.published",
        target_type="portal_publication",
        target_id=publication.id,
        ip_docket_id=docket.id,
        metadata={
            "portal_user_id": user.id,
            "portal_grant_id": grant.id,
            "document_id": document.id,
            "document_version_id": version.id,
            "document_sha256": version.sha256_hex,
            "delivery_intent_id": publication.delivery_intent_id,
        },
    )
    session.commit()
    return _publication_record(session, publication=publication, portal_user=user)


def _publication_targets(
    session: Session, *, publication: PortalPublication
) -> list[PortalPublicationTargetRecord]:
    rows = session.execute(
        select(PortalPublicationTarget, MatterPortalGrant, IpDocketRecord)
        .join(MatterPortalGrant, MatterPortalGrant.id == PortalPublicationTarget.portal_grant_id)
        .join(IpDocketRecord, IpDocketRecord.id == PortalPublicationTarget.ip_docket_record_id)
        .where(
            PortalPublicationTarget.company_id == publication.company_id,
            PortalPublicationTarget.publication_id == publication.id,
        )
        .order_by(IpDocketRecord.title, IpDocketRecord.id)
    ).all()
    now = _now()
    return [
        PortalPublicationTargetRecord(
            ip_docket_record_id=docket.id,
            docket_title=docket.title,
            current=bool(
                _grant_is_active(grant, now=now)
                and docket.is_active
                and not docket.archived_by_matter_disposal
                and docket.current_version == target.docket_version
                and docket.lifecycle_version == target.lifecycle_version
                and docket.access_policy_version == target.access_policy_version
            ),
        )
        for target, grant, docket in rows
    ]


def _publication_targets_for_ids(
    session: Session,
    *,
    company_id: str,
    publication_ids: list[str],
) -> dict[str, list[PortalPublicationTargetRecord]]:
    grouped: dict[str, list[PortalPublicationTargetRecord]] = defaultdict(list)
    if not publication_ids:
        return grouped
    rows = session.execute(
        select(PortalPublicationTarget, MatterPortalGrant, IpDocketRecord)
        .join(MatterPortalGrant, MatterPortalGrant.id == PortalPublicationTarget.portal_grant_id)
        .join(IpDocketRecord, IpDocketRecord.id == PortalPublicationTarget.ip_docket_record_id)
        .where(
            PortalPublicationTarget.company_id == company_id,
            PortalPublicationTarget.publication_id.in_(publication_ids),
        )
        .order_by(
            PortalPublicationTarget.publication_id,
            IpDocketRecord.title,
            IpDocketRecord.id,
        )
        .limit(len(publication_ids) * 50)
    ).all()
    now = _now()
    for target, grant, docket in rows:
        grouped[target.publication_id].append(
            PortalPublicationTargetRecord(
                ip_docket_record_id=docket.id,
                docket_title=docket.title,
                current=bool(
                    _grant_is_active(grant, now=now)
                    and docket.is_active
                    and not docket.archived_by_matter_disposal
                    and docket.current_version == target.docket_version
                    and docket.lifecycle_version == target.lifecycle_version
                    and docket.access_policy_version == target.access_policy_version
                ),
            )
        )
    return grouped


def _publication_record(
    session: Session,
    *,
    publication: PortalPublication,
    portal_user: PortalUser,
    record_access: bool = False,
    dependencies_loaded: bool = False,
    loaded_targets: list[PortalPublicationTargetRecord] | None = None,
    loaded_artifact: ReportArtifact | None = None,
    loaded_version: IpDocumentVersion | None = None,
    loaded_intent: NotificationDeliveryIntent | None = None,
) -> PortalPublicationRecord:
    if publication.portal_user_id != portal_user.id:
        raise HTTPException(status_code=404, detail="Publication not found.")
    targets = (
        loaded_targets or []
        if dependencies_loaded
        else _publication_targets(session, publication=publication)
    )
    now = _now()
    scheduled = bool(
        publication.status == "scheduled"
        and publication.scheduled_for is not None
        and _aware(publication.scheduled_for) > now
    )
    current = bool(targets) and all(target.current for target in targets)
    access_state = (
        "revoked"
        if publication.status == "revoked"
        else "scheduled"
        if scheduled
        else "available"
        if current
        else "review_required"
    )
    artifact = (
        loaded_artifact
        if dependencies_loaded
        else (
            session.get(ReportArtifact, publication.report_artifact_id)
            if publication.report_artifact_id
            else None
        )
    )
    version = (
        loaded_version
        if dependencies_loaded
        else (
            session.get(IpDocumentVersion, publication.document_version_id)
            if publication.document_version_id
            else None
        )
    )
    intent = (
        loaded_intent
        if dependencies_loaded
        else (
            session.get(NotificationDeliveryIntent, publication.delivery_intent_id)
            if publication.delivery_intent_id
            else None
        )
    )
    visible = access_state == "available"
    if record_access and visible:
        publication.access_count += 1
        publication.last_accessed_at = now
        record_audit(
            session,
            company_id=portal_user.company_id,
            actor_type=AuditActorType.SYSTEM,
            actor_label=f"portal:{portal_user.email}",
            action="portal.publication.opened",
            target_type="portal_publication",
            target_id=publication.id,
            result=AuditResult.SUCCESS,
            metadata={"portal_user_id": portal_user.id},
            commit=True,
        )
    return PortalPublicationRecord(
        id=publication.id,
        publication_kind="report" if artifact else "document",
        title=publication.title,
        status=publication.status,
        access_state=access_state,
        scheduled_for=publication.scheduled_for,
        published_at=publication.published_at
        or (publication.scheduled_for if not scheduled else None),
        delivery_status=str(intent.status) if intent else None,
        delivery_error=intent.dead_letter_reason if intent else None,
        report_kind=artifact.report_kind if artifact and visible else None,
        schema_version=artifact.schema_version if artifact and visible else None,
        generated_at=artifact.generated_at if artifact and visible else None,
        freshness=artifact.freshness_json if artifact and visible else None,
        summary=artifact.summary_json if artifact and visible else None,
        rows=artifact.rows_json if artifact and visible else None,
        document_id=version.document_id if version and visible else None,
        document_version=version.version if version and visible else None,
        document_filename=version.display_name if version and visible else None,
        targets=targets,
        accessed_at=publication.last_accessed_at,
    )


def list_portal_publications(
    session: Session, *, portal_user: PortalUser
) -> PortalPublicationListResponse:
    rows = list(
        session.scalars(
            select(PortalPublication)
            .where(
                PortalPublication.company_id == portal_user.company_id,
                PortalPublication.portal_user_id == portal_user.id,
                PortalPublication.status != "revoked",
            )
            .order_by(PortalPublication.approved_at.desc())
            .limit(50)
        )
    )
    publication_ids = [row.id for row in rows]
    targets_by_publication = _publication_targets_for_ids(
        session,
        company_id=portal_user.company_id,
        publication_ids=publication_ids,
    )
    artifact_ids = [row.report_artifact_id for row in rows if row.report_artifact_id]
    artifacts = {
        row.id: row
        for row in session.scalars(
            select(ReportArtifact).where(
                ReportArtifact.company_id == portal_user.company_id,
                ReportArtifact.id.in_(artifact_ids),
            )
        )
    }
    version_ids = [row.document_version_id for row in rows if row.document_version_id]
    versions = {
        row.id: row
        for row in session.scalars(
            select(IpDocumentVersion).where(
                IpDocumentVersion.company_id == portal_user.company_id,
                IpDocumentVersion.id.in_(version_ids),
            )
        )
    }
    intent_ids = [row.delivery_intent_id for row in rows if row.delivery_intent_id]
    intents = {
        row.id: row
        for row in session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == portal_user.company_id,
                NotificationDeliveryIntent.id.in_(intent_ids),
            )
        )
    }
    return PortalPublicationListResponse(
        publications=[
            _publication_record(
                session,
                publication=row,
                portal_user=portal_user,
                dependencies_loaded=True,
                loaded_targets=targets_by_publication[row.id],
                loaded_artifact=artifacts.get(row.report_artifact_id),
                loaded_version=versions.get(row.document_version_id),
                loaded_intent=intents.get(row.delivery_intent_id),
            )
            for row in rows
        ]
    )


def get_portal_publication(
    session: Session, *, portal_user: PortalUser, publication_id: str
) -> PortalPublicationRecord:
    publication = session.scalar(
        select(PortalPublication).where(
            PortalPublication.id == publication_id,
            PortalPublication.company_id == portal_user.company_id,
            PortalPublication.portal_user_id == portal_user.id,
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    return _publication_record(
        session, publication=publication, portal_user=portal_user, record_access=True
    )


def portal_document_download(
    session: Session,
    *,
    portal_user: PortalUser,
    publication_id: str,
) -> IpDocumentVersion:
    publication = session.scalar(
        select(PortalPublication).where(
            PortalPublication.id == publication_id,
            PortalPublication.company_id == portal_user.company_id,
            PortalPublication.portal_user_id == portal_user.id,
            PortalPublication.document_version_id.is_not(None),
        )
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    record = _publication_record(
        session, publication=publication, portal_user=portal_user, record_access=True
    )
    if record.access_state != "available" or publication.document_version_id is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    version = session.get(IpDocumentVersion, publication.document_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    return version


def submit_portal_instruction(
    session: Session,
    *,
    portal_user: PortalUser,
    publication_id: str,
    payload: PortalInstructionSubmitRequest,
) -> PortalInstructionRecord:
    publication = session.scalar(
        select(PortalPublication)
        .where(
            PortalPublication.id == publication_id,
            PortalPublication.company_id == portal_user.company_id,
            PortalPublication.portal_user_id == portal_user.id,
        )
        .with_for_update(of=PortalPublication)
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found.")
    publication_record = _publication_record(
        session, publication=publication, portal_user=portal_user
    )
    if publication_record.access_state != "available":
        raise _conflict(
            "portal_publication_not_current",
            "The publication is no longer current; ask the firm to review and republish it.",
        )
    target_ids = [target.ip_docket_record_id for target in publication_record.targets]
    docket_id = payload.docket_id or (target_ids[0] if len(target_ids) == 1 else None)
    if docket_id is None or docket_id not in target_ids:
        raise HTTPException(
            status_code=422,
            detail="Select one granted IP record for this instruction.",
        )
    grant, docket = _portal_grant(session, portal_user=portal_user, docket_id=docket_id, lock=True)
    if not _scope(grant).can_submit_instructions:
        raise HTTPException(status_code=403, detail="Instructions are disabled for this grant.")
    thread_key = f"portal:{publication.id}:{docket.id}"
    current = session.scalar(
        select(IpClientInstruction)
        .where(
            IpClientInstruction.company_id == portal_user.company_id,
            IpClientInstruction.instruction_thread_key == thread_key,
            IpClientInstruction.status != "superseded",
        )
        .order_by(IpClientInstruction.instruction_version.desc())
        .with_for_update(of=IpClientInstruction)
    )
    if current is None:
        if payload.expected_current_instruction_id is not None:
            raise _conflict(
                "portal_instruction_stale",
                "No current instruction exists; refresh before submitting.",
            )
        instruction_version = 1
    else:
        if (
            payload.expected_current_instruction_id != current.id
            or payload.expected_current_row_version != current.row_version
        ):
            raise _conflict(
                "portal_instruction_stale",
                "The instruction changed; refresh before submitting a revision.",
            )
        current.status = "superseded"
        current.row_version += 1
        current.updated_at = _now()
        instruction_version = current.instruction_version + 1
    renewal_term = None
    if payload.instruction_kind == "renewal":
        renewal_term = session.scalar(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.company_id == portal_user.company_id,
                IpRenewalTerm.docket_id == docket.id,
                IpRenewalTerm.state.not_in(("completed", "cancelled")),
            )
            .order_by(IpRenewalTerm.term_sequence.desc())
            .limit(1)
        )
        if renewal_term is None:
            raise _conflict(
                "portal_renewal_term_required",
                "No active renewal term is available for this instruction.",
            )
    now = _now()
    instruction = IpClientInstruction(
        id=str(uuid4()),
        company_id=portal_user.company_id,
        docket_id=docket.id,
        renewal_term_id=renewal_term.id if renewal_term else None,
        instruction_thread_key=thread_key,
        instruction_kind=payload.instruction_kind,
        instruction_version=instruction_version,
        row_version=1,
        decision=payload.decision,
        status="pending",
        scope_json={"note": payload.note, "publication_id": publication.id},
        options_json=[],
        instruction_deadline_at=None,
        source_channel="client_portal",
        source_communication_id=None,
        source_portal_user_id=portal_user.id,
        source_portal_grant_id=grant.id,
        portal_publication_id=publication.id,
        authority_name=portal_user.full_name,
        authority_reference=portal_user.email,
        evidence_refs_json=[f"portal_publication:{publication.id}"],
        received_at=now,
        supersedes_instruction_id=current.id if current else None,
        created_by_membership_id=None,
        creator_label_snapshot=f"portal:{portal_user.email}"[:255],
    )
    session.add(instruction)
    session.flush()
    if renewal_term is not None:
        cancel_pending_notification_intents(
            session,
            company_id=portal_user.company_id,
            schedule_source_type="ip_renewal_term",
            schedule_source_id=renewal_term.id,
            cancellation_reason="portal_instruction_received",
        )
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        action="portal.client_instruction.submitted",
        target_type="ip_client_instruction",
        target_id=instruction.id,
        result=AuditResult.SUCCESS,
        metadata={
            "portal_user_id": portal_user.id,
            "portal_publication_id": publication.id,
            "ip_docket_id": docket.id,
            "decision": instruction.decision,
            "instruction_version": instruction.instruction_version,
        },
        commit=True,
    )
    return _instruction_record(session, instruction=instruction, docket=docket)


def _instruction_record(
    session: Session,
    *,
    instruction: IpClientInstruction,
    docket: IpDocketRecord | None = None,
) -> PortalInstructionRecord:
    docket = docket or session.get(IpDocketRecord, instruction.docket_id)
    if docket is None or instruction.portal_publication_id is None:
        raise ValueError("Portal instruction target is incomplete.")
    return PortalInstructionRecord(
        id=instruction.id,
        docket_id=docket.id,
        docket_title=docket.title,
        publication_id=instruction.portal_publication_id,
        instruction_version=instruction.instruction_version,
        row_version=instruction.row_version,
        instruction_kind=instruction.instruction_kind,
        decision=instruction.decision,
        status=instruction.status,
        note=str((instruction.scope_json or {}).get("note") or ""),
        submitted_by=instruction.creator_label_snapshot,
        received_at=instruction.received_at,
        acknowledged_at=instruction.acknowledged_at,
        acknowledgement_reason=instruction.acknowledgement_reason,
        resulting_event_id=instruction.resulting_event_id,
        updated_at=instruction.updated_at,
    )


def list_firm_portal_instructions(
    session: Session, *, context: SessionContext
) -> PortalInstructionListResponse:
    rows = session.execute(
        select(IpClientInstruction, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == IpClientInstruction.docket_id)
        .where(
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.source_portal_user_id.is_not(None),
            IpClientInstruction.status != "superseded",
            IpDocketRecord.company_id == context.company.id,
        )
        .order_by(IpClientInstruction.received_at.desc())
        .limit(200)
    ).all()
    return PortalInstructionListResponse(
        instructions=[
            _instruction_record(session, instruction=instruction, docket=docket)
            for instruction, docket in rows
            if can_access_ip_docket(session, context=context, docket=docket)
        ]
    )


def acknowledge_portal_instruction(
    session: Session,
    *,
    context: SessionContext,
    instruction_id: str,
    payload: PortalInstructionAcknowledgeRequest,
) -> PortalInstructionRecord:
    row = session.execute(
        select(IpClientInstruction, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == IpClientInstruction.docket_id)
        .where(
            IpClientInstruction.id == instruction_id,
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.source_portal_user_id.is_not(None),
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpClientInstruction)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Client instruction not found.")
    instruction, docket = row
    if not can_access_ip_docket(session, context=context, docket=docket):
        raise HTTPException(status_code=404, detail="Client instruction not found.")
    if (
        instruction.status != payload.expected_status
        or instruction.row_version != payload.expected_row_version
    ):
        raise _conflict(
            "portal_instruction_stale",
            "The client instruction changed; refresh before acknowledging it.",
        )
    if payload.resulting_event_id:
        event = session.scalar(
            select(IpDocketEvent).where(
                IpDocketEvent.id == payload.resulting_event_id,
                IpDocketEvent.company_id == context.company.id,
                IpDocketEvent.docket_id == docket.id,
                IpDocketEvent.event_kind == "client_instruction",
                IpDocketEvent.candidate_status == "confirmed",
            )
        )
        if event is None:
            raise HTTPException(status_code=404, detail="Resulting instruction event not found.")
    now = _now()
    instruction.status = payload.status
    instruction.row_version += 1
    instruction.acknowledged_at = now
    instruction.acknowledged_by_membership_id = context.membership.id
    instruction.acknowledgement_reason = payload.reason.strip()
    instruction.resulting_event_id = payload.resulting_event_id
    instruction.updated_at = now
    if (
        payload.status == "accepted"
        and instruction.decision == "renew"
        and instruction.renewal_term_id is not None
    ):
        term = session.scalar(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.id == instruction.renewal_term_id,
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id == docket.id,
            )
            .with_for_update(of=IpRenewalTerm)
        )
        if term is not None and term.state == "due":
            term.state = "instructed"
            term.version += 1
            term.updated_by_membership_id = context.membership.id
            term.updated_at = now
    record_from_context(
        session,
        context,
        action=f"portal.client_instruction.{payload.status}",
        target_type="ip_client_instruction",
        target_id=instruction.id,
        ip_docket_id=docket.id,
        metadata={
            "portal_publication_id": instruction.portal_publication_id,
            "decision": instruction.decision,
            "resulting_event_id": instruction.resulting_event_id,
            "row_version": instruction.row_version,
        },
    )
    session.commit()
    return _instruction_record(session, instruction=instruction, docket=docket)


__all__ = [
    "acknowledge_portal_instruction",
    "get_portal_ip_record",
    "get_portal_publication",
    "list_admin_ip_grants",
    "list_firm_portal_instructions",
    "list_portal_ip_records",
    "list_portal_publications",
    "portal_document_download",
    "publish_document_to_portal",
    "publish_report_to_portal",
    "revoke_ip_grant",
    "submit_portal_instruction",
]
