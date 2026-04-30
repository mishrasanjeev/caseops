"""Tests for the matter conflict-check workflow (PG-001)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _new_matter(
    client: TestClient,
    *,
    token: str,
    code: str,
    title: str,
    client_name: str,
    opposing: str | None = None,
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
            "status": "active",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


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
