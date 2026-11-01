"""B4-ADJ-02: a screen names a referenced Matter without recording a probe.

Rows on the notification-rules page, the mailbox, Drive and calendar-conflict
queues carry a Matter id. The web named each one with GET /api/matters/{id},
which records a committed ``access_denied`` audit event for a Matter the
viewer is walled from, so simply opening the page read as probing in the
audit trail. GET /api/matters/?id= goes through the list's tenant and
ethical-wall filter instead: a hidden Matter is absent, nothing is audited.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ethical_walls import _create_matter, _invite_member


def _denials(company_id: str, matter_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "access_denied",
                    AuditEvent.target_id == matter_id,
                )
            )
            or 0
        )


def _by_id(client: TestClient, token: str, matter_id: str) -> list[str]:
    response = client.get(
        "/api/matters/", params={"id": matter_id, "limit": 1}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["matters"]]


def test_id_filter_returns_exactly_the_visible_matter(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner = str(boot["access_token"])
    first = _create_matter(client, owner, "ID-FILTER-1")
    _create_matter(client, owner, "ID-FILTER-2")
    assert _by_id(client, owner, first) == [first]
    assert _by_id(client, owner, "00000000-0000-0000-0000-000000000000") == []


def test_walled_admin_reads_no_matter_and_writes_no_denial(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, owner, "ID-FILTER-WALL")
    admin_mid, admin_token = _invite_member(
        client, owner, "walled-admin@asterlegal.in", role="admin"
    )
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": admin_mid, "reason": "Conflict on the other side."},
    )
    assert wall.status_code == 200, wall.text

    # The admin's notification-rule page lists every rule in the company; a
    # rule scoped to this Matter is named through the id filter.
    rule = client.post(
        "/api/notification-rules",
        headers=auth_headers(owner),
        json={
            "scope_type": "matter",
            "scope_id": matter_id,
            "event_type": "hearing_upcoming",
            "channels": ["in_app"],
            "enabled": True,
        },
    )
    assert rule.status_code in {200, 201}, rule.text
    rules = client.get("/api/notification-rules", headers=auth_headers(admin_token))
    assert rules.status_code == 200, rules.text

    before = _denials(company_id, matter_id)
    for _ in range(3):  # each render or refetch
        assert _by_id(client, admin_token, matter_id) == []
    assert _denials(company_id, matter_id) == before

    # Positive control: the by-id read still records the denial, which is
    # why display lookups must not use it.
    direct = client.get(f"/api/matters/{matter_id}", headers=auth_headers(admin_token))
    assert direct.status_code == 404
    assert _denials(company_id, matter_id) == before + 1


def test_restricted_matter_is_absent_until_granted(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner = str(boot["access_token"])
    matter_id = _create_matter(client, owner, "ID-FILTER-RESTRICT")
    member_mid, member_token = _invite_member(client, owner, "restricted-id@asterlegal.in")
    client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner),
        json={"restricted": True},
    )
    assert _by_id(client, member_token, matter_id) == []
    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner),
        json={"membership_id": member_mid, "reason": "Joining the brief."},
    )
    assert grant.status_code == 200, grant.text
    assert _by_id(client, member_token, matter_id) == [matter_id]


def test_other_tenant_cannot_read_a_matter_by_id(client: TestClient) -> None:
    boot = bootstrap_company(client)
    matter_id = _create_matter(client, str(boot["access_token"]), "ID-FILTER-TENANT")
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Chambers",
            "company_slug": "other-chambers-id",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@otherchambers.in",
            "owner_password": "OtherPass123!",
        },
    )
    assert other.status_code == 200, other.text
    assert _by_id(client, str(other.json()["access_token"]), matter_id) == []


def test_id_filter_rejects_an_oversized_value(client: TestClient) -> None:
    boot = bootstrap_company(client)
    response = client.get(
        "/api/matters/",
        params={"id": "x" * 37},
        headers=auth_headers(str(boot["access_token"])),
    )
    assert response.status_code == 422
