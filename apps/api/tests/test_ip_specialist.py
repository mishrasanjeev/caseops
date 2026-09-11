import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    IpAsset,
    IpDocketRecord,
    IpSpecialistObservation,
    IpSpecialistRecord,
    IpSpecialistVersion,
    MatterAccessGrant,
    PrivateProjectionEvent,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_specialist import SpecialistFacts, SpecialistObservation
from caseops_api.services import ip_domain_catalog as catalogue
from caseops_api.services.ip_domain_policy import general_ip_disclosure_allowed
from caseops_api.services.ip_specialist_contracts import (
    CHILD_PRD_HASHES,
    FACT_MODELS,
    JOURNEYS,
    LABELS,
    OBSERVATION_KINDS,
    contract_fields,
    contract_path,
    contract_version,
)
from tests.test_auth_company import auth_headers, bootstrap_company

BASE = "/api/ip/specialist"
# These endpoint templates are exercised through BASE and f-string helpers
# below. Keep the concrete paths visible to the route-coverage audit.
ROUTE_COVERAGE_PATHS = (
    "/api/ip/specialist/contracts",
    "/api/ip/specialist/records",
    "/api/ip/specialist/records/{record_id}",
    "/api/ip/specialist/records/{record_id}/observations",
    "/api/ip/specialist/records/{record_id}/versions/{version}",
)
DETAILS = {
    "design": {"applicant": "Client", "article": "Lamp casing"},
    "copyright": {
        "work_type_as_supplied": "Literary",
        "author": "Author",
        "claimant": "Client",
        "ownership_claim": "Claim under review",
    },
    "domain_name": {"domain_name": "example.test", "registrant_as_supplied": "Client"},
    "licensing": {
        "grantor": "Client",
        "grantee": "Licensee",
        "affected_rights_as_supplied": "Design reference",
        "territory": "As stated in clause 3",
    },
    "enforcement": {
        "represented_party": "Client",
        "asserted_right_as_supplied": "Copyright claim",
        "allegation": "Unreviewed allegation",
        "proposed_channel": "investigation",
    },
    "geographical_indication": {
        "applicant_or_association": "Association",
        "geographical_area": "Claimed region",
        "goods": "Textile",
    },
    "plant_variety": {
        "denomination": "Candidate",
        "category_as_supplied": "Unreviewed",
        "crop_species": "Crop",
        "applicant": "Client",
        "material_custodian": "Custodian",
        "material_access_instructions": "Restricted lab reference only",
    },
    "semiconductor_layout": {
        "creator": "Creator",
        "proprietor_as_supplied": "Client",
        "layout_description": "Restricted layout reference",
    },
    "trade_secret": {
        "owner_as_supplied": "Client",
        "custodian": "Custodian",
        "asset_reference": "Vault record 2",
        "protective_controls": "Restricted vault",
        "permitted_access_as_supplied": "Named custodians only",
    },
    "customs_enforcement": {
        "right_holder": "Client",
        "asserted_right_as_supplied": "Right reference",
        "products": "Product label",
        "authority_or_channel_as_supplied": "Authority in retained instruction",
        "authentication_guide_custodian": "Specialist",
        "authorised_importer_policy": "Retained policy reference",
        "instruction_reference": "Instruction 7",
    },
}


@pytest.fixture
def registered_intake(monkeypatch):
    definitions = tuple(
        row for row in catalogue.DOMAIN_DEFINITIONS if row.domain not in FACT_MODELS
    ) + tuple(
        catalogue.IpDomainDefinition(
            domain,
            LABELS[domain],
            contract_version(domain),
            contract_path(domain),
            True,
            (),
            (),
            JOURNEYS[domain],
            child_prd_sha256=CHILD_PRD_HASHES[domain],
        )
        for domain in FACT_MODELS
    )
    monkeypatch.setattr(catalogue, "DOMAIN_DEFINITIONS", definitions)
    monkeypatch.setattr(catalogue, "DOMAIN_BY_ID", {row.domain: row for row in definitions})


def setup(client, domain="design"):
    boot = bootstrap_company(client)
    headers = {
        **auth_headers(str(boot["access_token"])),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    response = client.post(
        "/api/clients",
        headers=headers,
        json={"name": "Specialist client", "client_type": "corporate"},
    )
    assert response.status_code == 200, response.text
    facts = {
        "title": f"Restricted {domain} intake",
        "client_id": response.json()["id"],
        "jurisdiction_as_supplied": "India - user supplied",
        "details": {"domain": domain, **DETAILS[domain]},
    }
    return headers, facts


def create(client, headers, facts, key=None):
    return client.post(
        f"{BASE}/records", headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=facts
    )


def observation(client, headers, record, *, kind=None, content=None):
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    if content is None:
        content = b"Private source evidence retained for this specialist record. " * 20
    upload = client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": "evidence",
                    "title": "source.txt",
                    "confidentiality": "restricted",
                    "asset_type": record["facts"]["details"]["domain"],
                    "links": [{"target_type": "docket", "target_id": record["docket_id"]}],
                }
            )
        },
        files={"upload": ("source.txt", content, "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["outcome"] == "created"
    document = upload.json()["document"]
    source = document["versions"][0]
    payload = {
        "expected_version": record["version"],
        "expected_lifecycle_version": record["lifecycle_version"],
        "kind": kind or OBSERVATION_KINDS[record["facts"]["details"]["domain"]][0],
        "occurred_on": "2026-09-09",
        "account": "Recorded from retained evidence, no legal determination.",
        "source": {
            "document_id": document["id"],
            "document_version_id": source["id"],
            "content_sha256": source["sha256_hex"],
            "locator": "page 1",
        },
    }
    return document, payload, content


def post_observation(client, headers, record, payload, key=None):
    return client.post(
        f"{BASE}/records/{record['id']}/observations",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json=payload,
    )


@pytest.mark.parametrize("domain", FACT_MODELS)
def test_domain_intake_and_source_journey(client, registered_intake, domain):
    headers, facts = setup(client, domain)
    response = create(client, headers, facts)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["facts"]["details"]["domain"] == domain
    assert client.get(f"{BASE}/records/{saved['id']}", headers=headers).json() == saved
    document, payload, _ = observation(client, headers, saved)
    result = post_observation(client, headers, saved, payload)
    assert result.status_code == 201, result.text
    assert result.json()["legal_effect"] == "not_determined"
    history = client.get(f"{BASE}/records/{saved['id']}/observations", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["observations"] == [result.json()]
    policy = client.get(f"/api/ip/documents/{document['id']}", headers=headers).json()
    assert policy["versions"][0]["ai_eligible"] is False, policy
    policy_response = client.get(f"/api/ip/documents/{document['id']}/policy", headers=headers)
    assert policy_response.status_code == 200, policy_response.text
    policy = policy_response.json()
    for field in ("portal_share_allowed", "export_allowed", "notification_content_allowed"):
        assert policy[field] is False, policy
    assert client.get("/api/ip/dockets", headers=headers).json()["dockets"] == []
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, saved["docket_id"])
        assert docket.restricted and docket.record_type == f"{domain}_intake"
        assert not general_ip_disclosure_allowed(docket)
        assert session.get(IpAsset, saved["asset_id"]).asset_kind == domain
        assert session.scalar(select(func.count()).select_from(TrademarkApplication)) == 0


def test_default_catalogue_is_fail_closed_and_read_contracts_are_not_activation(
    client, monkeypatch
):
    definitions = tuple(
        replace(row, intake_implemented=False) if row.domain in FACT_MODELS else row
        for row in catalogue.DOMAIN_DEFINITIONS
    )
    monkeypatch.setattr(catalogue, "DOMAIN_DEFINITIONS", definitions)
    monkeypatch.setattr(catalogue, "DOMAIN_BY_ID", {row.domain: row for row in definitions})
    headers, facts = setup(client)
    response = create(client, headers, facts)
    assert response.status_code == 409 and "ip_domain_not_available" in response.text
    rows = client.get(f"{BASE}/contracts", headers=headers).json()
    assert len(rows) == 10
    assert all(not row["intake_available"] for row in rows)
    client.cookies.clear()
    assert client.get(f"{BASE}/contracts").status_code == 401


def test_specialist_access_cannot_be_published_through_generic_acl(client, registered_intake):
    headers, facts = setup(client)
    record = create(client, headers, facts).json()
    access = client.get(f"/api/ip/dockets/{record['docket_id']}/access", headers=headers)
    assert access.status_code == 200, access.text
    payload = {
        "action": "set_restricted",
        "restricted": False,
        "expected_access_policy_version": access.json()["access_policy_version"],
        "reason": "Deliberate forbidden broadening regression",
    }
    response = client.post(
        f"/api/ip/dockets/{record['docket_id']}/access/preview", headers=headers, json=payload
    )
    assert response.status_code == 409 and "specialist_restriction_required" in response.text
    with get_session_factory()() as session:
        assert session.get(IpDocketRecord, record["docket_id"]).restricted


@pytest.mark.parametrize("domain", FACT_MODELS)
def test_exact_child_prd_and_no_trademark_fields(domain):
    root = Path(__file__).resolve().parents[3]
    assert (
        sha256((root / contract_path(domain)).read_bytes()).hexdigest() == CHILD_PRD_HASHES[domain]
    )
    assert contract_fields(domain)
    data = {
        "title": "Intake",
        "client_id": str(uuid4()),
        "jurisdiction_as_supplied": "As supplied",
        "details": {"domain": domain, **DETAILS[domain]},
    }
    assert SpecialistFacts.model_validate(data).details.domain == domain
    with pytest.raises(ValidationError):
        SpecialistFacts.model_validate(
            {**data, "details": {**data["details"], "trademark_classes": [9]}}
        )


def test_all_nested_schema_objects_forbid_extra_properties():
    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(SpecialistFacts.model_json_schema())
    visit(SpecialistObservation.model_json_schema())


def test_capability_request_preserves_existing_journey_gates():
    for definition in catalogue.DOMAIN_DEFINITIONS:
        if definition.domain in JOURNEYS:
            assert set(definition.journeys) <= set(JOURNEYS[definition.domain])
    assert {"UJ-30", "UJ-43", "UJ-60", "UJ-61"} <= set(JOURNEYS["licensing"])


def test_version_history_stale_writes_identity_and_immutable_database(client, registered_intake):
    headers, facts = setup(client)
    key = str(uuid4())
    response = create(client, headers, facts, key)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert create(client, headers, facts, key).json() == saved
    correction = {
        "expected_version": 1,
        "expected_lifecycle_version": 0,
        "reason": "Correct source transcription",
        "facts": {**saved["facts"], "title": "Corrected design title"},
    }
    path = f"{BASE}/records/{saved['id']}/corrections"
    result = client.post(path, headers=headers, json=correction)
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2
    assert client.post(path, headers=headers, json=correction).status_code == 409
    assert (
        client.get(f"{BASE}/records/{saved['id']}/versions/1", headers=headers).json()["facts"]
        == saved["facts"]
    )
    assert client.get(f"{BASE}/records/{saved['id']}", headers=headers).json() == result.json()
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpSpecialistRecord)) == 1
        assert session.scalar(select(func.count()).select_from(IpSpecialistVersion)) == 2
        event = session.scalar(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.target_id == saved["docket_id"],
                PrivateProjectionEvent.reason_code == "ip_specialist_facts_corrected",
            )
        )
        assert (
            event is not None and event.event_type == "source_changed" and event.status == "applied"
        )
        with pytest.raises(IntegrityError):
            session.execute(text("UPDATE ip_specialist_versions SET reason = 'overwrite'"))
        session.rollback()


def test_source_failure_supersession_replay_and_domain_mismatch(client, registered_intake):
    headers, facts = setup(client, "copyright")
    record = create(client, headers, facts).json()
    _, payload, _ = observation(client, headers, record)
    wrong = {**payload, "source": {**payload["source"], "content_sha256": "0" * 64}}
    assert post_observation(client, headers, record, wrong).status_code == 409
    assert (
        post_observation(
            client, headers, record, {**payload, "kind": "detention_alert"}
        ).status_code
        == 422
    )
    key = str(uuid4())
    first = post_observation(client, headers, record, payload, key)
    assert first.status_code == 201, first.text
    assert post_observation(client, headers, record, payload, key).json() == first.json()
    changed = {
        **payload,
        "supersedes_id": first.json()["id"],
        "account": "Corrected account from the same exact source.",
    }
    second = post_observation(client, headers, record, changed)
    assert second.status_code == 201, second.text
    assert post_observation(client, headers, record, changed).status_code == 409
    history = client.get(f"{BASE}/records/{record['id']}/observations", headers=headers).json()[
        "observations"
    ]
    assert history == [second.json(), first.json()]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpSpecialistObservation)) == 2


def test_terminal_history_download_and_revoke(client, registered_intake):
    headers, facts = setup(client, "trade_secret")
    key = str(uuid4())
    record = create(client, headers, facts, key).json()
    document, payload, content = observation(client, headers, record)
    saved = post_observation(client, headers, record, payload)
    assert saved.status_code == 201, saved.text
    close = client.post(
        f"/api/ip/dockets/{record['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Client withdrew the specialist instruction.",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "test:withdrawal",
            "linked_matter_handling": "reviewed",
        },
    )
    assert close.status_code == 200, close.text
    assert create(client, headers, facts, key).status_code == 404
    assert post_observation(client, headers, record, payload).status_code == 404
    assert (
        client.get(f"{BASE}/records/{record['id']}", headers=headers).json()["is_active"] is False
    )
    history = client.get(f"{BASE}/records/{record['id']}/observations", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["observations"] == [saved.json()]
    download_path = f"/api/ip/documents/{document['id']}/versions/1/download"
    download = client.get(download_path, headers=headers)
    assert download.status_code == 200 and download.content == content, download.text
    with get_session_factory()() as session:
        for grant in session.scalars(
            select(MatterAccessGrant).where(MatterAccessGrant.ip_docket_id == record["docket_id"])
        ):
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(f"{BASE}/records/{record['id']}", headers=headers).status_code == 404
    assert client.get(download_path, headers=headers).status_code == 404
    assert (
        client.get(
            f"{BASE}/records?domain=trade_secret&include_closed=true", headers=headers
        ).json()["records"]
        == []
    )


def test_cross_tenant_cannot_read_or_mutate(client, registered_intake):
    headers, facts = setup(client)
    saved = create(client, headers, facts).json()
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other specialist firm",
            "company_slug": "other-specialist",
            "company_type": "law_firm",
            "owner_full_name": "Other Specialist",
            "owner_email": "other-specialist@example.com",
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    other = response.json()
    other_headers = auth_headers(str(other["access_token"]))
    assert client.get(f"{BASE}/records/{saved['id']}", headers=other_headers).status_code == 404
    assert (
        client.get(f"{BASE}/records?domain=design", headers=other_headers).json()["records"] == []
    )
    assert create(client, other_headers, facts).status_code == 404


def test_same_day_reopen_retires_creation_and_source_replays(client, registered_intake):
    headers, facts = setup(client)
    creation_key = str(uuid4())
    record = create(client, headers, facts, creation_key).json()
    document, payload, content = observation(client, headers, record)
    observation_key = str(uuid4())
    first = post_observation(client, headers, record, payload, observation_key)
    assert first.status_code == 201, first.text
    path = f"/api/ip/dockets/{record['docket_id']}/lifecycle"
    effective_at = datetime.now(UTC).isoformat()
    close_payload = {
        "expected_lifecycle_version": 0,
        "to_status": "closed",
        "effective_at": effective_at,
        "reason": "Client closed the specialist instruction.",
        "outcome": "closed",
        "source": "lawyer_review",
        "evidence_ref": "test:closure",
        "linked_matter_handling": "reviewed",
    }
    closed = client.post(path, headers=headers, json=close_payload)
    assert closed.status_code == 200, closed.text
    reopened = client.post(
        path,
        headers=headers,
        json={
            **close_payload,
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "outcome": "reopened",
            "reason": "Explicit new client instruction to reopen.",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["event"]["payload_json"]["reopen_without_child_resurrection"]
    assert create(client, headers, facts, creation_key).status_code == 409
    assert post_observation(client, headers, record, payload, observation_key).status_code == 409
    assert client.post(path, headers=headers, json=close_payload).status_code == 409
    second_close = client.post(
        path, headers=headers, json={**close_payload, "expected_lifecycle_version": 2}
    )
    assert second_close.status_code == 200, second_close.text
    assert second_close.json()["event"]["id"] != closed.json()["event"]["id"]
    current = client.get(f"{BASE}/records/{record['id']}", headers=headers).json()
    assert not current["is_active"] and current["lifecycle_version"] == 3
    assert client.get(f"{BASE}/records?domain=design", headers=headers).json()["records"] == []
    history = client.get(f"{BASE}/records/{record['id']}/observations", headers=headers)
    assert history.status_code == 200 and history.json()["observations"] == [first.json()]
    download = client.get(
        f"/api/ip/documents/{document['id']}/versions/1/download", headers=headers
    )
    assert download.status_code == 200 and download.content == content
