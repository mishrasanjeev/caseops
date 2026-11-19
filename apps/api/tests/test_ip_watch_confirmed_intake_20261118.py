"""A confirmed profile change and manual-intake availability are one receipt."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, IpWatchProfile
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_watch
from tests.test_auth_company import auth_headers
from tests.test_ip_journal_watch import _fixture, _profile
from tests.test_ip_record_workflow import _docket


def _change(client: TestClient, headers: dict, profile: dict, status: str) -> dict:
    response = client.post(
        f"/api/ip/watch/profiles/{profile['id']}/status",
        headers=headers,
        json={
            "expected_version": profile["version"],
            "poll_status": status,
            "reason": "Synthetic confirmed-intake acceptance",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["id"] == profile["id"] and result["version"] == profile["version"] + 1
    assert result["poll_status"] == status
    return result


def _count_journey(client: TestClient) -> None:
    client.headers.update({"X-CaseOps-Automated-Test": "no-paid-providers"})
    owner, headers, docket, _ = _fixture(client, "INTAKE COUNT A")
    other_docket = _docket(client, headers, "INTAKE COUNT B")
    first = _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=owner["membership"]["id"]
    )
    second = _profile(
        client,
        headers=headers,
        docket_id=other_docket["id"],
        recipient_id=owner["membership"]["id"],
    )
    foreign_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Synthetic foreign intake firm",
            "company_slug": "intake-count-foreign",
            "company_type": "law_firm",
            "owner_full_name": "Synthetic foreign owner",
            "owner_email": "intake-foreign@example.com",
            "owner_password": f"Synthetic!{uuid4()}",
        },
    )
    assert foreign_response.status_code == 200, foreign_response.text
    foreign = foreign_response.json()
    foreign_headers = auth_headers(foreign["access_token"])
    foreign_docket = _docket(client, foreign_headers, "FOREIGN INTAKE")
    _profile(
        client,
        headers=foreign_headers,
        docket_id=foreign_docket["id"],
        recipient_id=foreign["membership"]["id"],
    )
    # Probe each retained Bearer principal independently of the newest cookie.
    client.cookies.clear()
    # Probe each retained Bearer identity independently of the last bootstrap cookie.
    client.cookies.clear()
    first = _change(client, headers, first, "paused")
    assert first["intake_profile_count"] == 1
    scoped = client.get("/api/ip/watch", headers=headers, params={"docket_id": docket["id"]})
    assert scoped.status_code == 200
    assert scoped.json()["intake_profile_count"] == 1
    assert [row["id"] for row in scoped.json()["profiles"]] == [first["id"]]
    second = _change(client, headers, second, "paused")
    assert second["intake_profile_count"] == 0
    first = _change(client, headers, first, "active")
    assert first["intake_profile_count"] == 1
    first = _change(client, headers, first, "disabled")
    assert first["intake_profile_count"] == 0
    # A quota-paused profile remains in the existing intake predicate: its
    # captured attempt must explain the quota, rather than claim no profile.
    with get_session_factory()() as session:
        row = session.get(IpWatchProfile, second["id"])
        row.poll_status = "paused_cost_quota"
        row.version += 1
        session.commit()
        second["version"] = row.version
    scoped = client.get("/api/ip/watch", headers=headers, params={"docket_id": docket["id"]})
    assert scoped.status_code == 200 and scoped.json()["intake_profile_count"] == 1
    second = _change(client, headers, second, "paused")
    assert second["intake_profile_count"] == 0
    foreign_read = client.get("/api/ip/watch", headers=foreign_headers)
    assert foreign_read.status_code == 200 and foreign_read.json()["intake_profile_count"] == 1


def _persisted(profile_id: str) -> tuple:
    with get_session_factory()() as session:
        row = session.get(IpWatchProfile, profile_id)
        audits = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.company_id == row.company_id,
                AuditEvent.target_id == profile_id,
                AuditEvent.action == "ip_watch.profile_status_changed",
            )
        )
        return row.version, row.poll_status, row.pause_reason, row.next_poll_at, audits


def _rollback_journey(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.headers.update({"X-CaseOps-Automated-Test": "no-paid-providers"})
    owner, headers, docket, _ = _fixture(client, "INTAKE ROLLBACK")
    profile = _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=owner["membership"]["id"]
    )
    before = _persisted(profile["id"])

    entered = []

    def unavailable(*_args, **_kwargs):
        entered.append("intake-count")
        raise HTTPException(status_code=503, detail="Synthetic intake-count read unavailable.")

    with monkeypatch.context() as patch:
        patch.setattr(ip_watch, "_intake_profile_count", unavailable)
        response = client.post(
            f"/api/ip/watch/profiles/{profile['id']}/status",
            headers=headers,
            json={
                "expected_version": profile["version"],
                "poll_status": "paused",
                "reason": "Synthetic rollback acceptance",
            },
        )
        assert response.status_code == 503
        assert entered == ["intake-count"]
        # A fresh session proves rollback; a failed response alone is insufficient.
        after_failure = _persisted(profile["id"])
        assert after_failure == before
    acknowledged = _change(client, headers, profile, "paused")
    assert acknowledged["intake_profile_count"] == 0
    after = _persisted(profile["id"])
    assert after[0] == before[0] + 1 and after[1] == "paused" and after[-1] == before[-1] + 1


def test_confirmed_intake_counts_across_dockets_and_tenants(client: TestClient) -> None:
    _count_journey(client)


def test_failed_intake_count_read_rolls_back_profile_and_audit(
    client: TestClient, monkeypatch
) -> None:
    _rollback_journey(client, monkeypatch)


@pytest.mark.postgres
def test_confirmed_intake_counts_across_dockets_and_tenants_postgres(client: TestClient) -> None:
    _count_journey(client)


@pytest.mark.postgres
def test_failed_intake_count_read_rolls_back_profile_and_audit_postgres(
    client: TestClient, monkeypatch
) -> None:
    _rollback_journey(client, monkeypatch)
