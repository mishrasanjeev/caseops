from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from psycopg import sql
from psycopg.pq import TransactionStatus
from sqlalchemy import delete, event, func, insert, select, text, tuple_, update
from sqlalchemy.dialects.postgresql.psycopg import dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, sessionmaker

from caseops_api.db.models import (
    Client,
    CompanyMembership,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    EthicalWall,
    IpAsset,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpPatentFamily,
    IpPatentFamilyVersion,
    MatterAccessGrant,
    MembershipRole,
    PrivateProjectionEvent,
    Team,
    TeamMembership,
)
from caseops_api.schemas.ip_patents import (
    PatentDocumentSource,
    PatentFamilyCorrectionRequest,
    PatentFamilyCreateRequest,
)
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_families import (
    correct_patent_family,
    create_patent_family,
    get_patent_family,
    list_patent_families,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.private_retrieval import (
    ensure_active_private_generation,
    lock_private_authority_writer,
)
from caseops_api.services.record_access_policy import _active_ip_subject_match
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


def test_patent_history_lifecycle_http_round_trip_on_postgres(isolated_postgres_client):
    from tests.test_ip_patent_families import (
        test_closed_family_sources_history_reopen_and_revoke_keep_boundaries,
    )

    test_closed_family_sources_history_reopen_and_revoke_keep_boundaries(isolated_postgres_client)


@pytest.mark.parametrize("journey", ["same_day_reclose", "backdated_commands"])
def test_shared_lifecycle_reclose_and_backdate_on_postgres(isolated_postgres_client, journey):
    from tests.test_ip_lifecycle_service import (
        test_backdated_lifecycle_commands_preview_acknowledge_and_preserve_history,
        test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children,
    )

    run_journey = {
        "same_day_reclose": (
            test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children
        ),
        "backdated_commands": (
            test_backdated_lifecycle_commands_preview_acknowledge_and_preserve_history
        ),
    }[journey]
    run_journey(isolated_postgres_client)


def _seed(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(company_id=company_id, name="Patent PG client", client_type="corporate")
        session.add(client)
        session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        family = create_patent_family(
            session,
            context=context,
            payload=PatentFamilyCreateRequest(
                title="Restricted PostgreSQL disclosure",
                client_id=client.id,
                disclosure_date=date(2026, 9, 5),
                disclosure_narrative="Original disclosure.",
            ),
            idempotency_key=str(uuid4()),
        )
        return company_id, actor_id, family


def test_patent_family_pg_persistence_tenant_constraints_and_atomic_rollback(migration_pg_engine):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    pg_engine = migration_pg_engine
    company_id, actor_id, family = _seed(pg_engine)
    with Session(pg_engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        corrected = correct_patent_family(
            session,
            context=context,
            family_id=str(family.id),
            payload=PatentFamilyCorrectionRequest(
                expected_version=family.version,
                expected_lifecycle_version=family.lifecycle_version,
                reason="Corrected inventor transcription.",
                facts=family.facts.model_copy(update={"title": "Corrected disclosure"}),
            ),
        )
        assert corrected.version == 2
        assert (
            get_patent_family(
                session,
                context=context,
                family_id=str(family.id),
                version_number=1,
            ).facts.title
            == family.facts.title
        )
        original = session.scalar(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.family_id == str(family.id),
                IpPatentFamilyVersion.version == 1,
            )
        )
        values = {
            column.name: getattr(original, column.name) for column in original.__table__.columns
        }
        for statement in (
            "UPDATE ip_patent_family_versions SET title='Overwritten' WHERE id=:id",
            "DELETE FROM ip_patent_family_versions WHERE id=:id",
        ):
            with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
                session.execute(text(statement), {"id": original.id})
        session.refresh(original)
        assert original.title == family.facts.title
        other_company = _seed_company(session)
        for changes in (
            {"company_id": other_company},
            {"family_id": str(uuid4())},
            {"source_document_version_id": str(uuid4()), "source_document_id": str(uuid4())},
            {"source_sha256": "a" * 64},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    IpPatentFamilyVersion(
                        **{
                            **values,
                            "id": str(uuid4()),
                            "version": 3,
                            **changes,
                        }
                    )
                )
                session.flush()
        session.rollback()

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", pg_engine.url.render_as_string(hide_password=False))
    head = ScriptDirectory.from_config(config).get_current_head()
    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="Patent disclosure evidence exists"):
            command.downgrade(config, "20260905_0003")
        command.upgrade(config, "head")
        with pg_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(IpPatentFamilyVersion)
                    .where(
                        IpPatentFamilyVersion.family_id == str(family.id),
                    )
                )
                == 2
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
                        "WHERE c.relname IN ('ip_patent_families','ip_patent_family_versions') "
                        "AND (NOT i.indisvalid OR NOT i.indisready)"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE "
                        "tgname='trg_patent_family_versions_append_only' AND tgenabled='O'"
                    )
                )
                == 1
            )


def test_patent_correction_rechecks_version_after_parent_lock_on_postgres(pg_engine):
    company_id, actor_id, family = _seed(pg_engine)
    payload = PatentFamilyCorrectionRequest(
        expected_version=family.version,
        expected_lifecycle_version=family.lifecycle_version,
        facts=family.facts,
        reason="Concurrent disclosure correction.",
    )
    application_name = f"patent-stale-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(pg_engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
            try:
                correct_patent_family(
                    session, context=context, family_id=str(family.id), payload=payload
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail["code"]
            raise AssertionError("Stale correction was accepted")

    with Session(pg_engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        lock_private_authority_writer(winner, company_id=company_id)
        context = _lock_ip_writer_context(
            winner,
            context=_ip_race_context(winner, company_id=company_id, membership_id=actor_id),
            required_capability="ip:write",
        )
        winner.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == str(family.docket_id),
            )
            .with_for_update()
        )
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(pg_engine, application_name=application_name)
            correct_patent_family(
                winner,
                context=context,
                family_id=str(family.id),
                payload=payload,
            )
            assert future.result(timeout=8) == (409, "patent_family_stale")
        finally:
            winner.rollback()
    with Session(pg_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPatentFamilyVersion)
                .where(
                    IpPatentFamilyVersion.family_id == str(family.id),
                )
            )
            == 2
        )


@pytest.mark.parametrize(
    "autoflush", [False, True], ids=["production-session", "autoflush-session"]
)
def test_patent_source_correction_and_index_worker_take_company_before_version_on_postgres(
    pg_engine, monkeypatch, autoflush
):
    from caseops_api.services import document_jobs, document_processing

    company_id, actor_id, family = _seed(pg_engine)
    content = "Original immutable inventor evidence for the PostgreSQL worker race."
    content_hash = sha256(content.encode()).hexdigest()
    with Session(pg_engine) as seed:
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="patent-worker-evidence",
            label="Inventor evidence",
            updated_by_membership_id=actor_id,
        )
        seed.add(taxonomy)
        seed.flush()
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Original inventor source",
            confidentiality="restricted",
            created_by_membership_id=actor_id,
        )
        seed.add(document)
        seed.flush()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="inventor.txt",
            display_name="inventor.txt",
            storage_key=f"patent-worker-race/{uuid4()}/inventor.txt",
            content_type="text/plain",
            size_bytes=len(content.encode()),
            sha256_hex=content_hash,
            uploaded_by_membership_id=actor_id,
        )
        seed.add(version)
        seed.flush()
        seed.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=document.id,
                target_type="docket",
                target_id=str(family.docket_id),
                docket_id=str(family.docket_id),
                created_by_membership_id=actor_id,
            )
        )
        job = DocumentProcessingJob(
            company_id=company_id,
            requested_by_membership_id=actor_id,
            target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
            attachment_id=version.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        seed.add(job)
        # Without an active generation the worker's real event path returns early.
        ensure_active_private_generation(seed, company_id=company_id)
        seed.commit()
        job_id, document_id, version_id = job.id, document.id, version.id
        storage_key = version.storage_key

    source = PatentDocumentSource(
        document_id=document_id,
        document_version_id=version_id,
        content_sha256=content_hash,
    )
    payload = PatentFamilyCorrectionRequest(
        expected_version=family.version,
        expected_lifecycle_version=family.lifecycle_version,
        facts=family.facts.model_copy(update={"source": source}),
        reason="Pin inventor source while background extraction completes.",
    )
    extraction_entered, release_extraction = Event(), Event()
    worker_name = f"patent-index-worker-{uuid4().hex[:12]}"
    factory = sessionmaker(bind=pg_engine, autoflush=autoflush, expire_on_commit=False)

    def worker_session():
        session = factory()
        session.execute(text("SET lock_timeout = '10s'"))
        session.execute(
            text("SELECT set_config('application_name', :name, false)"), {"name": worker_name}
        )
        return session

    def paused_parse(key, content_type):
        assert (key, content_type) == (storage_key, "text/plain")
        extraction_entered.set()
        assert release_extraction.wait(timeout=15)
        return document_processing.ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=content,
            chunks=[content],
            error=None,
        )

    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: worker_session)
    monkeypatch.setattr(document_processing, "parse_attachment", paused_parse)
    with ThreadPoolExecutor(max_workers=1) as pool, Session(pg_engine) as correction:
        worker = pool.submit(document_jobs.run_document_processing_job, job_id)
        try:
            assert extraction_entered.wait(timeout=15)
            correction.execute(text("SET LOCAL lock_timeout = '1s'"))
            context = _ip_race_context(correction, company_id=company_id, membership_id=actor_id)
            # This must succeed while storage/OCR is still paused, before taking source locks.
            lock_private_authority_writer(correction, company_id=company_id)
            correction_pid = correction.scalar(text("SELECT pg_backend_pid()"))
            with Session(pg_engine) as probe:
                for model, row_id in ((IpDocument, document_id), (IpDocumentVersion, version_id)):
                    assert (
                        probe.scalar(
                            select(model.id).where(model.id == row_id).with_for_update(nowait=True)
                        )
                        == row_id
                    )
                probe.rollback()

            release_extraction.set()
            _wait_for_postgres_lock_wait(pg_engine, application_name=worker_name)
            with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                waiting = (
                    observer.execute(
                        text(
                            "SELECT query, pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                            "WHERE application_name = :name AND wait_event_type = 'Lock'"
                        ),
                        {"name": worker_name},
                    )
                    .mappings()
                    .one()
                )
                assert "FROM companies" in waiting["query"]
                assert "FOR NO KEY UPDATE" in waiting["query"]
                assert correction_pid in waiting["blockers"]

            # The Company waiter must not own the version needed by this correction.
            # Keep Company held through this probe and the real writer, not just a signal.
            with Session(pg_engine) as probe:
                assert (
                    probe.scalar(
                        select(IpDocumentVersion.id)
                        .where(IpDocumentVersion.id == version_id)
                        .with_for_update(nowait=True)
                    )
                    == version_id
                )
                probe.rollback()
            corrected = correct_patent_family(
                correction, context=context, family_id=str(family.id), payload=payload
            )
            assert corrected.version == family.version + 1
            assert corrected.facts.source == source
        finally:
            release_extraction.set()
            correction.rollback()
        worker.result(timeout=15)

    with Session(pg_engine) as verify:
        job = verify.get(DocumentProcessingJob, job_id)
        assert job.status == DocumentProcessingJobStatus.COMPLETED, job.error_message
        assert job.attempt_count == 1
        assert job.error_message is None and job.completed_at is not None
        assert job.processed_char_count == len(content)
        version = verify.get(IpDocumentVersion, version_id)
        assert version.processing_status == DocumentProcessingStatus.INDEXED
        assert version.extracted_text == content
        assert version.sha256_hex == content_hash and version.storage_key == storage_key
        assert version.state == "draft"
        assert verify.get(IpDocument, document_id).current_version == 1
        worker_event = verify.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == company_id,
                PrivateProjectionEvent.idempotency_key == f"ip-document-indexed:{job_id}",
            )
        ).one()
        assert worker_event.status == "applied"
        assert worker_event.target_id == document_id and worker_event.target_version == "1"
        assert worker_event.reason_code == "ip_document_processing_completed"
        context = _ip_race_context(verify, company_id=company_id, membership_id=actor_id)
        retained = get_patent_family(verify, context=context, family_id=str(family.id))
        assert retained.version == family.version + 1 and retained.facts.source == source
        original = get_patent_family(
            verify, context=context, family_id=str(family.id), version_number=family.version
        )
        assert original.facts == family.facts
        assert (
            verify.scalar(
                select(func.count())
                .select_from(IpPatentFamilyVersion)
                .where(IpPatentFamilyVersion.family_id == str(family.id))
            )
            == 2
        )


def _patent_family_page_plan(session, statement, *, limit, generic, kind="page"):
    compiled = statement.limit(limit).compile(
        dialect=dialect(paramstyle="numeric_dollar"),
        compile_kwargs={"render_postcompile": True},
    )
    name = f"patent_page_{uuid4().hex}"
    with session.connection().connection.cursor() as cursor:
        cursor.execute(
            "SET LOCAL plan_cache_mode = "
            + ("'force_generic_plan'" if generic else "'force_custom_plan'")
        )
        cursor.execute(
            sql.SQL("PREPARE {} AS ").format(sql.Identifier(name)) + sql.SQL(str(compiled))
        )
        try:
            cursor.execute(
                sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) EXECUTE {} ({})").format(
                    sql.Identifier(name),
                    sql.SQL(",").join(
                        sql.Literal(compiled.params[key]) for key in compiled.positiontup
                    ),
                )
            )
            plan = cursor.fetchone()[0][0]
        finally:
            if cursor.connection.info.transaction_status != TransactionStatus.INERROR:
                cursor.execute(sql.SQL("DEALLOCATE {}").format(sql.Identifier(name)))
    # Retain all four plans before checking bounds, including failing counterexamples.
    print(json.dumps({"kind": kind, "generic": generic, "limit": limit, "plan": plan}))
    return plan


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


def _plan_work(node):
    return node.get("Actual Loops", 0) * sum(
        node.get(key, 0)
        for key in (
            "Actual Rows",
            "Rows Removed by Filter",
            "Rows Removed by Join Filter",
            "Rows Removed by Index Recheck",
        )
    )


def _assert_patent_family_page_work(plan, *, limit):
    all_nodes = list(_plan_nodes(plan["Plan"]))
    family_nodes = [node for node in all_nodes if node.get("Relation Name") == "ip_patent_families"]
    docket_nodes = [node for node in all_nodes if node.get("Relation Name") == "ip_docket_records"]
    assert family_nodes
    # Alternating ACLs examine at most two keys and two unique family rows per result.
    assert sum(_plan_work(node) for node in family_nodes) <= 4 * limit + 4
    assert docket_nodes
    assert sum(node["Actual Loops"] for node in docket_nodes) <= 2 * limit + 2
    assert sum(_plan_work(node) for node in docket_nodes) <= 2 * limit + 2
    assert sum(_plan_work(node) for node in all_nodes) < 50_000
    assert plan["Plan"]["Shared Hit Blocks"] + plan["Plan"]["Shared Read Blocks"] < 10_000


def _assert_patent_family_hydration_work(plan, *, limit):
    all_nodes = list(_plan_nodes(plan["Plan"]))
    family_nodes = [node for node in all_nodes if node.get("Relation Name") == "ip_patent_families"]
    assert family_nodes
    assert sum(_plan_work(node) for node in family_nodes) <= limit
    assert sum(_plan_work(node) for node in all_nodes) < 50_000
    assert plan["Plan"]["Shared Hit Blocks"] + plan["Plan"]["Shared Read Blocks"] < 10_000


def _seed_patent_family_scale(
    pg_engine,
    *,
    count=10_000,
    mixed_order=False,
    family_uuid_base=None,
    key_stride=1,
    key_start=0,
):
    company_id, actor_id, family = _seed(pg_engine)
    with Session(pg_engine) as session:
        docket = session.get(IpDocketRecord, str(family.docket_id))
        asset = session.get(IpAsset, str(family.asset_id))
        base_family = session.get(IpPatentFamily, str(family.id))
        version = session.scalar(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.family_id == str(family.id),
            )
        )
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == str(family.docket_id),
            )
        )

        def clone(row, **changes):
            return {
                **{col.name: getattr(row, col.name) for col in row.__table__.columns},
                **changes,
            }

        if family_uuid_base is None:
            family_uuid_base = uuid4().int & ~((1 << 32) - 1)
        asset_uuid_base = uuid4().int & ~((1 << 32) - 1)
        for batch in range((count + 499) // 500):
            dockets, assets, families, versions, grants = [], [], [], [], []
            for offset in range(min(500, count - batch * 500)):
                docket_id, asset_id = (str(uuid4()) for _ in range(2))
                ordinal = batch * 500 + offset
                key_offset = ordinal
                if mixed_order:
                    # Independent import identities: ordered assets, scattered family keys.
                    asset_id = str(UUID(int=asset_uuid_base + ordinal))
                    key_offset = ordinal * 7919 % count
                # Stable ordering alternates granted/denied rows without changing cardinality.
                family_id = str(UUID(int=family_uuid_base + key_start + key_stride * key_offset))
                dockets.append(
                    clone(docket, id=docket_id, title=f"Scale disclosure {batch}-{offset}")
                )
                assets.append(clone(asset, id=asset_id, docket_id=docket_id))
                families.append(
                    clone(base_family, id=family_id, docket_id=docket_id, asset_id=asset_id)
                )
                versions.append(clone(version, id=str(uuid4()), family_id=family_id))
                if offset % 2 == 0:
                    grants.append(clone(grant, id=str(uuid4()), ip_docket_id=docket_id))
            for model, rows in (
                (IpDocketRecord, dockets),
                (IpAsset, assets),
                (IpPatentFamily, families),
                (IpPatentFamilyVersion, versions),
                (MatterAccessGrant, grants),
            ):
                session.execute(insert(model.__table__), rows)
            session.commit()
    return company_id, actor_id, family_uuid_base


def test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres(pg_engine):
    _check_patent_family_scale(pg_engine)


def _check_patent_family_scale(
    pg_engine, *, mixed_order=False, fresh_statistics=False, family_uuid_base=None
):
    company_id, actor_id, family_uuid_base = _seed_patent_family_scale(
        pg_engine,
        mixed_order=mixed_order,
        key_stride=2 if mixed_order else 1,
        family_uuid_base=family_uuid_base,
    )
    if mixed_order:
        # Interleave another tenant's keys, not merely another tenant's heap rows.
        other_company_id, _, _ = _seed_patent_family_scale(
            pg_engine,
            mixed_order=True,
            family_uuid_base=family_uuid_base,
            key_stride=2,
            key_start=1,
        )
        with Session(pg_engine) as session:
            interleaved = list(
                session.execute(
                    select(IpPatentFamily.id, IpPatentFamily.company_id)
                    .where(
                        IpPatentFamily.id >= str(UUID(int=family_uuid_base)),
                        IpPatentFamily.id < str(UUID(int=family_uuid_base + 20_000)),
                    )
                    .order_by(IpPatentFamily.id)
                )
            )
            assert len(interleaved) == 20_000
            assert [row.company_id for row in interleaved] == [
                tenant for _ in range(10_000) for tenant in (company_id, other_company_id)
            ]
    with Session(pg_engine) as session:
        if fresh_statistics:
            for table in (
                "ip_docket_records",
                "ip_patent_families",
                "matter_access_grants",
                "ethical_walls",
            ):
                session.execute(text(f"ANALYZE {table}"))
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        statements = []
        page_statements = []
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        session.execute(text("SET LOCAL enable_hashjoin = off"))
        session.execute(text("SET LOCAL enable_mergejoin = off"))

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
            if _context.compiled is not None:
                page_statements.append(_context.compiled.statement)

        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            result = list_patent_families(session, context=context, limit=100)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        assert len(result.families) == 100 and result.next_cursor is not None
        assert len(statements) <= 12
        assert [col.key for col in page_statements[0].selected_columns] == ["id", "docket_id"]
        plans = [
            (
                plan_limit,
                _patent_family_page_plan(
                    session, page_statements[0], limit=plan_limit, generic=generic
                ),
            )
            for generic in (False, True)
            for plan_limit in (101, 1)
        ]
        hydration_plans = [
            _patent_family_page_plan(
                session, page_statements[1], limit=None, generic=generic, kind="hydration"
            )
            for generic in (False, True)
        ]
        if mixed_order and not fresh_statistics:
            # Pre-fix outer shape only, not the full old ACL query: wide rows before ordering.
            wide = aliased(
                IpPatentFamily,
                select(IpPatentFamily)
                .where(IpPatentFamily.company_id == company_id)
                .order_by(IpPatentFamily.id)
                .offset(0)
                .subquery(),
            )
            old_plan = _patent_family_page_plan(
                session,
                select(wide).order_by(wide.id),
                limit=101,
                generic=True,
                kind="pre_feature_outer_shape",
            )
            old_nodes = list(_plan_nodes(old_plan["Plan"]))
            print(
                json.dumps(
                    {
                        "kind": "pre_feature_outer_shape_diagnostic",
                        "wide_sort": any(
                            node["Node Type"] == "Sort" and node["Plan Width"] > 100
                            for node in old_nodes
                        ),
                        "family_work": sum(
                            _plan_work(node)
                            for node in old_nodes
                            if node.get("Relation Name") == "ip_patent_families"
                        ),
                    }
                )
            )
        allowed = set(
            session.scalars(
                select(MatterAccessGrant.ip_docket_id).where(
                    MatterAccessGrant.company_id == company_id,
                    MatterAccessGrant.membership_id == actor_id,
                )
            )
        )
        assert all(str(row.docket_id) in allowed for row in result.families)
        expected = sorted(
            session.scalars(
                select(IpPatentFamily.id).where(
                    IpPatentFamily.company_id == company_id,
                    IpPatentFamily.docket_id.in_(allowed),
                )
            )
        )
        assert len(expected) == 5001
        assert [str(row.id) for row in result.families] == expected[:100]
        assert result.next_cursor == expected[99]
        statements.clear()
        page_statements.clear()
        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            second = list_patent_families(
                session, context=context, limit=100, cursor=result.next_cursor
            )
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        assert len(statements) <= 12
        hydration_plans.extend(
            _patent_family_page_plan(
                session, page_statements[1], limit=None, generic=generic, kind="cursor_hydration"
            )
            for generic in (False, True)
        )
        cursor_plans = []
        for generic in (False, True):
            for plan_limit in (101, 1):
                cursor_plan = _patent_family_page_plan(
                    session, page_statements[0], limit=plan_limit, generic=generic
                )
                cursor_plans.append(cursor_plan)
                plans.append((plan_limit, cursor_plan))
        assert [str(row.id) for row in second.families] == expected[100:200]
        seen = [str(row.id) for row in result.families + second.families]
        next_cursor = second.next_cursor
        while next_cursor is not None:
            page = list_patent_families(session, context=context, limit=100, cursor=next_cursor)
            assert page.families
            assert page.next_cursor is None or page.next_cursor > next_cursor
            seen.extend(str(row.id) for row in page.families)
            assert len(seen) <= len(expected)
            next_cursor = page.next_cursor
        assert seen == expected
        # A selective match beyond thousands of denied/nonmatching candidates must not be capped.
        found = list_patent_families(
            session, context=context, limit=1, query="Scale disclosure 19-498"
        )
        assert [str(row.id) for row in found.families] == [
            str(UUID(int=family_uuid_base + (2 * (9998 * 7919 % 10_000) if mixed_order else 9998)))
        ]
        assert found.next_cursor is None
        print(json.dumps({"authorized_ids": seen, "late_match_id": str(found.families[0].id)}))
        for cursor_plan in cursor_plans:
            assert any(
                node.get("Relation Name") == "ip_patent_families"
                and "id" in node.get("Index Cond", "") + node.get("Filter", "")
                and ">" in node.get("Index Cond", "") + node.get("Filter", "")
                for node in _plan_nodes(cursor_plan["Plan"])
            )
        for plan_limit, plan in plans:
            _assert_patent_family_page_work(plan, limit=plan_limit)
        for plan in hydration_plans:
            _assert_patent_family_hydration_work(plan, limit=100)


def test_patent_family_list_stale_unique_tenant_statistics_bound_docket_work(
    migration_pg_engine,
):
    # Train unique tenant statistics before a concentrated import; do not analyze it away.
    for _ in range(32):
        _seed(migration_pg_engine)
    with migration_pg_engine.begin() as connection:
        connection.execute(text("ANALYZE ip_docket_records"))
        connection.execute(text("ANALYZE ip_patent_families"))
        connection.execute(text("ANALYZE matter_access_grants"))
        connection.execute(text("ANALYZE ethical_walls"))
    test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres(migration_pg_engine)


def _train_patent_family_mixed_statistics(migration_pg_engine):
    # Disable background analysis only in this independently fresh, disposable fixture.
    with migration_pg_engine.begin() as connection:
        for table in (
            "ip_docket_records",
            "ip_patent_families",
            "matter_access_grants",
            "ethical_walls",
        ):
            connection.execute(text(f"ALTER TABLE {table} SET (autovacuum_enabled = false)"))
    for _ in range(64):
        _seed(migration_pg_engine)
    _seed_patent_family_scale(migration_pg_engine, count=1000, mixed_order=True)
    with migration_pg_engine.begin() as connection:
        for table in (
            "ip_docket_records",
            "ip_patent_families",
            "matter_access_grants",
            "ethical_walls",
        ):
            connection.execute(text(f"ANALYZE {table}"))
        assert connection.scalar(text("SELECT count(*) FROM ip_patent_families")) == 1065
        assert (
            connection.scalar(
                text(
                    "SELECT n_distinct FROM pg_stats WHERE tablename = 'ip_patent_families' "
                    "AND attname = 'company_id'"
                )
            )
            == 65
        )


def test_patent_family_list_stale_mixed_tenant_statistics_bound_outer_family_work(
    migration_pg_engine,
):
    _train_patent_family_mixed_statistics(migration_pg_engine)
    _check_patent_family_scale(migration_pg_engine, mixed_order=True)


def test_patent_family_list_fresh_mixed_tenant_statistics_bound_outer_family_work(
    migration_pg_engine,
):
    _train_patent_family_mixed_statistics(migration_pg_engine)
    _check_patent_family_scale(migration_pg_engine, mixed_order=True, fresh_statistics=True)


def test_patent_family_list_retained_grants_bound_authorization_work(migration_pg_engine):
    # Train the active-grant index before a foreign import, as retained suites
    # and ordinary bulk imports can leave its global statistics stale.
    _seed(migration_pg_engine)
    with migration_pg_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE matter_access_grants SET (autovacuum_enabled = false)")
        )
        connection.execute(text("ANALYZE matter_access_grants"))
    _seed_patent_family_scale(migration_pg_engine, count=10_000)
    _seed_patent_family_scale(migration_pg_engine, count=10_000)
    _check_patent_family_scale(migration_pg_engine)


def test_patent_family_list_stale_low_id_histogram_bounds_cursor_work(migration_pg_engine):
    # A known cursor above the stale histogram can make a global seek+sort look
    # cheaper than an ordered tenant seek. Keep that pre-import state explicit.
    with migration_pg_engine.begin() as connection:
        for table in (
            "ip_docket_records",
            "ip_patent_families",
            "matter_access_grants",
            "ethical_walls",
        ):
            connection.execute(text(f"ALTER TABLE {table} SET (autovacuum_enabled = false)"))
    _seed_patent_family_scale(
        migration_pg_engine,
        count=1000,
        family_uuid_base=UUID("00000000-0000-0000-0000-000100000000").int,
    )
    imported_base = UUID("ffffffff-ffff-ffff-ffff-fffe00000000").int
    with migration_pg_engine.begin() as connection:
        for table in (
            "ip_docket_records",
            "ip_patent_families",
            "matter_access_grants",
            "ethical_walls",
        ):
            connection.execute(text(f"ANALYZE {table}"))
        assert connection.scalar(text("SELECT count(*) FROM ip_patent_families")) == 1001
        assert connection.scalar(text("SELECT max(id) FROM ip_patent_families")) < str(
            UUID(int=imported_base)
        )
    _check_patent_family_scale(migration_pg_engine, family_uuid_base=imported_base)


@pytest.mark.parametrize("change", ["retarget", "delete", "revoke"])
def test_patent_family_page_rechecks_warm_identity_after_selection(pg_engine, change):
    company_id, actor_id, original = _seed(pg_engine)
    with Session(pg_engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        original_family = session.get(IpPatentFamily, str(original.id))
        original_docket = session.get(IpDocketRecord, str(original.docket_id))
        original_asset = session.get(IpAsset, str(original.asset_id))
        original_version = session.scalars(
            select(IpPatentFamilyVersion).where(IpPatentFamilyVersion.family_id == str(original.id))
        ).one()
        original_grant = session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == str(original.docket_id)
            )
        ).one()

        def clone(row, **changes):
            return {
                **{col.name: getattr(row, col.name) for col in row.__table__.columns},
                **changes,
            }

        family_id, docket_id, asset_id, replacement_id, grant_id = (str(uuid4()) for _ in range(5))
        title = f"Warm family page {family_id}"
        for new_docket_id in (docket_id, replacement_id):
            session.execute(
                insert(IpDocketRecord.__table__),
                clone(original_docket, id=new_docket_id, title=title),
            )
        session.execute(
            insert(IpAsset.__table__), clone(original_asset, id=asset_id, docket_id=docket_id)
        )
        session.execute(
            insert(IpPatentFamily.__table__),
            clone(original_family, id=family_id, docket_id=docket_id, asset_id=asset_id),
        )
        if change != "delete":
            session.execute(
                insert(IpPatentFamilyVersion.__table__),
                clone(original_version, id=str(uuid4()), family_id=family_id, title=title),
            )
        for new_docket_id, new_grant_id in ((docket_id, grant_id), (replacement_id, str(uuid4()))):
            session.execute(
                insert(MatterAccessGrant.__table__),
                clone(original_grant, id=new_grant_id, ip_docket_id=new_docket_id),
            )
        session.commit()
        warm_family = session.get(IpPatentFamily, family_id)
        assert warm_family.docket_id == docket_id
        changed = False

        def interleave(_conn, _cursor, _statement, _params, execution_context, _many):
            nonlocal changed
            compiled = execution_context.compiled
            if changed or compiled is None or not compiled.statement.is_select:
                return
            if list(compiled.statement.selected_columns) != list(IpPatentFamily.__table__.columns):
                return
            changed = True
            with Session(pg_engine) as writer:
                if change == "retarget":
                    writer.execute(
                        update(IpPatentFamily)
                        .where(IpPatentFamily.id == family_id)
                        .values(docket_id=replacement_id)
                    )
                elif change == "delete":
                    writer.execute(delete(IpPatentFamily).where(IpPatentFamily.id == family_id))
                else:
                    writer.execute(
                        update(MatterAccessGrant)
                        .where(MatterAccessGrant.id == grant_id)
                        .values(revoked_at=datetime.now(UTC))
                    )
                writer.commit()

        event.listen(pg_engine, "before_cursor_execute", interleave)
        try:
            with pytest.raises(HTTPException) as rejected:
                list_patent_families(session, context=context, query=title, limit=1)
        finally:
            event.remove(pg_engine, "before_cursor_execute", interleave)
        assert changed
        assert rejected.value.status_code == 409
        assert rejected.value.detail["code"] == "patent_family_access_changed"
        assert session.get(IpPatentFamily, family_id) is warm_family

    with Session(pg_engine) as verify:
        context = _ip_race_context(verify, company_id=company_id, membership_id=actor_id)
        visible = set(
            verify.scalars(
                select(IpDocketRecord.id).where(
                    IpDocketRecord.company_id == company_id,
                    visible_ip_dockets_filter(verify, context=context),
                )
            )
        )
        assert replacement_id in visible
        assert (docket_id in visible) is (change != "revoke")
        retained = verify.get(IpPatentFamily, family_id)
        if change == "delete":
            assert retained is None
        else:
            assert retained.docket_id == (replacement_id if change == "retarget" else docket_id)


def test_patent_family_key_barrier_preserves_canonical_effective_acl(pg_engine):
    company_id, actor_id, family = _seed(pg_engine)
    with Session(pg_engine) as session:
        session.get(CompanyMembership, actor_id).role = MembershipRole.OWNER
        session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        grant = session.scalars(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == str(family.docket_id))
        ).one()
        now = datetime.now(UTC)

        def assert_visible(expected):
            session.flush()
            canonical = session.scalar(
                select(IpDocketRecord.id).where(
                    IpDocketRecord.id == str(family.docket_id),
                    IpDocketRecord.company_id == company_id,
                    visible_ip_dockets_filter(session, context=context),
                )
            )
            assert (canonical is not None) is expected
            for scope in ("active", "all"):
                page = list_patent_families(session, context=context, status_scope=scope)
                assert [str(row.id) for row in page.families] == (
                    [str(family.id)] if expected else []
                )

        assert_visible(True)
        grant.revoked_at = now
        assert_visible(False)
        grant.revoked_at = None
        grant.effective_from = now + timedelta(days=1)
        assert_visible(False)
        grant.effective_from = now - timedelta(days=2)
        grant.expires_at = now - timedelta(days=1)
        assert_visible(False)
        grant.expires_at = None
        team = Team(company_id=company_id, name="Family review", slug=f"family-{uuid4().hex}")
        session.add(team)
        session.flush()
        session.add(TeamMembership(team_id=team.id, membership_id=actor_id))
        grant.membership_id = None
        grant.team_id = team.id
        assert_visible(True)
        team.is_active = False
        assert_visible(False)
        team.is_active = True
        wall = EthicalWall(
            company_id=company_id,
            ip_docket_id=str(family.docket_id),
            excluded_team_id=team.id,
            reason="Conflict blocks the family page.",
            created_by_membership_id=actor_id,
        )
        session.add(wall)
        assert_visible(False)
        wall.effective_from = now + timedelta(days=1)
        assert_visible(True)
        wall.effective_from = now - timedelta(days=2)
        wall.expires_at = now - timedelta(days=1)
        assert_visible(True)
        wall.expires_at = None
        wall.revoked_at = now
        assert_visible(True)
        wall.revoked_at = None
        wall.excluded_team_id = None
        wall.excluded_membership_id = actor_id
        assert_visible(False)


def test_ip_subject_seek_rejects_present_wrong_subject_and_target_successors(pg_engine):
    company_id, actor_id, family = _seed(pg_engine)
    now = datetime.now(UTC)
    base = uuid4().int & ~((1 << 32) - 1)
    first_id, gap_id, last_id = [str(UUID(int=base + offset)) for offset in (1, 2, 3)]
    absent_subject = str(UUID(int=0))
    with Session(pg_engine) as session:
        source = session.get(IpDocketRecord, str(family.docket_id))
        for docket_id in (first_id, gap_id, last_id):
            session.add(
                IpDocketRecord(
                    **{
                        column.name: (
                            docket_id if column.name == "id" else getattr(source, column.name)
                        )
                        for column in source.__table__.columns
                    }
                )
            )
        team = Team(company_id=company_id, name="Seek successor", slug=f"seek-{uuid4().hex}")
        session.add(team)
        session.flush()
        assert absent_subject < actor_id and absent_subject < team.id
        for model, membership_column, team_column, creator_column in (
            (MatterAccessGrant, "membership_id", "team_id", "granted_by_membership_id"),
            (EthicalWall, "excluded_membership_id", "excluded_team_id", "created_by_membership_id"),
        ):
            for column_name, subject_id in ((membership_column, actor_id), (team_column, team.id)):
                column = getattr(model, column_name)
                records = {}
                for target_id in (first_id, last_id):
                    row = model(
                        company_id=company_id,
                        ip_docket_id=target_id,
                        effective_from=now - timedelta(days=1),
                        **{column_name: subject_id, creator_column: actor_id},
                    )
                    session.add(row)
                    session.flush()
                    records[target_id] = row.id

                def lookup(target_id, subject, model=model, column=column):
                    return session.scalar(
                        select(_active_ip_subject_match(model, column, subject, now))
                        .select_from(IpDocketRecord)
                        .where(IpDocketRecord.id == target_id)
                    )

                for target_id, subject, successor_target in (
                    (first_id, absent_subject, first_id),
                    (gap_id, subject_id, last_id),
                ):
                    # Prove this is a present successor, not an empty negative lookup.
                    successor = session.execute(
                        select(model.id, model.ip_docket_id, column)
                        .where(
                            model.revoked_at.is_(None),
                            model.ip_docket_id.is_not(None),
                            column.is_not(None),
                            tuple_(model.ip_docket_id, column) >= tuple_(target_id, subject),
                        )
                        .order_by(model.ip_docket_id, column)
                        .limit(1)
                    ).one()
                    assert tuple(successor) == (
                        records[successor_target], successor_target, subject_id
                    )
                    assert lookup(target_id, subject) is None
                for target_id in (first_id, last_id):
                    assert lookup(target_id, subject_id) == records[target_id]
        session.rollback()
