"""Canonical IPLF-051 registry reconciliation and court-reference service."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpIdentifier,
    IpPartyAndRole,
    IpProceeding,
    IpRegistryDiff,
    IpRegistryLink,
    IpRegistrySnapshot,
    IpRegistrySyncAttempt,
    IpTrackedCaseLink,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCaseUpdate,
    TrademarkApplication,
)
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest
from caseops_api.schemas.ip_registry import (
    IpRegistryDiffResponse,
    IpRegistryLinkResponse,
    IpRegistrySnapshotResponse,
    IpRegistrySnapshotResult,
    IpRegistrySyncAttemptResponse,
    IpRegistryWorkspaceResponse,
    IpTrackedCaseReferenceResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier
from caseops_api.services.ip_lifecycle import append_ip_docket_event
from caseops_api.services.ip_operations import _docket_or_404, _lock_ip_writer_context
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.provider_adapter_catalog import provider_adapter_definition
from caseops_api.services.session_context import SessionContext

if TYPE_CHECKING:
    from caseops_api.schemas.ip_registry import (
        IpRegistryDiffResolveRequest,
        IpRegistryFailureRequest,
        IpRegistryLinkCreateRequest,
        IpRegistryLinkMatchDecisionRequest,
        IpRegistryManualSnapshotRequest,
        IpTrackedCaseLinkCreateRequest,
        IpTrackedCaseLinkDecisionRequest,
    )


REGISTRY_DIFF_POLICY_VERSION = "ip-registry-diff-risk-v1"
MAX_SNAPSHOT_BYTES = 1_000_000
_HIGH_RISK_TOKENS = {
    "applicant",
    "cancellation",
    "cancelled",
    "deadline",
    "due_date",
    "hearing_date",
    "opposition",
    "owner",
    "proprietor",
    "refusal",
    "refused",
    "registration_date",
    "renewal_date",
    "status",
}
_DEADLINE_TOKENS = {
    "deadline",
    "due_date",
    "hearing_date",
    "opposition_date",
    "publication_date",
    "refusal_date",
    "registration_date",
    "renewal_date",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _assert_snapshot_size(*values: object) -> None:
    for value in values:
        if len(_canonical_json(value).encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Registry snapshot exceeds the one-megabyte evidence limit.",
            )


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _flatten(value: object, *, path: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        if not value:
            return {path or "/": {}}
        flattened: dict[str, object] = {}
        for key in sorted(value):
            child = f"{path}/{_pointer_segment(str(key))}"
            flattened.update(_flatten(value[key], path=child))
        return flattened
    return {path or "/": value}


def _unescape_pointer(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _set_pointer(document: dict[str, Any], path: str, value: object) -> dict[str, Any]:
    result = copy.deepcopy(document)
    segments = [_unescape_pointer(item) for item in path.split("/")[1:]]
    if not segments:
        if not isinstance(value, dict):
            raise HTTPException(status_code=422, detail="Registry root mapping must be an object.")
        return copy.deepcopy(value)
    cursor: dict[str, Any] = result
    for segment in segments[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    cursor[segments[-1]] = copy.deepcopy(value)
    return result


def _remove_pointer(document: dict[str, Any], path: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    segments = [_unescape_pointer(item) for item in path.split("/")[1:]]
    if not segments:
        return {}
    cursor: dict[str, Any] = result
    for segment in segments[:-1]:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            return result
        cursor = child
    cursor.pop(segments[-1], None)
    return result


def _risk(field_path: str) -> tuple[str, list[str], str]:
    normalized = field_path.casefold().replace("-", "_")
    high = sorted(token for token in _HIGH_RISK_TOKENS if token in normalized)
    deadline = sorted(token for token in _DEADLINE_TOKENS if token in normalized)
    reasons = [f"high_risk_field:{token}" for token in high]
    if deadline:
        reasons.append("deadline_recalculation_required")
    return (
        "high" if reasons else "low",
        reasons,
        "required" if deadline else "not_applicable",
    )


def _target_state(
    session: Session,
    *,
    company_id: str,
    docket_id: str,
    application_id: str | None,
    proceeding_id: str | None,
) -> dict[str, Any]:
    identifiers = list(
        session.scalars(
            select(IpIdentifier)
            .where(
                IpIdentifier.company_id == company_id,
                IpIdentifier.docket_id == docket_id,
                IpIdentifier.effective_until.is_(None),
            )
            .order_by(IpIdentifier.identifier_kind, IpIdentifier.normalized_value)
        ).all()
    )
    parties = list(
        session.scalars(
            select(IpPartyAndRole)
            .where(
                IpPartyAndRole.company_id == company_id,
                IpPartyAndRole.docket_id == docket_id,
                IpPartyAndRole.effective_until.is_(None),
                (
                    IpPartyAndRole.proceeding_id == proceeding_id
                    if proceeding_id
                    else IpPartyAndRole.proceeding_id.is_(None)
                ),
            )
            .order_by(IpPartyAndRole.role_kind, IpPartyAndRole.party_name)
        ).all()
    )
    state: dict[str, Any] = {
        "identifiers": {
            row.identifier_kind: row.raw_value
            for row in identifiers
            if (application_id and row.application_id == application_id)
            or (proceeding_id and row.proceeding_id == proceeding_id)
        },
        "parties": [{"name": row.party_name, "role": row.role_kind} for row in parties],
    }
    if application_id:
        target = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == application_id,
                TrademarkApplication.company_id == company_id,
                TrademarkApplication.docket_id == docket_id,
            )
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Trademark application not found.")
        state.update(
            {
                "office": target.office,
                "jurisdiction": target.jurisdiction,
                "status": target.filing_phase,
            }
        )
    else:
        target = session.scalar(
            select(IpProceeding).where(
                IpProceeding.id == proceeding_id,
                IpProceeding.company_id == company_id,
                IpProceeding.docket_id == docket_id,
            )
        )
        if target is None:
            raise HTTPException(status_code=404, detail="IP proceeding not found.")
        state.update(
            {
                "office": target.office,
                "jurisdiction": target.jurisdiction,
                "status": target.stage,
            }
        )
    return state


def _link_or_404(
    session: Session,
    *,
    context: SessionContext,
    link_id: str,
    for_update: bool = False,
) -> IpRegistryLink:
    statement = select(IpRegistryLink).where(
        IpRegistryLink.id == link_id,
        IpRegistryLink.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="IP registry link not found.")
    _docket_or_404(
        session,
        context=context,
        docket_id=row.docket_id,
        for_update=for_update,
    )
    return row


def create_registry_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpRegistryLinkCreateRequest,
) -> IpRegistryLink:
    locked_context = _lock_ip_writer_context(
        session,
        context=context,
        required_capability="ip:registry_sync",
    )
    docket = _docket_or_404(
        session,
        context=locked_context,
        docket_id=docket_id,
        for_update=True,
    )
    adapter = provider_adapter_definition(payload.provider_key)
    if adapter is None or adapter.domain != "ip_office_registry":
        raise HTTPException(status_code=422, detail="Choose a registered IP-office adapter.")
    normalized = normalize_ip_identifier(payload.raw_identifier)
    existing = session.scalar(
        select(IpRegistryLink).where(
            IpRegistryLink.company_id == locked_context.company.id,
            IpRegistryLink.docket_id == docket.id,
            IpRegistryLink.provider_key == adapter.provider,
            IpRegistryLink.office == payload.office,
            IpRegistryLink.jurisdiction == payload.jurisdiction,
            IpRegistryLink.identifier_kind == payload.identifier_kind,
            IpRegistryLink.normalized_identifier == normalized,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This registry identity is already linked.")
    accepted_state = _target_state(
        session,
        company_id=locked_context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
    )
    row = IpRegistryLink(
        company_id=locked_context.company.id,
        docket_id=docket.id,
        application_id=payload.application_id,
        proceeding_id=payload.proceeding_id,
        provider_key=adapter.provider,
        office=payload.office,
        jurisdiction=payload.jurisdiction,
        identifier_kind=payload.identifier_kind,
        raw_identifier=payload.raw_identifier.strip(),
        normalized_identifier=normalized,
        source_url=payload.source_url,
        match_confidence=payload.match_confidence,
        match_evidence_json=payload.match_evidence,
        accepted_state_json=accepted_state,
        terms_version=payload.terms_version,
        capability_version=payload.capability_version,
        created_by_membership_id=locked_context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        locked_context,
        action="ip_registry.link_created",
        target_type="ip_registry_link",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "provider_key": adapter.provider,
            "office": row.office,
            "jurisdiction": row.jurisdiction,
            "identifier_kind": row.identifier_kind,
            "match_confidence": str(row.match_confidence),
            "external_call": False,
        },
    )
    session.commit()
    session.refresh(row)
    return row


def decide_registry_match(
    session: Session,
    *,
    context: SessionContext,
    link_id: str,
    payload: IpRegistryLinkMatchDecisionRequest,
) -> IpRegistryLink:
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    link = _link_or_404(session, context=locked_context, link_id=link_id, for_update=True)
    if link.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Registry link changed; reload.")
    if link.match_status == "retired":
        raise HTTPException(status_code=409, detail="A retired registry link cannot be changed.")
    next_status = {
        "confirm": "confirmed",
        "mismatch": "mismatch",
        "retire": "retired",
    }[payload.decision]
    link.match_status = next_status
    link.version += 1
    link.updated_at = _now()
    record_from_context(
        session,
        locked_context,
        action=f"ip_registry.link_{payload.decision}",
        target_type="ip_registry_link",
        target_id=link.id,
        ip_docket_id=link.docket_id,
        metadata={"reason": payload.reason, "match_status": next_status},
    )
    session.commit()
    session.refresh(link)
    return link


def _attempt_by_key(
    session: Session,
    *,
    company_id: str,
    link_id: str,
    idempotency_key: str,
) -> IpRegistrySyncAttempt | None:
    return session.scalar(
        select(IpRegistrySyncAttempt).where(
            IpRegistrySyncAttempt.company_id == company_id,
            IpRegistrySyncAttempt.link_id == link_id,
            IpRegistrySyncAttempt.idempotency_key == idempotency_key,
        )
    )


def _existing_snapshot_result(
    session: Session,
    *,
    link: IpRegistryLink,
    attempt: IpRegistrySyncAttempt,
) -> IpRegistrySnapshotResult:
    snapshot = session.scalar(
        select(IpRegistrySnapshot).where(
            IpRegistrySnapshot.attempt_id == attempt.id,
            IpRegistrySnapshot.company_id == attempt.company_id,
        )
    )
    diffs = (
        list(
            session.scalars(
                select(IpRegistryDiff)
                .where(
                    IpRegistryDiff.snapshot_id == snapshot.id,
                    IpRegistryDiff.company_id == attempt.company_id,
                )
                .order_by(IpRegistryDiff.field_path)
            ).all()
        )
        if snapshot
        else []
    )
    return IpRegistrySnapshotResult(
        link=IpRegistryLinkResponse.model_validate(link),
        attempt=IpRegistrySyncAttemptResponse.model_validate(attempt),
        snapshot=(IpRegistrySnapshotResponse.model_validate(snapshot) if snapshot else None),
        diffs=[IpRegistryDiffResponse.model_validate(row) for row in diffs],
        no_change=attempt.status == "no_change",
        idempotent_replay=True,
    )


def _assert_idempotent_payload(
    attempt: IpRegistrySyncAttempt,
    *,
    request_fingerprint: str,
) -> None:
    if attempt.metadata_json.get("request_fingerprint") != request_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used with a different registry request.",
        )


def record_manual_snapshot(
    session: Session,
    *,
    context: SessionContext,
    link_id: str,
    payload: IpRegistryManualSnapshotRequest,
) -> IpRegistrySnapshotResult:
    _assert_snapshot_size(payload.raw_snapshot, payload.normalized_snapshot)
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    discovered = _link_or_404(session, context=locked_context, link_id=link_id)
    _docket_or_404(
        session,
        context=locked_context,
        docket_id=discovered.docket_id,
        for_update=True,
    )
    link = session.scalar(
        select(IpRegistryLink)
        .where(
            IpRegistryLink.id == link_id,
            IpRegistryLink.company_id == locked_context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert link is not None
    request_fingerprint = _hash(
        {
            "operation_kind": "manual_snapshot",
            "source_url": payload.source_url,
            "source_retrieved_at": payload.source_retrieved_at.isoformat(),
            "parser_version": payload.parser_version,
            "schema_version": payload.schema_version,
            "attribution": payload.attribution,
            "raw_snapshot": payload.raw_snapshot,
            "normalized_snapshot": payload.normalized_snapshot,
            "supersedes_snapshot_id": payload.supersedes_snapshot_id,
            "correction_reason": payload.correction_reason,
        }
    )
    existing = _attempt_by_key(
        session,
        company_id=locked_context.company.id,
        link_id=link.id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_payload(existing, request_fingerprint=request_fingerprint)
        return _existing_snapshot_result(session, link=link, attempt=existing)
    if link.version != payload.expected_link_version:
        raise HTTPException(status_code=409, detail="Registry link changed; reload.")
    if link.match_status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Confirm the registry match before adding a candidate snapshot.",
        )
    if payload.supersedes_snapshot_id:
        predecessor = session.scalar(
            select(IpRegistrySnapshot).where(
                IpRegistrySnapshot.id == payload.supersedes_snapshot_id,
                IpRegistrySnapshot.company_id == locked_context.company.id,
                IpRegistrySnapshot.link_id == link.id,
            )
        )
        if predecessor is None:
            raise HTTPException(status_code=404, detail="Superseded snapshot not found.")
        successor_exists = session.scalar(
            select(IpRegistrySnapshot.id).where(
                IpRegistrySnapshot.company_id == locked_context.company.id,
                IpRegistrySnapshot.supersedes_snapshot_id == predecessor.id,
            )
        )
        if successor_exists is not None:
            raise HTTPException(
                status_code=409,
                detail="This registry snapshot already has a correction successor.",
            )
    raw_hash = _hash(payload.raw_snapshot)
    normalized_hash = _hash(payload.normalized_snapshot)
    now = _now()
    correlation = sha256(
        f"{locked_context.company.id}:{link.id}:{payload.idempotency_key}".encode()
    ).hexdigest()
    attempt = IpRegistrySyncAttempt(
        company_id=locked_context.company.id,
        link_id=link.id,
        provider_key=link.provider_key,
        operation_kind="manual_snapshot",
        idempotency_key=payload.idempotency_key,
        correlation_id=correlation,
        status="pending",
        response_class="unknown",
        external_call=False,
        requested_by_membership_id=locked_context.membership.id,
        started_at=now,
        created_at=now,
        metadata_json={
            "source": "manual_upload",
            "parser_version": payload.parser_version,
            "request_fingerprint": request_fingerprint,
        },
    )
    session.add(attempt)
    session.flush()
    snapshot = IpRegistrySnapshot(
        company_id=locked_context.company.id,
        link_id=link.id,
        attempt_id=attempt.id,
        source_url=payload.source_url,
        source_retrieved_at=payload.source_retrieved_at,
        parser_version=payload.parser_version,
        schema_version=payload.schema_version,
        attribution_json=payload.attribution,
        terms_version=link.terms_version,
        raw_sha256=raw_hash,
        normalized_sha256=normalized_hash,
        raw_json=payload.raw_snapshot,
        normalized_json=payload.normalized_snapshot,
        supersedes_snapshot_id=payload.supersedes_snapshot_id,
        correction_reason=payload.correction_reason,
        created_at=now,
    )
    session.add(snapshot)
    session.flush()
    before = _flatten(link.accepted_state_json or {})
    after = _flatten(payload.normalized_snapshot)
    diff_rows: list[IpRegistryDiff] = []
    for field_path in sorted(set(before) | set(after)):
        prior_exists = field_path in before
        next_exists = field_path in after
        prior_value = before.get(field_path)
        next_value = after.get(field_path)
        if prior_exists and next_exists and prior_value == next_value:
            continue
        change_kind = (
            "added" if not prior_exists else "removed" if not next_exists else "changed"
        )
        risk_level, risk_reasons, deadline_state = _risk(field_path)
        row = IpRegistryDiff(
            company_id=locked_context.company.id,
            snapshot_id=snapshot.id,
            field_path=field_path,
            change_kind=change_kind,
            before_value_json=prior_value,
            after_value_json=next_value,
            risk_level=risk_level,
            risk_reasons_json=risk_reasons,
            policy_version=REGISTRY_DIFF_POLICY_VERSION,
            resolution_status="pending",
            deadline_recalculation_state=deadline_state,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        diff_rows.append(row)
    no_change = not diff_rows
    attempt.status = "no_change" if no_change else "succeeded"
    attempt.response_class = "no_change" if no_change else "success"
    attempt.completed_at = now
    link.last_attempted_at = now
    link.last_successful_at = now
    link.last_snapshot_id = snapshot.id
    link.last_normalized_hash = normalized_hash
    link.last_error_redacted = None
    link.freshness_status = "current"
    link.version += 1
    link.updated_at = now
    record_from_context(
        session,
        locked_context,
        action="ip_registry.snapshot_recorded",
        target_type="ip_registry_snapshot",
        target_id=snapshot.id,
        ip_docket_id=link.docket_id,
        metadata={
            "link_id": link.id,
            "attempt_id": attempt.id,
            "raw_sha256": raw_hash,
            "normalized_sha256": normalized_hash,
            "diff_count": len(diff_rows),
            "no_change": no_change,
            "external_call": False,
            "supersedes_snapshot_id": payload.supersedes_snapshot_id,
        },
    )
    session.commit()
    session.refresh(link)
    session.refresh(attempt)
    session.refresh(snapshot)
    for row in diff_rows:
        session.refresh(row)
    return IpRegistrySnapshotResult(
        link=IpRegistryLinkResponse.model_validate(link),
        attempt=IpRegistrySyncAttemptResponse.model_validate(attempt),
        snapshot=IpRegistrySnapshotResponse.model_validate(snapshot),
        diffs=[IpRegistryDiffResponse.model_validate(row) for row in diff_rows],
        no_change=no_change,
    )


def record_registry_failure(
    session: Session,
    *,
    context: SessionContext,
    link_id: str,
    payload: IpRegistryFailureRequest,
) -> IpRegistrySnapshotResult:
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    discovered = _link_or_404(session, context=locked_context, link_id=link_id)
    _docket_or_404(
        session,
        context=locked_context,
        docket_id=discovered.docket_id,
        for_update=True,
    )
    link = session.scalar(
        select(IpRegistryLink)
        .where(
            IpRegistryLink.id == link_id,
            IpRegistryLink.company_id == locked_context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert link is not None
    adapter = provider_adapter_definition(link.provider_key)
    if link.match_status == "retired":
        raise HTTPException(
            status_code=409,
            detail="A retired registry link cannot record attempts.",
        )
    if payload.external_call and (
        adapter is None or "record_fetch" not in adapter.implemented_capabilities
    ):
        raise HTTPException(
            status_code=422,
            detail="External registry activity cannot be recorded for a blocked adapter.",
        )
    request_fingerprint = _hash(
        {
            "operation_kind": "record_fetch_failure",
            "response_class": payload.response_class,
            "error_redacted": redact_provider_error(payload.error),
            "external_call": payload.external_call,
            "source_retrieved_at": (
                payload.source_retrieved_at.isoformat()
                if payload.source_retrieved_at
                else None
            ),
        }
    )
    existing = _attempt_by_key(
        session,
        company_id=locked_context.company.id,
        link_id=link.id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        _assert_idempotent_payload(existing, request_fingerprint=request_fingerprint)
        return _existing_snapshot_result(session, link=link, attempt=existing)
    if link.version != payload.expected_link_version:
        raise HTTPException(status_code=409, detail="Registry link changed; reload.")
    now = _now()
    error = redact_provider_error(payload.error)
    blocked = payload.response_class in {"configuration", "policy"}
    attempt = IpRegistrySyncAttempt(
        company_id=locked_context.company.id,
        link_id=link.id,
        provider_key=link.provider_key,
        operation_kind="record_fetch",
        idempotency_key=payload.idempotency_key,
        correlation_id=sha256(
            f"{locked_context.company.id}:{link.id}:{payload.idempotency_key}".encode()
        ).hexdigest(),
        status="blocked" if blocked else "failed",
        response_class=payload.response_class,
        external_call=payload.external_call,
        error_redacted=error,
        requested_by_membership_id=locked_context.membership.id,
        started_at=payload.source_retrieved_at or now,
        completed_at=now,
        created_at=now,
        metadata_json={
            "legal_state_changed": False,
            "request_fingerprint": request_fingerprint,
        },
    )
    session.add(attempt)
    link.last_attempted_at = now
    link.last_error_redacted = error
    link.freshness_status = "blocked" if blocked else "failed"
    link.version += 1
    link.updated_at = now
    record_from_context(
        session,
        locked_context,
        action="ip_registry.sync_failed",
        target_type="ip_registry_sync_attempt",
        target_id=attempt.id,
        ip_docket_id=link.docket_id,
        result="failed",
        metadata={
            "link_id": link.id,
            "response_class": payload.response_class,
            "external_call": payload.external_call,
            "legal_state_changed": False,
            "last_good_snapshot_id": link.last_snapshot_id,
        },
    )
    session.commit()
    session.refresh(link)
    session.refresh(attempt)
    return IpRegistrySnapshotResult(
        link=IpRegistryLinkResponse.model_validate(link),
        attempt=IpRegistrySyncAttemptResponse.model_validate(attempt),
        snapshot=None,
        diffs=[],
        no_change=False,
    )


def resolve_registry_diff(
    session: Session,
    *,
    context: SessionContext,
    diff_id: str,
    payload: IpRegistryDiffResolveRequest,
) -> IpRegistryDiff:
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    discovered = session.execute(
        select(IpRegistryDiff, IpRegistrySnapshot, IpRegistryLink)
        .join(IpRegistrySnapshot, IpRegistrySnapshot.id == IpRegistryDiff.snapshot_id)
        .join(IpRegistryLink, IpRegistryLink.id == IpRegistrySnapshot.link_id)
        .where(
            IpRegistryDiff.id == diff_id,
            IpRegistryDiff.company_id == locked_context.company.id,
        )
    ).one_or_none()
    if discovered is None:
        raise HTTPException(status_code=404, detail="Registry diff not found.")
    _, _, discovered_link = discovered
    docket = _docket_or_404(
        session,
        context=locked_context,
        docket_id=discovered_link.docket_id,
        for_update=True,
    )
    link = session.scalar(
        select(IpRegistryLink)
        .where(
            IpRegistryLink.id == discovered_link.id,
            IpRegistryLink.company_id == locked_context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = session.scalar(
        select(IpRegistryDiff)
        .where(
            IpRegistryDiff.id == diff_id,
            IpRegistryDiff.company_id == locked_context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert link is not None and row is not None
    snapshot = session.scalar(
        select(IpRegistrySnapshot).where(
            IpRegistrySnapshot.id == row.snapshot_id,
            IpRegistrySnapshot.company_id == locked_context.company.id,
        )
    )
    assert snapshot is not None
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Registry diff changed; reload.")
    if payload.decision == "accept" and link.match_status != "confirmed":
        raise HTTPException(
            status_code=409,
            detail="Only a confirmed registry match can change accepted legal state.",
        )
    if row.resolution_status in {"accepted", "rejected"}:
        raise HTTPException(status_code=409, detail="Registry diff is already final.")
    if row.risk_level == "high" and payload.decision == "accept":
        if not membership_has_capability(session, locked_context.membership, "ip:approve"):
            raise HTTPException(
                status_code=403,
                detail="High-risk registry changes require IP approval capability.",
            )
    now = _now()
    emitted_event_id: str | None = None
    if payload.decision == "accept":
        application = (
            session.scalar(
                select(TrademarkApplication).where(
                    TrademarkApplication.id == link.application_id,
                    TrademarkApplication.company_id == locked_context.company.id,
                )
            )
            if link.application_id
            else None
        )
        event_common = {
            "expected_lifecycle_version": docket.lifecycle_version,
            "expected_application_version": application.version if application else None,
            "application_id": link.application_id,
            "proceeding_id": link.proceeding_id,
            "event_kind": "registry_change",
            "source": "registry",
            "source_reference": snapshot.source_url,
            "effective_at": payload.effective_at,
            "responsible_membership_id": payload.responsible_membership_id,
            "reason": payload.reason,
            "evidence_refs": [f"ip_registry_snapshot:{snapshot.id}"],
            "payload": {
                "registry_link_id": link.id,
                "registry_snapshot_id": snapshot.id,
                "registry_diff_id": row.id,
                "field_path": row.field_path,
                "change_kind": row.change_kind,
                "before_value": row.before_value_json,
                "after_value": row.after_value_json,
                "policy_version": row.policy_version,
                "risk_level": row.risk_level,
                "deadline_recalculation_required": (row.deadline_recalculation_state == "required"),
            },
        }
        candidate = append_ip_docket_event(
            session,
            context=locked_context,
            docket_id=docket.id,
            payload=IpDocketEventCreateRequest(
                **event_common,
                candidate_status="candidate",
            ),
            commit=False,
        )
        accepted = append_ip_docket_event(
            session,
            context=locked_context,
            docket_id=docket.id,
            payload=IpDocketEventCreateRequest(
                **event_common,
                candidate_status="reconciled",
                reconciles_event_id=candidate.id,
                reconciliation_decision="same_fact",
            ),
            commit=False,
        )
        emitted_event_id = accepted.id
        row.resolution_status = "accepted"
        row.emitted_event_id = accepted.id
        target_path = row.mapped_field_path or row.field_path
        link.accepted_state_json = (
            _remove_pointer(link.accepted_state_json or {}, target_path)
            if row.change_kind == "removed"
            else _set_pointer(
                link.accepted_state_json or {},
                target_path,
                row.after_value_json,
            )
        )
    elif payload.decision == "reject":
        row.resolution_status = "rejected"
    elif payload.decision == "map":
        row.resolution_status = "mapped"
        row.mapped_field_path = payload.mapped_field_path
    else:
        row.resolution_status = "deferred"
    row.resolution_reason = payload.reason
    row.resolved_by_membership_id = locked_context.membership.id
    row.resolved_at = now
    row.version += 1
    row.updated_at = now
    link.version += 1
    link.updated_at = now
    record_from_context(
        session,
        locked_context,
        action=f"ip_registry.diff_{payload.decision}",
        target_type="ip_registry_diff",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "snapshot_id": snapshot.id,
            "field_path": row.field_path,
            "change_kind": row.change_kind,
            "risk_level": row.risk_level,
            "emitted_event_id": emitted_event_id,
            "deadline_recalculation_state": row.deadline_recalculation_state,
        },
    )
    session.commit()
    session.refresh(row)
    return row


def list_registry_workspaces(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str | None = None,
) -> list[IpRegistryWorkspaceResponse]:
    if docket_id:
        _docket_or_404(session, context=context, docket_id=docket_id)
    statement = select(IpRegistryLink).where(IpRegistryLink.company_id == context.company.id)
    if docket_id:
        statement = statement.where(IpRegistryLink.docket_id == docket_id)
    links = list(session.scalars(statement.order_by(IpRegistryLink.updated_at.desc())).all())
    output: list[IpRegistryWorkspaceResponse] = []
    for link in links:
        _docket_or_404(session, context=context, docket_id=link.docket_id)
        attempts = list(
            session.scalars(
                select(IpRegistrySyncAttempt)
                .where(
                    IpRegistrySyncAttempt.link_id == link.id,
                    IpRegistrySyncAttempt.company_id == context.company.id,
                )
                .order_by(IpRegistrySyncAttempt.created_at.desc())
                .limit(20)
            ).all()
        )
        snapshots = list(
            session.scalars(
                select(IpRegistrySnapshot)
                .where(
                    IpRegistrySnapshot.link_id == link.id,
                    IpRegistrySnapshot.company_id == context.company.id,
                )
                .order_by(IpRegistrySnapshot.created_at.desc())
                .limit(20)
            ).all()
        )
        snapshot_ids = [row.id for row in snapshots]
        diffs = (
            list(
                session.scalars(
                    select(IpRegistryDiff)
                    .where(
                        IpRegistryDiff.snapshot_id.in_(snapshot_ids),
                        IpRegistryDiff.company_id == context.company.id,
                    )
                    .order_by(IpRegistryDiff.created_at.desc(), IpRegistryDiff.field_path)
                ).all()
            )
            if snapshot_ids
            else []
        )
        output.append(
            IpRegistryWorkspaceResponse(
                link=IpRegistryLinkResponse.model_validate(link),
                attempts=[IpRegistrySyncAttemptResponse.model_validate(row) for row in attempts],
                snapshots=[IpRegistrySnapshotResponse.model_validate(row) for row in snapshots],
                diffs=[IpRegistryDiffResponse.model_validate(row) for row in diffs],
            )
        )
    return output


def create_tracked_case_reference(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpTrackedCaseLinkCreateRequest,
) -> IpTrackedCaseLink:
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    docket = _docket_or_404(
        session,
        context=locked_context,
        docket_id=docket_id,
        for_update=True,
    )
    proceeding = session.scalar(
        select(IpProceeding).where(
            IpProceeding.id == payload.proceeding_id,
            IpProceeding.company_id == locked_context.company.id,
            IpProceeding.docket_id == docket.id,
        )
    )
    if proceeding is None:
        raise HTTPException(status_code=404, detail="IP proceeding not found.")
    tracked_case = session.scalar(
        select(TrackedCase).where(
            TrackedCase.id == payload.tracked_case_id,
            TrackedCase.company_id == locked_context.company.id,
        )
    )
    if tracked_case is None:
        raise HTTPException(status_code=404, detail="Tracked case not found.")
    if docket.matter_id is None:
        raise HTTPException(
            status_code=409,
            detail="Link the IP docket to a Matter before referencing court tracking.",
        )
    bookmark = session.scalar(
        select(TrackedCaseBookmark).where(
            TrackedCaseBookmark.company_id == locked_context.company.id,
            TrackedCaseBookmark.tracked_case_id == tracked_case.id,
            TrackedCaseBookmark.matter_id == docket.matter_id,
            TrackedCaseBookmark.is_archived.is_(False),
        )
    )
    if bookmark is None:
        raise HTTPException(
            status_code=409,
            detail="The tracked case must already be bookmarked to the linked Matter.",
        )
    existing = session.scalar(
        select(IpTrackedCaseLink).where(
            IpTrackedCaseLink.company_id == locked_context.company.id,
            IpTrackedCaseLink.docket_id == docket.id,
            IpTrackedCaseLink.proceeding_id == proceeding.id,
            IpTrackedCaseLink.tracked_case_id == tracked_case.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This court tracking reference already exists.")
    row = IpTrackedCaseLink(
        company_id=locked_context.company.id,
        docket_id=docket.id,
        proceeding_id=proceeding.id,
        tracked_case_id=tracked_case.id,
        purpose=payload.purpose,
        evidence_reference=payload.evidence_reference,
        created_by_membership_id=locked_context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        locked_context,
        action="ip_tracked_case.reference_created",
        target_type="ip_tracked_case_link",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "proceeding_id": proceeding.id,
            "tracked_case_id": tracked_case.id,
            "copied_update_count": 0,
        },
    )
    session.commit()
    session.refresh(row)
    return row


def decide_tracked_case_reference(
    session: Session,
    *,
    context: SessionContext,
    link_id: str,
    payload: IpTrackedCaseLinkDecisionRequest,
) -> IpTrackedCaseLink:
    locked_context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:registry_sync"
    )
    discovered = session.scalar(
        select(IpTrackedCaseLink).where(
            IpTrackedCaseLink.id == link_id,
            IpTrackedCaseLink.company_id == locked_context.company.id,
        )
    )
    if discovered is None:
        raise HTTPException(status_code=404, detail="Tracked-case reference not found.")
    docket = _docket_or_404(
        session,
        context=locked_context,
        docket_id=discovered.docket_id,
        for_update=True,
    )
    row = session.scalar(
        select(IpTrackedCaseLink)
        .where(
            IpTrackedCaseLink.id == link_id,
            IpTrackedCaseLink.company_id == locked_context.company.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Tracked-case reference changed; reload.")
    row.link_status = {
        "confirm": "active",
        "mismatch": "mismatch",
        "retire": "retired",
    }[payload.decision]
    row.version += 1
    row.updated_at = _now()
    record_from_context(
        session,
        locked_context,
        action=f"ip_tracked_case.reference_{payload.decision}",
        target_type="ip_tracked_case_link",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"reason": payload.reason, "copied_update_count": 0},
    )
    session.commit()
    session.refresh(row)
    return row


def list_tracked_case_references(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> list[IpTrackedCaseReferenceResponse]:
    _docket_or_404(session, context=context, docket_id=docket_id)
    rows = list(
        session.execute(
            select(IpTrackedCaseLink, TrackedCase, func.count(TrackedCaseUpdate.id))
            .join(TrackedCase, TrackedCase.id == IpTrackedCaseLink.tracked_case_id)
            .outerjoin(
                TrackedCaseUpdate,
                TrackedCaseUpdate.tracked_case_id == TrackedCase.id,
            )
            .where(
                IpTrackedCaseLink.company_id == context.company.id,
                IpTrackedCaseLink.docket_id == docket_id,
                TrackedCase.company_id == context.company.id,
            )
            .group_by(IpTrackedCaseLink.id, TrackedCase.id)
            .order_by(IpTrackedCaseLink.updated_at.desc())
        ).all()
    )
    return [
        IpTrackedCaseReferenceResponse(
            id=link.id,
            company_id=link.company_id,
            docket_id=link.docket_id,
            proceeding_id=link.proceeding_id,
            tracked_case_id=link.tracked_case_id,
            link_status=link.link_status,
            purpose=link.purpose,
            evidence_reference=link.evidence_reference,
            created_by_membership_id=link.created_by_membership_id,
            version=link.version,
            created_at=link.created_at,
            updated_at=link.updated_at,
            provider=tracked.provider,
            case_title=tracked.case_title,
            cnr_number=tracked.cnr_number,
            case_number=tracked.case_number,
            court_name=tracked.court_name,
            current_status=tracked.current_status,
            last_provider_successful_at=tracked.last_provider_successful_at,
            provider_freshness_status=tracked.provider_freshness_status,
            update_count=int(update_count),
        )
        for link, tracked, update_count in rows
    ]
