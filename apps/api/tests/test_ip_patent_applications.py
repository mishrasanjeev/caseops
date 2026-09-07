from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    IpPatentApplication,
    IpPatentApplicationIdentifier,
    IpPatentApplicationIdentity,
    IpPatentApplicationVersion,
    IpTrademarkParticularVersion,
    MatterAccessGrant,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_domain_policy import disclosable_ip_document_ids
from tests.test_ip_document_workflow import _upload
from tests.test_ip_patent_families import BASE as FAMILIES
from tests.test_ip_patent_families import _create as _create_family
from tests.test_ip_patent_families import _setup as _setup_family

BASE = "/api/ip/patents/applications"


def _setup(client: TestClient) -> tuple[dict, dict, dict, dict]:
    bootstrap, headers, facts = _setup_family(client)
    response = _create_family(client, headers, facts)
    assert response.status_code == 201, response.text
    family = response.json()
    return bootstrap, headers, family, _payload(client, headers, family)


def _payload(client: TestClient, headers: dict, family: dict) -> dict:
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    document = _upload(
        client,
        headers,
        filename="sourced-application.txt",
        content=b"Original patent application evidence. " * 30,
        docket_id=family["docket_id"],
        confidentiality="restricted",
    )["document"]
    pin = {
        "kind": "document_version",
        "document_id": document["id"],
        "document_version_id": document["versions"][0]["id"],
        "content_sha256": document["versions"][0]["sha256_hex"],
    }
    payload = {
        "family_id": family["id"],
        "expected_family_version": family["version"],
        "expected_family_lifecycle_version": family["lifecycle_version"],
        "facts": {
            "title": "Sourced substrate application",
            "application_kind": "complete",
            "jurisdiction": "IN",
            "office": "IP India",
            "filing_date": "2026-09-05",
            "source": pin,
            "identifiers": [
                {"identifier_kind": "application", "raw_value": "  IN/2026/001-A  ", "source": pin}
            ],
        },
    }
    return payload


def _create(client: TestClient, headers: dict, payload: dict, key: str | None = None):
    return client.post(
        BASE, headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=payload
    )


def _correction(application: dict, **changes) -> dict:
    return {
        "expected_version": application["version"],
        "expected_lifecycle_version": application["lifecycle_version"],
        "reason": "Correct the source transcription without changing prosecution.",
        "facts": {**application["facts"], **changes},
    }


def _closed(client: TestClient, headers: dict, docket_id: str):
    response = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Client explicitly closed this individual application.",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "test:application-client-instruction",
            "linked_matter_handling": "reviewed",
        },
    )
    assert response.status_code == 200, response.text


def test_independent_applications_preserve_sources_identifiers_and_family_history(
    client: TestClient,
):
    bootstrap, headers, family, payload = _setup(client)
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    application = created.json()
    assert application["record_kind"] == "patent_application"
    assert application["prosecution_phase"] == "disclosure"
    assert application["facts"]["identifiers"] == payload["facts"]["identifiers"]
    assert application["docket_id"] != family["docket_id"]
    sibling = _create(
        client,
        headers,
        {**payload, "facts": {**payload["facts"], "office": "Separate sourced office"}},
    )
    assert sibling.status_code == 201, sibling.text
    assert sibling.json()["docket_id"] != application["docket_id"]
    corrected = client.post(
        f"/api/ip/patents/applications/{application['id']}/corrections",
        headers=headers,
        json=_correction(application, title="Corrected sourced application"),
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["version"] == 2
    assert corrected.json()["prosecution_phase"] == "disclosure"
    assert client.get(f"{BASE}/{application['id']}", headers=headers).json() == corrected.json()
    original_version = client.get(
        f"/api/ip/patents/applications/{application['id']}/versions/1", headers=headers
    )
    assert original_version.status_code == 200, original_version.text
    assert original_version.json()["facts"] == application["facts"]
    assert client.get(f"{FAMILIES}/{family['id']}", headers=headers).json() == family
    assert client.get(f"{BASE}/{sibling.json()['id']}", headers=headers).json() == sibling.json()
    page = client.get(BASE, headers=headers, params={"family_id": family["id"]})
    assert page.status_code == 200, page.text
    assert {row["id"] for row in page.json()["applications"]} == {
        application["id"],
        sibling.json()["id"],
    }
    assert client.get("/api/ip/dockets", headers=headers).json()["dockets"] == []
    assert (
        client.get(f"/api/ip/dockets/{application['docket_id']}", headers=headers).status_code
        == 409
    )
    with get_session_factory()() as session:
        for model in (TrademarkApplication, IpTrademarkParticularVersion):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            disclosable_ip_document_ids(
                session,
                company_id=bootstrap["company"]["id"],
                document_ids={payload["facts"]["source"]["document_id"]},
            )
            == set()
        )
        assert set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.target_id == application["id"])
            )
        ) >= {
            "ip_patent_application.created",
            "ip_patent_application.corrected",
        }


def test_current_identifier_uniqueness_and_correction_rollback_preserve_immutable_history(client):
    _, headers, _, payload = _setup(client)
    first = _create(client, headers, payload)
    assert first.status_code == 201, first.text
    application = first.json()
    equivalent = {
        **payload,
        "facts": {
            **payload["facts"],
            "office": "  ip   INDIA  ",
            "identifiers": [{**payload["facts"]["identifiers"][0], "raw_value": "in/2026/001-a"}],
        },
    }
    duplicate = _create(client, headers, equivalent)
    assert duplicate.status_code == 409 and "patent_identifier_exists" in duplicate.text
    changed = client.post(
        f"{BASE}/{application['id']}/corrections",
        headers=headers,
        json=_correction(
            application,
            identifiers=[{**application["facts"]["identifiers"][0], "raw_value": "Corrected-002"}],
        ),
    )
    assert changed.status_code == 200, changed.text
    replacement = _create(client, headers, payload)
    assert replacement.status_code == 201, replacement.text
    collision = client.post(
        f"{BASE}/{application['id']}/corrections",
        headers=headers,
        json=_correction(
            changed.json(),
            identifiers=application["facts"]["identifiers"],
        ),
    )
    assert collision.status_code == 409, collision.text
    assert client.get(f"{BASE}/{application['id']}", headers=headers).json() == changed.json()
    assert (
        client.get(f"{BASE}/{application['id']}/versions/1", headers=headers).json()["facts"]
        == application["facts"]
    )
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentApplication)) == 2
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationVersion)) == 3
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationIdentifier)) == 3
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationIdentity)) == 2


def test_pending_identifiers_search_pagination_and_stale_write_are_explicit(client):
    _, headers, family, payload = _setup(client)
    pending = {
        **payload,
        "facts": {
            **payload["facts"],
            "identifiers": [],
            "source_pending_identifier_allocation": True,
        },
    }
    result = _create(client, headers, pending)
    assert result.status_code == 201, result.text
    application = result.json()
    allocated = client.post(
        f"{BASE}/{application['id']}/corrections",
        headers=headers,
        json=_correction(
            application,
            identifiers=payload["facts"]["identifiers"],
            source_pending_identifier_allocation=False,
        ),
    )
    assert allocated.status_code == 200, allocated.text
    stale = client.post(
        f"{BASE}/{application['id']}/corrections", headers=headers, json=_correction(application)
    )
    assert stale.status_code == 409 and "patent_application_stale" in stale.text
    searched = client.get(BASE, headers=headers, params={"q": "in/2026/001-a"})
    assert searched.status_code == 200 and searched.json()["applications"] == [allocated.json()]
    for office in ("Office B", "Office C"):
        response = _create(
            client, headers, {**payload, "facts": {**payload["facts"], "office": office}}
        )
        assert response.status_code == 201, response.text
    seen = set()
    cursor = None
    for _ in range(4):
        page = client.get(
            BASE,
            headers=headers,
            params={
                "limit": 1,
                "family_id": family["id"],
                **({"cursor": cursor} if cursor else {}),
            },
        )
        assert page.status_code == 200, page.text
        for row in page.json()["applications"]:
            assert row["id"] not in seen
            seen.add(row["id"])
        cursor = page.json()["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 3 and cursor is None
    for params in (
        {"limit": 101},
        {"limit": 0},
        {"cursor": "invented"},
        {"status_scope": "invented"},
        {"q": "x" * 201},
    ):
        assert client.get(BASE, headers=headers, params=params).status_code == 422


def test_terminal_application_is_read_only_and_does_not_close_its_family(client):
    _, headers, family, payload = _setup(client)
    key = str(uuid4())
    response = _create(client, headers, payload, key)
    assert response.status_code == 201, response.text
    application = response.json()
    _closed(client, headers, application["docket_id"])
    assert _create(client, headers, payload, key).status_code == 404
    assert (
        client.post(
            f"{BASE}/{application['id']}/corrections",
            headers=headers,
            json=_correction(application),
        ).status_code
        == 404
    )
    retained = client.get(f"{BASE}/{application['id']}", headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["facts"] == application["facts"]
    assert retained.json()["is_active"] is False
    history = client.get(
        f"/api/ip/patents/applications/{application['id']}/lifecycle-history", headers=headers
    )
    assert history.status_code == 200, history.text
    assert len(history.json()["events"]) == 1
    assert history.json()["events"][0]["to_status"] == "closed"
    assert client.get(BASE, headers=headers).json()["applications"] == []
    assert client.get(BASE, headers=headers, params={"status_scope": "terminal"}).json()[
        "applications"
    ] == [retained.json()]
    assert client.get(f"{FAMILIES}/{family['id']}", headers=headers).json() == family
    source = application["facts"]["source"]
    download = client.get(
        f"/api/ip/documents/{source['document_id']}/versions/1/download", headers=headers
    )
    assert download.status_code == 200, download.text
    assert download.content == b"Original patent application evidence. " * 30


def test_closed_sibling_and_family_sources_do_not_block_active_application_corrections(client):
    _, headers, family, payload = _setup(client)
    first = _create(client, headers, payload)
    assert first.status_code == 201, first.text
    pending = {
        **payload,
        "facts": {
            **payload["facts"],
            "identifiers": [],
            "source_pending_identifier_allocation": True,
        },
    }
    sibling = _create(client, headers, pending)
    assert sibling.status_code == 201, sibling.text
    _closed(client, headers, first.json()["docket_id"])
    retained = client.get(f"{BASE}/{first.json()['id']}", headers=headers).json()
    history = client.get(f"{BASE}/{first.json()['id']}/lifecycle-history", headers=headers).json()
    corrected = client.post(
        f"{BASE}/{sibling.json()['id']}/corrections",
        headers=headers,
        json=_correction(sibling.json(), title="Still active sibling"),
    )
    assert corrected.status_code == 200, corrected.text
    third = _create(client, headers, pending)
    assert third.status_code == 201, third.text
    _closed(client, headers, family["docket_id"])
    corrected_again = client.post(
        f"{BASE}/{sibling.json()['id']}/corrections",
        headers=headers,
        json=_correction(corrected.json(), title="Independent active record"),
    )
    assert corrected_again.status_code == 200, corrected_again.text
    assert corrected_again.json()["version"] == 3
    assert client.get(f"{BASE}/{first.json()['id']}", headers=headers).json() == retained
    assert (
        client.get(f"{BASE}/{first.json()['id']}/lifecycle-history", headers=headers).json()
        == history
    )
    assert _create(client, headers, pending).status_code == 404
    assert (
        client.post(
            f"{BASE}/{first.json()['id']}/corrections", headers=headers, json=_correction(retained)
        ).status_code
        == 404
    )
    with get_session_factory()() as session:
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == first.json()["docket_id"]
            )
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()
    denied = client.post(
        f"{BASE}/{sibling.json()['id']}/corrections",
        headers=headers,
        json=_correction(corrected_again.json(), title="Revoked source must reject"),
    )
    assert denied.status_code == 404, denied.text


def test_source_read_exception_never_admits_a_terminal_mutation_target(client):
    from caseops_api.db.models import IpDocketRecord

    _, headers, _, payload = _setup(client)
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    application = created.json()
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, application["docket_id"])
        docket.status = "closed"
        assert docket.is_active
        with pytest.raises(IntegrityError, match="ck_ip_docket_status_active_consistent"):
            session.commit()
        session.rollback()
        assert session.get(IpDocketRecord, application["docket_id"]).is_active
    _closed(client, headers, application["docket_id"])
    denied = client.post(
        f"{BASE}/{application['id']}/corrections",
        headers=headers,
        json=_correction(application, title="Inconsistent lifecycle must reject"),
    )
    assert denied.status_code == 404, denied.text
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentApplicationVersion)) == 1


def test_sources_hash_replay_revocation_and_parent_version_fail_closed(client):
    _, headers, family, payload = _setup(client)
    for changes, code in (
        ({"expected_family_version": 2}, "patent_family_stale"),
        ({"expected_family_lifecycle_version": 1}, "patent_family_stale"),
    ):
        response = _create(client, headers, {**payload, **changes})
        assert response.status_code == 409 and code in response.text
    wrong_pin = {**payload["facts"]["source"], "content_sha256": "0" * 64}
    for facts in (
        {**payload["facts"], "source": wrong_pin},
        {
            **payload["facts"],
            "identifiers": [{**payload["facts"]["identifiers"][0], "source": wrong_pin}],
        },
    ):
        response = _create(client, headers, {**payload, "facts": facts})
        assert response.status_code == 409 and "patent_source_changed" in response.text
    key = str(uuid4())
    created = _create(client, headers, payload, key)
    assert created.status_code == 201, created.text
    application = created.json()
    assert _create(client, headers, payload, key).json() == application
    assert (
        _create(
            client,
            headers,
            {**payload, "facts": {**payload["facts"], "title": "Other intent"}},
            key,
        ).status_code
        == 409
    )
    with get_session_factory()() as session:
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == application["docket_id"]
            )
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(f"{BASE}/{application['id']}", headers=headers).status_code == 404
    assert client.get(f"{BASE}/{application['id']}/versions/1", headers=headers).status_code == 404
    assert (
        client.get(f"{BASE}/{application['id']}/lifecycle-history", headers=headers).status_code
        == 404
    )
    assert client.get(BASE, headers=headers).json()["applications"] == []
    assert _create(client, headers, payload, key).status_code == 404
    assert client.get(f"{FAMILIES}/{family['id']}", headers=headers).json() == family


def test_application_version_and_identifier_rows_are_database_append_only(client):
    _, headers, _, payload = _setup(client)
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    application = created.json()
    with get_session_factory()() as session:
        for statement in (
            "UPDATE ip_patent_application_versions SET title='forged' WHERE application_id=:id",
            "DELETE FROM ip_patent_application_versions WHERE application_id=:id",
            "UPDATE ip_patent_application_identifiers SET raw_value='forged' "
            "WHERE application_id=:id",
            "DELETE FROM ip_patent_application_identifiers WHERE application_id=:id",
        ):
            with pytest.raises(IntegrityError, match="append-only"), session.begin_nested():
                session.execute(text(statement), {"id": application["id"]})
        session.rollback()
    assert client.get(f"{BASE}/{application['id']}", headers=headers).json() == application


def test_tenant_isolation_includes_sources_history_search_and_same_identifier_admission(client):
    _, headers, family, payload = _setup(client)
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    application = created.json()
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Separate Patent Firm",
            "company_slug": "separate-patent-firm",
            "company_type": "law_firm",
            "owner_full_name": "Separate Owner",
            "owner_email": "owner@separate-patent.example.com",
            "owner_password": "SeparateTest123!",
        },
    )
    assert response.status_code == 200, response.text
    other_headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    # Bootstrap changes this TestClient's session cookie. Explicit bearer
    # requests below must not accidentally keep selecting the last cookie tenant.
    client.cookies.clear()
    for suffix in ("", "/versions/1", "/lifecycle-history"):
        assert (
            client.get(f"{BASE}/{application['id']}{suffix}", headers=other_headers).status_code
            == 404
        )
    assert (
        client.get(BASE, headers=other_headers, params={"q": "IN/2026/001-A"}).json()[
            "applications"
        ]
        == []
    )
    assert (
        client.get(BASE, headers=other_headers, params={"family_id": family["id"]}).status_code
        == 404
    )
    assert _create(client, other_headers, payload).status_code == 404
    assert (
        client.post(
            f"{BASE}/{application['id']}/corrections",
            headers=other_headers,
            json=_correction(application),
        ).status_code
        == 404
    )
    other_client = client.post(
        "/api/clients",
        headers=other_headers,
        json={"name": "Separate Patent Client", "client_type": "corporate"},
    )
    assert other_client.status_code == 200, other_client.text
    other_family = _create_family(
        client,
        other_headers,
        {
            **family["facts"],
            "client_id": other_client.json()["id"],
        },
    )
    assert other_family.status_code == 201, other_family.text
    own_payload = _payload(client, other_headers, other_family.json())
    for facts in (
        {**own_payload["facts"], "source": payload["facts"]["source"]},
        {**own_payload["facts"], "identifiers": payload["facts"]["identifiers"]},
    ):
        denied = _create(client, other_headers, {**own_payload, "facts": facts})
        assert denied.status_code == 404 and "patent_source_not_found" in denied.text
    own = _create(client, other_headers, own_payload)
    assert own.status_code == 201, own.text
    assert (
        own.json()["facts"]["identifiers"][0]["raw_value"]
        == payload["facts"]["identifiers"][0]["raw_value"]
    )
    assert client.get(BASE, headers=headers).json()["applications"] == [application]
    assert client.get(BASE, headers=other_headers).json()["applications"] == [own.json()]


def test_unavailable_registry_and_normalized_duplicate_sources_roll_back_all_admission(client):
    _, headers, _, payload = _setup(client)
    registry = {
        "kind": "registry_snapshot",
        "snapshot_id": str(uuid4()),
        "raw_sha256": "a" * 64,
        "normalized_sha256": "b" * 64,
    }
    for facts in (
        {**payload["facts"], "source": registry},
        {
            **payload["facts"],
            "identifiers": [{**payload["facts"]["identifiers"][0], "source": registry}],
        },
    ):
        response = _create(client, headers, {**payload, "facts": facts})
        assert response.status_code == 409 and "patent_registry_source_unavailable" in response.text
    duplicate = _create(
        client,
        headers,
        {
            **payload,
            "facts": {
                **payload["facts"],
                "identifiers": [
                    *payload["facts"]["identifiers"],
                    {**payload["facts"]["identifiers"][0], "raw_value": "in/2026/001-a"},
                ],
            },
        },
    )
    assert duplicate.status_code == 422 and "patent_identifier_duplicate" in duplicate.text
    with get_session_factory()() as session:
        for model in (
            IpPatentApplication,
            IpPatentApplicationVersion,
            IpPatentApplicationIdentifier,
            IpPatentApplicationIdentity,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    assert _create(client, headers, payload).status_code == 201


def test_identity_digest_collision_fails_closed_without_merging_different_identifiers(
    client, monkeypatch
):
    from caseops_api.services import ip_patent_applications as service

    _, headers, _, payload = _setup(client)
    original_hash = service.canonical_json_sha256
    monkeypatch.setattr(
        service,
        "canonical_json_sha256",
        lambda value: "a" * 64 if "value_key" in value else original_hash(value),
    )
    created = _create(client, headers, payload)
    assert created.status_code == 201, created.text
    collision = _create(
        client,
        headers,
        {
            **payload,
            "facts": {
                **payload["facts"],
                "identifiers": [
                    {**payload["facts"]["identifiers"][0], "raw_value": "Different-002"}
                ],
            },
        },
    )
    assert collision.status_code == 409 and "patent_identifier_integrity" in collision.text
    assert client.get(BASE, headers=headers).json()["applications"] == [created.json()]


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/00000000-0000-0000-0000-000000000000",
        "/00000000-0000-0000-0000-000000000000/versions/1",
    ],
)
def test_application_reads_require_authentication(client, suffix):
    assert client.get(BASE + suffix).status_code == 401


@pytest.mark.parametrize("suffix", ["", "/00000000-0000-0000-0000-000000000000/corrections"])
def test_application_mutations_require_authentication(client, suffix):
    assert client.post(BASE + suffix, json={}).status_code == 403
    assert (
        client.post(
            BASE + suffix, json={}, headers={"Authorization": "Bearer invalid-test-token"}
        ).status_code
        == 401
    )
