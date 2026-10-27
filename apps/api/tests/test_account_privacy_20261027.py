"""Real synthetic HTTP intake; received is not erased, sent or fulfilled."""

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.console_auth import create_console_token
from caseops_api.core.security import create_portal_session_token
from caseops_api.db.models import (
    AccountDeletionRequest,
    AuditEvent,
    Company,
    CompanyMembership,
    MembershipRole,
    NativeDeviceSession,
    PlatformAdminAuditEvent,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import account_privacy
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_native_auth_20261024 import _browser, _device, _headers

forbid_unadmitted_network = _forbid_unadmitted_network
BASE = "/api/account/deletion-requests"
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
PASSWORD = "SyntheticAccountPass123!"
ACTION = "account.deletion_request_received"


def boot(client):
    slug = "privacy-" + uuid4().hex[:12]
    response = client.post(
        "/api/bootstrap/company",
        headers=MARKER,
        json={
            "company_name": "Synthetic privacy workspace",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Synthetic requester",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    auth = response.json()
    auth["headers"] = {**MARKER, "Authorization": "Bearer " + auth["access_token"]}
    return auth


def payload(operation_id=None):
    return {
        "operation_id": operation_id or str(uuid4()),
        "confirmation": "request_account_deletion",
    }


def snapshot():
    with get_session_factory()() as session:
        rows = [
            dict(row)
            for row in session.execute(
                select(AccountDeletionRequest.__table__).order_by(AccountDeletionRequest.id)
            ).mappings()
        ]
        private_audits = [
            dict(row)
            for row in session.execute(
                select(PlatformAdminAuditEvent.__table__)
                .where(PlatformAdminAuditEvent.action == ACTION)
                .order_by(PlatformAdminAuditEvent.id)
            ).mappings()
        ]
        tenant_audits = [
            dict(row)
            for row in session.execute(
                select(
                    AuditEvent.id,
                    AuditEvent.company_id,
                    AuditEvent.actor_membership_id,
                    AuditEvent.action,
                    AuditEvent.target_id,
                    AuditEvent.metadata_json,
                    AuditEvent.created_at,
                )
                .where(AuditEvent.action == ACTION)
                .order_by(AuditEvent.id)
            ).mappings()
        ]
        return {
            "requests": rows,
            "private_audits": private_audits,
            "tenant_audits": tenant_audits,
            "users": session.scalar(select(func.count()).select_from(User)),
            "companies": session.scalar(select(func.count()).select_from(Company)),
        }


def assert_receipt(body):
    assert set(body) == {
        "id",
        "operation_id",
        "request_type",
        "status",
        "requested_at",
        "deletion_completed",
    }
    assert body["request_type"] == "account_deletion" and body["status"] == "received"
    assert body["deletion_completed"] is False
    stamp = datetime.fromisoformat(body["requested_at"].replace("Z", "+00:00"))
    assert stamp.utcoffset() == timedelta(0)
    return body


def assert_private_audit(retained, *, receipt, user_id, membership_id):
    assert retained["tenant_audits"] == []
    assert len(retained["private_audits"]) == 1
    event = retained["private_audits"][0]
    assert set(event) == {
        "id",
        "platform_admin_id",
        "actor_user_id",
        "actor_membership_id",
        "company_id",
        "action",
        "target_type",
        "target_id",
        "result",
        "reason",
        "metadata_json",
        "created_at",
    }
    assert event["id"] and event["created_at"] is not None
    assert event["platform_admin_id"] is None and event["company_id"] is None
    assert event["actor_user_id"] == user_id
    assert event["actor_membership_id"] == membership_id
    assert event["action"] == "account.deletion_request_received"
    assert event["target_type"] == "account_deletion_request"
    assert event["target_id"] == receipt["id"]
    assert event["result"] == "success" and event["reason"] is None
    assert event["metadata_json"] == {
        "request_type": "account_deletion",
        "status": "received",
        "deletion_completed": False,
    }


def roundtrip(client):
    auth = boot(client)
    before = snapshot()
    assert client.get(BASE, headers=auth["headers"]).json() == {"request": None}
    data = payload()
    created = client.post(BASE, headers=auth["headers"], json=data)
    assert created.status_code == 202, created.text
    receipt = assert_receipt(created.json())
    assert receipt["operation_id"] == data["operation_id"]
    assert created.headers["cache-control"] == "no-store"
    retained = snapshot()
    assert len(retained["requests"]) == 1
    assert_private_audit(
        retained,
        receipt=receipt,
        user_id=auth["user"]["id"],
        membership_id=auth["membership"]["id"],
    )
    assert retained["users"] == before["users"] and retained["companies"] == before["companies"]
    row = retained["requests"][0]
    assert row["subject_user_id"] == auth["user"]["id"]
    assert row["submitted_from_company_id"] == auth["company"]["id"]
    assert row["submitted_by_membership_id"] == auth["membership"]["id"]
    assert row["submitted_realm"] == "tenant_web"
    for _ in range(2):
        replay = client.post(BASE, headers=auth["headers"], json=data)
        assert replay.status_code == 202 and replay.json() == receipt
        read = client.get(BASE + "/" + receipt["id"], headers=auth["headers"])
        assert read.status_code == 200 and read.json() == receipt
        assert read.headers["cache-control"] == "no-store"
        assert client.get(BASE, headers=auth["headers"]).json() == {"request": receipt}
        assert snapshot() == retained
    conflict = client.post(BASE, headers=auth["headers"], json=payload())
    assert (
        conflict.status_code == 409
        and conflict.json()["code"] == "account_deletion_request_pending"
    )
    assert snapshot() == retained
    with get_session_factory()() as session:
        assert session.get(User, auth["user"]["id"]).is_active is True
        assert session.get(CompanyMembership, auth["membership"]["id"]).is_active is True
    return auth, receipt


def test_received_receipt_persists_and_exact_replay_is_byte_stable(client):
    roundtrip(client)


def tenant_export_privacy(client):
    owner = boot(client)
    created = client.post(
        "/api/companies/current/users",
        headers=owner["headers"],
        json={
            "full_name": "Synthetic private requester",
            "email": f"requester-{uuid4().hex}@privacy.example.com",
            "password": PASSWORD,
            "role": "viewer",
        },
    )
    assert created.status_code == 200, created.text
    member = created.json()
    login = client.post(
        "/api/auth/login",
        headers=MARKER,
        json={
            "company_slug": owner["company"]["slug"],
            "email": member["email"],
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    headers = {**MARKER, "Authorization": "Bearer " + login.json()["access_token"]}
    data = payload()
    response = client.post(BASE, headers=headers, json=data)
    assert response.status_code == 202, response.text
    receipt = assert_receipt(response.json())
    retained = snapshot()
    # The shared HTTPS client retains the requester's login cookie. Remove it
    # before probing a different principal's Bearer credential; cookies retain
    # their normal authentication precedence in the application.
    client.cookies.clear()
    # A real, non-subject owner reaches the capability-protected exporter and
    # sees an independently admitted normal tenant event, not a 403/empty fake.
    for format_name in ("jsonl", "csv"):
        exported = client.get(
            "/api/admin/audit/export",
            headers=owner["headers"],
            params={"format": format_name},
        )
        assert exported.status_code == 200, exported.text
        rows = (
            [json.loads(line) for line in exported.text.splitlines() if line]
            if format_name == "jsonl"
            else list(csv.DictReader(io.StringIO(exported.text)))
        )
        assert any(
            row["action"] == "company_user.created"
            and row["target_id"] == member["membership_id"]
            for row in rows
        )
        assert not any(row["action"] == ACTION for row in rows)
        assert receipt["id"] not in exported.text
        assert receipt["operation_id"] not in exported.text
        assert "account_deletion_request" not in exported.text
        filtered = client.get(
            "/api/admin/audit/export",
            headers=owner["headers"],
            params={"format": format_name, "action": ACTION},
        )
        assert filtered.status_code == 200, filtered.text
        if format_name == "jsonl":
            assert filtered.content == b""
        else:
            assert list(csv.DictReader(io.StringIO(filtered.text))) == []
    assert_private_audit(
        retained,
        receipt=receipt,
        user_id=member["user_id"],
        membership_id=member["membership_id"],
    )
    assert client.get(BASE, headers=owner["headers"]).json() == {"request": None}
    assert client.get(BASE + "/" + receipt["id"], headers=owner["headers"]).status_code == 404
    assert client.get(BASE, headers=headers).json() == {"request": receipt}
    assert client.get(BASE + "/" + receipt["id"], headers=headers).json() == receipt
    replay = client.post(BASE, headers=headers, json=data)
    assert replay.status_code == 202 and replay.json() == receipt
    assert snapshot() == retained


def test_global_self_request_is_private_from_real_tenant_owner_audit_exports(client):
    tenant_export_privacy(client)


def postcommit_acknowledgement_failure(client, monkeypatch):
    auth = boot(client)
    data = payload()
    original = account_privacy.submit_deletion_request

    def lost_response(session, **kwargs):
        original(session, **kwargs)
        raise RuntimeError("synthetic postcommit response failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(account_privacy, "submit_deletion_request", lost_response)
        raw = TestClient(client.app, raise_server_exceptions=False)
        try:
            response = raw.post(BASE, headers=auth["headers"], json=data)
        finally:
            raw.close()
    assert response.status_code == 500, response.text
    current = client.get(BASE, headers=auth["headers"])
    assert current.status_code == 200, current.text
    receipt = assert_receipt(current.json()["request"])
    assert receipt["operation_id"] == data["operation_id"]
    retained = snapshot()
    assert len(retained["requests"]) == 1
    assert_private_audit(
        retained,
        receipt=receipt,
        user_id=auth["user"]["id"],
        membership_id=auth["membership"]["id"],
    )
    read = client.get(BASE + "/" + receipt["id"], headers=auth["headers"])
    assert read.status_code == 200 and read.json() == receipt
    replay = client.post(BASE, headers=auth["headers"], json=data)
    assert replay.status_code == 202 and replay.json() == receipt
    assert snapshot() == retained


def test_postcommit_response_failure_retains_own_receipt_and_single_private_audit(
    client, monkeypatch
):
    postcommit_acknowledgement_failure(client, monkeypatch)


def native_roundtrip(client):
    auth, browser = _browser(client)
    device = _device(client, browser)
    headers = {**MARKER, **_headers(device)}
    data = payload()
    response = client.post(BASE, headers=headers, json=data)
    assert response.status_code == 202, response.text
    receipt = assert_receipt(response.json())
    with get_session_factory()() as session:
        row = session.scalar(select(AccountDeletionRequest))
        assert row.subject_user_id == auth["user"]["id"] and row.submitted_realm == "native"
    assert client.get(BASE, headers=headers).json() == {"request": receipt}
    revoked = client.delete("/api/auth/native/sessions/" + device["session_id"], headers=headers)
    assert revoked.status_code == 204, revoked.text
    retained = snapshot()
    assert client.post(BASE, headers=headers, json=data).status_code == 401
    assert client.get(BASE, headers=headers).status_code == 401
    assert snapshot() == retained


def test_actual_native_session_requests_self_and_revocation_still_fences_it(client):
    native_roundtrip(client)


def self_scope(client):
    first, receipt = roundtrip(client)
    other = boot(client)
    before = snapshot()
    assert client.get(BASE, headers=other["headers"]).json() == {"request": None}
    assert client.get(BASE + "/" + receipt["id"], headers=other["headers"]).status_code == 404
    assert snapshot() == before
    # A valid shared User/membership fixture models an existing multi-workspace
    # identity; actual normal login, never a minted synthetic tenant credential,
    # must establish the second workspace's session.
    with get_session_factory()() as session:
        session.add(
            CompanyMembership(
                company_id=other["company"]["id"], user_id=first["user"]["id"], role="viewer"
            )
        )
        session.commit()
    logged = client.post(
        "/api/auth/login",
        headers=MARKER,
        json={
            "email": first["user"]["email"],
            "password": PASSWORD,
            "company_slug": other["company"]["slug"],
        },
    )
    assert logged.status_code == 200, logged.text
    shared = {**MARKER, "Authorization": "Bearer " + logged.json()["access_token"]}
    stable = snapshot()
    read = client.get(BASE, headers=shared)
    assert read.status_code == 200 and read.json() == {"request": receipt}
    assert (
        client.post(BASE, headers=shared, json=payload(receipt["operation_id"])).json() == receipt
    )
    assert client.post(BASE, headers=shared, json=payload()).status_code == 409
    assert snapshot() == stable
    assert first["company"]["id"] not in read.text
    assert first["membership"]["id"] not in read.text
    assert first["company"]["name"] not in read.text


def test_global_subject_one_request_across_own_workspaces_no_foreign_routing_disclosure(client):
    self_scope(client)


@pytest.mark.parametrize("role", [role.value for role in MembershipRole])
def test_every_tenant_role_may_request_only_its_own_identity(client, role):
    assert role in {value.value for value in MembershipRole}
    owner = boot(client)
    if role == "owner":
        # Bootstrap is the real supported owner-creation path. The employee
        # creation DTO deliberately excludes creating another owner.
        headers, subject = owner["headers"], owner["user"]["id"]
        other = boot(client)
    else:
        created = client.post(
            "/api/companies/current/users",
            headers=owner["headers"],
            json={
                "full_name": "Synthetic self requester",
                "email": f"self-{role}@privacy.example.com",
                "password": PASSWORD,
                "role": role,
            },
        )
        assert created.status_code == 200, created.text
        member = created.json()
        auth = client.post(
            "/api/auth/login",
            headers=MARKER,
            json={
                "company_slug": owner["company"]["slug"],
                "email": member["email"],
                "password": PASSWORD,
            },
        )
        assert auth.status_code == 200, auth.text
        headers = {**MARKER, "Authorization": "Bearer " + auth.json()["access_token"]}
        subject, other = member["user_id"], owner
    response = client.post(BASE, headers=headers, json=payload())
    assert response.status_code == 202, response.text
    receipt = assert_receipt(response.json())
    assert client.get(BASE, headers=other["headers"]).json() == {"request": None}
    assert client.get(BASE + "/" + receipt["id"], headers=other["headers"]).status_code == 404
    with get_session_factory()() as session:
        assert session.scalar(select(AccountDeletionRequest.subject_user_id)) == subject


@pytest.mark.parametrize(
    "change",
    [
        "missing_confirmation",
        "false_confirmation",
        "extra_subject",
        "extra_company",
        "extra_status",
        "extra_details",
        "bad_uuid",
        "nil_uuid",
        "oversize_uuid",
    ],
)
def test_bounded_fixed_confirmation_has_no_caller_identity_or_freeform_pii(client, change):
    auth = boot(client)
    body = payload()
    if change == "missing_confirmation":
        body.pop("confirmation")
    elif change == "false_confirmation":
        body["confirmation"] = False
    elif change == "extra_subject":
        body["subject_user_id"] = str(uuid4())
    elif change == "extra_company":
        body["company_id"] = str(uuid4())
    elif change == "extra_status":
        body["status"] = "completed"
    elif change == "extra_details":
        body["details"] = "SYNTHETIC_PRIVATE_DETAILS"
    elif change == "bad_uuid":
        body["operation_id"] = "not-a-uuid"
    elif change == "nil_uuid":
        body["operation_id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "oversize_uuid":
        body["operation_id"] = "x" * 1000
    else:
        raise AssertionError("unsupported fixture target")
    before = snapshot()
    response = client.post(BASE, headers=auth["headers"], json=body)
    assert response.status_code == 422, response.text
    assert "SYNTHETIC_PRIVATE_DETAILS" not in response.text
    assert snapshot() == before


@pytest.mark.parametrize("realm", ["missing", "portal", "report", "invalid"])
def test_other_realms_cannot_acquire_self_request_authority(client, realm):
    owner = boot(client)
    client.cookies.clear()
    headers = dict(MARKER)
    now = datetime.now(UTC)
    if realm == "portal":
        token = create_portal_session_token(
            portal_user_id=str(uuid4()), company_id=owner["company"]["id"], role="client"
        )
    elif realm == "report":
        token = create_console_token(
            user_id=owner["user"]["id"],
            admin_id=str(uuid4()),
            secret="synthetic-realm-secret",
            purpose="authenticated",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
    elif realm == "invalid":
        token = "invalid-synthetic-token"
    elif realm == "missing":
        token = None
    else:
        raise AssertionError("unsupported fixture realm")
    if token:
        headers["Authorization"] = "Bearer " + token
    before = snapshot()
    assert client.post(BASE, headers=headers, json=payload()).status_code in {401, 403}
    assert client.get(BASE, headers=headers).status_code == 401
    assert snapshot() == before


def test_actual_cookie_wins_over_other_tenant_bearer_and_native_mixed_realm_is_rejected(client):
    a = boot(client)
    b = boot(client)
    body = payload()
    # A separate raw client intentionally bypasses the suite's bearer-cookie
    # isolation adapter to exercise the real canonical cookie-first boundary.
    with TestClient(client.app) as raw:
        cookie = f"caseops_session={b['access_token']}"
        response = raw.post(
            BASE,
            headers={**MARKER, "Cookie": cookie, "Authorization": "Bearer " + a["access_token"]},
            json=body,
        )
        assert response.status_code == 202, response.text
    with get_session_factory()() as session:
        assert session.scalar(select(AccountDeletionRequest.subject_user_id)) == b["user"]["id"]
    auth, browser = _browser(client)
    device = _device(client, browser)
    retained = snapshot()
    with TestClient(client.app) as raw:
        response = raw.post(
            BASE,
            headers={
                **MARKER,
                **_headers(device),
                "Cookie": f"caseops_session={auth['access_token']}",
            },
            json=payload(),
        )
        assert response.status_code == 401, response.text
    assert snapshot() == retained


def concurrent_submission(client, monkeypatch, *, same_operation):
    auth = boot(client)
    data = payload()
    held, entered_second, release = Event(), Event(), Event()
    gate = Lock()
    calls = [0]
    original_submit, original_own = account_privacy.submit_deletion_request, account_privacy._own

    def submit(session, **kwargs):
        with gate:
            calls[0] += 1
            if calls[0] == 2:
                entered_second.set()
        return original_submit(session, **kwargs)

    def own(session, user_id):
        if not held.is_set():
            held.set()
            assert release.wait(5), "test release missing"
        return original_own(session, user_id)

    monkeypatch.setattr(account_privacy, "submit_deletion_request", submit)
    monkeypatch.setattr(account_privacy, "_own", own)

    def invoke(body):
        # The parent fixture already owns application lifespan; separate HTTP
        # clients avoid cookie-jar sharing without replaying startup seed work.
        raw = TestClient(client.app)
        try:
            return raw.post(BASE, headers=auth["headers"], json=body)
        finally:
            raw.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, data)
        second = None
        try:
            if not held.wait(5):
                if first.done():
                    first.result()
                raise AssertionError("first request did not reach its lookup fence")
            second = pool.submit(invoke, data if same_operation else payload())
            if not entered_second.wait(5):
                if second.done():
                    second.result()
                raise AssertionError("second request did not enter authenticated handler")
            assert not first.done()
            if second.done():
                second.result()
                raise AssertionError("second submission bypassed the held identity writer fence")
        finally:
            release.set()
        one, two = first.result(timeout=10), second.result(timeout=10)
    assert one.status_code == 202, one.text
    assert two.status_code == (202 if same_operation else 409), two.text
    if same_operation:
        assert one.json() == two.json()
    retained = snapshot()
    assert len(retained["requests"]) == len(retained["private_audits"]) == 1
    assert retained["tenant_audits"] == []


@pytest.mark.parametrize("same_operation", [True, False])
def test_overlapping_actual_http_submissions_serialize_without_duplicate_audit(
    client, monkeypatch, same_operation
):
    concurrent_submission(client, monkeypatch, same_operation=same_operation)


def test_native_revocation_between_advisory_context_and_service_fence_denies_without_row(
    client, monkeypatch
):
    _, browser = _browser(client)
    device = _device(client, browser)
    original = account_privacy.submit_deletion_request

    def revoked(session, *, context, payload):
        with get_session_factory()() as concurrent:
            row = concurrent.get(NativeDeviceSession, device["session_id"])
            row.revoked_at = datetime.now(UTC)
            concurrent.commit()
        return original(session, context=context, payload=payload)

    monkeypatch.setattr(account_privacy, "submit_deletion_request", revoked)
    response = client.post(BASE, headers={**MARKER, **_headers(device)}, json=payload())
    assert response.status_code == 401, response.text
    retained = snapshot()
    assert retained["requests"] == retained["private_audits"] == retained["tenant_audits"] == []
