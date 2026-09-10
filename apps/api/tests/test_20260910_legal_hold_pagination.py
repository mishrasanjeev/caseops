"""DATA-GOV-04/05: retained preservation remains reachable with bounded reads."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from caseops_api.db.models import LegalHold, LegalHoldItem, LegalHoldReleaseRequest
from caseops_api.db.session import get_session_factory
from tests import test_20260909_legal_hold_workflow as workflow


def seed_holds(owner, count=105):
    with get_session_factory()() as session:
        rows = [
            LegalHold(
                company_id=owner["company_id"],
                key=uuid4().hex,
                title=f"Retained preservation {index:03d}",
                authority_reference="fixture://authority",
                creator_label_snapshot="Synthetic owner",
                status="draft",
                created_at=datetime(2026, 9, 9, tzinfo=UTC),
            )
            for index in range(count)
        ]
        session.add_all(rows)
        session.flush()
        ids = sorted((row.id for row in rows), reverse=True)
        session.add_all(
            [
                LegalHoldItem(
                    company_id=owner["company_id"],
                    legal_hold_id=row.id,
                    data_class_id="legal_holds",
                    target_type="data_class",
                    target_reference_hash="f" * 64,
                )
                for row in rows
            ]
        )
        session.commit()
    return ids


def test_hold_pages_keep_tied_rows_and_bound_queries_during_new_inserts(client):
    owner, reviewer = workflow.make_actors(client)
    expected = seed_holds(owner)
    factory = get_session_factory()
    with factory() as session:
        engine = session.get_bind()
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if "FROM legal_holds" in statement or "FROM legal_hold_items" in statement:
            statements.append(statement)

    cursor, seen = None, []
    for page in range(5):
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = client.get(
                f"{workflow.BASE}/holds",
                headers=reviewer["headers"],
                params={"limit": 25, **({"before_id": cursor} if cursor else {})},
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert result.status_code == 200, result.text
        body = result.json()
        assert len(statements) == (2 if page == 0 else 3), statements
        assert sum("FROM legal_hold_items" in sql for sql in statements) == 1
        assert all("OFFSET" not in sql or "LIMIT" in sql for sql in statements)
        assert len(body["holds"]) <= 25
        assert all(row["data_class_ids"] == ["legal_holds"] for row in body["holds"])
        seen.extend(row["id"] for row in body["holds"])
        assert body["has_more"] == (page < 4)
        cursor = body["next_before_id"]
        if page == 0:
            newest, _ = workflow._create(client, owner)
    assert cursor is None
    assert seen == expected and len(set(seen)) == 105
    assert (
        client.get(f"{workflow.BASE}/holds", headers=owner["headers"]).json()["holds"][0]["id"]
        == newest["id"]
    )
    with factory() as session:
        assert len(list(session.scalars(select(LegalHold.id)))) == 106


def test_hold_cursor_is_tenant_scoped_and_current_access_is_rechecked(client):
    owner, reviewer = workflow.make_actors(client)
    ids = seed_holds(owner, 2)
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other preservation tenant",
            "company_slug": "other-preservation",
            "company_type": "law_firm",
            "owner_full_name": "Other owner",
            "owner_email": "other-preservation@example.com",
            "owner_password": "OtherTenantProof2026!",
        },
    )
    assert response.status_code == 200, response.text
    foreign = {"company_id": response.json()["company"]["id"]}
    client.cookies.clear()
    foreign_ids = seed_holds(foreign, 1)
    for cursor in (foreign_ids[0], "not-a-real-hold"):
        result = client.get(
            f"{workflow.BASE}/holds", headers=owner["headers"], params={"before_id": cursor}
        )
        assert result.status_code == 404, result.text
        assert "Retained preservation" not in result.text
    from caseops_api.db.models import CompanyMembership

    with get_session_factory()() as session:
        session.get(CompanyMembership, reviewer["id"]).role = "member"
        session.commit()
    denied = client.get(
        f"{workflow.BASE}/holds", headers=reviewer["headers"], params={"before_id": ids[0]}
    )
    assert denied.status_code == 403
    assert "Retained preservation" not in denied.text


def test_oversized_individual_scope_is_not_hidden_by_page_allowance(client):
    owner, _ = workflow.make_actors(client)
    ids = seed_holds(owner, 2)
    with get_session_factory()() as session:
        session.add_all(
            [
                LegalHoldItem(
                    company_id=owner["company_id"],
                    legal_hold_id=ids[0],
                    data_class_id="legal_holds",
                    target_type="data_class",
                    target_reference_hash=f"{index:064x}",
                )
                for index in range(100)
            ]
        )
        session.commit()
    result = client.get(f"{workflow.BASE}/holds", headers=owner["headers"])
    assert result.status_code == 409, result.text
    assert result.json()["type"] == "legal_hold_scope_limit"


def test_release_pages_keep_scope_and_can_continue_after_anchor_expiry(client, monkeypatch):
    owner, reviewer = workflow.make_actors(client)
    active = workflow._activate(client, reviewer, workflow._create(client, owner)[0])
    proposal, _ = workflow._proposal(client, owner, active)
    with get_session_factory()() as session:
        original = session.get(LegalHoldReleaseRequest, proposal["id"])
        values = {
            column.name: getattr(original, column.name)
            for column in original.__table__.columns
            if column.name not in {"id", "idempotency_key", "created_at", "expires_at"}
        }
        now = datetime.now(UTC)
        newest = LegalHoldReleaseRequest(
            **values,
            idempotency_key=uuid4().hex,
            created_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        rows = [
            LegalHoldReleaseRequest(
                **values,
                idempotency_key=uuid4().hex,
                created_at=original.created_at + timedelta(microseconds=1),
                expires_at=now + timedelta(minutes=10),
            )
            for _ in range(27)
        ]
        session.add_all([newest, *rows])
        session.commit()
        expected = sorted((row.id for row in rows), reverse=True) + [original.id]
    url = f"{workflow.BASE}/holds/{active['id']}/release-requests"
    first = client.get(url, headers=reviewer["headers"], params={"limit": 1})
    assert first.status_code == 200, first.text
    assert first.json()["proposals"][0]["id"] == newest.id

    from caseops_api.services import legal_hold_workflow

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(minutes=2)

    monkeypatch.setattr(legal_hold_workflow, "datetime", AfterExpiry)
    second = client.get(url, headers=reviewer["headers"], params={"before_id": newest.id})
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["proposals"]] == expected[:25]
    third = client.get(
        url, headers=reviewer["headers"], params={"before_id": second.json()["next_before_id"]}
    )
    assert third.status_code == 200, third.text
    assert [row["id"] for row in third.json()["proposals"]] == expected[25:]
    assert third.json()["has_more"] is False and third.json()["next_before_id"] is None
    other = workflow._activate(client, reviewer, workflow._create(client, owner)[0])
    denied = client.get(
        f"{workflow.BASE}/holds/{other['id']}/release-requests",
        headers=reviewer["headers"],
        params={"before_id": newest.id},
    )
    assert denied.status_code == 404
    assert client.get(url, headers=reviewer["headers"], params={"limit": 101}).status_code == 422


@pytest.mark.postgres
def test_preservation_pagination_on_postgres(isolated_postgres_client):
    test_hold_pages_keep_tied_rows_and_bound_queries_during_new_inserts(isolated_postgres_client)


@pytest.mark.postgres
def test_release_pagination_on_postgres(isolated_postgres_client, monkeypatch):
    test_release_pages_keep_scope_and_can_continue_after_anchor_expiry(
        isolated_postgres_client, monkeypatch
    )
