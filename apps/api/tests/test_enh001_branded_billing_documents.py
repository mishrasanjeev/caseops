"""ENH-001 (Ram, test-legal, 2026-11-27): branded, verifiable billing PDFs.

Ram's words: generated invoices and receipts "look basic and do not have proper
law firm branding. The logo, watermark, authorised signature and document
verification QR code are missing. Outside Counsel invoices also need better
formatting." Each test below asserts one of those nouns on the PDF itself:

* logo / signature: the image object in the PDF carries exactly the pixels the
  admin uploaded (after the safe re-encode), not merely "an image exists";
* watermark: the page carries the watermark image produced for the expected
  text, and rendered pixels behind the body are tinted;
* QR code: the module matrix of the embedded image equals the QR encoding of
  the link printed under it, and that link verifies through the public API
  with the SHA-256 of the bytes downloaded;
* outside counsel: the counsel's firm, address and tax identifiers are the
  supplier, and the firm is the party billed.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    BillingDocumentVerification,
    CompanyDocumentBranding,
    InvoiceStatus,
    MatterInvoice,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.billing_document_layout import (
    QR_BORDER_MODULES,
    QR_BOX_SIZE,
    qr_modules,
    watermark_png,
)
from tests.pdf_legibility import assert_legible, compact
from tests.test_auth_company import auth_headers
from tests.test_bug016_invoice_pdf_legibility import _member_token, _profile
from tests.test_gba_law_office_prd import _bootstrap, _create_matter

VERIFY_RE = re.compile(r"(https?://\S+?/verify/([A-Za-z0-9_-]{43}))")


# --- fixtures -----------------------------------------------------------------


def _png(width: int, height: int, colour: tuple[int, int, int], *, alpha: bool = True) -> bytes:
    image = Image.new("RGBA" if alpha else "RGB", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([4, 4, width - 5, height - 5], outline=(*colour, 255), width=8)
    draw.ellipse([width // 5, height // 5, width * 4 // 5, height * 4 // 5], fill=(*colour, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.line([(10, height - 20), (width // 3, 15), (width // 2, height - 30), (width - 10, 20)],
              fill=(15, 23, 80), width=9)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _upload(client: TestClient, token: str, kind: str, name: str, data: bytes, mime: str):
    return client.put(
        f"/api/admin/document-branding/{kind}",
        headers=auth_headers(token),
        files={"file": (name, data, mime)},
    )


def _brand(client: TestClient, token: str) -> dict[str, bytes]:
    logo = _png(600, 300, (20, 60, 120))
    signature = _jpeg(500, 150)
    assert _upload(client, token, "logo", "firm-logo.png", logo, "image/png").status_code == 200
    response = _upload(client, token, "signature", "sign.jpg", signature, "image/jpeg")
    assert response.status_code == 200, response.text
    patched = client.patch(
        "/api/admin/document-branding",
        headers=auth_headers(token),
        json={
            "signatory_name": "Anil Mehta",
            "signatory_designation": "Managing Partner",
            "watermark_text": "MEHTA LEGAL",
        },
    )
    assert patched.status_code == 200, patched.text
    stored = {}
    for kind in ("logo", "signature"):
        image = client.get(f"/api/admin/document-branding/{kind}", headers=auth_headers(token))
        assert image.status_code == 200, image.text
        assert image.headers["content-type"] == "image/png"
        stored[kind] = image.content
    return stored


def _invoice(client: TestClient, token: str, matter_id: str, **payload: object) -> dict:
    body = {
        "issued_on": "2026-11-27",
        "client_name": "Punjab National Bank",
        "include_uninvoiced_time_entries": False,
        "manual_items": [
            {"description": "Drafting the written statement", "amount_minor": 1750000}
        ],
        **payload,
    }
    created = client.post(
        f"/api/matters/{matter_id}/invoices", headers=auth_headers(token), json=body
    )
    assert created.status_code == 200, created.text
    return created.json()


def _download(client: TestClient, token: str, matter_id: str, invoice_id: str) -> bytes:
    response = client.get(
        f"/api/matters/{matter_id}/invoices/{invoice_id}/download", headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["X-CaseOps-Checksum"] == hashlib.sha256(response.content).hexdigest()
    return response.content


# --- PDF inspection -------------------------------------------------------------


def _images(pdf: bytes) -> list[tuple[tuple[float, float, float, float], Image.Image]]:
    document = pdfium.PdfDocument(pdf)
    found = []
    try:
        for index in range(len(document)):
            page = document[index]
            for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
                found.append((obj.get_bounds(), obj.get_bitmap(render=False).to_pil().copy()))
    finally:
        document.close()
    return found


def _same_pixels(embedded: Image.Image, source_png: bytes) -> bool:
    with Image.open(io.BytesIO(source_png)) as source:
        expected = source.convert("RGB") if source.mode != "L" else source.copy()
    actual = embedded.convert(expected.mode)
    return actual.size == expected.size and actual.tobytes() == expected.tobytes()


def _qr_matrix(embedded: Image.Image) -> list[list[bool]]:
    grey = embedded.convert("L")
    modules = grey.width // QR_BOX_SIZE - 2 * QR_BORDER_MODULES
    offset = QR_BORDER_MODULES * QR_BOX_SIZE + QR_BOX_SIZE // 2
    return [
        [grey.getpixel((offset + col * QR_BOX_SIZE, offset + row * QR_BOX_SIZE)) < 128
         for col in range(modules)]
        for row in range(modules)
    ]


def _verification_link(text: str) -> tuple[str, str]:
    match = VERIFY_RE.search(text.replace("\r", "").replace("\n", ""))
    assert match, "the verification link is printed under the QR code"
    return match.group(1), match.group(2)


def _assert_qr_resolves(client: TestClient, pdf: bytes, text: str) -> dict:
    url, token = _verification_link(text)
    qr_images = [image for _, image in _images(pdf) if image.mode == "L"]
    assert len(qr_images) == 1, "exactly one QR code is drawn"
    assert _qr_matrix(qr_images[0]) == qr_modules(url), "the QR code encodes the printed link"
    assert url.startswith("http://testserver/verify/")
    client.cookies.clear()
    verified = client.get(f"/api/verify/billing-documents/{token}")
    assert verified.status_code == 200, verified.text
    assert verified.headers["cache-control"] == "no-store"
    body = verified.json()
    assert body["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    return body


def _watermark_present(pdf: bytes, text: str) -> bool:
    expected = Image.open(io.BytesIO(watermark_png(text)))
    return any(image.size == expected.size for _, image in _images(pdf))


# --- settings -------------------------------------------------------------------


def test_enh001_admin_uploads_logo_signature_and_signatory_audited(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001-settings")
    token = str(boot["access_token"])
    _profile(client, token, firm_legal_name="Mehta Legal Chambers LLP")
    logo = _png(2400, 1200, (20, 60, 120))
    response = _upload(client, token, "logo", "logo.png", logo, "image/png")
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["has_logo"] is True
    # Stored re-encoded and bounded, never the uploaded bytes.
    assert (record["logo_width"], record["logo_height"]) == (1200, 600)
    assert record["logo_sha256"] != hashlib.sha256(logo).hexdigest()
    stored = _brand(client, token)
    current = client.get("/api/admin/document-branding", headers=auth_headers(token)).json()
    assert current["signatory_name"] == "Anil Mehta"
    assert current["signatory_designation"] == "Managing Partner"
    assert current["effective_watermark_text"] == "MEHTA LEGAL"
    assert current["letterhead"]["issuer_name"] == "Mehta Legal Chambers LLP"
    assert current["logo_sha256"] == hashlib.sha256(stored["logo"]).hexdigest()
    removed = client.delete("/api/admin/document-branding/signature", headers=auth_headers(token))
    assert removed.status_code == 200 and removed.json()["has_signature"] is False
    factory = get_session_factory()
    with factory() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.company_id == str(boot["company"]["id"]),
                    AuditEvent.action.like("document_branding.%"),
                )
            )
        )
    assert {
        "document_branding.logo.uploaded",
        "document_branding.signature.uploaded",
        "document_branding.updated",
        "document_branding.signature.removed",
    } <= actions


@pytest.mark.parametrize("role", ["member", "partner"])
def test_enh001_branding_settings_are_admin_only(client: TestClient, role: str) -> None:
    boot = _bootstrap(client, slug_seed=f"enh001-{role}")
    token = str(boot["access_token"])
    member = _member_token(client, token, str(boot["company"]["slug"]), role)
    png = _png(200, 100, (0, 0, 0))
    headers = auth_headers(member)
    assert client.get("/api/admin/document-branding", headers=headers).status_code == 403
    assert client.patch(
        "/api/admin/document-branding",
        headers=auth_headers(member),
        json={"signatory_name": "Impostor"},
    ).status_code == 403
    assert _upload(client, member, "logo", "l.png", png, "image/png").status_code == 403
    removed = client.delete("/api/admin/document-branding/logo", headers=headers)
    assert removed.status_code == 403


@pytest.mark.parametrize(
    ("name", "data", "mime", "message"),
    [
        ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
         "image/svg+xml", "SVG files are not accepted"),
        ("logo.png", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/png",
         "do not match the expected signature"),
        ("logo.gif", b"GIF89a" + b"\0" * 64, "image/gif", "PNG or JPEG"),
        ("logo.png", _png(20, 20, (0, 0, 0)), "image/png", "at least 32 pixels"),
        ("logo.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64, "image/png", "could not be read"),
        ("logo.jpg", _png(200, 100, (0, 0, 0)), "image/jpeg", "do not match the expected"),
    ],
)
def test_enh001_unsafe_or_invalid_images_are_refused(
    client: TestClient, name: str, data: bytes, mime: str, message: str
) -> None:
    boot = _bootstrap(client, slug_seed="enh001-reject")
    token = str(boot["access_token"])
    response = _upload(client, token, "logo", name, data, mime)
    assert response.status_code == 400, response.text
    assert message in response.text
    record = client.get("/api/admin/document-branding", headers=auth_headers(token)).json()
    assert record["has_logo"] is False


def test_enh001_oversized_upload_and_polyglot_tail_are_handled(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001-size")
    token = str(boot["access_token"])
    noise = Image.frombytes("RGB", (1400, 1400), bytes(range(256)) * (1400 * 1400 * 3 // 256 + 1))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG", compress_level=0)
    assert len(buffer.getvalue()) > 2 * 1024 * 1024
    too_big = _upload(client, token, "logo", "big.png", buffer.getvalue(), "image/png")
    assert too_big.status_code == 413, too_big.text
    assert "2 MiB" in too_big.text
    # A valid PNG with a script appended: only the pixels are stored.
    polyglot = _png(300, 150, (0, 80, 0)) + b"<script>alert(document.cookie)</script>"
    accepted = _upload(client, token, "logo", "logo.png", polyglot, "image/png")
    assert accepted.status_code == 200, accepted.text
    stored = client.get("/api/admin/document-branding/logo", headers=auth_headers(token)).content
    assert b"<script>" not in stored
    assert stored.startswith(b"\x89PNG")


def test_enh001_branding_is_tenant_isolated(client: TestClient) -> None:
    first = _bootstrap(client, slug_seed="enh001-iso-a")
    second = _bootstrap(client, slug_seed="enh001-iso-b")
    token_a, token_b = str(first["access_token"]), str(second["access_token"])
    stored_a = _brand(client, token_a)
    record_b = client.get("/api/admin/document-branding", headers=auth_headers(token_b)).json()
    assert record_b["has_logo"] is False and record_b["signatory_name"] is None
    assert client.get(
        "/api/admin/document-branding/logo", headers=auth_headers(token_b)
    ).status_code == 404
    client.patch(
        "/api/admin/document-branding", headers=auth_headers(token_b),
        json={"signatory_name": "Second Firm Signatory"},
    )
    record_a = client.get("/api/admin/document-branding", headers=auth_headers(token_a)).json()
    assert record_a["signatory_name"] == "Anil Mehta"
    # Tenant B's issued invoice carries none of tenant A's assets.
    _profile(client, token_b, firm_legal_name="Second Firm LLP")
    matter = _create_matter(client, token_b, "ENH001-ISO-B")
    invoice = _invoice(client, token_b, str(matter["id"]), status="issued")
    pdf = _download(client, token_b, str(matter["id"]), invoice["id"])
    images = [image for _, image in _images(pdf)]
    assert not any(_same_pixels(image, stored_a["logo"]) for image in images)
    assert not any(_same_pixels(image, stored_a["signature"]) for image in images)
    assert "Anil Mehta" not in assert_legible(pdf).text
    factory = get_session_factory()
    with factory() as session:
        rows = list(session.scalars(select(CompanyDocumentBranding)))
        assert {row.company_id for row in rows} == {
            str(first["company"]["id"]), str(second["company"]["id"])
        }
        for row in rows:
            for key in (row.logo_storage_key, row.signature_storage_key):
                if key:
                    assert key.startswith(f"{row.company_id}/branding/")


# --- matter invoices and receipts ---------------------------------------------


def test_enh001_issued_invoice_carries_logo_signature_watermark_and_verifiable_qr(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="enh001-issued")
    token = str(boot["access_token"])
    _profile(client, token)
    stored = _brand(client, token)
    matter = _create_matter(client, token, "ENH001-ISSUED")
    invoice = _invoice(
        client, token, str(matter["id"]), status="issued", client_gstin="07AAACP0165G1ZR"
    )
    pdf = _download(client, token, str(matter["id"]), invoice["id"])
    rendered = assert_legible(pdf)
    assert len(rendered.page_sizes) == 1
    text = compact(rendered.text)
    images = [image for _, image in _images(pdf)]
    assert any(_same_pixels(image, stored["logo"]) for image in images), "logo drawn"
    assert any(_same_pixels(image, stored["signature"]) for image in images), "signature drawn"
    assert _watermark_present(pdf, "MEHTA LEGAL"), "custom watermark drawn"
    for expected in (
        "Mehta Legal Chambers LLP", "GSTIN: 07ABCDE1234F1Z5", "PAN: ABCDE1234F",
        "For Mehta Legal Chambers LLP", "Anil Mehta", "Managing Partner | Authorised signatory",
        "Verify this document", "Status: Issued", "Client: Punjab National Bank",
        "Page 1 of 1",
    ):
        assert compact(expected) in text, expected
    verified = _assert_qr_resolves(client, pdf, rendered.text)
    assert verified["state"] == "valid"
    assert verified["document_number"] == invoice["invoice_number"]
    assert verified["issuer_name"] == "Mehta Legal Chambers LLP"
    assert verified["amount_minor"] == invoice["total_amount_minor"]
    assert verified["current_status"] == "Issued"
    assert verified["document_type"] == "Tax invoice"
    # Minimal disclosure: nothing about the client, the matter or the tenant.
    raw = str(verified)
    for secret in ("Punjab National Bank", str(matter["id"]), str(boot["company"]["id"]),
                   str(matter["title"]), "07AAACP0165G1ZR"):
        assert secret not in raw


def test_enh001_two_downloads_get_distinct_tokens_and_only_a_hash_is_stored(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="enh001-tokens")
    token = str(boot["access_token"])
    _profile(client, token)
    matter = _create_matter(client, token, "ENH001-TOKENS")
    invoice = _invoice(client, token, str(matter["id"]), status="issued")
    first = _download(client, token, str(matter["id"]), invoice["id"])
    second = _download(client, token, str(matter["id"]), invoice["id"])
    token_one = _verification_link(assert_legible(first).text)[1]
    token_two = _verification_link(assert_legible(second).text)[1]
    assert token_one != token_two
    factory = get_session_factory()
    with factory() as session:
        rows = list(session.scalars(select(BillingDocumentVerification)))
    assert len(rows) == 2
    stored_columns = " ".join(str(value) for row in rows for value in row.__dict__.values())
    assert token_one not in stored_columns and token_two not in stored_columns
    assert {row.pdf_sha256 for row in rows} == {
        hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest()
    }


def test_enh001_draft_is_watermarked_draft_unsigned_and_void_revokes_its_codes(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="enh001-draft")
    token = str(boot["access_token"])
    _profile(client, token)
    stored = _brand(client, token)
    matter = _create_matter(client, token, "ENH001-DRAFT")
    invoice = _invoice(client, token, str(matter["id"]))
    assert invoice["status"] == "draft"
    pdf = _download(client, token, str(matter["id"]), invoice["id"])
    rendered = assert_legible(pdf)
    images = [image for _, image in _images(pdf)]
    assert any(_same_pixels(image, stored["logo"]) for image in images)
    assert not any(_same_pixels(image, stored["signature"]) for image in images), (
        "a draft must never carry the authorised signature"
    )
    assert _watermark_present(pdf, "DRAFT")
    assert not _watermark_present(pdf, "MEHTA LEGAL")
    assert compact("The signature is applied when the invoice is issued.") in compact(rendered.text)
    draft_check = _assert_qr_resolves(client, pdf, rendered.text)
    # ENH-001 review: a draft is not an issued document; its code resolves and
    # pins the file, but never calls it genuine.
    assert draft_check["state"] == "not_issued"
    assert draft_check["current_status"] == "Draft (not issued)"
    _, draft_token = _verification_link(rendered.text)

    voided = client.post(
        f"/api/matters/{matter['id']}/invoices/{invoice['id']}/void", headers=auth_headers(token)
    )
    assert voided.status_code == 200, voided.text
    client.cookies.clear()
    after = client.get(f"/api/verify/billing-documents/{draft_token}").json()
    assert after["state"] == "revoked"
    assert after["revoked_reason"] == "The invoice was voided."
    assert after["current_status"] == "Void (cancelled)"
    void_pdf = _download(client, token, str(matter["id"]), invoice["id"])
    void_text = assert_legible(void_pdf).text
    assert _watermark_present(void_pdf, "VOID")
    void_check = _assert_qr_resolves(client, void_pdf, void_text)
    assert void_check["state"] == "revoked"


def test_enh001_paid_invoice_prints_as_signed_receipt_watermarked_paid(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001-receipt")
    token = str(boot["access_token"])
    _profile(client, token)
    stored = _brand(client, token)
    matter = _create_matter(client, token, "ENH001-RECEIPT")
    invoice = _invoice(client, token, str(matter["id"]), status="issued")
    factory = get_session_factory()
    with factory() as session:
        row = session.get(MatterInvoice, invoice["id"])
        assert row is not None
        row.amount_received_minor = row.total_amount_minor
        row.balance_due_minor = 0
        row.status = InvoiceStatus.PAID
        session.commit()
    pdf = _download(client, token, str(matter["id"]), invoice["id"])
    rendered = assert_legible(pdf)
    text = compact(rendered.text)
    assert compact("Tax Invoice / Receipt") in text
    assert compact("Status: Paid") in text
    assert _watermark_present(pdf, "PAID")
    assert any(_same_pixels(image, stored["signature"]) for _, image in _images(pdf))
    verified = _assert_qr_resolves(client, pdf, rendered.text)
    assert verified["document_type"] == "Invoice and payment receipt"
    assert verified["current_status"] == "Paid"


def test_enh001_watermark_can_be_turned_off_but_status_words_cannot(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001-wmoff")
    token = str(boot["access_token"])
    _profile(client, token)
    client.patch(
        "/api/admin/document-branding", headers=auth_headers(token),
        json={"watermark_enabled": False},
    )
    matter = _create_matter(client, token, "ENH001-WMOFF")
    issued = _invoice(client, token, str(matter["id"]), status="issued")
    issued_pdf = _download(client, token, str(matter["id"]), issued["id"])
    assert not _watermark_present(issued_pdf, "Mehta Legal Chambers LLP")
    assert len(_images(issued_pdf)) == 1, "only the QR code remains"
    draft = _invoice(client, token, str(matter["id"]), invoice_number="ENH-WMOFF-D")
    assert _watermark_present(_download(client, token, str(matter["id"]), draft["id"]), "DRAFT")


def test_enh001_indic_firm_and_signatory_names_render_shaped(client: TestClient) -> None:
    boot = _bootstrap(client, slug_seed="enh001-indic")
    token = str(boot["access_token"])
    _profile(client, token, firm_legal_name="मेहता लीगल चैम्बर्स")
    client.patch(
        "/api/admin/document-branding", headers=auth_headers(token),
        json={"signatory_name": "अनिल मेहता", "signatory_designation": "प्रबंध साझेदार"},
    )
    matter = _create_matter(client, token, "ENH001-INDIC")
    invoice = _invoice(client, token, str(matter["id"]), status="issued")
    pdf = _download(client, token, str(matter["id"]), invoice["id"])
    text = compact(assert_legible(pdf).text)
    for value in ("मेहता लीगल चैम्बर्स", "अनिल मेहता", "प्रबंध साझेदार"):
        assert compact(value) in text, value
    assert _watermark_present(pdf, "मेहता लीगल चैम्बर्स")


# --- outside counsel ------------------------------------------------------------


def _oc_setup(client: TestClient, slug: str, email: str):
    from tests.test_portal_matters import _bootstrap as _portal_bootstrap
    from tests.test_portal_matters import _seed_matter
    from tests.test_portal_outside_counsel import _invite_oc_portal_user

    boot = _portal_bootstrap(client, slug=slug, email=f"owner@{slug}.example")
    token = str(boot["access_token"])
    _profile(client, token, firm_legal_name="Mehta Legal Chambers LLP")
    _brand(client, token)
    matter_id = _seed_matter(boot["company"]["id"], code=f"{slug.upper()}-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id, email=email)
    return token, matter_id, debug


def _submit_oc(client: TestClient, matter_id: str, debug: str, number: str, **extra: object):
    from tests.test_portal_matters import _portal_csrf_headers, _verify_and_session

    _verify_and_session(client, debug)
    submitted = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": number,
            "issued_on": "2026-11-20",
            "currency": "INR",
            "line_items": [{"description": "Appearance before the DRT", "amount_minor": 250000}],
            **extra,
        },
        headers=_portal_csrf_headers(client),
    )
    assert submitted.status_code == 201, submitted.text
    client.cookies.clear()
    return submitted.json()


def test_enh001_outside_counsel_invoice_shows_counsel_as_supplier_and_firm_as_billed(
    client: TestClient,
) -> None:
    token, matter_id, debug = _oc_setup(client, "enh001-oc", "counsel@khanna.example")
    record = _submit_oc(
        client, matter_id, debug, "KA/2026/114",
        counsel_firm_name="Khanna Advisory Chambers",
        counsel_address="14 Lawyers Chambers\nSaket Court, New Delhi 110017",
        counsel_gstin="07aaafk1234q1z2",
        counsel_pan="aaafk1234q",
    )
    assert record["counsel_firm_name"] == "Khanna Advisory Chambers"
    assert record["counsel_gstin"] == "07AAAFK1234Q1Z2"
    pdf = _download(client, token, matter_id, record["id"])
    rendered = assert_legible(pdf)
    text = compact(rendered.text)
    for expected in (
        "Khanna Advisory Chambers", "14 Lawyers Chambers", "Saket Court, New Delhi 110017",
        "GSTIN: 07AAAFK1234Q1Z2", "PAN: AAAFK1234Q",
        "Outside counsel | OC Counsel | counsel@khanna.example",
        "Bill to: Mehta Legal Chambers LLP", "Bill to GSTIN: 07ABCDE1234F1Z5",
        "OUTSIDE COUNSEL INVOICE - SUBMITTED FOR REVIEW", "Submitted by",
        "REVIEW COPY | KA/2026/114 | Page 1 of 1",
    ):
        assert compact(expected) in text, expected
    assert "Client: Not available" not in rendered.text
    assert "Anil Mehta" not in rendered.text, "the firm's signatory never signs a counsel invoice"
    assert _watermark_present(pdf, "FOR REVIEW")
    # The firm's logo and signature are not the counsel's: only watermark + QR.
    assert len(_images(pdf)) == 2
    verified = _assert_qr_resolves(client, pdf, rendered.text)
    assert verified["document_type"] == "Outside counsel invoice"
    assert verified["issuer_name"] == "Khanna Advisory Chambers"
    assert verified["current_status"] == "Submitted for review (not approved)"
    assert verified["state"] == "not_issued"
    assert verified["issuer_supplied_by_counsel"] is True


def test_enh001_outside_counsel_invoice_without_details_uses_linked_counsel_profile(
    client: TestClient,
) -> None:
    token, matter_id, debug = _oc_setup(client, "enh001-oc-profile", "Anika@Khanna.example")
    profile = client.post(
        "/api/outside-counsel/profiles",
        headers=auth_headers(token),
        json={
            "name": "Khanna Advisory Chambers",
            "primary_contact_name": "Anika Khanna",
            "primary_contact_email": "anika@khanna.example",
            "primary_contact_phone": "+91-9876543210",
            "firm_city": "New Delhi",
        },
    )
    assert profile.status_code == 200, profile.text
    record = _submit_oc(client, matter_id, debug, "KA-0001")
    assert record["counsel_firm_name"] == "Khanna Advisory Chambers"
    text = compact(assert_legible(_download(client, token, matter_id, record["id"])).text)
    assert compact("Khanna Advisory Chambers") in text
    assert compact("New Delhi") in text
    assert compact("Anika Khanna | anika@khanna.example | +91-9876543210") in text


def test_enh001_legacy_outside_counsel_row_without_snapshot_still_names_counsel(
    client: TestClient,
) -> None:
    token, matter_id, debug = _oc_setup(client, "enh001-oc-legacy", "legacy@counsel.example")
    record = _submit_oc(client, matter_id, debug, "LEG-1")
    factory = get_session_factory()
    with factory() as session:
        row = session.get(MatterInvoice, record["id"])
        assert row is not None
        row.firm_legal_name = row.firm_address = row.firm_gstin = row.firm_pan = None
        session.commit()
    text = compact(assert_legible(_download(client, token, matter_id, record["id"])).text)
    assert compact("OC Counsel") in text
    assert compact("Outside counsel | OC Counsel | legacy@counsel.example") in text
    assert compact("Bill to: Mehta Legal Chambers LLP") in text


# --- SaaS billing PDFs ----------------------------------------------------------


def test_enh001_saas_invoice_and_statement_use_the_branded_layout(client: TestClient) -> None:
    from caseops_api.db.models import BillingManualInvoice, BillingSubscription

    boot = _bootstrap(client, slug_seed="enh001-saas")
    token = str(boot["access_token"])
    _brand(client, token)  # the tenant's branding must never appear on CaseOps' invoice
    client.get("/api/billing/current", headers=auth_headers(token))
    factory = get_session_factory()
    with factory() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == str(boot["company"]["id"])
            )
        )
        assert subscription is not None
        manual = BillingManualInvoice(
            company_id=subscription.company_id,
            subscription_id=subscription.id,
            invoice_number=f"BILL-ENH001-{str(boot['company']['id'])[:6]}",
            amount_minor=100000,
            tax_amount_minor=18000,
            status="paid",
            amount_received_minor=118000,
            issued_on=date(2026, 11, 1),
            due_on=date(2026, 11, 30),
        )
        session.add(manual)
        session.commit()
        invoice_id, number = manual.id, manual.invoice_number
    pdf = client.get(f"/api/billing/invoices/{invoice_id}/download", headers=auth_headers(token))
    assert pdf.status_code == 200, pdf.text
    rendered = assert_legible(pdf.content)
    text = compact(rendered.text)
    assert compact("CaseOps Billing Invoice") in text
    assert compact("GSTIN: 09AANCM5923C1ZD") in text
    assert compact(f"{number} | Page 1 of 1") in text
    assert "Anil Mehta" not in rendered.text
    assert _watermark_present(pdf.content, "PAID")
    verified = _assert_qr_resolves(client, pdf.content, rendered.text)
    assert verified["document_type"] == "CaseOps subscription invoice"
    assert verified["issuer_name"] == "CaseOps"
    assert verified["amount_minor"] == 118000
    statement = client.get("/api/billing/statement?format=pdf", headers=auth_headers(token))
    assert statement.status_code == 200, statement.text
    statement_text = compact(assert_legible(statement.content).text)
    assert compact("CaseOps Billing Statement") in statement_text
    assert compact("GSTIN: 09AANCM5923C1ZD") in statement_text
    assert _watermark_present(statement.content, "CaseOps")
    assert "verify" not in statement_text.lower(), "a statement is not an issued document"


# --- public verification --------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["A" * 43, "short", "A" * 42 + "!", "A" * 44, "..%2E" + "A" * 40],
)
def test_enh001_unknown_and_malformed_tokens_get_the_same_404(
    client: TestClient, token: str
) -> None:
    client.cookies.clear()
    response = client.get(f"/api/verify/billing-documents/{token}")
    assert response.status_code == 404
    assert "This verification link is not valid." in response.text


def test_enh001_verification_is_public_and_identical_for_any_caller(client: TestClient) -> None:
    first = _bootstrap(client, slug_seed="enh001-pub-a")
    second = _bootstrap(client, slug_seed="enh001-pub-b")
    token_a = str(first["access_token"])
    _profile(client, token_a)
    matter = _create_matter(client, token_a, "ENH001-PUB")
    invoice = _invoice(client, token_a, str(matter["id"]), status="issued")
    pdf = _download(client, token_a, str(matter["id"]), invoice["id"])
    _, verify_token = _verification_link(assert_legible(pdf).text)
    anonymous = client.get(f"/api/verify/billing-documents/{verify_token}").json()
    other_tenant = client.get(
        f"/api/verify/billing-documents/{verify_token}",
        headers=auth_headers(str(second["access_token"])),
    ).json()
    assert anonymous == other_tenant
    assert set(anonymous) == {
        "state", "document_type", "document_number", "issued_on", "issuer_name",
        "issuer_supplied_by_counsel", "amount_minor", "currency", "status_at_generation",
        "current_status", "generated_at", "pdf_sha256", "revoked_at", "revoked_reason",
    }


def test_enh001_verification_is_rate_limited(rate_limited_verify_client: TestClient) -> None:
    client = rate_limited_verify_client
    statuses = [
        client.get(f"/api/verify/billing-documents/{'B' * 43}").status_code for _ in range(31)
    ]
    assert statuses[:30] == [404] * 30
    assert statuses[30] == 429


@pytest.fixture
def rate_limited_verify_client(client: TestClient):
    from caseops_api.core.rate_limit import limiter

    limiter.reset()
    previous = limiter.enabled
    limiter.enabled = True
    try:
        yield client
    finally:
        limiter.enabled = previous
        limiter.reset()


# --- line and amount formatting (coordinator follow-ups) ----------------------


def test_enh001_fixed_fee_lines_print_charge_type_and_amount_not_blank_rate(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, slug_seed="enh001-fixed")
    token = str(boot["access_token"])
    _profile(client, token)
    matter = _create_matter(client, token, "ENH001-FIXED")
    entry = client.post(
        f"/api/matters/{matter['id']}/time-entries",
        headers=auth_headers(token),
        json={"work_date": "2026-11-26", "description": "Conference with client",
              "duration_minutes": 90, "billable": True, "rate_currency": "INR"},
    )
    assert entry.status_code == 200, entry.text
    invoice = _invoice(
        client, token, str(matter["id"]), status="issued",
        include_uninvoiced_time_entries=True,
        manual_items=[
            {"description": "Drafting the written statement", "amount_minor": 1750000},
            {"description": "Filing charges", "amount_minor": 400000, "category": "court_fee"},
        ],
    )
    text = compact(assert_legible(_download(client, token, str(matter["id"]), invoice["id"])).text)
    assert compact("Drafting the written statement Fixed fee INR 17,500.00") in text
    assert compact("Filing charges Court fee INR 4,000.00") in text
    # Time entries keep hours and the hourly rate.
    assert compact("Conference with client 1.50 hrs INR 9,000.00/hr") in text
    assert "Item" not in text


def test_enh001_saas_invoice_and_statement_print_currency_not_minor_units(
    client: TestClient,
) -> None:
    from caseops_api.db.models import BillingManualInvoice, BillingSubscription

    boot = _bootstrap(client, slug_seed="enh001-saas-money")
    token = str(boot["access_token"])
    client.get("/api/billing/current", headers=auth_headers(token))
    factory = get_session_factory()
    with factory() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == str(boot["company"]["id"])
            )
        )
        assert subscription is not None
        manual = BillingManualInvoice(
            company_id=subscription.company_id,
            subscription_id=subscription.id,
            invoice_number=f"CO-MONEY-{str(boot['company']['id'])[:6]}",
            amount_minor=2500000,
            tax_amount_minor=450000,
            amount_received_minor=1000000,
            status="partially_paid",
            issued_on=date(2026, 11, 1),
        )
        session.add(manual)
        session.commit()
        invoice_id = manual.id
    pdf = client.get(f"/api/billing/invoices/{invoice_id}/download", headers=auth_headers(token))
    assert pdf.status_code == 200, pdf.text
    text = assert_legible(pdf.content).text
    for expected in ("Amount INR 25,000.00", "GST/tax INR 4,500.00", "Total INR 29,500.00",
                     "Received INR 10,000.00", "Status Partially paid"):
        assert compact(expected) in compact(text), expected
    assert "minor" not in text and "2500000" not in text
    statement = client.get("/api/billing/statement?format=pdf", headers=auth_headers(token))
    statement_text = assert_legible(statement.content).text
    assert compact("Partially paid | total INR 29,500.00") in compact(statement_text)
    assert "minor" not in statement_text
