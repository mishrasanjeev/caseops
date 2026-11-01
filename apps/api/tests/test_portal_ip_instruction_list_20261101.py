"""B4-ADJ-14 sibling: the firm's portal client-instruction list applied the
ethical wall after a fixed 200-row bound, so walled rows used up the page and
visible instructions silently disappeared, with no total to say so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from caseops_api.db.models import EthicalWall, IpClientInstruction, IpDocketRecord
from caseops_api.db.session import get_session_factory
from caseops_api.services import portal_ip
from tests.test_auth_company import auth_headers
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_portal_ip import (
    _invite_ip_client,
    _portal_csrf,
    _preview,
    _publish_report,
    _verify_portal,
)


def _copy(source: IpClientInstruction, *, docket_id: str, received_at: datetime):
    return IpClientInstruction(
        company_id=source.company_id,
        docket_id=docket_id,
        instruction_thread_key=f"portal:{uuid4().hex}",
        instruction_kind=source.instruction_kind,
        instruction_version=1,
        decision=source.decision,
        status="pending",
        scope_json=source.scope_json,
        options_json=source.options_json,
        source_channel=source.source_channel,
        authority_name=source.authority_name,
        received_at=received_at,
        source_portal_user_id=source.source_portal_user_id,
        source_portal_grant_id=source.source_portal_grant_id,
        portal_publication_id=source.portal_publication_id,
        creator_label_snapshot=source.creator_label_snapshot,
    )


def test_walled_rows_never_hide_visible_instructions_and_total_is_honest(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(portal_ip, "FIRM_PORTAL_INSTRUCTION_LIMIT", 2)
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, debug_token = _invite_ip_client(client, headers, docket_id=docket["id"])
    preview = _preview(client, headers)
    publication = _publish_report(
        client, headers, invitation=invitation, snapshot_sha256=preview["snapshot_sha256"]
    )
    _verify_portal(client, debug_token)
    submitted = client.post(
        f"/api/portal/publications/{publication['id']}/instructions",
        headers=_portal_csrf(client),
        json={
            "decision": "proceed",
            "instruction_kind": "proceeding",
            "docket_id": docket["id"],
            "note": "Please proceed with the opposition response.",
        },
    )
    assert submitted.status_code == 201, submitted.text
    client.cookies.clear()

    member = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": "Walled Member",
            "email": "walled-member-adj14@example.com",
            "password": "MemberPass!2026",
            "role": "member",
        },
    )
    assert member.status_code == 200, member.text
    member_client = TestClient(client.app)
    login = member_client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "walled-member-adj14@example.com",
            "password": "MemberPass!2026",
        },
    )
    assert login.status_code == 200, login.text
    member_id = login.json()["membership"]["id"]
    member_headers = auth_headers(login.json()["access_token"])

    now = datetime.now(UTC)
    with get_session_factory()() as session:
        source = session.get(IpClientInstruction, submitted.json()["id"])
        visible_docket = session.get(IpDocketRecord, docket["id"])
        assert source is not None and visible_docket is not None
        walled = IpDocketRecord(
            company_id=visible_docket.company_id,
            matter_id=visible_docket.matter_id,
            record_type=visible_docket.record_type,
            title="Walled docket",
            status=visible_docket.status,
            restricted=False,
            created_by_membership_id=visible_docket.created_by_membership_id,
        )
        session.add(walled)
        session.flush()
        session.add(
            EthicalWall(
                company_id=walled.company_id,
                ip_docket_id=walled.id,
                excluded_membership_id=member_id,
            )
        )
        # Three newer instructions on the walled docket, one older visible one.
        for minutes in (1, 2, 3):
            session.add(
                _copy(source, docket_id=walled.id, received_at=now + timedelta(minutes=minutes))
            )
        oldest = _copy(source, docket_id=visible_docket.id, received_at=now - timedelta(days=1))
        session.add(oldest)
        session.commit()
        visible_ids = {source.id, oldest.id}

    owner_list = client.get("/api/ip/portal/client-instructions", headers=headers)
    assert owner_list.status_code == 200, owner_list.text
    assert owner_list.json()["total"] == 5
    assert owner_list.json()["limit"] == 2
    assert len(owner_list.json()["instructions"]) == 2

    listed = member_client.get("/api/ip/portal/client-instructions", headers=member_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    # The walled member sees both visible rows, sorted after three walled ones.
    assert {row["id"] for row in body["instructions"]} == visible_ids
    assert body["total"] == 2
    assert all(row["docket_title"] != "Walled docket" for row in body["instructions"])
    member_client.close()
