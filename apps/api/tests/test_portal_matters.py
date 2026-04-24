"""Phase C-2 (2026-04-24, MOD-TS-015) — client portal matter surface.

Covers:

- GET /api/portal/matters: list of granted matters, scope-isolated
- GET /api/portal/matters/{id}: 200 on grant, 404 on no grant, 404 on
  cross-tenant matter
- GET /api/portal/matters/{id}/communications: read works, scope-isolated
- POST /api/portal/matters/{id}/communications: posts inbound row, lands
  in internal log; 403 when can_reply is false; 404 cross-tenant
- POST /api/portal/matters/{id}/kyc: marks attached clients as submitted +
  audit; 400 when no client linked
- GET /api/portal/matters/{id}/hearings: returns matter hearings
- Outside-counsel role denied client-only endpoints
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    AuditEvent,
    Client,
    ClientKycStatus,
    Communication,
    Matter,
    MatterHearing,
    MatterHearingStatus,
)
from caseops_api.db.models import (
    MatterClientAssignment as MatterClient,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers


def _bootstrap(client: TestClient, *, slug: str, email: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.title() + " LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert resp.status_code == 200
    client.cookies.clear()
    return resp.json()


def _seed_matter(company_id: str, *, code: str) -> str:
    Session = get_session_factory()
    with Session() as session:
        matter = Matter(
            company_id=company_id,
            client_name="Anchor Client",
            title=f"Matter {code}",
            matter_code=code,
            status="active",
            practice_area="commercial",
            forum_level="high_court",
        )
        session.add(matter)
        session.commit()
        return matter.id


def _seed_client_and_link(company_id: str, matter_id: str) -> str:
    Session = get_session_factory()
    with Session() as session:
        c = Client(
            company_id=company_id,
            name="Test Client",
            client_type="individual",
            kyc_status=ClientKycStatus.NOT_STARTED,
        )
        session.add(c)
        session.flush()
        mc = MatterClient(matter_id=matter_id, client_id=c.id)
        session.add(mc)
        session.commit()
        return c.id


def _invite_client_portal_user(
    client: TestClient, owner_token: str, matter_id: str, *,
    email: str = "client@portal.example", can_reply: bool = True,
) -> tuple[str, str]:
    """Returns (portal_user_id, debug_token)."""
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(owner_token),
        json={
            "email": email,
            "full_name": "Test Portal Client",
            "role": "client",
            "matter_ids": [matter_id],
            "can_reply": can_reply,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["portal_user"]["id"], body["debug_token"]


def _verify_and_session(
    client: TestClient, debug_token: str
) -> None:
    client.cookies.clear()
    resp = client.post(
        "/api/portal/auth/verify-link", json={"token": debug_token},
    )
    assert resp.status_code == 200, resp.text


# ---------- list matters ----------


def test_portal_user_lists_only_granted_matters(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c2-list", email="c2-list@firm.example")
    company_id = boot["company"]["id"]
    token = str(boot["access_token"])
    granted_id = _seed_matter(company_id, code="C2-GRANTED")
    _ungranted_id = _seed_matter(company_id, code="C2-UNGRANTED")

    _, debug = _invite_client_portal_user(client, token, granted_id)
    _verify_and_session(client, debug)

    resp = client.get("/api/portal/matters")
    assert resp.status_code == 200
    matters = resp.json()["matters"]
    assert [m["matter_code"] for m in matters] == ["C2-GRANTED"]


def test_portal_matter_list_is_tenant_isolated(client: TestClient) -> None:
    boot_a = _bootstrap(client, slug="c2-a", email="c2-a@firm.example")
    boot_b = _bootstrap(client, slug="c2-b", email="c2-b@firm.example")
    matter_a = _seed_matter(boot_a["company"]["id"], code="C2-A-1")
    matter_b = _seed_matter(boot_b["company"]["id"], code="C2-B-1")

    _, debug_a = _invite_client_portal_user(
        client, str(boot_a["access_token"]), matter_a,
        email="iso@firm-a.example",
    )
    _, debug_b = _invite_client_portal_user(
        client, str(boot_b["access_token"]), matter_b,
        email="iso@firm-b.example",
    )

    _verify_and_session(client, debug_a)
    a_matters = client.get("/api/portal/matters").json()["matters"]
    assert [m["matter_code"] for m in a_matters] == ["C2-A-1"]

    _verify_and_session(client, debug_b)
    b_matters = client.get("/api/portal/matters").json()["matters"]
    assert [m["matter_code"] for m in b_matters] == ["C2-B-1"]


# ---------- matter detail ----------


def test_portal_matter_detail_404_on_no_grant(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c2-detail", email="c2-d@firm.example")
    token = str(boot["access_token"])
    granted = _seed_matter(boot["company"]["id"], code="C2-GR")
    ungranted = _seed_matter(boot["company"]["id"], code="C2-UN")
    _, debug = _invite_client_portal_user(client, token, granted)
    _verify_and_session(client, debug)

    ok = client.get(f"/api/portal/matters/{granted}")
    assert ok.status_code == 200
    assert ok.json()["matter_code"] == "C2-GR"
    deny = client.get(f"/api/portal/matters/{ungranted}")
    assert deny.status_code == 404


def test_portal_matter_detail_404_on_cross_tenant(client: TestClient) -> None:
    boot_a = _bootstrap(client, slug="c2-x-a", email="c2-x-a@f.example")
    boot_b = _bootstrap(client, slug="c2-x-b", email="c2-x-b@f.example")
    matter_a = _seed_matter(boot_a["company"]["id"], code="C2-X-A")
    matter_b = _seed_matter(boot_b["company"]["id"], code="C2-X-B")
    _, debug_a = _invite_client_portal_user(
        client, str(boot_a["access_token"]), matter_a,
        email="x-a@portal.example",
    )
    _verify_and_session(client, debug_a)
    cross = client.get(f"/api/portal/matters/{matter_b}")
    assert cross.status_code == 404


# ---------- communications read + reply ----------


def test_portal_user_reads_matter_communications(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c2-comms", email="c2-c@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C2-CR")
    # Internal user posts a comm via the firm-side route.
    posted = client.post(
        f"/api/matters/{matter_id}/communications",
        headers=auth_headers(token),
        json={
            "channel": "note",
            "direction": "outbound",
            "body": "Hello from the firm.",
            "subject": "Welcome",
        },
    )
    assert posted.status_code in {200, 201}, posted.text
    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    listing = client.get(f"/api/portal/matters/{matter_id}/communications")
    assert listing.status_code == 200
    rows = listing.json()["communications"]
    assert any(c["body"] == "Hello from the firm." for c in rows)
    assert all(c["direction"] in {"inbound", "outbound"} for c in rows)


def test_portal_user_can_reply_creates_inbound_row(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="c2-reply", email="c2-r@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C2-RP")
    portal_user_id, debug = _invite_client_portal_user(
        client, token, matter_id,
    )
    _verify_and_session(client, debug)

    resp = client.post(
        f"/api/portal/matters/{matter_id}/communications",
        json={"body": "Question about the next hearing date please."},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["direction"] == "inbound"
    assert body["posted_by_portal_user"] is True
    assert body["body"].startswith("Question")

    # Verify the row landed on the internal Comms log too.
    Session = get_session_factory()
    with Session() as session:
        row = (
            session.query(Communication)
            .filter(Communication.id == body["id"])
            .first()
        )
        assert row is not None
        assert row.direction == "inbound"
        assert row.matter_id == matter_id
        assert row.metadata_json["portal_user_id"] == portal_user_id


def test_portal_reply_blocked_when_can_reply_is_false(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="c2-noreply", email="c2-n@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C2-NR")
    _, debug = _invite_client_portal_user(
        client, token, matter_id, can_reply=False,
    )
    _verify_and_session(client, debug)

    resp = client.post(
        f"/api/portal/matters/{matter_id}/communications",
        json={"body": "I want to reply but I can't."},
    )
    assert resp.status_code == 403
    assert "can_reply" in resp.json()["detail"]


def test_portal_reply_404_on_cross_tenant_matter(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, slug="c2-rxt-a", email="c2-rxt-a@f.example")
    boot_b = _bootstrap(client, slug="c2-rxt-b", email="c2-rxt-b@f.example")
    matter_a = _seed_matter(boot_a["company"]["id"], code="C2-RXT-A")
    matter_b = _seed_matter(boot_b["company"]["id"], code="C2-RXT-B")
    _, debug_a = _invite_client_portal_user(
        client, str(boot_a["access_token"]), matter_a,
        email="rxt-a@portal.example",
    )
    _verify_and_session(client, debug_a)
    cross = client.post(
        f"/api/portal/matters/{matter_b}/communications",
        json={"body": "trying to leak"},
    )
    assert cross.status_code == 404


def test_portal_reply_empty_body_returns_400(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c2-empty", email="c2-e@firm.example")
    matter_id = _seed_matter(boot["company"]["id"], code="C2-EM")
    _, debug = _invite_client_portal_user(
        client, str(boot["access_token"]), matter_id,
    )
    _verify_and_session(client, debug)
    resp = client.post(
        f"/api/portal/matters/{matter_id}/communications",
        json={"body": ""},
    )
    # Either 400 from service or 422 from pydantic — both acceptable.
    assert resp.status_code in {400, 422}


# ---------- KYC submit ----------


def test_portal_kyc_submit_marks_clients_and_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="c2-kyc", email="c2-k@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C2-KY")
    client_id = _seed_client_and_link(boot["company"]["id"], matter_id)
    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    resp = client.post(
        f"/api/portal/matters/{matter_id}/kyc",
        json={
            "documents": [
                {"name": "PAN", "note": "scanned"},
                {"name": "Aadhaar", "note": "redacted"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["matter_id"] == matter_id
    assert body["affected_client_ids"] == [client_id]
    assert body["submitted_at"]

    Session = get_session_factory()
    with Session() as session:
        c = session.get(Client, client_id)
        assert c is not None
        assert c.kyc_status == ClientKycStatus.PENDING
        assert c.kyc_submitted_at is not None
        assert len(c.kyc_documents_json) == 2
        # Audit row written.
        events = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "portal.kyc.submitted")
            .filter(AuditEvent.target_id == matter_id)
            .all()
        )
        assert len(events) == 1


def test_portal_kyc_400_when_no_client_linked(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c2-noc", email="c2-no@firm.example")
    matter_id = _seed_matter(boot["company"]["id"], code="C2-NO")
    _, debug = _invite_client_portal_user(
        client, str(boot["access_token"]), matter_id,
    )
    _verify_and_session(client, debug)

    resp = client.post(
        f"/api/portal/matters/{matter_id}/kyc",
        json={"documents": []},
    )
    assert resp.status_code == 400
    assert "client" in resp.json()["detail"].lower()


# ---------- hearings ----------


def test_portal_user_lists_matter_hearings(client: TestClient) -> None:
    from datetime import date

    boot = _bootstrap(client, slug="c2-hr", email="c2-h@firm.example")
    matter_id = _seed_matter(boot["company"]["id"], code="C2-HR")
    Session = get_session_factory()
    with Session() as session:
        h = MatterHearing(
            id=str(uuid4()),
            matter_id=matter_id,
            hearing_on=date.today() + timedelta(days=7),
            forum_name="Delhi High Court — Court Room 5",
            judge_name="Hon'ble Justice X",
            purpose="First hearing",
            status=MatterHearingStatus.SCHEDULED,
        )
        session.add(h)
        session.commit()
    _, debug = _invite_client_portal_user(
        client, str(boot["access_token"]), matter_id,
    )
    _verify_and_session(client, debug)

    resp = client.get(f"/api/portal/matters/{matter_id}/hearings")
    assert resp.status_code == 200
    hearings = resp.json()["hearings"]
    assert len(hearings) == 1
    assert "Court Room 5" in hearings[0]["forum_name"]


# ---------- outside-counsel role denied client-only routes ----------


def test_outside_counsel_role_cannot_use_client_matter_surface(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug="c2-oc", email="c2-oc@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C2-OC")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "external@counsel.example",
            "full_name": "External Counsel",
            "role": "outside_counsel",
            "matter_ids": [matter_id],
        },
    ).json()
    _verify_and_session(client, invite["debug_token"])

    # Client-role endpoints must 404 (we deliberately conflate role
    # mismatch with not-found to avoid leaking matter existence).
    list_matters = client.get("/api/portal/matters")
    assert list_matters.status_code == 200
    assert list_matters.json()["matters"] == []  # role-filtered to client only

    detail = client.get(f"/api/portal/matters/{matter_id}")
    assert detail.status_code == 404


# ---------- unauthenticated ----------


def test_portal_matter_routes_require_portal_session(
    client: TestClient,
) -> None:
    client.cookies.clear()
    resp = client.get("/api/portal/matters")
    assert resp.status_code == 401
