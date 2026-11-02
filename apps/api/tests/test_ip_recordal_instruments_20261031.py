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

    # A transaction sent without a time is stamped by the server's clock, after
    # the recordal's own creation event, so it is never refused as backdated.
    me = client.get("/api/auth/me", headers=headers).json()
    withdrawn = client.post(
        f"/api/ip/recordals/{created.json()['id']}/transactions",
        headers=headers,
        json={
            "expected_version": created.json()["version"],
            "expected_lifecycle_version": docket["lifecycle_version"],
            "transaction_kind": "withdrawn",
            "responsible_membership_id": me["membership"]["id"],
            "reason": "Client withdrew the instruction.",
        },
    )
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["recordal"]["status"] == "withdrawn"
    assert withdrawn.json()["event"]["effective_at"] >= workspace.json()["transactions"][-1][
        "effective_at"
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


def _colleague(client: TestClient, owner: dict[str, str], slug: str) -> dict[str, str]:
    """A same-company IP admin created through the product's user API."""

    created = client.post(
        "/api/companies/current/users",
        headers=owner,
        json={
            "full_name": "Walled Colleague",
            "email": f"walled@{slug}.example",
            "role": "admin",
            "password": "WalledPass123!",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": slug,
            "email": f"walled@{slug}.example",
            "password": "WalledPass123!",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return auth_headers(str(login.json()["access_token"]))


def _restricted_docket(client: TestClient, headers: dict[str, str]) -> str:
    """A restricted docket: only its creator holds the seeded access grant."""

    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Restricted ASTER portfolio",
            "restricted": True,
            "particulars": {
                "form_key": "TM-A",
                "form_version": "2026.1",
                "mark_kind": "word",
                "representation": {"text": "ASTER"},
                "classes": [{"class_number": 9, "specification": "Downloadable software"}],
                "parties": [{"role": "applicant", "name": "Aster Holdings LLP"}],
                "filing_manifest": [
                    {
                        "key": "representation",
                        "label": "Mark representation",
                        "required": True,
                        "evidence_reference": "fixture:recordal-wall",
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_walled_colleague_cannot_list_or_cite_and_co_linked_deeds_follow_access(
    client: TestClient,
) -> None:
    slug = "recordal-instruments-wall"
    tenant = _bootstrap(client, slug)
    owner = auth_headers(str(tenant["access_token"]))
    enable_ip_workspace(client, owner, str(tenant["membership"]["id"]))
    open_docket = _create_docket(client, owner)
    walled_docket = _restricted_docket(client, owner)
    colleague = _colleague(client, owner, slug)

    walled_deed = _upload(client, owner, title="Deed on the walled docket",
                          links=[{"target_type": "docket", "target_id": walled_docket}])
    shared_deed = _upload(client, owner, title="Deed on the open docket",
                          links=[{"target_type": "docket", "target_id": open_docket}])
    co_linked = _upload(client, owner, title="Deed also filed on the walled docket",
                        links=[{"target_type": "docket", "target_id": open_docket},
                               {"target_type": "docket", "target_id": walled_docket}])

    # (a) The walled docket does not exist for the colleague: no list, no recordal.
    hidden = client.get(ROUTE, headers=colleague, params={"docket_id": walled_docket})
    assert hidden.status_code == 404
    assert "Deed on the walled docket" not in hidden.text
    assert client.get(f"/api/ip/dockets/{walled_docket}", headers=colleague).status_code == 404
    colleague_me = client.get("/api/auth/me", headers=colleague).json()
    refused = client.post(
        "/api/ip/recordals",
        headers=colleague,
        json={
            "docket_id": walled_docket,
            "expected_lifecycle_version": 1,
            "responsible_membership_id": colleague_me["membership"]["id"],
            "reason": "Record the executed assignment.",
            "recordal_type": "assignment",
            "legal_basis": "Trade Marks Act, 1999, section 45",
            "form_code": "TM-P",
            "parties": [
                {"role": "assignor", "name": "Oldco", "evidence_reference": walled_deed},
                {"role": "assignee", "name": "Newco", "evidence_reference": walled_deed},
            ],
            "executed_on": "2026-10-01",
            "effective_on": "2026-10-01",
            "affected_registration_refs": ["TM-1234567"],
            "supporting_instrument_refs": [walled_deed],
        },
    )
    assert refused.status_code == 404, refused.text
    assert "Deed on the walled docket" not in refused.text

    # (b) A deed co-linked to a docket the viewer cannot see is neither offered nor accepted
    # for that viewer, while the owner, who can see both dockets, is offered it and may cite it.
    offered = client.get(ROUTE, headers=colleague, params={"docket_id": open_docket})
    assert offered.status_code == 200, offered.text
    assert [row["id"] for row in offered.json()["items"]] == [shared_deed]
    assert offered.json()["truncated"] is False
    cited = _assignment(client, colleague, open_docket, [shared_deed, co_linked])
    assert cited.status_code == 422, cited.text
    assert "linked to the selected docket" in cited.text

    owner_offered = client.get(ROUTE, headers=owner, params={"docket_id": open_docket})
    assert {row["id"] for row in owner_offered.json()["items"]} == {shared_deed, co_linked}
    accepted = _assignment(client, owner, open_docket, [shared_deed, co_linked])
    assert accepted.status_code == 201, accepted.text


def test_truncation_counts_only_documents_the_viewer_may_cite(
    client: TestClient, monkeypatch
) -> None:
    from caseops_api.services import ip_recordals

    slug = "recordal-instruments-bound"
    tenant = _bootstrap(client, slug)
    owner = auth_headers(str(tenant["access_token"]))
    enable_ip_workspace(client, owner, str(tenant["membership"]["id"]))
    docket_id = _create_docket(client, owner)
    walled_docket = _restricted_docket(client, owner)
    colleague = _colleague(client, owner, slug)
    older = _upload(client, owner, title="Older deed",
                    links=[{"target_type": "docket", "target_id": docket_id}])
    newer = _upload(client, owner, title="Newer deed",
                    links=[{"target_type": "docket", "target_id": docket_id}])
    # Newest of all, and invisible to the colleague: it must not use up their bound.
    _upload(client, owner, title="Newest deed, co-linked to the walled docket",
            links=[{"target_type": "docket", "target_id": docket_id},
                   {"target_type": "docket", "target_id": walled_docket}])

    monkeypatch.setattr(ip_recordals, "RECORDAL_INSTRUMENT_LIMIT", 2)
    colleague_view = client.get(ROUTE, headers=colleague, params={"docket_id": docket_id}).json()
    assert [row["id"] for row in colleague_view["items"]] == [newer, older]
    assert colleague_view["truncated"] is False
    owner_view = client.get(ROUTE, headers=owner, params={"docket_id": docket_id}).json()
    assert len(owner_view["items"]) == 2
    assert owner_view["truncated"] is True

    monkeypatch.setattr(ip_recordals, "RECORDAL_INSTRUMENT_LIMIT", 1)
    colleague_view = client.get(ROUTE, headers=colleague, params={"docket_id": docket_id}).json()
    assert [row["id"] for row in colleague_view["items"]] == [newer]
    assert colleague_view["truncated"] is True


def test_deadline_linked_deed_is_offered_and_accepted(client: TestClient, monkeypatch) -> None:
    from caseops_api.core.settings import get_settings
    from tests.test_ip_deadline_terminal_state import _confirmed_deadline

    # Creating the governed deadline needs rule governance, which defaults off.
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    legal_headers, legal_id, _reviewer, deadline, docket_id = _confirmed_deadline(client)
    enable_ip_workspace(client, legal_headers, legal_id)
    via_deadline = _upload(client, legal_headers, title="Deed filed against the deadline",
                           links=[{"target_type": "deadline", "target_id": deadline["id"]}])

    offered = client.get(ROUTE, headers=legal_headers, params={"docket_id": docket_id})
    assert offered.status_code == 200, offered.text
    assert [row["id"] for row in offered.json()["items"]] == [via_deadline]
    created = _assignment(client, legal_headers, docket_id, [via_deadline])
    assert created.status_code == 201, created.text
    assert created.json()["supporting_instrument_refs_json"] == [via_deadline]
