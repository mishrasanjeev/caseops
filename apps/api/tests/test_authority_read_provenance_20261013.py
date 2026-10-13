from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import CaseOpsSession, _proven_read_statement
from caseops_api.services import authorities
from caseops_api.services.llm import generate_structured
from caseops_api.services.llm_types import LLMCallContext, LLMCompletion, LLMMessage


class _Base(DeclarativeBase):
    pass


class _CallerRow(_Base):
    __tablename__ = "authority_provenance_caller_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(sa.String(40))


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class _OfflineProvider:
    name = "mock"
    model = "authority-provenance-offline"

    def __init__(self, session):
        self.session = session
        self.calls = 0

    def generate(self, **_kwargs):
        assert isinstance(self.session, CaseOpsSession)
        assert not self.session.in_transaction()
        self.calls += 1
        return LLMCompletion(
            text=json.dumps({"answer": "offline fixture"}), provider=self.name,
            model=self.model, prompt_tokens=1, completion_tokens=1, latency_ms=0,
        )


def _generate(session, provider):
    return generate_structured(
        provider, session=session, schema=_Payload,
        context=LLMCallContext(purpose="authority-provenance-offline"),
        messages=[LLMMessage(role="user", content="offline fixture")],
        release_session_before_provider=True,
    )


class _StatementRecorder:
    """SQL-tree capture only; never substitutes for native PostgreSQL proof."""

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __init__(self):
        self.statements = []

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return SimpleNamespace(first=lambda: (1,), all=lambda: [])


def test_indexed_name_expression_is_read_only_and_keeps_literal_index_constants():
    expression = authorities._indexed_search_text(
        AuthorityDocument.parties_json, AuthorityDocument.title, AuthorityDocument.bench_name,
    )
    statement = sa.select(AuthorityDocument.id).where(expression.ilike("%Fixture%")).limit(24)
    assert _proven_read_statement(statement)
    compiled = str(statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True},
    ))
    assert (
        "coalesce(authority_documents.parties_json, '') || ' ' || "
        "coalesce(authority_documents.title, '') || ' ' || "
        "coalesce(authority_documents.bench_name, '')"
    ) in compiled
    assert "ILIKE %(" in compiled
    assert "Fixture" not in compiled


@pytest.mark.parametrize("mode", ["exact_citation", "party", "judge", "act_section"])
def test_all_indexed_mode_expressions_have_read_provenance(mode):
    clause = authorities._authority_mode_filter_clause(mode, "Fixture")
    assert clause is not None
    assert _proven_read_statement(sa.select(AuthorityDocument.id).where(clause).limit(24))


def test_embedding_availability_is_a_bounded_structured_read():
    recorder = _StatementRecorder()
    assert authorities._pg_embedding_scope_available(
        recorder, forum_level=None, court_name=None, document_type=None,
    )
    assert len(recorder.statements) == 1
    statement = recorder.statements[0]
    assert _proven_read_statement(statement)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "authority_document_chunks" in sql
    assert "embedding_vector IS NOT NULL" in sql
    assert "JOIN" not in sql
    assert statement._limit_clause.value == 1


def test_vector_prefilter_is_structured_and_preserves_pre_join_topk():
    recorder = _StatementRecorder()
    assert authorities._pg_prefilter_document_hits(
        recorder, query_vector=[0.123456789, -0.00000049], forum_level="high_court",
        court_name="Fixture%_Court", document_type="judgment", limit=48,
    ) == []
    assert len(recorder.statements) == 1
    statement = recorder.statements[0]
    assert _proven_read_statement(statement)
    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True},
    )
    sql = str(compiled)
    assert sql.index("ORDER BY") < sql.index("JOIN authority_documents")
    assert sql.index("LIMIT") < sql.index("JOIN authority_documents")
    assert "<=> CAST(" in sql
    assert " AS vector)" in sql
    assert "row_number() OVER (PARTITION BY" in sql
    assert "WHERE ranked.doc_rank =" in sql
    assert "1440" in {str(value) for value in compiled.params.values()}
    assert "48" in {str(value) for value in compiled.params.values()}
    assert "[0.123457,-0.000000]" in {
        str(value).replace(" ", "") for value in compiled.params.values()
    }
    assert "Fixture%_Court" not in sql
    assert "high_court" not in sql
    assert "judgment" not in sql


@pytest.mark.parametrize("forum_level", [None, "high_court"])
@pytest.mark.parametrize("court_name", [None, "Fixture Court"])
@pytest.mark.parametrize("document_type", [None, "judgment"])
def test_vector_prefilter_keeps_every_nullable_filter_combination(
    forum_level, court_name, document_type,
):
    recorder = _StatementRecorder()
    assert authorities._pg_prefilter_document_hits(
        recorder, query_vector=[1.0, 0.0], forum_level=forum_level,
        court_name=court_name, document_type=document_type, limit=1,
    ) == []
    assert len(recorder.statements) == 1
    statement = recorder.statements[0]
    assert _proven_read_statement(statement)
    compiled = statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True},
    )
    assert "CAST(" in str(compiled)
    assert " AS vector)" in str(compiled)
    assert "1000" in {str(value) for value in compiled.params.values()}


def test_caseops_session_releases_indexed_read_before_offline_provider():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    table = sa.Table(
        "authority_documents", sa.MetaData(), sa.Column("id", sa.String, primary_key=True),
        sa.Column("parties_json", sa.String), sa.Column("title", sa.String),
        sa.Column("bench_name", sa.String),
    )
    table.metadata.create_all(engine)
    try:
        with CaseOpsSession(engine) as session:
            expression = authorities._indexed_search_text(
                table.c.parties_json, table.c.title, table.c.bench_name,
            )
            session.execute(sa.select(table.c.id).where(expression.ilike("%Fixture%"))).all()
            provider = _OfflineProvider(session)
            payload, _ = _generate(session, provider)
            assert payload.answer == "offline fixture"
            assert provider.calls == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "kind", ["orm-new", "orm-dirty", "orm-deleted", "orm-flushed", "core", "text", "driver"],
)
def test_shared_provider_still_rejects_every_caller_write(kind):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _Base.metadata.create_all(engine)
    try:
        with CaseOpsSession(engine) as session:
            if kind in {"orm-dirty", "orm-deleted"}:
                row = _CallerRow(id=1, value="before")
                session.add(row)
                session.commit()
                if kind == "orm-dirty":
                    row.value = "after"
                else:
                    session.delete(row)
            elif kind in {"orm-new", "orm-flushed"}:
                session.add(_CallerRow(id=1, value="after"))
                if kind == "orm-flushed":
                    session.flush()
            elif kind == "core":
                session.execute(sa.insert(_CallerRow).values(id=1, value="after"))
            elif kind == "text":
                session.execute(sa.text(
                    "INSERT INTO authority_provenance_caller_rows (id, value) VALUES (1, 'after')"
                ))
            else:
                session.connection().exec_driver_sql(
                    "INSERT INTO authority_provenance_caller_rows (id, value) VALUES (1, 'after')"
                )
            transaction = session.get_transaction()
            session.execute(sa.select(_CallerRow.id).where(
                authorities._indexed_search_text(_CallerRow.value).ilike("%after%"),
            )).all()
            assert session.get_transaction() is transaction
            provider = _OfflineProvider(session)
            with pytest.raises(RuntimeError, match="contains writes"):
                _generate(session, provider)
            assert provider.calls == 0
            assert session.get_transaction() is transaction
            assert session.new or session.dirty or session.deleted or (
                session.info["caseops_written_transaction"] is transaction
            )
    finally:
        engine.dispose()


def test_shared_provider_still_rejects_nested_and_external_transactions():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with CaseOpsSession(engine) as session, session.begin_nested():
            provider = _OfflineProvider(session)
            with pytest.raises(RuntimeError, match="external or nested"):
                _generate(session, provider)
            assert provider.calls == 0
            assert session.in_nested_transaction()
        with engine.connect() as connection, CaseOpsSession(connection) as session:
            provider = _OfflineProvider(session)
            with pytest.raises(RuntimeError, match="external or nested"):
                _generate(session, provider)
            assert provider.calls == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["core", "orm-flushed", "driver"])
def test_vector_read_error_never_rolls_back_caller_writes(kind, monkeypatch):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _Base.metadata.create_all(engine)
    try:
        with CaseOpsSession(engine) as session:
            if kind == "core":
                session.execute(sa.insert(_CallerRow).values(id=1, value="retained"))
            elif kind == "orm-flushed":
                session.add(_CallerRow(id=1, value="retained"))
                session.flush()
            else:
                session.connection().exec_driver_sql(
                    "INSERT INTO authority_provenance_caller_rows (id, value) "
                    "VALUES (1, 'retained')"
                )
            transaction = session.get_transaction()

            def failed_read(*_args, **_kwargs):
                raise RuntimeError("offline authority read failure")

            monkeypatch.setattr(session, "execute", failed_read)
            with pytest.raises(RuntimeError, match="offline authority read failure"):
                authorities._pg_prefilter_document_hits(
                    session, query_vector=[1.0, 0.0], forum_level=None, court_name=None,
                    document_type=None, limit=1,
                )
            assert session.get_transaction() is transaction
            assert session.info["caseops_written_transaction"] is transaction
            provider = _OfflineProvider(session)
            with pytest.raises(RuntimeError, match="contains writes"):
                _generate(session, provider)
            assert provider.calls == 0
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_native_caseops_empty_authority_reads_release_before_provider(http_pg_engine):
    with CaseOpsSession(http_pg_engine) as session:
        assert isinstance(session, CaseOpsSession)
        assert session.get_bind().dialect.name == "postgresql"
        assert authorities._exact_name_match_document_ids(
            session, query="Fixture Petitioner", forum_level=None,
            court_name=None, document_type=None, limit=24,
        ) == []
        assert not authorities._pg_embedding_scope_available(
            session, forum_level=None, court_name=None, document_type=None,
        )
        provider = _OfflineProvider(session)
        assert _generate(session, provider)[0].answer == "offline fixture"
        assert provider.calls == 1


def _seed_native_vectors(engine):
    vector = [1.0] + [0.0] * 1023
    definitions = [
        ("Fixture%_\\Court", "high_court", "judgment", (1.0, 0.0)),
        ("Other Court", "supreme_court", "order", (0.8, 0.6)),
        ("FixtureXXCourt", "high_court", "judgment", (0.6, 0.8)),
    ]
    document_ids = []
    chunk_ids = []
    with CaseOpsSession(engine) as session:
        for index, (court, forum, kind, coordinates) in enumerate(definitions):
            document = AuthorityDocument(
                id=str(uuid4()), source="offline-provenance-fixture", adapter_name="offline",
                court_name=court, forum_level=forum, document_type=kind,
                title=f"Fixture Petitioner {index}", parties_json="Fixture Petitioner",
                canonical_key=str(uuid4()),
                summary="Offline metadata; not reviewed legal authority.",
            )
            session.add(document)
            session.flush()
            chunk = AuthorityDocumentChunk(
                id=str(uuid4()), authority_document_id=document.id, chunk_index=0,
                content="Offline vector fixture, not an approved legal source.", token_count=10,
            )
            session.add(chunk)
            session.flush()
            value = list(coordinates) + [0.0] * 1022
            session.execute(sa.update(authorities._PG_AUTHORITY_CHUNKS).where(
                authorities._PG_AUTHORITY_CHUNKS.c.id == chunk.id,
            ).values(embedding_vector=sa.cast(
                sa.literal(json.dumps(value)), authorities._PostgresVector(),
            )))
            document_ids.append(document.id)
            chunk_ids.append(chunk.id)
        extra = AuthorityDocumentChunk(
            id=str(uuid4()), authority_document_id=document_ids[0], chunk_index=1,
            content="Less relevant second offline chunk.", token_count=10,
        )
        session.add(extra)
        session.flush()
        session.execute(sa.update(authorities._PG_AUTHORITY_CHUNKS).where(
            authorities._PG_AUTHORITY_CHUNKS.c.id == extra.id,
        ).values(embedding_vector=sa.cast(
            sa.literal(json.dumps([0.0, 1.0] + [0.0] * 1022)), authorities._PostgresVector(),
        )))
        session.commit()
    return vector, document_ids, chunk_ids


@pytest.mark.postgres
@pytest.mark.parametrize("court", [None, "", "  ", "%", "_", "\\", "Fixture%_\\Court", "XX"])
def test_native_vector_filters_match_literal_position_and_keep_best_chunk(http_pg_engine, court):
    vector, document_ids, chunk_ids = _seed_native_vectors(http_pg_engine)
    normalized = authorities._normalize_court_filter(court)
    normalized = normalized.casefold() if normalized else None
    # Independent retained legacy predicate: observer connection owns no service session.
    with http_pg_engine.connect() as connection:
        expected_ids = set(connection.scalars(sa.text(
            "SELECT id FROM authority_documents WHERE "
            "cast(:court as text) IS NULL OR "
            "position(:court in lower(coalesce(court_name, ''))) > 0"
        ), {"court": normalized}))
    with CaseOpsSession(http_pg_engine) as session:
        assert session.get_bind().dialect.name == "postgresql"
        assert authorities._pg_embedding_scope_available(
            session, forum_level=None, court_name=None, document_type=None,
        )
        hits = authorities._pg_prefilter_document_hits(
            session, query_vector=vector, forum_level=None, court_name=court,
            document_type=None, limit=6,
        )
        assert hits is not None
        assert [hit.document_id for hit in hits] == [
            identity for identity in document_ids if identity in expected_ids
        ]
        assert [hit.chunk_id for hit in hits] == [
            identity for document_id, identity in zip(document_ids, chunk_ids, strict=True)
            if document_id in expected_ids
        ]
        provider = _OfflineProvider(session)
        assert _generate(session, provider)[0].answer == "offline fixture"
        assert provider.calls == 1


@pytest.mark.postgres
@pytest.mark.parametrize("forum", [None, "high_court"])
@pytest.mark.parametrize("court", [None, "Fixture"])
@pytest.mark.parametrize("kind", [None, "judgment"])
def test_native_vector_nullable_filters_and_ranked_limit(http_pg_engine, forum, court, kind):
    vector, document_ids, _ = _seed_native_vectors(http_pg_engine)
    expected = document_ids if forum is None and court is None and kind is None else [
        document_ids[0], document_ids[2],
    ]
    with CaseOpsSession(http_pg_engine) as session:
        all_hits = authorities._pg_prefilter_document_hits(
            session, query_vector=vector, forum_level=forum, court_name=court,
            document_type=kind, limit=6,
        )
        assert all_hits is not None
        assert [hit.document_id for hit in all_hits] == expected
        hits = authorities._pg_prefilter_document_hits(
            session, query_vector=vector, forum_level=forum, court_name=court,
            document_type=kind, limit=1,
        )
        assert hits is not None
        assert [hit.document_id for hit in hits] == expected[:1]
        session.require_read_only_transaction()


@pytest.mark.postgres
@pytest.mark.parametrize("forum,court,kind,expected_index", [
    ("supreme_court", None, None, 1),
    (None, "Other Court", None, 1),
    (None, None, "order", 1),
    ("tribunal", None, None, None),
    (None, "No Matching Court", None, None),
    (None, None, "statute", None),
    ("high_court", None, "order", None),
    ("supreme_court", None, "judgment", None),
])
def test_native_vector_filters_exclude_nearest_or_return_no_eligible_hit(
    http_pg_engine, forum, court, kind, expected_index,
):
    vector, document_ids, chunk_ids = _seed_native_vectors(http_pg_engine)
    with CaseOpsSession(http_pg_engine) as session:
        hits = authorities._pg_prefilter_document_hits(
            session, query_vector=vector, forum_level=forum, court_name=court,
            document_type=kind, limit=1,
        )
        assert hits is not None
        expected = [] if expected_index is None else [
            (document_ids[expected_index], chunk_ids[expected_index]),
        ]
        assert [(hit.document_id, hit.chunk_id) for hit in hits] == expected
        session.require_read_only_transaction()


@pytest.mark.postgres
def test_native_indexed_expression_keeps_trigram_under_forced_generic_plan(http_pg_engine):
    expression = authorities._indexed_search_text(
        AuthorityDocument.parties_json, AuthorityDocument.title, AuthorityDocument.bench_name,
    )
    sql_expression = str(expression.compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True},
    ))
    assert "%(" not in sql_expression
    with http_pg_engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL plan_cache_mode = force_generic_plan")
        connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        connection.exec_driver_sql(
            "PREPARE authority_provenance_generic (text, integer) AS "
            "SELECT id FROM authority_documents WHERE (" + sql_expression + ") ILIKE $1 LIMIT $2"
        )
        plan = connection.exec_driver_sql(
            "EXPLAIN (FORMAT JSON, COSTS FALSE) "
            "EXECUTE authority_provenance_generic ('%Fixture%', 24)",
            execution_options={"no_parameters": True},
        ).scalar_one()
        assert "ix_authority_documents_name_prefilter_trgm" in json.dumps(plan)
        connection.exec_driver_sql("DEALLOCATE authority_provenance_generic")


@pytest.mark.postgres
@pytest.mark.parametrize("matter_kind", ["criminal-intake", "original-commercial-active"])
def test_native_http_strategy_uses_real_caseops_session_without_provider_transaction(
    isolated_postgres_client, monkeypatch, matter_kind,
):
    from caseops_api.services.llm import MockProvider
    from tests.test_auth_company import auth_headers, bootstrap_company

    client = isolated_postgres_client
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    payload = {
        "title": "Fixture Petitioner authority read boundary", "matter_code": "READ-PROVENANCE",
        "practice_area": "criminal", "forum_level": "high_court", "court_name": "Delhi High Court",
        "client_name": "Offline Fixture", "status": "intake",
    }
    if matter_kind == "original-commercial-active":
        payload = {
            "title": "September 02 workbook regression fixture", "matter_code": "RAM902-READ",
            "status": "active", "practice_area": "Commercial Litigation",
            "forum_level": "high_court", "forum_catalog_entry_id": "hc:delhi",
        }
    matter = client.post("/api/matters/", headers=headers, json=payload)
    assert matter.status_code == 200, matter.text
    guarded = []
    calls = []
    original_guard = CaseOpsSession.require_read_only_transaction
    original_generate = MockProvider.generate

    def observe_guard(session):
        assert session.get_bind().dialect.name == "postgresql"
        original_guard(session)
        guarded.append(session)

    def observe_provider(provider, **kwargs):
        assert guarded
        assert isinstance(guarded[-1], CaseOpsSession)
        assert not guarded[-1].in_transaction()
        calls.append(provider.name)
        return original_generate(provider, **kwargs)

    monkeypatch.setattr(CaseOpsSession, "require_read_only_transaction", observe_guard)
    monkeypatch.setattr(MockProvider, "generate", observe_provider)
    response = client.post(
        f"/api/matters/{matter.json()['id']}/recommendations", headers=headers,
        json={"type": "litigation_strategy"},
    )
    # No reviewed corpus was seeded: retain the uncited-primary security refusal.
    assert response.status_code == 422, response.text
    assert calls == ["mock"]
    assert guarded


@pytest.mark.postgres
def test_native_http_strategy_persists_grounded_canonical_offline_payload(
    isolated_postgres_client, monkeypatch,
):
    from caseops_api.db.session import get_session_factory
    from tests.test_auth_company import auth_headers
    from tests.test_litigation_strategy import (
        _seed_relevant_authority,
        _setup_matter,
        _valid_strategy_payload,
    )

    client = isolated_postgres_client
    token, _, matter_id = _setup_matter(client)
    citation = _seed_relevant_authority()
    payload = _valid_strategy_payload(citation)
    observed = []
    original_guard = CaseOpsSession.require_read_only_transaction

    def observe_guard(session):
        assert session.get_bind().dialect.name == "postgresql"
        original_guard(session)
        observed.append(session)

    class GroundedOfflineProvider:
        name = "mock"
        model = "mock-strategy"
        calls = 0

        def generate(self, **_kwargs):
            assert observed and isinstance(observed[-1], CaseOpsSession)
            assert not observed[-1].in_transaction()
            self.calls += 1
            return LLMCompletion(
                text=json.dumps(payload), provider=self.name, model=self.model,
                prompt_tokens=120, completion_tokens=350, latency_ms=0,
            )

    provider = GroundedOfflineProvider()
    monkeypatch.setattr(CaseOpsSession, "require_read_only_transaction", observe_guard)
    monkeypatch.setattr(
        "caseops_api.services.litigation_strategy.build_provider", lambda **_kwargs: provider,
    )
    with get_session_factory()() as session:
        assert isinstance(session, CaseOpsSession)
        assert session.get_bind().dialect.name == "postgresql"
    headers = auth_headers(token)
    headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    generated = client.post(
        f"/api/matters/{matter_id}/recommendations", headers=headers,
        json={"type": "litigation_strategy"},
    )
    assert generated.status_code == 200, generated.text
    assert provider.calls == 1
    body = generated.json()
    assert body["review_required"] is True
    assert body["strategy_payload"] is not None
    assert body["strategy_payload"]["recommended_route"]["supporting_citations"]
    reloaded = client.get(f"/api/matters/{matter_id}/recommendations", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert body["id"] in {row["id"] for row in reloaded.json()["recommendations"]}


def _invoke_authority_read(session, helper):
    if helper == "name":
        return authorities._exact_name_match_document_ids(
            session, query="Fixture Petitioner", forum_level=None,
            court_name=None, document_type=None, limit=24,
        )
    if helper == "availability":
        return authorities._pg_embedding_scope_available(
            session, forum_level=None, court_name=None, document_type=None,
        )
    return authorities._pg_prefilter_document_hits(
        session, query_vector=[1.0] + [0.0] * 1023, forum_level=None,
        court_name=None, document_type=None, limit=1,
    )


@pytest.mark.postgres
@pytest.mark.parametrize("helper", ["name", "availability", "vector"])
@pytest.mark.parametrize("kind", ["core", "orm-flushed", "driver"])
def test_native_authority_read_error_preserves_caller_transaction(
    http_pg_engine, helper, kind, monkeypatch,
):
    _Base.metadata.create_all(http_pg_engine)
    with CaseOpsSession(http_pg_engine) as session:
        if kind == "core":
            session.execute(sa.insert(_CallerRow).values(id=1, value="retained"))
        elif kind == "orm-flushed":
            session.add(_CallerRow(id=1, value="retained"))
            session.flush()
        else:
            session.connection().exec_driver_sql(
                "INSERT INTO authority_provenance_caller_rows (id, value) VALUES (1, 'retained')"
            )
        _invoke_authority_read(session, helper)
        transaction = session.get_transaction()
        assert session.info["caseops_written_transaction"] is transaction
        original_execute = session.execute

        def database_failure(*_args, **_kwargs):
            return original_execute(sa.select(sa.literal(1) / sa.literal(0)))

        monkeypatch.setattr(session, "execute", database_failure)
        monkeypatch.setattr(session, "scalars", database_failure)
        with pytest.raises(sa.exc.DBAPIError):
            _invoke_authority_read(session, helper)
        assert session.get_transaction() is transaction
        assert session.info["caseops_written_transaction"] is transaction
        provider = _OfflineProvider(session)
        with pytest.raises(RuntimeError, match="contains writes"):
            _generate(session, provider)
        assert provider.calls == 0
        session.rollback()


@pytest.mark.postgres
@pytest.mark.parametrize("helper", ["name", "availability", "vector"])
def test_native_authority_read_error_retains_proven_read_only_fallback(
    http_pg_engine, helper, monkeypatch,
):
    with CaseOpsSession(http_pg_engine) as session:
        original_execute = session.execute

        def database_failure(*_args, **_kwargs):
            return original_execute(sa.select(sa.literal(1) / sa.literal(0)))

        monkeypatch.setattr(session, "execute", database_failure)
        monkeypatch.setattr(session, "scalars", database_failure)
        expected = {"name": [], "availability": False, "vector": None}[helper]
        assert _invoke_authority_read(session, helper) == expected
        assert not session.in_transaction()


@pytest.mark.postgres
def test_native_vector_query_retains_hnsw_index_eligibility(http_pg_engine):
    vector, _, _ = _seed_native_vectors(http_pg_engine)
    recorder = _StatementRecorder()
    authorities._pg_prefilter_document_hits(
        recorder, query_vector=vector, forum_level=None, court_name=None,
        document_type=None, limit=6,
    )
    statement = recorder.statements[0]
    sql = str(statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    with http_pg_engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
        plan = connection.exec_driver_sql("EXPLAIN (FORMAT JSON, COSTS FALSE) " + sql).scalar_one()
        assert "ix_authority_document_chunks_embedding_hnsw" in json.dumps(plan)
