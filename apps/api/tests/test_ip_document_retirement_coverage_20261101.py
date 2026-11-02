"""B4-ADJ-06 / B4-ADJ-07 review coverage (Ram batch 4 adjacent defects, 2026-11-01).

Every kind of record that relies on an IP document blocks its retirement in
the state the rule names and releases it where a releasing state exists; every
writer that accepts an IP document as evidence refuses a retired one; and the
docket document list offers every document the consuming validators accept.

Documents are uploaded through the product's upload endpoint. One record state
is written directly, and named where it happens: a foreign-associate
instruction's ``completed`` status, which takes the full dispatch, filing and
invoice chain covered by test_ip_059a. The renewal fixture's certificate comes
from the existing renewal fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import count
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import (
    IpDocketRecord,
    IpForeignAssociateInstruction,
    IpProceeding,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_document_retirement_20261101 import (
    LIST,
    _ids,
    _retire,
    _retire_docket,
    _tenant,
)
from tests.test_ip_document_taxonomy_provisioning_20261031 import _create_docket
from tests.test_ip_recordal_instruments_20261031 import _assignment, _upload
from tests.test_ip_specialist import registered_intake  # noqa: F401  (pytest fixture)


def _blockers(client: TestClient, headers: dict[str, str], document_id: str) -> list[dict]:
    preview = client.get(f"{LIST}/{document_id}/retirement", headers=headers)
    assert preview.status_code == 200, preview.text
    return preview.json()["blockers"]


def _kinds(client: TestClient, headers: dict[str, str], document_id: str) -> list[tuple]:
    return [
        (row["kind"], row["record_id"], row["status"])
        for row in _blockers(client, headers, document_id)
    ]


_EVENT_DAYS = count(1)


def _event(client, headers, docket_id: str, membership_id: str, **refs):
    # A distinct date per event: the same kind on the same instant is a duplicate.
    day = next(_EVENT_DAYS)
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()
    return client.post(
        f"/api/ip/dockets/{docket_id}/events",
        headers=headers,
        json={
            "event_kind": "examination_report",
            "source": "manual",
            "effective_at": f"2026-09-{day:02d}T09:00:00Z",
            "reason": "Examination report received from the registry.",
            "responsible_membership_id": membership_id,
            "expected_lifecycle_version": docket["lifecycle_version"],
            **refs,
        },
    )


def _title_interest(client, headers, docket_id: str, evidence: str, status: str = "pending"):
    return client.post(
        f"/api/ip/dockets/{docket_id}/title-interests",
        headers=headers,
        json={
            "interest_type": "licence",
            "party_name": f"Licensee {uuid4().hex[:6]}",
            "party_role": "licensee",
            "effective_from": "2026-10-01",
            "evidence_reference": evidence,
            "recordal_status": status,
        },
    )


# --- Finding: the history view's closed-record documents are read-only ---------


def test_history_marks_a_closed_records_document_read_only(client: TestClient) -> None:
    headers, _ = _tenant(client, "adj07-readonly")
    open_docket = _create_docket(client, headers)
    closed_docket = _create_docket(client, headers)
    current = _upload(
        client,
        headers,
        title="Deed on the open docket",
        links=[{"target_type": "docket", "target_id": open_docket}],
    )
    leftover = _upload(
        client,
        headers,
        title="Deed on the closed docket",
        links=[{"target_type": "docket", "target_id": closed_docket}],
    )
    retired = _upload(
        client,
        headers,
        title="Deed retired on the open docket",
        links=[{"target_type": "docket", "target_id": open_docket}],
    )
    assert _retire(client, headers, retired, "Uploaded to the wrong docket.").status_code == 200
    _retire_docket(client, headers, closed_docket)

    history = client.get(LIST, headers=headers, params={"include_history": "true"})
    assert history.status_code == 200, history.text
    reasons = {row["id"]: row["read_only_reason"] for row in history.json()["items"]}
    assert reasons == {current: None, leftover: "closed_record", retired: "retired"}
    assert client.get(f"{LIST}/{leftover}", headers=headers).json()["read_only_reason"] == (
        "closed_record"
    )
    assert client.get(f"{LIST}/{current}", headers=headers).json()["read_only_reason"] is None
    # The default list never carries a read-only document.
    assert {
        row["read_only_reason"] for row in client.get(LIST, headers=headers).json()["items"]
    } == {None}
    # What the flag promises: every change is refused, retirement is not.
    moved = client.post(
        f"{LIST}/{leftover}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "draft",
            "target_state": "review",
        },
    )
    assert moved.status_code == 404, moved.text
    bulk = client.post(
        f"{LIST}/bulk-preview",
        headers=headers,
        json={
            "items": [
                {
                    "document_id": leftover,
                    "expected_current_version": 1,
                    "expected_taxonomy_key": "assignment",
                    "taxonomy_key": "evidence",
                    "naming": {
                        "client_code": "ACME",
                        "document_type": "Evidence",
                        "version": 1,
                        "extension": "txt",
                    },
                }
            ]
        },
    )
    assert bulk.status_code == 404, bulk.text
    assert _retire(client, headers, leftover, "Closed docket's leftover upload.").status_code == 200


# --- Finding: free-text event and title-interest evidence -----------------------


def test_docket_event_and_title_interest_refuse_a_retired_document(client: TestClient) -> None:
    headers, membership_id = _tenant(client, "adj07-freetext")
    docket_id = _create_docket(client, headers)
    retired = _upload(
        client,
        headers,
        title="Licence draft uploaded early",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    current = _upload(
        client,
        headers,
        title="Executed licence",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    assert (
        _retire(client, headers, retired, "Draft replaced by the executed copy.").status_code == 200
    )

    for refs in ({"document_refs": [retired]}, {"evidence_refs": [retired]}):
        refused = _event(client, headers, docket_id, membership_id, **refs)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "ip_document_retired"
    interest = _title_interest(client, headers, docket_id, retired)
    assert interest.status_code == 409, interest.text
    assert interest.json()["code"] == "ip_document_retired"
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        assert docket is not None and docket.lifecycle_version == 0

    # Free text that names no document is still accepted; a current document is
    # accepted and, from then on, relied on.
    assert (
        _event(
            client,
            headers,
            docket_id,
            membership_id,
            evidence_refs=["Registry letter of 20 October"],
        ).status_code
        == 201
    )
    assert (
        _title_interest(client, headers, docket_id, "Licence deed, client file").status_code == 200
    )
    cited = _event(client, headers, docket_id, membership_id, document_refs=[current])
    assert cited.status_code == 201, cited.text
    assert [row[0] for row in _kinds(client, headers, current)] == ["docket_event"]

    # A tenant's free text that happens to equal another tenant's document id is
    # not a document of this tenant and is accepted as text.
    rival, rival_member = _tenant(client, "adj07-freetext-rival")
    rival_docket = _create_docket(client, rival)
    assert (
        _event(client, rival, rival_docket, rival_member, document_refs=[retired]).status_code
        == 201
    )


def test_title_interest_evidence_blocks_until_withdrawn_or_rejected(client: TestClient) -> None:
    headers, _ = _tenant(client, "adj07-title")
    docket_id = _create_docket(client, headers)
    pending = _upload(
        client,
        headers,
        title="Licence recorded later",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    withdrawn = _upload(
        client,
        headers,
        title="Licence withdrawn",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    assert _title_interest(client, headers, docket_id, pending, "pending").status_code == 200
    assert _title_interest(client, headers, docket_id, withdrawn, "withdrawn").status_code == 200

    blockers = _blockers(client, headers, pending)
    assert [(row["kind"], row["status"]) for row in blockers] == [("title_interest", "pending")]
    assert blockers[0]["docket_id"] == docket_id
    refused = _retire(client, headers, pending, "Licence no longer needed here.")
    assert refused.status_code == 409 and refused.json()["code"] == "ip_document_retirement_blocked"
    # A withdrawn interest no longer relies on its evidence.
    assert _blockers(client, headers, withdrawn) == []
    assert _retire(client, headers, withdrawn, "Withdrawn licence evidence.").status_code == 200


# --- Blocker: foreign-associate instruction ----------------------------------------


def test_foreign_associate_instruction_blocks_until_cancelled_and_completed_keeps_it(
    client: TestClient,
) -> None:
    from tests.test_ip_059a_foreign_associate_foundation import (
        _create_payload,
        _lifecycle_version,
        _transaction,
    )
    from tests.test_ip_foreign_associate_create_options_20261031 import _tenant as fa_tenant

    _, headers, _company, membership_id, _matter, docket, records = fa_tenant(client)
    draft_doc = _upload(
        client,
        headers,
        title="Power of attorney for the draft",
        links=[{"target_type": "docket", "target_id": docket["id"]}],
    )
    done_doc = _upload(
        client,
        headers,
        title="Power of attorney for the completed",
        links=[{"target_type": "docket", "target_id": docket["id"]}],
    )

    def create(thread: str, document_id: str) -> dict:
        response = client.post(
            "/api/ip/foreign-associate-instructions",
            headers=headers,
            json={
                **_create_payload(
                    docket_id=docket["id"],
                    membership_id=membership_id,
                    records=records,
                    thread=thread,
                ),
                "selected_document_refs": [records["filing_document_id"], document_id],
                "expected_lifecycle_version": _lifecycle_version(client, headers, docket["id"]),
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    draft = create("ADJ07-FA-DRAFT", draft_doc)
    blockers = _blockers(client, headers, draft_doc)
    assert [(row["kind"], row["record_id"], row["status"]) for row in blockers] == [
        ("foreign_associate_instruction", draft["id"], "draft")
    ]
    assert blockers[0]["href"] == "/app/ip/foreign-associates"
    assert "Cancel" in blockers[0]["resolution"]
    refused = _retire(client, headers, draft_doc, "Attorney letter replaced.")
    assert refused.status_code == 409, refused.text

    cancelled = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=draft["id"],
        version=draft["row_version"],
        membership_id=membership_id,
        kind="cancel",
    )
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()["instruction"]["status"] == "cancelled"
    assert _blockers(client, headers, draft_doc) == []
    assert (
        _retire(client, headers, draft_doc, "Instruction cancelled; retire it.").status_code == 200
    )

    completed = create("ADJ07-FA-DONE", done_doc)
    # Written directly, with every field the database requires of a completed
    # instruction: reaching ``completed`` takes the approval, dispatch,
    # acknowledgement, filing-evidence and invoice chain test_ip_059a covers.
    with get_session_factory()() as session:
        row = session.get(IpForeignAssociateInstruction, completed["id"])
        assert row is not None
        now = datetime.now(UTC)
        row.approved_at = now
        row.approved_by_membership_id = membership_id
        row.external_dispatch_reference = "ADJ07-DISPATCH"
        row.acknowledged_at = now
        row.acknowledgement_reference = "ADJ07-ACK"
        row.status = "completed"
        session.commit()
    blockers = _blockers(client, headers, done_doc)
    assert [(row["kind"], row["status"]) for row in blockers] == [
        ("foreign_associate_instruction", "completed")
    ]
    assert "completed instruction keeps" in blockers[0]["resolution"]
    assert (
        _retire(client, headers, done_doc, "Try to retire completed evidence.").status_code == 409
    )


# --- Blocker and refusal: renewal certificate ----------------------------------------


def test_renewal_certificate_blocks_retirement_and_a_retired_one_is_refused(
    client: TestClient,
) -> None:
    from tests.test_ip_renewal_transition_references_20261031 import _create_term
    from tests.test_ip_renewals import _seed_renewal_fixture

    _, headers, ids = _seed_renewal_fixture(client)
    term = _create_term(client, headers, ids)
    references = f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition-references"
    transition = f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition"
    guard = {
        "expected_state": term["state"],
        "expected_version": term["version"],
        "expected_updated_at": term["updated_at"],
        "reason": "Renewal filing started with the accepted certificate on file.",
        "fee_cost_item_id": ids["fee"],
        "filing_initiated_reference": "provider://attempt/adj07",
        "target_state": "filing_in_progress",
    }
    offered = client.get(references, headers=headers).json()["certificate_documents"]
    assert [row["id"] for row in offered] == [ids["certificate"]]
    recorded = client.post(
        transition, headers=headers, json={**guard, "certificate_document_id": ids["certificate"]}
    )
    assert recorded.status_code == 200, recorded.text

    blockers = _blockers(client, headers, ids["certificate"])
    assert [(row["kind"], row["record_id"]) for row in blockers] == [
        ("renewal_certificate", term["id"])
    ]
    refused = _retire(client, headers, ids["certificate"], "Certificate filed in error.")
    assert refused.status_code == 409, refused.text


def test_retired_certificate_leaves_the_renewal_picker_and_validator(client: TestClient) -> None:
    from tests.test_ip_renewal_transition_references_20261031 import _create_term
    from tests.test_ip_renewals import _seed_renewal_fixture

    _, headers, ids = _seed_renewal_fixture(client)
    term = _create_term(client, headers, ids)
    assert (
        _retire(client, headers, ids["certificate"], "Superseded certificate copy.").status_code
        == 200
    )
    references = client.get(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition-references",
        headers=headers,
    )
    assert references.json()["certificate_documents"] == []
    refused = client.post(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "reason": "Attempt to cite a retired certificate.",
            "fee_cost_item_id": ids["fee"],
            "filing_initiated_reference": "provider://attempt/adj07-retired",
            "target_state": "filing_in_progress",
            "certificate_document_id": ids["certificate"],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_renewal_certificate_not_accepted"


# --- Blocker and refusal: client portal publication -------------------------------


def _accept(client: TestClient, headers: dict[str, str], document_id: str) -> None:
    for expected, target in (
        ("draft", "review"),
        ("review", "approved"),
        ("approved", "filed"),
        ("filed", "served"),
        ("served", "accepted"),
    ):
        moved = client.post(
            f"{LIST}/{document_id}/versions/1/transition",
            headers=headers,
            json={
                "expected_current_version": 1,
                "expected_state": expected,
                "target_state": target,
            },
        )
        assert moved.status_code == 200, (target, moved.text)


def test_portal_publication_blocks_retirement_and_a_retired_document_is_not_shared(
    client: TestClient,
) -> None:
    from tests.test_portal_ip import _invite_ip_client

    headers, _ = _tenant(client, "adj07-portal")
    docket_id = _create_docket(client, headers)
    shared = _upload(
        client,
        headers,
        title="Assignment shared with the client",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    retired = _upload(
        client,
        headers,
        title="Assignment retired before sharing",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    _accept(client, headers, shared)
    _accept(client, headers, retired)
    invitation, _token = _invite_ip_client(
        client, headers, docket_id=docket_id, categories=["assignment"]
    )
    grant_id = invitation["grants"][0]["id"]
    shareable = client.get(f"/api/ip/portal/grants/{grant_id}/shareable-documents", headers=headers)
    assert shareable.status_code == 200, shareable.text
    assert {row["document_id"] for row in shareable.json()["documents"]} == {shared, retired}

    assert _retire(client, headers, retired, "Wrong counterpart; never shared.").status_code == 200
    shareable = client.get(f"/api/ip/portal/grants/{grant_id}/shareable-documents", headers=headers)
    assert {row["document_id"] for row in shareable.json()["documents"]} == {shared}
    payload = {
        "portal_user_id": invitation["portal_user"]["id"],
        "grant_id": grant_id,
        "version_number": 1,
        "title": "Executed assignment",
    }
    refused = client.post(
        "/api/ip/portal/document-publications",
        headers=headers,
        json={**payload, "document_id": retired},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "portal_document_retired"

    published = client.post(
        "/api/ip/portal/document-publications",
        headers=headers,
        json={**payload, "document_id": shared},
    )
    assert published.status_code == 201, published.text
    blockers = _blockers(client, headers, shared)
    assert [(row["kind"], row["record_id"]) for row in blockers] == [
        ("portal_publication", published.json()["id"])
    ]
    # No product path revokes one publication, so the blocker never asks for it.
    assert "Revoke" not in blockers[0]["resolution"]
    assert _retire(client, headers, shared, "Try to retire shared evidence.").status_code == 409


# --- Blocker and refusal: patent and specialist source pins --------------------------


def test_patent_source_pin_blocks_retirement_and_a_retired_source_is_refused(
    client: TestClient,
) -> None:
    from tests.test_ip_document_workflow import _upload as patent_upload
    from tests.test_ip_patent_applications import _create, _setup

    _, headers, family, payload = _setup(client)
    pinned = payload["facts"]["source"]["document_id"]
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    kinds = {row["kind"] for row in _blockers(client, headers, pinned)}
    assert kinds == {"source_evidence"}
    assert _retire(client, headers, pinned, "Try to retire a pinned source.").status_code == 409

    document = patent_upload(
        client,
        headers,
        filename="superseded-application.txt",
        content=b"Superseded application evidence. " * 30,
        docket_id=family["docket_id"],
        confidentiality="restricted",
    )["document"]
    assert _retire(client, headers, document["id"], "Superseded evidence copy.").status_code == 200
    pin = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    second = _create(
        client,
        headers,
        {
            **payload,
            "facts": {
                **payload["facts"],
                "office": "USPTO",
                "source": pin,
                "identifiers": [
                    {"identifier_kind": "application", "raw_value": "US/2026/9", "source": pin}
                ],
            },
        },
    )
    assert second.status_code == 422, second.text
    assert second.json()["code"] == "patent_source_retired"


@pytest.mark.usefixtures("registered_intake")
def test_specialist_source_pin_blocks_retirement_and_a_retired_source_is_refused(
    client: TestClient,
) -> None:
    from tests.test_ip_specialist import create, observation, post_observation, setup

    headers, facts = setup(client, "copyright")
    record = create(client, headers, facts).json()
    pinned, payload, _ = observation(client, headers, record)
    saved = post_observation(client, headers, record, payload)
    assert saved.status_code == 201, saved.text
    assert {row["kind"] for row in _blockers(client, headers, pinned["id"])} == {"source_evidence"}
    assert (
        _retire(client, headers, pinned["id"], "Try to retire pinned evidence.").status_code == 409
    )

    record = client.get(f"/api/ip/specialist/records/{record['id']}", headers=headers).json()
    retired, retired_payload, _ = observation(
        client, headers, record, content=b"Second specialist evidence file. " * 20
    )
    assert _retire(client, headers, retired["id"], "Duplicate evidence upload.").status_code == 200
    refused = post_observation(client, headers, record, retired_payload)
    assert refused.status_code in {409, 422}, refused.text
    assert refused.json()["code"] == "specialist_source_retired_document"


# --- Refusal: bulk, new version, drafting manifest ------------------------------------


def test_retired_document_is_refused_by_bulk_and_new_version(client: TestClient) -> None:
    headers, _ = _tenant(client, "adj07-bulk")
    docket_id = _create_docket(client, headers)
    retired = _upload(
        client,
        headers,
        title="Deed retired before bulk",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    current = _upload(
        client,
        headers,
        title="Deed still current for bulk",
        links=[{"target_type": "docket", "target_id": docket_id}],
    )
    assert _retire(client, headers, retired, "Wrong deed uploaded here.").status_code == 200
    items = [
        {
            "document_id": row,
            "expected_current_version": 1,
            "expected_taxonomy_key": "assignment",
            "taxonomy_key": "evidence",
            "naming": {
                "client_code": "ACME",
                "document_type": "Evidence",
                "version": 1,
                "extension": "txt",
            },
        }
        for row in (current, retired)
    ]
    preview = client.post(f"{LIST}/bulk-preview", headers=headers, json={"items": items})
    assert preview.status_code == 409, preview.text
    assert preview.json()["code"] == "ip_document_retired"
    applied = client.post(
        f"{LIST}/bulk-apply", headers=headers, json={"items": items, "preview_token": "0" * 64}
    )
    assert applied.status_code == 409, applied.text
    assert applied.json()["code"] == "ip_document_retired"
    # The current document alone still goes through.
    alone = client.post(f"{LIST}/bulk-preview", headers=headers, json={"items": items[:1]})
    assert alone.status_code == 200, alone.text

    version = client.post(
        f"{LIST}/{retired}/new-version",
        headers=headers,
        data={"metadata_json": json.dumps({"expected_current_version": 1})},
        files={"upload": ("deed-v2.txt", b"Second executed copy. " * 20, "text/plain")},
    )
    assert version.status_code == 409, version.text
    assert version.json()["code"] == "ip_document_retired"
    detail = client.get(f"{LIST}/{retired}", headers=headers).json()
    assert detail["current_version"] == 1 and len(detail["versions"]) == 1


def test_drafting_source_manifest_and_docket_list_follow_proceeding_links(
    client: TestClient,
) -> None:
    from caseops_api.services.drafting_targets import _load_source_manifest
    from tests.test_ip_document_taxonomy_provisioning_20261031 import enable_ip_workspace
    from tests.test_ip_opposition_opponent_workflow import _fixture

    bootstrap, _matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    enable_ip_workspace(client, headers, str(bootstrap["membership"]["id"]))
    link = [{"target_type": "proceeding", "target_id": proceeding["id"]}]
    current = _upload(client, headers, title="Opposition notice as filed", links=link)
    retired = _upload(client, headers, title="Opposition notice draft", links=link)
    assert (
        _retire(client, headers, retired, "Draft notice replaced by filed copy.").status_code == 200
    )

    # ADJ-06: the docket list now offers a proceeding-linked document, and the
    # recordal validator that shares the predicate accepts it.
    listed = _ids(client.get(LIST, headers=headers, params={"docket_id": docket["id"]}))
    assert listed == [current]
    assert _assignment(client, headers, docket["id"], [current]).status_code == 201

    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket["id"])
        proceeding_row = session.get(IpProceeding, proceeding["id"])
        assert docket_row is not None and proceeding_row is not None
        manifest, _text = _load_source_manifest(
            session,
            company_id=docket_row.company_id,
            docket=docket_row,
            proceeding=proceeding_row,
        )
    assert [row["document_id"] for row in manifest] == [current]


# --- ADJ-06: a patent consumer's picker equals what its validator accepts -----------


def test_patent_proceeding_linked_document_is_offered_and_accepted(client: TestClient) -> None:
    from tests.test_ip_patent_proceedings import _intake
    from tests.test_ip_patent_prosecution import _fixture, _save

    _, headers, _family, application, work = _fixture(client)
    first = _save(client, headers, application, "proceedings", _intake(work))
    assert first.status_code == 201, first.text
    proceeding_id = first.json()["id"]
    with get_session_factory()() as session:
        row = session.get(IpProceeding, proceeding_id)
        assert row is not None and row.docket_id == application["docket_id"]
    uploaded = client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": "evidence",
                    "title": "Opponent's statement",
                    "confidentiality": "restricted",
                    "links": [{"target_type": "proceeding", "target_id": proceeding_id}],
                }
            )
        },
        files={
            "upload": ("opponent-statement.txt", b"Opponent statement text. " * 30, "text/plain")
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    document = uploaded.json()["document"]

    offered = _ids(
        client.get(LIST, headers=headers, params={"docket_id": application["docket_id"]})
    )
    # The picker used to omit a proceeding-linked document the validator accepts.
    assert document["id"] in offered
    pin = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    application = client.get(
        f"/api/ip/patents/applications/{application['id']}", headers=headers
    ).json()
    second = _save(
        client,
        headers,
        application,
        "proceedings",
        _intake(
            {**work, "source": pin},
            expected_version=application["version"],
            expected_lifecycle_version=application["lifecycle_version"],
            expected_work_sequence=first.json()["latest"]["sequence"],
            title="Second pre-grant opposition",
            counterparty="Second Research",
        ),
    )
    assert second.status_code == 201, second.text
    assert second.json()["latest"]["source"]["document_id"] == document["id"]
