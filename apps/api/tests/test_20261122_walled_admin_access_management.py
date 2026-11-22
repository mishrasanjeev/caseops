"""An admin who cannot open a record cannot manage its access (SEC-004).

IP docket access management and employee off-boarding follow the same
visibility rule as every read: a walled admin, or one without a grant on a
restricted record, gets the
audited "not found" (IP) or an explicit, name-free refusal (off-boarding).
Owners stay exempt; unwalled admins keep working; other tenants get 404.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, MatterAccessGrant
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company

PASSWORD = "WalledAdmin123!"


def _invite(client: TestClient, owner_token: str, email: str, role: str) -> tuple[str, dict]:
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={"full_name": email.split("@")[0], "email": email, "role": role, "password": PASSWORD},
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": "aster-legal", "email": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return str(created.json()["membership_id"]), auth_headers(str(login.json()["access_token"]))


def _denials(company_id: str, target_id: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "access_denied",
                    AuditEvent.target_id == target_id,
                )
            )
        )


def _other_tenant(client: TestClient) -> dict:
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Firm LLP",
            "company_slug": "walled-admin-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@walled-admin-other.example",
            "owner_password": "OtherOwner123!",
        },
    )
    assert other.status_code == 200, other.text
    return auth_headers(str(other.json()["access_token"]))


# ---------------------------------------------------------------------------
# IP docket access management
# ---------------------------------------------------------------------------


def _docket(client: TestClient, headers: dict, *, restricted: bool, mark: str) -> str:
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": f"{mark} trade mark",
            "restricted": restricted,
            "particulars": {
                "form_key": "TM-A",
                "form_version": "2026.1",
                "mark_kind": "word",
                "representation": {"text": mark},
                "classes": [{"class_number": 9, "specification": "Downloadable software"}],
                "parties": [{"role": "applicant", "name": "Aster Legal LLP"}],
                "filing_manifest": [
                    {
                        "key": "representation",
                        "label": "Mark representation",
                        "required": True,
                        "evidence_reference": "fixture:walled-admin",
                    }
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _panel(client: TestClient, headers: dict, docket_id: str):
    return client.get(f"/api/ip/dockets/{docket_id}/access", headers=headers)


def _change(subject_id: str, version: int, action: str = "add_wall") -> dict:
    return {
        "action": action,
        "expected_access_policy_version": version,
        "reason": "Conflict found at intake for this IP record.",
        "subject_type": "membership",
        "subject_id": subject_id,
    }


def _preview_and_apply(client: TestClient, headers: dict, docket_id: str, payload: dict):
    preview = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview", headers=headers, json=payload
    )
    assert preview.status_code == 200, preview.text
    applied = client.post(
        f"/api/ip/dockets/{docket_id}/access/apply",
        headers=headers,
        json={**payload, "preview_token": preview.json()["preview_token"]},
    )
    assert applied.status_code == 200, applied.text
    return applied.json()


def test_walled_admin_cannot_read_preview_or_apply_ip_docket_access(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner = auth_headers(owner_token)
    company_id = str(boot["company"]["id"])
    walled_id, walled = _invite(client, owner_token, "ip-walled-admin@asterlegal.in", "admin")
    free_id, free = _invite(client, owner_token, "ip-free-admin@asterlegal.in", "admin")
    member_id, _ = _invite(client, owner_token, "ip-member@asterlegal.in", "member")
    docket_id = _docket(client, owner, restricted=False, mark="WALLMARK")

    version = _panel(client, owner, docket_id).json()["access_policy_version"]
    applied = _preview_and_apply(client, owner, docket_id, _change(walled_id, version))
    version = applied["panel"]["access_policy_version"]
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=walled).status_code == 404
    before = _panel(client, owner, docket_id).json()
    denied_before = len(_denials(company_id, docket_id))  # includes the read above

    # Panel, preview and apply all answer like a read of a hidden docket.
    wall_row = next(row for row in before["walls"] if row["subject_id"] == walled_id)
    lift_own = {
        "action": "revoke_wall",
        "expected_access_policy_version": version,
        "reason": "Trying to lift my own wall.",
        "wall_id": wall_row["id"],
    }
    attempts = [
        _panel(client, walled, docket_id),
        client.post(f"/api/ip/dockets/{docket_id}/access/preview", headers=walled, json=lift_own),
        client.post(
            f"/api/ip/dockets/{docket_id}/access/preview",
            headers=walled,
            json=_change(member_id, version),
        ),
        client.post(
            f"/api/ip/dockets/{docket_id}/access/apply",
            headers=walled,
            json={**lift_own, "preview_token": "x" * 64},
        ),
    ]
    assert [r.status_code for r in attempts] == [404] * len(attempts)
    assert all(r.json()["detail"] == "IP docket record not found." for r in attempts)
    denials = _denials(company_id, docket_id)[denied_before:]
    assert len(denials) == len(attempts)
    assert {e.actor_membership_id for e in denials} == {walled_id}
    assert _panel(client, owner, docket_id).json() == before

    # An unwalled admin still manages the same docket.
    assert _panel(client, free, docket_id).status_code == 200
    by_free = _preview_and_apply(client, free, docket_id, _change(member_id, version))
    assert by_free["panel"]["access_policy_version"] == version + 1
    assert free_id != walled_id


def test_owner_manages_ip_access_it_cannot_read_and_other_tenants_get_404(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner = auth_headers(owner_token)
    _, creator = _invite(client, owner_token, "ip-creator-admin@asterlegal.in", "admin")
    member_id, _ = _invite(client, owner_token, "ip-member2@asterlegal.in", "member")
    # Restricted record created by an admin: only the creator holds a grant, so
    # the IP read policy (which does not exempt owners) hides it from the owner.
    docket_id = _docket(client, creator, restricted=True, mark="OWNERMARK")
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=owner).status_code == 404

    panel = _panel(client, owner, docket_id)
    assert panel.status_code == 200, panel.text
    version = panel.json()["access_policy_version"]
    applied = _preview_and_apply(client, owner, docket_id, _change(member_id, version, "grant"))
    assert applied["panel"]["access_policy_version"] == version + 1

    other = _other_tenant(client)
    assert _panel(client, other, docket_id).status_code == 404
    cross = client.post(
        f"/api/ip/dockets/{docket_id}/access/preview",
        headers=other,
        json=_change(member_id, version + 1),
    )
    assert cross.status_code == 404


# ---------------------------------------------------------------------------
# Employee off-boarding
# ---------------------------------------------------------------------------


def _matter(client: TestClient, headers: dict, code: str) -> str:
    created = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": f"Offboarding {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert created.status_code == 200, created.text
    return str(created.json()["id"])


def _grant(client: TestClient, headers: dict, matter_id: str, membership_id: str) -> str:
    granted = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=headers,
        json={"membership_id": membership_id, "reason": "Assigned to the brief."},
    )
    assert granted.status_code == 200, granted.text
    return str(granted.json()["id"])


def _grant_holder(grant_id: str) -> str:
    with get_session_factory()() as session:
        return str(session.get(MatterAccessGrant, grant_id).membership_id)


def test_walled_admin_cannot_offboard_grants_on_walled_matter(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    owner = auth_headers(owner_token)
    walled_id, walled = _invite(client, owner_token, "off-walled-admin@asterlegal.in", "admin")
    _, free = _invite(client, owner_token, "off-free-admin@asterlegal.in", "admin")
    leaver_a, _ = _invite(client, owner_token, "off-leaver-a@asterlegal.in", "member")
    leaver_b, _ = _invite(client, owner_token, "off-leaver-b@asterlegal.in", "member")
    replacement, _ = _invite(client, owner_token, "off-replacement@asterlegal.in", "member")
    walled_matter = _matter(client, owner, "OFF-WALLED")
    grant_a = _grant(client, owner, walled_matter, leaver_a)
    grant_b = _grant(client, owner, walled_matter, leaver_b)
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=owner,
        json={"excluded_membership_id": walled_id, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text
    body = {"reassign_to_membership_id": replacement}
    base = f"/api/companies/current/employees/{leaver_a}/offboarding"

    preview = client.post(f"{base}/preview", headers=walled, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    refusal = (
        "You cannot act on 1 affected Matter that you are walled or restricted from."
    )
    assert any(b.startswith(refusal) for b in preview.json()["blockers"])
    assert not any("OFF-WALLED" in b for b in preview.json()["blockers"])

    commit = client.post(f"{base}/commit", headers=walled, json=body)
    assert commit.status_code == 400, commit.text
    assert refusal in commit.json()["detail"]
    assert "OFF-WALLED" not in commit.json()["detail"]
    assert _grant_holder(grant_a) == leaver_a

    # An unwalled admin completes the same off-boarding.
    done = client.post(f"{base}/commit", headers=free, json=body)
    assert done.status_code == 200, done.text
    assert _grant_holder(grant_a) == replacement

    # The owner also can, for the second leaver.
    owner_done = client.post(
        f"/api/companies/current/employees/{leaver_b}/offboarding/commit",
        headers=owner,
        json=body,
    )
    assert owner_done.status_code == 200, owner_done.text
    with get_session_factory()() as session:
        # Merged into the replacement's existing grant on the same Matter.
        assert session.get(MatterAccessGrant, grant_b) is None

    other = _other_tenant(client)
    cross = client.post(
        f"/api/companies/current/employees/{leaver_b}/offboarding/preview",
        headers=other,
        json=body,
    )
    assert cross.status_code == 404
