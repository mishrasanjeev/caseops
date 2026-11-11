"""Real PostgreSQL HTTP parity and deterministic Matter-before-Contract races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from caseops_api.db.models import AuditEvent, Company, CompanyMembership, Contract, Matter, User
from caseops_api.schemas.contracts import ContractMetadataUpdateRequest, ContractUpdateRequest
from caseops_api.services.contracts import update_contract, update_contract_metadata
from caseops_api.services.session_context import SessionContext
from tests.test_contract_metadata_b5_20261111 import (
    test_full_metadata_edit_retains_values_audit_and_rejects_stale_save as _http_metadata_matrix,
)
from tests.test_contract_transport_boundary_20261012_postgres import (
    _seed,
)
from tests.test_contract_transport_boundary_20261012_postgres import (
    contract_database as _contract_database,
)

pytestmark = pytest.mark.postgres
contract_database = _contract_database


def _context(session, state):
    return SessionContext(
        company=session.get(Company, state.company),
        user=session.get(User, state.user),
        membership=session.get(CompanyMembership, state.membership),
    )


def _linked_fixture(factory):
    state = _seed(factory)
    with factory() as session:
        parent = Matter(
            company_id=state.company,
            title="Synthetic linked parent",
            matter_code=uuid4().hex,
            practice_area="Commercial",
            forum_level="advisory",
            status="active",
            is_active=True,
        )
        session.add(parent)
        session.flush()
        contract = session.get(Contract, state.contract)
        contract.linked_matter_id = parent.id
        session.commit()
        return state, parent.id, contract.updated_at


@pytest.mark.parametrize("suffix", ["/metadata", ""])
def test_postgres_http_metadata_fields_audits_null_noop_and_stale(isolated_postgres_client, suffix):
    _http_metadata_matrix(isolated_postgres_client, suffix)


@pytest.mark.parametrize("generic", [False, True])
def test_postgres_same_version_writers_lock_parent_first_and_only_one_wins(
    contract_database, generic
):
    engine = contract_database.engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    state, parent_id, version = _linked_fixture(factory)
    roles = local()
    first_locked, release_first, second_parent = Event(), Event(), Event()
    seen = {"first": [], "second": []}
    pids = {}

    def before(connection, cursor, statement, parameters, context, many):
        role = getattr(roles, "name", None)
        if role and "FOR UPDATE" in statement:
            kind = (
                "matter"
                if "FROM matters" in statement
                else "contract"
                if "FROM contracts" in statement
                else "other"
            )
            seen[role].append(kind)
            if role == "second" and kind == "matter":
                second_parent.set()

    def after(connection, cursor, statement, parameters, context, many):
        if (
            getattr(roles, "name", None) == "first"
            and "FROM contracts" in statement
            and "FOR UPDATE" in statement
        ):
            first_locked.set()
            assert release_first.wait(10), "first writer barrier exceeded"

    def write(role):
        roles.name = role
        with factory() as session:
            pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
            context = _context(session, state)
            values = {"title": f"Synthetic {role} writer", "expected_updated_at": version}
            try:
                function, schema = (
                    (update_contract, ContractUpdateRequest)
                    if generic
                    else (update_contract_metadata, ContractMetadataUpdateRequest)
                )
                record = function(
                    session, context=context, contract_id=state.contract, payload=schema(**values)
                )
                return 200, record.title
            except HTTPException as exc:
                return exc.status_code, exc.detail

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(write, "first")
            assert first_locked.wait(10)
            second = pool.submit(write, "second")
            try:
                assert second_parent.wait(10)
                deadline = monotonic() + 5
                waiting = False
                while monotonic() < deadline:
                    with engine.connect() as probe:
                        waiting = probe.scalar(
                            text(
                                "SELECT wait_event_type = 'Lock' FROM pg_stat_activity "
                                "WHERE pid=:pid"
                            ),
                            {"pid": pids["second"]},
                        )
                    if waiting:
                        break
                    sleep(0.02)
                assert waiting, "second writer did not reach a real PostgreSQL lock wait"
            finally:
                release_first.set()
            assert first.result(timeout=10) == (200, "Synthetic first writer")
            assert second.result(timeout=10)[0] == 409
    finally:
        release_first.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    assert seen["first"][:2] == ["matter", "contract"]
    assert seen["second"][:2] == ["matter", "contract"]
    with factory() as session:
        assert session.get(Contract, state.contract).title == "Synthetic first writer"
        assert session.get(Contract, state.contract).linked_matter_id == parent_id
        assert (
            len(
                list(
                    session.scalars(
                        select(AuditEvent.id).where(
                            AuditEvent.target_id == state.contract,
                            AuditEvent.action == "contract.metadata.updated",
                        )
                    )
                )
            )
            == 1
        )


def test_postgres_relink_between_discovery_and_parent_lock_rejects_old_parent_writer(
    contract_database,
):
    engine = contract_database.engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    state, _, version = _linked_fixture(factory)
    with factory() as session:
        new_parent = Matter(
            company_id=state.company,
            title="Synthetic replacement parent",
            matter_code=uuid4().hex,
            practice_area="Commercial",
            forum_level="advisory",
            status="active",
            is_active=True,
        )
        session.add(new_parent)
        session.commit()
        new_parent_id = new_parent.id
    roles = local()
    discovered, resume = Event(), Event()

    def after(connection, cursor, statement, parameters, context, many):
        if getattr(roles, "stale", False) and statement.startswith(
            "SELECT contracts.linked_matter_id"
        ):
            discovered.set()
            assert resume.wait(10)

    def stale_edit():
        roles.stale = True
        with factory() as session:
            with pytest.raises(HTTPException) as error:
                update_contract_metadata(
                    session,
                    context=_context(session, state),
                    contract_id=state.contract,
                    payload=ContractMetadataUpdateRequest(
                        title="Rejected stale-parent correction", expected_updated_at=version
                    ),
                )
            assert error.value.status_code == 409
            assert "linked matter changed" in error.value.detail

    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            stale = pool.submit(stale_edit)
            try:
                assert discovered.wait(10)
                with factory() as session:
                    update_contract(
                        session,
                        context=_context(session, state),
                        contract_id=state.contract,
                        payload=ContractUpdateRequest(linked_matter_id=new_parent_id),
                    )
            finally:
                resume.set()
            stale.result(timeout=10)
    finally:
        resume.set()
        event.remove(engine, "after_cursor_execute", after)
    with factory() as session:
        current = session.get(Contract, state.contract)
        assert current.linked_matter_id == new_parent_id
        assert current.title == "Offline source contract"
