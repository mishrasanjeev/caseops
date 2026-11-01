"""B4-ADJ-06 / B4-ADJ-07 (Ram batch 4 adjacent defects, 2026-11-01).

ADJ-07: an IP document could not be retired, so every tester upload stayed in
the tenant for good. Retirement is audited, never a hard delete: the document
stays readable in history, leaves every picker and write validator, and is
refused while a record that cited it still relies on it.

ADJ-06: GET /api/ip/documents?docket_id= returned direct docket links only,
while the recordal, Madrid and foreign-associate validators accept documents
linked to the docket's events and deadlines.

Documents are uploaded through POST /api/ip/documents/upload; no fixture here
inserts document rows or calls the taxonomy seed endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, IpDocument
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_document_taxonomy_provisioning_20261031 import (
    _bootstrap,
    _create_docket,
    enable_ip_workspace,
)
from tests.test_ip_recordal_instruments_20261031 import (
    _assignment,
    _colleague,
    _docket_event_id,
    _restricted_docket,
    _upload,
)

LIST = "/api/ip/documents"


def _tenant(client: TestClient, slug: str) -> tuple[dict[str, str], str]:
    tenant = _bootstrap(client, slug)
    headers = auth_headers(str(tenant["access_token"]))
    enable_ip_workspace(client, headers, str(tenant["membership"]["id"]))
    return headers, str(tenant["membership"]["id"])


def _ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(body["items"])
    return [row["id"] for row in body["items"]]


def _retire(client: TestClient, headers: dict[str, str], document_id: str, reason: str):
    current = client.get(f"{LIST}/{document_id}", headers=headers)
    assert current.status_code == 200, current.text
    return client.post(
        f"{LIST}/{document_id}/retire",
        headers=headers,
        json={"expected_current_version": current.json()["current_version"], "reason": reason},
    )


def _user(client: TestClient, owner: dict[str, str], slug: str, role: str) -> dict[str, str]:
    email = f"{role}@{slug}.example"
    created = client.post(
        "/api/companies/current/users",
        headers=owner,
        json={"full_name": f"Synthetic {role}", "email": email, "role": role,
              "password": "SyntheticPass2026!"},
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": slug, "email": email, "password": "SyntheticPass2026!"},
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return auth_headers(str(login.json()["access_token"]))


def _retire_docket(client: TestClient, headers: dict[str, str], docket_id: str) -> None:
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    body = {
        "expected_lifecycle_version": docket["lifecycle_version"],
        "to_status": "retired",
        "effective_at": datetime.now(UTC).isoformat(),
        "reason": "Acceptance record retired after the run.",
        "outcome": "test record retired",
        "source": "manual_review",
        "evidence_ref": "e2e:retirement",
        "successor_docket_id": None,
        "acknowledged_exception_codes": [],
        "second_approver_membership_id": None,
        "client_report_handling": "retain",
        "linked_matter_handling": "not_linked",
    }
    preview = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle/preview", headers=headers, json=body
    )
    assert preview.status_code == 200, preview.text
    body["acknowledged_exception_codes"] = preview.json().get("blocker_codes") or []
    applied = client.post(f"/api/ip/dockets/{docket_id}/lifecycle", headers=headers, json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "retired"


# --- ADJ-06 -------------------------------------------------------------------


def test_docket_document_list_includes_every_link_the_validators_accept(
    client: TestClient,
) -> None:
    headers, _ = _tenant(client, "adj06-docket-list")
    docket_id = _create_docket(client, headers)
    other_docket = _create_docket(client, headers)
    direct = _upload(client, headers, title="Deed linked to the docket",
                     links=[{"target_type": "docket", "target_id": docket_id}])
    via_event = _upload(client, headers, title="Deed linked to a docket event",
                        links=[{"target_type": "event",
                               "target_id": _docket_event_id(client, headers, docket_id)}])
    elsewhere = _upload(client, headers, title="Deed on another docket",
                        links=[{"target_type": "docket", "target_id": other_docket}])

    listed = _ids(client.get(LIST, headers=headers, params={"docket_id": docket_id}))
    # The event-linked deed used to be missing although recordals accept it.
    assert set(listed) == {direct, via_event}
    assert listed[0] == via_event  # newest first
    assert set(_ids(client.get(LIST, headers=headers, params={"docket_id": other_docket}))) == {
        elsewhere
    }
    # Every document listed for the docket is accepted by the recordal validator.
    created = _assignment(client, headers, docket_id, listed)
    assert created.status_code == 201, created.text


def test_deadline_linked_document_is_listed_for_its_docket(client: TestClient, monkeypatch) -> None:
    from caseops_api.core.settings import get_settings
    from tests.test_ip_deadline_terminal_state import _confirmed_deadline

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()
    legal_headers, legal_id, _reviewer, deadline, docket_id = _confirmed_deadline(client)
    enable_ip_workspace(client, legal_headers, legal_id)
    via_deadline = _upload(client, legal_headers, title="Deed filed against the deadline",
                           links=[{"target_type": "deadline", "target_id": deadline["id"]}])
    assert _ids(client.get(LIST, headers=legal_headers, params={"docket_id": docket_id})) == [
        via_deadline
    ]


def test_foreign_associate_picker_and_validator_share_the_docket_document_set(
    client: TestClient,
) -> None:
    from tests.test_ip_059a_foreign_associate_foundation import (
        _create_payload,
        _lifecycle_version,
    )
    from tests.test_ip_foreign_associate_create_options_20261031 import _tenant as fa_tenant

    _, headers, _company_id, membership_id, _matter, docket, records = fa_tenant(client)
    via_event = _upload(client, headers, title="Power of attorney filed with an event",
                        links=[{"target_type": "event",
                               "target_id": _docket_event_id(client, headers, docket["id"])}])
    retired = _upload(client, headers, title="Superseded engagement letter",
                      links=[{"target_type": "docket", "target_id": docket["id"]}])
    retired_response = _retire(client, headers, retired, "Uploaded the wrong engagement letter.")
    assert retired_response.status_code == 200, retired_response.text

    options = client.get(
        "/api/ip/foreign-associate-instructions/create-options",
        headers=headers,
        params={"docket_id": docket["id"], "target_jurisdiction": "us"},
    )
    assert options.status_code == 200, options.text
    offered = {row["id"] for row in options.json()["documents"]}
    assert via_event in offered
    assert retired not in offered
    docket_list = set(_ids(client.get(LIST, headers=headers, params={"docket_id": docket["id"]})))
    assert offered == docket_list

    def create(thread: str, refs: list[str]):
        payload = {
            **_create_payload(
                docket_id=docket["id"], membership_id=membership_id, records=records, thread=thread
            ),
            "selected_document_refs": refs,
            "expected_lifecycle_version": _lifecycle_version(client, headers, docket["id"]),
        }
        return client.post("/api/ip/foreign-associate-instructions", headers=headers, json=payload)

    # The event-linked document the picker offers is accepted (it used to be a 422).
    accepted = create("ADJ06-EVENT", [records["filing_document_id"], via_event])
    assert accepted.status_code == 201, accepted.text
    # The retired document the picker hides is refused.
    refused = create("ADJ07-RETIRED", [retired])
    assert refused.status_code == 422, refused.text
    assert "current document" in refused.text


# --- ADJ-07: retirement -------------------------------------------------------


def test_retired_document_leaves_pickers_and_validators_but_stays_in_history(
    client: TestClient,
) -> None:
    headers, membership_id = _tenant(client, "adj07-retire")
    docket_id = _create_docket(client, headers)
    deed = _upload(client, headers, title="Deed uploaded by mistake",
                   links=[{"target_type": "docket", "target_id": docket_id}])
    keeper = _upload(client, headers, title="Deed that stays current",
                     links=[{"target_type": "docket", "target_id": docket_id}])

    preview = client.get(f"{LIST}/{deed}/retirement", headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "document_id": deed,
        "title": "Deed uploaded by mistake",
        "current_version": 1,
        "already_retired": False,
        "may_retire": True,
        "permission_reason": None,
        "blockers": [],
        "retirable": True,
    }
    short = client.post(f"{LIST}/{deed}/retire", headers=headers,
                        json={"expected_current_version": 1, "reason": "   oops   "})
    assert short.status_code == 422
    assert "Reason" in short.json()["detail"]
    stale = client.post(f"{LIST}/{deed}/retire", headers=headers,
                        json={"expected_current_version": 2,
                              "reason": "Uploaded to the wrong docket."})
    assert stale.status_code == 409
    assert stale.json()["code"] == "ip_document_version_conflict"

    retired = _retire(client, headers, deed, "  Uploaded to the wrong docket by mistake.  ")
    assert retired.status_code == 200, retired.text
    retirement = retired.json()["retirement"]
    assert retirement["reason"] == "Uploaded to the wrong docket by mistake."
    assert retirement["retired_by_name"]
    assert "membership" not in retirement and "retired_by_membership_id" not in retirement

    # Audited, with the reason; never deleted.
    with get_session_factory()() as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "ip_document.retired", AuditEvent.target_id == deed
            )
        ).all()
        assert len(events) == 1
        assert events[0].actor_membership_id == membership_id
        assert "Uploaded to the wrong docket" in str(events[0].metadata_json)
        stored = session.get(IpDocument, deed)
        assert stored is not None and stored.retired_at is not None

    # Default lists and every picker drop it; history keeps it.
    assert _ids(client.get(LIST, headers=headers)) == [keeper]
    assert _ids(client.get(LIST, headers=headers, params={"docket_id": docket_id})) == [keeper]
    history = client.get(LIST, headers=headers, params={"include_history": "true"})
    assert {row["id"]: bool(row["retirement"]) for row in history.json()["items"]} == {
        deed: True, keeper: False
    }
    instruments = client.get(
        "/api/ip/recordals/instruments", headers=headers, params={"docket_id": docket_id}
    )
    assert [row["id"] for row in instruments.json()["items"]] == [keeper]
    detail = client.get(f"{LIST}/{deed}", headers=headers)
    assert detail.status_code == 200 and detail.json()["retirement"]["reason"]
    download = client.get(f"{LIST}/{deed}/versions/1/download", headers=headers)
    assert download.status_code == 200
    policy = client.get(f"{LIST}/{deed}/policy", headers=headers).json()
    assert policy["ai_retrieval_allowed"] is False
    assert policy["portal_share_allowed"] is False

    # Validators refuse it as evidence; it cannot change any more.
    cited = _assignment(client, headers, docket_id, [deed])
    assert cited.status_code == 422, cited.text
    assert "retired" in cited.text
    again = _retire(client, headers, deed, "Retire the same deed a second time.")
    assert again.status_code == 409
    assert again.json()["code"] == "ip_document_already_retired"
    linked = client.post(f"{LIST}/{deed}/links", headers=headers, json={
        "expected_current_version": 1,
        "links": [{"target_type": "docket", "target_id": _create_docket(client, headers)}],
    })
    assert linked.status_code == 409 and linked.json()["code"] == "ip_document_retired"
    moved = client.post(f"{LIST}/{deed}/versions/1/transition", headers=headers, json={
        "expected_current_version": 1, "expected_state": "draft", "target_state": "review",
    })
    assert moved.status_code == 409 and moved.json()["code"] == "ip_document_retired"
    preview_after = client.get(f"{LIST}/{deed}/retirement", headers=headers).json()
    assert preview_after["already_retired"] is True and preview_after["retirable"] is False

    # Re-uploading the same bytes creates a new current document instead of
    # offering the retired one for reuse.
    reupload = _upload(client, headers, title="Deed uploaded by mistake",
                       links=[{"target_type": "docket", "target_id": docket_id}])
    assert reupload not in {deed, keeper}


def test_a_live_recordal_blocks_retirement_until_it_is_withdrawn(client: TestClient) -> None:
    headers, _ = _tenant(client, "adj07-recordal")
    docket_id = _create_docket(client, headers)
    deed = _upload(client, headers, title="Executed assignment deed",
                   links=[{"target_type": "docket", "target_id": docket_id}])
    recordal = _assignment(client, headers, docket_id, [deed])
    assert recordal.status_code == 201, recordal.text
    recordal_id = recordal.json()["id"]

    preview = client.get(f"{LIST}/{deed}/retirement", headers=headers).json()
    assert preview["retirable"] is False
    assert [(row["kind"], row["record_id"], row["status"]) for row in preview["blockers"]] == [
        ("recordal", recordal_id, "draft")
    ]
    blocker = preview["blockers"][0]
    assert blocker["label"] == "Assignment recordal"
    assert blocker["docket_id"] == docket_id and blocker["docket_title"]
    assert blocker["href"] == "/app/ip/recordals"
    assert "Withdraw" in blocker["resolution"]

    refused = _retire(client, headers, deed, "Test instrument no longer needed.")
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["code"] == "ip_document_retirement_blocked"
    assert body["detail"].startswith("1 record still relies on this document")
    assert [row["record_id"] for row in body["blockers"]] == [recordal_id]
    with get_session_factory()() as session:
        assert session.get(IpDocument, deed).retired_at is None
        assert not session.scalars(
            select(AuditEvent).where(AuditEvent.action == "ip_document.retired")
        ).all()

    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    me = client.get("/api/auth/me", headers=headers).json()
    withdrawn = client.post(f"/api/ip/recordals/{recordal_id}/transactions", headers=headers, json={
        "expected_version": recordal.json()["version"],
        "expected_lifecycle_version": docket["lifecycle_version"],
        "transaction_kind": "withdrawn",
        "responsible_membership_id": me["membership"]["id"],
        "reason": "Client withdrew the instruction.",
    })
    assert withdrawn.status_code == 201, withdrawn.text
    assert client.get(f"{LIST}/{deed}/retirement", headers=headers).json()["blockers"] == []
    released = _retire(client, headers, deed, "Recordal withdrawn; retire its test deed.")
    assert released.status_code == 200, released.text

    # The withdrawn recordal still names what it cited, from history.
    workspace = client.get(f"/api/ip/recordals/{recordal_id}/workspace", headers=headers).json()
    assert [row["id"] for row in workspace["documents"]] == []
    cited = {row["id"]: row for row in workspace["cited_documents"]}
    assert set(cited) == {deed}
    assert cited[deed]["title"] == "Executed assignment deed"
    assert cited[deed]["retirement"]["reason"]


def test_confirmed_docket_event_evidence_blocks_retirement(client: TestClient) -> None:
    headers, membership_id = _tenant(client, "adj07-event")
    docket_id = _create_docket(client, headers)
    evidence = _upload(client, headers, title="Examination report response",
                       links=[{"target_type": "docket", "target_id": docket_id}])
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    event = client.post(f"/api/ip/dockets/{docket_id}/events", headers=headers, json={
        "event_kind": "examination_report",
        "source": "manual",
        "effective_at": "2026-10-20T09:00:00Z",
        "reason": "Examination report received from the registry.",
        "responsible_membership_id": membership_id,
        "expected_lifecycle_version": docket["lifecycle_version"],
        "document_refs": [evidence],
    })
    assert event.status_code == 201, event.text
    blocked = _retire(client, headers, evidence, "Try to retire recorded evidence.")
    assert blocked.status_code == 409
    assert [(row["kind"], row["record_id"]) for row in blocked.json()["blockers"]] == [
        ("docket_event", event.json()["id"])
    ]
    assert blocked.json()["blockers"][0]["href"] == f"/app/ip?docket={docket_id}"


def test_document_on_a_closed_docket_is_listed_in_history_and_can_be_retired(
    client: TestClient,
) -> None:
    headers, _ = _tenant(client, "adj07-closed")
    docket_id = _create_docket(client, headers)
    leftover = _upload(client, headers, title="Acceptance run leftover",
                       links=[{"target_type": "docket", "target_id": docket_id}])
    _retire_docket(client, headers, docket_id)

    # The closed docket's document leaves the current list but not history.
    assert leftover not in _ids(client.get(LIST, headers=headers))
    history = _ids(client.get(LIST, headers=headers, params={"include_history": "true"}))
    assert leftover in history
    assert client.get(f"{LIST}/{leftover}/retirement", headers=headers).json()["retirable"] is True
    cleaned = _retire(client, headers, leftover, "Closed acceptance docket cleanup.")
    assert cleaned.status_code == 200, cleaned.text
    assert client.get(f"{LIST}/{leftover}", headers=headers).json()["retirement"]


def test_retirement_is_tenant_wall_and_role_scoped(client: TestClient) -> None:
    slug = "adj07-isolation"
    owner, _ = _tenant(client, slug)
    open_docket = _create_docket(client, owner)
    walled_docket = _restricted_docket(client, owner)
    walled_doc = _upload(client, owner, title="Deed on the walled docket",
                         links=[{"target_type": "docket", "target_id": walled_docket}])
    owner_doc = _upload(client, owner, title="Partner's deed",
                        links=[{"target_type": "docket", "target_id": open_docket}])

    # Another tenant cannot see, preview or retire it.
    rival, _ = _tenant(client, "adj07-rival")
    assert client.get(f"{LIST}/{owner_doc}/retirement", headers=rival).status_code == 404
    foreign = client.post(f"{LIST}/{owner_doc}/retire", headers=rival,
                          json={"expected_current_version": 1, "reason": "Cross-tenant attempt."})
    assert foreign.status_code == 404
    assert "Partner's deed" not in foreign.text

    # A walled colleague (an admin) cannot learn of or retire the walled deed.
    colleague = _colleague(client, owner, slug)
    assert client.get(f"{LIST}/{walled_doc}/retirement", headers=colleague).status_code == 404
    walled = client.post(f"{LIST}/{walled_doc}/retire", headers=colleague,
                         json={"expected_current_version": 1, "reason": "Walled attempt here."})
    assert walled.status_code == 404
    assert "walled docket" not in walled.text
    assert walled_doc not in _ids(
        client.get(LIST, headers=colleague, params={"include_history": "true"})
    )

    # A member may retire their own upload but not a colleague's.
    member = _user(client, owner, slug, "member")
    mine = _upload(client, member, title="Member's own upload",
                   links=[{"target_type": "docket", "target_id": open_docket}])
    others = client.get(f"{LIST}/{owner_doc}/retirement", headers=member).json()
    assert others["may_retire"] is False and others["retirable"] is False
    assert "uploaded" in others["permission_reason"]
    forbidden = _retire(client, member, owner_doc, "Member retiring a partner's deed.")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ip_document_retire_forbidden"
    assert _retire(client, member, mine, "Uploaded the wrong file.").status_code == 200

    # A viewer can read but not retire; an anonymous caller is refused.
    viewer = _user(client, owner, slug, "viewer")
    viewer_preview = client.get(f"{LIST}/{owner_doc}/retirement", headers=viewer)
    assert viewer_preview.json()["may_retire"] is False
    assert _retire(client, viewer, owner_doc, "Viewer retirement attempt.").status_code == 403
    client.cookies.clear()
    assert client.get(f"{LIST}/{owner_doc}/retirement").status_code == 401
    anonymous = client.post(f"{LIST}/{owner_doc}/retire",
                            json={"expected_current_version": 1, "reason": "No session here."})
    # Refused before the handler runs (no bearer token, no CSRF-bound cookie session).
    assert anonymous.status_code in {401, 403}, anonymous.text
    with get_session_factory()() as session:
        assert session.get(IpDocument, owner_doc).retired_at is None
        assert session.get(IpDocument, walled_doc).retired_at is None


def test_blocker_on_a_docket_the_viewer_cannot_open_is_counted_not_described(
    client: TestClient,
) -> None:
    slug = "adj07-redacted"
    owner, membership_id = _tenant(client, slug)
    open_docket = _create_docket(client, owner)
    walled_docket = _restricted_docket(client, owner)
    shared = _upload(client, owner, title="Deed cited on the walled docket",
                     links=[{"target_type": "docket", "target_id": open_docket}])
    docket = client.get(f"/api/ip/dockets/{walled_docket}", headers=owner).json()
    cited = client.post(f"/api/ip/dockets/{walled_docket}/events", headers=owner, json={
        "event_kind": "examination_report",
        "source": "manual",
        "effective_at": "2026-10-20T09:00:00Z",
        "reason": "Response filed citing the shared deed.",
        "responsible_membership_id": membership_id,
        "expected_lifecycle_version": docket["lifecycle_version"],
        "document_refs": [shared],
    })
    assert cited.status_code == 201, cited.text
    colleague = _colleague(client, owner, slug)
    preview = client.get(f"{LIST}/{shared}/retirement", headers=colleague)
    assert preview.status_code == 200, preview.text
    assert preview.json()["blockers"] == [{
        "kind": "docket_event", "record_id": "restricted", "label": "A record you cannot open",
        "status": None, "docket_id": None, "docket_title": None,
        "resolution": "Ask a colleague with access to that record to release the document.",
        "href": None,
    }]
    assert walled_docket not in preview.text and "Restricted ASTER" not in preview.text


def test_madrid_and_recordal_pickers_drop_a_retired_document(client: TestClient) -> None:
    from tests.test_auth_company import bootstrap_company
    from tests.test_ip_international import _action_payload, _registration_payload
    from tests.test_ip_record_workflow import _application, _asset, _docket

    bootstrap = bootstrap_company(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    enable_ip_workspace(client, owner, membership_id)
    basic = _docket(client, owner, "ASTER MADRID RETIRE")
    asset = _asset(client, owner, basic["id"], "ASTER")
    application = _application(client, owner, basic["id"], asset["id"])
    registration = client.post(
        "/api/ip/international-registrations",
        headers=owner,
        json=_registration_payload(basic_application_id=application["id"], ir_number="1888132"),
    )
    assert registration.status_code == 201, registration.text
    record = registration.json()
    current = _upload(client, owner, title="WIPO certificate",
                      links=[{"target_type": "docket", "target_id": record["docket_id"]}])
    retired = _upload(client, owner, title="Draft certificate uploaded early",
                      links=[{"target_type": "docket", "target_id": record["docket_id"]}])
    assert _retire(client, owner, retired, "Draft certificate replaced.").status_code == 200

    workspace = client.get(
        f"/api/ip/international-registrations/{record['id']}/workspace", headers=owner
    ).json()
    assert {row["id"] for row in workspace["documents"]} == {current}

    def act(document_id: str):
        state = client.get(
            f"/api/ip/international-registrations/{record['id']}/workspace", headers=owner
        ).json()
        return client.post(
            f"/api/ip/international-registrations/{record['id']}/actions",
            headers=owner,
            json=_action_payload(
                membership_id=membership_id,
                expected_version=state["record"]["version"],
                action_kind="source_snapshot",
                authority="wipo",
                source_url="https://www.wipo.int/madrid/monitor/en/showData.jsp?ID=1888132",
                source_reference=f"WIPO-IR-1888132:{document_id[:8]}",
                document_refs=[document_id],
                expected_lifecycle_version=state["docket"]["lifecycle_version"],
                wipo_status="recorded",
            ),
        )

    refused = act(retired)
    assert refused.status_code == 422, refused.text
    assert "current documents" in refused.text
    accepted = act(current)
    assert accepted.status_code in {200, 201}, accepted.text
    # The Madrid candidate event now relies on the certificate.
    blockers = client.get(f"{LIST}/{current}/retirement", headers=owner).json()["blockers"]
    assert [row["kind"] for row in blockers] == ["docket_event"]
