from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Contract
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_contract(client: TestClient, token: str, code: str = "CTR-LW9-001") -> dict:
    response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Vendor services agreement",
            "contract_code": code,
            "counterparty_name": "Acme India Pvt Ltd",
            "contract_type": "Legacy vendor agreement",
            "contract_type_key": "master_services_agreement",
            "status": "under_review",
            "jurisdiction": "India",
            "effective_on": "2026-05-01",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_attachment(
    client: TestClient,
    token: str,
    contract_id: str,
    filename: str = "contract.txt",
    *,
    role: str | None = None,
    parent_attachment_id: str | None = None,
) -> dict:
    data: dict[str, str] = {}
    if role:
        data["attachment_role"] = role
    if parent_attachment_id:
        data["parent_attachment_id"] = parent_attachment_id
    response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        data=data,
        files={
            "file": (
                filename,
                b"Agreement commences on 15 May 2026 and refers to damages.",
                "text/plain",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _audit_actions(company_id: str) -> list[str]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )


def test_ft_lw_021_controlled_contract_type_persists_and_legacy_freeform_survives(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])

    contract = _create_contract(client, token)
    assert contract["contract_type"] == "Legacy vendor agreement"
    assert contract["contract_type_key"] == "master_services_agreement"

    metadata_response = client.patch(
        f"/api/contracts/{contract['id']}/metadata",
        headers=auth_headers(token),
        json={
            "contract_type": "Distribution side letter",
            "contract_type_key": "other",
            "contract_type_notes": "Distribution side letter",
        },
    )

    assert metadata_response.status_code == 200, metadata_response.text
    updated = metadata_response.json()
    assert updated["contract_type_key"] == "other"
    assert updated["contract_type"] == "Distribution side letter"
    assert updated["contract_type_notes"] == "Distribution side letter"
    assert "contract.metadata.updated" in _audit_actions(company_id)


def test_ft_lw_022_legal_references_are_source_grounded_and_reviewable(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    contract = _create_contract(client, token)
    attachment = _upload_attachment(client, token, contract["id"], "msa.txt")

    create_response = client.post(
        f"/api/contracts/{contract['id']}/legal-references",
        headers=auth_headers(token),
        json={
            "act_name": "Indian Contract Act, 1872",
            "section_label": "Section 73",
            "clause_label": "Damages",
            "source": "ai_suggested",
            "confidence": 0.87,
            "evidence_attachment_id": attachment["id"],
            "evidence_quote": "compensation for loss naturally arising in usual course",
        },
    )

    assert create_response.status_code == 200, create_response.text
    reference = create_response.json()
    assert reference["status"] == "suggested"
    assert reference["evidence_attachment_id"] == attachment["id"]
    assert reference["evidence_attachment_name"] == "msa.txt"

    accept_response = client.patch(
        f"/api/contracts/{contract['id']}/legal-references/{reference['id']}",
        headers=auth_headers(token),
        json={"status": "accepted"},
    )

    assert accept_response.status_code == 200, accept_response.text
    assert accept_response.json()["status"] == "accepted"
    actions = _audit_actions(company_id)
    assert "contract.legal_reference.created" in actions
    assert "contract.legal_reference.updated" in actions


def test_sec_lw_007_term_suggestions_do_not_overwrite_canonical_dates_until_accept(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    contract = _create_contract(client, token)
    attachment = _upload_attachment(client, token, contract["id"], "terms.txt")

    suggestion_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions",
        headers=auth_headers(token),
        json={
            "source_attachment_id": attachment["id"],
            "suggested_effective_on": "2026-05-15",
            "suggested_expires_on": "2027-05-14",
            "suggested_duration_months": 12,
            "evidence_json": {"quote": "This agreement commences on 15 May 2026."},
        },
    )

    assert suggestion_response.status_code == 200, suggestion_response.text
    suggestion = suggestion_response.json()
    assert suggestion["status"] == "suggested"
    unchanged = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert unchanged["effective_on"] == "2026-05-01"
    assert unchanged["expires_on"] is None

    accept_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion['id']}/accept",
        headers=auth_headers(token),
    )

    assert accept_response.status_code == 200, accept_response.text
    assert accept_response.json()["status"] == "accepted"
    accepted_contract = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert accepted_contract["effective_on"] == "2026-05-15"
    assert accepted_contract["expires_on"] == "2027-05-14"
    actions = _audit_actions(company_id)
    assert "contract.term_suggestion.created" in actions
    assert "contract.term_suggestion.accepted" in actions
    assert "contract.metadata.updated" in actions


def test_term_suggestion_reject_does_not_change_contract_dates(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    contract = _create_contract(client, token)

    suggestion_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions",
        headers=auth_headers(token),
        json={"suggested_renewal_on": "2026-12-31", "evidence_json": {"quote": "renewal"}},
    )
    assert suggestion_response.status_code == 200, suggestion_response.text

    suggestion_id = suggestion_response.json()["id"]
    reject_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion_id}/reject",
        headers=auth_headers(token),
    )

    assert reject_response.status_code == 200, reject_response.text
    assert reject_response.json()["status"] == "rejected"
    current = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert current["renewal_on"] is None


def test_term_suggestion_terminal_states_are_safe_and_idempotent(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    contract = _create_contract(client, token, "CTR-LW9-TERM-001")
    attachment = _upload_attachment(client, token, contract["id"], "term-source.txt")

    suggestion_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions",
        headers=auth_headers(token),
        json={
            "source_attachment_id": attachment["id"],
            "suggested_effective_on": "2026-06-01",
            "evidence_json": {"quote": "commences on 1 June 2026"},
        },
    )
    assert suggestion_response.status_code == 200, suggestion_response.text
    suggestion_id = suggestion_response.json()["id"]

    first_accept = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion_id}/accept",
        headers=auth_headers(token),
    )
    assert first_accept.status_code == 200, first_accept.text
    second_accept = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion_id}/accept",
        headers=auth_headers(token),
    )
    assert second_accept.status_code == 200, second_accept.text
    assert second_accept.json()["status"] == "accepted"

    reject_after_accept = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion_id}/reject",
        headers=auth_headers(token),
    )
    assert reject_after_accept.status_code == 409
    current = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert current["effective_on"] == "2026-06-01"

    rejected_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions",
        headers=auth_headers(token),
        json={
            "source_attachment_id": attachment["id"],
            "suggested_expires_on": "2026-12-31",
            "evidence_json": {"quote": "expires on 31 December 2026"},
        },
    )
    assert rejected_response.status_code == 200, rejected_response.text
    rejected_id = rejected_response.json()["id"]
    first_reject = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{rejected_id}/reject",
        headers=auth_headers(token),
    )
    assert first_reject.status_code == 200, first_reject.text
    second_reject = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{rejected_id}/reject",
        headers=auth_headers(token),
    )
    assert second_reject.status_code == 200, second_reject.text
    assert second_reject.json()["status"] == "rejected"

    accept_after_reject = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{rejected_id}/accept",
        headers=auth_headers(token),
    )
    assert accept_after_reject.status_code == 409
    current_after_rejected = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert current_after_rejected["expires_on"] is None


def test_ai_legal_references_require_source_grounding_before_acceptance(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    contract = _create_contract(client, token, "CTR-LW9-AI-REF")
    attachment = _upload_attachment(client, token, contract["id"], "ai-source.txt")

    ungrounded_response = client.post(
        f"/api/contracts/{contract['id']}/legal-references",
        headers=auth_headers(token),
        json={
            "act_name": "Indian Contract Act, 1872",
            "source": "ai_suggested",
        },
    )
    assert ungrounded_response.status_code == 200, ungrounded_response.text
    ungrounded = ungrounded_response.json()
    assert ungrounded["status"] == "suggested"

    ungrounded_accept = client.patch(
        f"/api/contracts/{contract['id']}/legal-references/{ungrounded['id']}",
        headers=auth_headers(token),
        json={"status": "accepted"},
    )
    assert ungrounded_accept.status_code == 422

    grounded_bypass = client.post(
        f"/api/contracts/{contract['id']}/legal-references",
        headers=auth_headers(token),
        json={
            "act_name": "Indian Contract Act, 1872",
            "source": "ai_suggested",
            "status": "accepted",
            "evidence_attachment_id": attachment["id"],
            "evidence_quote": "agreement commences on 15 May 2026",
        },
    )
    assert grounded_bypass.status_code == 200, grounded_bypass.text
    grounded = grounded_bypass.json()
    assert grounded["status"] == "suggested"

    grounded_accept = client.patch(
        f"/api/contracts/{contract['id']}/legal-references/{grounded['id']}",
        headers=auth_headers(token),
        json={"status": "accepted"},
    )
    assert grounded_accept.status_code == 200, grounded_accept.text
    assert grounded_accept.json()["status"] == "accepted"


def test_ungrounded_term_suggestion_cannot_be_canonicalized(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    contract = _create_contract(client, token, "CTR-LW9-UNGROUNDED")

    suggestion_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions",
        headers=auth_headers(token),
        json={"suggested_effective_on": "2026-06-01", "evidence_json": {}},
    )
    assert suggestion_response.status_code == 200, suggestion_response.text
    suggestion_id = suggestion_response.json()["id"]

    accept_response = client.post(
        f"/api/contracts/{contract['id']}/term-suggestions/{suggestion_id}/accept",
        headers=auth_headers(token),
    )
    assert accept_response.status_code == 422
    current = client.get(
        f"/api/contracts/{contract['id']}",
        headers=auth_headers(token),
    ).json()
    assert current["effective_on"] == "2026-05-01"


def test_ft_lw_024_ancillary_attachment_metadata_groups_and_links_documents(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    contract = _create_contract(client, token)
    primary = _upload_attachment(
        client,
        token,
        contract["id"],
        "signed-msa.txt",
        role="primary_contract",
    )
    amendment = _upload_attachment(client, token, contract["id"], "amendment.txt")

    metadata_response = client.patch(
        f"/api/contracts/{contract['id']}/attachments/{amendment['id']}/metadata",
        headers=auth_headers(token),
        json={
            "attachment_role": "amendment",
            "parent_attachment_id": primary["id"],
            "document_date": "2026-05-05",
            "notes": "Pricing amendment",
        },
    )

    assert metadata_response.status_code == 200, metadata_response.text
    metadata = metadata_response.json()
    assert metadata["attachment_role"] == "amendment"
    assert metadata["parent_attachment_id"] == primary["id"]
    assert metadata["document_date"] == "2026-05-05"
    workspace = client.get(
        f"/api/contracts/{contract['id']}/workspace",
        headers=auth_headers(token),
    ).json()
    attachments = {row["id"]: row for row in workspace["attachments"]}
    assert attachments[primary["id"]]["attachment_role"] == "primary_contract"
    assert attachments[amendment["id"]]["parent_attachment_id"] == primary["id"]
    assert "contract_attachment.metadata.updated" in _audit_actions(company_id)


def test_contract_attachment_parent_cycles_are_rejected(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    contract = _create_contract(client, token, "CTR-LW9-CYCLE")
    first = _upload_attachment(client, token, contract["id"], "first.txt")
    second = _upload_attachment(client, token, contract["id"], "second.txt")
    third = _upload_attachment(client, token, contract["id"], "third.txt")

    first_to_second = client.patch(
        f"/api/contracts/{contract['id']}/attachments/{first['id']}/metadata",
        headers=auth_headers(token),
        json={"parent_attachment_id": second["id"]},
    )
    assert first_to_second.status_code == 200, first_to_second.text

    direct_cycle = client.patch(
        f"/api/contracts/{contract['id']}/attachments/{second['id']}/metadata",
        headers=auth_headers(token),
        json={"parent_attachment_id": first["id"]},
    )
    assert direct_cycle.status_code == 422

    third_to_first = client.patch(
        f"/api/contracts/{contract['id']}/attachments/{third['id']}/metadata",
        headers=auth_headers(token),
        json={"parent_attachment_id": first["id"]},
    )
    assert third_to_first.status_code == 200, third_to_first.text

    indirect_cycle = client.patch(
        f"/api/contracts/{contract['id']}/attachments/{second['id']}/metadata",
        headers=auth_headers(token),
        json={"parent_attachment_id": third["id"]},
    )
    assert indirect_cycle.status_code == 422


def test_legacy_contract_type_strings_map_to_controlled_values(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    factory = get_session_factory()
    with factory() as session:
        known = Contract(
            company_id=company_id,
            title="Legacy NDA",
            contract_code="CTR-LW9-LEGACY-KNOWN",
            contract_type="NDA",
        )
        unknown = Contract(
            company_id=company_id,
            title="Legacy Bespoke",
            contract_code="CTR-LW9-LEGACY-UNKNOWN",
            contract_type="Bespoke revenue side letter",
        )
        session.add_all([known, unknown])
        session.commit()
        known_id = known.id
        unknown_id = unknown.id

    known_response = client.get(
        f"/api/contracts/{known_id}",
        headers=auth_headers(token),
    )
    assert known_response.status_code == 200, known_response.text
    assert known_response.json()["contract_type_key"] == "nda"
    assert known_response.json()["contract_type_notes"] is None

    unknown_response = client.get(
        f"/api/contracts/{unknown_id}",
        headers=auth_headers(token),
    )
    assert unknown_response.status_code == 200, unknown_response.text
    assert unknown_response.json()["contract_type_key"] == "other"
    assert unknown_response.json()["contract_type_notes"] == "Bespoke revenue side letter"


def test_cross_contract_or_tenant_attachments_cannot_be_used_as_metadata_evidence(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    first_contract = _create_contract(client, token, "CTR-LW9-100")
    second_contract = _create_contract(client, token, "CTR-LW9-101")
    second_attachment = _upload_attachment(client, token, second_contract["id"], "other.txt")

    bad_reference = client.post(
        f"/api/contracts/{first_contract['id']}/legal-references",
        headers=auth_headers(token),
        json={
            "act_name": "Indian Contract Act, 1872",
            "source": "manual",
            "evidence_attachment_id": second_attachment["id"],
        },
    )
    assert bad_reference.status_code == 404

    child_attachment = _upload_attachment(client, token, first_contract["id"], "child.txt")
    bad_parent = client.patch(
        f"/api/contracts/{first_contract['id']}/attachments/"
        f"{child_attachment['id']}/metadata",
        headers=auth_headers(token),
        json={"parent_attachment_id": second_attachment["id"]},
    )
    assert bad_parent.status_code == 404

    other_company = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Contract Tenant",
            "company_slug": "other-contract-tenant",
            "company_type": "corporate_legal",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-contract-tenant.in",
            "owner_password": "OtherOwner123!",
        },
    )
    other_token = str(other_company.json()["access_token"])
    cross_tenant = client.get(
        f"/api/contracts/{first_contract['id']}/legal-references",
        headers=auth_headers(other_token),
    )
    assert cross_tenant.status_code == 404
