from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityIngestionRun,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_ingest import (
    ParsedJudgment,
    _guess_case_reference,
    _guess_decision_date,
    ingest_local_directory,
    parse_judgment_pdf,
    persist_judgment,
    reembed_corpus,
)
from caseops_api.services.embeddings import MockProvider


def _make_minimal_pdf_bytes(body: str) -> bytes:
    """Build a PDF that pdfminer can actually parse.

    We build the content stream by concatenating `TJ` operators per line —
    bypassing font descriptor/embedding concerns. Works for pure ASCII."""
    stream = []
    stream.append("BT")
    stream.append("/F1 12 Tf")
    stream.append("72 720 Td")
    for idx, line in enumerate(body.splitlines()):
        if idx > 0:
            stream.append("0 -14 Td")
        safe = line.replace("(", "").replace(")", "")
        stream.append(f"({safe}) Tj")
    stream.append("ET")
    content = "\n".join(stream).encode("latin-1")

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    objects: list[bytes] = []

    def add_obj(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    font_id = add_obj(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )
    content_id = add_obj(
        f"<< /Length {len(content)} >>\nstream\n".encode()
        + content
        + b"\nendstream"
    )
    page_id = add_obj(
        f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
        f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
        f"/Contents {content_id} 0 R >>".encode()
    )
    pages_id = add_obj(
        f"<< /Type /Pages /Count 1 /Kids [{page_id} 0 R] >>".encode()
    )
    catalog_id = add_obj(
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    )

    # Patch page parent
    objects[page_id - 1] = objects[page_id - 1].replace(
        b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode()
    )

    body_bytes = bytearray(header)
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(body_bytes))
        body_bytes.extend(f"{idx} 0 obj\n".encode())
        body_bytes.extend(obj)
        body_bytes.extend(b"\nendobj\n")

    xref_start = len(body_bytes)
    body_bytes.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    body_bytes.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        body_bytes.extend(f"{off:010d} 00000 n \n".encode())

    body_bytes.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode()
    )
    body_bytes.extend(f"startxref\n{xref_start}\n".encode())
    body_bytes.extend(b"%%EOF\n")
    return bytes(body_bytes)


def _write_pdf(path: Path, body: str) -> None:
    path.write_bytes(_make_minimal_pdf_bytes(body))


def test_guess_case_reference_parses_common_docket() -> None:
    assert _guess_case_reference("WP_12345_of_2019_ABC") == "WP 12345 / 2019"
    assert _guess_case_reference("slp-77-of-2021") == "SLP 77 / 2021"


def test_guess_case_reference_handles_missing() -> None:
    assert _guess_case_reference("just-a-random-name.pdf") is None


def test_guess_decision_date_falls_back_to_year() -> None:
    d = _guess_decision_date("no dates here", default_year=2007)
    assert d.year == 2007 and d.month == 1 and d.day == 1


def test_guess_decision_date_picks_named_month() -> None:
    text = "Pronounced on the 12th of March 2018 in open court."
    d = _guess_decision_date(text, default_year=1900)
    assert (d.year, d.month, d.day) == (2018, 3, 12)


def test_persist_judgment_writes_chunks_with_embeddings(
    client: TestClient,
) -> None:
    factory = get_session_factory()
    with factory() as session:
        parsed = ParsedJudgment(
            title="Sample Judgment",
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type=__import__(
                "caseops_api.db.models", fromlist=["AuthorityDocumentType"]
            ).AuthorityDocumentType.JUDGMENT,
            decision_date=__import__("datetime").date(2020, 1, 1),
            case_reference="WP 1 / 2020",
            canonical_key="k-test-1",
            source="ecourts-hc",
            adapter_name="corpus-ingest",
            source_reference="sample.pdf",
            summary="A short summary",
            document_text=(
                "Paragraph one discusses patent illegality under Section 34 "
                "of the Arbitration Act.\n\n"
                "Paragraph two further examines the patent illegality ground "
                "and interprets Supreme Court precedent."
            ),
        )
        provider = MockProvider(dimensions=128)
        document, chunks = persist_judgment(
            session, parsed=parsed, embedding_provider=provider
        )
        session.commit()
        document_id = document.id

    with factory() as session:
        stored_chunks = list(
            session.scalars(
                select(AuthorityDocumentChunk).where(
                    AuthorityDocumentChunk.authority_document_id == document_id
                )
            )
        )
    assert stored_chunks, "expected at least one chunk"
    for chunk in stored_chunks:
        assert chunk.embedding_json is not None
        assert chunk.embedding_model == provider.model
        assert chunk.embedding_dimensions == provider.dimensions
        assert chunk.embedded_at is not None


def test_ingest_local_directory_with_real_pdfs(
    client: TestClient, tmp_path: Path
) -> None:
    pdf_one = tmp_path / "WP_12345_of_2019.pdf"
    pdf_two = tmp_path / "WP_12346_of_2019.pdf"
    _write_pdf(
        pdf_one,
        "In the High Court of Judicature at Delhi\n"
        "Writ Petition Number 12345 of 2019\n"
        "Patent illegality under Section 34 of the Arbitration Act.\n"
        "The award is opposed to Indian public policy.\n",
    )
    _write_pdf(
        pdf_two,
        "In the High Court of Judicature at Delhi\n"
        "Writ Petition Number 12346 of 2019\n"
        "Taxation of non resident shipping companies.\n"
        "Unrelated commercial matters.\n",
    )
    factory = get_session_factory()
    with factory() as session:
        summary = ingest_local_directory(
            session,
            directory=tmp_path,
            court="hc",
            forum_level="high_court",
            year=2019,
            embedding_provider=MockProvider(dimensions=128),
            delete_after=False,
        )
    assert summary.total_files == 2
    assert summary.inserted_documents == 2
    assert summary.inserted_chunks >= 2

    with factory() as session:
        docs = list(session.scalars(select(AuthorityDocument)))
        runs = list(session.scalars(select(AuthorityIngestionRun)))
    assert len(docs) == 2
    assert any(r.imported_document_count == 2 for r in runs)


def test_ingest_respects_delete_after(client: TestClient, tmp_path: Path) -> None:
    pdf = tmp_path / "WP_999_of_2020.pdf"
    _write_pdf(pdf, "Short judgment text")
    factory = get_session_factory()
    with factory() as session:
        ingest_local_directory(
            session,
            directory=tmp_path,
            court="hc",
            forum_level="high_court",
            year=2020,
            embedding_provider=MockProvider(dimensions=128),
            delete_after=True,
        )
    assert not pdf.exists()


def test_ingest_dedupes_on_canonical_key(
    client: TestClient, tmp_path: Path
) -> None:
    pdf = tmp_path / "WP_1_of_2015.pdf"
    _write_pdf(pdf, "First ingestion.\nAnother line.")
    factory = get_session_factory()
    with factory() as session:
        first = ingest_local_directory(
            session,
            directory=tmp_path,
            court="hc",
            forum_level="high_court",
            year=2015,
            embedding_provider=MockProvider(dimensions=128),
        )
    assert first.inserted_documents == 1

    # Re-run: canonical key matches, should skip.
    with factory() as session:
        second = ingest_local_directory(
            session,
            directory=tmp_path,
            court="hc",
            forum_level="high_court",
            year=2015,
            embedding_provider=MockProvider(dimensions=128),
        )
    assert second.inserted_documents == 0
    assert second.skipped_files == 1


def test_parse_judgment_pdf_returns_none_on_blank_file(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    parsed = parse_judgment_pdf(pdf, court="hc", forum_level="high_court", year=2024)
    assert parsed is None


def _seed_two_chunks(
    session, *, model: str = "bge-small-v1.5"
) -> tuple[str, str]:
    """Insert a single document with two chunks already embedded by
    `model`. Returns (doc_id, second_chunk_id) for assertions."""
    from datetime import UTC, date, datetime

    from caseops_api.db.models import (
        AuthorityDocument,
        AuthorityDocumentChunk,
        AuthorityDocumentType,
    )

    doc = AuthorityDocument(
        source="seed-tests",
        adapter_name="seed",
        court_name="Supreme Court of India",
        forum_level="supreme_court",
        document_type=AuthorityDocumentType.JUDGMENT,
        title="Reembed seed",
        case_reference=None,
        bench_name=None,
        neutral_citation="REEMBED-1",
        decision_date=date(2024, 1, 1),
        canonical_key=f"reembed-seed::{model}",
        source_reference=None,
        summary="Placeholder summary",
        document_text=None,
        ingested_at=datetime.now(UTC),
    )
    session.add(doc)
    session.flush()
    chunk_a = AuthorityDocumentChunk(
        authority_document_id=doc.id,
        chunk_index=0,
        content="First chunk — says the award is opposed to public policy.",
        token_count=10,
        embedding_model=model,
        embedding_dimensions=128,
        embedding_json='[0.0, 0.1]',
        embedded_at=datetime.now(UTC),
    )
    chunk_b = AuthorityDocumentChunk(
        authority_document_id=doc.id,
        chunk_index=1,
        content="Second chunk — cites precedent and concludes on Section 34.",
        token_count=10,
        embedding_model=model,
        embedding_dimensions=128,
        embedding_json='[0.2, 0.3]',
        embedded_at=datetime.now(UTC),
    )
    session.add(chunk_a)
    session.add(chunk_b)
    session.commit()
    return doc.id, chunk_b.id


def test_reembed_swaps_every_chunk_and_is_idempotent(client: TestClient) -> None:
    factory = get_session_factory()
    with factory() as session:
        _seed_two_chunks(session, model="bge-small-v1.5")

    # First pass swaps all chunks to the mock model.
    provider = MockProvider(dimensions=64)
    with factory() as session:
        summary = reembed_corpus(session, embedding_provider=provider)
    assert summary.scanned_chunks == 2
    assert summary.reembedded_chunks == 2
    assert summary.failed_chunks == 0

    with factory() as session:
        models = {
            row.embedding_model
            for row in session.scalars(select(AuthorityDocumentChunk))
        }
    assert models == {provider.model}

    # Second pass with the same provider is a no-op — the predicate
    # already matches; nothing to touch.
    with factory() as session:
        again = reembed_corpus(session, embedding_provider=provider)
    assert again.scanned_chunks == 0
    assert again.reembedded_chunks == 0


def test_reembed_force_touches_already_correct_chunks(client: TestClient) -> None:
    factory = get_session_factory()
    with factory() as session:
        _seed_two_chunks(session, model="bge-small-v1.5")

    provider = MockProvider(dimensions=64)
    with factory() as session:
        reembed_corpus(session, embedding_provider=provider)
    # After the first pass, everyone is on the mock model. With force,
    # a rerun should still rewrite every row.
    with factory() as session:
        forced = reembed_corpus(session, embedding_provider=provider, force=True)
    assert forced.scanned_chunks == 2
    assert forced.reembedded_chunks == 2
