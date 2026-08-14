"""IPLF-031A duplicate identifier reconciliation (IP-ID-07, UJ-05).

Duplicate *detection* already existed: a colliding identifier is stored with
``reconciliation_status="needs_review"``, and an unconfirmed application number
blocks the filing from entering ``filed`` phase. Nothing could ever clear that
state, so a genuine duplicate permanently dead-ended the record. This module
covers the resolution workflow.

Stable manifest test IDs:

* ``IPLF-UJ-05-NORMAL``   detect and resolve a duplicate
* ``IPLF-UJ-05-EXC-01``   conflicting state/client/permission blocks auto-merge
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _docket(
    client: TestClient,
    headers: dict[str, str],
    *,
    matter_id: str,
    title: str,
    restricted: bool = False,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": restricted,
            "particulars": _particulars(title.upper()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _filing(
    client: TestClient,
    headers: dict[str, str],
    *,
    docket_id: str,
    mark: str = "Aster Mark",
    raw_value: str = "TM 1234567",
) -> dict:
    """Create a mark plus a filing that carries an application number."""

    asset = client.post(
        f"/api/ip/dockets/{docket_id}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": mark},
    )
    assert asset.status_code == 201, asset.text
    response = client.post(
        f"/api/ip/dockets/{docket_id}/applications",
        headers=headers,
        json={
            "asset_id": asset.json()["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "draft",
            "application_number": {
                "raw_value": raw_value,
                "source": "manual",
                "effective_from": "2026-01-01",
                "is_primary": True,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, headers, docket_id: str, identifier_id: str):
    return client.get(
        f"/api/ip/dockets/{docket_id}/identifiers/{identifier_id}/duplicates",
        headers=headers,
    )


def _reconcile(client, headers, docket_id: str, identifier_id: str, **body):
    return client.post(
        f"/api/ip/dockets/{docket_id}/identifiers/{identifier_id}/reconcile",
        headers=headers,
        json=body,
    )


def _setup(client: TestClient, *, second_matter: bool = False, restricted: bool = False):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-DUP-031A")
    first = _docket(client, headers, matter_id=matter["id"], title="Original Mark")
    other_matter = (
        _mk_matter(client, token, "IP-DUP-031A-B")["id"] if second_matter else matter["id"]
    )
    second = _docket(
        client,
        headers,
        matter_id=other_matter,
        title="Colliding Mark",
        restricted=restricted,
    )
    original = _filing(client, headers, docket_id=first["id"], mark="Original Mark")
    collision = _filing(client, headers, docket_id=second["id"], mark="Colliding Mark")
    return headers, first, second, original, collision


def test_uj05_normal_detect_and_resolve_duplicate(client: TestClient) -> None:
    """IPLF-UJ-05-NORMAL — a flagged duplicate is resolvable by explicit decision."""

    headers, _first, second, original, collision = _setup(client)

    # Detection: the colliding identifier is flagged, not silently merged.
    identifier = collision["identifier"]
    assert identifier["reconciliation_status"] == "needs_review"
    assert original["identifier"]["reconciliation_status"] == "confirmed"

    preview = _preview(client, headers, second["id"], identifier["id"])
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [c["identifier_id"] for c in body["candidates"]] == [
        original["identifier"]["id"]
    ]
    assert body["automatic_merge_blocked"] is False
    assert set(body["allowed_decisions"]) == {"distinct", "supersede"}

    # A stale token cannot resolve.
    stale = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="distinct",
        decision_token="stale",
        reason="Independent filing confirmed against the register.",
    )
    assert stale.status_code == 409
    assert "preview again" in stale.json()["detail"].lower()

    # Resolving as distinct clears review and records the reason.
    resolved = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="distinct",
        decision_token=body["decision_token"],
        reason="Independent filing confirmed against the register.",
    )
    assert resolved.status_code == 200, resolved.text
    payload = resolved.json()
    assert payload["decision"] == "distinct"
    assert payload["identifier"]["reconciliation_status"] == "confirmed"
    assert payload["identifier"]["effective_until"] is None
    assert (
        payload["identifier"]["correction_reason"]
        == "Independent filing confirmed against the register."
    )

    # The decision is terminal: it cannot be replayed.
    again = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="distinct",
        decision_token=body["decision_token"],
        reason="Independent filing confirmed against the register.",
    )
    assert again.status_code == 409
    assert "awaiting review" in again.json()["detail"].lower()


def test_uj05_normal_supersede_preserves_prior_value(client: TestClient) -> None:
    """IPLF-UJ-05-NORMAL — supersession retires the duplicate without deleting it."""

    headers, _first, second, original, collision = _setup(client)
    identifier = collision["identifier"]
    body = _preview(client, headers, second["id"], identifier["id"]).json()

    # Supersession must name a candidate from the preview.
    bad = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="supersede",
        decision_token=body["decision_token"],
        reason="Duplicate of the original filing.",
        superseded_by_identifier_id="not-a-candidate",
    )
    assert bad.status_code == 409

    resolved = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="supersede",
        decision_token=body["decision_token"],
        reason="Duplicate of the original filing.",
        superseded_by_identifier_id=original["identifier"]["id"],
    )
    assert resolved.status_code == 200, resolved.text
    retired = resolved.json()["identifier"]
    # IP-ID-08: prior value and reason survive; the row is retired, not deleted.
    assert retired["reconciliation_status"] == "superseded"
    assert retired["effective_until"] is not None
    assert retired["raw_value"] == "TM 1234567"
    assert retired["supersedes_identifier_id"] == original["identifier"]["id"]
    assert retired["is_primary"] is False
    assert retired["correction_reason"] == "Duplicate of the original filing."


def test_uj05_exc01_conflicting_client_blocks_automatic_merge(
    client: TestClient,
) -> None:
    """IPLF-UJ-05-EXC-01 — a different client matter forbids automatic merge."""

    headers, _first, second, original, collision = _setup(client, second_matter=True)
    identifier = collision["identifier"]

    body = _preview(client, headers, second["id"], identifier["id"]).json()
    assert body["automatic_merge_blocked"] is True
    assert "different_client_matter" in body["blocking_reasons"]
    assert body["allowed_decisions"] == ["distinct"]

    blocked = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="supersede",
        decision_token=body["decision_token"],
        reason="Attempting a cross-client merge.",
        superseded_by_identifier_id=original["identifier"]["id"],
    )
    assert blocked.status_code == 409
    # The RFC 7807 handler flattens a structured detail: the message becomes
    # `detail` and the remaining keys are hoisted to the top level.
    problem = blocked.json()
    assert problem["code"] == "ip_duplicate_merge_blocked"
    assert "different_client_matter" in problem["blocking_reasons"]

    # The owner may still record an explicit distinct decision.
    allowed = _reconcile(
        client,
        headers,
        second["id"],
        identifier["id"],
        decision="distinct",
        decision_token=body["decision_token"],
        reason="Separate client filed an identical number; kept distinct.",
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["identifier"]["reconciliation_status"] == "confirmed"


def test_uj05_exc01_privileged_mismatch_blocks_automatic_merge(
    client: TestClient,
) -> None:
    """IPLF-UJ-05-EXC-01 — a restricted counterpart forbids automatic merge."""

    headers, _first, second, _original, collision = _setup(client, restricted=True)
    identifier = collision["identifier"]

    body = _preview(client, headers, second["id"], identifier["id"]).json()
    assert body["automatic_merge_blocked"] is True
    assert "privileged_permission_mismatch" in body["blocking_reasons"]
    assert body["allowed_decisions"] == ["distinct"]


def test_duplicate_preview_is_access_scoped_and_tenant_isolated(
    client: TestClient,
) -> None:
    """A competing record the caller cannot open must not leak through preview."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)

    created = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Dup Associate",
            "email": "dup-associate@asterlegal.in",
            "password": "DupAssociate123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "dup-associate@asterlegal.in",
            "password": "DupAssociate123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    associate_headers = auth_headers(str(login.json()["access_token"]))

    matter = _mk_matter(client, owner_token, "IP-DUP-031A-ACL")
    hidden = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Hidden Original",
        restricted=True,
    )
    open_docket = _docket(
        client, owner_headers, matter_id=matter["id"], title="Visible Collision"
    )
    hidden_identifier = _filing(client, owner_headers, docket_id=hidden["id"], mark="Hidden Mark")
    collision = _filing(client, owner_headers, docket_id=open_docket["id"], mark="Visible Mark")
    identifier_id = collision["identifier"]["id"]

    # The owner sees the restricted counterpart.
    owner_preview = _preview(
        client, owner_headers, open_docket["id"], identifier_id
    ).json()
    assert [c["identifier_id"] for c in owner_preview["candidates"]] == [
        hidden_identifier["identifier"]["id"]
    ]

    # The associate does not: no candidate, no id, no title.
    scoped = _preview(client, associate_headers, open_docket["id"], identifier_id).json()
    assert scoped["candidates"] == []
    assert scoped["allowed_decisions"] == ["distinct"]
    serialized = str(scoped)
    assert hidden["id"] not in serialized
    assert hidden_identifier["identifier"]["id"] not in serialized
    assert "Hidden Original" not in serialized

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Dup Firm",
            "company_slug": "other-dup-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-dup.example",
            "owner_password": "OtherDup123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    assert (
        _preview(client, other_headers, open_docket["id"], identifier_id).status_code
        == 404
    )
