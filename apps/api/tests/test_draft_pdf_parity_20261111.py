import time
from dataclasses import replace

import pypdfium2 as pdfium

from caseops_api.services.court_format_profiles import resolve_profile
from caseops_api.services.draft_pdf_export import render_pdf_bytes


def render(profile, **overrides):
    return render_pdf_bytes(
        **{
            "profile": profile,
            "title": "Synthetic regular bail layout fixture",
            "matter_title": "Synthetic matter",
            "matter_code": "QA-B5",
            "draft_type": "brief",
            "revision": 1,
            "status_label": "approved",
            "body": "FACTS\n\nSynthetic layout fixture only. No legal proposition.",
            "citations": [],
            "review_required": False,
            **overrides,
        }
    )


def test_long_court_header_stays_within_profile_margins():
    profile = replace(
        resolve_profile(explicit_key="delhi_hc"), court_header_text="SYNTHETIC COURT HEADER " * 8
    )
    with pdfium.PdfDocument(render(profile)) as document:
        page = document[0]
        text = page.get_textpage()
        try:
            # Every character of the long header must fit, not merely its start.
            header_end = text.get_text_range().index("Synthetic regular bail")
            boxes = [
                text.get_charbox(i) for i in range(header_end) if text.get_text_range(i, 1).strip()
            ]
            assert min(box[0] for box in boxes) >= profile.margin_left_mm * 72 / 25.4 - 1
            assert max(box[2] for box in boxes) <= (210 - profile.margin_right_mm) * 72 / 25.4 + 1
        finally:
            text.close()
            page.close()


def test_layout_digest_tracks_settings_without_claiming_legal_review():
    profile = resolve_profile(explicit_key="delhi_hc")
    assert profile.layout_digest == replace(profile).layout_digest
    assert profile.layout_digest != replace(profile, margin_left_mm=30).layout_digest
    with pdfium.PdfDocument(render(profile)) as document:
        assert document.get_metadata_dict()["Subject"] == (
            f"court-profile=delhi_hc; layout-sha256={profile.layout_digest}; rules=unverified"
        )
        text = document[0].get_textpage().get_text_range()
        assert "Court rules unverified; lawyer review required." in text
        assert "FACTS" in text


def test_review_required_warning_survives_multipage_export(tmp_path):
    data = render(
        resolve_profile(explicit_key="generic"),
        review_required=True,
        body="\n\n".join(f"{i}. Synthetic paragraph only." for i in range(130)),
    )
    (tmp_path / "multipage-review.pdf").write_bytes(data)
    assert b"/FontFile2" in data
    with pdfium.PdfDocument(data) as document:
        assert len(document) >= 3
        assert "REVIEW REQUIRED" in document[0].get_textpage().get_text_range()
        for index in range(len(document)):
            text = document[index].get_textpage().get_text_range()
            assert f"Page{index + 1}of{len(document)}" in "".join(text.split())
            document[index].render(scale=1.2).to_pil().save(tmp_path / f"page-{index + 1}.png")


def test_pdf_api_pins_persisted_version_and_preserves_gates(client, monkeypatch):
    from caseops_api.db.models import Draft, DraftVersion
    from caseops_api.db.session import get_session_factory
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_drafting_studio import _create_draft, _create_matter

    def no_model(*args, **kwargs):
        raise AssertionError("PDF acceptance must not invoke a model")

    monkeypatch.setattr("caseops_api.services.drafting.build_provider", no_model)
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    matter_code = "SYNTHETIC-B5-PDF"
    matter_id = _create_matter(client, token, matter_code)
    created = _create_draft(client, token, matter_id)
    with get_session_factory()() as session:
        draft = session.get(Draft, created["id"])
        first = DraftVersion(
            draft_id=draft.id,
            revision=1,
            generated_by_membership_id=draft.created_by_membership_id,
            body="Synthetic persisted approved content. No legal claim.",
            citations_json='["SYNTHETIC-NOT-A-LEGAL-AUTHORITY"]',
            verified_citation_count=1,
        )
        session.add(first)
        session.flush()
        draft.current_version_id = first.id
        first_id = first.id
        session.commit()
    base = f"/api/matters/{matter_id}/drafts/{created['id']}"
    for action in ("submit", "approve"):
        result = client.post(f"{base}/{action}", headers=headers, json={})
        assert result.status_code == 200, result.text
    persisted = client.get(base, headers=headers).json()
    assert persisted["status"] == "approved"
    assert any(
        row["action"] == "approve" and row["version_id"] == first_id for row in persisted["reviews"]
    )
    response = client.get(f"{base}/export.pdf", params={"version_id": first_id}, headers=headers)
    assert response.status_code == 200, response.text
    # PDF creation metadata has whole-second precision; a later authorization
    # read must still produce identical bytes for the persisted snapshot.
    time.sleep(1.1)
    reauthorized = client.get(
        f"{base}/export.pdf", params={"version_id": first_id}, headers=headers
    )
    assert reauthorized.status_code == 200, reauthorized.text
    assert reauthorized.content == response.content
    assert response.headers["x-caseops-court-profile"] == "delhi_hc"
    with pdfium.PdfDocument(response.content) as document:
        assert (
            "Synthetic persisted approved content." in document[0].get_textpage().get_text_range()
        )
    assert (
        client.get(
            f"{base}/export.pdf", params={"version_id": "absent"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{base}/export.pdf", params={"court_profile": "invented"}, headers=headers
        ).status_code
        == 422
    )
    client.cookies.clear()
    assert client.get(f"{base}/export.pdf").status_code == 401
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Synthetic second PDF tenant",
            "company_slug": "other-pdf-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Synthetic PDF owner",
            "owner_email": "other-pdf@example.com",
            "owner_password": "SyntheticPdf!2345",
        },
    )
    assert other.status_code == 200, other.text
    other_token = str(other.json()["access_token"])
    assert client.get(f"{base}/export.pdf", headers=auth_headers(other_token)).status_code == 404
    updated = client.patch(
        base, headers=headers, json={"body": "Synthetic unapproved replacement without citations."}
    )
    assert updated.status_code == 200, updated.text
    assert client.get(f"{base}/export.pdf", headers=headers).status_code == 422
    old_response = client.get(
        f"{base}/export.pdf", params={"version_id": first_id}, headers=headers
    )
    assert old_response.status_code == 200, old_response.text
    with pdfium.PdfDocument(old_response.content) as document:
        text = document[0].get_textpage().get_text_range()
        assert "Synthetic persisted approved content." in text
        assert "Synthetic unapproved replacement" not in text
