"""Offline native image/SDK contracts and explicitly selected baked-model checks."""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Native compatibility contracts must not access the network")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, blocked)
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, blocked)
    yield
    assert not attempts


def test_native_security_versions_and_installed_rebuild_metadata():
    from importlib.metadata import distribution

    assert version("pillow") == "13.0.0"
    dist = distribution("fastembed")
    assert dist.version == "0.8.0"
    assert "Build: 1caseops1" in dist.read_text("WHEEL")
    assert "CaseOps-Provenance" in dist.read_text("METADATA")


@pytest.mark.parametrize("format_name", ["PNG", "TIFF", "BMP", "JPEG", "WEBP"])
def test_native_image_roundtrip_preserves_dimensions_and_pixels(format_name):
    image = Image.new("RGB", (32, 24), (123, 45, 67))
    stream = io.BytesIO()
    image.save(stream, format=format_name)
    stream.seek(0)
    with Image.open(stream) as decoded:
        decoded.load()
        assert decoded.size == image.size
        pixel = decoded.convert("RGB").getpixel((16, 12))
        tolerance = 3 if format_name in {"JPEG", "WEBP"} else 0
        assert max(abs(a - b) for a, b in zip(pixel, (123, 45, 67), strict=True)) <= tolerance


@pytest.mark.parametrize("dtype", [np.uint8, np.float32, np.float64])
def test_fastembed_actual_pillow_transform_preserves_normalized_pixels(dtype):
    from fastembed.image.transform.functional import resize_ndarray

    data = np.full((3, 24, 32), 127 if dtype == np.uint8 else 0.5, dtype=dtype)
    actual = resize_ndarray(data, (12, 16))
    assert actual.shape == (3, 16, 12)
    assert np.allclose(actual, 127 if dtype == np.uint8 else 127 / 255)


def test_google_genai_uses_actual_native_pillow_image_without_provider():
    from google.genai import _transformers

    part = _transformers.t_part(Image.new("RGB", (32, 24), "white"))
    assert part.inline_data and part.inline_data.data
    assert part.inline_data.mime_type in {"image/jpeg", "image/png"}


def test_fpdf_and_pdfium_render_actual_image_through_pillow():
    import pypdfium2
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.image(Image.new("RGB", (32, 24), "white"), x=5, y=5, w=20, h=15)
    with pypdfium2.PdfDocument(bytes(pdf.output())) as document:
        page = document[0]
        bitmap = page.render()
        try:
            image = bitmap.to_pil()
            image.load()
            assert image.width > 0 and image.height > 0
        finally:
            bitmap.close()
            page.close()


def _native_cache() -> Path:
    value = os.environ.get("CASEOPS_NATIVE_COMPAT_CACHE")
    if not value:
        pytest.skip("Select the offline baked-model gate with CASEOPS_NATIVE_COMPAT_CACHE")
    cache = Path(value)
    assert cache.is_dir(), "The selected native gate requires its real, pre-provisioned model cache"
    return cache


def test_offline_real_text_embedding_inference(request):
    from fastembed import TextEmbedding

    model = TextEmbedding(
        model_name="BAAI/bge-small-en-v1.5", cache_dir=str(_native_cache()),
        local_files_only=True, threads=1, providers=["CPUExecutionProvider"],
    )
    vectors = np.asarray(list(model.embed([
        "A court grants regular bail after applying the triple test.",
        "A tax assessment determines taxable income.",
    ])))
    assert vectors.shape == (2, 384) and np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    assert not np.allclose(vectors[0], vectors[1])
    request.node.user_properties.append(("native_output", json.dumps(vectors.tolist())))


def test_offline_real_cross_encoder_inference_not_fallback(request):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    model = TextCrossEncoder(
        model_name="jinaai/jina-reranker-v1-tiny-en", cache_dir=str(_native_cache()),
        local_files_only=True, threads=1, providers=["CPUExecutionProvider"],
    )
    scores = np.asarray(list(model.rerank(
        "regular bail triple test",
        ["A tax assessment determines taxable income.",
         "The court grants regular bail after applying the triple test."],
    )))
    assert scores.shape == (2,) and np.isfinite(scores).all()
    assert scores[1] > scores[0]
    request.node.user_properties.append(("native_output", json.dumps(scores.tolist())))


def test_native_tesseract_consumes_real_pillow_image(request):
    _native_cache()
    if not shutil.which("tesseract"):
        pytest.skip("Native Tesseract is required by the separately executed Linux shipping gate")
    from caseops_api.services.ocr import _TesseractBackend

    image = Image.new("RGB", (900, 140), "white")
    ImageDraw.Draw(image).text(
        (20, 30), "CASEOPS LEGAL EVIDENCE 2026", font=ImageFont.load_default(size=42), fill="black"
    )
    result = _TesseractBackend()._ocr_one(image, "eng")
    assert "CASEOPS" in result.text.upper() and "2026" in result.text
    assert result.confidence > 0
    request.node.user_properties.append(("native_output", json.dumps({
        "text": result.text, "confidence": result.confidence,
    })))
