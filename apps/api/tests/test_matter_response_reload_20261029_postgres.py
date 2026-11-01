"""Post-commit MatterRecord hydration, using the real PostgreSQL session boundary."""

from __future__ import annotations

import json
from collections import Counter
from contextlib import contextmanager
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, event, func, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import visitors

from caseops_api.db.models import (
    Matter,
    MatterCourtOrder,
    MatterNote,
    MatterTag,
    MatterTagAssignment,
)
from caseops_api.schemas.matter_tags import MatterTagRecord
from caseops_api.schemas.matters import MatterRecord, MatterUpdateRequest
from caseops_api.services import matters
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
_DERIVED = {"tags", "has_stay", "has_interim_order"}
_QUERY_TABLES = Counter({
    ("matters",): 1,
    ("matter_tag_assignments", "matter_tags"): 1,
    ("matter_court_orders",): 1,
})


@pytest.fixture
def reload_seed(pg_engine):
    with Session(pg_engine, expire_on_commit=False) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        matter_id = _seed_matter(session, company_id)
        foreign_company_id = _seed_company(session)
        foreign_matter_id = _seed_matter(session, foreign_company_id)
        row = session.get(Matter, matter_id)
        assert row is not None
        row.assignee_membership_id = actor_id
        row.responsible_lawyer_membership_id = actor_id
        row.matter_type = "civil_suit"
        row.client_code = "RELOAD-CLIENT"
        row.client_contact_number = "+919876543210"
        row.client_email = "reload@example.invalid"
        row.opposing_party = "Response opponent"
        row.opposing_counsel = "Response counsel"
        row.court_name = "Response test court"
        row.court_forum_number = "Court 7"
        row.judge_name = "Response test judge"
        row.case_number = "CS/29/2026"
        row.temporary_e_case_number = "TEMP-RELOAD"
        row.filing_number = "F/29/2026"
        row.filing_date = date(2026, 10, 1)
        row.cnr_number = "DLCT010012342026"
        row.description = "Pre-commit description"
        row.next_hearing_on = date(2026, 11, 3)
        row.next_hearing_source = "manual"
        row.next_hearing_manual_lock = True
        row.claim_amount_minor = 123456
        row.claim_currency = "INR"
        row.claim_amount_notes = "Response scalar coverage"
        row.oc_cross_visibility_enabled = True
        tags = [
            MatterTag(company_id=company_id, name=name, slug=slug, color_key=color,
                      created_by_membership_id=actor_id)
            for name, slug, color in (("Zulu", "reload-zulu", "red"),
                                      ("alpha", "reload-alpha", "green"))
        ]
        session.add_all(tags)
        session.flush()
        session.add_all([
            MatterTagAssignment(company_id=company_id, matter_id=matter_id, tag_id=tag.id,
                                created_by_membership_id=actor_id, source="manual")
            for tag in tags
        ])
        order = MatterCourtOrder(
            matter_id=matter_id, order_date=date(2026, 10, 2), title="Response order",
            summary="Valid persisted response fixture", source="manual",
            order_kind="daily_order", is_interim_order=True, stay_status="granted",
        )
        session.add(order)
        session.add(MatterNote(matter_id=matter_id, author_membership_id=actor_id,
                               body="Unrelated note must not be reloaded after commit."))
        session.commit()
        return {
            "company_id": company_id, "actor_id": actor_id, "matter_id": matter_id,
            "foreign_matter_id": foreign_matter_id, "tag_id": tags[0].id,
            "order_id": order.id,
        }


def _scalar_values(row):
    fields = set(MatterRecord.model_fields) - _DERIVED
    columns = set(inspect(Matter).columns.keys())
    assert fields <= columns, "A new DTO field needs an explicit non-scalar oracle."
    return {name: getattr(row, name) for name in sorted(fields)}


def _stored_values(engine, seed):
    with Session(engine) as check:
        row = check.scalar(select(Matter).where(
            Matter.id == seed["matter_id"], Matter.company_id == seed["company_id"],
        ))
        assert row is not None
        tag_fields = set(MatterTagRecord.model_fields)
        assert tag_fields <= set(inspect(MatterTag).columns.keys())
        tags = list(check.scalars(
            select(MatterTag).join(MatterTagAssignment, MatterTagAssignment.tag_id == MatterTag.id)
            .where(MatterTagAssignment.matter_id == seed["matter_id"],
                   MatterTagAssignment.company_id == seed["company_id"],
                   MatterTag.company_id == seed["company_id"])
        ))
        return {
            "scalars": _scalar_values(row),
            "tags": [{name: getattr(tag, name) for name in sorted(tag_fields)}
                     for tag in sorted(tags, key=lambda tag: tag.name.lower())],
        }


@contextmanager
def _response_inventory(session, engine, tmp_path, record_property, *, after_commit=None):
    receipt = {"commit_count": 0, "selects": [], "capture_finished": False}
    owned_connections = []
    recording = False

    def began(_session, _transaction, connection):
        owned_connections.append(connection)

    def committed(_session):
        nonlocal recording
        receipt["commit_count"] += 1
        if after_commit is not None:
            after_commit()
        recording = True

    def capture(connection, _cursor, statement, parameters, context, _many):
        if not recording or not any(connection is owned for owned in owned_connections):
            return
        if not statement.lstrip().upper().startswith(("SELECT", "WITH")):
            return
        compiled = context.compiled
        assert compiled is not None
        tables = {
            node.name
            for from_clause in compiled.statement.get_final_froms()
            for node in visitors.iterate(from_clause)
            if isinstance(node, Table)
        }
        receipt["selects"].append({"sql": statement, "tables": sorted(tables),
                                   "parameters": dict(parameters)})

    event.listen(session, "after_begin", began)
    event.listen(session, "after_commit", committed)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield receipt
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        event.remove(session, "after_commit", committed)
        event.remove(session, "after_begin", began)
        receipt["capture_finished"] = True
        evidence = tmp_path / "response-inventory.json"
        with evidence.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        record_property("matter_response_reload_inventory", str(evidence))


def _assert_inventory(receipt, seed):
    assert receipt["commit_count"] == 1
    rows = receipt["selects"]
    assert 0 < len(rows) <= 3, rows
    assert Counter(tuple(row["tables"]) for row in rows) == _QUERY_TABLES, rows
    root = next(row for row in rows if row["tables"] == ["matters"])
    assert "matters.id =" in root["sql"] and "matters.company_id =" in root["sql"]
    assert root["parameters"]["id_1"] == seed["matter_id"]
    assert root["parameters"]["company_id_1"] == seed["company_id"]


def _assert_record(record, expected, *, has_stay, has_interim):
    actual = record.model_dump()
    assert set(actual) == set(MatterRecord.model_fields)
    assert {name: value for name, value in actual.items() if name not in _DERIVED} == (
        expected["scalars"]
    )
    assert actual["tags"] == expected["tags"]
    assert actual["has_stay"] is has_stay
    assert actual["has_interim_order"] is has_interim


@pytest.mark.parametrize("expire_on_commit", [False, True], ids=["retained", "expired"])
def test_committed_response_selects_only_record_graph(
    pg_engine, reload_seed, tmp_path, record_property, expire_on_commit,
):
    seed = reload_seed
    with Session(pg_engine, expire_on_commit=expire_on_commit) as session:
        context = _ip_race_context(session, company_id=seed["company_id"],
                                   membership_id=seed["actor_id"])
        row = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        assert len(row.tag_assignments) == 2 and len(row.court_orders) == 1
        with _response_inventory(session, pg_engine, tmp_path, record_property) as receipt:
            result = matters.update_matter(
                session, context=context, matter_id=seed["matter_id"],
                payload=MatterUpdateRequest(title="Committed response title",
                                           expected_updated_at=row.updated_at),
            )
            _assert_inventory(receipt, seed)
        expected = _stored_values(pg_engine, seed)
        assert expected["scalars"]["title"] == "Committed response title"
        assert [tag["name"] for tag in expected["tags"]] == ["alpha", "Zulu"]
        _assert_record(result, expected, has_stay=True, has_interim=True)


@pytest.mark.parametrize("expire_on_commit", [False, True], ids=["retained", "expired"])
@pytest.mark.parametrize(
    "stay_status,interim_flag,order_kind,has_stay,has_interim",
    [
        ("granted", False, "daily_order", True, False),
        ("none", True, "daily_order", False, True),
        ("none", False, "interim_order", False, True),
        ("vacated", False, "daily_order", False, False),
    ],
    ids=["stay", "interim-flag", "interim-kind", "neither"],
)
def test_committed_response_sees_separate_writer_and_replaces_loaded_values(
    pg_engine, reload_seed, tmp_path, record_property, expire_on_commit,
    stay_status, interim_flag, order_kind, has_stay, has_interim,
):
    seed = reload_seed
    expected = {}
    with Session(pg_engine, expire_on_commit=expire_on_commit) as session:
        context = _ip_race_context(session, company_id=seed["company_id"],
                                   membership_id=seed["actor_id"])
        row = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        # Keep the preloaded identities alive; expire=False must replace them too.
        original_tag = next(item.tag for item in row.tag_assignments
                            if item.tag_id == seed["tag_id"])
        original_order = row.court_orders[0]
        assert original_tag.name == "Zulu" and original_order.stay_status == "granted"

        def write_after_commit():
            with Session(pg_engine, expire_on_commit=False) as writer:
                writer.execute(text("SET LOCAL lock_timeout = '2s'"))
                writer.execute(text("SET LOCAL statement_timeout = '10s'"))
                actor = _ip_race_context(writer, company_id=seed["company_id"],
                                         membership_id=seed["actor_id"])
                current = writer.get(Matter, seed["matter_id"])
                assert current is not None and current.title == "First committed title"
                matters.update_matter(
                    writer, context=actor, matter_id=seed["matter_id"], commit=False,
                    payload=MatterUpdateRequest(title="Separate writer title", client_name=None,
                                               description="Separate writer description",
                                               expected_updated_at=current.updated_at),
                )
                tag = writer.get(MatterTag, seed["tag_id"])
                order = writer.get(MatterCourtOrder, seed["order_id"])
                assert tag is not None and order is not None
                assert tag.company_id == seed["company_id"]
                assert order.matter_id == seed["matter_id"]
                tag.name = "Beta refreshed"
                order.stay_status = stay_status
                order.is_interim_order = interim_flag
                order.order_kind = order_kind
                new_tag = MatterTag(company_id=seed["company_id"], name="Aaron fresh",
                                    slug="reload-aaron", color_key="blue",
                                    created_by_membership_id=seed["actor_id"])
                writer.add(new_tag)
                writer.flush()
                writer.add(MatterTagAssignment(
                    company_id=seed["company_id"], matter_id=seed["matter_id"],
                    tag_id=new_tag.id, created_by_membership_id=seed["actor_id"], source="manual",
                ))
                writer.commit()
            expected.update(_stored_values(pg_engine, seed))

        with _response_inventory(session, pg_engine, tmp_path, record_property,
                                 after_commit=write_after_commit) as receipt:
            result = matters.update_matter(
                session, context=context, matter_id=seed["matter_id"],
                payload=MatterUpdateRequest(title="First committed title",
                                           expected_updated_at=row.updated_at),
            )
        assert expected["scalars"]["title"] == "Separate writer title"
        assert expected["scalars"]["client_name"] is None
        assert [tag["name"] for tag in expected["tags"]] == (
            ["Aaron fresh", "alpha", "Beta refreshed"]
        )
        _assert_record(result, expected, has_stay=has_stay, has_interim=has_interim)
        _assert_inventory(receipt, seed)


def test_foreign_tenant_update_is_fail_closed(pg_engine, reload_seed, tmp_path, record_property):
    seed = reload_seed
    with Session(pg_engine, expire_on_commit=False) as session:
        context = _ip_race_context(session, company_id=seed["company_id"],
                                   membership_id=seed["actor_id"])
        with Session(pg_engine) as observer:
            foreign = observer.get(Matter, seed["foreign_matter_id"])
            assert foreign is not None
            before = _scalar_values(foreign)
        with _response_inventory(session, pg_engine, tmp_path, record_property) as receipt:
            with pytest.raises(HTTPException) as error:
                matters.update_matter(
                    session, context=context, matter_id=seed["foreign_matter_id"],
                    payload=MatterUpdateRequest(title="Forbidden cross-tenant write",
                                               expected_updated_at=before["updated_at"]),
                )
            assert error.value.status_code == 404
            assert receipt["commit_count"] == 0 and receipt["selects"] == []
        session.rollback()
    with Session(pg_engine) as observer:
        foreign = observer.get(Matter, seed["foreign_matter_id"])
        assert foreign is not None and _scalar_values(foreign) == before


@pytest.mark.parametrize("expire_on_commit", [False, True], ids=["retained", "expired"])
@pytest.mark.parametrize("finish", ["rollback", "commit"])
def test_commit_false_retains_caller_work_and_transaction(
    pg_engine, reload_seed, tmp_path, record_property, expire_on_commit, finish,
):
    seed = reload_seed
    original = _stored_values(pg_engine, seed)["scalars"]
    with Session(pg_engine, expire_on_commit=expire_on_commit) as session:
        context = _ip_race_context(session, company_id=seed["company_id"],
                                   membership_id=seed["actor_id"])
        row = session.get(Matter, seed["matter_id"])
        assert row is not None
        note = MatterNote(matter_id=seed["matter_id"], author_membership_id=seed["actor_id"],
                          body="Caller-owned uncommitted work")
        session.add(note)
        with _response_inventory(session, pg_engine, tmp_path, record_property) as receipt:
            result = matters.update_matter(
                session, context=context, matter_id=seed["matter_id"], commit=False,
                payload=MatterUpdateRequest(title="Caller-owned response title",
                                           expected_updated_at=row.updated_at),
            )
            assert receipt["commit_count"] == 0 and receipt["selects"] == []
        note_id = note.id
        assert note_id is not None and session.in_transaction()
        assert session.scalar(select(func.count()).select_from(MatterNote).where(
            MatterNote.id == note_id, MatterNote.matter_id == seed["matter_id"],
        )) == 1
        assert result.title == "Caller-owned response title"
        assert {name: value for name, value in result.model_dump().items()
                if name not in _DERIVED} == _scalar_values(row)
        with Session(pg_engine) as observer:
            stored = observer.get(Matter, seed["matter_id"])
            assert stored is not None and _scalar_values(stored) == original
            assert observer.get(MatterNote, note_id) is None
        if finish == "rollback":
            session.rollback()
        else:
            session.commit()
    with Session(pg_engine) as observer:
        stored = observer.get(Matter, seed["matter_id"])
        assert stored is not None
        if finish == "rollback":
            assert _scalar_values(stored) == original
            assert observer.get(MatterNote, note_id) is None
        else:
            assert stored.title == "Caller-owned response title"
            assert observer.get(MatterNote, note_id) is not None


def test_narrow_response_preserves_later_workspace_in_same_session(
    pg_engine, reload_seed, tmp_path, record_property,
):
    seed = reload_seed
    with Session(pg_engine, expire_on_commit=False) as session:
        context = _ip_race_context(session, company_id=seed["company_id"],
                                   membership_id=seed["actor_id"])
        row = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        with _response_inventory(session, pg_engine, tmp_path, record_property) as receipt:
            response = matters.update_matter(
                session, context=context, matter_id=seed["matter_id"],
                payload=MatterUpdateRequest(title="Workspace after narrow response",
                                           expected_updated_at=row.updated_at),
            )
            _assert_inventory(receipt, seed)
        workspace = matters.get_matter_workspace(
            session, context=context, matter_id=seed["matter_id"],
        )
        assert workspace.matter.model_dump() == response.model_dump()
        assert [note.body for note in workspace.notes] == [
            "Unrelated note must not be reloaded after commit."
        ]
        assert len(workspace.court_orders) == 1 and len(workspace.activity) == 1
        with Session(pg_engine, expire_on_commit=False) as fresh:
            fresh_context = _ip_race_context(fresh, company_id=seed["company_id"],
                                             membership_id=seed["actor_id"])
            reloaded = matters.get_matter_workspace(
                fresh, context=fresh_context, matter_id=seed["matter_id"],
            )
            assert workspace.model_dump() == reloaded.model_dump()
