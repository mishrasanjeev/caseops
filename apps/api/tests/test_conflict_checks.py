"""Tests for the matter conflict-check workflow (PG-001)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Client, Matter, MatterConflictCheck
from caseops_api.db.session import get_session_factory
from caseops_api.services import conflict_checks as conflict_check_service
from tests.test_auth_company import auth_headers, bootstrap_company


def _new_matter(
    client: TestClient,
    *,
    token: str,
    code: str,
    title: str,
    client_name: str,
    opposing: str | None = None,
    status: str = "intake",
) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title,
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": client_name,
            "opposing_party": opposing,
            "description": f"Seed matter for {title}",
            "status": status,
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _run_check(
    client: TestClient,
    *,
    token: str,
    matter_id: str,
    opposing_party_name: str,
) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={
            "opposing_party_name": opposing_party_name,
            "related_party_names": [],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _resolve_check(
    client: TestClient,
    *,
    token: str,
    check_id: str,
    status: str,
    note: str | None = None,
) -> dict:
    payload: dict[str, str] = {"status": status}
    if note is not None:
        payload["resolution_note"] = note
    resp = client.patch(
        f"/api/conflict-checks/{check_id}",
        headers=auth_headers(token),
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _activate_matter(client: TestClient, *, token: str, matter_id: str):
    current = client.get(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
    )
    assert current.status_code == 200, current.text
    return client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "expected_updated_at": current.json()["updated_at"],
        },
    )


def _matter_status(matter_id: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        status = session.scalar(select(Matter.status).where(Matter.id == matter_id))
    assert status is not None
    return str(status)


def _audit_events(*, company_id: str, action: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .where(AuditEvent.action == action)
                .order_by(AuditEvent.created_at.asc())
            )
        )


def test_run_conflict_check_with_no_overlap_auto_clears(client: TestClient) -> None:
    """Fresh tenant + no prior matters/clients → conflict scan returns
    zero candidates → status auto-clears so the user doesn't have to
    click resolve on a meaningless review."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _new_matter(
        client,
        token=token,
        code="CONF-001",
        title="Greenfield matter",
        client_name="Acme Pvt Ltd",
        opposing="Wholly Unrelated Co",
    )
    resp = client.post(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={
            "opposing_party_name": "Wholly Unrelated Co",
            "related_party_names": [],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "cleared"
    assert body["candidates"] == []
    assert body["resolved_at"] is not None


def test_run_conflict_check_flags_existing_client_record_as_pending(
    client: TestClient,
) -> None:
    """Regression for 2026-07-07 production bug: the scanner must read
    the real Client.name column. The previous stale primary_name
    reference only failed in tenants that had Client rows."""
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    factory = get_session_factory()
    with factory() as session:
        session.add(
            Client(
                company_id=company_id,
                name="Tata Sons Pvt Ltd",
                client_type="corporate",
            )
        )
        session.commit()

    matter_id = _new_matter(
        client,
        token=token,
        code="CLIENT-CONF-001",
        title="New dispute against existing client",
        client_name="Neutral Client",
        opposing="Tata Sons Pvt Ltd",
    )

    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Tata Sons Pvt Ltd",
    )

    assert check["status"] == "pending"
    client_candidates = [
        candidate for candidate in check["candidates"] if candidate["kind"] == "client"
    ]
    assert client_candidates
    assert client_candidates[0]["name"] == "Tata Sons Pvt Ltd"


def test_run_conflict_check_prefilters_large_client_tables(
    client: TestClient,
    monkeypatch,
) -> None:
    """Large tenants must not hydrate/score every Client row for one scan."""
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    factory = get_session_factory()
    with factory() as session:
        session.add(
            Client(
                company_id=company_id,
                name="Tata Sons Pvt Ltd",
                client_type="corporate",
            )
        )
        for index in range(150):
            session.add(
                Client(
                    company_id=company_id,
                    name=f"Unrelated Portfolio Entity {index:03d}",
                    client_type="corporate",
                )
            )
        session.commit()

    scored_names: list[str | None] = []
    original_score = conflict_check_service._score

    def counting_score(query_name: str, candidate_name: str | None):
        scored_names.append(candidate_name)
        return original_score(query_name, candidate_name)

    monkeypatch.setattr(conflict_check_service, "_score", counting_score)
    matter_id = _new_matter(
        client,
        token=token,
        code="CLIENT-PREFILTER-001",
        title="Prefiltered conflict scan",
        client_name="Neutral Client",
        opposing="Tata Sons Pvt Ltd",
    )

    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Tata Sons Pvt Ltd",
    )

    assert check["status"] == "pending"
    assert "Tata Sons Pvt Ltd" in scored_names
    assert not any(
        name and name.startswith("Unrelated Portfolio Entity")
        for name in scored_names
    )


def test_run_conflict_check_flags_existing_client_as_pending(
    client: TestClient,
) -> None:
    """When a prior matter's client_name overlaps the new matter's
    opposing_party, the scanner flags it as a candidate and the check
    requires partner review (status=pending)."""
    token = str(bootstrap_company(client)["access_token"])
    # Seed the conflict universe via a prior matter for "Acme Pvt Ltd"
    # as the existing client.
    _new_matter(
        client,
        token=token,
        code="EXIST-001",
        title="Acme contract dispute",
        client_name="Acme Pvt Ltd",
    )
    new_matter_id = _new_matter(
        client,
        token=token,
        code="NEW-001",
        title="New retainer",
        client_name="Beta Corp",
        opposing="Acme Pvt Ltd",  # is already our client → conflict
    )
    resp = client.post(
        f"/api/matters/{new_matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={
            "opposing_party_name": "Acme Pvt Ltd",
            "related_party_names": [],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["candidates"], "expected at least one candidate"
    # The prior matter (kind=matter) is the actionable hit.
    kinds = {c["kind"] for c in body["candidates"]}
    assert "matter" in kinds


def test_intake_to_active_does_not_require_conflict_check(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-001",
        title="Ungated intake",
        client_name="Beta Corp",
        opposing="Acme Pvt Ltd",
        status="intake",
    )

    activate = _activate_matter(client, token=token, matter_id=matter_id)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    assert _matter_status(matter_id) == "active"
    blocked_events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.blocked",
    )
    assert blocked_events == []
    completed_events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.completed",
    )
    assert len(completed_events) == 1
    metadata = json.loads(completed_events[0].metadata_json or "{}")
    assert metadata["from_status"] == "intake"
    assert metadata["to_status"] == "active"
    assert "conflict_gate" not in metadata
    assert completed_events[0].result == "success"


def test_direct_active_matter_create_does_not_require_conflict_check(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])

    create = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Direct active bypass attempt",
            "matter_code": "GATE-DIRECT",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Beta Corp",
            "opposing_party": "Acme Pvt Ltd",
            "status": "active",
        },
    )

    assert create.status_code == 200, create.text
    assert create.json()["status"] == "active"
    assert create.json()["is_active"] is True
    events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.blocked",
    )
    assert events == []


def test_completed_conflict_check_remains_recorded_independently_of_activation(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-002",
        title="Clear intake",
        client_name="Beta Corp",
        opposing="Unrelated Co",
        status="intake",
    )
    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Unrelated Co",
    )
    assert check["status"] == "cleared"

    activate = _activate_matter(client, token=token, matter_id=matter_id)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.completed",
    )
    assert len(events) == 1
    metadata = json.loads(events[0].metadata_json or "{}")
    assert metadata["from_status"] == "intake"
    assert metadata["to_status"] == "active"
    assert "conflict_gate" not in metadata
    recorded = client.get(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["checks"][0]["id"] == check["id"]
    assert recorded.json()["checks"][0]["status"] == "cleared"


def test_on_hold_to_active_is_independent_of_conflict_check_state(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    missing_check_matter = _new_matter(
        client,
        token=token,
        code="GATE-HOLD-001",
        title="On hold without clearance",
        client_name="Beta Corp",
        status="on_hold",
    )

    without_check = _activate_matter(
        client,
        token=token,
        matter_id=missing_check_matter,
    )

    assert without_check.status_code == 200, without_check.text
    assert without_check.json()["status"] == "active"
    assert _matter_status(missing_check_matter) == "active"

    cleared_matter = _new_matter(
        client,
        token=token,
        code="GATE-HOLD-002",
        title="On hold with clearance",
        client_name="Gamma Corp",
        opposing="Unrelated Co",
        status="on_hold",
    )
    _run_check(
        client,
        token=token,
        matter_id=cleared_matter,
        opposing_party_name="Unrelated Co",
    )

    allowed = _activate_matter(client, token=token, matter_id=cleared_matter)

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "active"


def test_active_to_active_update_is_independent_of_conflict_check_status(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-ACTIVE-UPDATE",
        title="Active update",
        client_name="Beta Corp",
        opposing="Unrelated Co",
    )
    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Unrelated Co",
    )
    activate = _activate_matter(client, token=token, matter_id=matter_id)
    assert activate.status_code == 200, activate.text

    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(MatterConflictCheck).where(MatterConflictCheck.id == check["id"])
        )
        assert row is not None
        row.status = "failed"
        session.commit()

    update = client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "court_name": "Bombay High Court",
            "expected_updated_at": activate.json()["updated_at"],
        },
    )

    assert update.status_code == 200, update.text
    assert update.json()["status"] == "active"
    assert update.json()["court_name"] == "Bombay High Court"


def test_pending_conflict_check_does_not_block_intake_activation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _new_matter(
        client,
        token=token,
        code="GATE-EXIST-003",
        title="Existing Acme matter",
        client_name="Acme Pvt Ltd",
    )
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-003",
        title="Pending conflict intake",
        client_name="Beta Corp",
        opposing="Acme Pvt Ltd",
        status="intake",
    )
    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Acme Pvt Ltd",
    )
    assert check["status"] == "pending"

    activate = _activate_matter(client, token=token, matter_id=matter_id)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    assert _matter_status(matter_id) == "active"
    recorded = client.get(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["checks"][0]["id"] == check["id"]
    assert recorded.json()["checks"][0]["status"] == "pending"


def test_invalid_latest_conflict_check_status_does_not_block_activation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-INVALID",
        title="Invalid status intake",
        client_name="Beta Corp",
        opposing="Unrelated Co",
    )
    check = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Unrelated Co",
    )
    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(
            select(MatterConflictCheck).where(MatterConflictCheck.id == check["id"])
        )
        assert row is not None
        row.status = "failed"
        session.commit()

    activate = _activate_matter(client, token=token, matter_id=matter_id)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    assert _matter_status(matter_id) == "active"
    factory = get_session_factory()
    with factory() as session:
        recorded_status = session.scalar(
            select(MatterConflictCheck.status).where(
                MatterConflictCheck.id == check["id"]
            )
        )
    assert recorded_status == "failed"


def test_latest_pending_check_does_not_make_older_clearance_an_activation_gate(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-004",
        title="Stale clear intake",
        client_name="Beta Corp",
        opposing="Unrelated Co",
        status="intake",
    )
    clear = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Unrelated Co",
    )
    assert clear["status"] == "cleared"
    _new_matter(
        client,
        token=token,
        code="GATE-EXIST-004",
        title="Newly discovered Acme matter",
        client_name="Acme Pvt Ltd",
    )
    latest = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Acme Pvt Ltd",
    )
    assert latest["status"] == "pending"

    activate = _activate_matter(client, token=token, matter_id=matter_id)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    recorded = client.get(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
    )
    assert recorded.status_code == 200, recorded.text
    recorded_checks = recorded.json()["checks"]
    assert [item["id"] for item in recorded_checks[:2]] == [latest["id"], clear["id"]]
    events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.completed",
    )
    metadata = json.loads(events[-1].metadata_json or "{}")
    assert metadata["from_status"] == "intake"
    assert metadata["to_status"] == "active"
    assert "conflict_gate" not in metadata


def test_stale_party_scope_check_does_not_block_activation_or_party_update(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _new_matter(
        client,
        token=token,
        code="GATE-PARTY-SCOPE",
        title="Party-scope stale intake",
        client_name="Beta Corp",
        opposing="Unrelated Co",
    )
    clear = _run_check(
        client,
        token=token,
        matter_id=matter_id,
        opposing_party_name="Unrelated Co",
    )
    assert clear["status"] == "cleared"

    activate = client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "opposing_party": "Acme Pvt Ltd",
            "expected_updated_at": client.get(
                f"/api/matters/{matter_id}",
                headers=auth_headers(token),
            ).json()["updated_at"],
        },
    )

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    assert activate.json()["opposing_party"] == "Acme Pvt Ltd"
    assert _matter_status(matter_id) == "active"
    blocked_events = _audit_events(
        company_id=company_id,
        action="matter.status_transition.blocked",
    )
    assert blocked_events == []
    recorded = client.get(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["checks"][0]["id"] == clear["id"]
    assert recorded.json()["checks"][0]["status"] == "cleared"


def test_cross_tenant_conflict_check_access_isolated_without_gating_activation(
    client: TestClient,
) -> None:
    boot_a = bootstrap_company(client)
    token_a = str(boot_a["access_token"])
    matter_a = _new_matter(
        client,
        token=token_a,
        code="GATE-XTENANT",
        title="Tenant A intake",
        client_name="Beta Corp",
        opposing="Unrelated Co",
    )
    boot_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "PG001 Cross Tenant",
            "company_slug": "pg001-cross-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Tenant B Owner",
            "owner_email": "owner@pg001-cross-tenant.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert boot_b.status_code == 200, boot_b.text
    token_b = str(boot_b.json()["access_token"])

    cross_check = client.post(
        f"/api/matters/{matter_a}/conflict-checks",
        headers=auth_headers(token_b),
        json={
            "opposing_party_name": "Unrelated Co",
            "related_party_names": [],
        },
    )
    assert cross_check.status_code == 404

    activate = _activate_matter(client, token=token_a, matter_id=matter_a)

    assert activate.status_code == 200, activate.text
    assert activate.json()["status"] == "active"
    assert _matter_status(matter_a) == "active"


def test_conflicted_and_waived_checks_are_advisory_for_activation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _new_matter(
        client,
        token=token,
        code="GATE-EXIST-005",
        title="Existing Acme matter",
        client_name="Acme Pvt Ltd",
    )
    conflicted_matter = _new_matter(
        client,
        token=token,
        code="GATE-005",
        title="Conflicted intake",
        client_name="Beta Corp",
        opposing="Acme Pvt Ltd",
        status="intake",
    )
    conflicted_check = _run_check(
        client,
        token=token,
        matter_id=conflicted_matter,
        opposing_party_name="Acme Pvt Ltd",
    )
    _resolve_check(
        client,
        token=token,
        check_id=conflicted_check["id"],
        status="conflicted",
        note="Confirmed possible conflict requiring review.",
    )

    conflicted_activation = _activate_matter(
        client,
        token=token,
        matter_id=conflicted_matter,
    )

    assert conflicted_activation.status_code == 200, conflicted_activation.text
    assert conflicted_activation.json()["status"] == "active"

    waived_matter = _new_matter(
        client,
        token=token,
        code="GATE-006",
        title="Waived intake",
        client_name="Gamma Corp",
        opposing="Acme Pvt Ltd",
        status="intake",
    )
    waived_check = _run_check(
        client,
        token=token,
        matter_id=waived_matter,
        opposing_party_name="Acme Pvt Ltd",
    )
    _resolve_check(
        client,
        token=token,
        check_id=waived_check["id"],
        status="waived",
        note="Partner waiver recorded outside this audit payload.",
    )

    allowed = _activate_matter(client, token=token, matter_id=waived_matter)

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "active"
    conflicted_record = client.get(
        f"/api/matters/{conflicted_matter}/conflict-checks",
        headers=auth_headers(token),
    )
    waived_record = client.get(
        f"/api/matters/{waived_matter}/conflict-checks",
        headers=auth_headers(token),
    )
    assert conflicted_record.status_code == 200, conflicted_record.text
    assert waived_record.status_code == 200, waived_record.text
    assert conflicted_record.json()["checks"][0]["status"] == "conflicted"
    assert waived_record.json()["checks"][0]["status"] == "waived"
    factory = get_session_factory()
    with factory() as session:
        event = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.action == "matter.status_transition.completed",
                AuditEvent.matter_id == waived_matter,
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert event is not None
        metadata = json.loads(event.metadata_json or "{}")
        assert metadata["from_status"] == "intake"
        assert metadata["to_status"] == "active"
        assert "conflict_gate" not in metadata


def test_status_activation_respects_tenant_restricted_wall_and_team_scoping(
    client: TestClient,
) -> None:
    slug = "pg001-access"
    boot = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "PG001 Access LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Access Owner",
            "owner_email": "owner@pg001-access.example",
            "owner_password": "OwnerStrong!234",
        },
    )
    assert boot.status_code == 200, boot.text
    owner_token = str(boot.json()["access_token"])
    owner_headers = auth_headers(owner_token)
    member = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Blocked Member",
            "email": "member@pg001-access.example",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "member@pg001-access.example",
            "password": "MemberPass123!",
            "company_slug": slug,
        },
    )
    assert login.status_code == 200, login.text
    member_token = str(login.json()["access_token"])
    member_headers = auth_headers(member_token)

    restricted_matter = _new_matter(
        client,
        token=owner_token,
        code="GATE-REST",
        title="Restricted intake",
        client_name="Beta Corp",
        status="intake",
    )
    restricted = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    denied = client.patch(
        f"/api/matters/{restricted_matter}",
        headers=member_headers,
        json={
            "status": "active",
            "expected_updated_at": client.get(
                f"/api/matters/{restricted_matter}",
                headers=owner_headers,
            ).json()["updated_at"],
        },
    )
    assert denied.status_code == 404

    walled_matter = _new_matter(
        client,
        token=owner_token,
        code="GATE-WALL",
        title="Walled intake",
        client_name="Beta Corp",
        status="intake",
    )
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": member.json()["membership_id"]},
    )
    assert wall.status_code == 200, wall.text
    walled = client.patch(
        f"/api/matters/{walled_matter}",
        headers=member_headers,
        json={
            "status": "active",
            "expected_updated_at": client.get(
                f"/api/matters/{walled_matter}",
                headers=owner_headers,
            ).json()["updated_at"],
        },
    )
    assert walled.status_code == 404

    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "litigation"},
    )
    assert team.status_code == 201, team.text
    team_matter = _new_matter(
        client,
        token=owner_token,
        code="GATE-TEAM",
        title="Team-scoped intake",
        client_name="Beta Corp",
        status="intake",
    )
    assign = client.patch(
        f"/api/matters/{team_matter}",
        headers=owner_headers,
        json={
            "team_id": team.json()["id"],
            "expected_updated_at": client.get(
                f"/api/matters/{team_matter}",
                headers=owner_headers,
            ).json()["updated_at"],
        },
    )
    assert assign.status_code == 200, assign.text
    scope = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text
    team_denied = client.patch(
        f"/api/matters/{team_matter}",
        headers=member_headers,
        json={
            "status": "active",
            "expected_updated_at": assign.json()["updated_at"],
        },
    )
    assert team_denied.status_code == 404

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "PG001 Other LLP",
            "company_slug": "pg001-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@pg001-other.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert other.status_code == 200, other.text
    cross = client.patch(
        f"/api/matters/{team_matter}",
        headers=auth_headers(str(other.json()["access_token"])),
        json={
            "status": "active",
            "expected_updated_at": assign.json()["updated_at"],
        },
    )
    assert cross.status_code == 404


def test_pg001_contract_keeps_conflict_review_advisory_and_nonblocking() -> None:
    module_contract = " ".join((conflict_check_service.__doc__ or "").lower().split())
    model_contract = " ".join((MatterConflictCheck.__doc__ or "").lower().split())

    assert "advisory review workflow" in module_contract
    assert "do not block matter status changes" in module_contract
    assert "does not control the matter lifecycle" in model_contract
    assert not hasattr(conflict_check_service, "evaluate_matter_opening_gate")


def test_resolve_conflict_check_records_partner_decision(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _new_matter(
        client, token=token, code="EXIST-002", title="Existing", client_name="Acme",
    )
    matter_id = _new_matter(
        client, token=token, code="NEW-002", title="New", client_name="Beta",
        opposing="Acme",
    )
    run = client.post(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={"opposing_party_name": "Acme", "related_party_names": []},
    )
    check_id = run.json()["id"]
    resolve = client.patch(
        f"/api/conflict-checks/{check_id}",
        headers=auth_headers(token),
        json={"status": "cleared", "resolution_note": "Reviewed; no real overlap."},
    )
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["status"] == "cleared"
    assert resolve.json()["resolution_note"] == "Reviewed; no real overlap."


def test_waiver_requires_resolution_note(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _new_matter(
        client, token=token, code="EXIST-003", title="Existing", client_name="Acme",
    )
    matter_id = _new_matter(
        client, token=token, code="NEW-003", title="New", client_name="Beta",
        opposing="Acme",
    )
    run = client.post(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={"opposing_party_name": "Acme", "related_party_names": []},
    )
    bad = client.patch(
        f"/api/conflict-checks/{run.json()['id']}",
        headers=auth_headers(token),
        json={"status": "waived"},
    )
    assert bad.status_code == 400
    detail = bad.json()["detail"].lower()
    assert "resolution_note" in detail or "basis" in detail


def test_list_conflict_checks_is_tenant_and_matter_scoped(
    client: TestClient,
) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _new_matter(
        client, token=token_a, code="A-001", title="A's matter",
        client_name="A's client",
    )
    client.post(
        f"/api/matters/{matter_a}/conflict-checks",
        headers=auth_headers(token_a),
        json={"opposing_party_name": "Adversary", "related_party_names": []},
    )

    company_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": "tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "B Owner",
            "owner_email": "owner@tenant-b.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert company_b.status_code == 200
    token_b = str(company_b.json()["access_token"])

    cross = client.get(
        f"/api/matters/{matter_a}/conflict-checks",
        headers=auth_headers(token_b),
    )
    assert cross.status_code == 404


def test_resolve_rejects_already_terminal_check(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _new_matter(
        client, token=token, code="EXIST-004", title="Existing", client_name="Acme",
    )
    matter_id = _new_matter(
        client, token=token, code="NEW-004", title="New", client_name="Beta",
        opposing="Acme",
    )
    run = client.post(
        f"/api/matters/{matter_id}/conflict-checks",
        headers=auth_headers(token),
        json={"opposing_party_name": "Acme", "related_party_names": []},
    )
    check_id = run.json()["id"]
    first = client.patch(
        f"/api/conflict-checks/{check_id}",
        headers=auth_headers(token),
        json={"status": "conflicted", "resolution_note": "Confirmed conflict."},
    )
    assert first.status_code == 200
    second = client.patch(
        f"/api/conflict-checks/{check_id}",
        headers=auth_headers(token),
        json={"status": "cleared"},
    )
    assert second.status_code == 409
