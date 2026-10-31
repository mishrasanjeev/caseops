"""BUG-008: the recordal Instrument picker offers exactly what the validator accepts.

Ram's recordal form was a dead end: each party's Instrument picker listed only
documents ticked in a separate checkbox list, and GET /api/ip/documents?docket_id=
returned direct docket links only while the write validator also accepted
documents linked to the docket's events and deadlines. GET
/api/ip/recordals/instruments is built from the validator's own predicate.

No fixture here calls /api/ip/document-taxonomy/seed or inserts document rows:
instruments are uploaded through POST /api/ip/documents/upload, which
provisions the default classifications for a configured workspace.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, IpDocketEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_taxonomy_provisioning_20261031 import (
    _bootstrap,
    _create_docket,
    enable_ip_workspace,
)
from tests.test_ip_nice_classes_20261031 import _member_without_ip_read

ROUTE = "/api/ip/recordals/instruments"


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    links: list[dict[str, str]],
) -> str:
    response = client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": "assignment",
                    "title": title,
                    "confidentiality": "internal",
                    "is_privileged": False,
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "document_date": "2026-10-31",
                    "links": links,
                }
            )
        },
        files={"upload": (f"{title}.txt", f"{title} executed copy. ".encode() * 20, "text/plain")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "created", body
    return str(body["document"]["id"])


def _docket_event_id(client: TestClient, headers: dict[str, str], docket_id: str) -> str:
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    me = client.get("/api/auth/me", headers=headers)
    created = client.post(
        f"/api/ip/dockets/{docket_id}/events",
        headers=headers,
        json={
            "event_kind": "examination_report",
            "source": "manual",
            "effective_at": "2026-10-20T09:00:00Z",
            "reason": "Examination report received from the registry.",
            "responsible_membership_id": me.json()["membership"]["id"],
            "expected_lifecycle_version": docket.json()["lifecycle_version"],
        },
    )
    assert created.status_code == 201, created.text
    with get_session_factory()() as session:
        stored = session.get(IpDocketEvent, created.json()["id"])
        assert stored is not None and stored.docket_id == docket_id
    return str(created.json()["id"])


def _assignment(client: TestClient, headers: dict[str, str], docket_id: str, refs: list[str]):
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert docket.status_code == 200, docket.text
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return client.post(
        "/api/ip/recordals",
        headers=headers,
        json={
            "docket_id": docket_id,
            "expected_lifecycle_version": docket.json()["lifecycle_version"],
            "responsible_membership_id": me.json()["membership"]["id"],
            "reason": "Record the executed assignment.",
            "recordal_type": "assignment",
            "legal_basis": "Trade Marks Act, 1999, section 45",
            "form_code": "TM-P",
            "parties": [
                {"role": "assignor", "name": "Oldco Brands Limited", "evidence_reference": refs[0]},
                {"role": "assignee", "name": "Newco IP LLP", "evidence_reference": refs[-1]},
            ],
            "executed_on": "2026-10-01",
            "effective_on": "2026-10-01",
            "affected_registration_refs": ["TM-1234567"],
            "supporting_instrument_refs": refs,
        },
    )


def test_instrument_options_match_the_recordal_validator(client: TestClient) -> None:
    tenant = _bootstrap(client, "recordal-instruments-firm")
    headers = auth_headers(str(tenant["access_token"]))
    enable_ip_workspace(client, headers, str(tenant["membership"]["id"]))
    docket_id = _create_docket(client, headers)
    other_docket_id = _create_docket(client, headers)
    direct = _upload(client, headers, title="Deed linked to the docket",
                     links=[{"target_type": "docket", "target_id": docket_id}])
    via_event = _upload(client, headers, title="Deed linked to a docket event",
                        links=[{"target_type": "event",
                               "target_id": _docket_event_id(client, headers, docket_id)}])
    elsewhere = _upload(client, headers, title="Deed on another docket",
                        links=[{"target_type": "docket", "target_id": other_docket_id}])

    options = client.get(ROUTE, headers=headers, params={"docket_id": docket_id})
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["docket_id"] == docket_id
    assert body["truncated"] is False
    offered = {row["id"] for row in body["items"]}
    # The event-linked deed is offered (GET /documents?docket_id= used to hide it).
    assert offered == {direct, via_event}
    titles = {row["id"]: row["title"] for row in body["items"]}
    assert titles[via_event] == "Deed linked to a docket event"
    other = client.get(ROUTE, headers=headers, params={"docket_id": other_docket_id})
    assert {row["id"] for row in other.json()["items"]} == {elsewhere}

    # Everything offered is accepted, including both parties citing different instruments.
    created = _assignment(client, headers, docket_id, [direct, via_event])
    assert created.status_code == 201, created.text
    assert created.json()["supporting_instrument_refs_json"] == [direct, via_event]
    # Anything not offered is refused.
    refused = _assignment(client, headers, docket_id, [elsewhere])
    assert refused.status_code == 422
    assert "linked to the selected docket" in refused.text

    # The recordal workspace uses the same predicate for its transaction document picker.
    workspace = client.get(f"/api/ip/recordals/{created.json()['id']}/workspace", headers=headers)
    assert workspace.status_code == 200, workspace.text
    assert {row["id"] for row in workspace.json()["documents"]} == {direct, via_event}

    # The list names each recordal's docket instead of leaving the page to show its id.
    listed = client.get("/api/ip/recordals", headers=headers)
    assert listed.status_code == 200, listed.text
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    assert [(row["id"], row["docket_title"]) for row in listed.json()["items"]] == [
        (created.json()["id"], docket["title"])
    ]


def test_instrument_options_are_tenant_scoped_and_need_ip_read(client: TestClient) -> None:
    owner = auth_headers(str(bootstrap_company(client)["access_token"]))
    me = client.get("/api/auth/me", headers=owner).json()
    enable_ip_workspace(client, owner, str(me["membership"]["id"]))
    docket_id = _create_docket(client, owner)
    deed = _upload(client, owner, title="Aster assignment deed",
                   links=[{"target_type": "docket", "target_id": docket_id}])

    other = _bootstrap(client, "recordal-instruments-rival")
    other_headers = auth_headers(str(other["access_token"]))
    enable_ip_workspace(client, other_headers, str(other["membership"]["id"]))
    other_docket = _create_docket(client, other_headers)

    # Another tenant cannot list this docket's instruments or learn that it exists.
    foreign = client.get(ROUTE, headers=other_headers, params={"docket_id": docket_id})
    assert foreign.status_code == 404
    assert "Aster assignment deed" not in foreign.text
    # Nor cite this tenant's document on its own docket.
    cross = _assignment(client, other_headers, other_docket, [deed])
    assert cross.status_code == 422
    assert client.get(ROUTE, headers=other_headers, params={"docket_id": other_docket}).json()[
        "items"
    ] == []

    clerk = _member_without_ip_read(client, owner)
    denied = client.get(ROUTE, headers=clerk, params={"docket_id": docket_id})
    assert denied.status_code == 403
    assert "Aster assignment deed" not in denied.text
    client.cookies.clear()
    assert client.get(ROUTE, params={"docket_id": docket_id}).status_code == 401
    assert client.get(ROUTE, headers=owner, params={"docket_id": ""}).status_code == 422

    # Reading options is not an auditable mutation; creating a recordal still is.
    with get_session_factory()() as session:
        actions = set(session.scalars(select(AuditEvent.action)))
    assert not any("instrument" in action for action in actions)
