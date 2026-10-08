"""Real client/portal writers must enter Company before actor/source locks."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    AuditEvent,
    Client,
    CompanyMembership,
    Matter,
    MatterClientAssignment,
    MatterPortalGrant,
    MembershipRole,
    PortalUser,
    PrivateProjectionEvent,
    User,
)
from caseops_api.schemas.clients import (
    ClientCreateRequest,
    ClientUpdateRequest,
    ClientVerificationUpdateRequest,
    KycRejectRequest,
    KycSubmitRequest,
    MatterClientAssignRequest,
)
from caseops_api.schemas.employees import EmployeeOffboardingRequest
from caseops_api.schemas.ip_patents import PatentFamilyCorrectionRequest
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import clients, employees, ip_patent_families, matters, portal_matters
from caseops_api.services.identity import get_session_context
from caseops_api.services.private_retrieval import (
    ensure_active_private_generation,
    lock_private_authority_writer,
)
from tests.test_ip_patent_postgres import _seed
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres

WRITERS = (
    "create",
    "update",
    "archive",
    "unarchive",
    "submit",
    "verify",
    "reject",
    "matter-verify",
    "portal-kyc",
)


def _fixture(engine, writer, *, indexed=True):
    company_id, actor_id, family = _seed(engine)
    with Session(engine) as session:
        matter_id = _seed_matter(session, company_id)
        client = Client(
            company_id=company_id,
            name="Client fence fixture",
            client_type="individual",
            kyc_status="submitted"
            if writer in {"verify", "reject", "matter-verify"}
            else "not_required",
            is_active=writer != "unarchive",
            created_by_membership_id=actor_id,
        )
        portal = PortalUser(
            company_id=company_id,
            email=f"client-{uuid4()}@example.com",
            full_name="Client",
            role="client",
            invited_by_membership_id=actor_id,
        )
        session.add_all([client, portal])
        session.flush()
        grant = MatterPortalGrant(
            company_id=company_id,
            portal_user_id=portal.id,
            matter_id=matter_id,
            role="client",
            granted_by_membership_id=actor_id,
            granted_by_label_snapshot="Fixture inviter",
        )
        session.add_all([grant, MatterClientAssignment(matter_id=matter_id, client_id=client.id)])
        if indexed:
            ensure_active_private_generation(session, company_id=company_id)
        session.commit()
        return dict(
            company_id=company_id,
            actor_id=actor_id,
            family=family,
            matter_id=matter_id,
            client_id=client.id,
            portal_id=portal.id,
            grant_id=grant.id,
        )


def _write(session, fixture, writer, *, dirty_source=False, context=None):
    context = context or _ip_race_context(
        session,
        company_id=fixture["company_id"],
        membership_id=fixture["actor_id"],
    )
    portal = session.get(PortalUser, fixture["portal_id"]) if writer == "portal-kyc" else None
    if dirty_source:
        session.get(Client, fixture["client_id"]).internal_notes = "Pending before admission"
    kwargs = dict(context=context, client_id=fixture["client_id"])
    if writer == "create":
        return clients.create_client(
            session,
            context=context,
            payload=ClientCreateRequest(
                name="Created under tenant fence",
                client_type="individual",
            ),
        )
    if writer == "update":
        return clients.update_client(session, **kwargs, payload=ClientUpdateRequest(name="Updated"))
    if writer == "archive":
        return clients.archive_client(session, **kwargs)
    if writer == "unarchive":
        return clients.unarchive_client(session, **kwargs)
    if writer == "submit":
        return clients.submit_client_kyc(session, **kwargs, payload=KycSubmitRequest(documents=[]))
    if writer == "verify":
        return clients.verify_client_kyc(session, **kwargs)
    if writer == "reject":
        return clients.reject_client_kyc(
            session,
            **kwargs,
            payload=KycRejectRequest(
                reason="Unreadable identification",
            ),
        )
    if writer == "matter-verify":
        return clients.update_matter_client_verification(
            session,
            **kwargs,
            matter_id=fixture["matter_id"],
            payload=ClientVerificationUpdateRequest(status="verified"),
        )
    if writer == "assign":
        return clients.assign_client_to_matter(
            session, context=context, matter_id=fixture["matter_id"],
            payload=MatterClientAssignRequest(client_id=fixture["client_id"]),
        )
    if writer == "remove":
        return clients.remove_client_from_matter(
            session, **kwargs, matter_id=fixture["matter_id"],
        )
    assert writer == "portal-kyc"
    return portal_matters.submit_matter_kyc(
        session,
        portal_user=portal,
        matter_id=fixture["matter_id"],
        client_id=fixture["client_id"],
        documents=[],
    )


def _company_lock(statement):
    return "FROM companies" in statement and "FOR NO KEY UPDATE" in statement


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("first", ["writer", "offboarding"])
@pytest.mark.parametrize(
    "writer", ["portal-inviter", "portal-creator", "audit-only", "assign", "remove"]
)
def test_client_actor_fk_precedes_real_offboarding_parent(
    pg_engine,
    request,
    tmp_path,
    writer,
    first,
    autoflush,
):
    portal_writer = writer.startswith("portal-")
    fixture = _fixture(pg_engine, "portal-kyc", indexed=portal_writer)
    with Session(pg_engine) as seed:
        leaver = _seed_membership(seed, fixture["company_id"])
        owner = _seed_membership(seed, fixture["company_id"], role="owner")
        replacement = owner if portal_writer else fixture["actor_id"]
        seed.get(Matter, fixture["matter_id"]).assignee_membership_id = leaver
        portal = seed.get(PortalUser, fixture["portal_id"])
        portal.invited_by_membership_id = leaver if writer == "portal-inviter" else None
        seed.get(Client, fixture["client_id"]).created_by_membership_id = leaver
        if writer == "assign":
            assignment = seed.scalar(
                select(MatterClientAssignment).where(
                    MatterClientAssignment.matter_id == fixture["matter_id"],
                    MatterClientAssignment.client_id == fixture["client_id"],
                )
            )
            seed.delete(assignment)
        seed.commit()

    paused, resume, thread = Event(), Event(), local()
    sql, pids, errors, outcomes = {"writer": [], "offboarding": []}, {}, [], {}
    observer = create_engine(pg_engine.url, poolclass=NullPool)
    second = "offboarding" if first == "writer" else "writer"
    observed, cycle = None, None

    def before(conn, cursor, statement, parameters, context, many):
        role = getattr(thread, "role", None)
        if role in sql:
            sql[role].append(statement)

    def after(conn, cursor, statement, parameters, context, many):
        boundary = (
            "FROM matters" in statement and "FOR UPDATE" in statement
            if first == "writer"
            else "FROM users" in statement and "FOR UPDATE" in statement
        )
        if getattr(thread, "role", None) == first and boundary and not paused.is_set():
            paused.set()
            assert resume.wait(15), "First service boundary was not released"

    def run(role):
        with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            session.execute(text("SET statement_timeout = '12s'"))
            session.execute(text("SET deadlock_timeout = '1s'"))
            pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
            thread.role = role
            try:
                context = _ip_race_context(
                    session,
                    company_id=fixture["company_id"],
                    membership_id=owner if role == "offboarding" else fixture["actor_id"],
                )
                if role == "offboarding":
                    employees.commit_employee_offboarding(
                        session,
                        context=context,
                        membership_id=leaver,
                        payload=EmployeeOffboardingRequest(reassign_to_membership_id=replacement),
                    )
                else:
                    portal = session.get(PortalUser, fixture["portal_id"])
                    client = session.get(Client, fixture["client_id"])
                    client.internal_notes = "Pending before actor admission"
                    if portal_writer:
                        portal_matters.submit_matter_kyc(
                            session,
                            portal_user=portal,
                            matter_id=fixture["matter_id"],
                            client_id=fixture["client_id"],
                            documents=[],
                        )
                    elif writer == "audit-only":
                        clients.update_matter_client_verification(
                            session,
                            context=context,
                            matter_id=fixture["matter_id"],
                            client_id=fixture["client_id"],
                            payload=ClientVerificationUpdateRequest(documents=[]),
                        )
                    elif writer == "assign":
                        clients.assign_client_to_matter(
                            session,
                            context=context,
                            matter_id=fixture["matter_id"],
                            payload=MatterClientAssignRequest(client_id=fixture["client_id"]),
                        )
                    else:
                        clients.remove_client_from_matter(
                            session,
                            context=context,
                            matter_id=fixture["matter_id"],
                            client_id=fixture["client_id"],
                        )
                outcomes[role] = "committed"
            except Exception as exc:
                errors.append(
                    dict(
                        role=role,
                        type=type(exc).__name__,
                        message=str(exc),
                        sqlstate=getattr(getattr(exc, "orig", None), "sqlstate", None),
                    )
                )
                session.rollback()
            finally:
                thread.role = None

    def snapshot(connection):
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT pid, query, wait_event_type, pg_blocking_pids(pid) AS blockers "
                    "FROM pg_stat_activity WHERE pid IN (:writer, :offboarding)"
                ),
                {"writer": pids.get("writer", 0), "offboarding": pids.get("offboarding", 0)},
            ).mappings()
        ]

    event.listen(pg_engine, "before_cursor_execute", before)
    event.listen(pg_engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(run, first)
            try:
                assert paused.wait(10), errors
                b = pool.submit(run, second)
                with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as obs:
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        rows = snapshot(obs)
                        observed = next(
                            (
                                row
                                for row in rows
                                if row["pid"] == pids.get(second) and pids[first] in row["blockers"]
                            ),
                            None,
                        )
                        if observed:
                            break
                        sleep(0.01)
                    assert observed is not None, errors
                    resume.set()
                    deadline = monotonic() + 0.9
                    while monotonic() < deadline and not (a.done() and b.done()):
                        rows = snapshot(obs)
                        if len(rows) == 2 and all(row["blockers"] for row in rows):
                            cycle = rows
                            break
                        sleep(0.01)
            finally:
                resume.set()
            a.result(15)
            b.result(15)
    finally:
        resume.set()
        event.remove(pg_engine, "before_cursor_execute", before)
        event.remove(pg_engine, "after_cursor_execute", after)
        with observer.connect() as obs:
            pending = obs.execute(
                text(
                    "SELECT pid FROM pg_stat_activity WHERE pid IN (:writer, :offboarding) "
                    "AND xact_start IS NOT NULL"
                ),
                {"writer": pids.get("writer", 0), "offboarding": pids.get("offboarding", 0)},
            ).all()
        observer.dispose()
        directory = Path(os.environ.get("CASEOPS_CLIENT_ACTOR_EVIDENCE", str(tmp_path)))
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"offboarding-{request.node.callspec.id}.json").open(
            "x", encoding="utf-8"
        ) as output:
            json.dump(
                dict(
                    sql=sql,
                    observed=observed,
                    cycle=cycle,
                    errors=errors,
                    outcomes=outcomes,
                    pending=[list(row) for row in pending],
                ),
                output,
                indent=2,
            )

    assert not pending
    assert not errors, errors
    assert outcomes == {"writer": "committed", "offboarding": "committed"}
    assert "FROM company_memberships" in observed["query"], observed
    statements = sql["writer"]
    actor_index = next(
        i
        for i, statement in enumerate(statements)
        if "FROM company_memberships" in statement and "FOR KEY SHARE" in statement
    )
    assert not any(
        "FOR UPDATE" in statement or statement.startswith(("UPDATE", "INSERT", "DELETE"))
        for statement in statements[:actor_index]
    )
    assert any(
        "FROM matters" in statement and "FOR UPDATE" in statement
        for statement in sql["offboarding"]
    )
    assert not any(_company_lock(statement) for statement in sql["offboarding"])
    with Session(pg_engine) as verify:
        assert not verify.get(CompanyMembership, leaver).is_active
        assert not verify.get(CompanyMembership, leaver).user.is_active
        assert verify.get(CompanyMembership, fixture["actor_id"]).is_active
        assert verify.get(Matter, fixture["matter_id"]).assignee_membership_id == replacement
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture["company_id"],
                )
            )
        )
        if portal_writer:
            assert len(events) == 1 and events[0].actor_membership_id == leaver
            assert verify.get(Client, fixture["client_id"]).kyc_status == "submitted"
        else:
            assert not events
            assert (
                verify.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.company_id == fixture["company_id"],
                        AuditEvent.actor_membership_id == fixture["actor_id"],
                        AuditEvent.action
                        == {
                            "audit-only": "client.verification_updated",
                            "assign": "matter.client_assigned",
                            "remove": "matter.client_unassigned",
                        }[writer],
                    )
                )
                is not None
            )


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("first", ["ip", "client"])
@pytest.mark.parametrize("writer", WRITERS)
def test_client_private_writer_serializes_with_real_ip_writer(
    pg_engine,
    request,
    tmp_path,
    writer,
    first,
    autoflush,
):
    fixture = _fixture(pg_engine, writer)
    paused, resume = Event(), Event()
    thread = local()
    pids, sql, errors, outcomes = {}, {"ip": [], "client": []}, [], {}
    observer_engine = create_engine(pg_engine.url, poolclass=NullPool)
    second = "client" if first == "ip" else "ip"
    observed = None
    unlocked = {}

    def before(conn, cursor, statement, parameters, context, many):
        role = getattr(thread, "role", None)
        if role in sql:
            sql[role].append(statement)

    def after(conn, cursor, statement, parameters, context, many):
        if getattr(thread, "role", None) == first and _company_lock(statement):
            if not paused.is_set():
                paused.set()
                assert resume.wait(15), "Company owner was not released"

    def run(role):
        with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            session.execute(text("SET statement_timeout = '12s'"))
            pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
            thread.role = role
            try:
                if role == "client":
                    result = _write(session, fixture, writer)
                    outcomes[role] = "committed"
                    return result
                context = _ip_race_context(
                    session,
                    company_id=fixture["company_id"],
                    membership_id=fixture["actor_id"],
                )
                family = fixture["family"]
                result = ip_patent_families.correct_patent_family(
                    session,
                    context=context,
                    family_id=str(family.id),
                    payload=PatentFamilyCorrectionRequest(
                        expected_version=family.version,
                        expected_lifecycle_version=family.lifecycle_version,
                        reason="Concurrent client fence correction",
                        facts=family.facts.model_copy(update={"title": "Corrected under fence"}),
                    ),
                )
                outcomes[role] = "committed"
                return result
            except Exception as exc:
                errors.append(
                    dict(
                        role=role,
                        type=type(exc).__name__,
                        message=str(exc),
                        sqlstate=getattr(getattr(exc, "orig", None), "sqlstate", None),
                    )
                )
                session.rollback()
            finally:
                thread.role = None

    event.listen(pg_engine, "before_cursor_execute", before)
    event.listen(pg_engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(run, first)
            try:
                assert paused.wait(10), "First real writer did not reach Company"
                waiter = pool.submit(run, second)
                deadline = monotonic() + 5
                with observer_engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as obs:
                    while monotonic() < deadline:
                        if second in pids:
                            row = (
                                obs.execute(
                                    text(
                                        "SELECT pid, query, pg_blocking_pids(pid) AS blockers "
                                        "FROM pg_stat_activity WHERE pid = :pid"
                                    ),
                                    {"pid": pids[second]},
                                )
                                .mappings()
                                .one()
                            )
                            if pids[first] in row["blockers"] and _company_lock(row["query"]):
                                observed = dict(row)
                                break
                        sleep(0.01)
                assert observed is not None, "Second real writer never waited on first"
                if first == "ip":
                    for table, key in (
                        ("clients", "client_id"),
                        ("matters", "matter_id"),
                        ("company_memberships", "actor_id"),
                    ):
                        with observer_engine.connect() as probe:
                            try:
                                probe.execute(
                                    text(
                                        f"SELECT id FROM {table} WHERE id = :id FOR UPDATE NOWAIT"
                                    ),
                                    {"id": fixture[key]},
                                ).one()
                                unlocked[table] = True
                            except DBAPIError as exc:
                                assert exc.orig.sqlstate == "55P03"
                                unlocked[table] = False
                            finally:
                                probe.rollback()
            finally:
                resume.set()
            owner.result(timeout=15)
            waiter.result(timeout=15)
    finally:
        resume.set()
        event.remove(pg_engine, "before_cursor_execute", before)
        event.remove(pg_engine, "after_cursor_execute", after)
        with observer_engine.connect() as obs:
            pending = obs.execute(
                text(
                    "SELECT pid FROM pg_stat_activity WHERE pid IN (:ip, :client) "
                    "AND xact_start IS NOT NULL"
                ),
                {"ip": pids.get("ip", 0), "client": pids.get("client", 0)},
            ).all()
        observer_engine.dispose()
        evidence_dir = Path(os.environ.get("CASEOPS_CLIENT_ACTOR_EVIDENCE", str(tmp_path)))
        evidence_dir.mkdir(parents=True, exist_ok=True)
        with (evidence_dir / f"{request.node.callspec.id}.json").open(
            "x", encoding="utf-8"
        ) as output:
            json.dump(
                dict(
                    sql=sql,
                    observed=observed,
                    unlocked=unlocked,
                    errors=errors,
                    outcomes=outcomes,
                    pending=[list(row) for row in pending],
                ),
                output,
                indent=2,
            )

    assert not pending
    assert not errors, errors
    assert outcomes == {"ip": "committed", "client": "committed"}
    assert _company_lock(observed["query"]), observed
    assert all(unlocked.values()), unlocked
    client_sql = sql["client"]
    tenant_index = next(i for i, statement in enumerate(client_sql) if _company_lock(statement))
    assert not any(
        "FOR UPDATE" in statement or statement.startswith(("UPDATE", "INSERT", "DELETE"))
        for statement in client_sql[:tenant_index]
    ), client_sql[:tenant_index]
    with Session(pg_engine) as session:
        events = list(
            session.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture["company_id"],
                    PrivateProjectionEvent.target_type == "client",
                )
            )
        )
        assert len(events) == 1
        assert events[0].actor_membership_id == fixture["actor_id"]
        assert events[0].status == "applied"
        client = session.get(Client, fixture["client_id"])
        if writer in {"verify", "matter-verify"}:
            assert client.kyc_status == "verified"
        elif writer in {"submit", "portal-kyc"}:
            assert client.kyc_status == "submitted"
        elif writer == "reject":
            assert client.kyc_status == "rejected"
        elif writer in {"archive", "unarchive"}:
            assert client.is_active == (writer == "unarchive")
        elif writer == "update":
            assert client.name == "Updated"


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("autoflush", [False, True])
def test_client_writer_fence_precedes_pending_autoflush(pg_engine, writer, autoflush):
    fixture = _fixture(pg_engine, writer)
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(pg_engine, "before_cursor_execute", capture)
    try:
        with Session(pg_engine, autoflush=autoflush) as session:
            _write(session, fixture, writer, dirty_source=True)
    finally:
        event.remove(pg_engine, "before_cursor_execute", capture)
    first_write = next(
        i for i, sql in enumerate(statements) if sql.startswith(("UPDATE", "INSERT"))
    )
    first_fence = next(i for i, sql in enumerate(statements) if _company_lock(sql))
    assert first_fence < first_write
    with Session(pg_engine) as session:
        assert (
            session.get(Client, fixture["client_id"]).internal_notes == "Pending before admission"
        )


@pytest.mark.parametrize("writer", ["matter-verify", "portal-kyc"])
@pytest.mark.parametrize("autoflush", [False, True])
def test_disposal_wins_before_client_writer_admission(pg_engine, writer, autoflush):
    fixture = _fixture(pg_engine, writer)
    ready, resume = Event(), Event()
    thread = local()
    waiter_pid = []
    observer = create_engine(pg_engine.url, poolclass=NullPool)

    def after(conn, cursor, statement, parameters, context, many):
        if getattr(thread, "dispose", False) and _company_lock(statement) and not ready.is_set():
            ready.set()
            assert resume.wait(15)

    def dispose():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            context = _ip_race_context(
                session,
                company_id=fixture["company_id"],
                membership_id=fixture["actor_id"],
            )
            matter = session.get(Matter, fixture["matter_id"])
            payload = MatterLifecycleStatusRequest(
                to_status="disposed",
                expected_from_status="active",
                expected_updated_at=matter.updated_at,
                reason="Concurrent lifecycle disposal regression",
            )
            thread.dispose = True
            try:
                return matters.transition_matter_lifecycle_status(
                    session,
                    context=context,
                    matter_id=matter.id,
                    payload=payload,
                )
            finally:
                thread.dispose = False

    def write():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            waiter_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            with pytest.raises(HTTPException) as rejected:
                _write(session, fixture, writer)
            session.rollback()
            assert rejected.value.status_code == 409
            assert "disposed" in str(rejected.value.detail)

    event.listen(pg_engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            disposal = pool.submit(dispose)
            try:
                if not ready.wait(10):
                    disposal.result(timeout=1)
                    pytest.fail("Disposal did not reach the Company fence")
                mutation = pool.submit(write)
                deadline = monotonic() + 5
                observed = False
                with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as obs:
                    while monotonic() < deadline:
                        if waiter_pid:
                            row = (
                                obs.execute(
                                    text(
                                        "SELECT query, pg_blocking_pids(pid) AS blockers "
                                        "FROM pg_stat_activity WHERE pid=:pid"
                                    ),
                                    {"pid": waiter_pid[0]},
                                )
                                .mappings()
                                .one()
                            )
                            if row["blockers"] and _company_lock(row["query"]):
                                observed = True
                                break
                        sleep(0.01)
                assert observed
            finally:
                resume.set()
            assert disposal.result(timeout=15).status == "disposed"
            mutation.result(timeout=15)
    finally:
        resume.set()
        event.remove(pg_engine, "after_cursor_execute", after)
        observer.dispose()
    with Session(pg_engine) as session:
        matter = session.get(Matter, fixture["matter_id"])
        assert matter.status == "disposed" and matter.is_active is False
        assert matter.lifecycle_version == 1
        assert session.get(Client, fixture["client_id"]).kyc_status == (
            "submitted" if writer == "matter-verify" else "not_required"
        )
        assert not session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
                PrivateProjectionEvent.target_type == "client",
            )
        ).all()


@pytest.mark.parametrize("writer", WRITERS[1:])
def test_client_writer_rejects_foreign_client(pg_engine, writer):
    fixture = _fixture(pg_engine, writer)
    foreign = _fixture(pg_engine, writer)
    fixture["client_id"] = foreign["client_id"]
    with Session(pg_engine) as session:
        original = clients._client_record(session.get(Client, foreign["client_id"]))
        with pytest.raises(HTTPException) as rejected:
            _write(session, fixture, writer)
        assert rejected.value.status_code == 404
        session.rollback()
        assert clients._client_record(session.get(Client, foreign["client_id"])) == original
        assert not session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
            )
        ).all()


@pytest.mark.parametrize(
    "writer, fence",
    [
        ("matter-verify", "company"),
        ("portal-kyc", "company"),
        ("portal-kyc", "actor"),
    ],
)
@pytest.mark.parametrize("autoflush", [False, True])
def test_client_access_revoked_while_waiting_for_admission(pg_engine, writer, fence, autoflush):
    fixture = _fixture(pg_engine, writer)
    pid = []
    loaded = Event()
    observer = create_engine(pg_engine.url, poolclass=NullPool)

    def write():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            # Keep stale access-related objects in the identity map across admission.
            retained = [
                session.get(Matter, fixture["matter_id"]),
                session.get(MatterPortalGrant, fixture["grant_id"]),
            ]
            pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            loaded.set()
            with pytest.raises(HTTPException) as rejected:
                _write(session, fixture, writer)
            assert retained
            session.rollback()
            return rejected.value.status_code

    try:
        with Session(pg_engine) as revoker, ThreadPoolExecutor(max_workers=1) as pool:
            if fence == "company":
                lock_private_authority_writer(revoker, company_id=fixture["company_id"])
            else:
                revoker.scalar(
                    select(CompanyMembership.id)
                    .where(
                        CompanyMembership.id == fixture["actor_id"],
                    )
                    .with_for_update()
                )
            result = pool.submit(write)
            try:
                assert loaded.wait(5)
                deadline = monotonic() + 5
                observed = False
                with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as obs:
                    while monotonic() < deadline:
                        row = (
                            obs.execute(
                                text(
                                    "SELECT query, pg_blocking_pids(pid) AS blockers "
                                    "FROM pg_stat_activity WHERE pid=:pid"
                                ),
                                {"pid": pid[0]},
                            )
                            .mappings()
                            .one()
                        )
                        expected_wait = (
                            _company_lock(row["query"])
                            if fence == "company"
                            else "FROM company_memberships" in row["query"]
                            and "FOR KEY SHARE" in row["query"]
                        )
                        if row["blockers"] and expected_wait:
                            observed = True
                            break
                        sleep(0.01)
                assert observed
                if writer == "portal-kyc":
                    revoker.get(MatterPortalGrant, fixture["grant_id"]).revoked_at = datetime.now(
                        UTC
                    )
                else:
                    revoker.get(Matter, fixture["matter_id"]).restricted_access = True
                revoker.commit()
            finally:
                revoker.rollback()
            assert result.result(timeout=12) == 404
    finally:
        observer.dispose()
    with Session(pg_engine) as session:
        assert not session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
            )
        ).all()
        assert session.get(Client, fixture["client_id"]).kyc_status == (
            "submitted" if writer == "matter-verify" else "not_required"
        )


@pytest.mark.parametrize("provenance", ["inviter", "client-creator"])
def test_portal_kyc_keeps_inactive_historical_actor_not_portal_identity(pg_engine, provenance):
    fixture = _fixture(pg_engine, "portal-kyc")
    with Session(pg_engine) as session:
        actor = session.get(CompanyMembership, fixture["actor_id"])
        actor.is_active = False
        session.get(User, actor.user_id).is_active = False
        portal = session.get(PortalUser, fixture["portal_id"])
        if provenance != "inviter":
            portal.invited_by_membership_id = None
        session.commit()
    with Session(pg_engine) as session:
        _write(session, fixture, "portal-kyc")
    with Session(pg_engine) as session:
        row = session.scalars(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture["company_id"],
            )
        ).one()
        assert row.actor_membership_id == fixture["actor_id"]
        assert row.actor_membership_id != fixture["portal_id"]
        assert row.status == "applied"
        assert not session.get(CompanyMembership, fixture["actor_id"]).is_active


CURRENT_CLIENT_WRITERS = tuple(writer for writer in WRITERS if writer != "portal-kyc") + (
    "assign", "remove",
)
CURRENT_ACTOR_CASES = [(writer, "capability") for writer in CURRENT_CLIENT_WRITERS] + [
    (writer, revocation)
    for writer in ("update", "verify")
    for revocation in ("membership", "user", "session")
]


def _client_write_snapshot(session, fixture):
    client = session.get(Client, fixture["client_id"])
    return {
        "client": {
            column.name: getattr(client, column.name) for column in Client.__table__.columns
        },
        "clients": session.scalar(select(func.count()).select_from(Client).where(
            Client.company_id == fixture["company_id"],
        )),
        "assignments": session.scalar(
            select(func.count()).select_from(MatterClientAssignment).where(
                MatterClientAssignment.matter_id == fixture["matter_id"],
            )
        ),
        "events": session.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture["company_id"],
        )),
        "audits": session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.company_id == fixture["company_id"],
        )),
    }


@pytest.mark.parametrize("writer,revocation", CURRENT_ACTOR_CASES)
@pytest.mark.parametrize("fence", ["company", "actor"])
@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
def test_client_current_actor_revoked_during_admission(
    pg_engine, request, tmp_path, writer, revocation, fence, autoflush,
):
    fixture = _fixture(pg_engine, writer)
    with Session(pg_engine) as seed:
        before = _client_write_snapshot(seed, fixture)
    loaded, thread = Event(), local()
    pids, sql, observed, outcome = {}, [], None, None
    observer = create_engine(pg_engine.url, poolclass=NullPool)

    def capture(conn, cursor, statement, parameters, context, many):
        if getattr(thread, "writer", False):
            sql.append(statement)

    def write():
        with Session(pg_engine, autoflush=autoflush) as session:
            session.execute(text("SET lock_timeout = '8s'"))
            session.execute(text("SET statement_timeout = '12s'"))
            context = get_session_context(
                session, fixture["actor_id"],
                token_issued_at=(datetime.now(UTC) - timedelta(seconds=1)).timestamp(),
            )
            # Retain the authenticated objects and a pending source across the wait.
            session.get(Client, fixture["client_id"]).internal_notes = "Must not escape admission"
            pids["writer"] = session.scalar(text("SELECT pg_backend_pid()"))
            thread.writer = True
            loaded.set()
            try:
                _write(session, fixture, writer, context=context)
                return {"status": 200}
            except HTTPException as exc:
                return {"status": exc.status_code, "detail": exc.detail}
            finally:
                session.rollback()
                thread.writer = False

    event.listen(pg_engine, "before_cursor_execute", capture)
    try:
        with Session(pg_engine) as revoker, ThreadPoolExecutor(max_workers=1) as pool:
            pids["revoker"] = revoker.scalar(text("SELECT pg_backend_pid()"))
            if fence == "company":
                lock_private_authority_writer(revoker, company_id=fixture["company_id"])
            else:
                revoker.scalar(select(CompanyMembership.id).where(
                    CompanyMembership.id == fixture["actor_id"],
                ).with_for_update())
            future = pool.submit(write)
            try:
                assert loaded.wait(5)
                deadline = monotonic() + 5
                with observer.connect().execution_options(isolation_level="AUTOCOMMIT") as obs:
                    while monotonic() < deadline:
                        row = obs.execute(text(
                            "SELECT query, pg_blocking_pids(pid) AS blockers "
                            "FROM pg_stat_activity WHERE pid=:pid"
                        ), {"pid": pids["writer"]}).mappings().one()
                        expected = _company_lock(row["query"]) if fence == "company" else (
                            "FROM company_memberships" in row["query"]
                            and "FOR KEY SHARE" in row["query"]
                        )
                        if expected and pids["revoker"] in row["blockers"]:
                            observed = dict(row)
                            break
                        sleep(0.01)
                assert observed is not None, "Writer did not reach the real authority wait"
                actor = revoker.get(CompanyMembership, fixture["actor_id"])
                if revocation == "membership":
                    actor.is_active = False
                elif revocation == "user":
                    revoker.get(User, actor.user_id).is_active = False
                elif revocation == "capability":
                    actor.role = MembershipRole.VIEWER
                else:
                    actor.sessions_valid_after = datetime.now(UTC)
                revoker.commit()
            finally:
                revoker.rollback()
            outcome = future.result(timeout=15)
        with Session(pg_engine) as verify:
            after = _client_write_snapshot(verify, fixture)
        assert outcome["status"] == (401 if revocation == "session" else 403), outcome
        assert after == before
        assert not any(statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                       for statement in sql), sql
    finally:
        event.remove(pg_engine, "before_cursor_execute", capture)
        observer.dispose()
        directory = Path(os.environ.get("CASEOPS_CLIENT_ACTOR_EVIDENCE", str(tmp_path)))
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"current-actor-{request.node.callspec.id}.json").open(
            "x", encoding="utf-8",
        ) as stream:
            json.dump({"nodeid": request.node.nodeid, "pids": pids, "wait": observed,
                       "outcome": outcome, "sql": sql}, stream, indent=2)


@pytest.mark.parametrize("indexed", [False, True], ids=["default-off", "indexed"])
@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
def test_client_live_authority_preserves_inactive_historical_provenance(
    pg_engine, indexed, autoflush,
):
    fixture = _fixture(pg_engine, "update", indexed=indexed)
    with Session(pg_engine) as seed:
        historical = _seed_membership(seed, fixture["company_id"])
        actor = seed.get(CompanyMembership, historical)
        actor.is_active = False
        actor.user.is_active = False
        target = seed.get(Client, fixture["client_id"])
        target.created_by_membership_id = historical
        target.kyc_verified_by_membership_id = historical
        seed.commit()
    with Session(pg_engine, autoflush=autoflush) as session:
        context = get_session_context(
            session, fixture["actor_id"], token_issued_at=datetime.now(UTC).timestamp(),
        )
        _write(session, fixture, "update", context=context)
    with Session(pg_engine) as verify:
        target = verify.get(Client, fixture["client_id"])
        assert target.name == "Updated"
        assert target.created_by_membership_id == historical
        assert target.kyc_verified_by_membership_id == historical
        assert not verify.get(CompanyMembership, historical).is_active
        events = verify.scalars(select(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture["company_id"],
        )).all()
        assert bool(events) == indexed
        assert all(row.actor_membership_id == fixture["actor_id"] for row in events)
