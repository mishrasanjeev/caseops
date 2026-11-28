"""ENH-001 review round 2: what the public verification page may vouch for.

* A draft, or an outside-counsel submission the firm has not approved, is not
  an issued document. Its QR code still resolves and still pins the file's
  fingerprint, but the public page must not call it genuine (``not_issued``),
  and a draft copy stays ``not_issued`` after the invoice is issued.
* On an outside-counsel invoice the supplier name, GSTIN and PAN are typed by
  the counsel. The verification response says so, and the portal checks the
  GSTIN and PAN formats on submit (the web form mirrors the same messages).
* Two first-time branding saves racing each other must not 500 on the
  one-row-per-company constraint.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CompanyDocumentBranding,
    InvoiceStatus,
    MatterInvoice,
)
from caseops_api.db.session import get_session_factory
from tests.pdf_legibility import assert_legible
from tests.test_auth_company import auth_headers
from tests.test_bug016_invoice_pdf_legibility import _profile
from tests.test_enh001_branded_billing_documents import (
    _download,
    _invoice,
    _oc_setup,
    _png,
    _submit_oc,
    _upload,
    _verification_link,
)
from tests.test_gba_law_office_prd import _bootstrap, _create_matter

REPO_ROOT = Path(__file__).resolve().parents[3]


def _verify(client: TestClient, pdf: bytes) -> dict:
    _, token = _verification_link(assert_legible(pdf).text)
    client.cookies.clear()
    response = client.get(f"/api/verify/billing-documents/{token}")
    assert response.status_code == 200, response.text
    return response.json()


# --- not-issued copies ------------------------------------------------------------


def test_draft_copy_verifies_as_not_issued_and_stays_so_after_issue(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-draft")
    token = str(boot["access_token"])
    _profile(client, token)
    matter = _create_matter(client, token, "ENH001R2-DRAFT")
    matter_id = str(matter["id"])
    draft = _invoice(client, token, matter_id)
    assert draft["status"] == "draft"
    draft_pdf = _download(client, token, matter_id, draft["id"])
    draft_check = _verify(client, draft_pdf)
    assert draft_check["state"] == "not_issued", "a draft must never verify as genuine"
    assert draft_check["status_at_generation"] == "Draft (not issued)"
    assert draft_check["issuer_supplied_by_counsel"] is False

    issued = client.post(
        f"/api/matters/{matter_id}/invoices/{draft['id']}/issue", headers=auth_headers(token)
    )
    assert issued.status_code == 200, issued.text
    after_issue = _verify(client, draft_pdf)
    assert after_issue["state"] == "not_issued", (
        "the draft copy is still the unsigned, DRAFT-watermarked file after the invoice is issued"
    )
    assert after_issue["current_status"] == "Issued"
    issued_check = _verify(client, _download(client, token, matter_id, draft["id"]))
    assert issued_check["state"] == "valid"


def test_outside_counsel_review_copy_is_not_issued_and_supplier_is_marked_counsel_typed(
    client: TestClient,
) -> None:
    token, matter_id, debug = _oc_setup(client, "enh001r2-oc", "counsel@r2.example")
    record = _submit_oc(
        client, matter_id, debug, "R2/OC/1",
        counsel_firm_name="Khanna Advisory Chambers",
        counsel_gstin="07AAAFK1234Q1Z2",
        counsel_pan="AAAFK1234Q",
    )
    assert record["status"] == "needs_review"
    review = _verify(client, _download(client, token, matter_id, record["id"]))
    assert review["state"] == "not_issued"
    assert review["status_at_generation"] == "Submitted for review (not approved)"
    assert review["issuer_name"] == "Khanna Advisory Chambers"
    assert review["issuer_supplied_by_counsel"] is True

    # Even once the firm treats it as issued, the supplier details remain the
    # counsel's own typing, and the response keeps saying so.
    factory = get_session_factory()
    with factory() as session:
        row = session.get(MatterInvoice, record["id"])
        assert row is not None
        row.status = InvoiceStatus.ISSUED
        session.commit()
    approved = _verify(client, _download(client, token, matter_id, record["id"]))
    assert approved["state"] == "valid"
    assert approved["issuer_supplied_by_counsel"] is True


def test_one_issued_status_set_drives_signature_watermark_and_verification() -> None:
    from caseops_api.services import matter_billing
    from caseops_api.services.billing_document_verification import (
        ISSUED_DOCUMENT_STATUSES,
        is_issued_status,
    )

    assert matter_billing._SIGNED_STATUSES is ISSUED_DOCUMENT_STATUSES
    assert set(ISSUED_DOCUMENT_STATUSES) == {"issued", "partially_paid", "paid"}
    for status in InvoiceStatus:
        if not is_issued_status(status):
            assert matter_billing._status_watermark(status), (
                f"{status} is not issued, so its PDF must carry a status watermark"
            )
    assert matter_billing._status_watermark("some_future_status") == "NOT ISSUED"
    assert matter_billing._status_watermark(InvoiceStatus.ISSUED) is None


# --- counsel GSTIN / PAN on the portal submit path --------------------------------


def _portal_post(client: TestClient, matter_id: str, number: str, **extra: object):
    """Submit through an already signed-in portal session (the magic link is single use)."""
    from tests.test_portal_matters import _portal_csrf_headers

    return client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": number,
            "issued_on": "2026-11-20",
            "currency": "INR",
            "line_items": [{"description": "Appearance", "amount_minor": 100000}],
            **extra,
        },
        headers=_portal_csrf_headers(client),
    )


def _submit_raw(client: TestClient, matter_id: str, debug: str, number: str, **extra: object):
    from tests.test_portal_matters import _verify_and_session

    _verify_and_session(client, debug)
    response = _portal_post(client, matter_id, number, **extra)
    client.cookies.clear()
    return response


def _field_messages(response, field: str) -> list[str]:
    return [
        issue["msg"] for issue in response.json()["errors"] if issue["loc"][-1] == field
    ]


@pytest.mark.parametrize(
    ("extra", "field", "message"),
    [
        ({"counsel_gstin": "07AAAFK1234Q1Z"}, "counsel_gstin", "15-character GSTIN"),
        ({"counsel_gstin": "Not registered"}, "counsel_gstin", "15-character GSTIN"),
        ({"counsel_gstin": "07AAAFK1234Q1A2"}, "counsel_gstin", "15-character GSTIN"),
        ({"counsel_gstin": "45AAAFK1234Q1Z2"}, "counsel_gstin", "valid GST state code"),
        ({"counsel_gstin": "00AAAFK1234Q1Z2"}, "counsel_gstin", "valid GST state code"),
        ({"counsel_pan": "AAAF1234Q"}, "counsel_pan", "10-character PAN"),
        ({"counsel_pan": "12345ABCDE"}, "counsel_pan", "10-character PAN"),
        (
            {"counsel_gstin": "07AAAFK1234Q1Z2", "counsel_pan": "BBBFK1234Q"},
            "counsel_pan",
            "must match characters 3 to 12 of the GSTIN",
        ),
    ],
)
def test_portal_rejects_malformed_counsel_gstin_and_pan(
    client: TestClient, extra: dict, field: str, message: str
) -> None:
    _, matter_id, debug = _oc_setup(client, "enh001r2-ids", "ids@r2.example")
    response = _submit_raw(client, matter_id, debug, "R2-IDS-1", **extra)
    assert response.status_code == 422, response.text
    messages = _field_messages(response, field)
    assert messages and message in messages[0], response.text


def test_portal_normalises_spaced_lowercase_counsel_ids(client: TestClient) -> None:
    from tests.test_portal_matters import _verify_and_session

    _, matter_id, debug = _oc_setup(client, "enh001r2-norm", "norm@r2.example")
    _verify_and_session(client, debug)
    response = _portal_post(
        client, matter_id, "R2-NORM-1",
        counsel_gstin=" 07 aaafk1234q 1z2 ", counsel_pan="aaafk 1234q",
    )
    assert response.status_code == 201, response.text
    assert response.json()["counsel_gstin"] == "07AAAFK1234Q1Z2"
    assert response.json()["counsel_pan"] == "AAAFK1234Q"
    blank = _portal_post(client, matter_id, "R2-NORM-2", counsel_gstin="  ", counsel_pan="")
    assert blank.status_code == 201, blank.text
    assert blank.json()["counsel_gstin"] is None


def test_web_tax_identifier_mirror_matches_the_api() -> None:
    from caseops_api.services import matter_billing

    source = (REPO_ROOT / "apps/web/lib/tax-identifiers.ts").read_text(encoding="utf-8")
    flattened = re.sub(r'"\s*\+\s*"', "", source)
    for name in (
        "GSTIN_FORMAT_MESSAGE",
        "GSTIN_STATE_MESSAGE",
        "PAN_FORMAT_MESSAGE",
        "PAN_GSTIN_MISMATCH_MESSAGE",
    ):
        assert f'"{getattr(matter_billing, name)}"' in flattened, name
    listed = re.search(r"GSTIN_STATE_CODES[^=]*=\s*\[(.*?)\]", source, re.S)
    assert listed is not None
    assert set(re.findall(r'"(\d{2})"', listed.group(1))) == set(matter_billing.GSTIN_STATE_CODES)
    assert matter_billing._GSTIN_PATTERN.pattern in source
    assert matter_billing._PAN_PATTERN.pattern in source


# --- race-safe first branding save ------------------------------------------------


def _race_first_branding_save(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit a competing first row between the existence check and the insert."""

    from caseops_api.services import document_branding

    original = document_branding._row
    raced = {"done": False}

    def racing_row(session, company_id):
        if not raced["done"]:
            raced["done"] = True
            with get_session_factory()() as other:
                other.add(
                    CompanyDocumentBranding(
                        company_id=company_id, signatory_name="Concurrent Admin"
                    )
                )
                other.commit()
            return None
        return original(session, company_id)

    monkeypatch.setattr(document_branding, "_row", racing_row)


def _branding_rows(company_id: str) -> list[CompanyDocumentBranding]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(CompanyDocumentBranding).where(
                    CompanyDocumentBranding.company_id == company_id
                )
            )
        )


def test_racing_first_branding_patch_updates_the_winner_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-race-patch")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    _race_first_branding_save(monkeypatch)
    response = client.patch(
        "/api/admin/document-branding",
        headers=auth_headers(token),
        json={"signatory_designation": "Managing Partner"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["signatory_name"] == "Concurrent Admin"
    assert response.json()["signatory_designation"] == "Managing Partner"
    rows = _branding_rows(company_id)
    assert len(rows) == 1
    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "document_branding.updated",
            )
        )
        assert audit is not None and audit.target_id == rows[0].id


def test_racing_first_branding_upload_updates_the_winner_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-race-upload")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    _race_first_branding_save(monkeypatch)
    response = _upload(
        client, token, "logo", "logo.png", _png(400, 200, (10, 40, 90)), "image/png"
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_logo"] is True
    assert response.json()["signatory_name"] == "Concurrent Admin"
    rows = _branding_rows(company_id)
    assert len(rows) == 1 and rows[0].logo_storage_key is not None


# --- text the PDF cannot print is refused when saved, not on every download ---------


@pytest.mark.parametrize(
    "patch",
    [
        {"watermark_text": "MEHTA \U0001f642"},
        {"watermark_text": "漢字 LEGAL"},
        {"signatory_name": "Anil \U0001f642 Mehta"},
        # Tamil: the pinned PDF fonts cover Latin and Devanagari only.
        {"signatory_designation": "பங்காளர்"},
    ],
)
def test_branding_text_the_pdf_cannot_print_is_refused_and_invoices_still_download(
    client: TestClient, patch: dict
) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-glyph")
    token = str(boot["access_token"])
    _profile(client, token)
    refused = client.patch(
        "/api/admin/document-branding", headers=auth_headers(token), json=patch
    )
    assert refused.status_code == 422, refused.text
    field = next(iter(patch))
    messages = _field_messages(refused, field)
    assert messages and "cannot be printed on billing PDFs" in messages[0], refused.text
    record = client.get("/api/admin/document-branding", headers=auth_headers(token)).json()
    assert record[field] is None, "nothing was saved"
    glyph_matter_code = "ENH001R2-GLYPH"
    matter = _create_matter(client, token, glyph_matter_code)
    invoice = _invoice(client, token, str(matter["id"]), status="issued")
    assert _download(client, token, str(matter["id"]), invoice["id"]).startswith(b"%PDF")


def test_branding_indic_text_the_pdf_can_print_is_still_accepted(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-indic")
    token = str(boot["access_token"])
    accepted = client.patch(
        "/api/admin/document-branding",
        headers=auth_headers(token),
        json={"signatory_name": "अनिल मेहता",
              "watermark_text": "Mehta & Co. — ₹"},
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.parametrize("field", ["counsel_firm_name", "counsel_address"])
def test_portal_refuses_counsel_supplier_text_the_pdf_cannot_print(
    client: TestClient, field: str
) -> None:
    from tests.test_portal_matters import _verify_and_session

    token, matter_id, debug = _oc_setup(client, "enh001r2-ocglyph", "glyph@r2.example")
    _verify_and_session(client, debug)
    refused = _portal_post(
        client, matter_id, "R2-GLYPH-1", **{field: "Khanna \U0001f642 Chambers"}
    )
    assert refused.status_code == 422, refused.text
    messages = _field_messages(refused, field)
    assert messages and "cannot be printed on billing PDFs" in messages[0], refused.text
    accepted = _portal_post(
        client, matter_id, "R2-GLYPH-2",
        counsel_firm_name="Khanna Advisory Chambers",
        counsel_address="14 Lawyers Chambers\nSaket Court, New Delhi 110017",
    )
    assert accepted.status_code == 201, accepted.text
    client.cookies.clear()
    assert _download(client, token, matter_id, accepted.json()["id"]).startswith(b"%PDF")


# --- malformed images never reach a 500 -------------------------------------------


def _image_bytes(mode: str, size: tuple[int, int], fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "mime", "expected"),
    [
        ("logo.png", _image_bytes("I;16", (200, 100), "PNG"), "image/png", 200),
        ("logo.png", _image_bytes("LA", (200, 100), "PNG"), "image/png", 200),
        ("logo.png", _image_bytes("1", (200, 100), "PNG"), "image/png", 200),
        ("logo.png", _image_bytes("P", (200, 100), "PNG"), "image/png", 200),
        ("logo.jpg", _image_bytes("CMYK", (200, 100), "JPEG"), "image/jpeg", 200),
        ("logo.png", _png(300, 150, (1, 2, 3))[:200], "image/png", 400),
        ("logo.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 200, "image/jpeg", 400),
    ],
)
def test_unusual_or_truncated_images_are_stored_or_refused_never_500(
    client: TestClient, name: str, data: bytes, mime: str, expected: int
) -> None:
    boot = _bootstrap(client, slug_seed="enh001r2-img")
    token = str(boot["access_token"])
    response = _upload(client, token, "logo", name, data, mime)
    assert response.status_code == expected, response.text
    if expected == 200:
        stored = client.get("/api/admin/document-branding/logo", headers=auth_headers(token))
        assert stored.content.startswith(b"\x89PNG")
    else:
        assert "could not be read as an image" in response.text
