"""Core invalidation keeps ORM rollback semantics on both database dialects."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_, event, insert
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AssistantSession,
    AssistantTurn,
    PrivateIndexProjection,
    PrivateSavedOutputAccess,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval import (
    _apply_private_invalidation,
    ensure_active_private_generation,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_matter,
    _seed_membership,
)
from tests.test_private_event_set_based_20261009_postgres import _projection


@pytest.mark.parametrize("flush_before_rollback", [False, True])
@pytest.mark.parametrize(
    "storage",
    ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)],
)
def test_cached_invalidation_reverts_with_its_savepoint(
    client: TestClient, request, storage, flush_before_rollback,
):
    if storage == "postgres":
        engine = request.getfixturevalue("pg_engine")
    else:
        with get_session_factory()() as current:
            engine = current.get_bind()
    with Session(engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        generation = ensure_active_private_generation(seed, company_id=company_id)
        projection = _projection(company_id, generation.id, matter_id)
        seed.execute(insert(PrivateIndexProjection), [projection])
        assistant = AssistantSession(
            company_id=company_id, created_by_membership_id=actor_id,
            title="Savepoint cache regression", policy_version=1,
            retention_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        seed.add(assistant)
        seed.flush()
        turn = AssistantTurn(
            company_id=company_id, session_id=assistant.id, sequence=1,
            role="assistant", status="completed", created_by_membership_id=actor_id,
        )
        seed.add(turn)
        seed.flush()
        output_id = str(uuid4())
        seed.add(PrivateSavedOutputAccess(
            id=output_id, company_id=company_id, assistant_turn_id=turn.id,
            generation_id=generation.id, source_type="matter", source_id=matter_id,
            source_version="1", access_policy_generation=1, tombstone_generation=0,
            state="accessible",
        ))
        seed.commit()
    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    with Session(engine, expire_on_commit=False) as session:
        cached = session.get(PrivateIndexProjection, projection["id"])
        output = session.get(PrivateSavedOutputAccess, output_id)
        original_text = cached.content_text
        now = datetime.now(UTC)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(RuntimeError, match="rollback the private mutation"):
                with session.begin_nested(), session.no_autoflush:
                    count, sources = _apply_private_invalidation(
                        session, model=PrivateIndexProjection,
                        predicate=and_(
                            PrivateIndexProjection.company_id == company_id,
                            PrivateIndexProjection.id == projection["id"],
                        ),
                        values={
                            "is_tombstoned": True, "content_text": "", "embedding_json": None,
                            "embedding_dimensions": None, "tombstoned_at": now,
                            "tombstone_reason": "source_revoked", "tombstone_generation": 1,
                            "updated_at": now,
                        },
                        collect_sources=True,
                    )
                    assert (count, sources) == (1, {("matter", matter_id)})
                    assert _apply_private_invalidation(
                        session, model=PrivateSavedOutputAccess,
                        predicate=and_(
                            PrivateSavedOutputAccess.company_id == company_id,
                            PrivateSavedOutputAccess.id == output_id,
                        ),
                        values={
                            "state": "locked", "locked_reason": "source_revoked",
                            "locked_at": now, "access_policy_generation": 1,
                            "tombstone_generation": 1, "updated_at": now,
                        },
                    ) == (1, set())
                    assert cached.is_tombstoned and cached.content_text == ""
                    assert output.state == "locked" and output.locked_reason == "source_revoked"
                    if flush_before_rollback:
                        session.flush()
                    raise RuntimeError("rollback the private mutation")
            assert not cached.is_tombstoned and cached.content_text == original_text
            assert cached.embedding_json == projection["embedding_json"]
            assert output.state == "accessible" and output.locked_reason is None
            assert sum(
                sql.startswith("UPDATE private_index_projections") for sql in statements
            ) == 1
            assert sum(
                sql.startswith("UPDATE private_saved_output_access") for sql in statements
            ) == 1
            session.commit()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    with Session(engine) as check:
        assert not check.get(PrivateIndexProjection, projection["id"]).is_tombstoned
        assert check.get(PrivateSavedOutputAccess, output_id).state == "accessible"
