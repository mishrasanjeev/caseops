"""MOB-39-CONDUCT-03/04/05. Private reports and current-authority intake."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import delete, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    PlatformAdminAuditEvent,
    PlatformAdminMembership,
    UserMFAStepUp,
    WorkspaceConductReport,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import workspace_conduct_reports
from tests.test_native_auth_20261024 import _browser, _device, _headers
from tests.test_p0_paid_production_safety import _current_totp
from tests.test_workspace_conduct_20261108 import PATH, _matter, _note, _upload

REPORTS = "/api/account/workspace-conduct/reports"
WORKSPACE = "/api/admin/workspace-conduct/reports"
PUBLISHER = "/api/platform-admin/workspace-conduct-reports"


def _member(client, owner, auth, *, role):
    email = f"conduct-{uuid4()}@example.com"
    password = "SyntheticConduct123!"
    invited = client.post("/api/companies/current/users", headers=owner, json={
        "full_name": "Synthetic report member", "email": email, "password": password, "role": role,
    })
    assert invited.status_code == 200, invited.text
    logged_in = client.post("/api/auth/login", json={
        "company_slug": auth["company"]["slug"], "email": email, "password": password,
    })
    assert logged_in.status_code == 200, logged_in.text
    csrf = client.cookies.get("caseops_csrf")
    client.cookies.clear()
    browser = {
        "Cookie": f"caseops_session={logged_in.json()['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }
    return invited.json()["membership_id"], browser, _headers(_device(client, browser))


def _payload(kind, matter, item, *, membership=None, source_kind=None):
    target = {"kind": kind, "matter_id": matter, "item_id": item}
    if membership is not None:
        target.update(membership_id=membership, source_kind=source_kind)
    return {"operation_id": str(uuid4()), "reason": "harassment_threats", "target": target}


def _receipt(client, headers, payload):
    response = client.post(REPORTS, headers=headers, json=payload)
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "id": response.json()["id"],
        "operation_id": payload["operation_id"],
        "received_at": response.json()["received_at"],
        "status": "received",
    }
    assert response.json()["received_at"].endswith("Z")
    return response


def test_reported_note_file_and_author_require_exact_current_visible_provenance(client):
    auth, owner = _browser(client)
    reporter_id, reporter_web, reporter = _member(client, owner, auth, role="member")
    author_id, author, author_native = _member(client, owner, auth, role="member")
    matter = _matter(client, owner)
    matter_id, version = matter["id"], matter["lifecycle_version"]
    note = _note(client, author, matter_id, version, body="Sensitive synthetic fixture note")
    attachment = _upload(client, author, matter_id, version)
    assert note.status_code == attachment.status_code == 200, [note.text, attachment.text]
    note_id, file_id = note.json()["id"], attachment.json()["id"]
    assert note.json()["author_membership_id"] == author_id
    assert attachment.json()["uploaded_by_membership_id"] == author_id
    assert client.get(PATH, headers=reporter).json()["accepted_at"] is None

    note_payload = _payload("note", matter_id, note_id)
    note_receipt = _receipt(client, reporter, note_payload)
    replay = _receipt(client, reporter, note_payload)
    assert replay.content == note_receipt.content
    changed_reason = {**note_payload, "reason": "other"}
    conflict = client.post(REPORTS, headers=reporter, json=changed_reason)
    assert conflict.status_code == 409
    assert conflict.json()["type"] == "workspace_conduct_report_operation_conflict"
    file_receipt = _receipt(client, reporter, _payload("file", matter_id, file_id))
    user_payload = _payload("user", matter_id, note_id, membership=author_id, source_kind="note")
    user_receipt = _receipt(client, reporter, user_payload)
    expected_receipts = {
        receipt.json()["id"] for receipt in (note_receipt, file_receipt, user_receipt)
    }

    unknown_item = _payload("note", matter_id, str(uuid4()))
    opaque = client.post(REPORTS, headers=reporter, json=unknown_item)
    assert opaque.status_code == 404
    opaque_body = opaque.json()
    request_id = opaque_body.pop("request_id")
    assert request_id
    web_denied = client.post(REPORTS, headers=reporter_web, json=note_payload)
    assert web_denied.status_code == 403
    free_text_denied = client.post(REPORTS, headers=reporter, json={
        **note_payload, "target": {**note_payload["target"], "body": "Synthetic free text"},
    })
    assert free_text_denied.status_code == 422
    unbound_user_denied = client.post(REPORTS, headers=reporter, json={
        "operation_id": str(uuid4()), "reason": "other",
        "target": {"kind": "user", "membership_id": author_id},
    })
    assert unbound_user_denied.status_code == 422
    for forged in (
        _payload("note", str(uuid4()), note_id),
        _payload("file", matter_id, note_id),
        _payload("user", matter_id, note_id, membership=reporter_id, source_kind="note"),
        _payload("user", matter_id, file_id, membership=author_id, source_kind="note"),
    ):
        response = client.post(REPORTS, headers=reporter, json=forged)
        assert response.status_code == 404
        body = response.json()
        request_id = body.pop("request_id")
        assert request_id
        assert body == opaque_body

    wall = client.post(f"/api/matters/{matter_id}/access/walls", headers=owner, json={
        "excluded_membership_id": reporter_id, "reason": "Synthetic report scope",
    })
    assert wall.status_code == 200, wall.text
    for payload in (note_payload, user_payload, _payload("file", matter_id, file_id)):
        denied = client.post(REPORTS, headers=reporter, json=payload)
        assert denied.status_code == 404
        body = denied.json()
        request_id = body.pop("request_id")
        assert request_id
        assert body == opaque_body

    # Reports do not change the target's access. The existing explicit owner
    # action cuts it off while keeping the legal note and attachment readable
    # by a separate already-authorized workspace user.
    workspace = f"/api/matters/{matter_id}/workspace"
    assert client.get(workspace, headers=author_native).status_code == 200
    disabled = client.patch(
        f"/api/companies/current/users/{author_id}", headers=owner, json={"is_active": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["membership_active"] is False
    assert client.get(workspace, headers=author_native).status_code in (401, 403)
    owner_view = client.get(workspace, headers=owner)
    assert owner_view.status_code == 200
    assert any(row["id"] == note_id for row in owner_view.json()["notes"])
    assert any(row["id"] == file_id for row in owner_view.json()["attachments"])
    with get_session_factory()() as session:
        rows = session.scalars(select(WorkspaceConductReport)).all()
        assert {row.id for row in rows} == expected_receipts
        assert {row.reporter_membership_id for row in rows} == {reporter_id}
        assert {row.target_membership_id for row in rows} == {author_id}
        assert {row.routing for row in rows} == {"workspace"}
        assert {row.source_item_id for row in rows} == {note_id, file_id}


def test_operator_intake_paginates_opaque_metadata_and_escalates_admins(client, monkeypatch):
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    auth, owner = _browser(client)
    _reporter_id, reporter_web, reporter = _member(client, owner, auth, role="member")
    member_id, member, _native = _member(client, owner, auth, role="member")
    admin_id, admin, _native_admin = _member(client, owner, auth, role="admin")
    matter = _matter(client, owner)
    matter_id, version = matter["id"], matter["lifecycle_version"]
    member_note = _note(client, member, matter_id, version)
    admin_note = _note(client, admin, matter_id, version)
    owner_note = _note(client, owner, matter_id, version)
    assert [r.status_code for r in (member_note, admin_note, owner_note)] == [200, 200, 200]
    member_note_id = member_note.json()["id"]
    first = _receipt(client, reporter, _payload("note", matter_id, member_note_id)).json()["id"]
    second = _receipt(client, reporter, _payload(
        "user", matter_id, member_note_id, membership=member_id, source_kind="note",
    )).json()["id"]
    escalated = _receipt(client, reporter, _payload(
        "note", matter_id, admin_note.json()["id"],
    )).json()["id"]
    owner_report = _receipt(client, reporter, _payload(
        "note", matter_id, owner_note.json()["id"],
    )).json()["id"]

    page = client.get(WORKSPACE, headers=owner, params={"limit": 1})
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    first_page = page.json()
    assert len(first_page["reports"]) == 1
    next_page = client.get(
        WORKSPACE, headers=owner, params={"limit": 1, "after": first_page["next_cursor"]},
    )
    assert next_page.status_code == 200, next_page.text
    assert next_page.json()["next_cursor"] is None
    workspace_rows = first_page["reports"] + next_page.json()["reports"]
    assert {row["id"] for row in workspace_rows} == {first, second}
    for row in workspace_rows:
        assert set(row) == {
            "id", "company_id", "target_membership_id", "target_kind", "reason", "received_at",
        }
        assert row["target_membership_id"] == member_id
        assert row["company_id"] == auth["company"]["id"]
    for browser in (reporter_web, member, admin):
        assert client.get(WORKSPACE, headers=browser).status_code == 403
        assert client.get(PUBLISHER, headers=browser).status_code == 403
    assert client.get(WORKSPACE, headers=_headers(_device(client, owner))).status_code == 403
    assert client.get(WORKSPACE, headers=owner, params={"after": escalated}).status_code == 404

    other = client.post("/api/bootstrap/company", json={
        "company_name": "Synthetic other tenant", "company_slug": "other-report-company",
        "company_type": "law_firm", "owner_full_name": "Other synthetic owner",
        "owner_email": "other-report-owner@example.com", "owner_password": "OtherReport123!",
    })
    assert other.status_code == 200, other.text
    csrf = client.cookies.get("caseops_csrf")
    client.cookies.clear()
    other_owner = {
        "Cookie": f"caseops_session={other.json()['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }
    other_native = _headers(_device(client, other_owner))
    assert client.get(WORKSPACE, headers=other_owner).json() == {"reports": [], "next_cursor": None}
    assert client.get(WORKSPACE, headers=other_owner, params={"after": first}).status_code == 404
    foreign_report = client.post(
        REPORTS, headers=other_native, json=_payload("note", matter_id, member_note_id),
    )
    assert foreign_report.status_code == 404

    # The existing platform MFA fence applies to the new endpoint. Synthetic
    # enrolment and step-up exercise real auth APIs without changing policy.
    enrolled = client.post("/api/auth/mfa/enroll", headers=owner)
    assert enrolled.status_code == 200, enrolled.text
    secret = enrolled.json()["secret"]
    verified = client.post(
        "/api/auth/mfa/enroll/verify", headers=owner, json={"code": _current_totp(secret)},
    )
    assert verified.status_code == 200, verified.text
    with get_session_factory()() as session:
        platform = session.scalar(select(PlatformAdminMembership))
        platform.mfa_enforced_at = datetime.now(UTC) - timedelta(minutes=1)
        session.execute(delete(UserMFAStepUp))
        session.commit()
    denied = client.get(PUBLISHER, headers=owner)
    assert denied.status_code == 403 and denied.json()["type"] == "step_up_required"
    stepped_up = client.post("/api/auth/mfa/step-up", headers=owner, json={
        "code": _current_totp(secret), "purpose": "platform_admin_access",
    })
    assert stepped_up.status_code == 200, stepped_up.text
    publisher = client.get(PUBLISHER, headers=owner)
    assert publisher.status_code == 200, publisher.text
    assert publisher.headers["cache-control"] == "no-store"
    assert [row["id"] for row in publisher.json()["reports"]] == [escalated]
    assert publisher.json()["reports"][0]["target_membership_id"] == admin_id
    assert client.get(PUBLISHER, headers=owner, params={"after": owner_report}).status_code == 404
    with get_session_factory()() as session:
        session.get(CompanyMembership, member_id).role = "admin"
        session.commit()
    assert client.get(WORKSPACE, headers=owner).json() == {"reports": [], "next_cursor": None}
    publisher = client.get(PUBLISHER, headers=owner)
    assert {row["id"] for row in publisher.json()["reports"]} == {first, second, escalated}
    with get_session_factory()() as session:
        assert len(session.scalars(select(WorkspaceConductReport)).all()) == 4
        assert session.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "workspace_conduct.intake_read",
        )) is not None
        assert session.scalar(select(PlatformAdminAuditEvent.id).where(
            PlatformAdminAuditEvent.action == "workspace_conduct.publisher_intake_read",
        )) is not None


def test_report_rechecks_revocation_after_authentication(client, monkeypatch):
    auth, owner = _browser(client)
    reporter_id, _browser_session, reporter = _member(client, owner, auth, role="member")
    matter = _matter(client, owner)
    matter_id = matter["id"]
    note = _note(client, owner, matter_id, matter["lifecycle_version"])
    assert note.status_code == 200, note.text
    original = workspace_conduct_reports.receive

    def revoked(session, *, context, payload):
        with get_session_factory()() as concurrent:
            concurrent.get(CompanyMembership, reporter_id).sessions_valid_after = datetime.now(UTC)
            concurrent.commit()
        return original(session, context=context, payload=payload)

    monkeypatch.setattr(workspace_conduct_reports, "receive", revoked)
    denied = client.post(
        REPORTS, headers=reporter, json=_payload("note", matter_id, note.json()["id"]),
    )
    assert denied.status_code == 401, denied.text
    with get_session_factory()() as session:
        assert session.scalars(select(WorkspaceConductReport)).all() == []


def test_concurrent_exact_report_replays_share_one_durable_receipt(client, monkeypatch):
    auth, owner = _browser(client)
    _reporter_id, _browser_session, reporter = _member(client, owner, auth, role="member")
    matter = _matter(client, owner)
    matter_id = matter["id"]
    note = _note(client, owner, matter_id, matter["lifecycle_version"])
    assert note.status_code == 200, note.text
    payload = _payload("note", matter_id, note.json()["id"])
    original = workspace_conduct_reports.receive
    ready = Barrier(2)

    def same_time(session, *, context, payload):
        ready.wait(timeout=10)
        return original(session, context=context, payload=payload)

    monkeypatch.setattr(workspace_conduct_reports, "receive", same_time)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(client.post, REPORTS, headers=reporter, json=payload) for _ in range(2)
        ]
        receipts = [future.result(timeout=15) for future in futures]
    assert [response.status_code for response in receipts] == [202, 202]
    assert receipts[0].content == receipts[1].content
    with get_session_factory()() as session:
        rows = session.scalars(select(WorkspaceConductReport)).all()
        assert [row.id for row in rows] == [receipts[0].json()["id"]]
