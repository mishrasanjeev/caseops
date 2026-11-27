"""OCR & Translate on JPG, JPEG and PNG uploads (BUG-001, 2026-11-27 workbook).

Tester report: every image OCR failed with "Sarvam OCR could not read the
pages (page_missing)". Root cause: the image was uploaded to Sarvam as
``page-1.<ext>``; Sarvam names its ``output_format=json`` primary file after
the upload stem (``page-1.png/page-1.json``), which the archive parser took for
a per-page metadata file, could not read as one and then never read as the
primary file. PDFs were uploaded as ``pages-<a>-<b>.pdf`` and never collided.

The mocked Sarvam archive follows the documented layout (Parse how-to, "Read
the output", and the ``/results`` schema, docs.sarvam.ai, checked
2026-11-27). No real provider is called.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from caseops_api.db.models import ProviderSpendReservation
from caseops_api.db.session import get_session_factory
from caseops_api.services import document_rendition_pipeline as pipeline
from caseops_api.services.document_renditions import SUPPORTED_SOURCE_TYPES
from caseops_api.services.file_security import ALLOWED_UPLOADS
from caseops_api.services.sarvam_document_ai import parse_output_archive
from tests.test_document_renditions_20261123 import (
    _detail,
    _latest,
    _setup,
    _start,
    _upload,
    _verify_costs,
    _versions,
    providers,  # noqa: F401 (pytest fixture)
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MARK = (20, 20, 120, 60)  # dark box near the top-left of the upright page


# ------------------------------------------------------------- image fixtures


def _page(mode: str = "RGB", size: tuple[int, int] = (300, 400)) -> Image.Image:
    """An upright page: white ground, a dark box top-left, a line of 'text'."""

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(MARK, fill="black")
    draw.text((20, 100), "ORDER 12.03.2023", fill="black")
    return image.convert(mode)


def _encode(image: Image.Image, fmt: str, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def _transparent_png() -> bytes:
    # Dark text on a fully transparent ground: flattened on black it vanishes.
    image = Image.new("RGBA", (300, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(MARK, fill=(0, 0, 0, 255))
    return _encode(image, "PNG")


def _palette_png_with_transparency() -> bytes:
    # Index 2 is transparent and stored as black underneath.
    image = Image.new("P", (300, 400), 1)
    image.putpalette([0, 0, 0, 255, 255, 255, 0, 0, 0] + [0] * 759)
    ImageDraw.Draw(image).rectangle(MARK, fill=0)
    image.paste(2, (200, 200, 300, 400))
    return _encode(image, "PNG", transparency=2)


def _grey16_png() -> bytes:
    image = Image.new("I;16", (300, 400), 65535)
    ImageDraw.Draw(image).rectangle(MARK, fill=0)
    return _encode(image, "PNG")


def _exif_rotated_jpeg() -> bytes:
    # Stored landscape; EXIF orientation 6 tells viewers to turn it upright.
    stored = _page().transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[0x0112] = 6
    return _encode(stored, "JPEG", quality=95, exif=exif.tobytes())


def _mpo_jpeg() -> bytes:
    # Phone cameras write multi-picture JPEGs with a .jpg name.
    return _encode(_page(), "MPO", save_all=True, append_images=[_page(size=(150, 200))])


def _cmyk_jpeg() -> bytes:
    return _encode(_page("CMYK"), "JPEG", quality=95)


# name, bytes, declared type, "same" (sent byte for byte) or "converted"
IMAGE_CASES = {
    "jpg": ("scan.jpg", lambda: _encode(_page(), "JPEG", quality=90), "image/jpeg", "same"),
    "jpeg-upper": (
        "Scan.JPEG", lambda: _encode(_page(), "JPEG", quality=90), "image/jpeg", "same",
    ),
    "png": ("scan.png", lambda: _encode(_page(), "PNG"), "image/png", "same"),
    "png-greyscale": ("grey.png", lambda: _encode(_page("L"), "PNG"), "image/png", "same"),
    "png-16-bit": ("grey16.png", _grey16_png, "image/png", "same"),
    "png-large": (
        "large.png", lambda: _encode(_page("L", (4960, 7016)), "PNG"), "image/png", "same",
    ),
    "png-transparent": ("clip.png", _transparent_png, "image/png", "converted"),
    "png-palette-transparency": (
        "palette.png", _palette_png_with_transparency, "image/png", "converted",
    ),
    "jpg-exif-rotated": ("phone.jpg", _exif_rotated_jpeg, "image/jpeg", "converted"),
    "jpg-multi-picture": ("camera.jpg", _mpo_jpeg, "image/jpeg", "converted"),
    "jpg-cmyk": ("print.jpg", _cmyk_jpeg, "image/jpeg", "converted"),
}


def _dark(image: Image.Image, xy: tuple[int, int]) -> bool:
    return max(image.convert("L").getpixel(xy), 0) < 64


# ------------------------------------------------------- end-to-end, per type


@pytest.mark.parametrize("case", sorted(IMAGE_CASES))
def test_image_ocr_reads_the_page_the_user_sees(
    client: TestClient, providers,  # noqa: F811
    case: str,
) -> None:
    sarvam, _ = providers
    name, build, declared, expectation = IMAGE_CASES[case]
    original = build()
    _verify_costs()
    _, token, matter_id = _setup(client, f"IMG-{case}"[:30])
    attachment_id = _upload(client, token, matter_id, name, original, declared)

    assert _start(client, token, matter_id, attachment_id, "hi").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")

    # The tester's exact failure must not recur: one page, read, with text.
    assert ocr["status"] == "ocr_completed", (ocr["error_code"], ocr["error_message"])
    assert ocr["error_code"] is None and ocr["page_count"] == 1 and ocr["pages_ok"] == 1
    detail = _detail(client, token, matter_id, attachment_id, ocr["id"])
    page = detail["pages"][0]
    assert page["source"] == "ocr" and page["reasons"] == []
    assert page["text"] == sarvam.text_for(1, 1)

    assert len(sarvam.submissions) == 1 and sarvam.submissions[0]["language"] == "hi-IN"
    sent = sarvam.uploads["job-1"]
    suffix = "png" if sent["content_type"] == "image/png" else "jpg"
    assert sent["filename"] == f"pages-1-1.{suffix}"
    assert sent["content_type"] in {"image/png", "image/jpeg"}
    received = Image.open(io.BytesIO(sent["content"]))
    assert received.format == {"image/png": "PNG", "image/jpeg": "JPEG"}[sent["content_type"]]
    if expectation == "same":
        assert sent["content"] == original
        return
    # Converted: one upright frame, RGB or greyscale, no EXIF turn left to apply.
    assert getattr(received, "n_frames", 1) == 1
    assert received.mode in {"RGB", "L"}
    assert received.getexif().get(0x0112, 1) == 1
    assert received.size == (300, 400)
    assert _dark(received, (70, 40)), "the top-left mark must stay top-left"
    assert not _dark(received, (250, 350)), "transparent or blank areas must read white"


def test_image_page_with_no_text_is_an_empty_page_not_a_provider_failure(
    client: TestClient, providers,  # noqa: F811
) -> None:
    sarvam, _ = providers
    sarvam.text_for = lambda job_no, page_no: ""  # completed, no text block
    _verify_costs()
    _, token, matter_id = _setup(client, "IMG-BLANK")
    attachment_id = _upload(
        client, token, matter_id, "blank.png", _encode(Image.new("RGB", (60, 60), "white"),
                                                     "PNG"), "image/png",
    )
    assert _start(client, token, matter_id, attachment_id, "en").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")
    detail = _detail(client, token, matter_id, attachment_id, ocr["id"])
    assert ocr["status"] == "review_required", (ocr["error_code"], ocr["error_message"])
    assert detail["pages"][0]["reasons"] == ["empty_page"]


def test_provider_page_missing_message_tells_the_user_what_to_do(
    client: TestClient, providers,  # noqa: F811
) -> None:
    sarvam, _ = providers
    sarvam.text_for = lambda job_no, page_no: None  # Sarvam failed the page
    _verify_costs()
    _, token, matter_id = _setup(client, "IMG-MISSING")
    attachment_id = _upload(
        client, token, matter_id, "faint.jpg", _encode(_page(), "JPEG"), "image/jpeg",
    )
    assert _start(client, token, matter_id, attachment_id, "en").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")
    assert ocr["status"] == "failed" and ocr["error_code"] == "provider_page_missing"
    message = ocr["error_message"]
    assert "(page_missing)" not in message
    assert "300 DPI" in message and "retry" in message


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image_unreadable"),
        (b"\xff\xd8\xff\xe0" + b"not a jpeg" * 8, "image_unreadable"),
    ],
    ids=["png-garbage", "jpeg-garbage"],
)
def test_undecodable_image_fails_locally_without_any_provider_call_or_hold(
    client: TestClient, providers,  # noqa: F811
    data: bytes, code: str,
) -> None:
    sarvam, _ = providers
    _verify_costs()
    _, token, matter_id = _setup(client, "IMG-BROKEN")
    suffix, declared = ("png", "image/png") if data.startswith(b"\x89PNG") else (
        "jpg", "image/jpeg",
    )
    attachment_id = _upload(client, token, matter_id, f"broken.{suffix}", data, declared)
    assert _start(client, token, matter_id, attachment_id, "en").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")
    assert ocr["status"] == "failed" and ocr["error_code"] == code
    assert "PNG or JPEG" in ocr["error_message"]
    assert sarvam.submissions == []
    with get_session_factory()() as session:
        assert session.scalars(select(ProviderSpendReservation)).all() == []


def test_decompression_bomb_image_is_refused_before_any_provider_call(
    client: TestClient, providers,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sarvam, _ = providers
    _verify_costs()
    _, token, matter_id = _setup(client, "IMG-BOMB")
    attachment_id = _upload(
        client, token, matter_id, "huge.png", _encode(_page(), "PNG"), "image/png",
    )
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000)
    assert _start(client, token, matter_id, attachment_id, "en").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")
    assert ocr["status"] == "failed" and ocr["error_code"] == "image_too_large"
    assert sarvam.submissions == []


def test_declared_octet_stream_is_sent_with_the_type_of_its_bytes(tmp_path: Path) -> None:
    # source_format() accepts application/octet-stream for an eligible suffix
    # (other ingestion paths store it); Sarvam must still get image/png.
    path = tmp_path / "scan.png"
    path.write_bytes(_encode(_page(), "PNG"))
    name, data, media_type = pipeline._content_for_batch(
        str(path), "image", [1], "scan.png", "application/octet-stream",
    )
    assert (name, media_type) == ("pages-1-1.png", "image/png")
    assert data == path.read_bytes()


# ------------------------------------------------------ archive parser shapes


def _zip(members: dict[str, object]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, json.dumps(payload, ensure_ascii=False))
    return buffer.getvalue()


def _block(page: int, order: int, text: str, tag: str = "paragraph") -> dict:
    return {
        "block_id": f"p{page}-b{order}", "text": text, "layout_tag": tag,
        "reading_order": order, "coordinates": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
        "bbox_norm": [0.1, 0.1, 0.2, 0.2], "confidence": 0.9,
    }


def _document(name: str, pages: list[list[dict]]) -> dict:
    return {
        "filename": name, "page_count": len(pages), "language": "hi-IN",
        "status": "completed", "partial": False, "warnings": [],
        "pages": [
            {"page_num": number, "status": "completed", "image_width": 1667,
             "image_height": 1250, "blocks": blocks}
            for number, blocks in enumerate(pages, start=1)
        ],
    }


@pytest.mark.parametrize("upload", ["page-1.png", "page-1.jpg", "page_001.jpeg", "page1.png"])
def test_primary_json_named_like_a_page_file_is_still_read(upload: str) -> None:
    stem = upload.rsplit(".", 1)[0]
    archive = _zip({
        "manifest.json": {"files": [upload]},
        f"{upload}/{stem}.json": _document(upload, [[_block(1, 1, "आदेश दिनांक 12.03.2023")]]),
    })
    pages = parse_output_archive(archive, page_count=1)
    assert pages[1].text == "आदेश दिनांक 12.03.2023"


def test_results_shaped_primary_json_maps_every_page() -> None:
    archive = _zip({
        "manifest.json": {},
        "pages-1-2.pdf/pages-1-2.json": {
            "type": "digitise",
            "documents": [_document("pages-1-2.pdf", [
                [_block(1, 1, "first page")], [_block(2, 1, "second page")],
            ])],
        },
    })
    pages = parse_output_archive(archive, page_count=2)
    assert {number: page.text for number, page in pages.items()} == {
        1: "first page", 2: "second page",
    }


def test_blocks_follow_reading_order_and_keep_the_layout_tag() -> None:
    blocks = [_block(1, 2, "second"), _block(1, 1, "TITLE", "section-title")]
    archive = _zip({"x.pdf/x.json": _document("x.pdf", [blocks])})
    page = parse_output_archive(archive, page_count=1)[1]
    assert page.text == "TITLE\n\nsecond"
    assert [block["tag"] for block in page.blocks] == ["section-title", "paragraph"]


def test_markdown_layout_metadata_pages_are_still_read() -> None:
    archive = _zip({
        "manifest.json": {},
        "doc.pdf/metadata/page_001.json": {"blocks": [_block(1, 1, "one")]},
        "doc.pdf/metadata/page_002.json": {"blocks": [_block(2, 1, "two")]},
    })
    pages = parse_output_archive(archive, page_count=2)
    assert pages[1].text == "one" and pages[2].text == "two"


def test_completed_empty_page_is_empty_and_failed_page_is_missing() -> None:
    document = _document("x.pdf", [[], []])
    document["pages"][1]["status"] = "failed"
    pages = parse_output_archive(_zip({"x.pdf/x.json": document}), page_count=2)
    assert pages[1].text == "" and 2 not in pages


# ---------------------------------------- upload, API gate and web gate agree


def _web_eligible_types() -> dict[str, set[str]]:
    source = (REPO_ROOT / "apps/web/lib/renditions.ts").read_text(encoding="utf-8")
    body = re.search(r"const ELIGIBLE_TYPES[^=]*=\s*\{(.*?)\};", source, re.S)
    assert body, "ELIGIBLE_TYPES not found in apps/web/lib/renditions.ts"
    return {
        key: set(re.findall(r'"([^"]+)"', values))
        for key, values in re.findall(r"(\w+):\s*\[([^\]]*)\]", body.group(1))
    }


def test_web_ocr_gate_offers_exactly_what_the_api_accepts() -> None:
    assert _web_eligible_types() == {
        suffix: set(types) for suffix, types in SUPPORTED_SOURCE_TYPES.items()
    }


def test_every_uploadable_image_type_is_ocr_eligible_and_vice_versa() -> None:
    uploadable_images = {
        kind.extension.lstrip(".") for kind in ALLOWED_UPLOADS
        if any(ctype.startswith("image/") for ctype in kind.content_types)
    }
    eligible_images = {suffix for suffix in SUPPORTED_SOURCE_TYPES if suffix != "pdf"}
    assert uploadable_images == eligible_images == {"png", "jpg", "jpeg"}
    for kind in ALLOWED_UPLOADS:
        suffix = kind.extension.lstrip(".")
        if suffix in SUPPORTED_SOURCE_TYPES:
            assert kind.content_types <= SUPPORTED_SOURCE_TYPES[suffix], suffix
