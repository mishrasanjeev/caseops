from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDocketRecord,
    IpPatentApplication,
    IpPatentEvidenceDocument,
    IpPatentEvidenceVersion,
    IpPatentProsecutionEvent,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_patent_prosecution import (
    PatentEvidenceCreateRequest,
    PatentProsecutionCreateRequest,
)
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_families import _lock_sources_and_dockets
from caseops_api.services.ip_patent_prosecution import (
    _manifest_digest,
    create_patent_evidence,
    create_patent_prosecution,
    list_patent_evidence,
)
from tests import test_ip_patent_prosecution as journeys
from tests.test_ip_patent_application_postgres import _clone
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "journey",
    [
        "test_patent_manifest_filing_and_new_edition_retain_exact_receipt_history",
        "test_patent_work_idempotency_stale_commands_and_source_hash_fail_closed",
        "test_patent_backdated_and_exceptional_preview_must_be_acknowledged_and_current",
        "test_patent_work_closure_reopen_stale_replay_and_second_closure",
        "test_patent_manifest_and_event_direct_mutation_rejected",
        "test_patent_work_current_source_access_and_other_application_scope",
        "test_patent_event_replay_reopen_and_current_access_revocation",
        "test_patent_work_pages_and_manifest_contracts_are_bounded",
        "test_every_patent_document_kind_retains_exact_source_and_edition_history",
        "test_every_admitted_prosecution_event_preserves_sibling_and_audited_history",
    ],
)
def test_patent_work_http_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)


def _context(session, bootstrap, membership_id=None):
    return _ip_race_context(
        session,
        company_id=bootstrap["company"]["id"],
        membership_id=membership_id or bootstrap["membership"]["id"],
    )


@pytest.mark.parametrize("replay", [False, True])
def test_different_actor_closure_wins_waiting_patent_manifest(isolated_postgres_client, replay):
    _closure_wins_waiting_work(isolated_postgres_client, replay, "evidence")


@pytest.mark.parametrize("replay", [False, True])
def test_different_actor_closure_wins_waiting_patent_prosecution(isolated_postgres_client, replay):
    _closure_wins_waiting_work(isolated_postgres_client, replay, "prosecution")


def _closure_wins_waiting_work(client, replay, operation):
    bootstrap, headers, _, app, raw = journeys._fixture(client)
    if operation == "prosecution":
        raw = journeys._previewed(client, headers, app, journeys._event(app, raw["source"]))
    schema = (
        PatentEvidenceCreateRequest if operation == "evidence" else PatentProsecutionCreateRequest
    )
    writer = create_patent_evidence if operation == "evidence" else create_patent_prosecution
    model = IpPatentEvidenceVersion if operation == "evidence" else IpPatentProsecutionEvent
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        other_actor = _seed_membership(session, bootstrap["company"]["id"], role="admin")
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.membership_id == bootstrap["membership"]["id"]
                )
            )
        )
        for grant in grants:
            session.execute(
                insert(MatterAccessGrant.__table__).values(
                    _clone(grant, id=str(uuid4()), membership_id=other_actor)
                )
            )
        session.commit()
    payload = schema.model_validate(raw)
    key = str(uuid4())
    if replay:
        with Session(engine) as session:
            writer(
                session,
                context=_context(session, bootstrap, other_actor),
                application_id=app["id"],
                payload=payload,
                idempotency_key=key,
            )
    name = f"patent-{operation}-close-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                writer(
                    session,
                    context=_context(session, bootstrap, other_actor),
                    application_id=app["id"],
                    payload=payload,
                    idempotency_key=key,
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError(f"A terminal patent {operation} command succeeded")

    with Session(engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        context = _lock_ip_writer_context(
            winner, context=_context(winner, bootstrap), required_capability="ip:write"
        )
        _lock_sources_and_dockets(winner, context, [payload.source], {app["docket_id"]})
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(engine, application_name=name)
            transition_ip_docket_lifecycle(
                winner,
                context=context,
                docket_id=app["docket_id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="closed",
                    effective_at=datetime.now(UTC),
                    reason="Explicit closure wins over the waiting manifest writer.",
                    outcome="closed",
                    source="lawyer_review",
                    evidence_ref="test:manifest-close-race",
                    linked_matter_handling="reviewed",
                ),
            )
            winner.commit()
            assert future.result(timeout=8) == 404
        finally:
            winner.rollback()
    with Session(engine) as session:
        assert session.get(IpDocketRecord, app["docket_id"]).status == "closed"
        assert not session.get(IpDocketRecord, app["docket_id"]).is_active
        assert session.scalar(select(func.count()).select_from(model)) == int(replay)
        application = session.get(IpPatentApplication, app["id"])
        assert application.work_sequence == int(replay)
        assert application.prosecution_phase == (
            "filing_preparation" if operation == "prosecution" and replay else "disclosure"
        )


def test_patent_500_retained_editions_query_budget_and_hard_history_limit(isolated_postgres_client):
    bootstrap, headers, _, app, raw = journeys._fixture(isolated_postgres_client)
    first = journeys._save(isolated_postgres_client, headers, app, "evidence", raw)
    assert first.status_code == 201, first.text
    engine = get_session_factory().kw["bind"]
    payload = PatentEvidenceCreateRequest.model_validate(raw)

    def append_history(start, end, predecessor):
        with Session(engine) as session:
            original = session.get(IpPatentEvidenceVersion, first.json()["id"])
            document = session.scalar(select(IpPatentEvidenceDocument))
            for edition in range(start, end + 1):
                identifier = str(uuid4())
                title = f"Retained synthetic edition {edition}"
                session.execute(
                    insert(IpPatentEvidenceVersion.__table__).values(
                        _clone(
                            original,
                            id=identifier,
                            predecessor_id=predecessor,
                            edition=edition,
                            sequence=edition,
                            title=title,
                            manifest_sha256=_manifest_digest(
                                title, payload.document_kind, payload.source, payload.documents
                            ),
                        )
                    )
                )
                session.execute(
                    insert(IpPatentEvidenceDocument.__table__).values(
                        _clone(
                            document,
                            id=str(uuid4()),
                            evidence_id=identifier,
                        )
                    )
                )
                predecessor = identifier
            session.get(IpPatentApplication, app["id"]).work_sequence = end
            session.commit()
        return predecessor

    latest = append_history(2, 500, first.json()["id"])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentEvidenceVersion)) == 500
        assert session.scalar(select(func.count()).select_from(IpPatentEvidenceDocument)) == 500
        assert (
            session.scalar(select(func.count(func.distinct(IpPatentEvidenceVersion.root_id)))) == 1
        )
        context = _context(session, bootstrap)
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            page = list_patent_evidence(
                session, context=context, application_id=app["id"], limit=100
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(page.records) == 100 and page.next_cursor == 401
        assert sum(row.is_current for row in page.records) == 1
        assert len(statements) <= 30, statements
        manifest_queries = [sql for sql in statements if "FROM ip_patent_evidence_documents" in sql]
        assert len(manifest_queries) == 1 and "LIMIT" in manifest_queries[0]
    key = str(uuid4())
    command = {
        **raw,
        "title": "Below-bound edition 501",
        "expected_work_sequence": 500,
        "predecessor_id": latest,
    }
    saved = journeys._save(isolated_postgres_client, headers, app, "evidence", command, key)
    assert saved.status_code == 201, saved.text
    replay = journeys._save(isolated_postgres_client, headers, app, "evidence", command, key)
    assert replay.status_code == 201 and replay.json() == saved.json()
    latest = append_history(502, 1000, saved.json()["id"])
    rejected = journeys._save(
        isolated_postgres_client,
        headers,
        app,
        "evidence",
        {
            **raw,
            "expected_work_sequence": 1000,
            "title": "Over-bound edition",
            "predecessor_id": latest,
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert "patent_evidence_history_limit" in rejected.text
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentEvidenceVersion)) == 1000
        original = session.scalar(select(IpPatentEvidenceDocument))
        with (
            pytest.raises(IntegrityError, match="Patent manifest is sealed"),
            session.begin_nested(),
        ):
            session.execute(
                insert(IpPatentEvidenceDocument.__table__).values(
                    _clone(
                        original,
                        id=str(uuid4()),
                        ordinal=1,
                    )
                )
            )


def _work_schema(engine):
    with engine.connect() as connection:
        return {
            "columns": connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns WHERE table_schema='public' AND "
                    "(table_name LIKE 'ip_patent_evidence%' "
                    "OR table_name='ip_patent_prosecution_events' "
                    "OR table_name LIKE 'ip_patent_proceeding%' "
                    "OR (table_name='ip_patent_applications' AND column_name='work_sequence')) "
                    "ORDER BY table_name, ordinal_position"
                )
            ).all(),
            "constraints": connection.execute(
                text(
                    "SELECT c.relname, con.conname, pg_get_constraintdef(con.oid) "
                    "FROM pg_constraint con "
                    "JOIN pg_class c ON c.oid=con.conrelid "
                    "WHERE c.relname LIKE 'ip_patent_evidence%' "
                    "OR c.relname='ip_patent_prosecution_events' "
                    "OR c.relname LIKE 'ip_patent_proceeding%' ORDER BY 1,2"
                )
            ).all(),
            "indexes": connection.execute(
                text(
                    "SELECT tablename, indexname, indexdef, i.indisvalid, i.indisready "
                    "FROM pg_indexes p "
                    "JOIN pg_class c ON c.relname=p.indexname "
                    "JOIN pg_index i ON i.indexrelid=c.oid "
                    "WHERE tablename LIKE 'ip_patent_evidence%' "
                    "OR tablename='ip_patent_prosecution_events' "
                    "OR tablename LIKE 'ip_patent_proceeding%' "
                    "ORDER BY 1,2"
                )
            ).all(),
            "triggers": connection.execute(
                text(
                    "SELECT c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid WHERE NOT t.tgisinternal AND "
                    "(c.relname LIKE 'ip_patent_evidence%' "
                    "OR c.relname='ip_patent_prosecution_events' "
                    "OR c.relname LIKE 'ip_patent_proceeding%') "
                    "ORDER BY 1,2"
                )
            ).all(),
        }


def test_patent_work_fresh_migration_roundtrip_and_retained_downgrade(
    migration_pg_engine, monkeypatch, tmp_path
):
    from alembic.config import Config
    from fastapi.testclient import TestClient

    from alembic import command
    from caseops_api.core.settings import get_settings
    from caseops_api.main import create_application

    engine = migration_pg_engine
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    before = _work_schema(engine)
    assert len(before["triggers"]) == 6 and before["columns"] and before["indexes"]
    command.downgrade(config, "20260909_0003")
    assert not any(_work_schema(engine).values())
    command.upgrade(config, "head")
    assert _work_schema(engine) == before
    for name, value in {
        "CASEOPS_ENV": "local",
        "CASEOPS_AUTO_MIGRATE": "false",
        "CASEOPS_AUTH_SECRET": "test-secret-should-be-at-least-32-bytes",
        "CASEOPS_AUTH_RATE_LIMIT_ENABLED": "false",
        "CASEOPS_DOCUMENT_STORAGE_PATH": (tmp_path / "documents").as_posix(),
        "CASEOPS_LLM_PROVIDER": "mock",
        "CASEOPS_EMBEDDING_PROVIDER": "mock",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    with TestClient(
        create_application(), headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    ) as client:
        _, headers, _, app, raw = journeys._fixture(client)
        saved = journeys._save(client, headers, app, "evidence", raw)
        assert saved.status_code == 201, saved.text
        from tests.test_ip_patent_proceedings import _intake

        proceeding = journeys._save(
            client, headers, app, "proceedings", _intake(raw, expected_work_sequence=1)
        )
        assert proceeding.status_code == 201, proceeding.text
        proceeding_url = f"{journeys.BASE}/{app['id']}/proceedings/{proceeding.json()['id']}"
        proceeding_before = client.get(proceeding_url, headers=headers).json()
        for _ in range(2):
            with pytest.raises(RuntimeError, match="Patent work evidence exists"):
                command.downgrade(config, "20260909_0003")
            command.upgrade(config, "head")
            assert _work_schema(engine) == before
            retained = client.get(
                f"{journeys.BASE}/{app['id']}/evidence/{saved.json()['id']}", headers=headers
            )
            assert retained.status_code == 200 and retained.json() == saved.json()
            assert client.get(proceeding_url, headers=headers).json() == proceeding_before
