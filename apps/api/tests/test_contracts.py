from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_authenticated_user_can_create_and_list_contracts(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "MSA with Northstar Retail",
            "contract_code": "CTR-2026-001",
            "counterparty_name": "Northstar Retail Pvt Ltd",
            "contract_type": "Master Services Agreement",
            "status": "under_review",
            "jurisdiction": "Delhi",
            "auto_renewal": True,
            "currency": "INR",
            "total_value_minor": 9500000,
            "summary": "Annual services agreement with data security and renewal controls.",
        },
    )

    assert create_response.status_code == 200
    contract = create_response.json()
    assert contract["contract_code"] == "CTR-2026-001"
    assert contract["status"] == "under_review"

    list_response = client.get("/api/contracts/", headers=auth_headers(token))
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["contracts"]) == 1
    assert payload["contracts"][0]["title"] == "MSA with Northstar Retail"


def test_contract_workspace_includes_playbook_hits_obligations_and_activity(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    user_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Aditi Counsel",
            "email": "aditi@asterlegal.in",
            "password": "CounselPass123!",
            "role": "member",
        },
    )
    owner_membership_id = user_response.json()["membership_id"]

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(owner_token),
        json={
            "title": "Vendor relationship dispute reserve",
            "matter_code": "COMM-CTR-2026-010",
            "practice_area": "Commercial",
            "forum_level": "advisory",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(owner_token),
        json={
            "title": "Cloud hosting MSA",
            "contract_code": "CTR-2026-010",
            "linked_matter_id": matter_id,
            "owner_membership_id": owner_membership_id,
            "counterparty_name": "Nimbus Cloud Services",
            "contract_type": "MSA",
            "status": "under_review",
            "jurisdiction": "Bengaluru",
            "summary": "Commercial hosting arrangement under legal review.",
        },
    )
    assert contract_response.status_code == 200
    contract_id = contract_response.json()["id"]

    clause_response = client.post(
        f"/api/contracts/{contract_id}/clauses",
        headers=auth_headers(owner_token),
        json={
            "title": "Termination for convenience",
            "clause_type": "termination",
            "clause_text": (
                "Either party may terminate this agreement by providing 30 days "
                "written notice."
            ),
            "risk_level": "medium",
        },
    )
    assert clause_response.status_code == 200

    second_clause_response = client.post(
        f"/api/contracts/{contract_id}/clauses",
        headers=auth_headers(owner_token),
        json={
            "title": "Confidentiality controls",
            "clause_type": "confidentiality",
            "clause_text": (
                "Recipient shall protect confidential information using "
                "reasonable safeguards."
            ),
            "risk_level": "high",
        },
    )
    assert second_clause_response.status_code == 200

    obligation_response = client.post(
        f"/api/contracts/{contract_id}/obligations",
        headers=auth_headers(owner_token),
        json={
            "owner_membership_id": owner_membership_id,
            "title": "Deliver security schedule redlines",
            "description": "Send fallback confidentiality wording and SLA annexure edits.",
            "due_on": "2026-04-30",
            "status": "pending",
            "priority": "high",
        },
    )
    assert obligation_response.status_code == 200

    client.post(
        f"/api/contracts/{contract_id}/playbook-rules",
        headers=auth_headers(owner_token),
        json={
            "rule_name": "Termination requires 30-day notice",
            "clause_type": "termination",
            "expected_position": "Termination should require at least 30 days written notice.",
            "severity": "medium",
            "keyword_pattern": "30 days",
        },
    )
    client.post(
        f"/api/contracts/{contract_id}/playbook-rules",
        headers=auth_headers(owner_token),
        json={
            "rule_name": "Confidentiality needs breach notice",
            "clause_type": "confidentiality",
            "expected_position": (
                "Confidentiality clause should include 24 hours breach "
                "notification."
            ),
            "severity": "high",
            "keyword_pattern": "24 hours",
            "fallback_text": (
                "Recipient must notify the disclosing party within 24 hours of "
                "any breach."
            ),
        },
    )
    client.post(
        f"/api/contracts/{contract_id}/playbook-rules",
        headers=auth_headers(owner_token),
        json={
            "rule_name": "Indemnity cap fallback",
            "clause_type": "indemnity",
            "expected_position": (
                "Indemnity must be capped to fees paid in the prior 12 months."
            ),
            "severity": "high",
            "fallback_text": (
                "Liability under indemnity is capped to fees paid in the prior "
                "12 months."
            ),
        },
    )

    workspace_response = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers=auth_headers(owner_token),
    )

    assert workspace_response.status_code == 200
    payload = workspace_response.json()
    assert payload["contract"]["linked_matter_id"] == matter_id
    assert payload["linked_matter"]["id"] == matter_id
    assert payload["owner"]["membership_id"] == owner_membership_id
    assert len(payload["clauses"]) == 2
    assert len(payload["obligations"]) == 1
    assert payload["obligations"][0]["owner_name"] == "Aditi Counsel"
    assert len(payload["playbook_rules"]) == 3

    hit_statuses = {hit["rule_name"]: hit["status"] for hit in payload["playbook_hits"]}
    assert hit_statuses["Termination requires 30-day notice"] == "matched"
    assert hit_statuses["Confidentiality needs breach notice"] == "flagged"
    assert hit_statuses["Indemnity cap fallback"] == "missing"
    assert len(payload["activity"]) >= 7


def test_cross_tenant_user_cannot_access_another_company_contract(client: TestClient) -> None:
    first_company = bootstrap_company(client)
    first_token = str(first_company["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(first_token),
        json={
            "title": "Restricted procurement contract",
            "contract_code": "CTR-2026-404",
            "contract_type": "Procurement",
            "status": "draft",
        },
    )
    contract_id = contract_response.json()["id"]

    second_company_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Tenant Legal",
            "company_slug": "second-tenant-contracts",
            "company_type": "corporate_legal",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondcontracts.in",
            "owner_password": "SecondOwner123!",
        },
    )
    second_token = str(second_company_response.json()["access_token"])

    forbidden_workspace = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers=auth_headers(second_token),
    )

    assert forbidden_workspace.status_code == 404
