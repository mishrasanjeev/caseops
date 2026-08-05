"""Fail-closed, versioned governance for statute source text."""

from __future__ import annotations

from datetime import UTC, datetime
from difflib import unified_diff
from hashlib import sha256

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Statute,
    StatuteSection,
    StatuteSourceConflict,
    StatuteSourceVersion,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import is_official_source_reference

AUTHORITATIVE_STATUSES = {"verified_official", "verified_licensed"}
ALLOWED_SOURCE_CATEGORIES = {
    "consolidated_statute",
    "enacted_legislation",
    "rule",
    "official_gazette",
    "office_direction",
}
ALLOWED_LEGAL_STATUSES = {"enacted", "advisory", "draft", "repealed"}


def _section_or_404(session: Session, section_id: str, *, lock: bool) -> StatuteSection:
    stmt = select(StatuteSection).where(StatuteSection.id == section_id)
    if lock:
        stmt = stmt.with_for_update()
    section = session.scalar(stmt)
    if section is None:
        raise HTTPException(status_code=404, detail="Statute section not found.")
    return section


def _validate_source_policy(
    *,
    source_status: str,
    source_url: str,
    source_policy: dict,
) -> None:
    if source_status == "official":
        if not is_official_source_reference(source_url):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="An official source must use an approved official HTTPS host.",
            )
        return
    if source_status != "licensed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Statutory text approval requires an official or licensed source.",
        )
    required = {"fetch", "cache", "display", "ai_retrieval", "retention", "deletion"}
    permitted = {
        str(value) for value in source_policy.get("permitted_uses", []) if value
    }
    if not source_policy.get("lawful_access_approved") or not required.issubset(permitted):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Licensed source terms are incomplete. Record approved fetch, cache, "
                "display, AI retrieval, retention, and deletion uses before review."
            ),
        )


def probe_statute_source(
    *,
    source_url: str,
    source_status: str,
    source_policy: dict,
    client: httpx.Client | None = None,
) -> tuple[str, str | None]:
    """Probe an approved source without following redirects or leaking response text."""

    _validate_source_policy(
        source_status=source_status,
        source_url=source_url,
        source_policy=source_policy,
    )
    if source_status == "licensed" and not source_policy.get("link_check_approved"):
        return "manual_required", "licensed_link_check_not_approved"
    owns_client = client is None
    http_client = client or httpx.Client(timeout=8.0, follow_redirects=False)
    try:
        response = http_client.head(
            source_url,
            headers={"User-Agent": "CaseOps-SourceHealth/1.0"},
        )
        if 200 <= response.status_code < 400:
            return "available", None
        if response.status_code in {401, 403}:
            return "protected", f"http_{response.status_code}"
        if response.status_code in {404, 410}:
            return "missing", f"http_{response.status_code}"
        if response.status_code == 429:
            return "rate_limited", "http_429"
        return "unavailable", f"http_{response.status_code}"
    except httpx.TimeoutException:
        return "unavailable", "timeout"
    except httpx.HTTPError:
        return "unavailable", "network_error"
    finally:
        if owns_client:
            http_client.close()


def propose_statute_source_version(
    session: Session,
    *,
    context: SessionContext,
    section_id: str,
    expected_source_version: int,
    candidate_text: str,
    source_url: str,
    source_publisher: str,
    issuing_body: str,
    source_category: str,
    source_status: str,
    legal_status: str,
    source_locator_type: str,
    exact_source_version: str,
    retrieved_at: datetime,
    publication_date,
    effective_from,
    effective_to,
    amendment_metadata: dict,
    source_policy: dict,
) -> StatuteSourceVersion:
    section = _section_or_404(session, section_id, lock=True)
    if section.source_version != expected_source_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Statute source version changed; reload before proposing.",
        )
    text_value = candidate_text.strip()
    if len(text_value) < 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Candidate statutory text is too short for review.",
        )
    if source_category not in ALLOWED_SOURCE_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unsupported legal source category.")
    if legal_status not in ALLOWED_LEGAL_STATUSES:
        raise HTTPException(status_code=422, detail="Unsupported legal status.")
    if legal_status != "enacted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft, advisory, or repealed material cannot activate statutory text.",
        )
    if source_locator_type != "section_deep_link":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A section-level deep link is required; an Act landing page is insufficient.",
        )
    statute = session.get(Statute, section.statute_id)
    if statute is None:
        raise HTTPException(status_code=409, detail="Parent statute is missing.")
    if statute.source_url and source_url.rstrip("/") == statute.source_url.rstrip("/"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The proposed URL is the Act landing page, not a section-level deep link.",
        )
    _validate_source_policy(
        source_status=source_status,
        source_url=source_url,
        source_policy=source_policy,
    )
    if effective_from and effective_to and effective_to < effective_from:
        raise HTTPException(status_code=422, detail="effective_to precedes effective_from.")
    if not exact_source_version.strip():
        raise HTTPException(status_code=422, detail="Exact source version is required.")

    proposed_version = section.source_version + 1
    existing = session.scalar(
        select(StatuteSourceVersion).where(
            StatuteSourceVersion.section_id == section.id,
            StatuteSourceVersion.proposed_source_version == proposed_version,
        )
    )
    if existing is not None:
        if existing.status == "pending":
            return existing
        raise HTTPException(
            status_code=409,
            detail="This source version was already reviewed; reload before proposing.",
        )
    diff = "".join(
        unified_diff(
            (section.section_text or "").splitlines(keepends=True),
            text_value.splitlines(keepends=True),
            fromfile=f"section-{section.source_version}",
            tofile=f"candidate-{proposed_version}",
            n=3,
        )
    )
    row = StatuteSourceVersion(
        section_id=section.id,
        proposed_source_version=proposed_version,
        candidate_text=text_value,
        candidate_sha256=sha256(text_value.encode("utf-8")).hexdigest(),
        source_url=source_url.strip(),
        source_publisher=source_publisher.strip(),
        issuing_body=issuing_body.strip(),
        source_category=source_category,
        source_status=source_status,
        legal_status=legal_status,
        source_locator_type=source_locator_type,
        exact_source_version=exact_source_version.strip(),
        retrieved_at=retrieved_at,
        publication_date=publication_date,
        effective_from=effective_from,
        effective_to=effective_to,
        amendment_metadata_json=dict(amendment_metadata),
        source_policy_json=dict(source_policy),
        diff_unified=diff[:50_000],
        status="pending",
        proposed_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="statute_source_version.proposed",
        target_type="statute_source_version",
        target_id=row.id,
        metadata={
            "section_id": section.id,
            "proposed_source_version": proposed_version,
            "candidate_sha256": row.candidate_sha256,
            "source_status": source_status,
            "source_category": source_category,
        },
    )
    session.commit()
    session.refresh(row)
    return row


def decide_statute_source_version(
    session: Session,
    *,
    context: SessionContext,
    proposal_id: str,
    expected_source_version: int,
    decision: str,
    reason: str,
    client: httpx.Client | None = None,
) -> StatuteSourceVersion:
    proposal = session.scalar(
        select(StatuteSourceVersion)
        .where(StatuteSourceVersion.id == proposal_id)
        .with_for_update()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Source proposal not found.")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Source proposal is already reviewed.")
    section = _section_or_404(session, proposal.section_id, lock=True)
    if section.source_version != expected_source_version:
        raise HTTPException(
            status_code=409,
            detail="Statute source version changed; reload before deciding.",
        )
    if proposal.proposed_by_membership_id == context.membership.id:
        raise HTTPException(
            status_code=409,
            detail="Two-person legal review is required; proposer cannot approve or reject.",
        )
    reason_value = reason.strip()
    if len(reason_value) < 5:
        raise HTTPException(status_code=422, detail="A review reason is required.")
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="Decision must be approve or reject.")

    now = datetime.now(UTC)
    proposal.reviewed_by_membership_id = context.membership.id
    proposal.reviewed_at = now
    proposal.review_reason = reason_value
    if decision == "reject":
        proposal.status = "rejected"
    else:
        health, health_error = probe_statute_source(
            source_url=proposal.source_url,
            source_status=proposal.source_status,
            source_policy=dict(proposal.source_policy_json or {}),
            client=client,
        )
        if health != "available":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Source link is {health}; preserve the proposal and use the manual "
                    "evidence path before approval."
                ),
            )
        for previous in session.scalars(
            select(StatuteSourceVersion).where(
                StatuteSourceVersion.section_id == section.id,
                StatuteSourceVersion.status == "approved",
            )
        ):
            previous.status = "superseded"
        proposal.status = "approved"
        section.section_text = proposal.candidate_text
        section.section_text_source = (
            "official_source"
            if proposal.source_status == "official"
            else "licensed_source"
        )
        section.section_text_fetched_at = proposal.retrieved_at
        section.verification_status = (
            "verified_official"
            if proposal.source_status == "official"
            else "verified_licensed"
        )
        section.source_sha256 = proposal.candidate_sha256
        section.source_publisher = proposal.source_publisher
        section.issuing_body = proposal.issuing_body
        section.source_category = proposal.source_category
        section.source_status = proposal.source_status
        section.legal_status = proposal.legal_status
        section.publication_date = proposal.publication_date
        section.effective_from = proposal.effective_from
        section.effective_to = proposal.effective_to
        section.amendment_metadata_json = dict(proposal.amendment_metadata_json or {})
        section.history_status = (
            "versioned_history"
            if proposal.amendment_metadata_json
            else "current_text_only"
        )
        section.exact_source_version = proposal.exact_source_version
        section.source_locator_type = proposal.source_locator_type
        section.source_policy_json = dict(proposal.source_policy_json or {})
        section.link_health_status = health
        section.link_last_checked_at = now
        section.link_last_error = health_error
        section.section_url = proposal.source_url
        section.source_version = proposal.proposed_source_version
        section.verified_at = now
        section.verified_by_membership_id = context.membership.id
        section.quarantined_at = None
        section.quarantine_reason = None
        section.is_provisional = False
    record_from_context(
        session,
        context,
        action="statute_source_version.reviewed",
        target_type="statute_source_version",
        target_id=proposal.id,
        result=proposal.status,
        metadata={
            "section_id": section.id,
            "source_version": proposal.proposed_source_version,
            "candidate_sha256": proposal.candidate_sha256,
            "two_person_review": True,
        },
    )
    session.commit()
    session.refresh(proposal)
    return proposal


def check_statute_section_link(
    session: Session,
    *,
    context: SessionContext,
    section_id: str,
    client: httpx.Client | None = None,
) -> StatuteSection:
    section = _section_or_404(session, section_id, lock=True)
    if section.source_locator_type != "section_deep_link" or not section.section_url:
        health, health_error = "missing", "section_deep_link_unavailable"
    else:
        health, health_error = probe_statute_source(
            source_url=section.section_url,
            source_status=section.source_status,
            source_policy=dict(section.source_policy_json or {}),
            client=client,
        )
    section.link_health_status = health
    section.link_last_checked_at = datetime.now(UTC)
    section.link_last_error = health_error
    record_from_context(
        session,
        context,
        action="statute_source_link.checked",
        target_type="statute_section",
        target_id=section.id,
        result=health,
        metadata={"source_version": section.source_version, "health": health},
    )
    session.commit()
    session.refresh(section)
    return section


def create_statute_source_conflict(
    session: Session,
    *,
    context: SessionContext,
    section_id: str,
    expected_source_version: int,
    disputed_facts: dict,
    source_versions: list,
    authority_rank: dict,
    affected_records: list,
    impact_scan: dict,
) -> StatuteSourceConflict:
    section = _section_or_404(session, section_id, lock=True)
    if section.source_version != expected_source_version:
        raise HTTPException(status_code=409, detail="Statute source version changed.")
    if not disputed_facts or len(source_versions) < 2 or not authority_rank:
        raise HTTPException(
            status_code=422,
            detail="Conflict requires disputed facts, at least two versions, and authority rank.",
        )
    conflict = StatuteSourceConflict(
        section_id=section.id,
        disputed_facts_json=dict(disputed_facts),
        source_versions_json=list(source_versions),
        authority_rank_json=dict(authority_rank),
        affected_records_json=list(affected_records),
        impact_scan_json=dict(impact_scan),
        status="open",
        created_by_membership_id=context.membership.id,
    )
    session.add(conflict)
    section.verification_status = "quarantined"
    section.quarantined_at = datetime.now(UTC)
    section.quarantine_reason = "Credible source conflict pending curator/legal decision."
    section.source_version += 1
    session.flush()
    record_from_context(
        session,
        context,
        action="statute_source_conflict.opened",
        target_type="statute_source_conflict",
        target_id=conflict.id,
        result="quarantined",
        metadata={
            "section_id": section.id,
            "source_version": section.source_version,
            "affected_record_count": len(affected_records),
        },
    )
    session.commit()
    session.refresh(conflict)
    return conflict


def decide_statute_source_conflict(
    session: Session,
    *,
    context: SessionContext,
    conflict_id: str,
    decision: str,
) -> StatuteSourceConflict:
    conflict = session.scalar(
        select(StatuteSourceConflict)
        .where(StatuteSourceConflict.id == conflict_id)
        .with_for_update()
    )
    if conflict is None:
        raise HTTPException(status_code=404, detail="Source conflict not found.")
    if conflict.status != "open":
        raise HTTPException(status_code=409, detail="Source conflict is already decided.")
    if conflict.created_by_membership_id == context.membership.id:
        raise HTTPException(
            status_code=409,
            detail="A different legal reviewer must decide this source conflict.",
        )
    decision_value = decision.strip()
    if len(decision_value) < 10:
        raise HTTPException(status_code=422, detail="A substantive legal decision is required.")
    conflict.status = "decided"
    conflict.decision = decision_value
    conflict.decision_by_membership_id = context.membership.id
    conflict.decided_at = datetime.now(UTC)
    record_from_context(
        session,
        context,
        action="statute_source_conflict.decided",
        target_type="statute_source_conflict",
        target_id=conflict.id,
        result="decided",
        metadata={"section_id": conflict.section_id},
    )
    session.commit()
    session.refresh(conflict)
    return conflict
