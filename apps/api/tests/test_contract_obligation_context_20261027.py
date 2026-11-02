"""Real canonical contract/obligation fixtures on both supported SQL dialects."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    ContractObligation,
    CustomRole,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.contract_obligation_context import list_contract_obligation_context
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company

STAMP = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def obligation_client(request):
    return request.getfixturevalue(request.param)


def fixture(client, count=3):
    seeded = bootstrap_company(client)
    headers = auth_headers(seeded["access_token"])
    created = client.post(
        "/api/contracts/",
        headers=headers,
        json={
            "title": "Recorded obligation contract",
            "contract_code": "OBLIGATIONS-01",
            "contract_type": "NDA",
            "currency": "INR",
            "total_value_minor": 1,
        },
    )
    assert created.status_code == 200, created.text
    contract = created.json()
    identities = []
    for index in range(count):
        response = client.post(
            f"/api/contracts/{contract['id']}/obligations",
            headers=headers,
            json={
                "title": f"Recorded duty {index}",
                "due_on": "2028-02-29" if index else None,
                "owner_membership_id": seeded["membership"]["id"] if index else None,
                "status": "pending",
                "priority": "medium",
            },
        )
        assert response.status_code == 200, response.text
        identities.append(response.json()["id"])
    return seeded, headers, contract, identities


def context(session, seeded):
    return SessionContext(
        company=session.get(Company, seeded["company"]["id"]),
        membership=session.get(CompanyMembership, seeded["membership"]["id"]),
        user=session.get(User, seeded["user"]["id"]),
    )


def test_real_create_acknowledgements_have_complete_stable_pages_and_reload(obligation_client):
    seeded, headers, contract, identities = fixture(obligation_client, 5)
    path = f"/api/contracts/{contract['id']}/obligations"
    first = obligation_client.get(path, params={"limit": 2}, headers=headers)
    assert first.status_code == 200, first.text
    original = first.json()
    assert original["company_id"] == seeded["company"]["id"]
    assert original["contract_id"] == contract["id"]
    assert original["limit"] == 2 and original["ordering"] == "id_ascending"
    found = [row["id"] for row in original["obligations"]]
    cursor = original["next_after"]
    while cursor is not None:
        page = obligation_client.get(path, params={"limit": 2, "after": cursor}, headers=headers)
        assert page.status_code == 200, page.text
        body = page.json()
        found.extend(row["id"] for row in body["obligations"])
        assert body["next_after"] != cursor
        cursor = body["next_after"]
    assert found == sorted(identities) and len(found) == len(set(found)) == 5
    assert obligation_client.get(path, params={"limit": 2}, headers=headers).json() == original


def test_nullable_recorded_values_and_utc_timestamps_remain_exact(obligation_client):
    seeded, headers, contract, identities = fixture(obligation_client, 1)
    with get_session_factory()() as session:
        row = session.get(ContractObligation, identities[0])
        row.created_at = STAMP
        row.completed_at = None
        session.commit()
    response = obligation_client.get(
        f"/api/contracts/{contract['id']}/obligations", headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "company_id": seeded["company"]["id"],
        "contract_id": contract["id"],
        "obligations": [
            {
                "id": identities[0],
                "contract_id": contract["id"],
                "title": "Recorded duty 0",
                "description": None,
                "description_truncated": False,
                "due_on": None,
                "status": "pending",
                "priority": "medium",
                "owner_membership_id": None,
                "owner_name": None,
                "completed_at": None,
                "created_at": "2026-10-27T01:02:03Z",
            }
        ],
        "next_after": None,
        "limit": 10,
        "ordering": "id_ascending",
    }


def test_current_tenant_read_does_not_require_contract_edit_authority(obligation_client):
    seeded, headers, contract, _ = fixture(obligation_client, 1)
    with get_session_factory()() as session:
        role = CustomRole(
            company_id=seeded["company"]["id"],
            name="Read only",
            slug="obligation-reader",
            permissions_json=[],
        )
        session.add(role)
        session.flush()
        member = session.get(CompanyMembership, seeded["membership"]["id"])
        member.role, member.custom_role_id = "member", role.id
        session.commit()
    response = obligation_client.get(
        f"/api/contracts/{contract['id']}/obligations", headers=headers
    )
    assert response.status_code == 200, response.text
    denied = obligation_client.post(
        f"/api/contracts/{contract['id']}/obligations",
        headers=headers,
        json={"title": "Must not create"},
    )
    assert denied.status_code == 403, denied.text
    assert len(response.json()["obligations"]) == 1


def test_missing_foreign_parent_and_foreign_owner_do_not_reveal_identity(obligation_client):
    seeded, headers, contract, identities = fixture(obligation_client, 1)
    foreign_company, foreign_member, foreign_user = str(uuid4()), str(uuid4()), str(uuid4())
    with get_session_factory()() as session:
        session.add(
            Company(
                id=foreign_company,
                tenant_key=foreign_company,
                name="Foreign synthetic",
                slug="foreign-obligation",
                company_type="law_firm",
            )
        )
        session.add(
            User(
                id=foreign_user,
                email="foreign-obligation@example.com",
                full_name="Foreign private owner",
                password_hash="not-a-live-password",
            )
        )
        session.flush()
        session.add(
            CompanyMembership(
                id=foreign_member, company_id=foreign_company, user_id=foreign_user, role="member"
            )
        )
        session.flush()
        session.get(ContractObligation, identities[0]).owner_membership_id = foreign_member
        session.commit()
        foreign_context = SessionContext(
            company=session.get(Company, foreign_company),
            membership=session.get(CompanyMembership, foreign_member),
            user=session.get(User, foreign_user),
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as failure:
            list_contract_obligation_context(
                session, context=foreign_context, contract_id=contract["id"]
            )
        assert failure.value.status_code == 404
    response = obligation_client.get(
        f"/api/contracts/{contract['id']}/obligations", headers=headers
    )
    assert response.status_code == 200, response.text
    record = response.json()["obligations"][0]
    assert record["owner_membership_id"] is None and record["owner_name"] is None
    assert "Foreign private owner" not in response.text and foreign_member not in response.text
    missing = obligation_client.get(f"/api/contracts/{uuid4()}/obligations", headers=headers)
    assert missing.status_code == 404


def test_cold_page_uses_three_scalar_queries_without_relationship_or_owner_fanout(
    obligation_client,
):
    seeded, _, contract, identities = fixture(obligation_client, 5)
    with get_session_factory()() as session:
        actor = context(session, seeded)
        statements, loaded = [], []

        def capture(_c, _u, statement, _p, _x, _m):
            statements.append(statement)

        def observe(_session, row):
            loaded.append(row)

        event.listen(session.bind, "before_cursor_execute", capture)
        event.listen(session, "loaded_as_persistent", observe)
        try:
            page = list_contract_obligation_context(
                session, context=actor, contract_id=contract["id"], limit=2
            )
            assert [row.id for row in page.obligations] == sorted(identities)[:2]
            assert page.next_after == sorted(identities)[1]
            assert len(statements) == 3 and loaded == []
            assert all(
                "contract_attachments" not in statement and "contract_clauses" not in statement
                for statement in statements
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", capture)
            event.remove(session, "loaded_as_persistent", observe)


def test_cursor_never_substitutes_another_contract_and_invalid_limits_refuse(obligation_client):
    seeded, headers, contract, identities = fixture(obligation_client, 1)
    path = f"/api/contracts/{contract['id']}/obligations"
    for params in ({"limit": 0}, {"limit": 26}, {"after": "not-a-uuid"}):
        response = obligation_client.get(path, params=params, headers=headers)
        assert response.status_code == 422, response.text
    response = obligation_client.get(
        path, params={"after": "ffffffff-ffff-ffff-ffff-ffffffffffff"}, headers=headers
    )
    assert response.status_code == 404
    second = obligation_client.post(
        "/api/contracts/",
        headers=headers,
        json={
            "title": "Other recorded contract",
            "contract_code": "OBLIGATIONS-OTHER",
            "contract_type": "NDA",
        },
    )
    assert second.status_code == 200, second.text
    child = obligation_client.post(
        f"/api/contracts/{second.json()['id']}/obligations",
        headers=headers,
        json={"title": "Other recorded duty"},
    )
    assert child.status_code == 200, child.text
    wrong = obligation_client.get(path, params={"after": child.json()["id"]}, headers=headers)
    assert wrong.status_code == 404
    response = obligation_client.get(path, params={"after": identities[0]}, headers=headers)
    assert response.status_code == 200 and response.json()["obligations"] == []
    assert response.json()["next_after"] is None
    with get_session_factory()() as session:
        assert (
            session.scalars(
                select(ContractObligation.id).where(
                    ContractObligation.contract_id == contract["id"]
                )
            ).all()
            == identities
        )


def test_page_bounds_are_independent_of_retained_obligation_history(obligation_client):
    seeded, _, contract, _ = fixture(obligation_client, 0)
    ids = [f"a0000000-0000-4000-8000-{index:012x}" for index in range(3000)]
    with get_session_factory()() as session:
        session.add_all(
            [
                ContractObligation(
                    id=identity,
                    contract_id=contract["id"],
                    title="Retained duty",
                    due_on=date(2026, 10, 27),
                    created_at=STAMP,
                )
                for identity in ids
            ]
        )
        session.commit()
    with get_session_factory()() as session:
        page = list_contract_obligation_context(
            session,
            context=context(session, seeded),
            contract_id=contract["id"],
            limit=25,
            after=ids[1499],
        )
        assert [row.id for row in page.obligations] == ids[1500:1525]
        assert page.next_after == ids[1524]


def test_long_retained_description_is_an_explicit_unicode_preview_with_valid_siblings(
    obligation_client,
):
    _, headers, contract, identities = fixture(obligation_client, 2)
    retained = "क\U0001f4da" * 3000
    with get_session_factory()() as session:
        session.get(ContractObligation, identities[0]).description = retained
        session.commit()
    response = obligation_client.get(
        f"/api/contracts/{contract['id']}/obligations", headers=headers
    )
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["obligations"]}
    assert set(rows) == set(identities)
    assert rows[identities[0]]["description"] == retained[:4000]
    assert rows[identities[0]]["description_truncated"] is True
    assert rows[identities[1]]["description"] is None
    assert rows[identities[1]]["description_truncated"] is False
    with get_session_factory()() as session:
        assert session.get(ContractObligation, identities[0]).description == retained
