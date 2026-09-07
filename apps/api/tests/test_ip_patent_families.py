from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    ApiIdempotencyRecord,
    AuditEvent,
    CompanyMembership,
    IpAsset,
    IpDocketEvent,
    IpDocketRecord,
    IpDocumentLink,
    IpPatentFamily,
    IpPatentFamilyVersion,
    IpTrademarkParticularVersion,
    MatterAccessGrant,
    MembershipRole,
    PrivateProjectionEvent,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_domain_policy import disclosable_ip_document_ids
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_workflow import _upload
from tests.test_ip_record_workflow import _docket

BASE = "/api/ip/patents/families"


def _setup(client: TestClient) -> tuple[dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    legal_client = client.post(
        "/api/clients",
        headers=headers,
        json={
            "name": "Patent disclosure client",
            "client_type": "corporate",
        },
    )
    assert legal_client.status_code == 200, legal_client.text
    facts = {
        "title": "Confidential substrate invention",
        "client_id": legal_client.json()["id"],
        "disclosure_date": "2026-09-05",
        "disclosure_narrative": "Original inventor disclosure.",
    }
    return bootstrap, headers, facts


def _create(client: TestClient, headers: dict, facts: dict, key: str | None = None):
    return client.post(
        BASE, headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=facts
    )


def _correction(family: dict, **changes) -> dict:
    return {
        "expected_version": family["version"],
        "expected_lifecycle_version": family["lifecycle_version"],
        "reason": "Correct original inventor disclosure transcription.",
        "facts": {**family["facts"], **changes},
    }


def test_family_create_reload_correct_and_history_keep_independent_patent_identity(
    client: TestClient,
):
    bootstrap, headers, facts = _setup(client)
    response = _create(client, headers, facts)
    assert response.status_code == 201, response.text
    family = response.json()
    assert family["record_kind"] == "patent_family"
    assert family["facts"]["confidentiality"] == "restricted"
    assert family["version"] == 1
    assert client.get(f"{BASE}/{family['id']}", headers=headers).json() == family
    changed = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, title="Corrected invention title"),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    original = client.get(f"{BASE}/{family['id']}/versions/1", headers=headers)
    assert original.status_code == 200, original.text
    assert original.json()["facts"]["title"] == facts["title"]
    assert client.get(f"{BASE}/{family['id']}", headers=headers).json() == changed.json()
    assert client.get(BASE, headers=headers).json()["families"] == [changed.json()]
    assert client.get("/api/ip/dockets", headers=headers).json()["dockets"] == []
    assert client.get(f"/api/ip/dockets/{family['docket_id']}", headers=headers).status_code == 409
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, family["docket_id"])
        asset = session.get(IpAsset, family["asset_id"])
        assert docket.restricted and docket.record_type == "patent_family"
        assert asset.asset_kind == "patent" and asset.docket_id == docket.id
        assert asset.title == docket.title == "Corrected invention title"
        assert session.scalar(select(func.count()).select_from(IpPatentFamilyVersion)) == 2
        for model in (IpTrademarkParticularVersion, TrademarkApplication):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == bootstrap["company"]["id"],
                    AuditEvent.target_id == family["id"],
                )
            )
        )
        assert {row.action for row in events} >= {
            "ip_patent_family.created",
            "ip_patent_family.corrected",
        }


def test_creation_replay_cannot_duplicate_disclosure_or_bypass_revoked_access(client: TestClient):
    _, headers, facts = _setup(client)
    key = str(uuid4())
    first = _create(client, headers, facts, key)
    assert first.status_code == 201, first.text
    replay = _create(client, headers, facts, key)
    assert replay.status_code == 201 and replay.json() == first.json(), replay.text
    different = _create(client, headers, {**facts, "title": "Different intent"}, key)
    assert different.status_code == 409, different.text
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentFamily)) == 1
        assert session.scalar(select(func.count()).select_from(ApiIdempotencyRecord)) == 1
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == first.json()["docket_id"],
            )
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert _create(client, headers, facts, key).status_code == 404
    assert client.get(BASE, headers=headers).json()["families"] == []


def test_stale_correction_and_client_transfer_never_overwrite_current_disclosure(
    client: TestClient,
):
    _, headers, facts = _setup(client)
    family = _create(client, headers, facts).json()
    other = client.post(
        "/api/clients", headers=headers, json={"name": "Other client", "client_type": "corporate"}
    ).json()
    transfer = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, client_id=other["id"]),
    )
    assert transfer.status_code == 409, transfer.text
    changed = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, title="New source facts"),
    )
    assert changed.status_code == 200, changed.text
    stale = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, title="Stale source facts"),
    )
    assert stale.status_code == 409 and "patent_family_stale" in stale.text
    assert client.get(f"{BASE}/{family['id']}", headers=headers).json() == changed.json()


def test_terminal_family_cannot_be_corrected_or_replayed_into_active_state(client: TestClient):
    _, headers, facts = _setup(client)
    key = str(uuid4())
    created = _create(client, headers, facts, key)
    assert created.status_code == 201, created.text
    family = created.json()
    closed = client.post(
        f"/api/ip/dockets/{family['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Client withdrew the invention disclosure instruction.",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "test:withdrawal-instruction",
            "linked_matter_handling": "reviewed",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["is_active"] is False
    assert (
        client.post(
            f"{BASE}/{family['id']}/corrections", headers=headers, json=_correction(family)
        ).status_code
        == 404
    )
    assert _create(client, headers, facts, key).status_code == 404
    assert client.get(BASE, headers=headers).json()["families"] == []
    retained = client.get(f"{BASE}/{family['id']}", headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["facts"] == family["facts"]
    assert retained.json()["lifecycle_status"] == "closed"
    assert retained.json()["is_active"] is False
    for scope in ("terminal", "all"):
        page = client.get(BASE, headers=headers, params={"status_scope": scope})
        assert page.status_code == 200, page.text
        assert page.json()["families"] == [retained.json()]
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, family["docket_id"])
        assert docket.status == "closed" and not docket.is_active
        assert docket.current_version == 1


def test_closed_family_sources_history_reopen_and_revoke_keep_boundaries(client: TestClient):
    _, headers, facts = _setup(client)
    family = _create(client, headers, facts).json()
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    content = b"Immutable closed patent disclosure evidence. " * 30
    document = _upload(
        client,
        headers,
        filename="patent-history.txt",
        content=content,
        docket_id=family["docket_id"],
        confidentiality="confidential",
    )["document"]
    source = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    correction = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, source=source),
    )
    assert correction.status_code == 200, correction.text
    family = correction.json()
    lifecycle_path = f"/api/ip/dockets/{family['docket_id']}/lifecycle"
    command = {
        "expected_lifecycle_version": 0,
        "to_status": "closed",
        "effective_at": datetime.now(UTC).isoformat(),
        "reason": "Client instructed disclosure closure.",
        "outcome": "closed",
        "source": "lawyer_review",
        "evidence_ref": "instruction:close-patent-family",
        "linked_matter_handling": "reviewed",
    }
    closed = client.post(lifecycle_path, headers=headers, json=command)
    assert closed.status_code == 200, closed.text
    for path in (f"{BASE}/{family['id']}", f"{BASE}/{family['id']}/versions/2"):
        result = client.get(path, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["facts"]["source"] == source
        assert result.json()["is_active"] is False
    assert client.get(f"/api/ip/documents/{document['id']}", headers=headers).status_code == 200
    downloaded = client.get(
        f"/api/ip/documents/{document['id']}/versions/1/download", headers=headers
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == content
    listed = client.get(
        "/api/ip/documents", headers=headers, params={"docket_id": family["docket_id"]}
    )
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["items"]] == [document["id"]]
    denied = client.post(
        f"/api/ip/documents/{document['id']}/versions",
        headers=headers,
        files={"file": ("changed.txt", b"Attempted terminal replacement", "text/plain")},
        data={"expected_version": "1", "change_reason": "Must not replace terminal source"},
    )
    assert denied.status_code == 404, denied.text
    stale = client.post(lifecycle_path, headers=headers, json={**command, "to_status": "ready"})
    assert stale.status_code == 409, stale.text
    opened = client.post(
        lifecycle_path,
        headers=headers,
        json={
            **command,
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "reason": "Client explicitly renewed disclosure instruction.",
            "outcome": "intake resumed",
            "evidence_ref": "instruction:reopen-patent-family",
        },
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "ready" and opened.json()["is_active"]
    assert opened.json()["event"]["payload_json"]["reopen_without_child_resurrection"] is True
    stale_correction = client.post(
        f"{BASE}/{family['id']}/corrections", headers=headers, json=_correction(family)
    )
    assert stale_correction.status_code == 409, stale_correction.text
    closed_again = client.post(
        lifecycle_path,
        headers=headers,
        json={
            **command,
            "expected_lifecycle_version": 2,
            "evidence_ref": "instruction:second-closure",
        },
    )
    assert closed_again.status_code == 200, closed_again.text
    assert closed_again.json()["lifecycle_version"] == 3
    assert closed_again.json()["is_active"] is False
    assert (
        client.post(
            lifecycle_path,
            headers=headers,
            json={
                **command,
                "expected_lifecycle_version": 2,
            },
        ).status_code
        == 409
    )
    history_path = f"{BASE}/{family['id']}/lifecycle-history"
    first = client.get(history_path, headers=headers, params={"limit": 1}).json()
    assert [event["to_status"] for event in first["events"]] == ["closed"]
    assert first["next_cursor"] == 3
    middle = client.get(history_path, headers=headers, params={"limit": 1, "cursor": 3}).json()
    assert [event["to_status"] for event in middle["events"]] == ["ready"]
    assert middle["next_cursor"] == 2
    second = client.get(history_path, headers=headers, params={"limit": 1, "cursor": 2}).json()
    assert [event["to_status"] for event in second["events"]] == ["closed"]
    assert second["next_cursor"] is None
    assert second["events"][0]["evidence_refs"] == [command["evidence_ref"]]
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, family["docket_id"])
        assert docket.status == "closed" and docket.lifecycle_version == 3
        assert docket.current_version == 2
        assert session.scalar(select(func.count()).select_from(IpDocketEvent)) == 3
        grant = session.scalar(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == docket.id)
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()
    for path in (
        f"{BASE}/{family['id']}",
        f"{BASE}/{family['id']}/versions/2",
        history_path,
        f"/api/ip/documents/{document['id']}",
        f"/api/ip/documents/{document['id']}/versions/1/download",
    ):
        denied = client.get(path, headers=headers)
        assert denied.status_code == 404, (path, denied.text)
    assert (
        client.get(BASE, headers=headers, params={"status_scope": "all"}).json()["families"] == []
    )


def test_cross_tenant_family_and_client_identifiers_are_not_usable(client: TestClient):
    _, headers, facts = _setup(client)
    family = _create(client, headers, facts).json()
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Independent Firm",
            "company_slug": "independent-firm",
            "company_type": "law_firm",
            "owner_full_name": "Independent Owner",
            "owner_email": "owner@independent-firm.example.com",
            "owner_password": "IndependentPass123!",
        },
    )
    assert second.status_code == 200, second.text
    other_headers = auth_headers(second.json()["access_token"])
    assert client.get(BASE, headers=other_headers).json()["families"] == []
    for path in (
        f"{BASE}/{family['id']}",
        f"{BASE}/{family['id']}/versions/1",
        f"{BASE}/{family['id']}/lifecycle-history",
    ):
        assert client.get(path, headers=other_headers).status_code == 404
    assert (
        client.post(
            f"{BASE}/{family['id']}/corrections", headers=other_headers, json=_correction(family)
        ).status_code
        == 404
    )
    assert _create(client, other_headers, facts).status_code == 404


def test_shared_access_workflow_cannot_publish_a_patent_disclosure(client: TestClient):
    _, headers, facts = _setup(client)
    family = _create(client, headers, facts).json()
    panel = client.get(f"/api/ip/dockets/{family['docket_id']}/access", headers=headers)
    assert panel.status_code == 200, panel.text
    response = client.post(
        f"/api/ip/dockets/{family['docket_id']}/access/preview",
        headers=headers,
        json={
            "action": "set_restricted",
            "restricted": False,
            "expected_access_policy_version": panel.json()["access_policy_version"],
            "reason": "Attempted disclosure publication must fail closed.",
        },
    )
    assert response.status_code == 409, response.text
    assert "patent_disclosure_restriction_required" in response.text
    with get_session_factory()() as session:
        assert session.get(IpDocketRecord, family["docket_id"]).restricted


def test_source_pin_preserves_exact_version_and_rejects_wrong_hash_and_revoked_source(
    client: TestClient,
):
    _, headers, facts = _setup(client)
    source_family = _create(client, headers, facts).json()
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    uploaded = _upload(
        client,
        headers,
        filename="inventor-disclosure.txt",
        content=b"Original inventor source disclosure. " * 20,
        docket_id=source_family["docket_id"],
        confidentiality="confidential",
    )
    version = uploaded["document"]["versions"][0]
    pin = {
        "kind": "document_version",
        "document_id": uploaded["document"]["id"],
        "document_version_id": version["id"],
        "content_sha256": version["sha256_hex"],
    }
    wrong = _create(client, headers, {**facts, "source": {**pin, "content_sha256": "0" * 64}})
    assert wrong.status_code == 409, wrong.text
    correct = _create(client, headers, {**facts, "title": "Sourced disclosure", "source": pin})
    assert correct.status_code == 201, correct.text
    assert correct.json()["facts"]["source"] == pin
    with get_session_factory()() as session:
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == source_family["docket_id"],
            )
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(f"{BASE}/{correct.json()['id']}", headers=headers).status_code == 404
    assert client.get(BASE, headers=headers).json()["families"] == []
    denied_source = _create(
        client, headers, {**facts, "source": {**pin, "content_sha256": "0" * 64}}
    )
    assert denied_source.status_code == 404, denied_source.text


def test_pagination_search_and_malformed_inputs_are_bounded(client: TestClient):
    _, headers, facts = _setup(client)
    ids = set()
    for index in range(3):
        created = _create(client, headers, {**facts, "title": f"Disclosure {index}"})
        assert created.status_code == 201, created.text
        ids.add(created.json()["id"])
    seen = set()
    cursor = None
    while True:
        response = client.get(
            BASE,
            headers=headers,
            params={
                "limit": 1,
                **({"cursor": cursor} if cursor else {}),
            },
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["families"]) == 1
        seen.add(page["families"][0]["id"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ids
    assert (
        len(client.get(BASE, headers=headers, params={"q": "Disclosure 1"}).json()["families"]) == 1
    )
    for params in (
        {"limit": 101},
        {"limit": 0},
        {"cursor": "invented"},
        {"q": "x" * 201},
        {"status_scope": "invented"},
    ):
        assert client.get(BASE, headers=headers, params=params).status_code == 422
    assert client.post(BASE, headers=headers, json=facts).status_code == 422
    for params in ({"limit": 101}, {"limit": 0}, {"cursor": 0}, {"cursor": "invented"}):
        assert (
            client.get(
                f"{BASE}/{next(iter(ids))}/lifecycle-history", headers=headers, params=params
            ).status_code
            == 422
        )
    for change in (
        {"confidentiality": "public"},
        {"status": "closed"},
        {"company_id": str(uuid4())},
    ):
        assert _create(client, headers, {**facts, **change}).status_code == 422


@pytest.mark.parametrize("create_with_source", [True, False])
def test_source_pin_atomically_adds_canonical_disclosure_link_and_private_fence(
    client: TestClient,
    create_with_source: bool,
):
    bootstrap, headers, facts = _setup(client)
    trademark = _docket(client, headers, "Existing source record")
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    uploaded = _upload(
        client,
        headers,
        filename="source-to-restrict.txt",
        content=b"Source evidence. " * 40,
        docket_id=trademark["id"],
    )["document"]
    document_id = uploaded["id"]
    version = uploaded["versions"][0]
    pin = {
        "kind": "document_version",
        "document_id": document_id,
        "document_version_id": version["id"],
        "content_sha256": version["sha256_hex"],
    }
    company_id = bootstrap["company"]["id"]
    with get_session_factory()() as session:
        assert disclosable_ip_document_ids(
            session,
            company_id=company_id,
            document_ids={document_id},
        ) == {document_id}
    family = _create(
        client, headers, {**facts, **({"source": pin} if create_with_source else {})}
    ).json()
    if not create_with_source:
        corrected = client.post(
            f"{BASE}/{family['id']}/corrections",
            headers=headers,
            json=_correction(family, source=pin),
        )
        assert corrected.status_code == 200, corrected.text
        family = corrected.json()
    with get_session_factory()() as session:
        assert (
            disclosable_ip_document_ids(
                session,
                company_id=company_id,
                document_ids={document_id},
            )
            == set()
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpDocumentLink)
                .where(
                    IpDocumentLink.document_id == document_id,
                    IpDocumentLink.docket_id == family["docket_id"],
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(PrivateProjectionEvent.id).where(
                    PrivateProjectionEvent.company_id == company_id,
                    PrivateProjectionEvent.target_id == document_id,
                    PrivateProjectionEvent.reason_code == "patent_disclosure_source_linked",
                )
            )
            is not None
        )
    corrected = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, source=None),
    )
    assert corrected.status_code == 200, corrected.text
    with get_session_factory()() as session:
        assert (
            disclosable_ip_document_ids(
                session,
                company_id=company_id,
                document_ids={document_id},
            )
            == set()
        )
    assert client.get(f"/api/ip/documents/{document_id}", headers=headers).status_code == 200
    assert client.get(f"/api/ip/dockets/{trademark['id']}", headers=headers).status_code == 200


def test_restricting_an_existing_source_requires_document_management_and_rolls_back(client):
    bootstrap, headers, facts = _setup(client)
    trademark = _docket(client, headers, "Existing client document")
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    uploaded = _upload(
        client,
        headers,
        filename="original-client-document.txt",
        content=b"Source evidence. " * 40,
        docket_id=trademark["id"],
    )["document"]
    version = uploaded["versions"][0]
    with get_session_factory()() as session:
        actor = session.get(CompanyMembership, bootstrap["membership"]["id"])
        actor.role = MembershipRole.MEMBER
        session.commit()
    rejected = _create(
        client,
        headers,
        {
            **facts,
            "source": {
                "kind": "document_version",
                "document_id": uploaded["id"],
                "document_version_id": version["id"],
                "content_sha256": version["sha256_hex"],
            },
        },
    )
    assert rejected.status_code == 403, rejected.text
    assert "documents:manage" in rejected.text
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentFamily)) == 0
        assert session.scalar(select(func.count()).select_from(IpDocumentLink)) == 1
        assert disclosable_ip_document_ids(
            session,
            company_id=bootstrap["company"]["id"],
            document_ids={uploaded["id"]},
        ) == {uploaded["id"]}
    allowed = _create(client, headers, facts)
    assert allowed.status_code == 201, allowed.text


def test_family_foreign_keys_and_source_hash_constraints_reject_invalid_direct_writes(
    client: TestClient,
):
    bootstrap, headers, facts = _setup(client)
    response = _create(client, headers, facts)
    assert response.status_code == 201, response.text
    family = response.json()
    with get_session_factory()() as session:
        source = session.scalar(select(IpPatentFamilyVersion))
        values = {column.name: getattr(source, column.name) for column in source.__table__.columns}
        for changes in (
            {"family_id": str(uuid4())},
            {"company_id": str(uuid4())},
            {"created_by_membership_id": str(uuid4())},
            {"source_document_version_id": str(uuid4()), "source_sha256": None},
            {"source_sha256": "a" * 64},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    IpPatentFamilyVersion(
                        **{
                            **values,
                            "id": str(uuid4()),
                            "version": 2,
                            **changes,
                        }
                    )
                )
                session.flush()
        assert session.get(IpPatentFamily, family["id"]).company_id == bootstrap["company"]["id"]


def test_patent_version_database_guard_rejects_update_delete_but_allows_correction(client):
    _, headers, facts = _setup(client)
    family = _create(client, headers, facts).json()
    with get_session_factory()() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN "
                    "('trg_patent_family_versions_append_only_update', "
                    "'trg_patent_family_versions_append_only_delete')"
                )
            )
            == 2
        )
        for statement in (
            "UPDATE ip_patent_family_versions SET title='Overwritten' WHERE family_id=:id",
            "DELETE FROM ip_patent_family_versions WHERE family_id=:id",
        ):
            with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
                session.execute(text(statement), {"id": family["id"]})
        session.rollback()
    corrected = client.post(
        f"{BASE}/{family['id']}/corrections",
        headers=headers,
        json=_correction(family, title="Legitimate corrected title"),
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["version"] == 2
    original = client.get(f"{BASE}/{family['id']}/versions/1", headers=headers)
    assert original.status_code == 200, original.text
    assert original.json()["facts"] == family["facts"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/ip/patents/families",
        "/api/ip/patents/families/00000000-0000-0000-0000-000000000000",
        "/api/ip/patents/families/00000000-0000-0000-0000-000000000000/versions/1",
        "/api/ip/patents/families/00000000-0000-0000-0000-000000000000/lifecycle-history",
    ],
)
def test_patent_family_reads_require_authentication(client: TestClient, path: str):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/api/ip/patents/families",
        "/api/ip/patents/families/00000000-0000-0000-0000-000000000000/corrections",
    ],
)
def test_patent_family_writes_require_authentication(client: TestClient, path: str):
    assert client.post(path, json={}).status_code == 403
    assert (
        client.post(
            path,
            json={},
            headers={"Authorization": "Bearer invalid-test-token"},
        ).status_code
        == 401
    )
