from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.db.models import (
    Client,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    IpAsset,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpPatentFamily,
    IpPatentFamilyVersion,
    MatterAccessGrant,
    PrivateProjectionEvent,
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
from caseops_api.services.private_retrieval import (
    ensure_active_private_generation,
    lock_private_authority_writer,
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


def test_patent_family_list_10000_rows_has_bounded_queries_and_acl_on_postgres(pg_engine):
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

        for batch in range(20):
            dockets, assets, families, versions, grants = [], [], [], [], []
            for offset in range(500):
                docket_id, asset_id, family_id = (str(uuid4()) for _ in range(3))
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
        context = _ip_race_context(session, company_id=company_id, membership_id=actor_id)
        statements = []
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        session.execute(text("SET LOCAL enable_hashjoin = off"))
        session.execute(text("SET LOCAL enable_mergejoin = off"))

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            result = list_patent_families(session, context=context, limit=100)
        finally:
            event.remove(pg_engine, "before_cursor_execute", capture)
        assert len(result.families) == 100 and result.next_cursor is not None
        assert len(statements) <= 12
        allowed = set(
            session.scalars(
                select(MatterAccessGrant.ip_docket_id).where(
                    MatterAccessGrant.company_id == company_id,
                    MatterAccessGrant.membership_id == actor_id,
                )
            )
        )
        assert all(str(row.docket_id) in allowed for row in result.families)
