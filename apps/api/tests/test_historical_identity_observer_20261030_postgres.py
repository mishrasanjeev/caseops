"""Test-only historical observer: inspect all arms without widening entity reads."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, event, inspect, literal, select, text, union_all
from sqlalchemy.exc import DBAPIError, InvalidRequestError, ProgrammingError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.selectable import CompoundSelect

from caseops_api.db.models import CompanyMembership, DocumentProcessingJob, User
from caseops_api.services import compliance_participants
from tests import test_document_execution_protocol_20261010_postgres as historical_protocol
from tests.test_document_execution_protocol_20261010_postgres import (
    _historical_select_descriptions,
)
from tests.test_matter_writer_admission_postgres import _fixture
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres
protocol_database = historical_protocol.protocol_database


def test_historical_descriptions_keep_grouped_nested_and_repeated_leaves():
    user = select(User.id)
    member = select(CompanyMembership.id)
    statement = union_all(user, union_all(member, user).self_group()).self_group()
    descriptions = _historical_select_descriptions(statement)
    assert len(descriptions) == 3
    for description, expression in zip(
        descriptions, (User.id, CompanyMembership.id, User.id), strict=True
    ):
        assert description["expr"] is expression
    assert descriptions[0]["entity"] is descriptions[2]["entity"] is User
    assert descriptions[1]["entity"] is CompanyMembership


@pytest.mark.parametrize("shape", ["text", "textual_select", "compound", "grouped_compound"])
def test_historical_descriptions_reject_unsupported_even_after_valid_leaf(shape):
    opaque = text("SELECT 1 AS id").columns(id=Integer)
    statement = {
        "text": text("SELECT 1"),
        "textual_select": opaque,
        "compound": union_all(select(literal(1)), opaque),
        "grouped_compound": union_all(select(literal(1)), opaque).self_group(),
    }[shape]
    with pytest.raises(AssertionError, match="Unsupported historical identity SELECT"):
        _historical_select_descriptions(statement)


def test_historical_descriptions_reject_empty_compound():
    with pytest.raises(AssertionError, match="Empty historical identity compound SELECT"):
        _historical_select_descriptions(union_all())


def test_historical_recipient_union_keeps_raw_overlap_and_does_not_load_entities(protocol_database):
    engine = protocol_database.engine
    fixture = _fixture(engine, active=False)
    with Session(engine) as session:
        admins = tuple(tuple(row) for row in session.execute(
            select(CompanyMembership.id, CompanyMembership.role, CompanyMembership.is_active)
            .where(
                CompanyMembership.company_id == fixture.company,
                CompanyMembership.role.in_(["owner", "admin"]),
            )
        ))
        actor = next(row for row in admins if row[0] == fixture.actor)
        assert actor[2] is True
        reads, native = [], []
        before_map = dict(session.identity_map)

        def observed(state):
            assert state.is_select
            frozen = state.invoke_statement().freeze()
            reads.append((state.statement, tuple(tuple(row) for row in frozen().all())))
            return frozen()

        def sql(_connection, _cursor, statement, _parameters, context, _many):
            native.append((statement, context.compiled.statement))

        def loaded(_session, target):
            pytest.fail(f"Scalar recipient UNION loaded {type(target).__name__}")

        event.listen(session, "do_orm_execute", observed, retval=True)
        event.listen(session, "loaded_as_persistent", loaded)
        event.listen(engine, "before_cursor_execute", sql)
        try:
            review, failure = compliance_participants._select_recipient_ids(
                session,
                matter=SimpleNamespace(
                    company_id=fixture.company, assignee_membership_id=fixture.actor, team_id=None
                ),
            )
        finally:
            event.remove(engine, "before_cursor_execute", sql)
            event.remove(session, "loaded_as_persistent", loaded)
            event.remove(session, "do_orm_execute", observed)
        assert review == (fixture.actor,)
        assert failure == tuple(sorted(row[0] for row in admins if row[2]))
        assert len(reads) == len(native) == 1
        statement, rows = reads[0]
        assert isinstance(statement, CompoundSelect)
        assert native[0][1] is statement
        assert len(statement.selects) == 2
        assert len(_historical_select_descriptions(statement)) == 6
        assert sorted(rows) == sorted((*admins, actor))
        assert rows.count(actor) == 2
        assert len(rows) == len(admins) + 1
        assert dict(session.identity_map) == before_map


@pytest.mark.parametrize("root", ["user", "membership", "requester"])
@pytest.mark.parametrize("position", ["first", "last_grouped"])
def test_historical_entity_compound_rejects_before_sql(protocol_database, root, position):
    engine = protocol_database.engine
    model = {
        "user": User, "membership": CompanyMembership, "requester": DocumentProcessingJob
    }[root]
    entity = select(model)
    scalar = select(*model.__table__.columns)
    statement = (
        union_all(entity, scalar)
        if position == "first"
        else union_all(scalar, entity.limit(1))
    )
    native = []

    def sql(_connection, _cursor, statement, _parameters, _context, _many):
        native.append(statement)

    event.listen(engine, "before_cursor_execute", sql)
    try:
        with Session(engine) as session:
            with pytest.raises(AssertionError, match="entity loading requires a plain Select"):
                session.execute(statement)
            assert not session.identity_map
    finally:
        event.remove(engine, "before_cursor_execute", sql)
    assert native == []


@pytest.mark.parametrize("root", ["user", "membership", "requester"])
def test_historical_plain_entity_load_retains_defer_raiseload_and_parent_lock(
    protocol_database, root,
):
    engine = protocol_database.engine
    fixture = _fixture(engine, active=False)
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "sessions_valid_after" not in columns
    with Session(engine) as session:
        user_id = session.scalar(select(CompanyMembership.user_id).where(
            CompanyMembership.id == fixture.actor,
        ))
    model, identity = {
        "user": (User, user_id),
        "membership": (CompanyMembership, fixture.actor),
        "requester": (DocumentProcessingJob, fixture.job),
    }[root]
    statement = select(model).where(model.id == identity).with_for_update(of=model)
    if root == "membership":
        statement = statement.options(joinedload(CompanyMembership.user))
    elif root == "requester":
        statement = statement.options(
            joinedload(DocumentProcessingJob.requested_by_membership)
            .joinedload(CompanyMembership.user)
        )
    native = []

    def sql(_connection, _cursor, statement, _parameters, _context, _many):
        native.append(statement)

    event.listen(engine, "before_cursor_execute", sql)
    try:
        with Session(engine) as session:
            row = session.scalar(statement)
            assert row is not None and row.id == identity
            user = (
                row if root == "user"
                else row.user if root == "membership"
                else row.requested_by_membership.user
            )
            assert user.id == user_id and user.full_name
            assert columns <= set(inspect(user).dict)
            assert "sessions_valid_after" in inspect(user).unloaded
            assert "sessions_valid_after" not in inspect(user).dict
            assert len(native) == 1
            assert f"FOR UPDATE OF {model.__tablename__}" in native[0]
            with pytest.raises(InvalidRequestError, match="sessions_valid_after.*raiseload"):
                _ = user.sessions_valid_after
            assert len(native) == 1
            with Session(engine) as contender:
                with pytest.raises(DBAPIError) as blocked:
                    contender.scalar(select(model.id).where(model.id == identity).with_for_update(
                        of=model, nowait=True,
                    ))
                assert blocked.value.orig.sqlstate == "55P03"
    finally:
        event.remove(engine, "before_cursor_execute", sql)


@pytest.mark.parametrize("shape", ["plain", "compound"])
def test_historical_explicit_new_scalar_read_still_reaches_missing_column_rejection(
    protocol_database, shape,
):
    statement = select(User.sessions_valid_after)
    if shape == "compound":
        statement = union_all(statement, statement)
    with Session(protocol_database.engine) as session:
        with pytest.raises(ProgrammingError) as missing:
            session.execute(statement)
        assert missing.value.orig.sqlstate == "42703"
        assert "sessions_valid_after" in str(missing.value.orig)
