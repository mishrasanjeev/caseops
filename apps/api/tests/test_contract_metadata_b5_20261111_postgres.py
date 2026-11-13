"""Real PostgreSQL HTTP parity and deterministic Matter-before-Contract races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from time import monotonic, perf_counter, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from caseops_api.db.models import AuditEvent, Company, CompanyMembership, Contract, Matter, User
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.contracts import (
    ContractMetadataUpdateRequest,
    ContractTermSuggestionCreateRequest,
    ContractUpdateRequest,
)
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services.contracts import (
    create_contract_term_suggestion,
    review_contract_term_suggestion,
    update_contract,
    update_contract_metadata,
)
from caseops_api.services.matters import transition_matter_lifecycle_status
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_contract_metadata_b5_20261111 import (
    test_full_metadata_edit_retains_values_audit_and_rejects_stale_save as _http_metadata_matrix,
)
from tests.test_contract_transport_boundary_20261012_postgres import (
    _seed,
)
from tests.test_contract_transport_boundary_20261012_postgres import (
    contract_database as _contract_database,
)
from tests.test_legalworkspace_contract_metadata import _create_contract, _upload_attachment

pytestmark = pytest.mark.postgres
contract_database = _contract_database


def _is_lock(statement):
    return "FOR UPDATE" in statement or "FOR NO KEY UPDATE" in statement


def _context(session, state):
    return SessionContext(
        company=session.get(Company, state.company),
        user=session.get(User, state.user),
        membership=session.get(CompanyMembership, state.membership),
    )


def _additional_actor(factory, state):
    with factory() as session:
        user = User(
            email=f"contract-{uuid4().hex}@example.com",
            full_name="Second contract actor",
            password_hash="offline-unused-password",
        )
        session.add(user)
        session.flush()
        member = CompanyMembership(company_id=state.company, user_id=user.id, role="owner")
        session.add(member)
        session.commit()
        return SimpleNamespace(
            company=state.company, user=user.id, membership=member.id, contract=state.contract
        )


def _wait_for_pg_lock(engine, pid):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with engine.connect() as probe:
            if probe.scalar(
                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid=:pid"),
                {"pid": pid},
            ):
                return
        sleep(0.02)
    raise AssertionError("The actor did not reach a native PostgreSQL lock wait")


def _term(factory, state):
    with factory() as session:
        return create_contract_term_suggestion(
            session,
            context=_context(session, state),
            contract_id=state.contract,
            payload=ContractTermSuggestionCreateRequest(
                source_attachment_id=state.attachment,
                suggested_renewal_on="2027-11-01",
                evidence_json={"quote": "Synthetic fixture renewal on 1 November 2027"},
            ),
        ).id


def _mutate(session, state, workflow, version, suggestion_id):
    context = _context(session, state)
    if workflow == "edit":
        return update_contract_metadata(
            session,
            context=context,
            contract_id=state.contract,
            payload=ContractMetadataUpdateRequest(
                title="Concurrent reviewed correction", expected_updated_at=version
            ),
        )
    return review_contract_term_suggestion(
        session,
        context=context,
        contract_id=state.contract,
        suggestion_id=suggestion_id,
        accepted=True,
        expected_updated_at=version,
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
    first_locked, release_first, second_actor = Event(), Event(), Event()
    seen = {"first": [], "second": []}
    pids = {}

    def before(connection, cursor, statement, parameters, context, many):
        role = getattr(roles, "name", None)
        if role and _is_lock(statement):
            kind = (
                "membership"
                if "FROM company_memberships" in statement
                else "user"
                if "FROM users" in statement
                else "matter"
                if "FROM matters" in statement
                else "contract"
                if "FROM contracts" in statement
                else "other"
            )
            seen[role].append(kind)
            if role == "second" and kind == "membership":
                second_actor.set()

    def after(connection, cursor, statement, parameters, context, many):
        if (
            getattr(roles, "name", None) == "first"
            and "FROM contracts" in statement
            and _is_lock(statement)
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
                assert second_actor.wait(10)
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
    assert seen["first"][:4] == ["membership", "user", "matter", "contract"]
    assert seen["second"][:4] == ["membership", "user", "matter", "contract"]
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
    replacement_actor = _additional_actor(factory, state)
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
                        context=_context(session, replacement_actor),
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


@pytest.mark.parametrize("workflow", ["edit", "term"])
@pytest.mark.parametrize("first_role", ["mutation", "disposal"])
def test_postgres_real_disposal_and_contract_mutation_share_actor_before_parent_order(
    contract_database,
    workflow,
    first_role,
):
    engine = contract_database.engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    state, parent_id, version = _linked_fixture(factory)
    suggestion_id = _term(factory, state) if workflow == "term" else None
    with factory() as session:
        parent = session.get(Matter, parent_id)
        lifecycle = MatterLifecycleStatusRequest(
            to_status="disposed",
            expected_from_status="active",
            expected_updated_at=parent.updated_at,
            reason="Synthetic engagement concluded",
        )
    role = local()
    held, contender, resume = Event(), Event(), Event()
    pids = {}

    def before(connection, cursor, statement, parameters, context, many):
        current = getattr(role, "name", None)
        if (
            current
            and current != first_role
            and "FOR UPDATE" in statement
            and ("FROM company_memberships" in statement or "FROM matters" in statement)
        ):
            contender.set()

    def after(connection, cursor, statement, parameters, context, many):
        current = getattr(role, "name", None)
        gate = "FROM matters" if first_role == "mutation" else "FROM company_memberships"
        if (
            current == first_role
            and gate in statement
            and "FOR UPDATE" in statement
            and not held.is_set()
        ):
            held.set()
            assert resume.wait(10), "ordered mutation barrier exceeded"

    def run(name):
        role.name = name
        with factory() as session:
            pids[name] = session.scalar(text("SELECT pg_backend_pid()"))
            if name == "mutation":
                return _mutate(session, state, workflow, version, suggestion_id)
            return transition_matter_lifecycle_status(
                session, context=_context(session, state), matter_id=parent_id, payload=lifecycle
            )

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, first_role)
            try:
                assert held.wait(10)
                other_role = "disposal" if first_role == "mutation" else "mutation"
                second = pool.submit(run, other_role)
                assert contender.wait(10)
                _wait_for_pg_lock(engine, pids[other_role])
            finally:
                resume.set()
            first.result(timeout=15)
            second.result(timeout=15)
    finally:
        resume.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    with factory() as session:
        parent = session.get(Matter, parent_id)
        contract = session.get(Contract, state.contract)
        assert parent.status == "disposed" and parent.is_active is False
        assert contract.linked_matter_id == parent_id
        if workflow == "edit":
            assert contract.title == "Concurrent reviewed correction"
        else:
            assert contract.renewal_on.isoformat() == "2027-11-01"
        assert (
            session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.matter_id == parent_id,
                    AuditEvent.action == "matter.lifecycle.disposed",
                )
            )
            is not None
        )


@pytest.mark.parametrize("workflow", ["edit", "term"])
def test_postgres_capability_revocation_wins_before_contract_actor_fence(
    contract_database, workflow
):
    engine = contract_database.engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    state, _, version = _linked_fixture(factory)
    with factory() as setup:
        setup.get(CompanyMembership, state.membership).role = "member"
        setup.commit()
    suggestion_id = _term(factory, state) if workflow == "term" else None
    reached = Event()
    pid = {}

    def before(connection, cursor, statement, parameters, context, many):
        if "FROM company_memberships" in statement and "FOR UPDATE" in statement:
            pid["value"] = connection.connection.driver_connection.info.backend_pid
            reached.set()

    with factory() as revoker:
        member = revoker.scalar(
            select(CompanyMembership)
            .where(
                CompanyMembership.id == state.membership,
            )
            .with_for_update()
        )
        member.role = "viewer"
        revoker.flush()
        event.listen(engine, "before_cursor_execute", before)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:

                def denied():
                    with factory() as session:
                        with pytest.raises(HTTPException) as error:
                            _mutate(session, state, workflow, version, suggestion_id)
                        return error.value.status_code

                pending = pool.submit(denied)
                try:
                    assert reached.wait(10)
                    _wait_for_pg_lock(engine, pid["value"])
                finally:
                    revoker.commit()
                assert pending.result(timeout=10) == 403
        finally:
            event.remove(engine, "before_cursor_execute", before)
    with factory() as session:
        contract = session.get(Contract, state.contract)
        assert contract.title == "Offline source contract" and contract.renewal_on is None
        assert (
            session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.target_id == state.contract,
                    AuditEvent.action == "contract.metadata.updated",
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "workflow",
    ["metadata", "generic", "term_accept", "term_reject", "term_create", "preview", "download"],
)
def test_postgres_blocked_contract_http_writer_does_not_block_unrelated_http(
    isolated_postgres_client,
    workflow,
):
    client = isolated_postgres_client
    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    headers = auth_headers(token)
    contract = _create_contract(client, token)
    root = f"/api/contracts/{contract['id']}"
    if workflow in {"metadata", "generic"}:
        url, method = root + ("/metadata" if workflow == "metadata" else ""), "patch"
        payload = {
            "title": "Responsive contract writer",
            "expected_updated_at": contract["updated_at"],
        }
    elif workflow in {"preview", "download"}:
        from io import BytesIO

        from docx import Document

        document, buffer = Document(), BytesIO()
        document.add_paragraph("Synthetic source for HTTP responsiveness")
        document.save(buffer)
        uploaded = client.post(
            root + "/attachments",
            headers=headers,
            files={
                "file": (
                    "responsive.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        url, method, payload = (
            root + f"/attachments/{uploaded.json()['id']}/{workflow}",
            "get",
            None,
        )
    else:
        source = _upload_attachment(client, token, contract["id"])
        payload = {
            "source_attachment_id": source["id"],
            "suggested_renewal_on": "2027-11-01",
            "evidence_json": {"quote": "Synthetic source fixture"},
        }
        url, method = root + "/term-suggestions", "post"
        if workflow != "term_create":
            suggestion = client.post(url, headers=headers, json=payload)
            assert suggestion.status_code == 200, suggestion.text
            url += f"/{suggestion.json()['id']}/" + (
                "accept" if workflow == "term_accept" else "reject"
            )
            payload = (
                {"expected_updated_at": contract["updated_at"]} if workflow == "term_accept" else {}
            )
    factory = get_session_factory()
    engine = factory.kw["bind"]
    reached, pid = Event(), {}

    def before(connection, cursor, statement, parameters, context, many):
        if "FROM company_memberships" in statement and "FOR UPDATE" in statement:
            pid["value"] = connection.connection.driver_connection.info.backend_pid
            reached.set()

    with factory() as blocker:
        blocker.scalar(
            select(CompanyMembership)
            .where(
                CompanyMembership.id == auth["membership"]["id"],
            )
            .with_for_update()
        )
        event.listen(engine, "before_cursor_execute", before)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                writing = pool.submit(
                    client.request, method.upper(), url, headers=headers, json=payload
                )
                try:
                    assert reached.wait(10)
                    _wait_for_pg_lock(engine, pid["value"])
                    started = perf_counter()
                    healthy = pool.submit(client.get, "/api/build")
                    response = healthy.result(timeout=2)
                    assert response.status_code == 200
                    assert perf_counter() - started < 2
                finally:
                    blocker.rollback()
                assert writing.result(timeout=10).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", before)
