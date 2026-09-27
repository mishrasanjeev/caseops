"""Real PostgreSQL proof for the bounded Intelligent Review history (2026-09-27).

Production keeps every retained generation of the private index; its eligible
projection baseline was 9,820 on 2026-09-01. The review history must stay one
bounded statement set against tables of that size, without a manual ANALYZE,
inside a short per-statement budget and with hash and merge joins disabled so
an adverse nested-loop plan cannot hide behind the planner's choice.
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
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
)
from caseops_api.db.session import get_session_factory
from tests import test_20260927_review_history_bounded as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres

RETAINED_PROJECTIONS_PER_GENERATION = 10_000


def test_review_history_reauthorizes_every_private_manifest_in_one_bounded_query_set(
    isolated_postgres_client,
):
    journeys.test_review_history_reauthorizes_every_private_manifest_in_one_bounded_query_set(
        isolated_postgres_client
    )


def _retain_production_volume(session: Session, company_id: str) -> None:
    """Add unrelated tenant projections to the generation just activated."""

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
    for start in range(0, len(projections), 2_000):
        stop = start + 2_000
        session.execute(insert(PrivateIndexProjection.__table__), projections[start:stop])
        session.execute(insert(PrivateIndexProjectionScope.__table__), scopes[start:stop])
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
    assert retained >= 2 * RETAINED_PROJECTIONS_PER_GENERATION
    assert generations >= 2
    journeys.assert_bounded_history(
        isolated_postgres_client,
        history,
        prepare_session=_adverse_statement_budget,
    )
