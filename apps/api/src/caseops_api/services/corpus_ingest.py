"""Public legal corpus ingestion — Indian High Court and Supreme Court PDFs.

This service is deliberately streaming-friendly: the caller hands us one PDF
at a time (or a small batch) and we extract → chunk → embed → persist before
moving on. ``ingest_from_s3`` adds a batched S3 downloader on top that honours
a disk cap so hundreds of gigabytes never land on the workstation at once.

Assumptions:

- The two buckets we target are public and unsigned:
  ``s3://indian-high-court-judgments`` and
  ``s3://indian-supreme-court-judgments``. Both are anonymous-read.
- AuthorityDocument rows are *tenant-shared* — this is public law. Per-tenant
  overlays (internal notes, private precedents) live in separate tables and
  are out of scope here.
- Canonical dedup lets us re-run ingestion without duplicates.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    AuthorityIngestionRun,
    AuthorityIngestionStatus,
)
from caseops_api.services.document_processing import _chunk_text
from caseops_api.services.embeddings import (
    EmbeddingProvider,
    build_provider,
)

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client  # pragma: no cover

logger = logging.getLogger(__name__)


HC_BUCKET = "indian-high-court-judgments"
SC_BUCKET = "indian-supreme-court-judgments"

# Reasonable cap per-chunk so embedding calls do not hit provider limits.
MAX_CHUNK_CHARS = 2400


@dataclass
class IngestionSummary:
    total_files: int = 0
    processed_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    inserted_documents: int = 0
    inserted_chunks: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedJudgment:
    """Raw bytes plus parsed metadata for a single court document."""

    title: str
    court_name: str
    forum_level: str
    document_type: AuthorityDocumentType
    decision_date: date | None
    case_reference: str | None
    canonical_key: str
    source: str
    adapter_name: str
    source_reference: str
    summary: str
    document_text: str


# ---------------------------------------------------------------------------
# Metadata parsing — lightweight heuristics from filenames/paths
# ---------------------------------------------------------------------------


_DOCKET_RE = re.compile(
    r"(?P<type>WP|CRLP|CRLA|SA|RSA|LPA|CA|CS|CRR|OS|OA|SLP|WA|MA|AS|WPL|TA|RFA|MCA|OMP)"
    r"[\s(/_\-]*"
    r"(?:COMM|APPL|PIL|DB|SR|E|H|HC|CR|AD|L)?[\s(/_\-]*"
    r"(?P<number>\d{1,6})"
    r"[\s_\-]*(?:of|/|-|_)[\s_\-]*"
    r"(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)


def _guess_case_reference(stem: str) -> str | None:
    match = _DOCKET_RE.search(stem)
    if not match:
        return None
    return f"{match.group('type').upper()} {match.group('number')} / {match.group('year')}"


def _canonical_key_for(path: Path, court: str, year: int) -> str:
    raw = f"{court}|{year}|{path.name.lower()}|{path.stat().st_size}".encode()
    return hashlib.sha256(raw).hexdigest()[:40]


def parse_judgment_pdf(
    path: Path,
    *,
    court: str,
    forum_level: str,
    year: int,
    source_reference: str | None = None,
) -> ParsedJudgment | None:
    """Extract text + basic metadata from a judgment PDF.

    Falls back to OCR (see ``services/ocr.py``) when pdfminer's output is
    too sparse — typical for scanned HC filings. Returns ``None`` when both
    paths yield no meaningful text.
    """
    text = ""
    try:
        text = _extract_pdf_text(path)
    except Exception as exc:
        logger.warning("Could not extract text from %s: %s", path.name, exc)

    from caseops_api.services.ocr import ocr_pdf, should_fallback_to_ocr

    ocr_note: str | None = None
    if should_fallback_to_ocr(text):
        ocr_result = ocr_pdf(path)
        if ocr_result and ocr_result.text.strip():
            text = ocr_result.text
            ocr_note = (
                f"ocr:{ocr_result.provider} "
                f"pages={ocr_result.pages_processed}/{ocr_result.pages_total}"
            )
            if ocr_result.truncated:
                ocr_note += " truncated"

    if not text.strip():
        logger.warning("No text extracted from %s (even after OCR)", path.name)
        return None

    cleaned = _normalize_whitespace(text)
    title = _derive_title(path, cleaned)
    case_reference = _guess_case_reference(path.stem)
    decision_date = _guess_decision_date(cleaned, default_year=year)
    canonical_key = _canonical_key_for(path, court, year)
    court_name = _court_display_name(court)
    summary = _short_summary(cleaned)
    if ocr_note:
        summary = f"[{ocr_note}] {summary}"

    return ParsedJudgment(
        title=title,
        court_name=court_name,
        forum_level=forum_level,
        document_type=AuthorityDocumentType.JUDGMENT,
        decision_date=decision_date,
        case_reference=case_reference,
        canonical_key=canonical_key,
        source="ecourts-hc" if forum_level == "high_court" else "ecourts-sc",
        adapter_name="corpus-ingest",
        source_reference=source_reference or path.name,
        summary=summary,
        document_text=cleaned,
    )


def _court_display_name(court: str) -> str:
    if court == "sc":
        return "Supreme Court of India"
    if court == "hc":
        return "High Court of India"
    return court


def _derive_title(path: Path, text: str) -> str:
    # Prefer the first non-trivial line; fall back to the filename stem.
    for line in text.splitlines():
        stripped = line.strip()
        if 10 <= len(stripped) <= 220:
            return stripped[:220]
    return path.stem.replace("_", " ")[:220]


def _guess_decision_date(text: str, *, default_year: int) -> date:
    # Common legal date patterns.
    patterns = [
        r"(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
    ]
    months = {
        m.lower(): i
        for i, m in enumerate(
            [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ],
            start=1,
        )
    }
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        try:
            groups = match.groups()
            if len(groups) == 3 and groups[1].isdigit():
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                day = int(groups[0])
                month = months[groups[1].lower()]
                year = int(groups[2])
            return date(year, month, day)
        except (ValueError, KeyError):
            continue
    return date(default_year, 1, 1)


def _short_summary(text: str, *, max_chars: int = 600) -> str:
    snippet = " ".join(text.split())
    return snippet[:max_chars]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"[\t\x0b\x0c\r]+", " ", text).strip()


def _extract_pdf_text(path: Path) -> str:
    # pdfminer.six is already a core dependency; use it lazily to keep this
    # module import-light.
    from pdfminer.high_level import extract_text

    return extract_text(str(path))


# ---------------------------------------------------------------------------
# Persistence + embedding
# ---------------------------------------------------------------------------


def _already_indexed(session: Session, canonical_key: str) -> bool:
    existing = session.scalar(
        select(AuthorityDocument.id).where(AuthorityDocument.canonical_key == canonical_key)
    )
    return existing is not None


def persist_judgment(
    session: Session,
    *,
    parsed: ParsedJudgment,
    embedding_provider: EmbeddingProvider,
    chunk_target_size: int = MAX_CHUNK_CHARS,
) -> tuple[AuthorityDocument, list[AuthorityDocumentChunk]]:
    document = AuthorityDocument(
        source=parsed.source,
        adapter_name=parsed.adapter_name,
        court_name=parsed.court_name,
        forum_level=parsed.forum_level,
        document_type=parsed.document_type,
        title=parsed.title,
        case_reference=parsed.case_reference,
        decision_date=parsed.decision_date,
        canonical_key=parsed.canonical_key,
        source_reference=parsed.source_reference,
        summary=parsed.summary,
        document_text=parsed.document_text,
        extracted_char_count=len(parsed.document_text),
        ingested_at=datetime.now(UTC),
    )
    session.add(document)
    session.flush()

    chunks_text = _chunk_text(parsed.document_text, target_size=chunk_target_size)
    if not chunks_text:
        return document, []

    embed_result = embedding_provider.embed(chunks_text)
    chunk_rows: list[AuthorityDocumentChunk] = []
    for idx, (content, vector) in enumerate(zip(chunks_text, embed_result.vectors, strict=False)):
        chunk = AuthorityDocumentChunk(
            authority_document_id=document.id,
            chunk_index=idx,
            content=content,
            token_count=len(content.split()),
            embedding_model=embed_result.model,
            embedding_dimensions=embed_result.dimensions,
            embedding_json=_encode_vector(vector),
            embedded_at=datetime.now(UTC),
        )
        session.add(chunk)
        chunk_rows.append(chunk)

    # Best-effort pgvector sync. SQLite tests skip this block. Flush first so
    # the chunk rows actually exist when the UPDATE runs.
    if _postgres_backend(session):
        session.flush()
        _apply_pgvector_batch(session, chunks=chunk_rows, vectors=embed_result.vectors)
    return document, chunk_rows


def _encode_vector(vector: list[float]) -> str:
    import json

    return json.dumps([round(float(v), 6) for v in vector], separators=(",", ":"))


def _postgres_backend(session: Session) -> bool:
    try:
        return session.bind is not None and session.bind.dialect.name == "postgresql"
    except Exception:
        return False


def _apply_pgvector_batch(
    session: Session,
    *,
    chunks: list[AuthorityDocumentChunk],
    vectors: list[list[float]],
) -> None:
    """Populate the pgvector column for Postgres deployments."""
    from sqlalchemy import text

    for chunk, vector in zip(chunks, vectors, strict=False):
        session.execute(
            text(
                "UPDATE authority_document_chunks "
                "SET embedding_vector = :vec "
                "WHERE id = :id"
            ),
            {"vec": vector, "id": chunk.id},
        )


# ---------------------------------------------------------------------------
# Ingestion orchestration
# ---------------------------------------------------------------------------


def ingest_local_directory(
    session: Session,
    *,
    directory: Path,
    court: str,
    forum_level: str,
    year: int,
    embedding_provider: EmbeddingProvider | None = None,
    limit: int | None = None,
    delete_after: bool = False,
) -> IngestionSummary:
    """Walk ``directory`` for PDFs and ingest them one at a time.

    If ``delete_after`` is True, each PDF is unlinked from disk after its
    chunks are persisted. Use this when working against a downloaded batch
    that should not linger on the workstation.
    """
    embedder = embedding_provider or build_provider()
    summary = IngestionSummary()
    pdfs = sorted(p for p in directory.rglob("*.pdf") if p.is_file())
    if limit is not None:
        pdfs = pdfs[:limit]
    summary.total_files = len(pdfs)

    run = AuthorityIngestionRun(
        adapter_name="corpus-ingest",
        status=AuthorityIngestionStatus.COMPLETED,
        source="ecourts-hc" if forum_level == "high_court" else "ecourts-sc",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary=(
            f"{_court_display_name(court)} — year {year} — pending"
        ),
        imported_document_count=0,
    )
    session.add(run)
    session.flush()

    for path in pdfs:
        try:
            parsed = parse_judgment_pdf(
                path, court=court, forum_level=forum_level, year=year
            )
            if parsed is None:
                summary.failed_files += 1
                continue
            if _already_indexed(session, parsed.canonical_key):
                summary.skipped_files += 1
                if delete_after:
                    path.unlink(missing_ok=True)
                continue
            _, chunks = persist_judgment(
                session, parsed=parsed, embedding_provider=embedder
            )
            session.commit()
            summary.inserted_documents += 1
            summary.inserted_chunks += len(chunks)
            summary.processed_files += 1
        except Exception as exc:
            session.rollback()
            summary.failed_files += 1
            summary.errors.append(f"{path.name}: {exc}")
            logger.exception("Failed to ingest %s", path.name)
        finally:
            if delete_after:
                path.unlink(missing_ok=True)

    run.completed_at = datetime.now(UTC)
    run.imported_document_count = summary.inserted_documents
    run.summary = (
        f"{_court_display_name(court)} / {year}: "
        f"processed={summary.processed_files} "
        f"inserted_docs={summary.inserted_documents} "
        f"inserted_chunks={summary.inserted_chunks} "
        f"skipped={summary.skipped_files} "
        f"failed={summary.failed_files}"
    )
    session.commit()
    return summary


# ---------------------------------------------------------------------------
# S3 streaming ingestion
# ---------------------------------------------------------------------------


def _iter_s3_keys(
    client: S3Client,
    *,
    bucket: str,
    prefix: str,
    suffix: str | None = None,
    limit: int | None = None,
) -> Iterator[str]:
    paginator = client.get_paginator("list_objects_v2")
    yielded = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if suffix and not key.lower().endswith(suffix):
                continue
            yield key
            yielded += 1
            if limit is not None and yielded >= limit:
                return


def _open_s3_client():
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.client import Config
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is not installed. Run 'uv add boto3' to enable S3 corpus "
            "ingestion.",
        ) from exc
    return boto3.client(
        "s3",
        config=Config(signature_version=UNSIGNED),
        region_name="us-east-1",
    )


def _bytes_to_mb(n: int) -> float:
    return n / (1024 * 1024)


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
    return _bytes_to_mb(total)


def ingest_hc_from_s3(
    session: Session,
    *,
    year: int,
    limit: int | None = 50,
    batch_size: int | None = None,
    max_workdir_mb: int | None = None,
    temp_root: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> IngestionSummary:
    """Stream High Court judgments for a given year from S3.

    Downloads one batch at a time, ingests, and deletes the batch before
    moving on. Respects a workstation disk cap so we never hold more than
    ``max_workdir_mb`` megabytes of PDFs on disk.
    """
    settings = get_settings()
    batch_size = batch_size or settings.corpus_ingest_batch_size
    max_workdir_mb = max_workdir_mb or settings.corpus_ingest_max_workdir_mb
    root = Path(temp_root or settings.corpus_ingest_temp_root or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    embedder = embedding_provider or build_provider()

    client = _open_s3_client()
    prefix = f"data/pdf/year={year}/"
    keys = list(
        _iter_s3_keys(client, bucket=HC_BUCKET, prefix=prefix, suffix=".pdf", limit=limit)
    )

    overall = IngestionSummary()
    overall.total_files = len(keys)

    total_batches = max(1, (len(keys) + batch_size - 1) // batch_size)
    for batch_idx, batch_start in enumerate(range(0, len(keys), batch_size), start=1):
        batch = keys[batch_start : batch_start + batch_size]
        workdir = Path(tempfile.mkdtemp(prefix="caseops-hc-", dir=str(root)))
        logger.info(
            "[hc/%s] batch %d/%d — %d keys staged",
            year,
            batch_idx,
            total_batches,
            len(batch),
        )
        try:
            for key in batch:
                if _dir_size_mb(workdir) > max_workdir_mb:
                    logger.warning(
                        "Workdir reached %.1f MB (cap %d MB); flushing early",
                        _dir_size_mb(workdir),
                        max_workdir_mb,
                    )
                    break
                local_path = workdir / Path(key).name
                try:
                    client.download_file(HC_BUCKET, key, str(local_path))
                except Exception as exc:
                    overall.failed_files += 1
                    overall.errors.append(f"s3:{key}: {exc}")
                    continue

            batch_summary = ingest_local_directory(
                session,
                directory=workdir,
                court="hc",
                forum_level="high_court",
                year=year,
                embedding_provider=embedder,
                delete_after=True,
            )
            overall.processed_files += batch_summary.processed_files
            overall.skipped_files += batch_summary.skipped_files
            overall.failed_files += batch_summary.failed_files
            overall.inserted_documents += batch_summary.inserted_documents
            overall.inserted_chunks += batch_summary.inserted_chunks
            overall.errors.extend(batch_summary.errors)
            logger.info(
                "[hc/%s] batch %d/%d done — processed=%d inserted=%d "
                "skipped=%d failed=%d (totals: processed=%d inserted=%d)",
                year,
                batch_idx,
                total_batches,
                batch_summary.processed_files,
                batch_summary.inserted_documents,
                batch_summary.skipped_files,
                batch_summary.failed_files,
                overall.processed_files,
                overall.inserted_documents,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    return overall


def ingest_sc_from_s3(
    session: Session,
    *,
    year: int,
    limit: int | None = 5,
    temp_root: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    max_workdir_mb: int | None = None,
) -> IngestionSummary:
    """Stream Supreme Court tarballs for a year, extract + ingest + delete."""
    settings = get_settings()
    max_workdir_mb = max_workdir_mb or settings.corpus_ingest_max_workdir_mb
    root = Path(temp_root or settings.corpus_ingest_temp_root or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    embedder = embedding_provider or build_provider()

    client = _open_s3_client()
    prefix = f"data/tar/year={year}/"
    keys = list(
        _iter_s3_keys(client, bucket=SC_BUCKET, prefix=prefix, suffix=".tar", limit=limit)
    )

    overall = IngestionSummary()
    overall.total_files = len(keys)

    for key in keys:
        workdir = Path(tempfile.mkdtemp(prefix="caseops-sc-", dir=str(root)))
        try:
            tar_path = workdir / Path(key).name
            try:
                client.download_file(SC_BUCKET, key, str(tar_path))
            except Exception as exc:
                overall.failed_files += 1
                overall.errors.append(f"s3:{key}: {exc}")
                continue
            extract_dir = workdir / "extract"
            extract_dir.mkdir()
            try:
                with tarfile.open(tar_path) as tf:
                    _safe_extract_tar(tf, extract_dir)
            except Exception as exc:
                overall.failed_files += 1
                overall.errors.append(f"extract:{key}: {exc}")
                continue
            tar_path.unlink(missing_ok=True)

            batch_summary = ingest_local_directory(
                session,
                directory=extract_dir,
                court="sc",
                forum_level="supreme_court",
                year=year,
                embedding_provider=embedder,
                delete_after=True,
            )
            overall.processed_files += batch_summary.processed_files
            overall.skipped_files += batch_summary.skipped_files
            overall.failed_files += batch_summary.failed_files
            overall.inserted_documents += batch_summary.inserted_documents
            overall.inserted_chunks += batch_summary.inserted_chunks
            overall.errors.extend(batch_summary.errors)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    return overall


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract a tar safely, rejecting path-traversal and absolute names."""
    resolved_root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(resolved_root)):
            raise RuntimeError(f"Unsafe path in tar: {member.name!r}")
        if member.islnk() or member.issym():
            # Refuse to extract links — common tar-bomb vector.
            continue
    tf.extractall(dest)


__all__ = [
    "HC_BUCKET",
    "IngestionSummary",
    "ParsedJudgment",
    "SC_BUCKET",
    "ingest_hc_from_s3",
    "ingest_local_directory",
    "ingest_sc_from_s3",
    "parse_judgment_pdf",
    "persist_judgment",
]
