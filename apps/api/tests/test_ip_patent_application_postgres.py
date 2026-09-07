from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpDocketRecord,
    IpPatentApplication,
    IpPatentApplicationIdentifier,
    IpPatentApplicationIdentity,
    IpPatentApplicationVersion,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_patents import (
    PatentApplicationCorrectionRequest,
    PatentApplicationCreateRequest,
)
from caseops_api.services.ip_patent_applications import (
    _lock_application_identity_writer,
    correct_patent_application,
    create_patent_application,
    list_patent_applications,
)
from tests import test_ip_patent_applications as journeys
from tests.test_ip_patent_postgres import _seed as _seed_other_family
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "journey",
    [
        "test_terminal_application_is_read_only_and_does_not_close_its_family",
        "test_tenant_isolation_includes_sources_history_search_and_same_identifier_admission",
        "test_current_identifier_uniqueness_and_correction_rollback_preserve_immutable_history",
        "test_application_version_and_identifier_rows_are_database_append_only",
        "test_closed_sibling_and_family_sources_do_not_block_active_application_corrections",
        "test_source_read_exception_never_admits_a_terminal_mutation_target",
    ],
)
def test_application_http_journeys_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)


def _setup(client):
    bootstrap, headers, family, payload = journeys._setup(client)
    engine = get_session_factory().kw["bind"]
    return engine, bootstrap, headers, family, payload


def _context(session, bootstrap):
    return _ip_race_context(
        session, company_id=bootstrap["company"]["id"], membership_id=bootstrap["membership"]["id"]
    )


def _clone(row, **changes):
    return {
        **{column.name: getattr(row, column.name) for column in row.__table__.columns},
        **changes,
    }


def test_application_duplicate_waiter_and_other_tenant_are_bounded_on_postgres(
    isolated_postgres_client,
):
    engine, bootstrap, headers, _, raw = _setup(isolated_postgres_client)
    other_company, other_actor, other_family = _seed_other_family(engine)
    payload = PatentApplicationCreateRequest.model_validate(raw)
    name = f"patent-identifier-waiter-{uuid4().hex[:12]}"

    def waiting_writer():
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                create_patent_application(
                    session,
                    context=_context(session, bootstrap),
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail["code"]
            raise AssertionError("Concurrent duplicate application was admitted")

    with Session(engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        context = _context(winner, bootstrap)
        _lock_application_identity_writer(winner, context)
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(engine, application_name=name)
            # Another firm's identity lock and ordinary disclosure correction remain available.
            from caseops_api.schemas.ip_patents import PatentFamilyCorrectionRequest
            from caseops_api.services.ip_patent_families import correct_patent_family

            with Session(engine) as unrelated:
                unrelated.execute(text("SET lock_timeout = '750ms'"))
                other_context = _ip_race_context(
                    unrelated, company_id=other_company, membership_id=other_actor
                )
                _lock_application_identity_writer(unrelated, other_context)
                updated = correct_patent_family(
                    unrelated,
                    context=other_context,
                    family_id=str(other_family.id),
                    payload=PatentFamilyCorrectionRequest(
                        expected_version=1,
                        expected_lifecycle_version=0,
                        facts=other_family.facts,
                        reason="Unrelated tenant remains responsive.",
                    ),
                )
                assert updated.version == 2
            created = create_patent_application(
                winner, context=context, payload=payload, idempotency_key=str(uuid4())
            )
            assert future.result(timeout=8) == (409, "patent_identifier_exists")
        finally:
            winner.rollback()
    rows = isolated_postgres_client.get(journeys.BASE, headers=headers).json()["applications"]
    assert len(rows) == 1 and rows[0]["id"] == str(created.id)


def test_concurrent_identifier_swaps_and_stale_corrections_roll_back_on_postgres(
    isolated_postgres_client,
):
    engine, bootstrap, headers, _, payload = _setup(isolated_postgres_client)
    first = journeys._create(isolated_postgres_client, headers, payload).json()
    second_raw = {
        **payload,
        "facts": {
            **payload["facts"],
            "identifiers": [
                {**payload["facts"]["identifiers"][0], "raw_value": "Separate-002"},
            ],
        },
    }
    second_response = journeys._create(isolated_postgres_client, headers, second_raw)
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()

    def run_pair(commands):
        barrier = Barrier(2)

        def writer(record, changes):
            with Session(engine) as session:
                session.execute(text("SET lock_timeout = '5s'"))
                context = _context(session, bootstrap)
                barrier.wait(timeout=5)
                try:
                    result = correct_patent_application(
                        session,
                        context=context,
                        application_id=record["id"],
                        payload=PatentApplicationCorrectionRequest.model_validate(
                            journeys._correction(record, **changes)
                        ),
                    )
                    return 200, result.version
                except HTTPException as exc:
                    session.rollback()
                    return exc.status_code, exc.detail["code"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(writer, record, changes) for record, changes in commands]
            return [future.result(timeout=12) for future in futures]

    assert run_pair(
        [
            (first, {"identifiers": second["facts"]["identifiers"]}),
            (second, {"identifiers": first["facts"]["identifiers"]}),
        ]
    ) == [(409, "patent_identifier_exists"), (409, "patent_identifier_exists")]
    for record in (first, second):
        assert (
            isolated_postgres_client.get(f"{journeys.BASE}/{record['id']}", headers=headers).json()
            == record
        )
    outcomes = run_pair(
        [(first, {"title": "Concurrent title A"}), (first, {"title": "Concurrent title B"})]
    )
    assert sorted(outcomes, key=lambda outcome: outcome[0]) == [
        (200, 2),
        (409, "patent_application_stale"),
    ]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationVersion)) == 3
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationIdentifier)) == 3
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationIdentity)) == 2


def test_application_migration_source_ownership_and_retained_downgrade_on_postgres(
    isolated_postgres_client,
):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    engine, _, headers, _, payload = _setup(isolated_postgres_client)
    created = journeys._create(isolated_postgres_client, headers, payload)
    assert created.status_code == 201, created.text
    with Session(engine) as session:
        version = session.scalar(select(IpPatentApplicationVersion))
        identifier = session.scalar(select(IpPatentApplicationIdentifier))
        identity = session.scalar(select(IpPatentApplicationIdentity))
        for model, row, changes in (
            (IpPatentApplicationVersion, version, {"company_id": str(uuid4()), "version": 2}),
            (
                IpPatentApplicationVersion,
                version,
                {"source_document_id": str(uuid4()), "version": 2},
            ),
            (
                IpPatentApplicationIdentifier,
                identifier,
                {"application_id": str(uuid4()), "ordinal": 1},
            ),
            (
                IpPatentApplicationIdentity,
                identity,
                {"application_version_id": str(uuid4()), "identity_sha256": "f" * 64},
            ),
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(
                    insert(model.__table__).values(_clone(row, id=str(uuid4()), **changes))
                )
        session.rollback()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", os.environ["CASEOPS_TEST_POSTGRES_URL"])
    head = ScriptDirectory.from_config(config).get_current_head()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Patent application evidence exists"):
            command.downgrade(config, "20260906_0001")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid "
                        "WHERE c.relname LIKE 'ip_patent_application%' "
                        "AND (NOT i.indisvalid OR NOT i.indisready)"
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE "
                        "tgname IN ('trg_ip_patent_application_versions_append_only', "
                        "'trg_ip_patent_application_identifiers_append_only') AND tgenabled='O'"
                    )
                )
                == 2
            )
        assert (
            isolated_postgres_client.get(
                f"{journeys.BASE}/{created.json()['id']}", headers=headers
            ).json()
            == created.json()
        )


def test_application_list_10000_rows_is_bounded_with_family_acl_and_exact_identifier_on_postgres(
    isolated_postgres_client,
):
    engine, bootstrap, headers, family, payload = _setup(isolated_postgres_client)
    created = journeys._create(isolated_postgres_client, headers, payload)
    assert created.status_code == 201, created.text
    with Session(engine) as session:
        application = session.get(IpPatentApplication, created.json()["id"])
        docket = session.get(IpDocketRecord, application.docket_id)
        asset = session.get(IpAsset, application.asset_id)
        version = session.scalar(select(IpPatentApplicationVersion))
        identifier = session.scalar(select(IpPatentApplicationIdentifier))
        identity = session.scalar(select(IpPatentApplicationIdentity))
        grant = session.scalar(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket.id)
        )
        allowed = {docket.id}
        for batch in range(20):
            rows = {
                model: []
                for model in (
                    IpDocketRecord,
                    IpAsset,
                    IpPatentApplication,
                    IpPatentApplicationVersion,
                    IpPatentApplicationIdentifier,
                    IpPatentApplicationIdentity,
                    MatterAccessGrant,
                )
            }
            for offset in range(500):
                app_id, docket_id, asset_id, version_id = (str(uuid4()) for _ in range(4))
                number = f"scale-{batch}-{offset}"
                rows[IpDocketRecord].append(_clone(docket, id=docket_id, title=number))
                rows[IpAsset].append(_clone(asset, id=asset_id, docket_id=docket_id))
                rows[IpPatentApplication].append(
                    _clone(application, id=app_id, docket_id=docket_id, asset_id=asset_id)
                )
                rows[IpPatentApplicationVersion].append(
                    _clone(version, id=version_id, application_id=app_id, title=number)
                )
                rows[IpPatentApplicationIdentifier].append(
                    _clone(
                        identifier,
                        id=str(uuid4()),
                        application_id=app_id,
                        application_version_id=version_id,
                        raw_value=number,
                    )
                )
                rows[IpPatentApplicationIdentity].append(
                    _clone(
                        identity,
                        id=str(uuid4()),
                        application_id=app_id,
                        application_version_id=version_id,
                        value_key=number,
                        identity_sha256=f"{batch * 500 + offset:064x}",
                    )
                )
                if offset % 2 == 0:
                    rows[MatterAccessGrant].append(
                        _clone(grant, id=str(uuid4()), ip_docket_id=docket_id)
                    )
                    allowed.add(docket_id)
            for model, values in rows.items():
                session.execute(insert(model.__table__), values)
            session.commit()
        for model in (
            IpDocketRecord,
            IpPatentApplication,
            IpPatentApplicationIdentity,
            MatterAccessGrant,
        ):
            session.execute(text(f"ANALYZE {model.__tablename__}"))
        context = _context(session, bootstrap)
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        session.execute(text("SET LOCAL enable_hashjoin = off"))
        session.execute(text("SET LOCAL enable_mergejoin = off"))
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        for filters in (
            {},
            {"family_id": family["id"]},
            {"query": "in/2026/001-a"},
            {"query": "does-not-exist"},
        ):
            statements.clear()
            event.listen(engine, "before_cursor_execute", capture)
            try:
                result = list_patent_applications(session, context=context, limit=100, **filters)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            assert len(statements) <= 25
            assert all(str(row.docket_id) in allowed for row in result.applications)
            if "query" not in filters:
                assert len(result.applications) == 100 and result.next_cursor is not None
            elif filters["query"] == "does-not-exist":
                assert not result.applications and result.next_cursor is None
            else:
                assert [str(row.id) for row in result.applications] == [created.json()["id"]]
