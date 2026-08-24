"""Canonical IPLF-052 journal ingestion, watch review, and handoff service."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    IpDocketRecord,
    IpJournalIngestionRun,
    IpJournalPublication,
    IpWatchHandoff,
    IpWatchHit,
    IpWatchProfile,
    Matter,
    TrademarkApplication,
)
from caseops_api.schemas.ip_lifecycle import IpDocketEventCreateRequest
from caseops_api.schemas.ip_matter_links import IpMatterLinkCreateRequest
from caseops_api.schemas.ip_records import IpProceedingCreateRequest
from caseops_api.schemas.ip_watch import (
    IpJournalIngestionRunResponse,
    IpJournalPublicationResponse,
    IpWatchHandoffResponse,
    IpWatchHitResponse,
    IpWatchProfileResponse,
    IpWatchWorkspaceResponse,
)
from caseops_api.schemas.matters import MatterCreateRequest
from caseops_api.schemas.shared_work import (
    IpOperationalDeadlineCreateRequest,
    IpSharedTaskCreateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.domain_outbox import enqueue_domain_event
from caseops_api.services.ip_lifecycle import append_ip_docket_event
from caseops_api.services.ip_matter_links import create_matter_link
from caseops_api.services.ip_operations import _docket_or_404, _lock_ip_writer_context
from caseops_api.services.ip_records import create_ip_proceeding
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.matters import create_matter
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import (
    create_ip_operational_deadline,
    create_ip_shared_task,
)

if TYPE_CHECKING:
    from caseops_api.schemas.ip_watch import (
        IpJournalIngestRequest,
        IpJournalPublicationCreate,
        IpWatchHandoffRequest,
        IpWatchHitDispositionRequest,
        IpWatchProfileCreateRequest,
        IpWatchProfileUpdateRequest,
    )


CRITERIA_VERSION = "ip-watch-criteria-v1"
SIMILARITY_VERSION = "ip-watch-similarity-v1"
AI_ADVISORY_NOTICE = (
    "Similarity scoring is advisory. Verify the official source and apply independent "
    "legal judgment before filing, infringement advice, or enforcement."
)
FINAL_SOURCE_DEPENDENT_DISPOSITIONS = {
    "relevant",
    "not_relevant",
    "client_instruction",
    "enforcement_opened",
    "closed",
}
ACTIONABLE_DISPOSITIONS = {"relevant", "client_instruction", "enforcement_opened"}
STALE_AFTER_HOURS = 72
MAX_INGEST_PUBLICATIONS = 50
MAX_ACTIVE_PROFILES_PER_INGEST = 100
MAX_PROFILE_PUBLICATION_COMPARISONS = 2_500
MAX_HITS_PER_INGEST = 250


@dataclass(frozen=True, slots=True)
class JournalWatchSchedulerResult:
    due_profiles: int
    checked_profiles: int
    cost_paused_profiles: int
    provider_paused_profiles: int
    external_calls: int


def _now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: object) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value))


def _soundex(value: str) -> str:
    normalized = _normalize(value).replace(" ", "")
    if not normalized:
        return ""
    groups = {
        **dict.fromkeys("bfpv", "1"),
        **dict.fromkeys("cgjkqsxz", "2"),
        **dict.fromkeys("dt", "3"),
        "l": "4",
        **dict.fromkeys("mn", "5"),
        "r": "6",
    }
    first = normalized[0].upper()
    digits: list[str] = []
    previous = groups.get(normalized[0], "")
    for char in normalized[1:]:
        digit = groups.get(char, "")
        if digit and digit != previous:
            digits.append(digit)
        previous = digit
    return (first + "".join(digits) + "000")[:4]


def _next_poll(frequency: str, current: datetime) -> datetime:
    return (
        current
        + {
            "publication": timedelta(days=1),
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
            "monthly": timedelta(days=30),
        }[frequency]
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _cost_period_bounds(frequency: str, current: datetime) -> tuple[datetime, datetime]:
    current = _aware(current)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency == "monthly":
        start = day_start.replace(day=1)
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
    elif frequency == "weekly":
        start = day_start - timedelta(days=day_start.weekday())
        end = start + timedelta(days=7)
    else:
        # Publication-triggered profiles use the publication-day cost period.
        start = day_start
        end = start + timedelta(days=1)
    return start, end


def _reset_cost_period_if_due(profile: IpWatchProfile, current: datetime) -> None:
    start, _ = _cost_period_bounds(profile.frequency, current)
    last_polled = _aware(profile.last_polled_at) if profile.last_polled_at else None
    if profile.spent_cost_minor_in_period and (last_polled is None or last_polled < start):
        profile.spent_cost_minor_in_period = 0
        if profile.poll_status == "paused_cost_quota":
            profile.poll_status = "active"
            profile.pause_reason = None


def _profile_or_404(
    session: Session, *, context: SessionContext, profile_id: str, for_update: bool = False
) -> IpWatchProfile:
    statement = select(IpWatchProfile).where(
        IpWatchProfile.id == profile_id,
        IpWatchProfile.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    profile = session.scalar(statement)
    if profile is None:
        raise HTTPException(status_code=404, detail="Watch profile not found.")
    _docket_or_404(session, context=context, docket_id=profile.docket_id, for_update=for_update)
    return profile


def _hit_context(
    session: Session, *, context: SessionContext, hit_id: str, for_update: bool = False
) -> tuple[IpWatchHit, IpWatchProfile, IpJournalPublication, IpDocketRecord]:
    statement = select(IpWatchHit).where(
        IpWatchHit.id == hit_id,
        IpWatchHit.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    hit = session.scalar(statement)
    if hit is None:
        raise HTTPException(status_code=404, detail="Watch hit not found.")
    profile = session.scalar(
        select(IpWatchProfile).where(
            IpWatchProfile.id == hit.profile_id,
            IpWatchProfile.company_id == context.company.id,
        )
    )
    publication = session.scalar(
        select(IpJournalPublication).where(
            IpJournalPublication.id == hit.publication_id,
            IpJournalPublication.company_id == context.company.id,
        )
    )
    assert profile is not None and publication is not None
    docket = _docket_or_404(
        session, context=context, docket_id=profile.docket_id, for_update=for_update
    )
    return hit, profile, publication, docket


def create_watch_profile(
    session: Session,
    *,
    context: SessionContext,
    payload: IpWatchProfileCreateRequest,
) -> IpWatchProfile:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    docket = _docket_or_404(session, context=locked, docket_id=payload.docket_id, for_update=True)
    recipient_ids = sorted(set(payload.recipient_membership_ids))
    recipients = list(
        session.scalars(
            select(CompanyMembership).where(
                CompanyMembership.company_id == locked.company.id,
                CompanyMembership.id.in_(recipient_ids),
                CompanyMembership.is_active.is_(True),
            )
        )
    )
    if {item.id for item in recipients} != set(recipient_ids):
        raise HTTPException(status_code=422, detail="Every watch recipient must be active.")
    now = _now()
    row = IpWatchProfile(
        company_id=locked.company.id,
        docket_id=docket.id,
        name=payload.name.strip(),
        provider_key=payload.provider_key.strip(),
        word_terms_json=sorted(
            {_normalize(item) for item in payload.word_terms if _normalize(item)}
        ),
        phonetic_terms_json=sorted(
            {_normalize(item) for item in payload.phonetic_terms if _normalize(item)}
        ),
        device_references_json=sorted(set(payload.device_references)),
        class_numbers_json=sorted(set(payload.class_numbers)),
        proprietor_terms_json=sorted(
            {_normalize(item) for item in payload.proprietor_terms if _normalize(item)}
        ),
        jurisdictions_json=sorted({item.strip().upper() for item in payload.jurisdictions}),
        frequency=payload.frequency,
        recipient_membership_ids_json=recipient_ids,
        max_cost_minor_per_period=payload.max_cost_minor_per_period,
        spent_cost_minor_in_period=0,
        cost_currency=payload.cost_currency.upper(),
        poll_status="active",
        next_poll_at=now,
        criteria_version=CRITERIA_VERSION,
        created_by_membership_id=locked.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        locked,
        action="ip_watch.profile_created",
        target_type="ip_watch_profile",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={"frequency": row.frequency, "recipient_count": len(recipient_ids)},
    )
    session.commit()
    session.refresh(row)
    return row


def update_watch_profile_status(
    session: Session,
    *,
    context: SessionContext,
    profile_id: str,
    payload: IpWatchProfileUpdateRequest,
) -> IpWatchProfile:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    profile = _profile_or_404(session, context=locked, profile_id=profile_id, for_update=True)
    if profile.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Watch profile changed; reload and retry.")
    profile.poll_status = payload.poll_status
    profile.pause_reason = None if payload.poll_status == "active" else payload.reason.strip()
    profile.next_poll_at = _now() if payload.poll_status == "active" else None
    profile.version += 1
    record_from_context(
        session,
        locked,
        action="ip_watch.profile_status_changed",
        target_type="ip_watch_profile",
        target_id=profile.id,
        ip_docket_id=profile.docket_id,
        metadata={"poll_status": profile.poll_status, "reason": payload.reason},
    )
    session.commit()
    session.refresh(profile)
    return profile


def _publication_fingerprint(provider_key: str, payload: IpJournalPublicationCreate) -> str:
    return _fingerprint(
        {
            "provider": provider_key,
            "journal": payload.journal_number,
            "date": payload.journal_date.isoformat(),
            "kind": payload.publication_kind,
            "application": _normalize(payload.application_number),
            "classes": sorted(payload.class_numbers),
            "source_page": payload.source_page,
            "source_url": payload.source_url,
        }
    )


def _similarity(profile: IpWatchProfile, publication: IpJournalPublication) -> dict[str, Any]:
    candidate = _normalize(publication.mark_text)
    word_rows = [
        {
            "term": term,
            "score": round(SequenceMatcher(None, term, candidate).ratio(), 4) if candidate else 0,
            "contains": bool(term and candidate and (term in candidate or candidate in term)),
        }
        for term in profile.word_terms_json
    ]
    phonetic_rows = [
        {
            "term": term,
            "term_code": _soundex(term),
            "candidate_code": _soundex(candidate),
            "matched": bool(candidate and _soundex(term) == _soundex(candidate)),
        }
        for term in profile.phonetic_terms_json
    ]
    publication_classes = set(publication.class_numbers_json)
    profile_classes = set(profile.class_numbers_json)
    class_overlap = sorted(publication_classes & profile_classes)
    proprietor = _normalize(publication.proprietor_name)
    proprietor_matches = (
        [term for term in profile.proprietor_terms_json if term in proprietor or proprietor in term]
        if proprietor
        else []
    )
    jurisdiction_match = (
        not profile.jurisdictions_json
        or publication.jurisdiction.upper() in profile.jurisdictions_json
    )
    supplied_device = (publication.raw_evidence_json or {}).get("device_similarity")
    supplied_device_match = bool(
        isinstance(supplied_device, dict)
        and supplied_device.get("matched") is True
        and supplied_device.get("profile_reference") in profile.device_references_json
        and supplied_device.get("candidate_reference") == publication.device_reference
    )
    device_match = bool(
        publication.device_reference
        and profile.device_references_json
        and (
            publication.device_reference in profile.device_references_json or supplied_device_match
        )
    )
    matched = (
        bool(
            any(row["contains"] or row["score"] >= 0.6 for row in word_rows)
            or any(row["matched"] for row in phonetic_rows)
            or device_match
            or class_overlap
            or proprietor_matches
        )
        and jurisdiction_match
    )
    ai_advisory = bool(isinstance(supplied_device, dict) and supplied_device.get("method") == "ai")
    return {
        "version": SIMILARITY_VERSION,
        "matched": matched,
        "word": word_rows,
        "phonetic": phonetic_rows,
        "device": {
            "matched": device_match,
            "profile_references": profile.device_references_json,
            "candidate_reference": publication.device_reference,
            "supplied_evidence": supplied_device,
        },
        "class_overlap": class_overlap,
        "proprietor_matches": proprietor_matches,
        "jurisdiction_match": jurisdiction_match,
        "ai_advisory": ai_advisory,
    }


def _source_snapshot(publication: IpJournalPublication) -> dict[str, Any]:
    return {
        "publication_id": publication.id,
        "journal_number": publication.journal_number,
        "journal_date": publication.journal_date.isoformat(),
        "publication_kind": publication.publication_kind,
        "application_number": publication.application_number,
        "mark_text": publication.mark_text,
        "device_reference": publication.device_reference,
        "proprietor_name": publication.proprietor_name,
        "office": publication.office,
        "jurisdiction": publication.jurisdiction,
        "class_numbers": publication.class_numbers_json,
        "goods_services": publication.goods_services_json,
        "publication_scope": publication.publication_scope_json,
        "source_url": publication.source_url,
        "source_page": publication.source_page,
        "source_status": publication.source_status,
        "source_fingerprint": publication.source_fingerprint,
        "supersedes_publication_id": publication.supersedes_publication_id,
    }


def _record_hit_event(
    session: Session,
    *,
    context: SessionContext,
    profile: IpWatchProfile,
    publication: IpJournalPublication,
    hit: IpWatchHit,
) -> None:
    docket = _docket_or_404(session, context=context, docket_id=profile.docket_id, for_update=True)
    application = None
    if publication.application_id:
        application = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == publication.application_id,
                TrademarkApplication.company_id == context.company.id,
                TrademarkApplication.docket_id == docket.id,
            )
        )
    effective_at = datetime.combine(publication.journal_date, time.min, tzinfo=UTC)
    event = append_ip_docket_event(
        session,
        context=context,
        docket_id=docket.id,
        payload=IpDocketEventCreateRequest(
            expected_lifecycle_version=docket.lifecycle_version,
            expected_application_version=application.version if application else None,
            application_id=application.id if application else None,
            event_kind="publication",
            source="integration",
            source_reference=publication.id,
            effective_at=effective_at,
            responsible_membership_id=profile.recipient_membership_ids_json[0],
            reason="Journal watch candidate requires attorney review.",
            evidence_refs=[publication.source_url],
            candidate_status="candidate",
            payload={
                "watch_hit_id": hit.id,
                "watch_profile_id": profile.id,
                "recipient_membership_ids": profile.recipient_membership_ids_json,
                "source_status": publication.source_status,
                "ai_advisory": hit.ai_advisory,
            },
        ),
        commit=False,
    )
    enqueue_domain_event(
        session,
        company_id=context.company.id,
        event_key=f"ip-watch-hit:{hit.id}:1",
        event_type="ip.watch_hit.created",
        schema_version=1,
        aggregate_type="ip_watch_hit",
        aggregate_id=hit.id,
        aggregate_version=hit.version,
        occurred_at=_now(),
        effective_at=effective_at,
        source_command_id=f"ip_watch_hit:{hit.id}",
        source_event_id=event.id,
        producer="caseops.ip_watch",
        confidentiality="privileged",
        correlation_id=f"ip-watch-hit:{hit.id}",
        payload={
            "watch_hit_id": hit.id,
            "target_id": docket.id,
            "source_evidence_id": publication.id,
            "recipient_profile_id": profile.id,
        },
    )
    recipients = list(
        session.scalars(
            select(CompanyMembership).where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id.in_(profile.recipient_membership_ids_json),
                CompanyMembership.is_active.is_(True),
            )
        )
    )
    for recipient in recipients:
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel="in_app",
            event_type="ip_watch_hit_created",
            source_type="ip_watch_hit",
            source_id=hit.id,
            ip_docket=docket,
            title=(
                "Trademark journal watch hit: "
                f"{publication.mark_text or publication.application_number}"
            ),
            body=(
                f"Review journal {publication.journal_number} evidence for {docket.title}. "
                "Similarity is advisory; verify the official source before acting."
            ),
            scheduled_for=_now(),
            critical=False,
            schedule_source_type="ip_watch_profile",
            schedule_source_id=profile.id,
        )
        if intent is not None:
            process_notification_delivery_intent(
                session,
                intent_id=intent.id,
                context=context,
            )


def ingest_journal(
    session: Session,
    *,
    context: SessionContext,
    payload: IpJournalIngestRequest,
) -> tuple[IpJournalIngestionRun, list[IpJournalPublication], list[IpWatchHit], bool]:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    request_sha256 = _fingerprint(payload.model_dump(mode="json", exclude={"idempotency_key"}))
    replay = session.scalar(
        select(IpJournalIngestionRun).where(
            IpJournalIngestionRun.company_id == locked.company.id,
            IpJournalIngestionRun.idempotency_key == payload.idempotency_key,
        )
    )
    if replay is not None:
        if replay.request_sha256 != request_sha256:
            raise HTTPException(
                status_code=409,
                detail="This idempotency key was already used for a different journal payload.",
            )
        publications = (
            list(
                session.scalars(
                    select(IpJournalPublication).where(
                        IpJournalPublication.company_id == locked.company.id,
                        IpJournalPublication.id.in_(replay.publication_ids_json),
                    )
                )
            )
            if replay.publication_ids_json
            else []
        )
        hits = (
            list(
                session.scalars(
                    select(IpWatchHit).where(
                        IpWatchHit.company_id == locked.company.id,
                        IpWatchHit.id.in_(replay.hit_ids_json),
                    )
                )
            )
            if replay.hit_ids_json
            else []
        )
        return replay, publications, hits, True

    now = _now()
    profiles = list(
        session.scalars(
            select(IpWatchProfile)
            .join(
                IpDocketRecord,
                (IpDocketRecord.id == IpWatchProfile.docket_id)
                & (IpDocketRecord.company_id == IpWatchProfile.company_id),
            )
            .outerjoin(
                Matter,
                (Matter.id == IpDocketRecord.matter_id)
                & (Matter.company_id == IpDocketRecord.company_id),
            )
            .where(
                IpWatchProfile.company_id == locked.company.id,
                IpWatchProfile.poll_status.in_(("active", "paused_cost_quota")),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
                visible_ip_dockets_filter(session, context=locked),
            )
            .with_for_update(of=IpWatchProfile)
            .limit(MAX_ACTIVE_PROFILES_PER_INGEST + 1)
        )
    )
    if len(payload.publications) > MAX_INGEST_PUBLICATIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Journal ingestion is limited to {MAX_INGEST_PUBLICATIONS} publications.",
        )
    if len(profiles) > MAX_ACTIVE_PROFILES_PER_INGEST:
        raise HTTPException(
            status_code=422,
            detail=(
                "Too many active watch profiles for one interactive ingestion; "
                "pause or partition profiles before retrying."
            ),
        )
    comparison_count = len(profiles) * len(payload.publications)
    if comparison_count > MAX_PROFILE_PUBLICATION_COMPARISONS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Journal ingestion exceeds the bounded profile/publication comparison limit "
                f"of {MAX_PROFILE_PUBLICATION_COMPARISONS}."
            ),
        )
    active_profiles: list[IpWatchProfile] = []
    paused = False
    request_currency = payload.currency.upper()
    for profile in profiles:
        _reset_cost_period_if_due(profile, now)
        if payload.cost_minor and request_currency != profile.cost_currency.upper():
            raise HTTPException(
                status_code=422,
                detail=(
                    "Journal ingestion currency must match every charged watch profile "
                    f"({profile.cost_currency.upper()})."
                ),
            )
        would_spend = profile.spent_cost_minor_in_period + payload.cost_minor
        if profile.max_cost_minor_per_period and would_spend > profile.max_cost_minor_per_period:
            _, period_end = _cost_period_bounds(profile.frequency, now)
            profile.poll_status = "paused_cost_quota"
            profile.pause_reason = (
                f"Cost quota {profile.max_cost_minor_per_period} {profile.cost_currency} minor "
                "units would be exceeded."
            )
            profile.next_poll_at = period_end
            profile.version += 1
            paused = True
            continue
        active_profiles.append(profile)
    run = IpJournalIngestionRun(
        company_id=locked.company.id,
        provider_key=payload.provider_key,
        idempotency_key=payload.idempotency_key,
        request_sha256=request_sha256,
        status="paused_cost_quota" if paused and not active_profiles else "pending",
        external_call=payload.external_call,
        cost_minor=payload.cost_minor,
        currency=request_currency,
        publications_seen=len(payload.publications),
        requested_by_membership_id=locked.membership.id,
        started_at=now,
    )
    session.add(run)
    session.flush()
    if not active_profiles:
        run.completed_at = now
        session.commit()
        session.refresh(run)
        return run, [], [], False

    created_publications: list[IpJournalPublication] = []
    created_hits: list[IpWatchHit] = []
    duplicate_hits = 0
    stale_alert = False
    item_fingerprints = [
        (item, _publication_fingerprint(payload.provider_key, item))
        for item in payload.publications
    ]
    fingerprints = [fingerprint for _, fingerprint in item_fingerprints]
    existing_publications = list(
        session.scalars(
            select(IpJournalPublication).where(
                IpJournalPublication.company_id == locked.company.id,
                IpJournalPublication.source_fingerprint.in_(fingerprints),
            )
        )
    )
    publications_by_fingerprint = {
        publication.source_fingerprint: publication for publication in existing_publications
    }
    application_ids = {item.application_id for item in payload.publications if item.application_id}
    applications = (
        list(
            session.scalars(
                select(TrademarkApplication).where(
                    TrademarkApplication.company_id == locked.company.id,
                    TrademarkApplication.id.in_(application_ids),
                )
            )
        )
        if application_ids
        else []
    )
    applications_by_id = {application.id: application for application in applications}
    predecessor_ids = {
        item.supersedes_publication_id
        for item in payload.publications
        if item.supersedes_publication_id
    }
    predecessors = (
        list(
            session.scalars(
                select(IpJournalPublication).where(
                    IpJournalPublication.company_id == locked.company.id,
                    IpJournalPublication.id.in_(predecessor_ids),
                )
            )
        )
        if predecessor_ids
        else []
    )
    predecessors_by_id = {publication.id: publication for publication in predecessors}
    candidate_publications_by_id: dict[str, IpJournalPublication] = {}
    for item, fingerprint in item_fingerprints:
        publication = publications_by_fingerprint.get(fingerprint)
        if publication is None:
            if item.application_id and item.application_id not in applications_by_id:
                raise HTTPException(status_code=404, detail="Trademark application not found.")
            predecessor = None
            if item.supersedes_publication_id:
                predecessor = predecessors_by_id.get(item.supersedes_publication_id)
                if predecessor is None:
                    raise HTTPException(status_code=404, detail="Superseded publication not found.")
                if _normalize(predecessor.application_number) != _normalize(
                    item.application_number
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="Correction must preserve the advertised application identity.",
                    )
            retrieved = item.source_retrieved_at
            delay = max(
                0,
                int(
                    (
                        (retrieved or now)
                        - datetime.combine(item.journal_date, time.min, tzinfo=UTC)
                    ).total_seconds()
                    // 3600
                ),
            )
            stale = item.source_status == "stale" or delay > STALE_AFTER_HOURS
            stale_alert = stale_alert or stale
            publication = IpJournalPublication(
                company_id=locked.company.id,
                application_id=item.application_id,
                provider_key=payload.provider_key,
                journal_number=item.journal_number.strip(),
                journal_date=item.journal_date,
                publication_kind=item.publication_kind,
                application_number=item.application_number.strip(),
                mark_text=item.mark_text.strip() if item.mark_text else None,
                device_reference=item.device_reference,
                proprietor_name=item.proprietor_name.strip() if item.proprietor_name else None,
                office=item.office.strip(),
                jurisdiction=item.jurisdiction.strip().upper(),
                class_numbers_json=sorted(item.class_numbers),
                goods_services_json=item.goods_services,
                publication_scope_json=item.publication_scope,
                source_url=item.source_url,
                source_page=item.source_page,
                source_status=item.source_status,
                source_retrieved_at=retrieved,
                parser_version=item.parser_version,
                attribution_json=item.attribution,
                raw_evidence_json=item.raw_evidence,
                source_fingerprint=fingerprint,
                supersedes_publication_id=item.supersedes_publication_id,
                correction_reason=item.correction_reason,
                ingestion_delay_hours=delay,
            )
            session.add(publication)
            session.flush()
            created_publications.append(publication)
            publications_by_fingerprint[fingerprint] = publication
        stale_alert = stale_alert or (
            publication.source_status == "stale"
            or publication.ingestion_delay_hours > STALE_AFTER_HOURS
        )
        candidate_publications_by_id[publication.id] = publication

    candidate_publications = list(candidate_publications_by_id.values())
    profile_ids = [profile.id for profile in active_profiles]
    publication_ids = [publication.id for publication in candidate_publications]
    existing_hits = list(
        session.scalars(
            select(IpWatchHit).where(
                IpWatchHit.company_id == locked.company.id,
                IpWatchHit.profile_id.in_(profile_ids),
                IpWatchHit.publication_id.in_(publication_ids),
            )
        )
    )
    hits_by_pair = {(hit.profile_id, hit.publication_id): hit for hit in existing_hits}
    application_keys = {
        publication.application_number.lower() for publication in candidate_publications
    }
    history_rows = list(
        session.execute(
            select(IpWatchHit, IpJournalPublication.application_number)
            .join(
                IpJournalPublication,
                (IpJournalPublication.id == IpWatchHit.publication_id)
                & (IpJournalPublication.company_id == IpWatchHit.company_id),
            )
            .where(
                IpWatchHit.company_id == locked.company.id,
                IpWatchHit.profile_id.in_(profile_ids),
                func.lower(IpJournalPublication.application_number).in_(application_keys),
            )
            .order_by(IpWatchHit.created_at.desc())
        )
    )
    latest_by_application: dict[tuple[str, str], IpWatchHit] = {}
    for historical_hit, application_number in history_rows:
        latest_by_application.setdefault(
            (historical_hit.profile_id, _normalize(application_number)), historical_hit
        )

    planned_hits: list[tuple[IpWatchProfile, IpJournalPublication, dict[str, Any]]] = []
    for publication in candidate_publications:
        for profile in active_profiles:
            evidence = _similarity(profile, publication)
            if not evidence["matched"]:
                continue
            existing = hits_by_pair.get((profile.id, publication.id))
            if existing is not None:
                duplicate_hits += 1
                continue
            planned_hits.append((profile, publication, evidence))
    if len(planned_hits) > MAX_HITS_PER_INGEST:
        raise HTTPException(
            status_code=422,
            detail=f"Journal ingestion is limited to {MAX_HITS_PER_INGEST} resulting hits.",
        )

    for profile, publication, evidence in planned_hits:
        prior = None
        if publication.supersedes_publication_id:
            prior = hits_by_pair.get((profile.id, publication.supersedes_publication_id))
        if prior is None:
            prior = latest_by_application.get(
                (profile.id, _normalize(publication.application_number))
            )
        hit = IpWatchHit(
            company_id=locked.company.id,
            profile_id=profile.id,
            publication_id=publication.id,
            duplicate_of_hit_id=prior.id if prior else None,
            compared_mark_json={
                "word_terms": profile.word_terms_json,
                "phonetic_terms": profile.phonetic_terms_json,
                "device_references": profile.device_references_json,
            },
            candidate_mark_json={
                "mark_text": publication.mark_text,
                "device_reference": publication.device_reference,
                "application_number": publication.application_number,
                "proprietor_name": publication.proprietor_name,
            },
            classes_goods_json={
                "classes": publication.class_numbers_json,
                "goods_services": publication.goods_services_json,
                "scope": publication.publication_scope_json,
            },
            similarity_evidence_json=evidence,
            ai_advisory=evidence["ai_advisory"],
            advisory_notice=AI_ADVISORY_NOTICE,
            source_url=publication.source_url,
            source_status=publication.source_status,
            source_snapshot_json=_source_snapshot(publication),
            hit_date=publication.journal_date,
            stale_source_alert=(
                publication.source_status == "stale"
                or publication.ingestion_delay_hours > STALE_AFTER_HOURS
            ),
            deadline_confirmation_state="pending_confirmation",
        )
        session.add(hit)
        session.flush()
        _record_hit_event(
            session,
            context=locked,
            profile=profile,
            publication=publication,
            hit=hit,
        )
        created_hits.append(hit)
        hits_by_pair[(profile.id, publication.id)] = hit
        latest_by_application[(profile.id, _normalize(publication.application_number))] = hit

    for profile in active_profiles:
        profile.spent_cost_minor_in_period += payload.cost_minor
        profile.last_polled_at = now
        profile.next_poll_at = _next_poll(profile.frequency, now)
        profile.poll_status = "active"
        profile.pause_reason = None
        profile.version += 1
    run.status = "succeeded"
    run.publications_created = len(created_publications)
    run.hits_created = len(created_hits)
    run.duplicate_hits = duplicate_hits
    run.publication_ids_json = [row.id for row in candidate_publications]
    run.hit_ids_json = [row.id for row in created_hits]
    run.stale_source_alert = stale_alert
    run.completed_at = _now()
    record_from_context(
        session,
        locked,
        action="ip_watch.journal_ingested",
        target_type="ip_journal_ingestion_run",
        target_id=run.id,
        metadata={
            "publications_created": run.publications_created,
            "hits_created": run.hits_created,
            "duplicate_hits": run.duplicate_hits,
            "stale_source_alert": run.stale_source_alert,
            "external_call": run.external_call,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Journal ingestion conflicted; retry safely.",
        ) from exc
    session.refresh(run)
    return run, candidate_publications, created_hits, False


def decide_watch_hit(
    session: Session,
    *,
    context: SessionContext,
    hit_id: str,
    payload: IpWatchHitDispositionRequest,
) -> IpWatchHit:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    hit, _, publication, _ = _hit_context(session, context=locked, hit_id=hit_id, for_update=True)
    if hit.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Watch hit changed; reload and retry.")
    if payload.disposition == "new" and hit.disposition != "new":
        raise HTTPException(status_code=422, detail="A reviewed hit cannot return to new.")
    if payload.disposition in FINAL_SOURCE_DEPENDENT_DISPOSITIONS and (
        publication.source_status != "available" or not payload.source_confirmed
    ):
        raise HTTPException(
            status_code=422,
            detail="Open and confirm the available official source before final disposition.",
        )
    now = _now()
    hit.disposition = payload.disposition
    hit.disposition_reason = payload.reason.strip()
    hit.reviewed_by_membership_id = locked.membership.id
    hit.reviewed_at = now
    hit.reviewer_decision_json = {
        "disposition": payload.disposition,
        "reason": payload.reason.strip(),
        "source_confirmed": payload.source_confirmed,
        "source_fingerprint": publication.source_fingerprint,
        "ai_was_advisory": hit.ai_advisory,
        "reviewed_at": now.isoformat(),
    }
    hit.deadline_confirmation_state = (
        "confirmed"
        if payload.source_confirmed and payload.disposition in ACTIONABLE_DISPOSITIONS
        else "pending_confirmation"
    )
    hit.version += 1
    if publication.supersedes_publication_id and payload.source_confirmed:
        prior = session.scalar(
            select(IpWatchHit).where(
                IpWatchHit.company_id == locked.company.id,
                IpWatchHit.profile_id == hit.profile_id,
                IpWatchHit.publication_id == publication.supersedes_publication_id,
            )
        )
        if prior is not None:
            prior.deadline_confirmation_state = "superseded"
            prior.version += 1
    record_from_context(
        session,
        locked,
        action="ip_watch.hit_disposed",
        target_type="ip_watch_hit",
        target_id=hit.id,
        metadata={
            "disposition": hit.disposition,
            "source_confirmed": payload.source_confirmed,
            "deadline_confirmation_state": hit.deadline_confirmation_state,
        },
    )
    session.commit()
    session.refresh(hit)
    return hit


def create_watch_handoff(
    session: Session,
    *,
    context: SessionContext,
    hit_id: str,
    payload: IpWatchHandoffRequest,
) -> IpWatchHandoff:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    hit, profile, publication, docket = _hit_context(
        session, context=locked, hit_id=hit_id, for_update=True
    )
    if hit.disposition not in ACTIONABLE_DISPOSITIONS:
        raise HTTPException(status_code=422, detail="Mark the hit relevant before opening action.")
    if publication.source_status != "available" or not hit.reviewer_decision_json.get(
        "source_confirmed"
    ):
        raise HTTPException(status_code=422, detail="Confirmed official source is required.")
    existing = session.scalar(
        select(IpWatchHandoff).where(
            IpWatchHandoff.company_id == locked.company.id,
            IpWatchHandoff.hit_id == hit.id,
            IpWatchHandoff.handoff_kind == payload.handoff_kind,
        )
    )
    if existing is not None:
        return existing
    evidence_note = (
        f"Watch hit {hit.id}; journal {publication.journal_number} dated "
        f"{publication.journal_date.isoformat()}; source {publication.source_url}; "
        f"review decision: {hit.disposition} - {hit.disposition_reason}."
    )
    target_type: str
    target_id: str
    if payload.handoff_kind == "opposition":
        proceeding = create_ip_proceeding(
            session,
            context=locked,
            docket_id=docket.id,
            payload=IpProceedingCreateRequest(
                application_id=payload.application_id or publication.application_id,
                proceeding_kind="opposition",
                side=payload.represented_side,
                office=publication.office,
                jurisdiction=publication.jurisdiction,
                origin_kind="watch_hit",
                stage="draft",
                source_pending_identifier_allocation=True,
            ),
            commit=False,
        )
        target_type, target_id = "ip_proceeding", proceeding.id
    elif payload.handoff_kind == "task":
        task = create_ip_shared_task(
            session,
            context=locked,
            payload=IpSharedTaskCreateRequest(
                docket_id=docket.id,
                title=payload.title or "Review watch hit",
                description=f"{payload.notes or ''}\n\n{evidence_note}".strip(),
                owner_membership_id=payload.assignee_membership_id,
                due_on=payload.due_on,
                priority="high",
            ),
            commit=False,
        )
        target_type, target_id = "matter_task", task.id
    elif payload.handoff_kind == "deadline":
        assert payload.due_on is not None
        deadline = create_ip_operational_deadline(
            session,
            context=locked,
            payload=IpOperationalDeadlineCreateRequest(
                docket_id=docket.id,
                source="custom",
                kind="opposition_window",
                title=payload.title or "Opposition window",
                notes=f"{payload.notes or ''}\n\n{evidence_note}".strip(),
                due_on=payload.due_on,
                assignee_membership_id=payload.assignee_membership_id,
            ),
            commit=False,
        )
        target_type, target_id = "matter_deadline", deadline.id
    elif payload.handoff_kind == "enforcement_matter":
        matter = create_matter(
            session,
            context=locked,
            payload=MatterCreateRequest(
                title=payload.title or "Trademark enforcement",
                matter_code=payload.matter_code or f"IP-WATCH-{hit.id[:8]}",
                matter_type="trademark_enforcement",
                opposing_party=publication.proprietor_name,
                practice_area="intellectual_property",
                forum_level="advisory",
                description=f"{payload.notes or ''}\n\n{evidence_note}".strip(),
                assignee_membership_id=payload.assignee_membership_id,
                responsible_lawyer_membership_id=payload.assignee_membership_id,
            ),
            commit=False,
            required_capability="matters:create",
        )
        session.refresh(docket)
        create_matter_link(
            session,
            context=locked,
            docket_id=docket.id,
            payload=IpMatterLinkCreateRequest(
                matter_id=matter.id,
                relation_role="enforcement",
                source_reference=publication.source_url,
                reason="Created from confirmed trademark watch hit.",
                expected_docket_updated_at=docket.updated_at,
            ),
            commit=False,
        )
        target_type, target_id = "matter", matter.id
    else:
        session.refresh(docket)
        event = append_ip_docket_event(
            session,
            context=locked,
            docket_id=docket.id,
            payload=IpDocketEventCreateRequest(
                expected_lifecycle_version=docket.lifecycle_version,
                event_kind="publication",
                source="system",
                source_reference=publication.id,
                effective_at=_now(),
                responsible_membership_id=(
                    payload.assignee_membership_id or profile.recipient_membership_ids_json[0]
                ),
                reason="Confirmed watch hit added to the client-report evidence queue.",
                evidence_refs=[publication.source_url],
                payload={
                    "client_report_item": True,
                    "watch_hit_id": hit.id,
                    "reviewer_decision": hit.reviewer_decision_json,
                    "source_snapshot": hit.source_snapshot_json,
                },
            ),
            commit=False,
        )
        target_type, target_id = "ip_docket_event", event.id
    handoff = IpWatchHandoff(
        company_id=locked.company.id,
        hit_id=hit.id,
        handoff_kind=payload.handoff_kind,
        status="completed",
        target_type=target_type,
        target_id=target_id,
        source_snapshot_json=hit.source_snapshot_json,
        reviewer_decision_json=hit.reviewer_decision_json,
        request_json=payload.model_dump(mode="json"),
        created_by_membership_id=locked.membership.id,
        completed_at=_now(),
    )
    session.add(handoff)
    hit.disposition = (
        "enforcement_opened"
        if payload.handoff_kind == "enforcement_matter"
        else "client_instruction"
        if payload.handoff_kind == "client_report_item"
        else hit.disposition
    )
    hit.version += 1
    session.flush()
    record_from_context(
        session,
        locked,
        action="ip_watch.handoff_completed",
        target_type="ip_watch_handoff",
        target_id=handoff.id,
        matter_id=target_id if target_type == "matter" else docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "hit_id": hit.id,
            "handoff_kind": handoff.handoff_kind,
            "canonical_target_type": target_type,
            "canonical_target_id": target_id,
        },
    )
    session.commit()
    session.refresh(handoff)
    return handoff


def list_watch_workspace(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str | None = None,
    limit: int = 100,
) -> IpWatchWorkspaceResponse:
    if docket_id:
        _docket_or_404(session, context=context, docket_id=docket_id, for_update=False)
    profile_statement = (
        select(IpWatchProfile)
        .join(
            IpDocketRecord,
            (IpDocketRecord.id == IpWatchProfile.docket_id)
            & (IpDocketRecord.company_id == IpWatchProfile.company_id),
        )
        .outerjoin(
            Matter,
            (Matter.id == IpDocketRecord.matter_id)
            & (Matter.company_id == IpDocketRecord.company_id),
        )
        .where(
            IpWatchProfile.company_id == context.company.id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
            visible_ip_dockets_filter(session, context=context),
        )
    )
    if docket_id:
        profile_statement = profile_statement.where(IpWatchProfile.docket_id == docket_id)
    profiles = list(
        session.scalars(profile_statement.order_by(IpWatchProfile.updated_at.desc()).limit(limit))
    )
    profile_ids = [item.id for item in profiles]
    hits = (
        list(
            session.scalars(
                select(IpWatchHit)
                .where(
                    IpWatchHit.company_id == context.company.id,
                    IpWatchHit.profile_id.in_(profile_ids),
                )
                .order_by(IpWatchHit.hit_date.desc(), IpWatchHit.created_at.desc())
                .limit(limit)
            )
        )
        if profile_ids
        else []
    )
    publication_ids = list(dict.fromkeys(hit.publication_id for hit in hits))
    publications = (
        list(
            session.scalars(
                select(IpJournalPublication)
                .where(
                    IpJournalPublication.company_id == context.company.id,
                    IpJournalPublication.id.in_(publication_ids),
                )
                .order_by(IpJournalPublication.journal_date.desc())
            )
        )
        if publication_ids
        else []
    )
    hit_ids = [item.id for item in hits]
    handoffs = (
        list(
            session.scalars(
                select(IpWatchHandoff)
                .where(
                    IpWatchHandoff.company_id == context.company.id,
                    IpWatchHandoff.hit_id.in_(hit_ids),
                )
                .order_by(IpWatchHandoff.created_at.desc())
            )
        )
        if hit_ids
        else []
    )
    runs = list(
        session.scalars(
            select(IpJournalIngestionRun)
            .where(IpJournalIngestionRun.company_id == context.company.id)
            .order_by(IpJournalIngestionRun.created_at.desc())
            .limit(20)
        )
    )
    return IpWatchWorkspaceResponse(
        profiles=[IpWatchProfileResponse.model_validate(item) for item in profiles],
        hits=[IpWatchHitResponse.model_validate(item) for item in hits],
        publications=[IpJournalPublicationResponse.model_validate(item) for item in publications],
        ingestion_runs=[IpJournalIngestionRunResponse.model_validate(item) for item in runs],
        handoffs=[IpWatchHandoffResponse.model_validate(item) for item in handoffs],
    )


def run_journal_watch_scheduler(
    session: Session,
    *,
    now: datetime | None = None,
) -> JournalWatchSchedulerResult:
    """Advance due watch profiles without inventing an external provider call."""

    current = now or _now()
    profiles = list(
        session.scalars(
            select(IpWatchProfile)
            .join(
                IpDocketRecord,
                (IpDocketRecord.id == IpWatchProfile.docket_id)
                & (IpDocketRecord.company_id == IpWatchProfile.company_id),
            )
            .outerjoin(
                Matter,
                (Matter.id == IpDocketRecord.matter_id)
                & (Matter.company_id == IpDocketRecord.company_id),
            )
            .where(
                IpWatchProfile.poll_status.in_(("active", "paused_cost_quota")),
                or_(
                    IpWatchProfile.next_poll_at.is_(None),
                    IpWatchProfile.next_poll_at <= current,
                ),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                or_(IpDocketRecord.matter_id.is_(None), Matter.is_active.is_(True)),
            )
            .order_by(IpWatchProfile.company_id, IpWatchProfile.id)
            .with_for_update(of=IpWatchProfile)
        )
    )
    checked = 0
    cost_paused = 0
    provider_paused = 0
    for profile in profiles:
        _reset_cost_period_if_due(profile, current)
        if (
            profile.max_cost_minor_per_period
            and profile.spent_cost_minor_in_period >= profile.max_cost_minor_per_period
        ):
            profile.poll_status = "paused_cost_quota"
            profile.pause_reason = (
                f"Cost quota {profile.max_cost_minor_per_period} {profile.cost_currency} "
                "minor units is exhausted."
            )
            _, period_end = _cost_period_bounds(profile.frequency, current)
            profile.next_poll_at = period_end
            profile.version += 1
            cost_paused += 1
            continue
        manual = profile.provider_key == "manual-journal"
        scheduler_key = f"scheduler:{profile.id}:{current.strftime('%Y%m%dT%H%M%SZ')}"
        request_sha256 = _fingerprint(
            {
                "profile_id": profile.id,
                "provider_key": profile.provider_key,
                "scheduled_at": current.isoformat(),
            }
        )
        run = IpJournalIngestionRun(
            company_id=profile.company_id,
            provider_key=profile.provider_key,
            idempotency_key=scheduler_key,
            request_sha256=request_sha256,
            status="succeeded" if manual else "failed",
            external_call=False,
            cost_minor=0,
            currency=profile.cost_currency,
            publications_seen=0,
            publications_created=0,
            hits_created=0,
            duplicate_hits=0,
            stale_source_alert=False,
            error_redacted=(
                None
                if manual
                else "Journal provider is not activated; no external call was attempted."
            ),
            requested_by_membership_id=profile.created_by_membership_id,
            started_at=current,
            completed_at=current,
        )
        session.add(run)
        profile.last_polled_at = current
        if manual:
            profile.next_poll_at = _next_poll(profile.frequency, current)
            checked += 1
        else:
            profile.poll_status = "paused"
            profile.pause_reason = (
                "Journal provider activation, licensing, and credentials are required."
            )
            profile.next_poll_at = None
            provider_paused += 1
        profile.version += 1
    session.commit()
    return JournalWatchSchedulerResult(
        due_profiles=len(profiles),
        checked_profiles=checked,
        cost_paused_profiles=cost_paused,
        provider_paused_profiles=provider_paused,
        external_calls=0,
    )
