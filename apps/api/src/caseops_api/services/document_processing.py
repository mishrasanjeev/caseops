from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from pdfminer.high_level import extract_text as pdf_extract_text
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    ContractAttachment,
    ContractAttachmentChunk,
    DocumentProcessingStatus,
    MatterAttachment,
    MatterAttachmentChunk,
    utcnow,
)
from caseops_api.services.document_storage import resolve_storage_path

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml", ".xml", ".html", ".htm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class ParsedDocument:
    status: str
    extracted_text: str | None
    chunks: list[str]
    error: str | None


def _normalize_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines()).strip()


def _load_text(path: Path, suffix: str) -> str:
    if suffix == ".json":
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            return json.dumps(json.loads(raw), indent=2, ensure_ascii=True)
        except json.JSONDecodeError:
            return raw

    raw = path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        raw = HTML_TAG_PATTERN.sub(" ", raw)
    return raw


def _resolve_tesseract_command() -> str | None:
    settings = get_settings()
    return settings.tesseract_command or shutil.which("tesseract")


def _extract_pdf_text(path: Path) -> str:
    return pdf_extract_text(str(path))


def _run_tesseract(command: str, path: Path) -> str:
    completed = subprocess.run(
        [command, str(path), "stdout"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Tesseract OCR failed."
        raise RuntimeError(message)
    return completed.stdout


def _extract_image_text(path: Path) -> str:
    command = _resolve_tesseract_command()
    if not command:
        raise RuntimeError("OCR is not configured yet because no tesseract binary is available.")
    return _run_tesseract(command, path)


def _extract_scanned_pdf_text(path: Path) -> str:
    command = _resolve_tesseract_command()
    if not command:
        raise RuntimeError("OCR is not configured yet because no tesseract binary is available.")

    document = pdfium.PdfDocument(str(path))
    page_texts: list[str] = []
    try:
        for page_index in range(len(document)):
            page = document.get_page(page_index)
            temp_path: Path | None = None
            try:
                bitmap = page.render(scale=2)
                image = bitmap.to_pil()
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
                        temp_path = Path(temp_file.name)
                    image.save(temp_path, format="PNG")
                    text = _normalize_whitespace(_run_tesseract(command, temp_path))
                finally:
                    image.close()
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                if text:
                    page_texts.append(text)
            finally:
                page.close()
    finally:
        document.close()

    return "\n\n".join(page_texts)


def _chunk_text(text: str, *, target_size: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if not paragraphs:
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]

    chunks: list[str] = []
    buffer: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        paragraph_size = len(paragraph)
        if buffer and current_size + paragraph_size + 1 > target_size:
            chunks.append("\n\n".join(buffer))
            buffer = [paragraph]
            current_size = paragraph_size
            continue
        buffer.append(paragraph)
        current_size += paragraph_size + 1
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def parse_attachment(storage_key: str, content_type: str | None) -> ParsedDocument:
    path = resolve_storage_path(storage_key)
    suffix = path.suffix.lower()

    if content_type and content_type.startswith("text/") or suffix in TEXT_SUFFIXES:
        text = _normalize_whitespace(_load_text(path, suffix))
        if not text:
            return ParsedDocument(
                status=DocumentProcessingStatus.FAILED,
                extracted_text=None,
                chunks=[],
                error="Readable text extraction returned an empty payload.",
            )
        return ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=text,
            chunks=_chunk_text(text),
            error=None,
        )
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            text = _normalize_whitespace(_extract_pdf_text(path))
        except Exception as exc:
            try:
                text = _normalize_whitespace(_extract_scanned_pdf_text(path))
            except Exception as ocr_exc:
                return ParsedDocument(
                    status=DocumentProcessingStatus.NEEDS_OCR,
                    extracted_text=None,
                    chunks=[],
                    error=(
                        "PDF text extraction could not parse this file yet and OCR "
                        "is still required. "
                        f"{str(ocr_exc).strip() or str(exc).strip() or 'OCR is required.'}"
                    ),
                )
        if text:
            return ParsedDocument(
                status=DocumentProcessingStatus.INDEXED,
                extracted_text=text,
                chunks=_chunk_text(text),
                error=None,
            )
        try:
            text = _normalize_whitespace(_extract_scanned_pdf_text(path))
        except Exception as exc:
            return ParsedDocument(
                status=DocumentProcessingStatus.NEEDS_OCR,
                extracted_text=None,
                chunks=[],
                error=(
                    "PDF has no extractable text yet and still requires OCR. "
                    f"{str(exc).strip() or 'OCR is required.'}"
                ).strip(),
            )
        if text:
            return ParsedDocument(
                status=DocumentProcessingStatus.INDEXED,
                extracted_text=text,
                chunks=_chunk_text(text),
                error=None,
            )
        return ParsedDocument(
            status=DocumentProcessingStatus.NEEDS_OCR,
            extracted_text=None,
            chunks=[],
            error="PDF OCR ran but did not return readable text.",
        )
    if content_type and content_type.startswith("image/") or suffix in IMAGE_SUFFIXES:
        try:
            text = _normalize_whitespace(_extract_image_text(path))
        except Exception as exc:
            return ParsedDocument(
                status=DocumentProcessingStatus.NEEDS_OCR,
                extracted_text=None,
                chunks=[],
                error=str(exc),
            )
        if text:
            return ParsedDocument(
                status=DocumentProcessingStatus.INDEXED,
                extracted_text=text,
                chunks=_chunk_text(text),
                error=None,
            )
        return ParsedDocument(
            status=DocumentProcessingStatus.NEEDS_OCR,
            extracted_text=None,
            chunks=[],
            error="OCR ran but did not return readable text.",
        )

    try:
        text = _normalize_whitespace(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        return ParsedDocument(
            status=DocumentProcessingStatus.FAILED,
            extracted_text=None,
            chunks=[],
            error=str(exc),
        )

    if text and "\x00" not in text:
        return ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=text,
            chunks=_chunk_text(text),
            error=None,
        )

    return ParsedDocument(
        status=DocumentProcessingStatus.FAILED,
        extracted_text=None,
        chunks=[],
        error="Unsupported file type for text extraction.",
    )


def index_matter_attachment(attachment: MatterAttachment) -> None:
    parsed = parse_attachment(attachment.storage_key, attachment.content_type)
    attachment.processing_status = parsed.status
    attachment.extracted_text = parsed.extracted_text
    attachment.extracted_char_count = len(parsed.extracted_text or "")
    attachment.extraction_error = parsed.error
    attachment.processed_at = utcnow()
    attachment.chunks = [
        MatterAttachmentChunk(
            chunk_index=index,
            content=chunk,
            token_count=len(chunk.split()),
        )
        for index, chunk in enumerate(parsed.chunks)
    ]


def embed_matter_attachment_chunks(
    session: Session, attachment: MatterAttachment
) -> int:
    """Populate embedding_* columns on the attachment's chunks.

    Best-effort: if the embedding provider fails, the chunks remain
    indexed (so lexical retrieval still works) and this function
    returns 0. Returns the number of chunks embedded.
    """
    if not attachment.chunks:
        return 0
    try:
        from caseops_api.services.embeddings import (
            EmbeddingProviderError,
            build_provider,
        )
    except ImportError:
        return 0

    try:
        provider = build_provider()
    except EmbeddingProviderError:
        logger.warning(
            "embedding provider unavailable; matter attachment %s "
            "will be lexical-only", attachment.id,
        )
        return 0

    try:
        result = provider.embed([chunk.content for chunk in attachment.chunks])
    except EmbeddingProviderError as exc:
        logger.warning(
            "embedding call failed for matter attachment %s: %s",
            attachment.id, exc,
        )
        return 0

    now = utcnow()
    from caseops_api.services.corpus_ingest import (
        _apply_pgvector_batch_for_matter,
        _encode_vector,
        _postgres_backend,
    )

    for chunk, vector in zip(attachment.chunks, result.vectors, strict=False):
        chunk.embedding_model = result.model
        chunk.embedding_dimensions = result.dimensions
        chunk.embedding_json = _encode_vector(vector)
        chunk.embedded_at = now

    if _postgres_backend(session):
        session.flush()
        _apply_pgvector_batch_for_matter(
            session, chunks=list(attachment.chunks), vectors=result.vectors
        )
    return len(attachment.chunks)


def index_contract_attachment(attachment: ContractAttachment) -> None:
    parsed = parse_attachment(attachment.storage_key, attachment.content_type)
    attachment.processing_status = parsed.status
    attachment.extracted_text = parsed.extracted_text
    attachment.extracted_char_count = len(parsed.extracted_text or "")
    attachment.extraction_error = parsed.error
    attachment.processed_at = utcnow()
    attachment.chunks = [
        ContractAttachmentChunk(
            chunk_index=index,
            content=chunk,
            token_count=len(chunk.split()),
        )
        for index, chunk in enumerate(parsed.chunks)
    ]
