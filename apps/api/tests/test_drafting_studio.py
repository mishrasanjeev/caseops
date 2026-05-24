from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentType,
    Company,
    DocumentProcessingStatus,
    Draft,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterForumLevel,
    Team,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Drafting studio test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
            "description": "Seeded for drafting studio tests.",
            "court_name": "Delhi High Court",
            "judge_name": "Hon'ble Mr. Justice Bench",
            "client_name": "Aster Industries",
            "opposing_party": "State of Karnataka",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _seed_authority(
    neutral_citation: str = "2024 SCC OnLine SC 111",
    document_type: AuthorityDocumentType = AuthorityDocumentType.JUDGMENT,
) -> str:
    """Insert an AuthorityDocument directly so the citation verifier has
    something to match against."""
    factory = get_session_factory()
    session = factory()
    try:
        doc = AuthorityDocument(
            id=str(uuid.uuid4()),
            source="seed-tests",
            adapter_name="seed",
            court_name="Supreme Court of India",
            forum_level=MatterForumLevel.SUPREME_COURT,
            document_type=document_type,
            title="Seed authority for drafting tests",
            case_reference=None,
            bench_name="Bench",
            neutral_citation=neutral_citation,
            decision_date=date(2024, 3, 15),
            canonical_key=f"seed::{neutral_citation}",
            source_reference=None,
            summary=(
                "The Court held that the parties must comply with the "
                "procedural directions framed in the earlier order, "
                "subject to the reliefs prayed for in the present matter."
            ),
            document_text=None,
            ingested_at=datetime.now(UTC),
        )
        session.add(doc)
        session.commit()
        return str(doc.id)
    finally:
        session.close()


def _seed_attachment(
    matter_id: str,
    *,
    extracted_text: str,
    original_filename: str = "drafting-source.txt",
) -> str:
    factory = get_session_factory()
    attachment_id = str(uuid.uuid4())
    session = factory()
    try:
        attachment = MatterAttachment(
            id=attachment_id,
            matter_id=matter_id,
            original_filename=original_filename,
            storage_key=f"test/drafting/{uuid.uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=len(extracted_text),
            sha256_hex=(uuid.uuid4().hex + uuid.uuid4().hex)[:64],
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=len(extracted_text),
            extracted_text=extracted_text,
            document_type="complaint_petition",
            lifecycle_stage="pleadings",
        )
        session.add(attachment)
        session.flush()
        session.add(
            MatterAttachmentChunk(
                attachment_id=attachment_id,
                chunk_index=0,
                content=extracted_text,
                token_count=len(extracted_text.split()),
            )
        )
        session.commit()
        return attachment_id
    finally:
        session.close()


def _bootstrap_company_with_slug(client: TestClient, slug: str) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Legal LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "ADP Fifteen Owner",
            "owner_email": f"owner@{slug}.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    company_slug: str,
    email: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Drafting Associate",
            "email": email,
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "MemberPass123!",
            "company_slug": company_slug,
        },
    )
    assert login.status_code == 200, login.text
    return str(response.json()["membership_id"]), str(login.json()["access_token"])


def _create_draft(client: TestClient, token: str, matter_id: str) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Interim reply brief", "draft_type": "brief"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _generate(client: TestClient, token: str, matter_id: str, draft_id: str) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_draft_starts_empty_and_review_required(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-001")

    draft = _create_draft(client, token, matter_id)
    assert draft["status"] == "draft"
    assert draft["review_required"] is True
    assert draft["versions"] == []
    assert draft["current_version_id"] is None


def test_generate_creates_version_and_resets_status(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-002")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 222")

    draft = _create_draft(client, token, matter_id)
    regenerated = _generate(client, token, matter_id, draft["id"])

    assert regenerated["status"] == "draft"
    assert regenerated["review_required"] is True
    assert len(regenerated["versions"]) == 1
    version = regenerated["versions"][0]
    assert version["revision"] == 1
    assert version["body"].startswith("Brief in")
    # Mock emits the seeded citation since retrieval returns one hit.
    assert version["verified_citation_count"] >= 1
    assert regenerated["current_version_id"] == version["id"]


def test_state_machine_submit_request_changes_submit_approve_finalize(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-003")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 333")

    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    submitted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={"notes": "Ready for review."},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"

    reverted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/request-changes",
        headers=auth_headers(token),
        json={"notes": "Tighten prayer clause."},
    )
    assert reverted.status_code == 200
    assert reverted.json()["status"] == "changes_requested"

    resubmit = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "in_review"

    approved = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={"notes": "Approved."},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert body["review_required"] is False

    finalized = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/finalize",
        headers=auth_headers(token),
        json={},
    )
    assert finalized.status_code == 200
    assert finalized.json()["status"] == "finalized"

    # Review audit trail records every transition.
    actions = [r["action"] for r in finalized.json()["reviews"]]
    assert actions == ["submit", "request_changes", "submit", "approve", "finalize"]


def test_approve_blocked_when_no_verified_citations(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-004")
    # No authorities seeded — retrieval returns nothing, mock produces a
    # draft with no citations, so approve must fail closed.

    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    submitted = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "in_review"

    approve = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approve.status_code == 422
    assert "verified citations" in approve.json()["detail"]

    # Seeded citations after the fact — regenerate to pick them up, then approve.
    _seed_authority(neutral_citation="2024 SCC OnLine SC 444")
    _generate(client, token, matter_id, draft["id"])
    # Regenerating resets status back to 'draft' — we must submit again.
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    approve2 = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approve2.status_code == 200
    assert approve2.json()["status"] == "approved"


def test_finalized_draft_rejects_further_transitions(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-005")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 555")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/finalize",
        headers=auth_headers(token),
        json={},
    )

    # Submit / approve / regenerate / finalize all refused now.
    for path in ("submit", "approve", "finalize"):
        resp = client.post(
            f"/api/matters/{matter_id}/drafts/{draft['id']}/{path}",
            headers=auth_headers(token),
            json={},
        )
        assert resp.status_code == 409, resp.text

    regen = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert regen.status_code == 409


def test_drafts_list_is_tenant_scoped(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _create_matter(client, token_a, "DS-TEN-A")
    draft_a = _create_draft(client, token_a, matter_a)

    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Firm",
            "company_slug": "second-drafts-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@seconddrafts.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    token_b = str(resp.json()["access_token"])

    cross = client.get(
        f"/api/matters/{matter_a}/drafts/{draft_a['id']}",
        headers=auth_headers(token_b),
    )
    assert cross.status_code == 404


def test_docx_export_returns_a_word_document(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DOCX")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 777")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.docx",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".docx" in disposition
    # A valid DOCX is a ZIP archive — it starts with "PK\x03\x04".
    assert resp.content[:4] == b"PK\x03\x04"
    assert len(resp.content) > 2000  # sanity — a real .docx has meaningful bulk


def test_docx_export_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DOCX-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/export.docx",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------
# PG-005 Sprint 3 (2026-05-01) — court-format-aware PDF export.
# ---------------------------------------------------------------


def test_pdf_export_returns_a_pdf_document(client: TestClient) -> None:
    """Smoke: PDF endpoint produces a real PDF with the right
    Content-Type + Content-Disposition + court-profile header."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 1001")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.pdf",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".pdf" in disposition
    # A valid PDF starts with the magic bytes "%PDF-".
    assert resp.content[:5] == b"%PDF-"
    assert len(resp.content) > 1000  # sanity — must contain meaningful body
    # The matter's court_name is "Delhi High Court" → auto-resolves to
    # the delhi_hc profile and the route surfaces it in a header.
    assert resp.headers.get("x-caseops-court-profile") == "delhi_hc"
    # Filename embeds the resolved profile so a downloads folder with
    # multiple PDFs from the same draft is human-readable.
    assert "delhi_hc" in disposition


def test_pdf_export_explicit_court_profile_overrides_court_name(
    client: TestClient,
) -> None:
    """Caller can pass ?court_profile=supreme_court to override the
    auto-resolution. Useful when filing a transfer petition."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF-SC")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 1002")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.pdf"
        "?court_profile=supreme_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-caseops-court-profile") == "supreme_court"
    assert resp.headers.get("x-caseops-court-profile-category") == "supreme_court"
    assert "supreme_court" in resp.headers["content-disposition"]


def test_pdf_export_reports_required_field_gaps_without_blocking(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF-REQ")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 1004")
    draft_resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Writ petition with missing order details",
            "draft_type": "brief",
            "template_type": "writ_petition",
            "facts": {
                "petitioner_name": "Aster Industries",
                "respondent_name": "State of Karnataka",
            },
        },
    )
    assert draft_resp.status_code == 200, draft_resp.text
    draft = draft_resp.json()
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.pdf",
        headers=auth_headers(token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-caseops-court-profile") == "delhi_hc"
    assert resp.headers.get("x-caseops-court-profile-category") == "high_court"
    assert resp.headers.get("x-caseops-missing-required-fields") == "1"


def test_pdf_export_unknown_court_profile_returns_422(client: TestClient) -> None:
    """Unknown profile key → 422 with an actionable detail string."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF-422")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 1003")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.pdf"
        "?court_profile=mars_high_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "mars_high_court" in resp.json()["detail"]


def test_pdf_export_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/export.pdf",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_pdf_export_blocked_without_verified_citations(client: TestClient) -> None:
    """Same citation gate as DOCX — zero-citation drafts cannot be
    exported as PDF unless approved by a partner."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PDF-GATED")
    # No authorities seeded → mock produces a draft with no citations.
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/export.pdf",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "verified citation" in detail.lower()


def test_court_profiles_route_lists_adp16_profiles(client: TestClient) -> None:
    """GET /api/drafting/court-profiles exposes ADP-16 profile metadata.
    HC, Karnataka HC, NCLT, NCLAT, DRT — the web PDF-export selector
    reads this directly."""
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/drafting/court-profiles",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    keys = [p["key"] for p in body["profiles"]]
    assert keys == [
        "supreme_court",
        "high_court",
        "delhi_hc",
        "bombay_hc",
        "madras_hc",
        "calcutta_hc",
        "karnataka_hc",
        "district_court",
        "tribunal",
        "nclt",
        "nclat",
        "drt",
        "generic",
    ]
    sc = next(p for p in body["profiles"] if p["key"] == "supreme_court")
    assert sc["category"] == "supreme_court"
    assert sc["page_number_position"] == "center"
    assert sc["body_font_size_pt"] == 12
    assert sc["page_number_format"] == "{n}"
    assert sc["required_fields"][0]["key"] == "petitioner_or_appellant"
    district = next(p for p in body["profiles"] if p["key"] == "district_court")
    assert district["category"] == "district_court"
    assert district["cause_title_separator"] == "v."
    assert district["layout_rules"]
    nclt = next(p for p in body["profiles"] if p["key"] == "nclt")
    assert nclt["category"] == "tribunal"
    assert nclt["body_font_size_pt"] == 11


def test_court_profiles_route_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/drafting/court-profiles")
    assert resp.status_code in {401, 403}


def test_filing_checklist_surfaces_court_required_field_findings(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-CHECKLIST-REQ")
    draft_resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "District bail with incomplete facts",
            "draft_type": "brief",
            "template_type": "bail",
            "facts": {
                "complainant_name": "State",
                "accused_name": "Ravi Verma",
                "fir_number": "145/2026",
            },
        },
    )
    assert draft_resp.status_code == 200, draft_resp.text
    draft = draft_resp.json()

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-checklist"
        "?court_profile=district_court",
        headers=auth_headers(token),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["court_profile_key"] == "district_court"
    assert body["missing_required_field_count"] == 2
    findings = {item["key"]: item for item in body["required_field_findings"]}
    assert findings["court_or_forum_name"]["satisfied"] is True
    assert findings["party_names"]["satisfied"] is True
    assert findings["fir_number"]["satisfied"] is True
    assert findings["police_station"]["satisfied"] is False
    assert findings["case_number"]["satisfied"] is False
    assert all("storage_key" not in json.dumps(item) for item in findings.values())


# ---------------------------------------------------------------
# PG-005 Sprint 4 (2026-05-01) — filing bundle ZIP.
# ---------------------------------------------------------------


def _read_zip(content: bytes):
    import io
    import zipfile

    return zipfile.ZipFile(io.BytesIO(content), mode="r")


def test_filing_bundle_default_layout(client: TestClient) -> None:
    """Smoke: bundle endpoint returns a valid ZIP with the expected
    layout (00-index / 01-memorandum / 02-vakalat / 03-estamp), the
    right Content-Type + filename + telemetry headers, and a
    placeholder vakalat when no vakalat draft exists."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-1")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2001")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    disp = resp.headers["content-disposition"]
    assert "attachment" in disp
    assert "bundle.zip" in disp
    # Court profile auto-resolved from matter's "Delhi High Court".
    assert resp.headers.get("x-caseops-court-profile") == "delhi_hc"
    # No vakalat draft on the matter → placeholder.
    assert resp.headers.get("x-caseops-vakalat-source") == "placeholder"
    # No attachments seeded → exhibit count is 0.
    assert resp.headers.get("x-caseops-exhibit-count") == "0"

    with _read_zip(resp.content) as zf:
        names = sorted(zf.namelist())
        assert "00-index.pdf" in names
        assert any(n.startswith("01-memorandum-") and n.endswith(".pdf") for n in names)
        assert "02-vakalatnama.pdf" in names
        assert "03-estamp-placeholder.pdf" in names
        # Each PDF should be a real PDF (magic bytes).
        for n in ("00-index.pdf", "02-vakalatnama.pdf", "03-estamp-placeholder.pdf"):
            assert zf.read(n)[:5] == b"%PDF-", f"{n} is not a real PDF"
        # Memorandum filename embeds revision; magic-bytes check.
        memo_name = next(n for n in names if n.startswith("01-memorandum-"))
        assert "-r1-" in memo_name or memo_name.endswith("r1.pdf") or "-r1." in memo_name
        assert zf.read(memo_name)[:5] == b"%PDF-"


def test_filing_bundle_explicit_court_profile_override(
    client: TestClient,
) -> None:
    """Caller passes ?court_profile=supreme_court — bundle uses SC
    layout, response headers reflect the override."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-SC")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2002")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip"
        "?court_profile=supreme_court",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-caseops-court-profile") == "supreme_court"
    assert "supreme_court" in resp.headers["content-disposition"]


def test_filing_bundle_uses_existing_vakalat_draft(client: TestClient) -> None:
    """When the matter has a VAKALATNAMA draft, the bundle uses it
    instead of the placeholder. Vakalat-source header echoes the
    draft id."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-VK")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2003")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    # Create a VAKALATNAMA-typed draft on the same matter.
    vak_resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Vakalatnama for Mr Mehta",
            "draft_type": "other",
            "template_type": "vakalatnama",
        },
    )
    assert vak_resp.status_code == 200, vak_resp.text
    vak_id = vak_resp.json()["id"]
    _generate(client, token, matter_id, vak_id)

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("x-caseops-vakalat-source") == f"draft:{vak_id}"


def test_filing_bundle_explicit_vakalat_draft_id_must_be_vakalatnama(
    client: TestClient,
) -> None:
    """Passing a draft_id whose template_type is NOT vakalatnama
    returns 422 — the route refuses to silently swap a non-vakalat
    pleading into the vakalat slot."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-VK-422")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2004")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    # Use the memorandum draft id itself as the vakalat — should 422.
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip"
        f"?vakalat_draft_id={draft['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "VAKALATNAMA" in resp.json()["detail"]


def test_filing_bundle_blocked_without_verified_citations(
    client: TestClient,
) -> None:
    """Citation gate matches the PDF / DOCX export paths — zero-
    citation drafts are blocked unless the partner approves."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-GATED")
    # No authorities seeded.
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "verified citation" in resp.json()["detail"].lower()


def test_filing_bundle_404_on_unknown_draft(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-NF")
    resp = client.get(
        f"/api/matters/{matter_id}/drafts/00000000-0000-0000-0000-000000000000/filing-bundle.zip",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_filing_bundle_unknown_attachment_id_returns_422(
    client: TestClient,
) -> None:
    """Passing an attachment_id not on the matter → 422 with the
    bad ids surfaced in the detail."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-BUNDLE-ATT-422")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 2005")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    resp = client.get(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/filing-bundle.zip"
        "?attachment_ids=00000000-0000-0000-0000-000000000000",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "00000000-0000-0000-0000-000000000000" in resp.json()["detail"]


def test_generate_increments_revision_and_keeps_history(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-006")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 666")
    draft = _create_draft(client, token, matter_id)
    first = _generate(client, token, matter_id, draft["id"])
    assert first["versions"][0]["revision"] == 1
    second = _generate(client, token, matter_id, draft["id"])
    revisions = sorted(v["revision"] for v in second["versions"])
    assert revisions == [1, 2]
    # current_version_id tracks the newest version.
    newest = next(v for v in second["versions"] if v["revision"] == 2)
    assert second["current_version_id"] == newest["id"]


def test_manual_edit_creates_new_revision_and_invalidates_prior_approval(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-EDIT")
    citation = "2024 SCC OnLine SC 777"
    _seed_authority(neutral_citation=citation)
    draft = _create_draft(client, token, matter_id)
    generated = _generate(client, token, matter_id, draft["id"])
    original = generated["versions"][0]

    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    approved = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["review_required"] is False

    edited_body = (
        original["body"]
        + "\n\nAdditional lawyer edit preserving citation "
        + citation
        + "."
    )
    edited = client.patch(
        f"/api/matters/{matter_id}/drafts/{draft['id']}",
        headers=auth_headers(token),
        json={"body": edited_body},
    )

    assert edited.status_code == 200, edited.text
    payload = edited.json()
    assert payload["status"] == "draft"
    assert payload["review_required"] is True
    assert sorted(v["revision"] for v in payload["versions"]) == [1, 2]
    newest = next(v for v in payload["versions"] if v["revision"] == 2)
    assert payload["current_version_id"] == newest["id"]
    assert newest["body"] == edited_body
    assert newest["model_run_id"] is None
    assert newest["verified_citation_count"] >= 1
    assert [r["action"] for r in payload["reviews"]][-1] == "edit"


def test_manual_edit_drops_removed_citations_and_finalized_is_immutable(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-EDIT-FINAL")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 778")
    draft = _create_draft(client, token, matter_id)
    _generate(client, token, matter_id, draft["id"])

    removed_citation = client.patch(
        f"/api/matters/{matter_id}/drafts/{draft['id']}",
        headers=auth_headers(token),
        json={"body": "Manual draft text with no retained authority string."},
    )
    assert removed_citation.status_code == 200, removed_citation.text
    newest = max(removed_citation.json()["versions"], key=lambda v: v["revision"])
    assert newest["citations"] == []
    assert newest["verified_citation_count"] == 0

    _seed_authority(neutral_citation="2024 SCC OnLine SC 779")
    _generate(client, token, matter_id, draft["id"])
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    finalized = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/finalize",
        headers=auth_headers(token),
        json={},
    )
    assert finalized.status_code == 200, finalized.text

    edit_final = client.patch(
        f"/api/matters/{matter_id}/drafts/{draft['id']}",
        headers=auth_headers(token),
        json={"body": "Should not be saved."},
    )
    assert edit_final.status_code == 409
    assert edit_final.json()["type"] == "draft_finalized_immutable"


def test_generate_draft_provider_error_returns_actionable_422(
    client: TestClient, monkeypatch,
) -> None:
    """Hari-III-BUG-019 + Strict Ledger #7 (2026-04-22) — mirrors
    the recommendations regression for the drafting endpoint. The
    Hari III sheet numbers this drafting bug as 'BUG-019'; the
    Hari II sheet numbered an outside-counsel bug as 'BUG-019'
    (see test_hari_ii_regressions.py). Always use the
    Hari-II / Hari-III prefix when cross-referencing.

    AnthropicProvider wraps
    503 / httpx timeout in ``LLMProviderError`` (parent of
    ``LLMResponseFormatError``). Before commit 4104265 the drafting
    service caught only the format-error child; 503s escaped past
    the Haiku fallback and surfaced as opaque 500s with no
    actionable detail.

    Regression: when the primary provider raises
    ``LLMProviderError`` AND the Haiku fallback is unavailable, the
    endpoint MUST return a 422 with detail that names the failure
    shape and tells the user what to do — not a 500 with no body.
    """
    from caseops_api.services.llm import LLMMessage, LLMProviderError

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-PROVIDER-503")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 503")
    draft = _create_draft(client, token, matter_id)

    class _OverloadedProvider:
        name = "mock"
        model = "mock-overload-503"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMProviderError(
                "Anthropic call failed: 503 overloaded — please retry",
            )

    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider",
        lambda *a, **kw: _OverloadedProvider(),
    )

    resp = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    # 2026-04-30: gpt-5.1-only path. Single primary call → 422 with
    # actionable detail naming the failure shape + retry / support guidance.
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "LLMProviderError" in detail
    lowered = detail.lower()
    assert "retry" in lowered or "support" in lowered


def test_generate_draft_quota_error_returns_actionable_503_without_raw_provider_leak(
    client: TestClient, monkeypatch,
) -> None:
    from caseops_api.services.llm import LLMMessage, LLMQuotaExhaustedError

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-QUOTA-503")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 504")
    draft = _create_draft(client, token, matter_id)

    class _QuotaProvider:
        name = "openai"
        model = "gpt-5-mini"

        def generate(self, messages: list[LLMMessage], **_kwargs):
            raise LLMQuotaExhaustedError(
                "OpenAI quota exhausted: Error code: 429 - {'error': "
                "{'code': 'insufficient_quota', 'message': 'billing raw'}}"
            )

    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider",
        lambda *a, **kw: _QuotaProvider(),
    )

    resp = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["type"] == "llm_quota_exhausted"
    assert "provider quota is exhausted" in body["detail"]
    assert "draft" in body["detail"]
    assert "insufficient_quota" not in body["detail"]
    assert "billing raw" not in body["detail"]
    assert "No output was saved" in body["detail"]


def test_create_draft_stepper_facts_passthrough(client: TestClient) -> None:
    """R-UI: the stepper POSTs template_type + facts; both must be
    persisted and surfaced on the response, and the fact values must
    land in the LLM prompt so the generator can ground the body.
    """
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS")

    facts = {
        "applicant_name": "Aastha Mishra",
        "fir_number": "FIR 123/2026",
        "section_number": "BNS s.303",
        "period_of_custody_days": 45,
    }
    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail application — BNSS s.483",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": facts,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "bail_application"

    # DB row carries the full facts_json + template_type.
    factory = get_session_factory()
    session = factory()
    try:
        row = session.get(Draft, body["id"])
        assert row is not None
        assert row.template_type == "bail_application"
        assert row.facts_json is not None
        assert json.loads(row.facts_json) == facts
    finally:
        session.close()


def test_generate_draft_uses_stepper_facts_in_prompt(client: TestClient) -> None:
    """Prompt-assembly regression: when the Draft has facts_json set,
    the generated body echoes those facts rather than inserting
    bracketed placeholders."""
    from unittest.mock import patch

    from caseops_api.services import drafting as drafting_service

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS-2")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 777")

    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail — stepper-driven",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": {"applicant_name": "Ravi Verma", "fir_number": "FIR 9/2026"},
        },
    )
    assert resp.status_code == 200, resp.text
    draft_id = resp.json()["id"]

    original_build = drafting_service._build_messages
    captured: dict[str, str] = {}

    def _spy(matter, draft, retrieved, focus_note, **kwargs):
        # **kwargs accepts the bench_context BAAD-001 slice 3 added
        # to _build_messages without breaking this test's spy.
        msgs = original_build(matter, draft, retrieved, focus_note, **kwargs)
        captured["user"] = next(m.content for m in msgs if m.role == "user")
        return msgs

    with patch.object(drafting_service, "_build_messages", _spy):
        _generate(client, token, matter_id, draft_id)

    user_msg = captured["user"]
    assert "STEPPER FACTS" in user_msg
    assert "applicant_name: Ravi Verma" in user_msg
    assert "fir_number: FIR 9/2026" in user_msg
    assert "Template: bail_application" in user_msg


def _field_by_key(fields: list[dict], key: str) -> dict:
    return next(field for field in fields if field["field_key"] == key)


def test_drafting_data_extracts_reviewable_fields_from_existing_document_text(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DATA-1")
    attachment_id = _seed_attachment(
        matter_id,
        extracted_text=(
            "FIR No. 42/2026 was registered at Police Station: Indiranagar. "
            "Complainant Name: Neha Rao. Accused Name: Ravi Verma. "
            "Incident Date: 12/05/2026. Notice dated 14 May 2026. "
            "Sections 138 and 142 of NI Act are referenced. CC 88/2026."
        ),
    )

    response = client.post(
        f"/api/matters/{matter_id}/drafting-data/extract",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_count"] >= 6
    fields = body["fields"]
    assert _field_by_key(fields, "fir_number")["proposed_value"] == "42/2026"
    assert _field_by_key(fields, "police_station")["source_attachment_id"] == attachment_id
    assert _field_by_key(fields, "police_station")["status"] == "suggested"
    assert _field_by_key(fields, "case_number")["status"] == "needs_review"
    for field in fields:
        assert field["status"] != "confirmed"
        if field["source_snippet"] is not None:
            assert len(field["source_snippet"]) <= 280
    serialized = response.text
    assert "storage_key" not in serialized
    assert "test/drafting/" not in serialized


def test_drafting_data_review_actions_and_audit_are_redacted(
    client: TestClient,
) -> None:
    boot = _bootstrap_company_with_slug(client, f"adp15-audit-{uuid.uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "DS-DATA-2")
    _seed_attachment(
        matter_id,
        extracted_text=(
            "FIR No. 77/2026. Police Station: Koramangala. "
            "Complainant Name: Secret Complainant Tail. "
            "Accused Name: Sensitive Accused Tail."
        ),
    )
    extracted = client.post(
        f"/api/matters/{matter_id}/drafting-data/extract",
        headers=auth_headers(token),
    )
    assert extracted.status_code == 200, extracted.text
    fields = extracted.json()["fields"]
    fir = _field_by_key(fields, "fir_number")
    station = _field_by_key(fields, "police_station")
    accused = _field_by_key(fields, "accused_name")

    confirm = client.patch(
        f"/api/matters/{matter_id}/drafting-data/{fir['id']}",
        headers=auth_headers(token),
        json={"action": "confirm"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"
    assert confirm.json()["effective_value"] == "77/2026"

    override = client.patch(
        f"/api/matters/{matter_id}/drafting-data/{station['id']}",
        headers=auth_headers(token),
        json={"action": "override", "override_value": "Corrected PS"},
    )
    assert override.status_code == 200, override.text
    assert override.json()["status"] == "overridden"
    assert override.json()["effective_value"] == "Corrected PS"
    assert override.json()["reviewed_at"] is not None

    rejected = client.patch(
        f"/api/matters/{matter_id}/drafting-data/{accused['id']}",
        headers=auth_headers(token),
        json={"action": "reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["effective_value"] is None

    with get_session_factory()() as session:
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .where(AuditEvent.action.in_(["drafting_data.extracted", "drafting_data.reviewed"]))
                .order_by(AuditEvent.created_at.asc())
            )
        )
    audit_blob = json.dumps([event.metadata_json for event in events])
    assert "Secret Complainant Tail" not in audit_blob
    assert "Sensitive Accused Tail" not in audit_blob
    assert "Corrected PS" not in audit_blob
    assert "storage_key" not in audit_blob
    assert "test/drafting/" not in audit_blob


def test_reviewed_drafting_data_feeds_prompt_without_overriding_stepper_facts(
    client: TestClient,
) -> None:
    from unittest.mock import patch

    from caseops_api.services import drafting as drafting_service

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-DATA-3")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 778")
    _seed_attachment(
        matter_id,
        extracted_text=(
            "FIR No. 42/2026. Police Station: Indiranagar. "
            "Complainant Name: Neha Rao. Accused Name: Ravi Verma."
        ),
    )
    extracted = client.post(
        f"/api/matters/{matter_id}/drafting-data/extract",
        headers=auth_headers(token),
    )
    assert extracted.status_code == 200, extracted.text
    fields = extracted.json()["fields"]
    complainant = _field_by_key(fields, "complainant_name")
    fir = _field_by_key(fields, "fir_number")
    police_station = _field_by_key(fields, "police_station")
    accused = _field_by_key(fields, "accused_name")
    for field in (complainant,):
        assert client.patch(
            f"/api/matters/{matter_id}/drafting-data/{field['id']}",
            headers=auth_headers(token),
            json={"action": "confirm"},
        ).status_code == 200
    assert client.patch(
        f"/api/matters/{matter_id}/drafting-data/{fir['id']}",
        headers=auth_headers(token),
        json={"action": "override", "override_value": "FIR 42/2026"},
    ).status_code == 200
    assert client.patch(
        f"/api/matters/{matter_id}/drafting-data/{accused['id']}",
        headers=auth_headers(token),
        json={"action": "reject"},
    ).status_code == 200

    draft = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Bail with reviewed data",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": {"fir_number": "FIR 999/2026"},
        },
    )
    assert draft.status_code == 200, draft.text
    draft_id = draft.json()["id"]

    original_build = drafting_service._build_messages
    captured: dict[str, str] = {}

    def _spy(matter, draft, retrieved, focus_note, **kwargs):
        msgs = original_build(matter, draft, retrieved, focus_note, **kwargs)
        captured["user"] = next(m.content for m in msgs if m.role == "user")
        return msgs

    with patch.object(drafting_service, "_build_messages", _spy):
        _generate(client, token, matter_id, draft_id)

    user_msg = captured["user"]
    assert "REVIEWED DRAFTING DATA" in user_msg
    assert "Complainant name (complainant_name): Neha Rao" in user_msg
    assert "fir_number: FIR 999/2026" in user_msg
    assert "FIR 42/2026" not in user_msg
    assert "Police station (police_station)" not in user_msg
    assert police_station["proposed_value"] not in user_msg
    assert "Accused name (accused_name)" not in user_msg
    assert "Ravi Verma" not in user_msg


def test_drafting_data_routes_enforce_matter_access_boundaries(
    client: TestClient,
) -> None:
    boot_a = _bootstrap_company_with_slug(client, f"adp15-acl-a-{uuid.uuid4().hex[:6]}")
    owner_token = str(boot_a["access_token"])
    company_slug = str(boot_a["company"]["slug"])
    company_id = str(boot_a["company"]["id"])
    matter_id = _create_matter(client, owner_token, "DS-DATA-ACL")
    _seed_attachment(matter_id, extracted_text="FIR No. 11/2026.")
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"drafting-member-{uuid.uuid4().hex[:6]}@example.in",
    )
    boot_b = _bootstrap_company_with_slug(client, f"adp15-acl-b-{uuid.uuid4().hex[:6]}")
    other_token = str(boot_b["access_token"])

    cross_tenant = client.get(
        f"/api/matters/{matter_id}/drafting-data",
        headers=auth_headers(other_token),
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    hidden = client.post(
        f"/api/matters/{matter_id}/drafting-data/extract",
        headers=auth_headers(member_token),
    )
    assert hidden.status_code == 404, hidden.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=auth_headers(owner_token),
        json={"membership_id": member_id, "reason": "Drafting review"},
    )
    assert grant.status_code == 200, grant.text
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter_id}/drafting-data",
        headers=auth_headers(member_token),
    )
    assert walled.status_code == 404, walled.text

    team_matter_id = _create_matter(client, owner_token, "DS-DATA-TEAM")
    with get_session_factory()() as session:
        team = Team(
            id=str(uuid.uuid4()),
            company_id=company_id,
            name="Drafting Team",
            slug=f"drafting-team-{uuid.uuid4().hex[:6]}",
        )
        session.add(team)
        session.flush()
        matter = session.get(Matter, team_matter_id)
        company = session.get(Company, company_id)
        assert matter is not None
        assert company is not None
        matter.team_id = team.id
        company.team_scoping_enabled = True
        session.commit()
    team_hidden = client.get(
        f"/api/matters/{team_matter_id}/drafting-data",
        headers=auth_headers(member_token),
    )
    assert team_hidden.status_code == 404, team_hidden.text


def test_create_draft_rejects_oversized_facts(client: TestClient) -> None:
    """Defensive cap: >64 KiB of facts JSON → 413 so a pathological
    client can't inflate draft rows."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FACTS-CAP")

    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={
            "title": "Too much",
            "draft_type": "brief",
            "template_type": "bail_application",
            "facts": {"blob": "x" * (65 * 1024)},
        },
    )
    assert resp.status_code == 413, resp.text
