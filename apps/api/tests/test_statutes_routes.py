"""Slice S2 (MOD-TS-017) — statutes read API tests.

Maps to FT-S2-1 .. FT-S2-7 in
``docs/PRD_STATUTE_MODEL_2026-04-25.md`` §6.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityIngestionRun,
    Contract,
    ContractLegalReference,
    DocumentProcessingJob,
    LegalUpdateAlert,
    MatterStatuteReference,
    ModelRun,
    StatuteSection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.seed_statutes import _seed
from tests.test_auth_company import auth_headers, bootstrap_company

ADP18_AUTHORITY_RECORD_ID = "adp18-supreme-court-notification"


def _bootstrap_with_seed(client: TestClient) -> str:
    """Bootstrap a company, seed the statutes catalog, return token."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        _seed(s)
    return token


def _bootstrap_second_company(client: TestClient, slug: str = "adp18-other") -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": "OtherPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_legal_update_authority() -> str:
    with get_session_factory()() as session:
        existing = session.scalar(
            select(AuthorityDocument).where(
                AuthorityDocument.canonical_key == ADP18_AUTHORITY_RECORD_ID
            )
        )
        if existing is not None:
            return existing.id
        document = AuthorityDocument(
            source="supreme_court_latest_orders",
            adapter_name="test-adp18",
            court_name="Supreme Court of India",
            forum_level="supreme_court",
            document_type="notice",
            title="Supreme Court registry notification on Section 138 procedure",
            case_reference="Notification No. ADP18/2026",
            bench_name=None,
            neutral_citation=None,
            decision_date=date(2026, 5, 20),
            canonical_key=ADP18_AUTHORITY_RECORD_ID,
            source_reference="https://www.sci.gov.in/adp18-notification",
            summary=(
                "Registry notification addressing Section 138 filing procedure "
                "for cheque dishonour matters."
            ),
            document_text="ADP18_FULL_TEXT_SENTINEL should never be returned",
            extracted_char_count=128,
            sections_cited_json=json.dumps(["Section 138"]),
        )
        session.add(document)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=document.id,
                chunk_index=0,
                content=(
                    "Section 138 registry notification metadata for "
                    "cheque dishonour filing review."
                ),
                token_count=12,
            )
        )
        session.commit()
        return document.id


def test_ft_s2_1_list_statutes_returns_seeded_acts(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get("/api/statutes/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    short_names = {a["short_name"] for a in body["statutes"]}
    assert {
        "BNSS", "BNS", "BSA", "CrPC", "IPC", "Constitution", "NI Act",
    } <= short_names
    assert body["total_section_count"] > 0
    # Each item has its denormalised section_count.
    bnss = next(a for a in body["statutes"] if a["short_name"] == "BNSS")
    assert bnss["section_count"] >= 17  # we seeded 17 BNSS sections


def test_ft_s2_2_list_statutes_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/statutes/")
    assert resp.status_code == 401
    assert resp.json()["type"] == "missing_bearer_token"


def test_ft_s2_3_get_statute_returns_metadata(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get("/api/statutes/bnss-2023", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["short_name"] == "BNSS"
    assert body["enacted_year"] == 2023
    assert "indiacode" in body["source_url"]


def test_ft_s2_4_get_statute_404_unknown_id(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/does-not-exist", headers=auth_headers(token),
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_ft_s2_5_list_sections_returns_ordered_rows(client: TestClient) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/crpc-1973/sections", headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["statute"]["short_name"] == "CrPC"
    nums = [s["section_number"] for s in body["sections"]]
    assert "Section 482" in nums
    assert "Section 41A" in nums
    assert "Section 438" in nums  # Sushila Aggarwal anticipatory bail
    # Ordinals are monotonic (seed loader sets them by JSON position).
    ordinals = [s["ordinal"] for s in body["sections"]]
    assert ordinals == sorted(ordinals)


def test_ft_s2_6_get_section_detail_returns_section_url_fallback(
    client: TestClient,
) -> None:
    """Section URL falls back to parent act's source_url when not
    explicitly set in the seed (verified from S1; this is a route-
    level smoke too)."""
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/ipc-1860/sections/Section 302",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["section"]["section_number"] == "Section 302"
    assert body["section"]["section_label"] == "Punishment for murder"
    assert body["section"]["section_url"]
    assert "indiacode" in body["section"]["section_url"]
    # No parent or children for this section in v1 seed.
    assert body["parent_section"] is None
    assert body["child_sections"] == []


def test_ft_s2_7_get_section_404_unknown_section_number(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    resp = client.get(
        "/api/statutes/ipc-1860/sections/Section 99999",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"].lower()
    assert "section 99999" in detail
    assert "ipc" in detail


def test_adp18_legal_update_watchlist_run_is_in_app_idempotent_and_bounded(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    authority_id = _seed_legal_update_authority()

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Cheque dishonour updates",
            "statute_id": "ni-act-1881",
            "jurisdiction": "india",
            "statute_terms": ["Section 138"],
            "update_types": ["amendment", "notification"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist = create.json()
    assert watchlist["source_key"] is None
    assert watchlist["update_types"] == ["amendment", "notification"]

    preview = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": True, "limit": 10},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["delivery_status"] == "in_app_only"
    assert preview_body["matched_count"] >= 1
    response_blob = json.dumps(preview_body)
    assert authority_id in response_blob
    assert "ADP18_FULL_TEXT_SENTINEL" not in response_blob
    assert "document_text" not in response_blob
    assert "source_payload" not in response_blob
    assert "storage_key" not in response_blob
    assert all(
        len(item.get("snippet") or "") <= 280 for item in preview_body["matches"]
    )
    assert all(
        item["source_key"] and item["source_category"] and item["provenance_status"]
        for item in preview_body["matches"]
    )

    run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert run.status_code == 200, run.text
    assert run.json()["created_count"] >= 1

    rerun = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": False, "limit": 10},
    )
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["created_count"] == 0

    listed = client.get(
        "/api/statutes/legal-updates",
        headers=auth_headers(token),
    )
    assert listed.status_code == 200, listed.text
    updates = listed.json()["updates"]
    assert updates
    assert "ADP18_FULL_TEXT_SENTINEL" not in json.dumps(updates)

    read = client.patch(
        f"/api/statutes/legal-updates/{updates[0]['id']}",
        headers=auth_headers(token),
        json={"action": "read"},
    )
    assert read.status_code == 200, read.text
    assert read.json()["is_read"] is True

    digest = client.get(
        "/api/statutes/legal-updates/digest-preview",
        headers=auth_headers(token),
    )
    assert digest.status_code == 200, digest.text
    assert digest.json()["delivery_status"] == "in_app_only"
    assert "pending WTD-5.3" in digest.json()["delivery_note"]

    with get_session_factory()() as session:
        assert session.scalar(select(AuthorityIngestionRun)) is None
        assert session.scalar(select(DocumentProcessingJob)) is None
        assert session.scalar(select(ModelRun)) is None
        assert (
            session.scalar(
                select(func.count()).select_from(LegalUpdateAlert).where(
                    LegalUpdateAlert.watchlist_id == watchlist["id"],
                    LegalUpdateAlert.company_id == watchlist["company_id"],
                )
            )
            == run.json()["created_count"]
        )
        audit_events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == watchlist["company_id"],
                    AuditEvent.action.in_(
                        [
                            "legal_update.watchlist_created",
                            "legal_update.watchlist_run",
                            "legal_update.alert_read",
                        ]
                    ),
                )
            )
        )
        assert len(audit_events) >= 3
        audit_blob = "\n".join(event.metadata_json or "" for event in audit_events)
        for forbidden in (
            "Section 138",
            "cheque dishonour",
            "ADP18_FULL_TEXT_SENTINEL",
            "snippet",
            "document_text",
            "source_payload",
            "storage_key",
        ):
            assert forbidden not in audit_blob


def test_adp18_watchlists_are_tenant_scoped_and_archived_rules_do_not_generate(
    client: TestClient,
) -> None:
    token_a = _bootstrap_with_seed(client)
    token_b = str(_bootstrap_second_company(client, "adp18-other-b")["access_token"])

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token_a),
        json={
            "name": "Tenant A statutory updates",
            "statute_id": "crpc-1973",
            "statute_terms": ["Section 482"],
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    watchlist_id = create.json()["id"]

    tenant_b_list = client.get(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token_b),
    )
    assert tenant_b_list.status_code == 200, tenant_b_list.text
    assert tenant_b_list.json()["watchlists"] == []

    tenant_b_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token_b),
        json={"preview_only": False},
    )
    assert tenant_b_run.status_code == 404

    archive = client.patch(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}",
        headers=auth_headers(token_a),
        json={"is_archived": True},
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["is_archived"] is True

    archived_run = client.post(
        f"/api/statutes/legal-updates/watchlists/{watchlist_id}/run",
        headers=auth_headers(token_a),
        json={"preview_only": False},
    )
    assert archived_run.status_code == 200, archived_run.text
    assert archived_run.json()["matched_count"] == 0
    assert archived_run.json()["created_count"] == 0


def test_adp18_watchlist_rejects_unbounded_and_unknown_source_filters(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    unbounded = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={"name": "Unbounded"},
    )
    assert unbounded.status_code == 400
    assert "bounded filter" in unbounded.json()["detail"]

    unknown_source = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Unknown source",
            "source_key": "not-a-source",
            "update_types": ["notification"],
        },
    )
    assert unknown_source.status_code == 400
    assert "source registry" in unknown_source.json()["detail"]


def test_adp18_matter_and_contract_relevance_explanations_are_bounded(
    client: TestClient,
) -> None:
    token = _bootstrap_with_seed(client)
    matter_resp = client.post(
        "/api/matters",
        headers=auth_headers(token),
        json={
            "matter_code": "ADP18-REL",
            "title": "Cheque dishonour petition",
            "practice_area": "Criminal",
            "forum_level": "high_court",
            "court_name": "High Court of Delhi",
            "forum_state": "Delhi",
            "status": "intake",
        },
    )
    assert matter_resp.status_code == 200, matter_resp.text
    matter_id = matter_resp.json()["id"]

    with get_session_factory()() as session:
        section = session.scalar(
            select(StatuteSection).where(
                StatuteSection.statute_id == "ni-act-1881",
                StatuteSection.section_number == "Section 138",
            )
        )
        assert section is not None
        matter_ref = MatterStatuteReference(
            matter_id=matter_id,
            section_id=section.id,
            relevance="cited",
        )
        company_id = matter_resp.json()["company_id"]
        contract = Contract(
            company_id=company_id,
            linked_matter_id=matter_id,
            title="Cheque supply agreement",
            contract_code="ADP18-CONTRACT",
            contract_type="commercial",
            jurisdiction="Delhi",
        )
        session.add_all([matter_ref, contract])
        session.flush()
        session.add(
            ContractLegalReference(
                company_id=company_id,
                contract_id=contract.id,
                act_name="Negotiable Instruments Act",
                section_label="Section 138",
                statute_id="ni-act-1881",
            )
        )
        session.commit()
        contract_id = contract.id

    create = client.post(
        "/api/statutes/legal-updates/watchlists",
        headers=auth_headers(token),
        json={
            "name": "Matter linked NI Act updates",
            "statute_id": "ni-act-1881",
            "statute_terms": ["Section 138"],
            "matter_id": matter_id,
            "contract_id": contract_id,
            "update_types": ["amendment"],
        },
    )
    assert create.status_code == 201, create.text
    run = client.post(
        f"/api/statutes/legal-updates/watchlists/{create.json()['id']}/run",
        headers=auth_headers(token),
        json={"preview_only": True, "limit": 5},
    )
    assert run.status_code == 200, run.text
    matches = run.json()["matches"]
    assert matches
    explanation_blob = " ".join(item["relevance_explanation"] for item in matches)
    assert "matter statute references matched watched section" in explanation_blob
    assert "contract legal references matched watched statute/Act" in explanation_blob
    assert "ADP18" not in explanation_blob
