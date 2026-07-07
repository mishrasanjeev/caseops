"""Pre-engagement conflict-of-interest scanner (PG-001).

Surface every potential overlap between a matter's opposing/related
parties and existing clients, matters, and contacts in the same tenant.
A partner reviews the candidates and records `cleared`, `conflicted`, or
`waived`. The intake gate blocks matter status promotion until the latest
check is `cleared` or `waived`.

The matcher is deliberately simple for v1: case-insensitive normalised
substring match + Jaccard token overlap on length-≥2 tokens. False
positives are preferred over false negatives — partners can dismiss a
spurious match in two clicks; missing a real conflict is the bug we
cannot afford.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    Matter,
    MatterConflictCheck,
    MatterConflictCheckStatus,
)
from caseops_api.schemas.conflicts import (
    ConflictCandidate,
    ConflictCheckRecord,
    ConflictCheckResolveRequest,
    ConflictCheckRunRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.session_context import SessionContext

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GATE_ALLOWED_STATUSES = {
    MatterConflictCheckStatus.CLEARED.value,
    MatterConflictCheckStatus.WAIVED.value,
}


@dataclass(frozen=True)
class ConflictGateDecision:
    allowed: bool
    reason: str
    latest_check_id: str | None = None
    latest_status: str | None = None
    latest_ran_at: datetime | None = None


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.lower().strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(_normalise(text)) if len(t) >= 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _score(query_name: str, candidate_name: str | None) -> tuple[float, str | None]:
    """Return (similarity, overlap_reason) for a name pair.

    Substring + Jaccard with a 0.5 floor keeps "Tata Sons" matching
    "Tata Sons Pvt Ltd" while rejecting "Tata Steel" against "Bata
    Sons". Partners can still dismiss low-quality matches manually.
    """
    if not candidate_name:
        return 0.0, None
    q = _normalise(query_name)
    c = _normalise(candidate_name)
    if not q or not c:
        return 0.0, None
    if q == c:
        return 1.0, "exact name match"
    if q in c or c in q:
        return 0.85, "substring match"
    qt = _tokens(query_name)
    ct = _tokens(candidate_name)
    overlap = _jaccard(qt, ct)
    if overlap >= 0.5:
        shared = sorted(qt & ct)
        return overlap, f"shared tokens: {', '.join(shared)}"
    return 0.0, None


def _scan_clients(
    session: Session,
    *,
    company_id: str,
    query_names: list[str],
) -> list[ConflictCandidate]:
    """Find Client rows whose name overlaps any query name."""
    rows = list(
        session.scalars(
            select(Client).where(Client.company_id == company_id)
        )
    )
    out: list[ConflictCandidate] = []
    for client in rows:
        for q in query_names:
            sim, reason = _score(q, client.name)
            if sim >= 0.5 and reason is not None:
                out.append(
                    ConflictCandidate(
                        kind="client",
                        id=str(client.id),
                        name=client.name or "(no name)",
                        overlap_reason=f'"{q}" ↔ {reason}',
                        similarity=round(sim, 3),
                    )
                )
                break
    return out


def _scan_matters(
    session: Session,
    *,
    company_id: str,
    exclude_matter_id: str,
    query_names: list[str],
) -> list[ConflictCandidate]:
    """Find existing Matter rows where client_name or opposing_party
    overlaps any query name. Skip the matter being checked itself."""
    rows = list(
        session.scalars(
            select(Matter).where(
                Matter.company_id == company_id,
                Matter.id != exclude_matter_id,
                or_(
                    Matter.client_name.is_not(None),
                    Matter.opposing_party.is_not(None),
                ),
            )
        )
    )
    out: list[ConflictCandidate] = []
    for matter in rows:
        for q in query_names:
            for col_name, value in (
                ("client", matter.client_name),
                ("opposing_party", matter.opposing_party),
            ):
                sim, reason = _score(q, value)
                if sim >= 0.5 and reason is not None:
                    out.append(
                        ConflictCandidate(
                            kind="matter",
                            id=str(matter.id),
                            name=f"{matter.matter_code}: {value}",
                            overlap_reason=f'"{q}" ↔ {col_name} ({reason})',
                            similarity=round(sim, 3),
                        )
                    )
                    break
            else:
                continue
            break
    return out


def _load_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id, Matter.company_id == context.company.id
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _record(check: MatterConflictCheck) -> ConflictCheckRecord:
    candidates_raw = json.loads(check.candidates_json or "[]")
    return ConflictCheckRecord(
        id=check.id,
        matter_id=check.matter_id,
        opposing_party_name=check.opposing_party_name,
        related_party_names=json.loads(check.related_party_names_json or "[]"),
        candidates=[ConflictCandidate(**c) for c in candidates_raw],
        status=check.status,  # type: ignore[arg-type]
        resolution_note=check.resolution_note,
        resolved_by_membership_id=check.resolved_by_membership_id,
        resolved_at=check.resolved_at,
        ran_by_membership_id=check.ran_by_membership_id,
        ran_at=check.ran_at,
        created_at=check.created_at,
    )


def run_conflict_check(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: ConflictCheckRunRequest,
) -> ConflictCheckRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)

    query_names: list[str] = [payload.opposing_party_name.strip()]
    for related in payload.related_party_names:
        cleaned = related.strip()
        if cleaned:
            query_names.append(cleaned)
    query_names = list(dict.fromkeys(query_names))  # dedup, keep order

    candidates: list[ConflictCandidate] = []
    candidates.extend(
        _scan_clients(
            session, company_id=context.company.id, query_names=query_names,
        )
    )
    candidates.extend(
        _scan_matters(
            session,
            company_id=context.company.id,
            exclude_matter_id=matter.id,
            query_names=query_names,
        )
    )
    # Dedup by (kind, id) — a single source can match multiple query names.
    seen: set[tuple[str, str]] = set()
    deduped: list[ConflictCandidate] = []
    for c in candidates:
        key = (c.kind, c.id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    deduped.sort(key=lambda c: c.similarity, reverse=True)

    initial_status = (
        MatterConflictCheckStatus.PENDING
        if deduped
        else MatterConflictCheckStatus.CLEARED
    )

    now = datetime.now(UTC)
    check = MatterConflictCheck(
        company_id=context.company.id,
        matter_id=matter.id,
        ran_by_membership_id=context.membership.id,
        opposing_party_name=payload.opposing_party_name.strip()[:255],
        related_party_names_json=json.dumps([n for n in query_names[1:]]),
        candidates_json=json.dumps([c.model_dump() for c in deduped]),
        status=initial_status,
        ran_at=now,
        # No-conflict scans auto-resolve with the same actor + timestamp;
        # partner review is reserved for the cases that actually need it.
        resolved_by_membership_id=(
            context.membership.id if initial_status == MatterConflictCheckStatus.CLEARED else None
        ),
        resolved_at=now if initial_status == MatterConflictCheckStatus.CLEARED else None,
    )
    session.add(check)
    session.flush()

    record_from_context(
        session,
        context,
        action="conflict_check.ran",
        target_type="matter_conflict_check",
        target_id=check.id,
        matter_id=matter.id,
        metadata={
            "candidate_count": len(deduped),
            "initial_status": initial_status,
        },
    )
    session.commit()
    session.refresh(check)
    return _record(check)


def list_conflict_checks(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> list[ConflictCheckRecord]:
    _load_matter(session, context=context, matter_id=matter_id)
    rows = list(
        session.scalars(
            select(MatterConflictCheck)
            .where(
                MatterConflictCheck.company_id == context.company.id,
                MatterConflictCheck.matter_id == matter_id,
            )
            .order_by(MatterConflictCheck.ran_at.desc())
        )
    )
    return [_record(r) for r in rows]


def evaluate_matter_opening_gate(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    expected_opposing_party_name: str | None = None,
) -> ConflictGateDecision:
    """Return whether the latest conflict check permits intake -> active.

    PG-001 gates matter opening on the latest tenant/matter-scoped check.
    Older clear checks are intentionally stale once a newer pending or
    conflicted check exists.
    """
    latest = session.scalar(
        select(MatterConflictCheck)
        .where(
            MatterConflictCheck.company_id == company_id,
            MatterConflictCheck.matter_id == matter_id,
        )
        .order_by(
            MatterConflictCheck.ran_at.desc(),
            MatterConflictCheck.created_at.desc(),
            MatterConflictCheck.id.desc(),
        )
        .limit(1)
    )
    if latest is None:
        return ConflictGateDecision(allowed=False, reason="missing_check")

    if latest.status in _GATE_ALLOWED_STATUSES:
        if (
            expected_opposing_party_name
            and _normalise(latest.opposing_party_name)
            != _normalise(expected_opposing_party_name)
        ):
            return ConflictGateDecision(
                allowed=False,
                reason="stale_party_scope",
                latest_check_id=latest.id,
                latest_status=latest.status,
                latest_ran_at=latest.ran_at,
            )
        reason = (
            "clear"
            if latest.status == MatterConflictCheckStatus.CLEARED.value
            else "waived"
        )
        return ConflictGateDecision(
            allowed=True,
            reason=reason,
            latest_check_id=latest.id,
            latest_status=latest.status,
            latest_ran_at=latest.ran_at,
        )

    reason = "requires_review"
    if latest.status == MatterConflictCheckStatus.CONFLICTED.value:
        reason = "possible_conflict"
    return ConflictGateDecision(
        allowed=False,
        reason=reason,
        latest_check_id=latest.id,
        latest_status=latest.status,
        latest_ran_at=latest.ran_at,
    )


def resolve_conflict_check(
    session: Session,
    *,
    context: SessionContext,
    check_id: str,
    payload: ConflictCheckResolveRequest,
) -> ConflictCheckRecord:
    check = session.scalar(
        select(MatterConflictCheck).where(
            MatterConflictCheck.id == check_id,
            MatterConflictCheck.company_id == context.company.id,
        )
    )
    if check is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conflict check not found.",
        )
    # Ensure the actor can access the matter — tenant scope alone isn't
    # enough; matter-level ACL also gates resolution.
    matter = _load_matter(
        session, context=context, matter_id=check.matter_id
    )

    if check.status not in {
        MatterConflictCheckStatus.PENDING,
        MatterConflictCheckStatus.CLEARED,
    }:
        # Allow re-decision only when not already terminally conflicted/waived.
        # If a partner needs to revisit a "conflicted" call, run a fresh check.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Conflict check is already {check.status}. Run a fresh check "
                "instead of re-resolving this one."
            ),
        )

    if payload.status == "waived" and not (payload.resolution_note or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A waiver requires a resolution_note explaining the basis.",
        )

    check.status = payload.status  # type: ignore[assignment]
    check.resolution_note = (payload.resolution_note or None)
    check.resolved_by_membership_id = context.membership.id
    check.resolved_at = datetime.now(UTC)
    session.flush()

    record_from_context(
        session,
        context,
        action="conflict_check.resolved",
        target_type="matter_conflict_check",
        target_id=check.id,
        matter_id=matter.id,
        metadata={"status": payload.status},
    )
    session.commit()
    session.refresh(check)
    return _record(check)


__all__ = [
    "ConflictGateDecision",
    "evaluate_matter_opening_gate",
    "list_conflict_checks",
    "resolve_conflict_check",
    "run_conflict_check",
]
