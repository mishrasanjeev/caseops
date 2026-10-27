"""Real canonical DTOs and old-column writers against synchronous derived pages."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors
from sqlalchemy.sql.schema import Table

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    CounselReadPage,
    CounselReadPageDirty,
    CounselReadPageMember,
    DomainOutboxEvent,
    MatterOutsideCounselAssignment,
    NotificationDeliveryIntent,
    OutsideCounsel,
    OutsideCounselSpendRecord,
    User,
)
from caseops_api.db.session import _proven_read_statement, get_engine, get_session_factory
from caseops_api.services.counsel_read_pages import counsel_page_statement, source_row_from_page
from tests.sql_observation import is_read_only_select
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_matter_counsel_context_20261027 import get, seed_rows, setup_case, uid
from tests.test_outside_counsel import _create_matter

forbid_unadmitted_network = _forbid_unadmitted_network

MODELS = (MatterOutsideCounselAssignment, OutsideCounselSpendRecord)
PROJECTIONS = (CounselReadPage, CounselReadPageMember, CounselReadPageDirty)


def case_for(client, count):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    return setup_case(client, count=count)


def snapshot(models):
    with get_session_factory()() as session:
        return [
            [
                dict(row)
                for row in session.execute(
                    select(model.__table__).order_by(*model.__table__.primary_key.columns)
                ).mappings()
            ]
            for model in models
        ]


def immutable_side_effects():
    return snapshot((AuditEvent, DomainOutboxEvent, NotificationDeliveryIntent))


def require_dense(case, expected_ids, kind):
    company, matter = case["auth"]["company"]["id"], case["matter"]["id"]
    with get_session_factory()() as session:
        if get_engine().dialect.name == "postgresql":
            pages = list(
                session.scalars(
                    select(CounselReadPage)
                    .where(
                        CounselReadPage.company_id == company,
                        CounselReadPage.matter_id == matter,
                        CounselReadPage.record_kind == kind,
                    )
                    .order_by(CounselReadPage.page_number)
                )
            )
            assert [p.page_number for p in pages] == list(range((len(expected_ids) + 24) // 25))
            assert [p.record_count for p in pages] == [
                len(expected_ids[n : n + 25]) for n in range(0, len(expected_ids), 25)
            ]
            actual = []
            for page in pages:
                ids = [r["id"] for r in page.payload]
                assert (
                    len(ids) == page.record_count
                    and page.min_id == ids[0]
                    and page.max_id == ids[-1]
                )
                assert all(
                    "internal_notes" not in r
                    and "notes" not in r
                    and "actor_name" in r
                    and "actor_user_bucket" not in r
                    for r in page.payload
                )
                assert len(json.dumps(page.payload, ensure_ascii=False).encode()) <= 1024**2
                actual.extend(ids)
            assert actual == expected_ids
        else:
            members = list(
                session.scalars(
                    select(CounselReadPageMember)
                    .where(
                        CounselReadPageMember.company_id == company,
                        CounselReadPageMember.matter_id == matter,
                        CounselReadPageMember.record_kind == kind,
                    )
                    .order_by(CounselReadPageMember.source_id)
                )
            )
            assert [m.source_id for m in members] == expected_ids
            assert [(m.page_number, m.slot_number) for m in members] == [
                (n // 25, n % 25) for n in range(len(expected_ids))
            ]
            assert session.scalar(select(CounselReadPage.company_id).limit(1)) is None


def all_ids(case, kind):
    after, result = None, []
    for _ in range(4):
        params = {"assignment_limit": 25, "spend_limit": 25}
        cursor_key = "assignment_after" if kind == "assignment" else "spend_after"
        body_key = "assignments" if kind == "assignment" else "spend_records"
        next_key = "assignment_next_after" if kind == "assignment" else "spend_next_after"
        if after is not None:
            params[cursor_key] = after
        response = get(case, **params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert get(case, **params).json() == body
        result.extend(r["id"] for r in body[body_key])
        new = body[next_key]
        assert new is None or new != after
        after = new
        if after is None:
            break
    assert after is None and len(result) == len(set(result))
    return result


def exercise_old_source_crud(client):
    case = case_for(client, 0)
    # The unchanged old writer supplies ONLY source columns after migration.
    seed_rows(case["auth"], case["matter"], count=52)
    for kind, offset in (("assignment", 0), ("spend", 20000)):
        ids = [uid(offset + n) for n in range(1, 53)]
        require_dense(case, ids, kind)
        assert all_ids(case, kind) == ids
    before = immutable_side_effects()
    with get_engine().begin() as connection:
        connection.execute(
            update(MatterOutsideCounselAssignment)
            .where(MatterOutsideCounselAssignment.id == uid(2))
            .values(budget_amount_minor=17, internal_notes="Old writer changed note")
        )
        connection.execute(
            update(OutsideCounselSpendRecord)
            .where(OutsideCounselSpendRecord.id == uid(20002))
            .values(
                amount_minor=91, approved_amount_minor=27, status="paid", notes="Old spend note"
            )
        )
        connection.execute(
            delete(MatterOutsideCounselAssignment).where(
                MatterOutsideCounselAssignment.id == uid(1)
            )
        )
    response = get(case, assignment_limit=25, spend_limit=25)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["assignments"][0]["id"] == uid(2)
        and body["assignments"][0]["budget_amount_minor"] == 17
    )
    assert body["assignments"][0]["internal_notes"] == "Old writer changed note"
    assert body["spend_records"][0]["assignment_id"] is None
    row = body["spend_records"][1]
    assert (
        row["amount_minor"],
        row["approved_amount_minor"],
        row["paid_amount_minor"],
        row["pending_amount_minor"],
        row["notes"],
    ) == (91, 27, 27, 64, "Old spend note")
    assert immutable_side_effects() == before
    require_dense(case, [uid(n) for n in range(2, 53)], "assignment")
    require_dense(case, [uid(20000 + n) for n in range(1, 53)], "spend")


def exercise_wide_old_note(client):
    case = case_for(client, 2)
    wide = "Retained old writer 📜\n" * 70000
    assert len(wide.encode()) > 1024**2
    before = immutable_side_effects()
    with get_engine().begin() as connection:
        connection.execute(
            update(MatterOutsideCounselAssignment)
            .where(MatterOutsideCounselAssignment.id == uid(1))
            .values(internal_notes=wide)
        )
        connection.execute(
            update(OutsideCounselSpendRecord)
            .where(OutsideCounselSpendRecord.id == uid(20001))
            .values(notes=wide)
        )
    response = get(case)
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert (
        body["assignments"][0]["internal_notes"] == wide
        and body["spend_records"][0]["notes"] == wide
    )
    assert get(case).json() == body and immutable_side_effects() == before
    if get_engine().dialect.name == "postgresql":
        with get_session_factory()() as session:
            pages = list(
                session.scalars(
                    select(CounselReadPage).where(CounselReadPage.matter_id == case["matter"]["id"])
                )
            )
            assert len(pages) == 2 and all(p.note_00 == wide for p in pages)
            assert all(len(json.dumps(p.payload).encode()) < 1024**2 for p in pages)
    for kind, offset in (("assignment", 0), ("spend", 20000)):
        require_dense(case, [uid(offset + 1), uid(offset + 2)], kind)


def exercise_current_names_and_foreign_actor(client):
    case = case_for(client, 2)
    with get_session_factory()() as session:
        actor = session.get(CompanyMembership, case["auth"]["membership"]["id"])
        user_id = actor.user_id
    with get_engine().begin() as connection:
        connection.execute(
            update(OutsideCounsel)
            .where(OutsideCounsel.id == uid(10001))
            .values(name="Current counsel name")
        )
        connection.execute(
            update(User).where(User.id == user_id).values(full_name="Current actor name")
        )
    body = get(case).json()
    assert (
        body["assignments"][0]["counsel_name"]
        == body["spend_records"][0]["counsel_name"]
        == "Current counsel name"
    )
    assert all(r["assigned_by_name"] == "Current actor name" for r in body["assignments"])
    assert all(r["recorded_by_name"] == "Current actor name" for r in body["spend_records"])
    with get_session_factory()() as session:
        company = Company(
            name="Foreign label",
            slug="foreign-counsel-label",
            tenant_key="foreign-counsel-label",
            company_type="law_firm",
        )
        user = User(
            email="foreign-counsel@example.com",
            full_name="Never expose foreign actor",
            password_hash="synthetic-not-authentication",
        )
        session.add_all([company, user])
        session.flush()
        foreign = CompanyMembership(
            company_id=company.id, user_id=user.id, role="viewer", is_active=True
        )
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id
        session.commit()
    before = immutable_side_effects()
    with get_engine().begin() as connection:
        connection.execute(
            update(MatterOutsideCounselAssignment)
            .where(MatterOutsideCounselAssignment.id == uid(1))
            .values(assigned_by_membership_id=foreign_id)
        )
        connection.execute(
            update(OutsideCounselSpendRecord)
            .where(OutsideCounselSpendRecord.id == uid(20001))
            .values(recorded_by_membership_id=foreign_id)
        )
    result = get(case)
    assert result.status_code == 200, result.text
    assert result.json()["assignments"][0]["assigned_by_name"] is None
    assert result.json()["spend_records"][0]["recorded_by_name"] is None
    assert "Never expose foreign actor" not in result.text and immutable_side_effects() == before


def exercise_rollback(client):
    case = case_for(client, 3)
    before = snapshot((OutsideCounsel, *MODELS, *PROJECTIONS))
    effects = immutable_side_effects()
    body = get(case).json()
    with pytest.raises(RuntimeError, match="owned rollback"):
        with get_engine().begin() as connection:
            connection.execute(
                update(MatterOutsideCounselAssignment)
                .where(MatterOutsideCounselAssignment.id == uid(1))
                .values(internal_notes="Must roll back")
            )
            connection.execute(
                update(OutsideCounsel)
                .where(OutsideCounsel.id == uid(10001))
                .values(name="Must roll back counsel")
            )
            raise RuntimeError("owned rollback")
    assert snapshot((OutsideCounsel, *MODELS, *PROJECTIONS)) == before
    assert immutable_side_effects() == effects and get(case).json() == body


def exercise_move_parent_and_cursor(client):
    case = case_for(client, 3)
    other = _create_matter(
        client,
        case["auth"]["access_token"],
        title="Current other Matter",
        matter_code="OC-PAGE-MOVE",
    )
    first = get(case, assignment_limit=1).json()
    assert first["assignment_next_after"] == uid(1)
    before = immutable_side_effects()
    with get_engine().begin() as connection:
        connection.execute(
            update(MatterOutsideCounselAssignment)
            .where(MatterOutsideCounselAssignment.id == uid(1))
            .values(matter_id=other["id"])
        )
    stale = get(case, assignment_after=uid(1))
    assert stale.status_code == 404 and "Current other Matter" not in stale.text
    other_case = {
        **case,
        "matter": other,
        "url": f"/api/outside-counsel/matters/{other['id']}/context",
    }
    actual = get(other_case)
    assert actual.status_code == 200, actual.text
    assert [(r["id"], r["matter_title"]) for r in actual.json()["assignments"]] == [
        (uid(1), "Current other Matter")
    ]
    require_dense(case, [uid(2), uid(3)], "assignment")
    require_dense(other_case, [uid(1)], "assignment")
    assert immutable_side_effects() == before


def test_actual_old_column_insert_update_delete_and_dense_pages(client):
    exercise_old_source_crud(client)


def test_valid_legacy_text_larger_than_prototype_byte_budget_survives(client):
    exercise_wide_old_note(client)


def test_current_counsel_user_names_and_foreign_actor_null(client):
    exercise_current_names_and_foreign_actor(client)


def test_projection_source_and_audit_outbox_rollback_together(client):
    exercise_rollback(client)


def test_source_move_purges_old_scope_and_rejects_old_anchor(client):
    exercise_move_parent_and_cursor(client)


@pytest.mark.parametrize("model", MODELS)
def test_real_typed_program_has_explicit_committed_and_own_write_relations_no_dml(model):
    statement = counsel_page_statement(
        model, company_id=uid(700), matter_id=uid(701), after=uid(1), limit=25
    )
    assert is_read_only_select(statement) and _proven_read_statement(statement)
    assert {n.name for n in visitors.iterate(statement) if isinstance(n, Table)} == {
        "counsel_read_pages",
        "counsel_read_page_dirty",
        model.__tablename__,
        "outside_counsel",
        "company_memberships",
        "users",
    }
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "LIMIT 2" in sql and "LIMIT 26" in sql and "OFFSET" not in sql
    assert "txid_current_if_assigned()" in sql and "UNION ALL" in sql
    assert "counsel_own_write_rows" in sql and "counsel_committed_rows" in sql


@pytest.mark.parametrize(
    "failure", ("foreign_scope", "missing_column", "unknown_column", "wrong_note", "foreign_actor")
)
def test_decode_refuses_inconsistent_projection(failure):
    payload = dict(
        id=uid(1),
        company_id=uid(7),
        matter_id=uid(8),
        counsel_id=uid(9),
        assigned_by_membership_id=None,
        role_summary=None,
        budget_amount_minor=1,
        currency="INR",
        status="approved",
        created_at="2026-10-27T01:02:03+00:00",
        updated_at="2026-10-27T01:02:03+00:00",
        counsel_name="Current counsel",
        actor_user_id=None,
        actor_name=None,
    )
    note = None
    name = None
    if failure == "foreign_scope":
        payload["company_id"] = uid(99)
    elif failure == "missing_column":
        payload.pop("status")
    elif failure == "unknown_column":
        payload["untrusted"] = True
    elif failure == "wrong_note":
        note = {"text": "not source Text"}
    else:
        name = "Not admitted by Membership"
    with pytest.raises(HTTPException) as raised:
        source_row_from_page(
            MatterOutsideCounselAssignment, payload, note, name, company_id=uid(7), matter_id=uid(8)
        )
    assert (
        raised.value.status_code == 503
        and raised.value.detail == "Counsel read projection is unavailable."
    )
