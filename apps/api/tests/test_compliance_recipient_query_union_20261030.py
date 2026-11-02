"""Bounded recipient reads preserve the pinned original on both databases."""

from __future__ import annotations

import ast
import hashlib
import inspect as python_inspect
import json
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, insert, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CompoundSelect, Select

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    MembershipRole,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import clear_engine_cache, get_session_factory
from caseops_api.services import compliance_participants as owner
from caseops_api.services.compliance_participants import _MAX_PARTICIPANTS, _check_participant_bound

CAP_ERROR = ("error", 409, {"code": "compliance_participant_limit"})
LEGACY_SHA256 = "e6c6d2cacb9db3413da582e3707287a5bc012d8957df75bfb500f77c7a204325"


def _reference_selector(
    session: Session,
    *,
    matter: Matter,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ids: list[str] = []
    if matter.assignee_membership_id:
        ids.append(matter.assignee_membership_id)
    if matter.team_id:
        ids.extend(
            session.scalars(
                select(TeamMembership.membership_id)
                .where(TeamMembership.team_id == matter.team_id)
                .limit(_MAX_PARTICIPANTS + 1)
            )
        )
    assigned_ids = set(ids)
    _check_participant_bound(assigned_ids)
    admin_ids = set(
        session.scalars(
            select(CompanyMembership.id)
            .where(
                CompanyMembership.company_id == matter.company_id,
                CompanyMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
            )
            .limit(_MAX_PARTICIPANTS + 1)
        )
    )
    review_ids = assigned_ids or admin_ids
    failure_ids = assigned_ids | admin_ids
    _check_participant_bound(failure_ids)
    if not failure_ids:
        return (), ()
    active_ids = set(
        session.scalars(
            select(CompanyMembership.id).where(
                CompanyMembership.id.in_(sorted(failure_ids)),
                CompanyMembership.company_id == matter.company_id,
                CompanyMembership.is_active.is_(True),
            )
        )
    )
    return tuple(sorted(review_ids & active_ids)), tuple(sorted(failure_ids & active_ids))


@pytest.fixture
def recipient_selector():
    return owner._select_recipient_ids


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def recipient_sessions(request, tmp_path, monkeypatch):
    monkeypatch.setenv("CASEOPS_ENV", "local")
    if request.param == "postgres":
        engine = request.getfixturevalue("http_pg_engine")
        url = engine.url.render_as_string(hide_password=False)
    else:
        template = request.getfixturevalue("_migrated_template_db")
        database = tmp_path / "recipient-query.db"
        shutil.copyfile(template, database)
        url = f"sqlite+pysqlite:///{database.as_posix()}"
    factory = get_session_factory(url)
    try:
        yield factory
    finally:
        clear_engine_cache()


@pytest.fixture(scope="session")
def legacy_selector():
    record = json.loads(
        (Path(__file__).parent / "fixtures/recipient_selector_f0be_20261030.json").read_text(
            "utf-8"
        )
    )
    source = record["source"].encode("utf-8")
    assert len(source) == record["byte_length"] == 1533
    assert hashlib.sha256(source).hexdigest() == record["sha256"] == LEGACY_SHA256
    assert owner._MAX_PARTICIPANTS == 500
    pinned = ast.parse(source).body[0]
    reference = ast.parse(python_inspect.getsource(_reference_selector)).body[0]
    reference.name = pinned.name
    assert ast.dump(reference, include_attributes=False) == ast.dump(
        pinned, include_attributes=False
    )
    return _reference_selector


@dataclass
class Data:
    sessions: object
    company_id: str
    foreign_company_id: str

    def members(self, count, *, role="member", active=True, foreign=False, user_active=True):
        ids = tuple(str(uuid4()) for _ in range(count))
        users = tuple(str(uuid4()) for _ in ids)
        with self.sessions() as session:
            if ids:
                session.execute(
                    insert(User),
                    [
                        {
                            "id": user_id,
                            "email": f"recipient-{user_id}@example.test",
                            "full_name": "Recipient fixture",
                            "password_hash": "not-used",
                            "is_active": user_active,
                        }
                        for user_id in users
                    ],
                )
                session.execute(
                    insert(CompanyMembership),
                    [
                        {
                            "id": member_id,
                            "user_id": user_id,
                            "company_id": self.foreign_company_id if foreign else self.company_id,
                            "role": role,
                            "is_active": active,
                        }
                        for member_id, user_id in zip(ids, users, strict=True)
                    ],
                )
            session.commit()
        return ids

    def snapshot(self, *, assignee=None, team_members=None, team_active=True):
        with self.sessions() as session:
            team_id = None
            if team_members is not None:
                team = Team(
                    company_id=self.company_id,
                    name="Recipient team",
                    slug=f"recipient-{uuid4().hex}",
                    is_active=team_active,
                )
                session.add(team)
                session.flush()
                team_id = team.id
                session.add_all(
                    [
                        TeamMembership(team_id=team_id, membership_id=member_id)
                        for member_id in team_members
                    ]
                )
                session.flush()
            matter = Matter(
                company_id=self.company_id,
                title="Recipient fixture",
                matter_code=f"R-{uuid4().hex}",
                practice_area="commercial",
                forum_level="high_court",
                assignee_membership_id=assignee,
                team_id=team_id,
            )
            session.add(matter)
            session.flush()
            matter_id = matter.id
            session.commit()
            row = session.execute(
                select(
                    Matter.id,
                    Matter.company_id,
                    Matter.assignee_membership_id,
                    Matter.team_id,
                ).where(Matter.id == matter_id)
            ).one()
        # The production selector also accepts a scalar-only transient Matter snapshot.
        return Matter(
            id=row.id,
            company_id=row.company_id,
            assignee_membership_id=row.assignee_membership_id,
            team_id=row.team_id,
        )


@pytest.fixture
def data(recipient_sessions):
    engine = recipient_sessions.kw["bind"]
    catalogue = inspect(engine)
    assert catalogue.get_pk_constraint("company_memberships")["constrained_columns"] == ["id"]
    assert {
        tuple(fk["constrained_columns"]) for fk in catalogue.get_foreign_keys("company_memberships")
    } >= {("company_id",), ("user_id",)}
    with recipient_sessions() as session:
        if engine.dialect.name == "sqlite":
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        assert session.scalar(select(func.count()).select_from(Company)) == 0
        companies = [
            Company(
                name="Recipient fixture",
                slug=f"recipient-{uuid4().hex}",
                company_type="law_firm",
                tenant_key=uuid4().hex,
            )
            for _ in range(2)
        ]
        session.add_all(companies)
        session.flush()
        own_id, foreign_id = (company.id for company in companies)
        session.commit()
    return Data(recipient_sessions, own_id, foreign_id)


@dataclass
class Read:
    statement: object
    rows: tuple


@dataclass
class Observed:
    reads: list = field(default_factory=list)
    native: list = field(default_factory=list)


@contextmanager
def observe(session):
    observed = Observed()
    engine = session.get_bind()
    before_map = dict(session.identity_map)

    def execute(state):
        assert state.is_select, "Recipient selection must not write."
        result = state.invoke_statement()
        frozen = result.freeze()
        observed.reads.append(Read(state.statement, tuple(tuple(row) for row in frozen().all())))
        return frozen()

    def native(_connection, _cursor, sql, parameters, context, many):
        assert not many
        assert sql.lstrip().upper().startswith("SELECT"), sql
        compiled = context.compiled
        limits = []
        seen = set()
        positions = [
            expanded
            for name in (compiled.positiontup or ())
            for expanded in context._expanded_parameters.get(name, (name,))
        ]
        if compiled.positional:
            assert len(positions) == len(parameters)
        for node in visitors.iterate(compiled.statement):
            clause = getattr(node, "_limit_clause", None)
            if clause is None or id(clause) in seen:
                continue
            seen.add(id(clause))
            name = compiled.bind_names[clause]
            value = context.compiled_parameters[0][name]
            received = (
                parameters[positions.index(name)]
                if compiled.positional
                else parameters[name]
            )
            assert received == value
            assert isinstance(value, int) and 0 < value <= 1001
            limits.append(value)
        observed.native.append((sql, tuple(limits)))

    def loaded(_session, instance):
        pytest.fail(f"Recipient selector hydrated ORM object {type(instance).__name__}")

    event.listen(session, "do_orm_execute", execute, retval=True)
    event.listen(session, "loaded_as_persistent", loaded)
    event.listen(engine, "before_cursor_execute", native)
    try:
        yield observed
    finally:
        event.remove(engine, "before_cursor_execute", native)
        event.remove(session, "loaded_as_persistent", loaded)
        event.remove(session, "do_orm_execute", execute)
        assert dict(session.identity_map) == before_map


def outcome(selector, session, matter):
    try:
        return ("ok", selector(session, matter=matter))
    except owner.ComplianceParticipantFenceError as error:
        assert type(error) is owner.ComplianceParticipantFenceError
        return ("error", error.status_code, error.detail)


def run(data, selector, matter):
    with data.sessions() as session, observe(session) as observed:
        answer = outcome(selector, session, matter)
    assert len(observed.reads) == len(observed.native)
    return answer, observed


def union_leaves(statement):
    assert isinstance(statement, CompoundSelect)
    assert statement.keyword.value == "UNION ALL"
    assert statement._limit_clause is None
    assert len(statement.selects) == 2
    return tuple(branch.get_final_froms()[0].element for branch in statement.selects)


def assert_work(original, candidate, *, assigned, admins, own_assigned, team, rejected=False):
    # A raw assigned overflow must stop before either membership read.
    if assigned > 500:
        assert team
        assert len(original.reads) == len(candidate.reads) == 1
        assert len(candidate.reads[0].rows) == 501
        assert candidate.native[0][1] == (501,)
        return
    assert len(candidate.reads) == 1 + int(team), (
        "Recipient selection must use one bounded membership read."
    )
    assert len(original.reads) == 1 + int(team) + int(bool(not rejected and (admins or assigned)))
    if team:
        assert candidate.native[0][1] == original.native[0][1] == (501,)
        assert len(candidate.reads[0].rows) <= 501
    final = candidate.reads[-1]
    original_admin = original.reads[int(team)].statement
    if assigned:
        admin, assigned_leaf = union_leaves(final.statement)
        assert isinstance(assigned_leaf, Select)
        assert assigned_leaf._limit_clause is None
        assert [column.key for column in assigned_leaf.selected_columns] == [
            "id",
            "role",
            "is_active",
        ]
    else:
        admin = final.statement
        assert isinstance(admin, Select)
    assert admin.whereclause.compare(original_admin.whereclause)
    assert admin._limit_clause.value == original_admin._limit_clause.value == 501
    assert candidate.native[-1][1] == (501,)
    assert [column.key for column in admin.selected_columns] == ["id", "role", "is_active"]
    assert len(final.rows) == min(admins, 501) + own_assigned
    assert len(final.rows) <= 501 + assigned <= 1001
    assert all(
        len(row) == 3
        and isinstance(row[0], str)
        and isinstance(row[1], str)
        and isinstance(row[2], bool)
        for row in final.rows
    )


def test_team_assignee_admin_union_and_raw_duplicates(data, recipient_selector, legacy_selector):
    owner_ids = data.members(1, role="owner")
    inactive_admin = data.members(1, role="admin", active=False)
    assignee = data.members(1)
    viewer = data.members(1, role="viewer", user_active=False)
    inactive_member = data.members(1, active=False)
    assigned = owner_ids + inactive_admin + assignee + viewer + inactive_member
    matter = data.snapshot(assignee=assignee[0], team_members=assigned, team_active=False)
    original, old_work = run(data, legacy_selector, matter)
    actual, work = run(data, recipient_selector, matter)
    expected = tuple(sorted(owner_ids + assignee + viewer))
    assert actual == original == ("ok", (expected, expected))
    assert_work(old_work, work, assigned=5, admins=2, own_assigned=5, team=True)
    assert len(work.reads[-1].rows) == 7  # Two overlapping admins are charged twice.


@pytest.mark.parametrize("kind", ["foreign", "deleted"])
def test_nonempty_unusable_assignment_never_falls_back(
    data,
    recipient_selector,
    legacy_selector,
    kind,
):
    admin = data.members(1, role="admin")
    assigned = data.members(1, foreign=kind == "foreign")
    # Foreign IDs are negative scalar inputs only, never invalid persisted FKs.
    matter = data.snapshot(assignee=None if kind == "foreign" else assigned[0])
    if kind == "foreign":
        matter.assignee_membership_id = assigned[0]
    elif kind == "deleted":
        with data.sessions() as session:
            session.execute(delete(CompanyMembership).where(CompanyMembership.id == assigned[0]))
            session.commit()
            assert (
                session.scalar(
                    select(Matter.assignee_membership_id).where(
                        Matter.id == matter.id,
                    )
                )
                is None
            )
    original, old_work = run(data, legacy_selector, matter)
    actual, work = run(data, recipient_selector, matter)
    assert actual == original == ("ok", ((), admin))
    assert_work(old_work, work, assigned=1, admins=1, own_assigned=0, team=False)


@pytest.mark.parametrize(
    "admins,assigned,overlap,rejected",
    [
        pytest.param(500, 0, 0, False, id="admin-500-passes"),
        pytest.param(0, 500, 0, False, id="assigned-500-passes"),
        pytest.param(0, 501, 0, True, id="team-501-stops-before-memberships"),
        pytest.param(250, 250, 0, False, id="disjoint-union-500-passes"),
        pytest.param(250, 251, 0, True, id="inactive-disjoint-union-501-rejects"),
        pytest.param(500, 500, 500, False, id="full-overlap-1000-raw-rows-passes"),
        pytest.param(500, 500, 499, True, id="overlap-union-501-rejects"),
        pytest.param(1100, 500, 0, True, id="admin-overflow-1001-raw-rows-rejects"),
    ],
)
def test_exact_caps_and_raw_row_charge(
    data,
    recipient_selector,
    legacy_selector,
    admins,
    assigned,
    overlap,
    rejected,
):
    # Overflow fixtures are entirely inactive, so filtering first would be a real regression.
    admin_ids = data.members(admins, role="admin", active=not rejected)
    assigned_ids = admin_ids[:overlap] + data.members(assigned - overlap, active=not rejected)
    matter = data.snapshot(team_members=assigned_ids if assigned else None)
    original, old_work = run(data, legacy_selector, matter)
    actual, work = run(data, recipient_selector, matter)
    expected_review = tuple(sorted(assigned_ids or admin_ids))
    expected_failure = tuple(sorted(set(assigned_ids) | set(admin_ids)))
    assert (
        actual
        == original
        == (
            CAP_ERROR
            if rejected
            else (
                "ok",
                (expected_review, expected_failure),
            )
        )
    )
    assert_work(
        old_work,
        work,
        assigned=assigned,
        admins=admins,
        own_assigned=assigned,
        team=bool(assigned),
        rejected=rejected,
    )
    if assigned <= 500:
        raw = work.reads[-1].rows
        assert len(raw) - len({row[0] for row in raw}) == overlap


def test_assignee_beyond_team_500_stops_before_memberships(
    data,
    recipient_selector,
    legacy_selector,
):
    assigned = data.members(501)
    matter = data.snapshot(assignee=assigned[-1], team_members=assigned[:-1])
    original, old_work = run(data, legacy_selector, matter)
    actual, work = run(data, recipient_selector, matter)
    assert actual == original == CAP_ERROR
    assert len(old_work.reads) == len(work.reads) == 1
    assert len(work.reads[0].rows) == 500
    assert work.native[0][1] == (501,)


def test_foreign_assignment_still_counts_in_raw_union_cap(
    data,
    recipient_selector,
    legacy_selector,
):
    data.members(500, role="owner")
    foreign = data.members(1, foreign=True)
    matter = data.snapshot()
    matter.assignee_membership_id = foreign[0]  # Negative input, not a database write.
    original, old_work = run(data, legacy_selector, matter)
    actual, work = run(data, recipient_selector, matter)
    assert actual == original == CAP_ERROR
    assert_work(old_work, work, assigned=1, admins=500, own_assigned=0, team=False, rejected=True)
