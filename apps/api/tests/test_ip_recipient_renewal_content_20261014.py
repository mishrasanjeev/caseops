"""IP13-07/08/09: Portfolio reads only the recipient's delivered current source alert."""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    CustomRole,
    InAppNotification,
    IpDocketRecord,
    IpImportRow,
    MatterAccessGrant,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import ip_lifecycle, ip_renewals, notification_delivery
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers
from tests.test_clients import _mk_matter
from tests.test_ip_current_source_reminders_20261013 import (
    _PRIVATE,
    _append_current,
    _correct_number,
    _import_source,
)

pytestmark = pytest.mark.usefixtures("reminder_clock")


@pytest.fixture
def reminder_clock(monkeypatch):
    now = datetime(2028, 3, 20, tzinfo=UTC)
    monkeypatch.setattr(ip_renewals, "_now", lambda: now)
    monkeypatch.setattr(notification_delivery, "_now", lambda: now)


@pytest.fixture(params=[
    pytest.param("client", id="sqlite"),
    pytest.param("isolated_postgres_client", id="postgres", marks=pytest.mark.postgres),
])
def source_client(request):
    return request.getfixturevalue(request.param)


def test_operational_alert_statuses_match_existing_canonical_lifecycle_owner():
    assert set(ip_renewals._TERMINAL_DOCKET_STATUSES) == ip_lifecycle.TERMINAL_IP_DOCKET_STATUSES


def _deliver(actor, docket_id):
    with get_session_factory()() as session:
        intent = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == actor["company"]["id"],
                NotificationDeliveryIntent.ip_docket_id == docket_id,
                NotificationDeliveryIntent.status == "queued",
            )
        ).one()
        result = notification_delivery.process_notification_delivery_intent(
            session, intent_id=intent.id, company_id=actor["company"]["id"],
        )
        assert result.delivered and str(result.status) == "delivered"
        session.commit()
        session.refresh(intent)
        note = session.get(InAppNotification, intent.in_app_notification_id)
        assert note is not None and note.body
        assert note.recipient_membership_id == actor["membership"]["id"]
        assert note.source_id == intent.source_id
        assert note.body == intent.body and _PRIVATE not in note.body
        return intent.id, note.id, note.body


def _portfolio(client, actor, **params):
    response = client.get("/api/ip/portfolio", headers=actor["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("version", [1, 2], ids=["original-current", "corrected-current"])
def test_recipient_reads_exact_delivered_current_body(source_client, version):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    with get_session_factory()() as session:
        source_before = deepcopy(session.get(IpImportRow, imported["id"]).normalized_json)
    if version == 2:
        _correct_number(client, actor, docket_id)
        current = _append_current(client, actor, docket_id)
        assert current["current_version"] == 2
    intent_id, note_id, body = _deliver(actor, docket_id)
    expected = (
        "Original mark; application OLD/2026; classes 9; applicant Original Applicant. "
        "Source renewal date 2028-03-31 (not a verified legal deadline). "
        "11 days remaining on the alert date. "
        if version == 1 else
        "Current mark v2; application CURRENT/2028; classes 42, 45; "
        "applicant Current Applicant v2, Current Joint Applicant. "
        "Source renewal date 2028-03-30 (not a verified legal deadline). "
        "10 days remaining on the alert date. "
    ) + f"/app/ip?docket={docket_id}"
    assert body == expected
    body_hash = sha256(body.encode()).hexdigest()
    for _ in range(2):
        rows = _portfolio(client, actor)["rows"]
        assert len(rows) == 1 and rows[0]["docket_id"] == docket_id
        assert rows[0]["source_renewal_alert_status"] == "delivered"
        # On 655 this is the failing call: actual delivery exists, body DTO does not.
        assert rows[0].get("source_renewal_alert_body") == expected
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).body == body
        retained_hash = sha256(session.get(InAppNotification, note_id).body.encode()).hexdigest()
        assert retained_hash == body_hash
        assert session.get(NotificationDeliveryIntent, intent_id).body == body
        assert session.get(IpImportRow, imported["id"]).normalized_json == source_before


@pytest.mark.parametrize("state", [
    "queued", "missing-receipt", "cancelled", "blocked", "email",
    "foreign-receipt", "wrong-source", "wrong-date", "ambiguous",
])
def test_only_exact_actual_delivery_can_supply_body(source_client, state):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    if state == "queued":
        assert _portfolio(client, actor)["rows"][0].get("source_renewal_alert_body") is None
        with get_session_factory()() as session:
            assert session.scalar(select(InAppNotification.id)) is None
        return
    intent_id, note_id, body = _deliver(actor, docket_id)
    foreign_actor = None
    if state == "foreign-receipt":
        with TestClient(client.app) as foreign:
            foreign_actor = _bootstrap_foreign(foreign)
    with get_session_factory()() as session:
        intent = session.get(NotificationDeliveryIntent, intent_id)
        note = session.get(InAppNotification, note_id)
        if state == "missing-receipt":
            intent.in_app_notification_id = None
        elif state in {"cancelled", "blocked"}:
            intent.status = state
        elif state == "email":
            intent.channel = "email"
        elif state == "wrong-source":
            intent.source_type = "not_portfolio_source"
        elif state == "wrong-date":
            intent.metadata_json = {**intent.metadata_json, "source_due_on": "2028-04-30"}
        elif state == "foreign-receipt":
            foreign = InAppNotification(
                company_id=foreign_actor["company"]["id"],
                recipient_membership_id=foreign_actor["membership"]["id"],
                event_type=note.event_type, source_type=note.source_type,
                source_id=str(uuid4()), title="Foreign receipt", body="FOREIGN BODY",
            )
            session.add(foreign)
            session.flush()
            intent.in_app_notification_id = foreign.id
        else:
            session.add(NotificationDeliveryIntent(
                company_id=intent.company_id, ip_docket_id=docket_id,
                recipient_membership_id=intent.recipient_membership_id,
                channel="in_app", event_type=intent.event_type, source_type=intent.source_type,
                source_id=intent.source_id, status="delivered", delivered_at=intent.delivered_at,
                in_app_notification_id=note_id, idempotency_key=uuid4().hex,
                schedule_source_type=intent.schedule_source_type,
                schedule_source_id=intent.schedule_source_id,
                metadata_json=dict(intent.metadata_json),
            ))
        session.commit()
    rows = _portfolio(client, actor)["rows"]
    assert len(rows) == 1 and rows[0].get("source_renewal_alert_body") is None
    assert body not in str(rows) and "FOREIGN BODY" not in str(rows)
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).body == body


@pytest.mark.parametrize("target", ["intent", "note"])
@pytest.mark.parametrize("metadata", [["retained-non-object"], "retained-non-object", 7, []],
                         ids=["list", "string", "number", "empty-list"])
def test_non_object_retained_metadata_denies_body_without_crashing_portfolio(
    source_client, target, metadata,
):
    client = source_client
    actor, imported = _import_source(client)
    intent_id, note_id, body = _deliver(actor, imported["created_docket_id"])
    with get_session_factory()() as session:
        record = session.get(
            NotificationDeliveryIntent if target == "intent" else InAppNotification,
            intent_id if target == "intent" else note_id,
        )
        record.metadata_json = deepcopy(metadata)
        session.commit()
    with TestClient(client.app, raise_server_exceptions=False) as transport:
        transport.cookies.update(client.cookies)
        # This must remain a successful authenticated Portfolio read, not HTTP 500.
        rows = _portfolio(transport, actor)["rows"]
        assert len(rows) == 1
        assert rows[0]["source_renewal_alert_status"] == "delivered"
        assert rows[0].get("source_renewal_alert_body") is None
        assert body not in str(rows)
    with get_session_factory()() as session:
        record = session.get(
            NotificationDeliveryIntent if target == "intent" else InAppNotification,
            intent_id if target == "intent" else note_id,
        )
        assert record.metadata_json == metadata
        assert session.get(InAppNotification, note_id).body == body
        assert session.get(NotificationDeliveryIntent, intent_id).body == body


def _bootstrap_foreign(client):
    identity = uuid4().hex
    response = client.post("/api/bootstrap/company", json={
        "company_name": "Foreign recipient fixture", "company_slug": f"foreign-{identity}",
        "company_type": "law_firm", "owner_full_name": "Foreign recipient",
        "owner_email": f"foreign-{identity}@example.in", "owner_password": "ForeignRecipient123!",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_other_authorized_viewer_and_foreign_company_cannot_read_recipient_body(source_client):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    _intent_id, note_id, body = _deliver(actor, docket_id)
    email = f"recipient-viewer-{uuid4().hex}@example.in"
    created = client.post("/api/companies/current/users", headers=actor["headers"], json={
        "full_name": "Other authorized IP viewer", "email": email,
        "password": "RecipientViewer123!", "role": "admin",
    })
    assert created.status_code == 200, created.text
    # Native authentication is cookie-first: every principal owns a separate client.
    with TestClient(client.app) as viewer:
        login = viewer.post("/api/auth/login", json={
            "company_slug": actor["company"]["slug"], "email": email,
            "password": "RecipientViewer123!",
        })
        assert login.status_code == 200, login.text
        other = {"headers": {**auth_headers(login.json()["access_token"]),
                            "X-CaseOps-Automated-Test": "no-paid-providers"}}
        rows = _portfolio(viewer, other)["rows"]
        assert len(rows) == 1 and rows[0]["docket_id"] == docket_id
        assert rows[0].get("source_renewal_alert_body") is None and body not in str(rows)
    with TestClient(client.app) as foreign:
        bootstrap = _bootstrap_foreign(foreign)
        headers = {**auth_headers(bootstrap["access_token"]),
                   "X-CaseOps-Automated-Test": "no-paid-providers"}
        assert _portfolio(foreign, {"headers": headers})["rows"] == []
    assert _portfolio(client, actor)["rows"][0]["source_renewal_alert_body"] == body
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).body == body


def test_current_grant_revocation_hides_body_even_for_original_recipient(source_client):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    _intent_id, note_id, body = _deliver(actor, docket_id)
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        docket.restricted = True
        session.add(MatterAccessGrant(
            company_id=actor["company"]["id"], ip_docket_id=docket_id,
            membership_id=actor["membership"]["id"], reason="Recipient current access",
            granted_by_membership_id=actor["membership"]["id"],
        ))
        session.commit()
    assert _portfolio(client, actor)["rows"][0]["source_renewal_alert_body"] == body
    with get_session_factory()() as session:
        grants = session.scalars(select(MatterAccessGrant).where(
            MatterAccessGrant.ip_docket_id == docket_id,
            MatterAccessGrant.membership_id == actor["membership"]["id"],
        )).all()
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert _portfolio(client, actor, include_inactive=True)["rows"] == []
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).body == body


def test_source_correction_clear_and_reload_never_rebind_historical_body(source_client):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    _intent_id, old_note_id, old_body = _deliver(actor, docket_id)
    _append_current(client, actor, docket_id, due="2028-03-31")
    # Same-date edits suppress replay, but must not rebound the old delivered body.
    for _ in range(2):
        row = _portfolio(client, actor)["rows"][0]
        assert row["source_renewal_due_on"] == "2028-03-31"
        assert row["source_renewal_alert_status"] is None
        assert row.get("source_renewal_alert_body") is None
    _append_current(client, actor, docket_id, due="2028-03-30")
    for _ in range(2):
        row = _portfolio(client, actor)["rows"][0]
        assert row["source_renewal_due_on"] == "2028-03-30"
        assert row["source_renewal_alert_status"] == "queued"
        assert row.get("source_renewal_alert_body") is None
    _new_intent_id, new_note_id, new_body = _deliver(actor, docket_id)
    assert new_body != old_body and "Current mark v3;" in new_body
    assert _portfolio(client, actor)["rows"][0]["source_renewal_alert_body"] == new_body
    _append_current(client, actor, docket_id, due=None)
    for _ in range(2):
        row = _portfolio(client, actor)["rows"][0]
        assert row["source_renewal_due_on"] is None
        assert row.get("source_renewal_alert_body") is None
    with get_session_factory()() as session:
        assert session.get(InAppNotification, old_note_id).body == old_body
        assert session.get(InAppNotification, new_note_id).body == new_body


@pytest.mark.parametrize("boundary", ["docket-terminal", "matter-disposed", "ip-capability"])
def test_lifecycle_and_capability_revocation_preserve_notes_not_operational_alert(
    source_client, boundary,
):
    client = source_client
    actor, imported = _import_source(client)
    docket_id = imported["created_docket_id"]
    _intent_id, note_id, body = _deliver(actor, docket_id)
    assert _portfolio(client, actor)["rows"][0]["source_renewal_alert_body"] == body
    if boundary == "docket-terminal":
        response = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"])
        assert response.status_code == 200, response.text
        docket = response.json()
        closed = client.post(f"/api/ip/dockets/{docket_id}/lifecycle", headers=actor["headers"],
                            json={
            "expected_lifecycle_version": docket["lifecycle_version"], "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(), "reason": "Recipient alert closure",
            "outcome": "closed", "source": "lawyer_review", "evidence_ref": "fixture:closure",
            "linked_matter_handling": "reviewed",
        })
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed" and not closed.json()["is_active"]
        rows = _portfolio(client, actor, include_inactive=True)["rows"]
        assert all(row.get("source_renewal_alert_body") is None for row in rows)
    elif boundary == "matter-disposed":
        matter = _mk_matter(client, actor["access_token"], "RECIPIENT-LINKED-MATTER")
        with get_session_factory()() as session:
            docket = session.get(IpDocketRecord, docket_id)
            docket.matter_id = matter["id"]
            original_status = docket.status
            session.commit()
        disposed = client.patch(f"/api/matters/{matter['id']}/lifecycle/status",
                                headers=actor["headers"], json={
            "to_status": "disposed", "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Linked Matter disposed by authorized user",
        })
        assert disposed.status_code == 200, disposed.text
        assert disposed.json()["status"] == "disposed" and not disposed.json()["is_active"]
        assert _portfolio(client, actor, include_inactive=True)["rows"] == []
        with get_session_factory()() as session:
            assert session.get(IpDocketRecord, docket_id).status == original_status
    else:
        with get_session_factory()() as session:
            membership = session.get(CompanyMembership, actor["membership"]["id"])
            role = CustomRole(
                company_id=actor["company"]["id"], name="Recipient read policy",
                slug=f"recipient-read-{uuid4().hex}", base_role="member",
                permissions_json=["ip:read"], is_active=True, is_system=False,
                created_by_membership_id=membership.id,
            )
            session.add(role)
            session.flush()
            membership.role, membership.custom_role_id = "member", role.id
            session.commit()
            role_id = role.id
        assert _portfolio(client, actor)["rows"][0]["source_renewal_alert_body"] == body
        with get_session_factory()() as session:
            session.get(CustomRole, role_id).permissions_json = []
            session.commit()
        denied = client.get("/api/ip/portfolio", headers=actor["headers"])
        assert denied.status_code == 403, denied.text
        assert body not in denied.text and "ip:read" in denied.text
    with get_session_factory()() as session:
        assert session.get(InAppNotification, note_id).body == body


def test_source_body_hydration_is_three_read_queries_for_one_or_many_dockets(source_client):
    client = source_client
    actor, imported = _import_source(client)
    first_docket = imported["created_docket_id"]
    _deliver(actor, first_docket)
    uploaded = client.post("/api/ip/imports/upload", headers=actor["headers"], files={
        "file": ("bounded.csv", (
            "Trademark,Applicant,Class,Application No.,Renewal Date\n" +
            "".join(f"Bounded mark {i},Bounded Owner,9,BOUND/{i},2028-03-31\n" for i in range(25))
        ).encode(), "text/csv"),
    })
    assert uploaded.status_code == 201, uploaded.text
    preview = uploaded.json()
    committed = client.post(f"/api/ip/imports/{preview['job']['id']}/commit",
                            headers=actor["headers"], json={
        "preview_token": preview["job"]["preview_token"], "idempotency_key": str(uuid4()),
    })
    assert committed.status_code == 200, committed.text
    rows = committed.json()["rows"]
    assert len(rows) == 25 and all(row["commit_status"] == "committed" for row in rows)
    docket_ids = [first_docket] + [row["created_docket_id"] for row in rows]
    for docket_id in docket_ids[1:]:
        _deliver(actor, docket_id)
    with get_session_factory()() as session:
        member = session.get(CompanyMembership, actor["membership"]["id"])
        context = SessionContext(company=session.get(Company, actor["company"]["id"]),
                                 membership=member, user=session.get(User, member.user_id))
        statements = []
        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        engine = get_engine()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            for ids in ([first_docket], docket_ids):
                statements.clear()
                details = ip_renewals.portfolio_source_renewal_details(
                    session, context=context, docket_ids=ids,
                )
                assert set(details) == set(ids)
                assert all(details[id]["source_renewal_alert_body"] for id in ids)
                assert len(statements) == 3
                assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
            statements.clear()
            assert ip_renewals.portfolio_source_renewal_details(
                session, context=context, docket_ids=[],
            ) == {}
            assert statements == []
            assert not session.new and not session.dirty and not session.deleted
        finally:
            event.remove(engine, "before_cursor_execute", capture)
