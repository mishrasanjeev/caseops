from __future__ import annotations

import json
import os
from collections.abc import Mapping
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
from sqlalchemy import delete, event, func, insert, inspect, select, text, tuple_, update
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
from caseops_api.services.matter_access import (
    seed_restricted_ip_creator_access,
    visible_ip_dockets_filter,
)
from caseops_api.services.private_retrieval import (
    ensure_active_private_generation,
    lock_private_authority_writer,
)
from caseops_api.services.record_access_policy import _active_ip_subject_match
from tests.test_patent_plan_capture_20261031 import (
    _freeze_patent_execution,
    _numeric_patent_execution,
)
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
    from tests.fixtures_historical_migrations import assert_fixture_downgrade_refused

    assert_fixture_downgrade_refused(
        pg_engine,
        "20260906_0001",
        "20260905_0003",
        [
            ("ip_patent_family_versions", {"family_id": str(family.id), "version": version})
            for version in (1, 2)
        ],
        "Patent disclosure evidence exists",
    )
    for _attempt in range(2):
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

        def identify_transaction(_session, _transaction, connection):
            # A released provider/preparation transaction can return a different
            # pooled connection. Identify every new transaction, not just the first.
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(
                text("SELECT set_config('application_name', :name, true)"), {"name": worker_name}
            )

        from sqlalchemy import event

        event.listen(session, "after_begin", identify_transaction)
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


def _patent_evidence_value(value):
    if isinstance(value, Mapping):
        return {key: _patent_evidence_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_patent_evidence_value(item) for item in value]
    return value


def _patent_evidence_path(request, tmp_path):
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    native = os.environ.get("CASEOPS_FINALIZER_EVIDENCE_DIR")
    root = Path(native) if native else (Path(journal).parent if journal else tmp_path)
    node_hash = sha256(request.node.nodeid.encode()).hexdigest()[:20]
    directory = root / "ip-preflight-plans" / f"patent-family-{node_hash}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"plans-{uuid4().hex}.jsonl", request.node.nodeid


def _retain_patent_evidence(evidence, **record):
    path, nodeid = evidence
    with path.open("a", encoding="ascii") as output:
        output.write(
            json.dumps(
                _patent_evidence_value({"patent_kind": "family", "nodeid": nodeid, **record}),
                default=str,
                ensure_ascii=True,
            )
            + "\n"
        )


def _patent_execution_record(captured):
    return {
        "actual_sql": captured.raw_sql,
        "driver_parameters": captured.driver_parameters,
        "compiled_parameters": captured.compiled_parameters,
        "parameter_expansion": captured.parameter_expansion,
        "executemany": captured.executemany,
        "ast_columns": [column.key for column in captured.statement.selected_columns],
    }


def _patent_catalog_snapshot(session):
    tables = (
        "ip_patent_families",
        "ip_docket_records",
        "ip_patent_family_versions",
        "ip_document_versions",
        "matter_access_grants",
        "ethical_walls",
    )
    queries = {
        "settings": "SELECT name, setting, unit, source FROM pg_settings "
        "WHERE name LIKE 'enable_%' OR name IN "
        "('plan_cache_mode','statement_timeout','server_version','random_page_cost',"
        "'seq_page_cost','work_mem','effective_cache_size') ORDER BY name",
        "relations": "SELECT c.relname, c.reltuples, c.relpages, c.reloptions, "
        "s.last_analyze, s.last_autoanalyze, s.n_mod_since_analyze "
        "FROM pg_class c LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid "
        "WHERE c.oid IN (SELECT to_regclass(name) FROM unnest(CAST(:tables AS text[])) AS name)",
        "statistics": "SELECT schemaname, tablename, attname, null_frac, n_distinct, "
        "most_common_vals::text, most_common_freqs, histogram_bounds::text, correlation "
        "FROM pg_stats WHERE schemaname=current_schema() "
        "AND tablename=ANY(CAST(:tables AS text[]))",
        "indexes": "SELECT c.relname, i.indexrelid::regclass::text AS index_name, "
        "i.indisvalid, i.indisready, i.indislive, pg_get_indexdef(i.indexrelid) AS definition "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
        "WHERE c.oid IN (SELECT to_regclass(name) FROM unnest(CAST(:tables AS text[])) AS name)",
    }
    return {
        key: [
            dict(row) for row in session.execute(text(query), {"tables": list(tables)}).mappings()
        ]
        for key, query in queries.items()
    }


def _is_patent_entity_select(statement, model):
    return any(
        description.get("entity") is not None
        and inspect(description["entity"]).mapper.class_ is model
        for description in statement.column_descriptions
    )


def _patent_hydration_ids(captured, *, company_id):
    def leaves(value):
        if isinstance(value, (tuple, list)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    # The family hydration binds contain only UUID identities and integer seek limits.
    return [
        value
        for parameter in captured.compiled_parameters
        for value in leaves(tuple(parameter.values()))
        if isinstance(value, str) and value != company_id
    ]


def _patent_family_page_plan(
    session, captured, *, limit, generic, evidence, kind="page", expected_ids=None,
    expected_versions=None,
):
    numeric_sql, parameters = _numeric_patent_execution(captured, limit=limit)
    name = f"patent_page_{uuid4().hex}"
    mode = {False: "force_custom_plan", True: "force_generic_plan", None: "auto"}[generic]
    result_ids = None
    result_versions = None
    prepared = False
    with session.connection().connection.cursor() as cursor:
        cursor.execute("SHOW plan_cache_mode")
        previous_mode = cursor.fetchone()[0]
        try:
            cursor.execute(sql.SQL("SET LOCAL plan_cache_mode = {}").format(sql.Literal(mode)))
            cursor.execute(
                "SELECT name, setting FROM pg_settings WHERE name LIKE 'enable_%' "
                "OR name IN ('plan_cache_mode','statement_timeout') ORDER BY name"
            )
            settings = dict(cursor.fetchall())
            cursor.execute(
                sql.SQL("PREPARE {} AS ").format(sql.Identifier(name)) + sql.SQL(numeric_sql)
            )
            prepared = True
            execute = sql.SQL("EXECUTE {} ({})").format(
                sql.Identifier(name), sql.SQL(",").join(sql.Literal(value) for value in parameters)
            )
            cursor.execute(sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + execute)
            plan = cursor.fetchone()[0][0]
            # Retain the physical counterexample even if result reconciliation fails.
            _retain_patent_evidence(
                evidence,
                kind=kind,
                mode=mode,
                limit=limit,
                plan=plan,
                numeric_sql=numeric_sql,
                numeric_parameters=parameters,
                settings=settings,
                expected_ids=expected_ids,
                expected_versions=expected_versions,
                counters=_patent_plan_counters(plan),
                execution=_patent_execution_record(captured),
            )
            if expected_ids is not None or expected_versions is not None:
                cursor.execute(execute)
                columns = [column.name for column in cursor.description]
                result_rows = cursor.fetchall()
                if expected_ids is not None:
                    result_ids = [str(row[columns.index("id")]) for row in result_rows]
                if expected_versions is not None:
                    result_versions = [
                        (str(row[columns.index("company_id")]),
                         str(row[columns.index("family_id")]), row[columns.index("version")])
                        for row in result_rows
                    ]
                _retain_patent_evidence(
                    evidence,
                    kind=f"{kind}_results",
                    mode=mode,
                    actual_ids=result_ids,
                    expected_ids=expected_ids,
                    actual_versions=result_versions,
                    expected_versions=expected_versions,
                )
        finally:
            if cursor.connection.info.transaction_status != TransactionStatus.INERROR:
                if prepared:
                    cursor.execute(sql.SQL("DEALLOCATE {}").format(sql.Identifier(name)))
                cursor.execute(
                    sql.SQL("SET LOCAL plan_cache_mode = {}").format(sql.Literal(previous_mode))
                )
                cursor.execute("SHOW plan_cache_mode")
                restored_mode = cursor.fetchone()[0]
    _retain_patent_evidence(
        evidence,
        kind="plan_mode_restored",
        stage=kind,
        previous_mode=previous_mode,
        restored_mode=restored_mode,
    )
    assert restored_mode == previous_mode
    if expected_ids is not None:
        assert sorted(result_ids) == sorted(expected_ids)
    if expected_versions is not None:
        assert sorted(result_versions) == sorted(expected_versions)
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


def _patent_plan_counters(plan):
    nodes = list(_plan_nodes(plan["Plan"]))
    return {
        "total_work": sum(_plan_work(node) for node in nodes),
        "root_shared_blocks": plan["Plan"]["Shared Hit Blocks"]
        + plan["Plan"]["Shared Read Blocks"],
        "relations": [
            {**node, "charged_work": _plan_work(node)}
            for node in nodes
            if node.get("Relation Name")
        ],
    }


def _assert_patent_plan_common_work(plan):
    counters = _patent_plan_counters(plan)
    assert counters["total_work"] < 50_000
    assert counters["root_shared_blocks"] < 10_000


def _patent_later_hydration_plans(
    session, captured_statements, evidence, *, expected_versions, prefix=""
):
    plans = []
    for model, stage in (
        (IpDocketRecord, "docket_hydration"),
        (IpPatentFamilyVersion, "disclosure_version_hydration"),
        (IpDocumentVersion, "document_version_hydration"),
    ):
        matches = [
            captured
            for captured in captured_statements[2:]
            if _is_patent_entity_select(captured.statement, model)
        ]
        _retain_patent_evidence(
            evidence,
            kind=f"{prefix}{stage}_inventory",
            statement_count=len(matches),
            per_relation_work_bound=(
                "admitted_page_size" if model is IpPatentFamilyVersion else "diagnostic_only"
            ),
        )
        for captured in matches:
            for generic in (False, True, None):
                plans.append((
                    stage, _patent_family_page_plan(
                        session,
                        captured,
                        limit=None,
                        generic=generic,
                        evidence=evidence,
                        kind=f"{prefix}{stage}_diagnostic",
                        expected_versions=(
                            expected_versions if model is IpPatentFamilyVersion else None
                        ),
                    ),
                ))
        assert matches
    return plans


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


def _assert_patent_disclosure_hydration_work(plan, *, limit):
    nodes = [
        node for node in _plan_nodes(plan["Plan"])
        if node.get("Relation Name") == "ip_patent_family_versions"
    ]
    assert nodes
    assert sum(_plan_work(node) for node in nodes) <= limit
    _assert_patent_plan_common_work(plan)


def _seed_patent_family_scale(
    pg_engine,
    *,
    count=10_000,
    mixed_order=False,
    family_uuid_base=None,
    key_stride=1,
    key_start=0,
    with_source=False,
):
    company_id, actor_id, family = _seed(pg_engine)
    if with_source:
        family = _seed_patent_scale_source(pg_engine, company_id, actor_id, family)
    with Session(pg_engine) as session:
        docket = session.get(IpDocketRecord, str(family.docket_id))
        asset = session.get(IpAsset, str(family.asset_id))
        base_family = session.get(IpPatentFamily, str(family.id))
        version = session.scalar(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.family_id == str(family.id),
                IpPatentFamilyVersion.version == docket.current_version,
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


def _seed_patent_scale_source(pg_engine, company_id, actor_id, family):
    # Reuse the real source/link/correction path from the source-worker race fixture.
    with Session(pg_engine) as session:
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key=f"scale-source-{uuid4().hex}",
            label="Inventor evidence",
            updated_by_membership_id=actor_id,
        )
        session.add(taxonomy)
        session.flush()
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Scale inventor source",
            confidentiality="restricted",
            created_by_membership_id=actor_id,
        )
        session.add(document)
        session.flush()
        content = b"Immutable scale inventor source."
        content_hash = sha256(content).hexdigest()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="inventor.txt",
            display_name="inventor.txt",
            storage_key=f"patent-scale/{uuid4()}/inventor.txt",
            content_type="text/plain",
            size_bytes=len(content),
            sha256_hex=content_hash,
            uploaded_by_membership_id=actor_id,
        )
        session.add(version)
        session.flush()
        session.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=document.id,
                target_type="docket",
                target_id=str(family.docket_id),
                docket_id=str(family.docket_id),
                created_by_membership_id=actor_id,
            )
        )
        session.commit()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        return correct_patent_family(
            session,
            context=context,
            family_id=str(family.id),
            payload=PatentFamilyCorrectionRequest(
                expected_version=family.version,
                expected_lifecycle_version=family.lifecycle_version,
                facts=family.facts.model_copy(
                    update={
                        "source": PatentDocumentSource(
                            document_id=document.id,
                            document_version_id=version.id,
                            content_sha256=content_hash,
                        )
                    }
                ),
                reason="Pin immutable scale evidence.",
            ),
        )


def test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres(
    pg_engine, request, tmp_path
):
    _check_patent_family_scale(pg_engine, request=request, tmp_path=tmp_path)


def _check_patent_family_scale(
    pg_engine,
    *,
    request,
    tmp_path,
    mixed_order=False,
    fresh_statistics=False,
    family_uuid_base=None,
    adverse_joins=True,
):
    evidence = _patent_evidence_path(request, tmp_path)
    with Session(pg_engine) as before_import:
        _retain_patent_evidence(
            evidence, kind="catalog_before_import", catalog=_patent_catalog_snapshot(before_import)
        )
    company_id, actor_id, family_uuid_base = _seed_patent_family_scale(
        pg_engine,
        mixed_order=mixed_order,
        key_stride=2 if mixed_order else 1,
        family_uuid_base=family_uuid_base,
        with_source=True,
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
        if adverse_joins:
            session.execute(text("SET LOCAL enable_hashjoin = off"))
            session.execute(text("SET LOCAL enable_mergejoin = off"))
        _retain_patent_evidence(
            evidence,
            kind="catalog_before_pages",
            adverse_joins=adverse_joins,
            fresh_statistics=fresh_statistics,
            mixed_order=mixed_order,
            catalog=_patent_catalog_snapshot(session),
        )
        page_label = "first"

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
            if _context.compiled is not None and _context.compiled.statement.is_select:
                captured = _freeze_patent_execution(
                    _context.compiled,
                    statement,
                    _params,
                    _context.compiled_parameters,
                    _many,
                    # Pinned SQLAlchemy execution data, copied before another call can reuse it.
                    parameter_expansion=getattr(_context, "_expanded_parameters", None),
                )
                page_statements.append(captured)
                _retain_patent_evidence(
                    evidence,
                    kind="actual_execution",
                    page=page_label,
                    sequence=len(page_statements),
                    **_patent_execution_record(captured),
                )

        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            result = list_patent_families(session, context=context, limit=100)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        first_ids = [str(row.id) for row in result.families]
        first_inputs = _patent_hydration_ids(page_statements[1], company_id=company_id)
        _retain_patent_evidence(
            evidence,
            kind="admitted_page",
            page="first",
            actual_ids=first_ids,
            hydration_inputs=first_inputs,
            query_count=len(statements),
            next_cursor=result.next_cursor,
        )
        assert [col.key for col in page_statements[0].statement.selected_columns] == [
            "id",
            "docket_id",
        ]
        plans = [
            (
                plan_limit,
                _patent_family_page_plan(
                    session,
                    page_statements[0],
                    limit=plan_limit,
                    generic=generic,
                    evidence=evidence,
                ),
            )
            for generic in (False, True, None)
            for plan_limit in (101, 1)
        ]
        hydration_plans = [
            _patent_family_page_plan(
                session,
                page_statements[1],
                limit=None,
                generic=generic,
                kind="hydration",
                evidence=evidence,
                expected_ids=first_ids,
            )
            for generic in (False, True, None)
        ]
        diagnostic_plans = _patent_later_hydration_plans(
            session, page_statements, evidence,
            expected_versions=[(company_id, str(row.id), row.version) for row in result.families],
        )
        assert len(result.families) == 100 and result.next_cursor is not None
        assert len(statements) <= 12
        assert sorted(first_inputs) == sorted(first_ids)
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
            event.listen(pg_engine, "before_cursor_execute", capture)
            try:
                session.execute(select(wide).order_by(wide.id).limit(101)).all()
            finally:
                event.remove(pg_engine, "before_cursor_execute", capture)
            old_plan = _patent_family_page_plan(
                session,
                page_statements[-1],
                limit=101,
                generic=True,
                kind="pre_feature_outer_shape",
                evidence=evidence,
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
        page_label = "second"
        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            second = list_patent_families(
                session, context=context, limit=100, cursor=result.next_cursor
            )
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        second_ids = [str(row.id) for row in second.families]
        second_inputs = _patent_hydration_ids(page_statements[1], company_id=company_id)
        _retain_patent_evidence(
            evidence,
            kind="admitted_page",
            page="second",
            actual_ids=second_ids,
            hydration_inputs=second_inputs,
            first_ids=first_ids,
            query_count=len(statements),
            next_cursor=second.next_cursor,
        )
        hydration_plans.extend(
            _patent_family_page_plan(
                session,
                page_statements[1],
                limit=None,
                generic=generic,
                kind="cursor_hydration",
                evidence=evidence,
                expected_ids=second_ids,
            )
            for generic in (False, True, None)
        )
        diagnostic_plans.extend(
            _patent_later_hydration_plans(
                session, page_statements, evidence, prefix="cursor_",
                expected_versions=[
                    (company_id, str(row.id), row.version) for row in second.families
                ],
            )
        )
        cursor_plans = []
        for generic in (False, True, None):
            for plan_limit in (101, 1):
                cursor_plan = _patent_family_page_plan(
                    session,
                    page_statements[0],
                    limit=plan_limit,
                    generic=generic,
                    evidence=evidence,
                )
                cursor_plans.append(cursor_plan)
                plans.append((plan_limit, cursor_plan))
        _retain_patent_evidence(
            evidence, kind="catalog_after_pages", catalog=_patent_catalog_snapshot(session)
        )
        assert len(statements) <= 12
        assert sorted(second_inputs) == sorted(second_ids)
        assert set(first_inputs).isdisjoint(second_inputs)
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
        _retain_patent_evidence(
            evidence,
            kind="complete_traversal",
            authorized_ids=seen,
            late_match_ids=[str(row.id) for row in found.families],
        )
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
        for stage, plan in diagnostic_plans:
            _assert_patent_plan_common_work(plan)
            if stage == "disclosure_version_hydration":
                _assert_patent_disclosure_hydration_work(plan, limit=100)


def test_patent_family_list_stale_unique_tenant_statistics_bound_docket_work(
    migration_pg_engine,
    request,
    tmp_path,
):
    _train_patent_family_unique_statistics(migration_pg_engine)
    _check_patent_family_scale(migration_pg_engine, request=request, tmp_path=tmp_path)


def _train_patent_family_unique_statistics(migration_pg_engine):
    # Train unique tenant statistics before a concentrated import; do not analyze it away.
    with migration_pg_engine.begin() as connection:
        for table in (
            "ip_docket_records",
            "ip_patent_families",
            "matter_access_grants",
            "ethical_walls",
        ):
            connection.execute(text(f"ALTER TABLE {table} SET (autovacuum_enabled = false)"))
    for _ in range(32):
        _seed(migration_pg_engine)
    with migration_pg_engine.begin() as connection:
        connection.execute(text("ANALYZE ip_docket_records"))
        connection.execute(text("ANALYZE ip_patent_families"))
        connection.execute(text("ANALYZE matter_access_grants"))
        connection.execute(text("ANALYZE ethical_walls"))


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
    request,
    tmp_path,
):
    _train_patent_family_mixed_statistics(migration_pg_engine)
    _check_patent_family_scale(
        migration_pg_engine, request=request, tmp_path=tmp_path, mixed_order=True
    )


def test_patent_family_list_fresh_mixed_tenant_statistics_bound_outer_family_work(
    migration_pg_engine,
    request,
    tmp_path,
):
    _train_patent_family_mixed_statistics(migration_pg_engine)
    _check_patent_family_scale(
        migration_pg_engine,
        request=request,
        tmp_path=tmp_path,
        mixed_order=True,
        fresh_statistics=True,
    )


@pytest.mark.parametrize("profile", ["fresh", "stale_unique", "stale_mixed"])
def test_patent_family_list_default_join_scale_profiles(
    migration_pg_engine, request, tmp_path, profile
):
    if profile == "stale_unique":
        _train_patent_family_unique_statistics(migration_pg_engine)
    elif profile == "stale_mixed":
        _train_patent_family_mixed_statistics(migration_pg_engine)
    _check_patent_family_scale(
        migration_pg_engine,
        request=request,
        tmp_path=tmp_path,
        mixed_order=profile == "stale_mixed",
        fresh_statistics=profile == "fresh",
        adverse_joins=False,
    )


def test_patent_family_list_retained_grants_bound_authorization_work(
    migration_pg_engine, request, tmp_path
):
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
    _check_patent_family_scale(migration_pg_engine, request=request, tmp_path=tmp_path)


def test_patent_family_list_stale_low_id_histogram_bounds_cursor_work(
    migration_pg_engine, request, tmp_path
):
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
    _check_patent_family_scale(
        migration_pg_engine, request=request, tmp_path=tmp_path, family_uuid_base=imported_base
    )


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
        def mutate(writer):
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

        _assert_patent_family_page_rejects_interleaved_change(
            pg_engine,
            session,
            context=context,
            family_id=family_id,
            docket_id=docket_id,
            title=title,
            mutate=mutate,
        )

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


def _assert_patent_family_page_rejects_interleaved_change(
    pg_engine, session, *, context, family_id, docket_id, title, mutate
):
    warm_family = session.get(IpPatentFamily, family_id)
    assert warm_family.docket_id == docket_id
    changed = False

    def interleave(_conn, _cursor, _statement, _params, execution_context, _many):
        nonlocal changed
        compiled = execution_context.compiled
        if changed or compiled is None or not compiled.statement.is_select:
            return
        if not execution_context.execution_options.get("populate_existing"):
            return
        if not _is_patent_entity_select(compiled.statement, IpPatentFamily):
            return
        changed = True
        with Session(pg_engine) as writer:
            mutate(writer)
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


@pytest.mark.parametrize("deleted_position", ["with_successor", "without_successor"])
def test_patent_family_deleted_warm_identity_rejects_exact_seek_miss(
    migration_pg_engine, deleted_position
):
    pg_engine = migration_pg_engine
    with Session(pg_engine) as session:
        existing_ids = list(session.scalars(select(IpPatentFamily.id)))
        assert existing_ids == []
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        client = Client(company_id=company_id, name="Deleted family seek", client_type="corporate")
        session.add(client)
        session.flush()
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        pairs = {}
        for _ in range(2):
            docket = IpDocketRecord(
                company_id=company_id,
                record_type="patent_family",
                title=f"Warm family deletion {uuid4()}",
                status="draft",
                restricted=True,
                current_version=1,
                created_by_membership_id=actor_id,
            )
            session.add(docket)
            session.flush()
            seed_restricted_ip_creator_access(session, context=context, docket=docket)
            asset = IpAsset(
                company_id=company_id,
                docket_id=docket.id,
                asset_kind="patent",
                jurisdiction="UNSPECIFIED",
                title=docket.title,
            )
            session.add(asset)
            session.flush()
            family = IpPatentFamily(
                company_id=company_id,
                docket_id=docket.id,
                asset_id=asset.id,
                client_id=client.id,
            )
            session.add(family)
            session.flush()
            pairs[family.id] = (family, docket)
        ordered_ids = list(session.scalars(select(IpPatentFamily.id).order_by(IpPatentFamily.id)))
        assert len(ordered_ids) == 2
        family_id = ordered_ids[0 if deleted_position == "with_successor" else -1]
        sibling_id = next(key for key in ordered_ids if key != family_id)
        family, docket = pairs[family_id]
        _sibling, sibling_docket = pairs[sibling_id]
        docket_id, asset_id, title = docket.id, family.asset_id, docket.title
        sibling_docket_id = sibling_docket.id
        # Keep the existing delete race's versionless target; never remove or
        # disable append-only evidence. The retained sibling is fully readable.
        session.add(
            IpPatentFamilyVersion(
                company_id=company_id,
                family_id=sibling_id,
                version=sibling_docket.current_version,
                client_id=client.id,
                title=sibling_docket.title,
                disclosure_date=date(2026, 9, 5),
                disclosure_narrative="Retained successor disclosure.",
                created_by_membership_id=actor_id,
                reason="Initial inventor disclosure.",
            )
        )
        session.commit()
        retained_sibling = get_patent_family(session, context=context, family_id=sibling_id)
        target_versions = list(
            session.scalars(
                select(IpPatentFamilyVersion.id).where(IpPatentFamilyVersion.family_id == family_id)
            )
        )
        assert target_versions == []
        observed_successors = []

        def delete_and_probe(writer):
            deleted = writer.execute(delete(IpPatentFamily).where(IpPatentFamily.id == family_id))
            assert deleted.rowcount == 1
            successor = writer.scalar(
                select(IpPatentFamily.id)
                .where(IpPatentFamily.id >= family_id)
                .order_by(IpPatentFamily.id)
                .limit(1)
            )
            observed_successors.append(successor)

        _assert_patent_family_page_rejects_interleaved_change(
            pg_engine,
            session,
            context=context,
            family_id=family_id,
            docket_id=docket_id,
            title=title,
            mutate=delete_and_probe,
        )
        expected_successor = sibling_id if deleted_position == "with_successor" else None
        assert observed_successors == [expected_successor]

    with Session(pg_engine) as verify:
        context = _ip_race_context(verify, company_id=company_id, membership_id=actor_id)
        assert verify.get(IpPatentFamily, family_id) is None
        retained_docket = verify.get(IpDocketRecord, docket_id)
        assert retained_docket.company_id == company_id
        assert retained_docket.record_type == "patent_family" and retained_docket.restricted
        assert retained_docket.status == "draft" and retained_docket.is_active
        assert retained_docket.current_version == 1 and retained_docket.lifecycle_version == 0
        assert verify.get(IpAsset, asset_id).docket_id == docket_id
        visible = set(
            verify.scalars(
                select(IpDocketRecord.id).where(
                    IpDocketRecord.company_id == company_id,
                    visible_ip_dockets_filter(verify, context=context),
                )
            )
        )
        assert visible == {docket_id, sibling_docket_id}
        assert get_patent_family(verify, context=context, family_id=sibling_id) == retained_sibling
        remaining_versions = list(
            verify.scalars(
                select(IpPatentFamilyVersion.family_id).where(
                    IpPatentFamilyVersion.company_id == company_id
                )
            )
        )
        assert remaining_versions == [sibling_id]


def test_current_disclosure_seek_rejects_all_composite_successors(
    migration_pg_engine, request, tmp_path
):
    pg_engine = migration_pg_engine
    seeded = [_seed(pg_engine), _seed(pg_engine)]
    lower, upper = sorted(seeded, key=lambda row: row[0])
    company_id, actor_id, first = lower
    other_company, other_actor, other = upper
    evidence = _patent_evidence_path(request, tmp_path)
    with Session(pg_engine) as session:
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        sibling = create_patent_family(
            session,
            context=context,
            payload=PatentFamilyCreateRequest(
                title=f"Composite disclosure sibling {uuid4()}",
                client_id=first.facts.client_id,
                disclosure_date=date(2026, 9, 5),
                disclosure_narrative="Retained sibling disclosure.",
            ),
            idempotency_key=str(uuid4()),
        )
        low, high = sorted((first, sibling), key=lambda row: str(row.id))
        scenarios = (
            ("version", low, company_id, actor_id, (company_id, str(low.id), 3)),
            ("family", low, company_id, actor_id, (company_id, str(high.id), 1)),
            ("tenant", high, company_id, actor_id, (other_company, str(other.id), 1)),
            ("none", other, other_company, other_actor, None),
        )
        completed = []
        for kind, target, tenant, actor, expected_successor in scenarios:
            context = _ip_race_context(session, company_id=tenant, membership_id=actor)
            warm = session.scalars(
                select(IpPatentFamilyVersion).where(
                    IpPatentFamilyVersion.company_id == tenant,
                    IpPatentFamilyVersion.family_id == str(target.id),
                    IpPatentFamilyVersion.version == 1,
                )
            ).one()
            warm_title = warm.title
            boundary = session.begin_nested()
            try:
                # Inject an inconsistent current pointer without deleting or
                # modifying immutable history; roll back each negative fixture.
                session.execute(
                    update(IpDocketRecord)
                    .where(IpDocketRecord.id == str(target.docket_id))
                    .values(current_version=2)
                )
                if kind == "version":
                    fields = {
                        field.name: getattr(warm, field.name)
                        for field in IpPatentFamilyVersion.__table__.columns
                    }
                    fields.update(id=str(uuid4()), version=3, reason="Negative seek fixture.")
                    session.execute(insert(IpPatentFamilyVersion.__table__), fields)
                successor = session.execute(
                    select(
                        IpPatentFamilyVersion.company_id,
                        IpPatentFamilyVersion.family_id,
                        IpPatentFamilyVersion.version,
                    )
                    .where(
                        tuple_(
                            IpPatentFamilyVersion.company_id,
                            IpPatentFamilyVersion.family_id,
                            IpPatentFamilyVersion.version,
                        ) >= (tenant, str(target.id), 2)
                    )
                    .order_by(
                        IpPatentFamilyVersion.company_id,
                        IpPatentFamilyVersion.family_id,
                        IpPatentFamilyVersion.version,
                    )
                    .limit(1)
                ).first()
                actual_successor = tuple(successor) if successor is not None else None
                _retain_patent_evidence(
                    evidence, kind="composite_seek_negative", scenario=kind,
                    requested=(tenant, str(target.id), 2),
                    expected_successor=expected_successor, actual_successor=actual_successor,
                )
                assert actual_successor == expected_successor
                with pytest.raises(HTTPException) as rejected:
                    list_patent_families(
                        session, context=context, query=target.facts.title, limit=1
                    )
                assert rejected.value.status_code == 409
                assert rejected.value.detail["code"] == "patent_family_integrity"
                if kind == "family":
                    # A good sibling cannot conceal one missing admitted key.
                    with pytest.raises(HTTPException) as mixed:
                        list_patent_families(session, context=context, limit=100)
                    assert mixed.value.status_code == 409
                    assert mixed.value.detail["code"] == "patent_family_integrity"
                assert session.get(IpPatentFamilyVersion, warm.id) is warm
                assert warm.version == 1 and warm.title == warm_title
                completed.append(kind)
            finally:
                boundary.rollback()
            restored = get_patent_family(session, context=context, family_id=str(target.id))
            assert restored == target
            _retain_patent_evidence(
                evidence, kind="composite_seek_restored", scenario=kind,
                family_id=str(restored.id), version=restored.version,
            )
        assert completed == ["version", "family", "tenant", "none"]
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        original = session.scalars(
            select(IpPatentFamilyVersion).where(
                IpPatentFamilyVersion.company_id == company_id,
                IpPatentFamilyVersion.family_id == str(low.id),
                IpPatentFamilyVersion.version == 1,
            )
        ).one()
        boundary = session.begin_nested()
        try:
            for number in (2, 3):
                fields = {
                    field.name: getattr(original, field.name)
                    for field in IpPatentFamilyVersion.__table__.columns
                }
                fields.update(
                    id=str(uuid4()), version=number, title=f"Exact disclosure version {number}",
                    reason="Composite current-version selection fixture.",
                )
                session.execute(insert(IpPatentFamilyVersion.__table__), fields)
            session.execute(
                update(IpDocketRecord).where(IpDocketRecord.id == str(low.docket_id))
                .values(current_version=2)
            )
            current = list_patent_families(
                session, context=context, query=low.facts.title, limit=1
            )
            assert len(current.families) == 1 and current.next_cursor is None
            assert str(current.families[0].id) == str(low.id)
            assert current.families[0].version == 2
            assert current.families[0].facts.title == "Exact disclosure version 2"
            _retain_patent_evidence(
                evidence, kind="composite_seek_exact_middle_version",
                family_id=str(low.id), version=current.families[0].version,
            )
        finally:
            boundary.rollback()
        for tenant, actor, expected in (
            (company_id, actor_id, {str(low.id), str(high.id)}),
            (other_company, other_actor, {str(other.id)}),
        ):
            context = _ip_race_context(session, company_id=tenant, membership_id=actor)
            listed = list_patent_families(session, context=context)
            assert {str(row.id) for row in listed.families} == expected
            assert all(row.version == 1 for row in listed.families)


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
                        records[successor_target],
                        successor_target,
                        subject_id,
                    )
                    assert lookup(target_id, subject) is None
                for target_id in (first_id, last_id):
                    assert lookup(target_id, subject_id) == records[target_id]
        session.rollback()
