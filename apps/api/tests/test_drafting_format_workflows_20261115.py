"""Offline workflow/byte contracts, not a real-model legal-quality benchmark."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import func, select

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_HEADER,
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
)
from caseops_api.db.models import AuditEvent, Draft, DraftVersion, ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.services.court_format_profiles import resolve_profile
from caseops_api.services.drafting_formats import format_manifest
from caseops_api.services.llm import LLMCompletion, MockProvider
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_drafting_studio import _create_matter, _seed_authority
from tests.test_pdf_unicode_fidelity_20261104 import compact, numbered_pdf_body_pages

INVALID_DEED_FACTS = (
    None, {}, {"instrument_type": "unsupported", "private_fact": "PRIVATE-FACT-NEVER-REFLECT"},
)
EXISTING_VARIANT_CASES = (
    ("civil_suit", "suit_format", "General civil plaint"),
    ("special_leave_petition", "slp_kind", "civil"),
    ("writ_petition", "writ_kind", "criminal"),
    ("property_dispute_notice", "notice_format", "Notice to quit / ejectment"),
)
MISSING_LAW_CASES = (
    ("execution_application", {"court_name": "Synthetic court", "parties": "Supplied parties",
      "material_facts": "Supplied decree and request", "grounds": "Supplied grounds",
      "relief_sought": "Supplied relief"}),
    ("government_suit_notice", {"sender_details": "Supplied sender",
      "addressee_details": "Actual recipient", "subject": "Supplied subject",
      "material_facts": "Supplied facts", "required_action": "Supplied request"}),
    ("conveyancing_deed", {"instrument_type": "Gift deed", "parties": "Supplied parties",
      "transaction_facts": "Supplied transaction", "operative_terms": "Agreed terms"}),
)


def _reference_cases():
    source = Path(__file__).parent / "fixtures" / "drafting" / "reference_formats.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    court_types = {
        "injunction_breach_application", "indigent_person_application", "execution_application",
        "restitution_conjugal_rights", "judicial_separation_petition", "mutual_consent_divorce",
        "letters_of_administration", "succession_certificate", "cheque_bounce_complaint",
        "maintenance_application", "consumer_complaint", "domestic_violence_complaint",
    }
    if (
        set(data["court_forms"]) != court_types
        or set(data["notice_forms"]) != {"government_suit_notice", "legal_notice_reply"}
        or data["instruments"] != [
            "Sale deed", "Mortgage deed", "Partnership deed", "Dissolution of partnership",
            "Relinquishment deed", "Gift deed",
        ]
        or set(data["existing_variants"]) != {
            "civil_suit", "special_leave_petition", "property_dispute_notice", "writ_petition",
        }
        or data["existing_variants"]["civil_suit"]["variants"] != {
            "General civil plaint": {"suit_format": "General civil plaint"},
            "Summary recovery": {"suit_format": "Summary recovery"},
            "Permanent injunction": {"suit_format": "Permanent injunction"},
            "Ejectment and damages": {"suit_format": "Ejectment and damages"},
            "Specific performance": {"suit_format": "Specific performance"},
        }
        or data["existing_variants"]["special_leave_petition"]["variants"] != {
            "civil": {"slp_kind": "civil"}, "criminal": {"slp_kind": "criminal"},
        }
        or data["existing_variants"]["property_dispute_notice"]["variants"] != {
            "General property dispute": {"notice_format": "General property dispute"},
            "Notice to quit / ejectment": {"notice_format": "Notice to quit / ejectment"},
        }
        or data["existing_variants"]["writ_petition"]["variants"] != {
            "civil": {"writ_kind": "civil", "writ_type": "mandamus"},
            "criminal": {"writ_kind": "criminal", "writ_type": "habeas_corpus"},
        }
    ):
        raise ValueError("Unsupported reference workflow fixture inventory.")
    cases = []
    for key, details in data["court_forms"].items():
        cases.append(pytest.param(
            key, {**data["court_facts"], "procedure_details": details}, id=key,
        ))
    for key, details in data["notice_forms"].items():
        cases.append(pytest.param(key, {**data["notice_facts"], **details}, id=key))
    for instrument in data["instruments"]:
        cases.append(pytest.param(
            "conveyancing_deed", {**data["deed_facts"], "instrument_type": instrument},
            id=instrument,
        ))
    for template, block in data["existing_variants"].items():
        for key, selection in block["variants"].items():
            cases.append(pytest.param(
                template, {**block["facts"], **selection}, id=f"{template}-{key}",
            ))
    return cases


class _ReferenceProvider(MockProvider):
    """Explicit owned offline transport with captured real builder messages."""

    def __init__(self, body: str, citation: str | None, *, structured_response: bool = True):
        super().__init__()
        self.body = body
        self.citation = citation
        self.structured_response = structured_response
        self.observations = []

    def generate(self, messages, *, temperature=0.2, max_tokens=1024):
        self.observations.append((messages, paid_providers_blocked_for_request()))
        return LLMCompletion(
            text=json.dumps({
                "body": self.body, "citations": [self.citation] if self.citation else [],
                "summary": "Synthetic workflow only.",
            }) if self.structured_response else self.body,
            provider=self.name, model=self.model,
            prompt_tokens=120, completion_tokens=100, latency_ms=1,
        )


def _counts(matter_id):
    with get_session_factory()() as session:
        return (
            session.scalar(
                select(func.count()).select_from(Draft).where(Draft.matter_id == matter_id),
            ),
            session.scalar(
                select(func.count()).select_from(DraftVersion)
                .join(Draft, Draft.id == DraftVersion.draft_id)
                .where(Draft.matter_id == matter_id),
            ),
            session.scalar(
                select(func.count()).select_from(ModelRun).where(ModelRun.matter_id == matter_id),
            ),
            session.scalar(
                select(func.count()).select_from(AuditEvent)
                .where(AuditEvent.matter_id == matter_id),
            ),
        )


def _marked_setup(client):
    # This is this actual HTTP client's marker; no browser fixture supplies it.
    client.headers[NO_PAID_PROVIDERS_HEADER] = NO_PAID_PROVIDERS_VALUE
    token = str(bootstrap_company(client)["access_token"])
    headers = {**auth_headers(token), NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE}
    matter_id = _create_matter(client, token, "SYNTHETIC-REFERENCE-FORMAT")
    return matter_id, headers


@pytest.mark.parametrize("template_type,facts", _reference_cases())
def test_new_format_preview_generation_review_history_and_real_exports(
    client, monkeypatch, template_type, facts,
):
    matter_id, headers = _marked_setup(client)
    citation = "2024 SCC OnLine SC 717151"
    authority_id = _seed_authority(citation)
    expected_reference = format_manifest(template_type, facts=facts)
    family = expected_reference["family"]
    title = str(facts.get("instrument_type", "Synthetic supplied document"))
    if template_type == "execution_application":
        source = Path(__file__).parent / "fixtures" / "drafting" / "reference_formats.json"
        body = json.loads(source.read_text(encoding="utf-8"))["render_samples"][template_type]
    elif family == "deed":
        role_labels = {
            "Sale deed": "Vendor\nVendee", "Mortgage deed": "Mortgagor\nMortgagee",
            "Partnership deed": "Partners", "Dissolution of partnership": "Partners",
            "Relinquishment deed": "Releasor\nReleasee", "Gift deed": "Donor\nDonee",
        }[title]
        first_heading, second_heading = (
            ("BY", "IN FAVOUR OF") if title in {"Mortgage deed", "Relinquishment deed"}
            else ("BETWEEN", "AND")
        )
        body = (
            f"{title.upper()}\n{first_heading}\n[Supplied first party]\n"
            f"{second_heading}\n[Supplied second party]\nRECITALS\n"
            "1. Supplied transaction only.\nOPERATIVE TERMS\n2. Amount ₹0.50.\nSCHEDULE\n"
            f"[Supplied property]\nEXECUTION\n[Signature]\n{role_labels}"
        )
    elif family in {"notice", "correspondence_reply"}:
        body = (
            "FROM: [supplied sender]\nTO: [actual recipient]\nSubject: [supplied subject]\n"
            "1. Supplied facts only; amount ₹0.50.\n[Requested action]\n[Signature]"
        )
    else:
        body = (
            "IN THE COURT OF [confirmed court]\nBETWEEN\n[Supplied parties]\nFACTS\n"
            "1. Supplied facts only; amount ₹0.50.\nGROUNDS\n2. [Supported grounds]\nPRAYER\n"
            "(a) [Supplied relief]\nVERIFICATION\n[Actual paragraph ranges]\n[Signature]\nApplicant"
        )
    # Catalogue identity proves pipeline wiring only, never proposition accuracy.
    body += f"\n[{citation}]"
    provider = _ReferenceProvider(body, citation)
    preview_body = (
        ("RECITALS" if family == "deed" else "FACTS")
        + "\n1. Synthetic supplied facts only; other particulars are [not yet specified]."
    )
    preview_provider = _ReferenceProvider(preview_body, None, structured_response=False)
    monkeypatch.setattr("caseops_api.services.drafting.build_provider", lambda **kw: provider)
    monkeypatch.setattr(
        "caseops_api.services.drafting_preview._default_preview_provider", lambda: preview_provider,
    )
    from caseops_api.db.models import AuthorityDocument

    with get_session_factory()() as session:
        authority = session.get(AuthorityDocument, authority_id)
        assert authority is not None
        session.expunge(authority)
    monkeypatch.setattr(
        "caseops_api.services.drafting._retrieve_for_draft", lambda *a, **kw: [authority],
    )

    schema = client.get(f"/api/drafting/templates/{template_type}", headers=headers)
    assert schema.status_code == 200, schema.text
    preview = client.post("/api/drafting/preview", headers=headers, json={
        "template_type": template_type, "facts": facts, "step_group": "facts",
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["step_group"] == "facts"
    assert preview.json()["template_type"] == template_type
    assert preview.json()["preview_text"] == preview_body
    assert len(preview_provider.observations) == 1
    assert (
        "For a partial preview, render only the requested step"
        in preview_provider.observations[0][0][0].content
    )

    created = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": title, "template_type": template_type, "draft_type": "brief", "facts": facts,
    })
    assert created.status_code == 200, created.text
    base = f"/api/matters/{matter_id}/drafts/{created.json()['id']}"
    generated = client.post(f"{base}/generate", headers=headers, json={})
    assert generated.status_code == 200, generated.text
    first = generated.json()["versions"][0]
    assert first["body"] == body
    assert first["template_manifest"]["presentation_reference"] == expected_reference
    assert first["verified_citation_count"] == 1
    for action in ("submit", "request-changes"):
        result = client.post(f"{base}/{action}", headers=headers, json={})
        assert result.status_code == 200, result.text
    regenerated = client.post(
        f"{base}/generate", headers=headers,
        json={"focus_note": "Keep supplied facts and structure."},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["versions"][0] == first
    second = regenerated.json()["versions"][1]
    assert second["revision"] == 2
    assert second["template_manifest"]["presentation_reference"] == expected_reference
    edited_body = body + "\n[Lawyer-confirmed additional term]"
    edited = client.patch(base, headers=headers, json={"body": edited_body})
    assert edited.status_code == 200, edited.text
    third = edited.json()["versions"][2]
    assert third["revision"] == 3 and third["body"] == edited_body
    assert third["template_manifest"] == second["template_manifest"]
    assert edited.json()["review_required"] is True
    for action in ("submit", "approve", "finalize"):
        result = client.post(f"{base}/{action}", headers=headers, json={})
        assert result.status_code == 200, result.text
    reloaded = client.get(base, headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json() == result.json()
    assert reloaded.json()["current_version_id"] == third["id"]
    assert reloaded.json()["versions"] == [first, second, third]
    assert [row["action"] for row in reloaded.json()["reviews"]] == [
        "submit", "request_changes", "edit", "submit", "approve", "finalize",
    ]

    docx = client.get(f"{base}/export.docx", headers=headers, params={"version_id": third["id"]})
    assert docx.status_code == 200, docx.text
    document = Document(io.BytesIO(docx.content))
    if template_type == "execution_application":
        from docx.oxml.ns import qn

        word_text = "".join(node.text or "" for node in document.element.body.iter(qn("w:t")))
        assert compact(edited_body) in compact(word_text)
        assert len(document.tables) == 1 and len(document.tables[0].rows) == 10
        assert len(document.tables[0].columns) == 3
    else:
        word_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        assert edited_body in word_text
    assert "Revision 3" not in word_text
    assert document.core_properties.identifier == expected_reference["source_sha256"]
    pdf = client.get(f"{base}/export.pdf", headers=headers, params={"version_id": third["id"]})
    assert pdf.status_code == 200, pdf.text
    profile = resolve_profile(explicit_key=pdf.headers["x-caseops-court-profile"])
    pages = numbered_pdf_body_pages(pdf.content, profile.page_number_format)
    pdf_text = "\n".join(pages)
    assert compact(edited_body) in compact(pdf_text)
    if template_type == "execution_application":
        assert len(pages) >= 2
        assert sum("DecreeHolderAdvocate" in compact(page) for page in pages) == 1
    assert b"/FontFile2" in pdf.content
    if family in {"notice", "correspondence_reply", "deed"}:
        assert pdf.headers["x-caseops-court-profile"] == "generic"
        assert "IN THE HIGH COURT OF DELHI" not in pdf_text
        bundle = client.get(f"{base}/filing-bundle.zip", headers=headers)
        assert bundle.status_code == 422, bundle.text
    frozen_counts = _counts(matter_id)
    refused = client.post(f"{base}/generate", headers=headers, json={})
    assert refused.status_code == 409, refused.text
    assert _counts(matter_id) == frozen_counts
    assert len(provider.observations) == 2  # one generation, one regeneration
    observations = [*preview_provider.observations, *provider.observations]
    assert len(observations) == 3 and all(marked for _, marked in observations)
    for messages, _ in observations:
        assert "structure only, not legal authority or facts" in messages[0].content
        assert "Selected format: " + template_type in messages[0].content


@pytest.mark.parametrize("facts", INVALID_DEED_FACTS)
def test_invalid_new_deed_is_refused_over_http_without_persisted_side_effects(
    client, monkeypatch, facts,
):
    matter_id, headers = _marked_setup(client)
    calls = []
    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider", lambda **kw: calls.append("provider"),
    )
    monkeypatch.setattr(
        "caseops_api.services.drafting._retrieve_for_draft",
        lambda *a, **kw: calls.append("retrieve"),
    )
    before = _counts(matter_id)
    response = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic deed", "template_type": "conveyancing_deed", "facts": facts,
    })
    assert response.status_code == 422, response.text
    assert response.json()["errors"][0]["loc"] == ["body", "facts", "instrument_type"]
    assert "PRIVATE-FACT-NEVER-REFLECT" not in response.text
    assert calls == []
    assert _counts(matter_id) == before


@pytest.mark.parametrize("template,field,valid", EXISTING_VARIANT_CASES)
def test_invalid_existing_variant_is_refused_before_admission_and_retained_generation(
    client, monkeypatch, template, field, valid,
):
    matter_id, headers = _marked_setup(client)
    calls = []
    monkeypatch.setattr(
        "caseops_api.services.drafting.build_provider", lambda **kw: calls.append("provider"),
    )
    monkeypatch.setattr(
        "caseops_api.services.drafting._retrieve_for_draft",
        lambda *a, **kw: calls.append("retrieve"),
    )
    facts = {field: "PRIVATE-UNSUPPORTED-FORMAT"}
    before = _counts(matter_id)
    refused = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic format choice", "template_type": template, "facts": facts,
    })
    assert refused.status_code == 422, refused.text
    assert refused.json()["errors"][0]["loc"] == ["body", "facts", field]
    assert "PRIVATE-UNSUPPORTED-FORMAT" not in refused.text
    assert _counts(matter_id) == before and calls == []
    admitted = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic format choice", "template_type": template, "facts": {field: valid},
    })
    assert admitted.status_code == 200, admitted.text
    draft_id = admitted.json()["id"]
    # Defensive retained-state fixture, not a claim about a historical writer.
    with get_session_factory()() as session:
        record = session.get(Draft, draft_id)
        assert record is not None
        record.facts_json = json.dumps(facts)
        session.commit()
    before = _counts(matter_id)
    generated = client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/generate", headers=headers, json={},
    )
    assert generated.status_code == 422, generated.text
    assert generated.json()["errors"][0]["loc"] == ["body", "facts", field]
    assert "PRIVATE-UNSUPPORTED-FORMAT" not in generated.text
    assert _counts(matter_id) == before and calls == []
    retained = client.get(f"/api/matters/{matter_id}/drafts/{draft_id}", headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["versions"] == []


@pytest.mark.parametrize("template_type,facts", MISSING_LAW_CASES)
def test_required_governing_law_is_enforced_by_the_http_server_without_echoing_inputs(
    client, template_type, facts,
):
    matter_id, headers = _marked_setup(client)
    before = _counts(matter_id)
    for invalid in (
        facts, {**facts, "governing_law": " \t\n "},
        {**facts, "governing_law": {"private": "PRIVATE-LAW-INPUT"}},
    ):
        response = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
            "title": "Synthetic new format", "template_type": template_type, "facts": invalid,
        })
        assert response.status_code == 422, response.text
        errors = response.json()["errors"]
        assert any(error["loc"] == ["body", "facts", "governing_law"] for error in errors)
        assert all("input" not in error and "ctx" not in error for error in errors)
        assert "PRIVATE-LAW-INPUT" not in response.text
        assert _counts(matter_id) == before


def test_new_reference_does_not_bypass_zero_citation_approval_or_export_controls(
    client, monkeypatch,
):
    matter_id, headers = _marked_setup(client)
    provider = _ReferenceProvider(
        "Gift deed\nRECITALS\n[Supplied facts]\nEXECUTION\n[Signature]", None,
    )
    monkeypatch.setattr("caseops_api.services.drafting.build_provider", lambda **kw: provider)
    monkeypatch.setattr("caseops_api.services.drafting._retrieve_for_draft", lambda *a, **kw: [])
    response = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Gift deed", "template_type": "conveyancing_deed", "facts": {
            "instrument_type": "Gift deed", "parties": "Supplied donor and donee",
            "transaction_facts": "Supplied transaction",
            "governing_law": "[Confirmed law]", "operative_terms": "Actual agreed terms",
        },
    })
    assert response.status_code == 200, response.text
    base = f"/api/matters/{matter_id}/drafts/{response.json()['id']}"
    generated = client.post(f"{base}/generate", headers=headers, json={})
    assert generated.status_code == 200, generated.text
    version = generated.json()["versions"][0]
    assert version["verified_citation_count"] == 0
    assert version["template_manifest"]["presentation_reference"]["family"] == "deed"
    submitted = client.post(f"{base}/submit", headers=headers, json={})
    assert submitted.status_code == 200, submitted.text
    before = _counts(matter_id)
    approval = client.post(f"{base}/approve", headers=headers, json={})
    assert approval.status_code == 422, approval.text
    for suffix in ("export.docx", "export.pdf", "filing-bundle.zip"):
        refused = client.get(f"{base}/{suffix}", headers=headers)
        assert refused.status_code == 422, refused.text
    persisted = client.get(base, headers=headers)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["status"] == "in_review"
    assert persisted.json()["current_version_id"] == version["id"]
    assert not any(row["action"] == "approve" for row in persisted.json()["reviews"])
    assert _counts(matter_id) == before
    assert len(provider.observations) == 1 and provider.observations[0][1] is True


@pytest.mark.parametrize("retained_approved_fixture", [False, True])
def test_incomplete_execution_table_cannot_be_approved_finalized_or_exported(
    client, monkeypatch, retained_approved_fixture,
):
    from caseops_api.db.models import DraftStatus

    matter_id, headers = _marked_setup(client)
    citation = "2024 SCC OnLine SC 717152"
    _seed_authority(citation)
    invalid_body = f"IN THE COURT OF [actual court]\nEXECUTION APPLICATION\n[{citation}]"
    provider = _ReferenceProvider(invalid_body, citation)
    monkeypatch.setattr("caseops_api.services.drafting.build_provider", lambda **kw: provider)
    monkeypatch.setattr("caseops_api.services.drafting._retrieve_for_draft", lambda *a, **kw: [])
    source = Path(__file__).parent / "fixtures" / "drafting" / "reference_formats.json"
    fixture = json.loads(source.read_text(encoding="utf-8"))
    response = client.post(f"/api/matters/{matter_id}/drafts", headers=headers, json={
        "title": "Synthetic execution application", "template_type": "execution_application",
        "facts": {
            **fixture["court_facts"], "procedure_details": "Actual supplied decree particulars",
        },
    })
    assert response.status_code == 200, response.text
    draft_id = response.json()["id"]
    base = f"/api/matters/{matter_id}/drafts/{draft_id}"
    generated = client.post(f"{base}/generate", headers=headers, json={})
    assert generated.status_code == 200, generated.text
    original = generated.json()["versions"][0]
    assert original["verified_citation_count"] == 1
    if retained_approved_fixture:
        # Defensive retained-state input, not a claim that the current HTTP
        # approval accepted this malformed body or that a historical worker ran.
        with get_session_factory()() as session:
            record = session.get(Draft, draft_id)
            assert record is not None
            record.status = DraftStatus.APPROVED
            record.review_required = False
            session.commit()
        action = "finalize"
    else:
        submitted = client.post(f"{base}/submit", headers=headers, json={})
        assert submitted.status_code == 200, submitted.text
        action = "approve"
    before = _counts(matter_id)
    refused = client.post(f"{base}/{action}", headers=headers, json={})
    assert refused.status_code == 422, refused.text
    assert "ten labelled rows" in refused.json()["detail"]
    for suffix in ("export.docx", "export.pdf", "filing-bundle.zip"):
        exported = client.get(f"{base}/{suffix}", headers=headers)
        assert exported.status_code == 422, exported.text
        assert "ten labelled rows" in exported.json()["detail"]
    retained = client.get(base, headers=headers)
    assert retained.status_code == 200, retained.text
    assert retained.json()["current_version_id"] == original["id"]
    assert retained.json()["versions"][0] == original
    assert not any(row["action"] in {"approve", "finalize"}
                   for row in retained.json()["reviews"])
    assert _counts(matter_id) == before
    fixed_body = fixture["render_samples"]["execution_application"] + f"\n[{citation}]"
    corrected = client.patch(base, headers=headers, json={"body": fixed_body})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "draft"
    assert corrected.json()["versions"][0] == original
    current = corrected.json()["versions"][1]
    assert current["template_manifest"] == original["template_manifest"]
    for transition in ("submit", "approve", "finalize"):
        result = client.post(f"{base}/{transition}", headers=headers, json={})
        assert result.status_code == 200, result.text
    pdf = client.get(f"{base}/export.pdf", headers=headers)
    assert pdf.status_code == 200, pdf.text
    profile = resolve_profile(explicit_key=pdf.headers["x-caseops-court-profile"])
    pages = numbered_pdf_body_pages(pdf.content, profile.page_number_format)
    assert compact(fixed_body) in compact("\n".join(pages))
    assert len(pages) >= 2
    assert sum("DecreeHolderAdvocate" in compact(page) for page in pages) == 1
    persisted = client.get(base, headers=headers)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["current_version_id"] == current["id"]
    assert persisted.json()["versions"][0] == original
