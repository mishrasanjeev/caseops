"""Matter read projection: exact money, bounded pages and current existing ACL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.sql import visitors
from sqlalchemy.sql.schema import Table

from caseops_api.db.models import (
    Company,
    MatterOutsideCounselAssignment,
    OutsideCounsel,
    OutsideCounselSpendRecord,
)
from caseops_api.db.session import get_engine, get_session_factory
from tests.sql_observation import is_read_only_select
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_outside_counsel import _create_matter, _invite_admin

STAMP = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)


def uid(number):
    return str(UUID(int=number))


def setup_case(client, count=2):
    auth = bootstrap_company(client)
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    headers = auth_headers(auth["access_token"])
    matter = _create_matter(
        client, auth["access_token"], title="Scoped counsel", matter_code="OC-PAGE-01"
    )
    seed_rows(auth, matter, count=count)
    return {
        "client": client,
        "auth": auth,
        "headers": headers,
        "matter": matter,
        "url": f"/api/outside-counsel/matters/{matter['id']}/context",
    }


def seed_rows(auth, matter, *, count, start=1, stride=1):
    with get_session_factory()() as session:
        for index in range(count):
            number = start + index * stride
            counsel = OutsideCounsel(
                id=uid(10000 + number),
                company_id=auth["company"]["id"],
                name=f"Scoped counsel {number}",
                panel_status="active",
                created_at=STAMP,
                updated_at=STAMP,
            )
            session.add(counsel)
            session.flush()
            assignment = MatterOutsideCounselAssignment(
                id=uid(number),
                company_id=auth["company"]["id"],
                matter_id=matter["id"],
                counsel_id=counsel.id,
                assigned_by_membership_id=auth["membership"]["id"],
                role_summary="Recorded representation",
                budget_amount_minor=1 if index == 0 else 99,
                currency="INR" if index == 0 else "USD",
                status="approved",
                created_at=STAMP,
                updated_at=STAMP,
            )
            session.add(assignment)
            session.flush()
            session.add(
                OutsideCounselSpendRecord(
                    id=uid(20000 + number),
                    company_id=auth["company"]["id"],
                    matter_id=matter["id"],
                    counsel_id=counsel.id,
                    assignment_id=assignment.id,
                    recorded_by_membership_id=auth["membership"]["id"],
                    description="Recorded fees",
                    currency=assignment.currency,
                    amount_minor=3 if index == 0 else 37,
                    approved_amount_minor=1 if index == 0 else 25,
                    status="paid" if index == 0 else "approved",
                    created_at=STAMP,
                    updated_at=STAMP,
                )
            )
        session.commit()


def get(case, headers=None, **params):
    return case["client"].get(case["url"], headers=headers or case["headers"], params=params)


def rows_snapshot():
    with get_session_factory()() as session:
        return [
            [
                {c.key: getattr(row, c.key) for c in model.__table__.columns}
                for row in session.scalars(select(model).order_by(model.id))
            ]
            for model in (OutsideCounsel, MatterOutsideCounselAssignment, OutsideCounselSpendRecord)
        ]


def exercise_exact_money(client):
    case = setup_case(client)
    before = rows_snapshot()
    statements = []
    classifications = []
    actual_tables = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
        actual = getattr(getattr(_context, "compiled", None), "statement", None)
        classifications.append(is_read_only_select(actual))
        actual_tables.append(
            {node.name for node in visitors.iterate(actual) if isinstance(node, Table)}
            if actual is not None
            else set()
        )

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = get(case)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matter_id"] == case["matter"]["id"]
    assert body["matter_title"] == "Scoped counsel"
    assert body["totals_scope"] == "page"
    assert body["assignment_next_after"] is body["spend_next_after"] is None
    assert body["currencies"] == [
        {
            "currency": "INR",
            "recorded_budget_minor": 1,
            "unpriced_assignment_count": 0,
            "amount_minor": 3,
            "approved_amount_minor": 1,
            "paid_amount_minor": 1,
            "pending_amount_minor": 2,
        },
        {
            "currency": "USD",
            "recorded_budget_minor": 99,
            "unpriced_assignment_count": 0,
            "amount_minor": 37,
            "approved_amount_minor": 25,
            "paid_amount_minor": 0,
            "pending_amount_minor": 37,
        },
    ]
    assert [r["id"] for r in body["assignments"]] == [uid(1), uid(2)]
    assert [r["id"] for r in body["spend_records"]] == [uid(20001), uid(20002)]
    assert body["assignments"][0]["budget_amount_minor"] == 1
    assert body["assignments"][0]["fee_agreed_minor"] == 1
    assert body["spend_records"][0]["payment_tracking_status"] == "partially_paid"
    assert body["spend_records"][0]["pending_amount_minor"] == 2
    assert all(
        r["created_at"] == "2026-10-27T01:02:03Z"
        for key in ("assignments", "spend_records")
        for r in body[key]
    )
    assert "profiles" not in body and "summary" not in body and "invoices" not in body
    assert len(classifications) == len(statements) and all(classifications)
    assert all(
        row["matter_title"] == "Scoped counsel"
        and row["matter_code"] == "OC-PAGE-01"
        and row["counsel_name"] == f"Scoped counsel {index}"
        and row["assigned_by_name" if key == "assignments" else "recorded_by_name"]
        == "Sanjay Mishra"
        for key in ("assignments", "spend_records")
        for index, row in enumerate(body[key], start=1)
    )
    assert len(statements) <= 16
    if engine.dialect.name == "postgresql":
        page_reads = [tables for tables in actual_tables if "counsel_read_pages" in tables]
        assert len(page_reads) == 2
        shared = {
            "counsel_read_pages",
            "counsel_read_page_dirty",
            "outside_counsel",
            "company_memberships",
            "users",
        }
        # Both execution-time branches remain typed and observed; normal
        # committed plans must separately prove zero source-fallback loops.
        assert {frozenset(tables) for tables in page_reads} == {
            frozenset(shared | {"matter_outside_counsel_assignments"}),
            frozenset(shared | {"outside_counsel_spend_records"}),
        }
    else:
        assert sum("FROM matter_outside_counsel_assignments" in s for s in statements) == 1
        assert sum("FROM outside_counsel_spend_records" in s for s in statements) == 1
    assert rows_snapshot() == before
    assert get(case).json() == body  # Complete repeated DTO, no regenerated reporting values.


def exercise_pages(client):
    case = setup_case(client, count=28)
    other = _create_matter(
        client, case["auth"]["access_token"], title="Foreign page", matter_code="OC-PAGE-02"
    )
    seed_rows(case["auth"], other, count=4, start=101)
    first = get(case, assignment_limit=2, spend_limit=3)
    assert first.status_code == 200, first.text
    first = first.json()
    assert [r["id"] for r in first["assignments"]] == [uid(1), uid(2)]
    assert first["assignment_next_after"] == uid(2)
    assert first["spend_next_after"] == uid(20003)
    assert len(first["spend_records"]) == 3
    assert first["totals_scope"] == "page"
    second = get(
        case,
        assignment_limit=2,
        spend_limit=3,
        assignment_after=first["assignment_next_after"],
        spend_after=first["spend_next_after"],
    )
    assert second.status_code == 200, second.text
    assert [r["id"] for r in second.json()["assignments"]] == [uid(3), uid(4)]
    assert [r["id"] for r in second.json()["spend_records"]] == [uid(20004), uid(20005), uid(20006)]
    ids, after = [], None
    for _ in range(4):
        page = get(case, assignment_limit=10, **({"assignment_after": after} if after else {}))
        assert page.status_code == 200, page.text
        ids.extend(r["id"] for r in page.json()["assignments"])
        after = page.json()["assignment_next_after"]
        if after is None:
            break
    assert ids == [uid(index) for index in range(1, 29)]
    assert len(set(ids)) == 28 and after is None
    for cursor in (uid(101), uid(999999)):
        bad = get(case, assignment_after=cursor)
        assert bad.status_code == 404, bad.text
    for params in ({"assignment_limit": 26}, {"spend_limit": 0}, {"assignment_after": "bad"}):
        invalid = get(case, **params)
        assert invalid.status_code == 422, invalid.text


def exercise_acl(client, boundary):
    assert boundary in ("restricted", "wall", "team", "foreign", "closed")
    case = setup_case(client, count=3)
    admin_id, token = _invite_admin(client, case["auth"]["access_token"])
    headers = auth_headers(token)
    initial = get(case, headers, assignment_limit=1)
    assert initial.status_code == 200, initial.text
    cursor = initial.json()["assignment_next_after"]
    if boundary in ("restricted", "wall"):
        response = client.post(
            f"/api/matters/{case['matter']['id']}/access/restricted",
            headers=case["headers"],
            json={"restricted": True},
        )
        assert response.status_code == 200, response.text
        if boundary == "wall":
            grant = client.post(
                f"/api/matters/{case['matter']['id']}/access/grants",
                headers=case["headers"],
                json={"membership_id": admin_id, "reason": "Scoped read"},
            )
            assert grant.status_code == 200, grant.text
            assert get(case, headers).status_code == 200
            response = client.post(
                f"/api/matters/{case['matter']['id']}/access/walls",
                headers=case["headers"],
                json={"excluded_membership_id": admin_id, "reason": "Conflict"},
            )
            assert response.status_code == 200, response.text
    elif boundary == "team":
        team = client.post(
            "/api/teams/",
            headers=case["headers"],
            json={"name": "Counsel readers", "slug": "counsel-readers"},
        )
        assert team.status_code == 201, team.text
        response = client.patch(
            f"/api/matters/{case['matter']['id']}",
            headers=case["headers"],
            json={
                "team_id": team.json()["id"],
                "expected_updated_at": case["matter"]["updated_at"],
            },
        )
        assert response.status_code == 200, response.text
        response = client.put("/api/teams/scoping", headers=case["headers"], json={"enabled": True})
        assert response.status_code == 200, response.text
    elif boundary == "foreign":
        with get_session_factory()() as session:
            company = Company(
                name="Foreign tenant",
                slug="foreign-counsel-context",
                tenant_key="foreign-counsel-context",
                company_type="law_firm",
            )
            session.add(company)
            session.commit()
            foreign_id = company.id
        # Create a separate foreign record; never move a retained Matter/children.
        from caseops_api.db.models import Matter

        with get_session_factory()() as session:
            foreign = Matter(
                company_id=foreign_id,
                title="Foreign private Matter",
                matter_code="FOREIGN-OC",
                practice_area="litigation",
                forum_level="high_court",
                court_name="Synthetic court",
            )
            session.add(foreign)
            session.commit()
            case["url"] = f"/api/outside-counsel/matters/{foreign.id}/context"
    elif boundary == "closed":
        parent = client.get(
            f"/api/matters/{case['matter']['id']}/workspace", headers=case["headers"]
        ).json()["matter"]
        response = client.patch(
            f"/api/matters/{parent['id']}/lifecycle/status",
            headers=case["headers"],
            json={
                "to_status": "disposed",
                "expected_from_status": parent["status"],
                "expected_updated_at": parent["updated_at"],
                "reason": "Retain counsel context",
            },
        )
        assert response.status_code == 200, response.text
    result = get(case, headers, assignment_after=cursor)
    if boundary == "closed":
        assert result.status_code == 200, result.text
        assert (
            result.json()["matter_status"] == "disposed"
            and result.json()["matter_is_active"] is False
        )
        assert [r["id"] for r in result.json()["assignments"]] == [uid(2), uid(3)]
    else:
        assert result.status_code == 404, result.text
        assert "Scoped counsel" not in result.text and "Recorded fees" not in result.text


def test_matter_counsel_exact_literal_paise_currency_and_read_only_reload(client):
    exercise_exact_money(client)


def test_matter_counsel_independent_bounded_pages_and_scope(client):
    exercise_pages(client)


@pytest.mark.parametrize("boundary", ["restricted", "wall", "team", "foreign", "closed"])
def test_matter_counsel_reauthorizes_current_acl_on_each_page(client, boundary):
    exercise_acl(client, boundary)
