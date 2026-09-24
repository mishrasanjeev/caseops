from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document

from caseops_api.services import document_processing


def _write_docx(path: Path, *paragraphs: str) -> None:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(path)


def test_docx_preflight_rejects_expanded_part_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "compressed.docx"
    _write_docx(path, "Safe content")
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/unreferenced.xml", "x" * 2048)
    monkeypatch.setattr(document_processing, "MAX_DOCX_XML_PART_BYTES", 1024)
    monkeypatch.setattr("docx.Document", lambda _: pytest.fail("DOCX parser reached"))

    with pytest.raises(ValueError, match="expanded processing size limit"):
        document_processing._extract_docx_text(path)


def test_docx_extracted_text_and_segment_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "many-paragraphs.docx"
    _write_docx(path, "First paragraph", "Second paragraph")
    monkeypatch.setattr(document_processing, "MAX_DOCX_EXTRACTED_CHARS", 20)
    with pytest.raises(ValueError, match="extracted text limit"):
        document_processing._extract_docx_text(path)

    monkeypatch.setattr(document_processing, "MAX_DOCX_EXTRACTED_CHARS", 1_000_000)
    monkeypatch.setattr(document_processing, "MAX_DOCX_TEXT_SEGMENTS", 1)
    with pytest.raises(ValueError, match="extracted text limit"):
        document_processing._extract_docx_text(path)


def test_docx_chunk_cap_fails_without_retaining_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "many-chunks.docx"
    _write_docx(path, "A" * 4000, "B" * 4000)
    monkeypatch.setattr(document_processing, "resolve_storage_path", lambda _: path)
    monkeypatch.setattr(document_processing, "MAX_DOCX_CHUNKS", 1)

    result = document_processing.parse_attachment("many-chunks.docx", None)
    assert result.status == "failed"
    assert result.extracted_text is None
    assert result.chunks == []
    assert result.error == "DOCX exceeds the indexed chunk limit."
