from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AccountSetupToken,
    AuditEvent,
    CompanyMembership,
    EmployeeProfile,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.employees import AccountSetupCompleteRequest
from caseops_api.services import employees as employee_service
from tests.test_auth_company import auth_headers


def _bootstrap(
    client: TestClient,
    *,
    slug: str = "lw-s5-firm",
    email: str = "owner@lws5.example",
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner S5",
            "owner_email": email,
            "owner_password": "OwnerPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_employee(
    client: TestClient,
    token: str,
    *,
    email: str = "employee@lws5.example",
    full_name: str = "Employee S5",
    role: str = "member",
    department: str = "Litigation",
) -> dict[str, object]:
    response = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(token),
        json={
            "full_name": full_name,
            "email": email,
            "role": role,
            "mobile": "+91-9876543210",
            "designation": "Associate",
            "department": department,
            "employee_code": email.split("@")[0].upper(),
            "joined_on": "2026-05-06",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _audit_actions(company_id: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )


def test_employee_create_uses_setup_token_hash_and_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client)
    token = str(boot["access_token"])
    body = _create_employee(client, token)

    employee = body["employee"]
    setup = body["setup"]
    assert employee["email"] == "employee@lws5.example"
    assert employee["employment_status"] == "invited"
    assert employee["department"] == "Litigation"
    assert setup["debug_token"], "local/test must expose debug token for verification"
    serialized = json.dumps(body).lower()
    assert "password_hash" not in serialized
    assert "raw_password" not in serialized

    factory = get_session_factory()
    with factory() as session:
        token_rows = list(session.scalars(select(AccountSetupToken)))
        assert len(token_rows) == 1
        row = token_rows[0]
        assert row.purpose == "account_setup"
        assert row.token_hash != setup["debug_token"]
        assert len(row.token_hash) == 64
        assert row.used_at is None
        profile = session.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.membership_id == employee["membership_id"]
            )
        )
        assert profile is not None
        assert profile.employee_code == "EMPLOYEE"

    actions = [event.action for event in _audit_actions(str(boot["company"]["id"]))]
    assert "employee.created" in actions
    assert "employee.setup_token.created" in actions


@pytest.mark.parametrize(
    ("env_name", "expect_debug_token"),
    [
        ("local", True),
        ("test", True),
        ("cloud", False),
        ("staging", False),
        ("gke", False),
        ("prod", False),
        ("production", False),
    ],
)
def test_debug_tokens_are_only_exposed_in_local_or_test_envs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    expect_debug_token: bool,
) -> None:
    boot = _bootstrap(
        client,
        slug=f"debug-{env_name}",
        email=f"owner@debug-{env_name}.example",
    )
    token = str(boot["access_token"])
    monkeypatch.setenv("CASEOPS_ENV", env_name)
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    get_settings.cache_clear()

    created = _create_employee(
        client,
        token,
        email=f"debug-{env_name}@lws5.example",
        full_name=f"Debug {env_name}",
    )
    assert bool(created["setup"]["debug_token"]) is expect_debug_token

    reset_start = client.post(
        "/api/auth/password-reset/start",
        json={
            "company_slug": f"debug-{env_name}",
            "email": f"owner@debug-{env_name}.example",
        },
    )
    assert reset_start.status_code == 200, reset_start.text
    assert bool(reset_start.json()["debug_token"]) is expect_debug_token


def test_account_setup_complete_is_single_use_and_enables_login(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="setup-firm", email="owner@setup.example")
    owner_token = str(boot["access_token"])
    created = _create_employee(
        client,
        owner_token,
        email="setup@lws5.example",
        full_name="Setup User",
    )
    setup_token = created["setup"]["debug_token"]

    weak = client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "weak"},
    )
    assert weak.status_code == 422 or weak.status_code == 400

    complete = client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "SetupPass123!"},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["user"]["email"] == "setup@lws5.example"

    replay = client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "SetupPass123!"},
    )
    assert replay.status_code == 400

    login = client.post(
        "/api/auth/login",
        json={
            "email": "setup@lws5.example",
            "password": "SetupPass123!",
            "company_slug": "setup-firm",
        },
    )
    assert login.status_code == 200, login.text

    actions = [event.action for event in _audit_actions(str(boot["company"]["id"]))]
    assert "employee.account_setup.completed" in actions
    assert "employee.login" in actions


def test_account_setup_token_cannot_reactivate_deactivated_employee(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="deactivated-setup", email="owner@deact.example")
    owner_token = str(boot["access_token"])
    created = _create_employee(
        client,
        owner_token,
        email="deactivated@lws5.example",
        full_name="Deactivated User",
    )
    membership_id = created["employee"]["membership_id"]
    setup_token = created["setup"]["debug_token"]

    deactivate = client.patch(
        f"/api/companies/current/employees/{membership_id}",
        headers=auth_headers(owner_token),
        json={"employment_status": "inactive"},
    )
    assert deactivate.status_code == 200, deactivate.text

    complete = client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "ShouldNotWork123!"},
    )
    assert complete.status_code == 400

    factory = get_session_factory()
    with factory() as session:
        membership = session.scalar(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.user),
                joinedload(CompanyMembership.employee_profile),
            )
            .where(CompanyMembership.id == membership_id)
        )
        assert membership is not None
        assert membership.is_active is False
        assert membership.user.is_active is False
        assert membership.employee_profile is not None
        assert membership.employee_profile.employment_status == "inactive"


def test_employee_directory_filters_and_tenant_scope(client: TestClient) -> None:
    boot_a = _bootstrap(client, slug="dir-a", email="owner@dir-a.example")
    token_a = str(boot_a["access_token"])
    lit = _create_employee(
        client,
        token_a,
        email="litigator@dir.example",
        full_name="Asha Litigator",
        department="Litigation",
    )
    _create_employee(
        client,
        token_a,
        email="finance@dir.example",
        full_name="Finance User",
        role="viewer",
        department="Finance",
    )
    setup = client.post(
        "/api/auth/account-setup/complete",
        json={
            "token": lit["setup"]["debug_token"],
            "password": "Litigator123!",
        },
    )
    assert setup.status_code == 200, setup.text

    boot_b = _bootstrap(client, slug="dir-b", email="owner@dir-b.example")
    token_b = str(boot_b["access_token"])
    other = _create_employee(
        client,
        token_b,
        email="other@dir.example",
        full_name="Other Tenant",
        department="Litigation",
    )

    listing = client.get(
        "/api/companies/current/employees?department=Litigation",
        headers=auth_headers(token_a),
    )
    assert listing.status_code == 200
    emails = {row["email"] for row in listing.json()["employees"]}
    assert "litigator@dir.example" in emails
    assert "other@dir.example" not in emails

    role_filter = client.get(
        "/api/companies/current/employees?role=viewer",
        headers=auth_headers(token_a),
    )
    assert {row["email"] for row in role_filter.json()["employees"]} == {
        "finance@dir.example"
    }

    status_filter = client.get(
        "/api/companies/current/employees?status=active",
        headers=auth_headers(token_a),
    )
    assert "litigator@dir.example" in {
        row["email"] for row in status_filter.json()["employees"]
    }

    q_filter = client.get(
        "/api/companies/current/employees?q=asha",
        headers=auth_headers(token_a),
    )
    assert {row["email"] for row in q_filter.json()["employees"]} == {
        "litigator@dir.example"
    }

    cross_get = client.get(
        f"/api/companies/current/employees/{other['employee']['membership_id']}",
        headers=auth_headers(token_a),
    )
    assert cross_get.status_code == 404


def test_employee_update_reset_and_password_reset_start_are_secure(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="reset-firm", email="owner@reset.example")
    owner_token = str(boot["access_token"])
    created = _create_employee(
        client,
        owner_token,
        email="reset@lws5.example",
        full_name="Reset User",
    )
    membership_id = created["employee"]["membership_id"]
    resend = client.post(
        f"/api/companies/current/employees/{membership_id}/resend-setup",
        headers=auth_headers(owner_token),
    )
    assert resend.status_code == 200, resend.text
    setup_token = resend.json()["debug_token"]
    assert setup_token
    assert client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "Original123!"},
    ).status_code == 200

    patch = client.patch(
        f"/api/companies/current/employees/{membership_id}",
        headers=auth_headers(owner_token),
        json={
            "designation": "Senior Associate",
            "department": "Disputes",
            "employee_code": "RST-001",
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["designation"] == "Senior Associate"

    reset = client.post(
        f"/api/companies/current/employees/{membership_id}/reset-password",
        headers=auth_headers(owner_token),
    )
    assert reset.status_code == 200, reset.text
    reset_token = reset.json()["debug_token"]
    assert reset_token

    factory = get_session_factory()
    with factory() as session:
        hashes = [row.token_hash for row in session.scalars(select(AccountSetupToken))]
        assert reset_token not in hashes

    complete = client.post(
        "/api/auth/password-reset/complete",
        json={"token": reset_token, "password": "ResetPass123!"},
    )
    assert complete.status_code == 200, complete.text
    replay = client.post(
        "/api/auth/password-reset/complete",
        json={"token": reset_token, "password": "ResetPass123!"},
    )
    assert replay.status_code == 400
    old_login = client.post(
        "/api/auth/login",
        json={
            "email": "reset@lws5.example",
            "password": "Original123!",
            "company_slug": "reset-firm",
        },
    )
    assert old_login.status_code == 401

    start_unknown = client.post(
        "/api/auth/password-reset/start",
        json={"company_slug": "reset-firm", "email": "missing@lws5.example"},
    )
    assert start_unknown.status_code == 200
    assert start_unknown.json()["debug_token"] is None

    actions = [event.action for event in _audit_actions(str(boot["company"]["id"]))]
    assert "employee.updated" in actions
    assert "employee.password_reset_token.created" in actions
    assert "employee.password_reset.completed" in actions


def test_password_reset_token_consume_is_atomic_under_parallel_use(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = _bootstrap(client, slug="atomic-reset", email="owner@atomic.example")
    owner_token = str(boot["access_token"])
    created = _create_employee(
        client,
        owner_token,
        email="atomic@lws5.example",
        full_name="Atomic Reset",
    )
    setup_token = created["setup"]["debug_token"]
    assert client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "Original123!"},
    ).status_code == 200

    reset = client.post(
        f"/api/companies/current/employees/{created['employee']['membership_id']}/reset-password",
        headers=auth_headers(owner_token),
    )
    assert reset.status_code == 200, reset.text
    reset_token = reset.json()["debug_token"]

    original_utcnow = employee_service._utcnow
    barrier = threading.Barrier(2)
    gate_lock = threading.Lock()
    remaining_gate_calls = 2

    def gated_utcnow() -> datetime:
        nonlocal remaining_gate_calls
        if threading.current_thread().name.startswith("token-consume"):
            should_wait = False
            with gate_lock:
                if remaining_gate_calls > 0:
                    remaining_gate_calls -= 1
                    should_wait = True
            if should_wait:
                barrier.wait(timeout=5)
        return original_utcnow()

    monkeypatch.setattr(employee_service, "_utcnow", gated_utcnow)
    factory = get_session_factory()
    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        with factory() as session:
            try:
                employee_service.complete_password_reset(
                    session,
                    payload=AccountSetupCompleteRequest(
                        token=reset_token,
                        password="ParallelReset123!",
                    ),
                )
                outcome = "ok"
            except Exception as exc:  # noqa: BLE001 - asserting one generic failure
                outcome = f"error:{type(exc).__name__}"
            with results_lock:
                results.append(outcome)

    threads = [
        threading.Thread(target=worker, name=f"token-consume-{index}")
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert results.count("ok") == 1
    assert len(results) == 2


def test_employee_role_guards_manager_tenant_and_token_expiry(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, slug="guard-a", email="owner@guard-a.example")
    owner_a = str(boot_a["access_token"])
    boot_b = _bootstrap(client, slug="guard-b", email="owner@guard-b.example")
    owner_b = str(boot_b["access_token"])
    other = _create_employee(
        client,
        owner_b,
        email="manager@other.example",
        full_name="Other Manager",
    )

    bad_manager = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(owner_a),
        json={
            "full_name": "Bad Manager Ref",
            "email": "bad-manager@guard.example",
            "role": "member",
            "manager_membership_id": other["employee"]["membership_id"],
        },
    )
    assert bad_manager.status_code == 400

    member = _create_employee(
        client,
        owner_a,
        email="member@guard.example",
        full_name="Plain Member",
    )
    setup_token = member["setup"]["debug_token"]
    assert client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": "MemberPass123!"},
    ).status_code == 200
    member_login = client.post(
        "/api/auth/login",
        json={
            "email": "member@guard.example",
            "password": "MemberPass123!",
            "company_slug": "guard-a",
        },
    )
    member_token = member_login.json()["access_token"]
    forbidden = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(member_token),
        json={
            "full_name": "Blocked",
            "email": "blocked@guard.example",
            "role": "member",
        },
    )
    assert forbidden.status_code == 403

    expiring = _create_employee(
        client,
        owner_a,
        email="expired@guard.example",
        full_name="Expired Token",
    )
    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(AccountSetupToken).where(
                AccountSetupToken.membership_id
                == expiring["employee"]["membership_id"]
            )
        )
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
    expired = client.post(
        "/api/auth/account-setup/complete",
        json={
            "token": expiring["setup"]["debug_token"],
            "password": "ExpiredPass123!",
        },
    )
    assert expired.status_code == 400


def test_employee_matter_access_lists_every_matter_with_grant_state(client: TestClient) -> None:
    """BUG-048 (Hari 2026-05-11): admin matter-access fan-out endpoint.

    Verifies GET /api/companies/current/employees/{id}/matter-access
    returns one row per matter in the caller's company, with the
    correct restricted_access / has_grant / is_assignee / is_walled
    flags. Also verifies cross-tenant isolation (a different
    company's matters never leak in) and the membership-not-found
    404.
    """
    owner = _bootstrap(client, slug="bug048-a", email="owner@bug048a.example")
    owner_token = owner["access_token"]

    member = _create_employee(
        client,
        owner_token,
        email="member@bug048a.example",
        full_name="Matter Access Member",
    )
    membership_id = member["employee"]["membership_id"]

    # Two matters in this company: one open, one restricted-with-grant.
    open_matter = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Open matter",
            "matter_code": "B48-OPEN",
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert open_matter.status_code == 200, open_matter.text
    open_matter_id = open_matter.json()["id"]

    restricted_matter = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Restricted matter",
            "matter_code": "B48-RES",
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert restricted_matter.status_code == 200, restricted_matter.text
    restricted_matter_id = restricted_matter.json()["id"]

    restrict_resp = client.post(
        f"/api/matters/{restricted_matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restrict_resp.status_code == 200, restrict_resp.text

    grant_resp = client.post(
        f"/api/matters/{restricted_matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": membership_id, "access_level": "member"},
    )
    assert grant_resp.status_code == 200, grant_resp.text

    # Fan-out: every matter shows up with the right flags.
    fanout = client.get(
        f"/api/companies/current/employees/{membership_id}/matter-access",
        headers=auth_headers(owner_token),
    )
    assert fanout.status_code == 200, fanout.text
    body = fanout.json()
    assert body["membership_id"] == membership_id
    matters_by_id = {m["matter_id"]: m for m in body["matters"]}
    assert open_matter_id in matters_by_id
    assert restricted_matter_id in matters_by_id

    open_row = matters_by_id[open_matter_id]
    assert open_row["restricted_access"] is False
    assert open_row["has_grant"] is False
    assert open_row["is_walled"] is False

    restricted_row = matters_by_id[restricted_matter_id]
    assert restricted_row["restricted_access"] is True
    assert restricted_row["has_grant"] is True
    assert restricted_row["grant_id"] is not None
    assert restricted_row["is_walled"] is False

    # Cross-tenant isolation: a second company's matters never leak in.
    other = _bootstrap(client, slug="bug048-b", email="owner@bug048b.example")
    other_token = other["access_token"]
    other_matter = client.post(
        "/api/matters/",
        headers=auth_headers(other_token),
        json={
            "title": "Other tenant matter",
            "matter_code": "B48-OTHER",
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert other_matter.status_code == 200, other_matter.text
    other_matter_id = other_matter.json()["id"]

    fanout_again = client.get(
        f"/api/companies/current/employees/{membership_id}/matter-access",
        headers=auth_headers(owner_token),
    )
    assert fanout_again.status_code == 200, fanout_again.text
    leaked_ids = {m["matter_id"] for m in fanout_again.json()["matters"]}
    assert other_matter_id not in leaked_ids

    # 404 on unknown membership id (same tenant scope).
    missing = client.get(
        "/api/companies/current/employees/00000000-0000-0000-0000-000000000000/matter-access",
        headers=auth_headers(owner_token),
    )
    assert missing.status_code == 404, missing.text
