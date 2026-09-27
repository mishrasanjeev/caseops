"""Real PostgreSQL proof for the bounded Intelligent Review history (2026-09-27).

Production keeps every retained generation of the private index; its eligible
projection baseline was 9,820 on 2026-09-01. The review history must stay one
bounded statement set against tables of that size, without a manual ANALYZE,
inside a short per-statement budget and with hash and merge joins disabled so
an adverse nested-loop plan cannot hide behind the planner's choice. Every
saved projection is also checked against the tenant's event ledger, so each
generation retains unrelated ledger events beside its projections.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Client,
    CompanyMembership,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateProjectionEvent,
)
from caseops_api.db.session import get_session_factory
from tests import test_20260927_review_history_bounded as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres

RETAINED_PROJECTIONS_PER_GENERATION = 10_000
# Unrelated access and source events: the ledger check must reach a saved
# projection's own targets through the event target index, not scan these.
RETAINED_EVENTS_PER_GENERATION = 10_000
UNRELATED_EVENT_TARGET_TYPES = ("matter", "ip_docket", "client", "matter_document", "ip_document")


def test_review_history_reauthorizes_every_private_manifest_in_one_bounded_query_set(
    isolated_postgres_client,
):
    journeys.test_review_history_reauthorizes_every_private_manifest_in_one_bounded_query_set(
        isolated_postgres_client
    )


def test_review_history_keeps_revoked_sources_hidden_after_a_later_rebuild(
    isolated_postgres_client,
):
    journeys.test_review_history_keeps_revoked_sources_hidden_after_a_later_rebuild(
        isolated_postgres_client
    )


def _retain_production_volume(session: Session, company_id: str) -> None:
    """Add unrelated projections and ledger events to the generation just activated."""

    generation = session.scalar(
        select(PrivateIndexGeneration).where(
            PrivateIndexGeneration.company_id == company_id,
            PrivateIndexGeneration.state == "active",
        )
    )
    assert generation is not None
    client_id = str(uuid4())
    session.add(
        Client(
            id=client_id,
            company_id=company_id,
            name=f"Retained volume client {client_id[:8]}",
            client_type="organization",
            is_active=True,
        )
    )
    session.flush()
    now = datetime.now(UTC)
    projections = []
    scopes = []
    for index in range(RETAINED_PROJECTIONS_PER_GENERATION):
        projection_id = str(uuid4())
        content = f"Retained private projection {generation.id} {index}"
        projections.append(
            {
                "id": projection_id,
                "company_id": company_id,
                "generation_id": generation.id,
                "source_type": "client",
                "source_id": str(uuid4()),
                "source_version": f"retained-{index}",
                "chunk_ordinal": 0,
                "label": f"Retained projection {index}",
                "content_text": content,
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "confidentiality": "internal",
                "is_privileged": False,
                "source_state": "active",
                "approval_state": "not_required",
                "access_policy_version": 0,
                "access_policy_generation": generation.access_policy_generation,
                "tombstone_generation": generation.tombstone_generation,
                "is_tombstoned": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        scopes.append(
            {
                "id": str(uuid4()),
                "company_id": company_id,
                "projection_id": projection_id,
                "scope_type": "client",
                "scope_id": client_id,
                "client_id": client_id,
                "access_policy_version": 0,
                "created_at": now,
            }
        )
    actor_membership_id = session.scalar(
        select(CompanyMembership.id).where(CompanyMembership.company_id == company_id).limit(1)
    )
    assert actor_membership_id is not None
    events = [
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "generation_id": generation.id,
            "idempotency_key": f"retained-volume:{uuid4()}",
            "event_type": ("access_changed", "source_changed")[index % 2],
            "target_type": UNRELATED_EVENT_TARGET_TYPES[index % len(UNRELATED_EVENT_TARGET_TYPES)],
            "target_id": str(uuid4()),
            "target_version": None,
            "access_policy_generation": generation.access_policy_generation,
            "tombstone_generation": generation.tombstone_generation,
            "status": "applied",
            "reason_code": "retained_volume",
            "actor_membership_id": actor_membership_id,
            "affected_projection_count": 0,
            "affected_saved_output_count": 0,
            "attempt_count": 1,
            "created_at": now,
            "applied_at": now,
        }
        for index in range(RETAINED_EVENTS_PER_GENERATION)
    ]
    for start in range(0, len(projections), 2_000):
        stop = start + 2_000
        session.execute(insert(PrivateIndexProjection.__table__), projections[start:stop])
        session.execute(insert(PrivateIndexProjectionScope.__table__), scopes[start:stop])
    for start in range(0, len(events), 2_000):
        session.execute(insert(PrivateProjectionEvent.__table__), events[start : start + 2_000])
    session.commit()


def _adverse_statement_budget(session: Session) -> None:
    session.execute(text("SET LOCAL statement_timeout = '1500ms'"))
    session.execute(text("SET LOCAL enable_hashjoin = off"))
    session.execute(text("SET LOCAL enable_mergejoin = off"))


def test_review_history_page_of_100_is_bounded_at_production_private_index_volume(
    isolated_postgres_client,
):
    history = journeys.build_review_history(
        isolated_postgres_client,
        retired_reviews=40,
        current_reviews=55,
        after_rebuild=_retain_production_volume,
    )
    assert len(history["reviews"]) == 100
    with get_session_factory()() as session:
        retained = session.scalar(
            text(
                "SELECT count(*) FROM private_index_projections "
                "WHERE company_id = :company_id AND source_type = 'client'"
            ),
            {"company_id": history["company_id"]},
        )
        generations = session.scalar(
            text("SELECT count(*) FROM private_index_generations WHERE company_id = :company_id"),
            {"company_id": history["company_id"]},
        )
        ledger = session.scalar(
            text("SELECT count(*) FROM private_projection_events WHERE company_id = :company_id"),
            {"company_id": history["company_id"]},
        )
    assert retained >= 2 * RETAINED_PROJECTIONS_PER_GENERATION
    assert generations >= 2
    assert ledger >= 2 * RETAINED_EVENTS_PER_GENERATION
    journeys.assert_bounded_history(
        isolated_postgres_client,
        history,
        prepare_session=_adverse_statement_budget,
    )
