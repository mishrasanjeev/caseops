from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import AuditEvent, IpPartyAndRole, IpPatentPartyDetail, MatterAccessGrant
from caseops_api.db.session import get_session_factory
from tests.test_ip_patent_applications import _closed, _create, _setup


def _fixture(client, kind="application"):
    bootstrap, headers, family, application_payload = _setup(client)
    if kind == "application":
        response = _create(client, headers, application_payload)
        assert response.status_code == 201, response.text
        record = response.json()
    else:
        record = family
    base = f"/api/ip/patents/dockets/{record['docket_id']}/parties"
    payload = {
        "expected_version": record["version"],
        "expected_lifecycle_version": record["lifecycle_version"],
        "expected_party_sequence": 0,
        "reason": "Record exact parties from the signed source evidence.",
        "fact": {
            "role": "inventor",
            "name": "Original Inventor",
            "client_id": family["facts"]["client_id"],
            "address": {
                "address_lines": ["Original address", "Unit 10"],
                "city": "Delhi",
                "region": "Delhi",
                "postal_code": "110001",
                "country_code": "IN",
            },
            "effective_from": "2026-09-01",
            "effective_until": None,
            "source": application_payload["facts"]["source"],
        },
    }
    return bootstrap, headers, family, record, base, payload


def _post(client, base, headers, payload, key=None):
    return client.post(
        base, headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=payload
    )


@pytest.mark.parametrize("kind", ["family", "application"])
def test_all_patent_party_roles_preserve_canonical_facts_and_sourced_replacement(client, kind):
    _, headers, family, record, base, payload = _fixture(client, kind)
    originals = []
    for sequence, role in enumerate(["inventor", "applicant", "proprietor", "agent", "licensee"]):
        request = deepcopy(payload)
        request["expected_party_sequence"] = sequence
        request["fact"]["role"] = role
        request["fact"]["name"] = f"Original {role}"
        key = str(uuid4())
        response = _post(client, base, headers, request, key)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["fact"] == request["fact"]
        assert saved["sequence"] == sequence + 1 and saved["is_current"]
        assert _post(client, base, headers, request, key).json() == saved
        assert client.get(f"{base}/{saved['id']}", headers=headers).json() == saved
        originals.append(saved)
    replacement = deepcopy(payload)
    replacement.update(expected_party_sequence=5, supersedes_party_id=originals[0]["id"])
    replacement["fact"]["name"] = "Corrected inventor transcription"
    replacement["fact"]["address"]["address_lines"] = ["New sourced address"]
    replacement["fact"]["effective_from"] = "2026-09-05"
    response = _post(client, base, headers, replacement)
    assert response.status_code == 201, response.text
    successor = response.json()
    current = client.get(base, headers=headers).json()
    assert current["collection_sequence"] == 6 and len(current["parties"]) == 5
    assert current["parties"][0] == successor
    assert originals[0]["id"] not in {party["id"] for party in current["parties"]}
    history = client.get(base, headers=headers, params={"history": True}).json()
    assert len(history["parties"]) == 6
    retained = client.get(
        f"/api/ip/patents/dockets/{record['docket_id']}/parties/{originals[0]['id']}",
        headers=headers,
    )
    assert retained.status_code == 200, retained.text
    assert retained.json() == {**originals[0], "is_current": False}
    assert client.get(f"/api/ip/patents/families/{family['id']}", headers=headers).json() == family
    if kind == "application":
        assert (
            client.get(f"/api/ip/patents/applications/{record['id']}", headers=headers).json()
            == record
        )
    with get_session_factory()() as session:
        parties = list(
            session.scalars(
                select(IpPartyAndRole).where(IpPartyAndRole.docket_id == record["docket_id"])
            )
        )
        assert len(parties) == 6
        assert {row.id for row in parties} == {party["id"] for party in history["parties"]}
        assert session.get(IpPartyAndRole, originals[0]["id"]).party_name == "Original inventor"
        assert set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.target_id == successor["id"])
            )
        ) == {"ip_patent_party.superseded"}


def test_patent_party_stale_duplicate_and_second_supersession_are_atomic(client):
    _, headers, _, _, base, payload = _fixture(client)
    initial = _post(client, base, headers, payload)
    assert initial.status_code == 201, initial.text
    first = initial.json()
    assert _post(client, base, headers, payload).status_code == 409
    current = {**payload, "expected_party_sequence": 1}
    duplicate = _post(client, base, headers, current)
    assert duplicate.status_code == 409 and "patent_party_exists" in duplicate.text
    for changes in [{"expected_version": 2}, {"expected_lifecycle_version": 1}]:
        rejected = _post(client, base, headers, {**current, **changes})
        assert rejected.status_code == 409, rejected.text
    replacement = {
        **current,
        "supersedes_party_id": first["id"],
        "fact": {**payload["fact"], "name": "Corrected inventor"},
    }
    accepted = _post(client, base, headers, replacement)
    assert accepted.status_code == 201, accepted.text
    repeated = _post(client, base, headers, {**replacement, "expected_party_sequence": 2})
    assert repeated.status_code == 409 and "patent_party_not_current" in repeated.text
    assert (
        client.get(base, headers=headers, params={"history": True}).json()["collection_sequence"]
        == 2
    )


def test_patent_party_sources_clients_dates_and_immutable_rows_are_enforced(client):
    _, headers, _, record, base, payload = _fixture(client)
    for field in ("document_id", "document_version_id"):
        invalid = deepcopy(payload)
        invalid["fact"]["source"][field] = str(uuid4())
        assert _post(client, base, headers, invalid).status_code == 404
    invalid = deepcopy(payload)
    invalid["fact"]["source"]["content_sha256"] = "0" * 64
    assert _post(client, base, headers, invalid).status_code == 409
    for changes, status in [
        ({"client_id": str(uuid4())}, 404),
        ({"effective_until": "2026-08-31"}, 422),
    ]:
        assert (
            _post(
                client, base, headers, {**payload, "fact": {**payload["fact"], **changes}}
            ).status_code
            == status
        )
    response = _post(client, base, headers, payload)
    assert response.status_code == 201, response.text
    party = response.json()
    with get_session_factory()() as session:
        for statement in (
            "UPDATE ip_parties_and_roles SET party_name = 'Overwritten' WHERE id = :id",
            "DELETE FROM ip_parties_and_roles WHERE id = :id",
            "UPDATE ip_patent_party_details SET reason = 'Overwritten reason' WHERE id = :id",
            "DELETE FROM ip_patent_party_details WHERE id = :id",
        ):
            with pytest.raises(IntegrityError, match="append-only"):
                session.execute(text(statement), {"id": party["id"]})
                session.commit()
            session.rollback()
        assert session.scalar(select(func.count()).select_from(IpPatentPartyDetail)) == 1
    assert client.get(f"{base}/{party['id']}", headers=headers).json() == party
    _closed(client, headers, record["docket_id"])
    denied = _post(
        client,
        base,
        headers,
        {**payload, "expected_party_sequence": 1, "expected_lifecycle_version": 1},
    )
    assert denied.status_code == 404, denied.text
    assert client.get(base, headers=headers).json()["parties"] == [party]


def test_patent_party_pages_pin_sequence_and_reject_stale_continuation(client):
    _, headers, _, _, base, payload = _fixture(client)
    for sequence in range(4):
        response = _post(
            client,
            base,
            headers,
            {
                **payload,
                "expected_party_sequence": sequence,
                "fact": {**payload["fact"], "name": f"Inventor {sequence}"},
            },
        )
        assert response.status_code == 201, response.text
    first = client.get(base, headers=headers, params={"limit": 2}).json()
    assert [party["sequence"] for party in first["parties"]] == [4, 3]
    continuation = {"limit": 2, "cursor": first["next_cursor"], "snapshot_sequence": 4}
    second = client.get(base, headers=headers, params=continuation).json()
    assert [party["sequence"] for party in second["parties"]] == [2, 1]
    assert second["next_cursor"] is None
    assert client.get(base, headers=headers, params={"cursor": 3}).status_code == 422
    response = _post(
        client,
        base,
        headers,
        {
            **payload,
            "expected_party_sequence": 4,
            "fact": {**payload["fact"], "name": "Later inventor"},
        },
    )
    assert response.status_code == 201, response.text
    assert client.get(base, headers=headers, params=continuation).status_code == 409


def test_patent_party_tenant_scope_closed_source_and_access_revocation(client):
    bootstrap, headers, family, record, base, payload = _fixture(client)
    created = _post(client, base, headers, payload)
    assert created.status_code == 201, created.text
    party = created.json()
    _closed(client, headers, family["docket_id"])
    corrected = {
        **payload,
        "expected_party_sequence": 1,
        "supersedes_party_id": party["id"],
        "fact": {**payload["fact"], "name": "Active application party"},
    }
    response = _post(client, base, headers, corrected)
    assert response.status_code == 201, response.text
    client.cookies.clear()
    other_tenant = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Separate Party Firm",
            "company_slug": "separate-party-firm",
            "company_type": "law_firm",
            "owner_full_name": "Separate Owner",
            "owner_email": "owner@separate-party.example.com",
            "owner_password": "SeparateTest123!",
        },
    )
    assert other_tenant.status_code == 200, other_tenant.text
    other_headers = {"Authorization": f"Bearer {other_tenant.json()['access_token']}"}
    client.cookies.clear()
    other_client = client.post(
        "/api/clients",
        headers=other_headers,
        json={"name": "Other client", "client_type": "corporate"},
    )
    assert other_client.status_code == 200, other_client.text
    other_family = client.post(
        "/api/ip/patents/families",
        headers={**other_headers, "Idempotency-Key": str(uuid4())},
        json={
            "title": "Other family",
            "client_id": other_client.json()["id"],
            "disclosure_date": "2026-09-01",
            "disclosure_narrative": "Separate invention disclosure.",
        },
    )
    assert other_family.status_code == 201, other_family.text
    other_base = f"/api/ip/patents/dockets/{other_family.json()['docket_id']}/parties"
    other_payload = {**payload, "fact": {**payload["fact"], "client_id": other_client.json()["id"]}}
    for suffix in ("", f"/{party['id']}"):
        assert client.get(base + suffix, headers=other_headers).status_code == 404
    invalid_source = {
        **other_payload,
        "fact": {**other_payload["fact"], "source": payload["fact"]["source"]},
    }
    assert _post(client, other_base, other_headers, invalid_source).status_code == 404
    client.cookies.clear()
    with get_session_factory()() as session:
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.company_id == bootstrap["company"]["id"],
                    MatterAccessGrant.ip_docket_id == family["docket_id"],
                )
            )
        )
        assert grants
        for grant in grants:
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(base, headers=headers).status_code == 404
    assert (
        _post(client, base, headers, {**corrected, "expected_party_sequence": 2}).status_code == 404
    )
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpPatentPartyDetail)
                .where(
                    IpPatentPartyDetail.docket_id == record["docket_id"],
                )
            )
            == 2
        )
