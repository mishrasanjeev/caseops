"""Canonical judge mapping and curator operations for IPLF-060A.

This module extends the existing Court/Judge/AuthorityDocument owners. It never
copies authority records and never treats a free-text coincidence as a certain
mapping.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    Bench,
    BenchAlias,
    Court,
    Judge,
    JudgeAlias,
    JudgeAppointment,
    JudgeAuthorityAffinity,
    JudgeDecisionIndex,
    JudgeMappingReview,
    JudgeStatuteFocus,
)
from caseops_api.services.judge_aliases import MatchResult, match_candidates, normalise

RESOLVER_VERSION = "judge-alias-v2"
ANALYTICS_CONFIDENCE = frozenset({"exact", "initial_surname", "curator_confirmed"})


class JudgeMappingError(ValueError):
    pass


class JudgeMappingConflict(JudgeMappingError):
    pass


@dataclass(frozen=True)
class RawJudgeResolution:
    raw_judge_name: str
    source_ordinal: int
    status: str
    court_id: str | None
    match: MatchResult | None = None
    candidates: tuple[MatchResult, ...] = ()


@dataclass
class AuthorityRemapSummary:
    authority_document_id: str
    mapped: int = 0
    inserted: int = 0
    collisions: int = 0
    unresolved: int = 0
    review_ids: list[str] = field(default_factory=list)


def _authority_judge_names(document: AuthorityDocument) -> list[str]:
    if not document.judges_json:
        return []
    try:
        payload = json.loads(document.judges_json)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item.strip() for item in payload if isinstance(item, str) and item.strip()]


def resolve_authority_court(session: Session, document: AuthorityDocument) -> Court | None:
    """Resolve a source court name against the canonical court catalog."""
    needle = normalise(document.court_name)
    if not needle:
        return None
    courts = list(session.scalars(select(Court).where(Court.is_active.is_(True))))
    exact = [
        court
        for court in courts
        if needle in {normalise(court.name), normalise(court.short_name)}
    ]
    if len(exact) == 1:
        return exact[0]
    contained = [
        court
        for court in courts
        if normalise(court.name) in needle or needle in normalise(court.name)
    ]
    return contained[0] if len(contained) == 1 else None


def resolve_raw_judge(
    session: Session,
    *,
    raw_judge_name: str,
    source_ordinal: int,
    court_id: str | None,
) -> RawJudgeResolution:
    if court_id is None:
        return RawJudgeResolution(
            raw_judge_name=raw_judge_name,
            source_ordinal=source_ordinal,
            status="unresolved_court",
            court_id=None,
        )
    candidates = tuple(
        match_candidates(session, raw_text=raw_judge_name, court_id=court_id)
    )
    if not candidates:
        return RawJudgeResolution(
            raw_judge_name=raw_judge_name,
            source_ordinal=source_ordinal,
            status="unresolved",
            court_id=court_id,
        )
    if len(candidates) > 1:
        return RawJudgeResolution(
            raw_judge_name=raw_judge_name,
            source_ordinal=source_ordinal,
            status="collision",
            court_id=court_id,
            candidates=candidates,
        )
    return RawJudgeResolution(
        raw_judge_name=raw_judge_name,
        source_ordinal=source_ordinal,
        status="mapped",
        court_id=court_id,
        match=candidates[0],
        candidates=candidates,
    )


def _upsert_review(
    session: Session,
    *,
    document: AuthorityDocument,
    resolution: RawJudgeResolution,
) -> JudgeMappingReview:
    normalised = normalise(resolution.raw_judge_name)
    review = session.scalar(
        select(JudgeMappingReview).where(
            JudgeMappingReview.authority_document_id == document.id,
            JudgeMappingReview.source_ordinal == resolution.source_ordinal,
            JudgeMappingReview.raw_judge_name_normalised == normalised,
        )
    )
    candidate_ids = [candidate.judge_id for candidate in resolution.candidates]
    if review is None:
        review = JudgeMappingReview(
            authority_document_id=document.id,
            court_id=resolution.court_id,
            raw_judge_name=resolution.raw_judge_name,
            raw_judge_name_normalised=normalised,
            source_ordinal=resolution.source_ordinal,
            reason=resolution.status,
            candidate_judge_ids_json=candidate_ids,
            status="open",
            resolver_version=RESOLVER_VERSION,
        )
        session.add(review)
    elif review.status != "resolved":
        review.court_id = resolution.court_id
        review.reason = resolution.status
        review.candidate_judge_ids_json = candidate_ids
        review.status = "open"
        review.resolver_version = RESOLVER_VERSION
        review.record_version += 1
    session.flush()
    return review


def _close_review_after_automatic_match(
    session: Session,
    *,
    document: AuthorityDocument,
    resolution: RawJudgeResolution,
) -> None:
    if resolution.match is None:
        return
    review = session.scalar(
        select(JudgeMappingReview).where(
            JudgeMappingReview.authority_document_id == document.id,
            JudgeMappingReview.source_ordinal == resolution.source_ordinal,
            JudgeMappingReview.raw_judge_name_normalised
            == normalise(resolution.raw_judge_name),
            JudgeMappingReview.status.in_(["open", "superseded"]),
        )
    )
    if review is None:
        return
    review.status = "auto_resolved"
    review.resolved_judge_id = resolution.match.judge_id
    review.resolution_note = "Resolver produced one candidate after catalog change."
    review.resolved_at = datetime.now(UTC)
    review.resolver_version = RESOLVER_VERSION
    review.record_version += 1


def rebuild_authority_mapping(
    session: Session,
    *,
    authority_document_id: str,
    commit: bool = True,
) -> AuthorityRemapSummary:
    document = session.scalar(
        select(AuthorityDocument).where(AuthorityDocument.id == authority_document_id)
    )
    if document is None:
        raise JudgeMappingError("Authority document not found.")
    court = resolve_authority_court(session, document)
    names = _authority_judge_names(document)
    summary = AuthorityRemapSummary(authority_document_id=document.id)

    for review in session.scalars(
        select(JudgeMappingReview).where(
            JudgeMappingReview.authority_document_id == document.id,
            JudgeMappingReview.status.in_(["open", "auto_resolved"]),
        )
    ):
        review.status = "superseded"
        review.resolution_note = "Raw authority evidence was reprocessed."
        review.record_version += 1

    # Curator-confirmed rows survive an automatic rebuild. Automatic rows are
    # reconciled in place so unchanged evidence keeps stable IDs/timestamps.
    automatic_by_judge = {
        row.judge_id: row
        for row in session.scalars(
            select(JudgeDecisionIndex).where(
                JudgeDecisionIndex.authority_document_id == document.id,
                JudgeDecisionIndex.mapping_status != "curator_confirmed",
            )
        )
    }

    existing_curated = {
        (row.source_ordinal, normalise(row.raw_judge_name or "")): row
        for row in session.scalars(
            select(JudgeDecisionIndex).where(
                JudgeDecisionIndex.authority_document_id == document.id,
                JudgeDecisionIndex.mapping_status == "curator_confirmed",
            )
        )
    }
    mapped_judge_ids = {row.judge_id for row in existing_curated.values()}
    for ordinal, raw_name in enumerate(names):
        key = (ordinal, normalise(raw_name))
        if key in existing_curated:
            summary.mapped += 1
            continue
        resolution = resolve_raw_judge(
            session,
            raw_judge_name=raw_name,
            source_ordinal=ordinal,
            court_id=court.id if court else None,
        )
        if resolution.match is None:
            review = _upsert_review(session, document=document, resolution=resolution)
            summary.review_ids.append(review.id)
            if resolution.status == "collision":
                summary.collisions += 1
            else:
                summary.unresolved += 1
            continue

        match = resolution.match
        if match.judge_id in mapped_judge_ids:
            _close_review_after_automatic_match(
                session, document=document, resolution=resolution
            )
            continue
        mapping = automatic_by_judge.pop(match.judge_id, None)
        if mapping is None:
            mapping = JudgeDecisionIndex(
                judge_id=match.judge_id,
                authority_document_id=document.id,
            )
            session.add(mapping)
            summary.inserted += 1
        mapping.role = "sat_on"
        mapping.year = document.decision_date.year if document.decision_date else None
        mapping.matched_alias = match.matched_alias
        mapping.match_confidence = match.confidence
        mapping.raw_judge_name = raw_name
        mapping.source_ordinal = ordinal
        mapping.mapping_status = "auto_confirmed"
        mapping.resolver_version = RESOLVER_VERSION
        mapping.evidence_json = {
            "authority_document_id": document.id,
            "raw_judge_name": raw_name,
            "source": document.source,
            "source_reference": document.source_reference,
        }
        mapping.is_analytics_eligible = match.confidence in ANALYTICS_CONFIDENCE
        mapped_judge_ids.add(match.judge_id)
        _close_review_after_automatic_match(
            session, document=document, resolution=resolution
        )
        summary.mapped += 1
    for stale_mapping in automatic_by_judge.values():
        session.delete(stale_mapping)
    session.flush()
    if commit:
        session.commit()
    return summary


def resolve_mapping_review(
    session: Session,
    *,
    review_id: str,
    judge_id: str,
    expected_record_version: int,
    membership_id: str,
    note: str,
    commit: bool = True,
) -> JudgeMappingReview:
    review = session.scalar(
        select(JudgeMappingReview)
        .where(JudgeMappingReview.id == review_id)
        .with_for_update()
    )
    if review is None:
        raise JudgeMappingError("Judge mapping review not found.")
    if review.record_version != expected_record_version:
        raise JudgeMappingConflict("Judge mapping review changed; reload and retry.")
    if review.status not in {"open", "auto_resolved"}:
        raise JudgeMappingConflict("Judge mapping review is already closed.")
    judge = session.scalar(select(Judge).where(Judge.id == judge_id).with_for_update())
    if judge is None or not judge.is_active or judge.merged_into_judge_id is not None:
        raise JudgeMappingError("Selected canonical judge is unavailable.")
    if review.court_id and judge.court_id != review.court_id:
        raise JudgeMappingError("Selected judge does not belong to the mapped court.")

    competing_mappings = list(
        session.scalars(
            select(JudgeDecisionIndex)
            .where(
                JudgeDecisionIndex.authority_document_id
                == review.authority_document_id,
                JudgeDecisionIndex.source_ordinal == review.source_ordinal,
                JudgeDecisionIndex.judge_id != judge.id,
            )
            .with_for_update()
        )
    )
    if any(
        mapping.mapping_status == "curator_confirmed"
        for mapping in competing_mappings
    ):
        raise JudgeMappingConflict(
            "This authority evidence slot already has a curator-confirmed mapping."
        )
    for mapping in competing_mappings:
        session.delete(mapping)

    existing = session.scalar(
        select(JudgeDecisionIndex).where(
            JudgeDecisionIndex.judge_id == judge.id,
            JudgeDecisionIndex.authority_document_id == review.authority_document_id,
        )
    )
    if existing is None:
        document = session.scalar(
            select(AuthorityDocument).where(
                AuthorityDocument.id == review.authority_document_id
            )
        )
        if document is None:
            raise JudgeMappingError("Authority document not found.")
        existing = JudgeDecisionIndex(
            judge_id=judge.id,
            authority_document_id=document.id,
            role="sat_on",
            year=document.decision_date.year if document.decision_date else None,
            matched_alias=review.raw_judge_name,
            match_confidence="curator_confirmed",
            raw_judge_name=review.raw_judge_name,
            source_ordinal=review.source_ordinal,
            mapping_status="curator_confirmed",
            resolver_version=RESOLVER_VERSION,
            evidence_json={"review_id": review.id, "note": note},
            is_analytics_eligible=True,
        )
        session.add(existing)
    else:
        existing.raw_judge_name = review.raw_judge_name
        existing.source_ordinal = review.source_ordinal
        existing.matched_alias = review.raw_judge_name
        existing.match_confidence = "curator_confirmed"
        existing.mapping_status = "curator_confirmed"
        existing.resolver_version = RESOLVER_VERSION
        existing.evidence_json = {"review_id": review.id, "note": note}
        existing.is_analytics_eligible = True

    review.status = "resolved"
    review.resolved_judge_id = judge.id
    review.resolution_note = note
    review.resolved_by_membership_id = membership_id
    review.resolved_at = datetime.now(UTC)
    review.record_version += 1
    session.flush()
    if commit:
        session.commit()
        session.refresh(review)
    return review


def add_judge_alias(
    session: Session,
    *,
    judge_id: str,
    alias_text: str,
    source: str,
    source_url: str | None,
    source_evidence_text: str | None,
    commit: bool = True,
) -> JudgeAlias:
    judge = session.scalar(select(Judge).where(Judge.id == judge_id).with_for_update())
    if judge is None or not judge.is_active or judge.merged_into_judge_id is not None:
        raise JudgeMappingError("Canonical judge not found.")
    alias_normalised = normalise(alias_text)
    if not alias_normalised:
        raise JudgeMappingError("Alias cannot be empty.")
    collision = session.scalar(
        select(JudgeAlias)
        .join(Judge, Judge.id == JudgeAlias.judge_id)
        .where(
            JudgeAlias.alias_normalised == alias_normalised,
            JudgeAlias.is_active.is_(True),
            JudgeAlias.judge_id != judge.id,
            Judge.court_id == judge.court_id,
            Judge.is_active.is_(True),
        )
    )
    if collision is not None:
        raise JudgeMappingConflict(
            "Alias already resolves to another active judge in this court."
        )
    existing = session.scalar(
        select(JudgeAlias).where(
            JudgeAlias.judge_id == judge.id,
            JudgeAlias.alias_normalised == alias_normalised,
        )
    )
    if existing is not None:
        existing.alias_text = alias_text.strip()
        existing.source = source
        existing.source_url = source_url
        existing.source_evidence_text = source_evidence_text
        existing.is_active = True
        existing.record_version += 1
        alias = existing
    else:
        alias = JudgeAlias(
            judge_id=judge.id,
            alias_text=alias_text.strip(),
            alias_normalised=alias_normalised,
            source=source,
            source_url=source_url,
            source_evidence_text=source_evidence_text,
        )
        session.add(alias)
    judge.identity_version += 1
    judge.record_version += 1

    affected_authority_ids = set(
        session.scalars(
            select(JudgeMappingReview.authority_document_id).where(
                JudgeMappingReview.raw_judge_name_normalised == alias_normalised,
                JudgeMappingReview.court_id == judge.court_id,
                JudgeMappingReview.status.in_(["open", "superseded"]),
            )
        )
    )
    session.flush()
    for authority_document_id in affected_authority_ids:
        rebuild_authority_mapping(
            session,
            authority_document_id=authority_document_id,
            commit=False,
        )
    session.flush()
    if commit:
        session.commit()
        session.refresh(alias)
    return alias


def add_bench_alias(
    session: Session,
    *,
    bench_id: str,
    alias_text: str,
    source: str,
    source_url: str | None,
    commit: bool = True,
) -> BenchAlias:
    bench = session.scalar(select(Bench).where(Bench.id == bench_id).with_for_update())
    if bench is None:
        raise JudgeMappingError("Canonical bench not found.")
    alias_normalised = normalise(alias_text)
    if not alias_normalised:
        raise JudgeMappingError("Alias cannot be empty.")
    collision = session.scalar(
        select(BenchAlias)
        .join(Bench, Bench.id == BenchAlias.bench_id)
        .where(
            BenchAlias.alias_normalised == alias_normalised,
            BenchAlias.is_active.is_(True),
            BenchAlias.bench_id != bench.id,
            Bench.court_id == bench.court_id,
        )
    )
    if collision is not None:
        raise JudgeMappingConflict(
            "Alias already resolves to another bench in this court."
        )
    existing = session.scalar(
        select(BenchAlias).where(
            BenchAlias.bench_id == bench.id,
            BenchAlias.alias_normalised == alias_normalised,
        )
    )
    if existing is None:
        alias = BenchAlias(
            bench_id=bench.id,
            alias_text=alias_text.strip(),
            alias_normalised=alias_normalised,
            source=source,
            source_url=source_url,
        )
        session.add(alias)
    else:
        alias = existing
        alias.alias_text = alias_text.strip()
        alias.source = source
        alias.source_url = source_url
        alias.is_active = True
        alias.record_version += 1
    bench.record_version += 1
    session.flush()
    if commit:
        session.commit()
        session.refresh(alias)
    return alias


def merge_duplicate_judges(
    session: Session,
    *,
    source_judge_id: str,
    destination_judge_id: str,
    expected_source_version: int,
    expected_destination_version: int,
    commit: bool = True,
) -> Judge:
    if source_judge_id == destination_judge_id:
        raise JudgeMappingError("A judge cannot be merged into itself.")
    judges = list(
        session.scalars(
            select(Judge)
            .where(Judge.id.in_([source_judge_id, destination_judge_id]))
            .order_by(Judge.id)
            .with_for_update()
        )
    )
    by_id = {judge.id: judge for judge in judges}
    source = by_id.get(source_judge_id)
    destination = by_id.get(destination_judge_id)
    if source is None or destination is None:
        raise JudgeMappingError("Judge not found.")
    if not source.is_active or source.merged_into_judge_id is not None:
        raise JudgeMappingConflict("Source judge is already inactive or merged.")
    if not destination.is_active or destination.merged_into_judge_id is not None:
        raise JudgeMappingConflict("Destination judge is not canonical and active.")
    if (
        source.record_version != expected_source_version
        or destination.record_version != expected_destination_version
    ):
        raise JudgeMappingConflict("Judge identity changed; reload and retry.")

    # Serialize aliases in the destination court before changing ownership. The
    # database uniqueness key is per judge, while identity resolution requires
    # an active alias to identify at most one judge in a court.
    list(
        session.scalars(
            select(Judge.id)
            .where(Judge.court_id == destination.court_id)
            .order_by(Judge.id)
            .with_for_update()
        )
    )
    source_active_aliases = {
        alias.alias_normalised
        for alias in session.scalars(
            select(JudgeAlias).where(
                JudgeAlias.judge_id == source.id,
                JudgeAlias.is_active.is_(True),
            )
        )
    }
    if source_active_aliases:
        conflicting_alias = session.scalar(
            select(JudgeAlias)
            .join(Judge, Judge.id == JudgeAlias.judge_id)
            .where(
                Judge.court_id == destination.court_id,
                Judge.is_active.is_(True),
                JudgeAlias.is_active.is_(True),
                JudgeAlias.alias_normalised.in_(source_active_aliases),
                JudgeAlias.judge_id.notin_([source.id, destination.id]),
            )
            .order_by(JudgeAlias.alias_normalised, JudgeAlias.id)
            .with_for_update()
        )
        if conflicting_alias is not None:
            raise JudgeMappingConflict(
                "Merge would make an alias ambiguous in the destination court."
            )

    destination_aliases = {
        alias.alias_normalised
        for alias in session.scalars(
            select(JudgeAlias).where(JudgeAlias.judge_id == destination.id)
        )
    }
    for alias in list(
        session.scalars(select(JudgeAlias).where(JudgeAlias.judge_id == source.id))
    ):
        if alias.alias_normalised in destination_aliases:
            alias.is_active = False
            alias.record_version += 1
        else:
            alias.judge_id = destination.id
            alias.record_version += 1
            destination_aliases.add(alias.alias_normalised)

    destination_appointments = {
        (row.court_id, row.role, row.start_date)
        for row in session.scalars(
            select(JudgeAppointment).where(JudgeAppointment.judge_id == destination.id)
        )
    }
    for appointment in list(
        session.scalars(
            select(JudgeAppointment).where(JudgeAppointment.judge_id == source.id)
        )
    ):
        key = (appointment.court_id, appointment.role, appointment.start_date)
        if key in destination_appointments:
            session.delete(appointment)
        else:
            appointment.judge_id = destination.id
            destination_appointments.add(key)

    destination_authority_ids = {
        row.authority_document_id
        for row in session.scalars(
            select(JudgeDecisionIndex).where(JudgeDecisionIndex.judge_id == destination.id)
        )
    }
    for mapping in list(
        session.scalars(
            select(JudgeDecisionIndex).where(JudgeDecisionIndex.judge_id == source.id)
        )
    ):
        if mapping.authority_document_id in destination_authority_ids:
            session.delete(mapping)
        else:
            mapping.judge_id = destination.id
            destination_authority_ids.add(mapping.authority_document_id)

    session.execute(
        delete(JudgeAuthorityAffinity).where(JudgeAuthorityAffinity.judge_id == source.id)
    )
    session.execute(
        delete(JudgeStatuteFocus).where(JudgeStatuteFocus.judge_id == source.id)
    )
    for review in session.scalars(
        select(JudgeMappingReview).where(
            (JudgeMappingReview.resolved_judge_id == source.id)
            | JudgeMappingReview.candidate_judge_ids_json.is_not(None)
        )
    ):
        changed = False
        if review.resolved_judge_id == source.id:
            review.resolved_judge_id = destination.id
            changed = True
        candidate_ids = review.candidate_judge_ids_json or []
        if source.id in candidate_ids:
            review.candidate_judge_ids_json = list(
                dict.fromkeys(
                    destination.id if item == source.id else item
                    for item in candidate_ids
                )
            )
            changed = True
        if changed:
            review.record_version += 1

    source.is_active = False
    source.merged_into_judge_id = destination.id
    source.record_version += 1
    destination.identity_version += 1
    destination.record_version += 1
    session.flush()
    if commit:
        session.commit()
        session.refresh(destination)
    return destination


def analytics_mapping_filter():
    """Shared predicate: aggregates consume reviewed/high-confidence mappings only."""
    return JudgeDecisionIndex.is_analytics_eligible.is_(True)


__all__ = [
    "ANALYTICS_CONFIDENCE",
    "RESOLVER_VERSION",
    "AuthorityRemapSummary",
    "JudgeMappingConflict",
    "JudgeMappingError",
    "RawJudgeResolution",
    "add_bench_alias",
    "add_judge_alias",
    "analytics_mapping_filter",
    "merge_duplicate_judges",
    "rebuild_authority_mapping",
    "resolve_authority_court",
    "resolve_mapping_review",
    "resolve_raw_judge",
]
