"""Projection invalidation strips private bytes without loading them into Python."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
)
from caseops_api.services.private_retrieval import (
    create_shadow_private_generation,
    ensure_active_private_generation,
    propagate_private_projection_change,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


def _projection(company_id, generation_id, source_id, ordinal=0, source_type="matter"):
    content = "Private bytes must not be hydrated by a lifecycle write. " * 100
    now = datetime.now(UTC)
    return {
        "id": str(uuid4()),
        "company_id": company_id,
        "generation_id": generation_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_version": "1",
        "chunk_ordinal": ordinal,
        "label": "Bounded invalidation regression",
        "content_text": content,
        "content_sha256": sha256(content.encode()).hexdigest(),
        "access_policy_generation": 1,
        "tombstone_generation": 0,
        "embedding_dimensions": 3,
        "embedding_json": "[1.0, 0.0, 0.0]",
        "is_tombstoned": False,
        "created_at": now,
        "updated_at": now,
    }


def test_large_event_uses_one_set_update_without_private_byte_hydration(pg_engine):
    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        untouched_id = _seed_matter(seed, company_id)
        generation = ensure_active_private_generation(seed, company_id=company_id)
        shadow = create_shadow_private_generation(seed, company_id=company_id)
        retired = PrivateIndexGeneration(
            company_id=company_id,
            generation_number=3,
            state="retired",
        )
        seed.add(retired)
        seed.flush()
        other_company = _seed_company(seed)
        other_generation = ensure_active_private_generation(seed, company_id=other_company)
        rows = [_projection(company_id, generation.id, matter_id, n) for n in range(10_000)]
        child = _projection(company_id, generation.id, str(uuid4()), source_type="matter_document")
        rows.append(child)
        untouched = [
            _projection(company_id, generation.id, untouched_id),
            _projection(company_id, shadow.id, matter_id),
            _projection(company_id, retired.id, matter_id),
            _projection(other_company, other_generation.id, matter_id),
        ]
        seed.execute(insert(PrivateIndexProjection), rows + untouched)
        seed.add(
            PrivateIndexProjectionScope(
                company_id=company_id,
                projection_id=child["id"],
                scope_type="matter",
                scope_id=matter_id,
                matter_id=matter_id,
            )
        )
        seed.commit()
        generation_id, shadow_id = generation.id, shadow.id
        initial_shadow_epoch = shadow.tombstone_generation

    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, many):
        statements.append((sql, many))

    with Session(pg_engine) as session:
        # Prove identity-map synchronization as well as fresh-session persistence.
        cached = session.get(PrivateIndexProjection, rows[0]["id"])
        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            result = propagate_private_projection_change(
                session,
                company_id=company_id,
                actor_membership_id=actor_id,
                idempotency_key="set-based-large-event",
                event_type="revoked",
                target_type="matter",
                target_id=matter_id,
                target_version="1",
                reason_code="source_revoked",
            )
            assert result.affected_projection_count == 10_001
            assert result.status == "applied"
            assert cached.is_tombstoned and cached.content_text == ""
            assert cached.embedding_json is None
            session.commit()
            result_id = result.id
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)

    projection_updates = [
        sql for sql, many in statements if sql.startswith("UPDATE private_index_projections")
    ]
    wide_reads = [
        sql
        for sql, many in statements
        if sql.startswith("SELECT") and "private_index_projections.content_text" in sql
    ]
    assert not wide_reads, "Invalidation must not load retained content or embeddings."
    assert len(projection_updates) == 1
    assert not any(
        many for sql, many in statements if sql.startswith("UPDATE private_index_projections")
    )
    assert len(statements) <= 18, "SQL work must not scale with projection count."

    with Session(pg_engine) as check:
        invalidated = check.scalar(
            select(func.count())
            .select_from(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == generation_id,
                PrivateIndexProjection.is_tombstoned.is_(True),
                PrivateIndexProjection.content_text == "",
                PrivateIndexProjection.embedding_json.is_(None),
            )
        )
        assert invalidated == 10_001
        assert all(
            not check.get(PrivateIndexProjection, row["id"]).is_tombstoned for row in untouched
        )
        assert (
            check.get(PrivateIndexGeneration, shadow_id).tombstone_generation > initial_shadow_epoch
        )
        replay = propagate_private_projection_change(
            check,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="set-based-large-event",
            event_type="revoked",
            target_type="matter",
            target_id=matter_id,
            target_version="1",
            reason_code="source_revoked",
        )
        assert replay.id == result_id
        assert replay.affected_projection_count == 10_001
