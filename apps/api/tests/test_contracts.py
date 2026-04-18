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


def test_contract_attachment_upload_and_download_are_available_in_workspace(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Managed services agreement",
            "contract_code": "CTR-2026-200",
            "contract_type": "MSA",
            "status": "under_review",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "msa.txt",
                (
                    b"Termination. Either party may terminate this agreement by providing 30 days "
                    b"written notice.\n\nConfidentiality. Recipient shall notify the disclosing "
                    b"party within 24 hours of any breach."
                ),
                "text/plain",
            )
        },
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["original_filename"] == "msa.txt"
    assert attachment["processing_status"] == "pending"
    assert attachment["extracted_char_count"] == 0
    assert attachment["latest_job"]["action"] == "initial_index"
    assert attachment["latest_job"]["status"] == "queued"

    workspace_response = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers=auth_headers(token),
    )
    assert workspace_response.status_code == 200
    workspace = workspace_response.json()
    assert len(workspace["attachments"]) == 1
    assert workspace["attachments"][0]["id"] == attachment["id"]
    assert workspace["attachments"][0]["processing_status"] == "indexed"
    assert workspace["attachments"][0]["latest_job"]["status"] == "completed"
    assert any(
        event["event_type"] == "contract_attachment_added" for event in workspace["activity"]
    )
    assert any(
        event["event_type"] == "contract_attachment_processed"
        for event in workspace["activity"]
    )

    download_response = client.get(
        f"/api/contracts/{contract_id}/attachments/{attachment['id']}/download",
        headers=auth_headers(token),
    )
    assert download_response.status_code == 200
    assert b"30 days written notice" in download_response.content


def test_cross_tenant_user_cannot_download_another_company_contract_attachment(
    client: TestClient,
) -> None:
    first_company = bootstrap_company(client)
    first_token = str(first_company["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(first_token),
        json={
            "title": "Restricted vendor contract",
            "contract_code": "CTR-2026-201",
            "contract_type": "Vendor",
            "status": "draft",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(first_token),
        files={"file": ("confidential.txt", b"Private contract schedule", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    second_company_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Tenant Legal",
            "company_slug": "second-tenant-contract-attachments",
            "company_type": "corporate_legal",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondattachments.in",
            "owner_password": "SecondOwner123!",
        },
    )
    second_token = str(second_company_response.json()["access_token"])

    forbidden_download = client.get(
        f"/api/contracts/{contract_id}/attachments/{attachment_id}/download",
        headers=auth_headers(second_token),
    )

    assert forbidden_download.status_code == 404


def test_contract_pdf_attachment_is_marked_as_needing_ocr(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Signed vendor amendment",
            "contract_code": "CTR-2026-202A",
            "contract_type": "Vendor",
            "status": "executed",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("signed-amendment.pdf", b"%PDF-1.4 fake bytes", "application/pdf")},
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["extracted_char_count"] == 0
    assert attachment["latest_job"]["status"] == "queued"

    workspace_response = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers=auth_headers(token),
    )
    workspace_attachment = workspace_response.json()["attachments"][0]
    assert workspace_attachment["processing_status"] == "needs_ocr"
    assert "OCR" in workspace_attachment["extraction_error"]
    assert workspace_attachment["latest_job"]["status"] == "failed"


def test_contract_image_attachment_can_be_indexed_when_ocr_is_available(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._resolve_tesseract_command",
        lambda: "tesseract",
    )
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_image_text",
        lambda path: "Signed amendment confirms pricing schedule and termination notice.",
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Signed pricing exhibit",
            "contract_code": "CTR-2026-IMG-001",
            "contract_type": "Pricing Exhibit",
            "status": "executed",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "signed.png",
                b"\x89PNG\r\n\x1a\nfake-image-bytes",
                "image/png",
            )
        },
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["latest_job"]["status"] == "queued"

    review_response = client.post(
        f"/api/ai/contracts/{contract_id}/reviews/generate",
        headers=auth_headers(token),
        json={"review_type": "intake_review"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["source_attachments"] == ["signed.png"]


def test_contract_scanned_pdf_attachment_can_be_indexed_when_ocr_returns_text(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_pdf_text",
        lambda path: "",
    )
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: (
            "Executed amendment updates the pricing schedule and requires 45 days notice "
            "for termination."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Scanned amendment pack",
            "contract_code": "CTR-2026-SCAN-001",
            "contract_type": "Amendment",
            "status": "executed",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("scanned-amendment.pdf", b"%PDF-1.4 scanned bytes", "application/pdf")},
    )

    assert upload_response.status_code == 200
    attachment = upload_response.json()
    assert attachment["processing_status"] == "pending"
    assert attachment["latest_job"]["status"] == "queued"

    review_response = client.post(
        f"/api/ai/contracts/{contract_id}/reviews/generate",
        headers=auth_headers(token),
        json={"review_type": "intake_review"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["source_attachments"] == ["scanned-amendment.pdf"]


def test_owner_can_reindex_contract_attachment(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Contract reindex control",
            "contract_code": "CTR-2026-REINDEX-001",
            "contract_type": "MSA",
            "status": "under_review",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("reindex.txt", b"Termination clause baseline.", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    monkeypatch.setattr(
        "caseops_api.services.document_processing._load_text",
        lambda path, suffix: "Termination clause baseline with refreshed fallback language.",
    )

    reindex_response = client.post(
        f"/api/contracts/{contract_id}/attachments/{attachment_id}/reindex",
        headers=auth_headers(token),
    )

    assert reindex_response.status_code == 200
    attachment = reindex_response.json()
    assert attachment["latest_job"]["action"] == "reindex"
    assert attachment["latest_job"]["status"] == "queued"

    workspace_response = client.get(
        f"/api/contracts/{contract_id}/workspace",
        headers=auth_headers(token),
    )
    workspace_attachment = workspace_response.json()["attachments"][0]
    assert workspace_attachment["processing_status"] == "indexed"
    assert workspace_attachment["latest_job"]["status"] == "completed"


def test_ai_contract_review_uses_uploaded_contract_text_and_playbook_hits(
    client: TestClient,
) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Cloud services agreement",
            "contract_code": "CTR-2026-202",
            "counterparty_name": "Nimbus Cloud Services",
            "contract_type": "MSA",
            "status": "under_review",
        },
    )
    contract_id = contract_response.json()["id"]

    client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "cloud-msa.txt",
                (
                    b"Termination. Either party may terminate this agreement by providing 30 days "
                    b"written notice.\n\nConfidentiality. Recipient shall protect confidential "
                    b"information and must notify the disclosing party within 24 hours "
                    b"of any breach."
                ),
                "text/plain",
            )
        },
    )

    client.post(
        f"/api/contracts/{contract_id}/playbook-rules",
        headers=auth_headers(token),
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
        headers=auth_headers(token),
        json={
            "rule_name": "Indemnity fallback required",
            "clause_type": "indemnity",
            "expected_position": "Indemnity must be capped to fees paid in the prior 12 months.",
            "severity": "high",
            "fallback_text": "Indemnity is capped to fees paid in the prior 12 months.",
        },
    )

    review_response = client.post(
        f"/api/ai/contracts/{contract_id}/reviews/generate",
        headers=auth_headers(token),
        json={"review_type": "intake_review", "focus": "Security and breach posture"},
    )

    assert review_response.status_code == 200
    payload = review_response.json()
    assert payload["provider"] == "caseops-contract-review-retrieval-v1"
    assert payload["headline"].startswith("Contract review")
    assert any("Termination" in item for item in payload["key_clauses"])
    assert any("24 hours" in item for item in payload["extracted_obligations"])
    assert any("Indemnity fallback required" in risk for risk in payload["risks"])
    assert any("Security and breach posture" in item for item in payload["recommended_actions"])
    assert payload["source_attachments"] == ["cloud-msa.txt"]
