from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    IpDocketRecord,
    IpPartyAndRole,
    IpPatentPartyDetail,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import IpLifecycleTransitionRequest
from caseops_api.schemas.ip_patents import PatentPartyCreateRequest
from caseops_api.services.idempotency import canonical_json_sha256
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.ip_patent_families import _lock_sources_and_dockets
from caseops_api.services.ip_patent_parties import create_patent_party, list_patent_parties
from tests import test_ip_patent_parties as journeys
from tests.test_ip_patent_application_postgres import _clone
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("kind", ["family", "application"])
def test_patent_party_roles_on_postgres(isolated_postgres_client, kind):
    journeys.test_all_patent_party_roles_preserve_canonical_facts_and_sourced_replacement(
        isolated_postgres_client, kind
    )


@pytest.mark.parametrize(
    "journey",
    [
        "test_patent_party_stale_duplicate_and_second_supersession_are_atomic",
        "test_patent_party_sources_clients_dates_and_immutable_rows_are_enforced",
        "test_patent_party_pages_pin_sequence_and_reject_stale_continuation",
        "test_patent_party_tenant_scope_closed_source_and_access_revocation",
    ],
)
def test_patent_party_http_boundaries_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)


def _context(session, bootstrap, membership_id=None):
    return _ip_race_context(
        session,
        company_id=bootstrap["company"]["id"],
        membership_id=membership_id or bootstrap["membership"]["id"],
    )


def test_concurrent_patent_party_commands_cannot_share_a_collection_sequence(
    isolated_postgres_client,
):
    bootstrap, _, _, record, _, raw = journeys._fixture(isolated_postgres_client)
    engine = get_session_factory().kw["bind"]
    barrier = Barrier(2)

    def write(name):
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            context = _context(session, bootstrap)
            payload = PatentPartyCreateRequest.model_validate(
                {**raw, "fact": {**raw["fact"], "name": name}}
            )
            barrier.wait(timeout=5)
            try:
                saved = create_patent_party(
                    session,
                    context=context,
                    docket_id=record["docket_id"],
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
                return 201, saved.sequence
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, name) for name in ("Inventor A", "Inventor B")]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(results, key=lambda row: row[0]) == [(201, 1), (409, "patent_parties_stale")]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IpPatentPartyDetail)) == 1
        assert session.scalar(select(func.count()).select_from(IpPartyAndRole)) == 1


@pytest.mark.parametrize("kind", ["family", "application"])
def test_closure_wins_over_a_different_actors_waiting_patent_party_command(
    isolated_postgres_client, kind,
):
    bootstrap, _, _, record, _, raw = journeys._fixture(isolated_postgres_client, kind)
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        other_actor = _seed_membership(session, bootstrap["company"]["id"], role="admin")
        for grant in list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.membership_id == bootstrap["membership"]["id"],
                )
            )
        ):
            session.execute(
                insert(MatterAccessGrant.__table__).values(
                    _clone(grant, id=str(uuid4()), membership_id=other_actor)
                )
            )
        session.commit()
    name = f"patent-party-close-{uuid4().hex[:12]}"
    payload = PatentPartyCreateRequest.model_validate(raw)

    def waiting_writer():
        with Session(engine) as session:
            session.execute(text("SET lock_timeout = '5s'"))
            session.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                create_patent_party(
                    session,
                    context=_context(session, bootstrap, other_actor),
                    docket_id=record["docket_id"],
                    payload=payload,
                    idempotency_key=str(uuid4()),
                )
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
            raise AssertionError("A party was created after closure won")

    with Session(engine) as winner, ThreadPoolExecutor(max_workers=1) as pool:
        context = _lock_ip_writer_context(
            winner, context=_context(winner, bootstrap), required_capability="ip:write"
        )
        _lock_sources_and_dockets(winner, context, [payload.fact.source], {record["docket_id"]})
        future = pool.submit(waiting_writer)
        try:
            _wait_for_postgres_lock_wait(engine, application_name=name)
            transition_ip_docket_lifecycle(
                winner,
                context=context,
                docket_id=record["docket_id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="closed",
                    effective_at=datetime.now(UTC),
                    reason="Explicit closure wins over pending party entry.",
                    outcome="closed",
                    source="lawyer_review",
                    evidence_ref="test:party-close-race",
                    linked_matter_handling="reviewed",
                ),
            )
            winner.commit()
            assert future.result(timeout=8) == 404
        finally:
            winner.rollback()
    with Session(engine) as session:
        assert not session.get(IpDocketRecord, record["docket_id"]).is_active
        assert session.scalar(select(func.count()).select_from(IpPatentPartyDetail)) == 0
        assert session.scalar(select(func.count()).select_from(IpPartyAndRole)) == 0


def _alembic():
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", os.environ["CASEOPS_TEST_POSTGRES_URL"])
    return config


def test_patent_party_migration_recovers_interrupted_owner_index_without_changing_parties(
    isolated_postgres_client,
):
    from alembic import command

    bootstrap, headers, _, record, base, raw = journeys._fixture(isolated_postgres_client)
    engine = get_session_factory().kw["bind"]
    config = _alembic()
    command.downgrade(config, "20260906_0002")
    admin = create_engine(engine.url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    name = f"party-index-{uuid4().hex[:12]}"
    original_id = str(uuid4())

    def index_builder():
        with admin.connect() as connection:
            connection.execute(
                text("SELECT set_config('application_name', :name, false)"), {"name": name}
            )
            try:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX CONCURRENTLY uq_ip_party_owner "
                    "ON ip_parties_and_roles (id, company_id, docket_id)"
                )
            except DBAPIError as exc:
                return getattr(exc.orig, "sqlstate", None)
            raise AssertionError("The deliberately interrupted index unexpectedly completed")

    with Session(engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.add(
            IpPartyAndRole(
                id=original_id,
                company_id=bootstrap["company"]["id"],
                docket_id=record["docket_id"],
                party_name="Preserved existing party",
                role_kind="applicant",
                effective_from=datetime.now(UTC).date(),
                source="pre-patent-fixture",
            )
        )
        writer.flush()
        future = pool.submit(index_builder)
        try:
            deadline = monotonic() + 8
            with admin.connect() as control:
                while monotonic() < deadline:
                    pending = control.scalar(
                        text(
                            "SELECT NOT indisvalid FROM pg_index "
                            "WHERE indexrelid = to_regclass('uq_ip_party_owner')"
                        )
                    )
                    if pending:
                        break
                    Event().wait(0.02)
                assert pending, (
                    "Concurrent index did not leave its expected in-progress catalogue row"
                )
                assert control.scalar(
                    text(
                        "SELECT pg_cancel_backend(pid) FROM pg_stat_activity "
                        "WHERE application_name=:name"
                    ),
                    {"name": name},
                )
            assert future.result(timeout=8) == "57014"
            writer.commit()
        finally:
            writer.rollback()
            admin.dispose()
    for _ in range(2):
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT indisvalid AND indisready FROM pg_index "
                    "WHERE indexrelid='uq_ip_party_owner'::regclass"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT party_name FROM ip_parties_and_roles WHERE id=:id"),
                    {"id": original_id},
                )
                == "Preserved existing party"
            )
    created = journeys._post(isolated_postgres_client, base, headers, raw)
    assert created.status_code == 201, created.text
    with pytest.raises(RuntimeError, match="Patent party evidence exists"):
        command.downgrade(config, "20260906_0002")
    command.upgrade(config, "head")
    assert (
        isolated_postgres_client.get(f"{base}/{created.json()['id']}", headers=headers).json()
        == created.json()
    )
    with Session(engine) as session:
        original = session.get(IpPartyAndRole, original_id)
        original.party_name = "Existing trademark-style mutable party"
        session.commit()
        assert (
            session.get(IpPartyAndRole, original_id).party_name
            == "Existing trademark-style mutable party"
        )


def test_patent_party_composite_integrity_and_10000_fact_page_bound(isolated_postgres_client):
    bootstrap, headers, _, record, base, raw = journeys._fixture(isolated_postgres_client)
    response = journeys._post(isolated_postgres_client, base, headers, raw)
    assert response.status_code == 201, response.text
    engine = get_session_factory().kw["bind"]
    with Session(engine) as session:
        party = session.get(IpPartyAndRole, response.json()["id"])
        detail = session.get(IpPatentPartyDetail, party.id)
        for changes in (
            {"company_id": str(uuid4())},
            {"docket_id": str(uuid4())},
            {"source_document_id": str(uuid4())},
            {"supersedes_party_id": str(uuid4())},
        ):
            new_id = str(uuid4())
            session.execute(insert(IpPartyAndRole.__table__).values(_clone(party, id=new_id)))
            with pytest.raises(IntegrityError), session.begin_nested():
                session.execute(
                    insert(IpPatentPartyDetail.__table__).values(
                        _clone(detail, id=new_id, sequence=2, **changes)
                    )
                )
            session.rollback()
        for batch in range(20):
            parties, details = [], []
            for offset in range(500):
                sequence = batch * 500 + offset + 2
                new_id, name = str(uuid4()), f"Scale inventor {sequence}"
                parties.append(_clone(party, id=new_id, party_name=name))
                details.append(
                    _clone(
                        detail,
                        id=new_id,
                        sequence=sequence,
                        fact_sha256=canonical_json_sha256(
                            {**response.json()["fact"], "name": name}
                        ),
                    )
                )
            session.execute(insert(IpPartyAndRole.__table__), parties)
            session.execute(insert(IpPatentPartyDetail.__table__), details)
            session.commit()
        session.execute(text("ANALYZE ip_patent_party_details"))
        session.execute(text("ANALYZE ip_parties_and_roles"))
        context = _context(session, bootstrap)
        session.execute(text("SET LOCAL statement_timeout = '3s'"))
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            page = list_patent_parties(
                session, context=context, docket_id=record["docket_id"], limit=100
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) <= 30
        assert page.collection_sequence == 10001 and len(page.parties) == 100
        assert page.next_cursor is not None
        assert [party.sequence for party in page.parties] == list(range(10001, 9901, -1))
