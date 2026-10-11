from __future__ import annotations

import io
import stat
import tarfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentChunk,
    AuthorityDocumentType,
    AuthorityIngestionRun,
)
from caseops_api.scripts import backfill_title_chunks, ingest_corpus
from caseops_api.services import ai_money_budget, corpus_ingest, embeddings
from tests import test_ai_money_embedding_boundary as _sdk_fixtures
from tests.test_ai_money_embedding_boundary import provider, unmarked_offline_request

boundary = _sdk_fixtures.boundary
no_paid_marker = _sdk_fixtures.no_paid_marker


@pytest.fixture(autouse=True)
def forbid_external_staging(monkeypatch):
    def reject():
        pytest.fail("External source SDK must be replaced with an offline fake before use.")

    monkeypatch.setattr(corpus_ingest, "_open_s3_client", reject)


@pytest.fixture
def corpus_session(tmp_path):
    # Isolated file SQLite proves transaction ownership, not PostgreSQL locking/schema parity.
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'corpus.sqlite'}")
    for model in (AuthorityDocument, AuthorityDocumentChunk, AuthorityIngestionRun):
        model.__table__.create(engine)
    try:
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            yield session
    finally:
        engine.dispose()


def seed_documents(session, *, chunks=False, count=4):
    for index in range(count):
        document = AuthorityDocument(
            id=f"document-{index}",
            source="offline-corpus",
            adapter_name="offline",
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type="judgment",
            title=f"Party {index} v. State",
            canonical_key=f"offline-document-{index}",
            summary="Retained source summary",
            document_text="Retained source body",
            ingested_at=datetime(2026, 10, 1, tzinfo=UTC) - timedelta(days=index),
        )
        session.add(document)
        session.flush()
        if chunks:
            session.add(
                AuthorityDocumentChunk(
                    id=f"chunk-{index}",
                    authority_document_id=document.id,
                    chunk_index=0,
                    chunk_role="metadata",
                    content=f"Old header {index}",
                    embedding_model="old-model",
                    embedding_dimensions=4,
                    embedding_json="[1,0,0,0]",
                )
            )
    session.commit()


@pytest.fixture
def money_boundary(boundary, monkeypatch):
    def reserve(**kwargs):
        boundary.reservations.append(kwargs)
        boundary.events.append("reserve:" + kwargs["provider"])
        if len(boundary.reservations) == boundary.deny_at:
            raise ai_money_budget.AiMoneyBudgetError("sentinel-private-money-detail")
        receipt = ai_money_budget.AiMoneyAdmission(
            f"offline-receipt-{len(boundary.reservations)}",
            ai_money_budget.current_budget_month(),
        )
        boundary.receipts.append(receipt)
        return receipt

    monkeypatch.setattr(ai_money_budget, "reserve_paid_ai_call", reserve)
    return boundary


def observe_transactions(adapter, session):
    observed = []
    if adapter.name == "voyage":
        original = adapter._client.embed

        def embed(*args, **kwargs):
            observed.append(session.in_transaction())
            return original(*args, **kwargs)

        adapter._client.embed = embed
    else:
        original = adapter._client.models.embed_content

        def embed(*args, **kwargs):
            observed.append(session.in_transaction())
            return original(*args, **kwargs)

        adapter._client.models.embed_content = embed
    return observed


@pytest.mark.parametrize("name", ["voyage", "gemini"])
@pytest.mark.parametrize("deny_at", [1, 2])
def test_title_money_denial_stops_submission_and_preserves_unprocessed_metadata(
    corpus_session, money_boundary, name, deny_at, caplog
):
    seed_documents(corpus_session, chunks=True)
    money_boundary.deny_at = deny_at
    with unmarked_offline_request():
        summary = backfill_title_chunks._run(
            corpus_session, embedder=provider(name), limit=None, batch_size=1, refresh=True
        )
    # This assertion exercises original behavior before introducing a new error class.
    assert len(money_boundary.reservations) == deny_at, money_boundary.events
    assert len(money_boundary.transports) == deny_at - 1
    assert len(money_boundary.receipts) == deny_at - 1
    assert summary.inserted == deny_at - 1 and summary.errors == 0
    assert summary.stop_reason == "ai_money_budget_denied"
    chunks = list(corpus_session.scalars(select(AuthorityDocumentChunk)))
    assert len(chunks) == 4
    for index in range(deny_at - 1, 4):
        chunk = next(c for c in chunks if c.authority_document_id == f"document-{index}")
        assert chunk.id == f"chunk-{index}" and chunk.content == f"Old header {index}"
        assert chunk.embedding_model == "old-model" and chunk.embedding_json == "[1,0,0,0]"
    assert "sentinel-private-money-detail" not in caplog.text


@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_title_transport_has_no_source_transaction(corpus_session, money_boundary, name):
    seed_documents(corpus_session)
    adapter = provider(name)
    observed = observe_transactions(adapter, corpus_session)
    with unmarked_offline_request():
        summary = backfill_title_chunks._run(
            corpus_session, embedder=adapter, limit=None, batch_size=1
        )
    assert observed == [False] * 4
    assert summary.inserted == 4 and summary.errors == 0


def test_title_nested_sdk_group_denial_keeps_known_usage_without_later_driver_submission(
    corpus_session, money_boundary
):
    seed_documents(corpus_session, chunks=True, count=130)
    money_boundary.deny_at = 2
    with unmarked_offline_request():
        summary = backfill_title_chunks._run(
            corpus_session, embedder=provider("voyage"), limit=None, batch_size=129, refresh=True
        )
    assert len(money_boundary.reservations) == 2 and len(money_boundary.transports) == 1
    assert len(money_boundary.receipts) == 1 and len(money_boundary.transports[0][1]) == 128
    assert len(money_boundary.usage) == 1 and money_boundary.usage[0]["status"] == "ok"
    assert money_boundary.usage[0]["texts_count"] == 128
    assert summary.stop_reason == "ai_money_budget_denied"
    assert summary.inserted == summary.errors == summary.refreshed_dropped == 0
    chunks = list(corpus_session.scalars(select(AuthorityDocumentChunk)))
    assert len(chunks) == 130
    assert all(chunk.embedding_model == "old-model" for chunk in chunks)


def test_financial_stop_preserves_existing_placeholder_quality_gate(corpus_session, money_boundary):
    seed_documents(corpus_session, chunks=True)
    document = corpus_session.get(AuthorityDocument, "document-0")
    document.title = "2026_2_231_238_EN.pdf"
    corpus_session.commit()
    money_boundary.deny_at = 1
    with unmarked_offline_request():
        summary = backfill_title_chunks._run(
            corpus_session, embedder=provider("voyage"), limit=None, batch_size=1, refresh=True
        )
    assert summary.skipped_no_header_data == summary.refreshed_dropped == 1
    assert summary.stop_reason == "ai_money_budget_denied" and summary.errors == 0
    assert corpus_session.get(AuthorityDocumentChunk, "chunk-0") is None
    for index in range(1, 4):
        assert corpus_session.get(AuthorityDocumentChunk, f"chunk-{index}").content == (
            f"Old header {index}"
        )
    assert money_boundary.transports == []


def install_pdf_parser(monkeypatch, directory):
    paths = [directory / f"{index}.pdf" for index in range(4)]
    for path in paths:
        path.write_bytes(b"offline retained PDF")
    parsed_paths = []

    def parse(path, **kwargs):
        parsed_paths.append(path)
        return corpus_ingest.ParsedJudgment(
            title=f"Party {path.stem} v. State",
            court_name="Delhi High Court",
            forum_level="high_court",
            document_type=AuthorityDocumentType.JUDGMENT,
            decision_date=None,
            case_reference=None,
            canonical_key=f"offline-pdf-{path.stem}",
            source="ecourts-hc",
            adapter_name="offline",
            source_reference=path.name,
            summary="Source summary",
            document_text="A reasoned judgment body for offline embedding.",
        )

    monkeypatch.setattr(corpus_ingest, "parse_judgment_pdf", parse)
    return paths, parsed_paths


@pytest.mark.parametrize("name", ["voyage", "gemini"])
@pytest.mark.parametrize("deny_at", [1, 2])
def test_ingest_money_denial_preserves_pdf_and_stops_later_files(
    corpus_session, money_boundary, monkeypatch, tmp_path, name, deny_at, caplog
):
    paths, parsed_paths = install_pdf_parser(monkeypatch, tmp_path)
    money_boundary.deny_at = deny_at
    with unmarked_offline_request():
        summary = corpus_ingest.ingest_local_directory(
            corpus_session, directory=tmp_path, court="hc", forum_level="high_court",
            year=2026, embedding_provider=provider(name), delete_after=True,
        )
    assert paths[deny_at - 1].read_bytes() == b"offline retained PDF"
    assert len(money_boundary.reservations) == deny_at, money_boundary.events
    assert len(parsed_paths) == deny_at and len(money_boundary.transports) == deny_at - 1
    assert summary.inserted_documents == deny_at - 1 and summary.failed_files == 0
    assert summary.stop_reason == "ai_money_budget_denied"
    assert summary.errors == []
    assert all(path.exists() for path in paths[deny_at - 1:])
    assert all(not path.exists() for path in paths[:deny_at - 1])
    documents = list(corpus_session.scalars(select(AuthorityDocument)))
    assert len(documents) == deny_at - 1
    assert all(document.legal_review_status == "unreviewed" for document in documents)
    run = corpus_session.scalars(select(AuthorityIngestionRun)).one()
    assert run.status == "failed" and run.imported_document_count == deny_at - 1
    assert "sentinel-private-money-detail" not in run.summary + caplog.text


@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_ingest_transport_has_no_source_transaction(
    corpus_session, money_boundary, monkeypatch, tmp_path, name
):
    install_pdf_parser(monkeypatch, tmp_path)
    adapter = provider(name)
    observed = observe_transactions(adapter, corpus_session)
    with unmarked_offline_request():
        summary = corpus_ingest.ingest_local_directory(
            corpus_session, directory=tmp_path, court="hc", forum_level="high_court",
            year=2026, embedding_provider=adapter,
        )
    assert observed == [False] * 4
    assert summary.inserted_documents == 4 and summary.failed_files == 0


@pytest.mark.parametrize("name", ["voyage", "gemini"])
@pytest.mark.parametrize("deny_at", [1, 2])
def test_reembed_money_denial_stops_keyset_and_preserves_unprocessed_vectors(
    corpus_session, money_boundary, name, deny_at
):
    seed_documents(corpus_session, chunks=True)
    money_boundary.deny_at = deny_at
    with unmarked_offline_request():
        summary = corpus_ingest.reembed_corpus(
            corpus_session, embedding_provider=provider(name), batch_size=1
        )
    assert len(money_boundary.reservations) == deny_at, money_boundary.events
    assert len(money_boundary.transports) == deny_at - 1
    assert summary.reembedded_chunks == deny_at - 1 and summary.failed_chunks == 0
    assert summary.stop_reason == "ai_money_budget_denied"
    assert summary.errors == []
    chunks = list(corpus_session.scalars(select(AuthorityDocumentChunk)))
    assert len(chunks) == 4
    for index in range(deny_at - 1, 4):
        chunk = next(c for c in chunks if c.id == f"chunk-{index}")
        assert chunk.content == f"Old header {index}" and chunk.embedding_model == "old-model"
        assert chunk.embedding_json == "[1,0,0,0]" and chunk.embedded_at is None


@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_reembed_transport_has_no_source_transaction(corpus_session, money_boundary, name):
    seed_documents(corpus_session, chunks=True)
    adapter = provider(name)
    observed = observe_transactions(adapter, corpus_session)
    with unmarked_offline_request():
        summary = corpus_ingest.reembed_corpus(
            corpus_session, embedding_provider=adapter, batch_size=1
        )
    assert observed == [False] * 4
    assert summary.reembedded_chunks == 4 and summary.failed_chunks == 0


@pytest.mark.parametrize("mode", ["title", "reembed", "ingest"])
def test_ordinary_provider_errors_keep_existing_per_batch_continuation(
    corpus_session, money_boundary, monkeypatch, tmp_path, mode
):
    money_boundary.sdk_error = RuntimeError("offline transient outage")
    if mode != "ingest":
        seed_documents(corpus_session, chunks=mode == "reembed")
    else:
        install_pdf_parser(monkeypatch, tmp_path)
    with unmarked_offline_request():
        adapter = provider("voyage")
        if mode == "title":
            summary = backfill_title_chunks._run(
                corpus_session, embedder=adapter, limit=None, batch_size=1
            )
            assert summary.errors == 4
        elif mode == "reembed":
            summary = corpus_ingest.reembed_corpus(
                corpus_session, embedding_provider=adapter, batch_size=1
            )
            assert summary.failed_chunks == 4
        else:
            summary = corpus_ingest.ingest_local_directory(
                corpus_session, directory=tmp_path, court="hc", forum_level="high_court",
                year=2026, embedding_provider=adapter,
            )
            assert summary.failed_files == 4
    assert len(money_boundary.reservations) == len(money_boundary.transports) == 4


def test_title_cli_money_denial_is_nonzero_and_stops_after_first_batch(
    corpus_session, money_boundary, monkeypatch, capsys
):
    seed_documents(corpus_session)
    money_boundary.deny_at = 1
    monkeypatch.setattr(
        backfill_title_chunks, "get_session_factory", lambda: lambda: corpus_session
    )
    monkeypatch.setattr(backfill_title_chunks, "build_provider", lambda: provider("voyage"))
    with unmarked_offline_request():
        exit_code = backfill_title_chunks.main(["--batch-size", "1"])
    assert exit_code == 1
    assert len(money_boundary.reservations) == 1, money_boundary.events
    assert money_boundary.transports == []
    output = capsys.readouterr().out
    assert "stop_reason=ai_money_budget_denied" in output
    assert "errors=0" in output and "sentinel-private-money-detail" not in output


@pytest.mark.parametrize("reembed", [False, True])
def test_corpus_cli_money_denial_is_nonzero_and_does_not_advance_year(
    corpus_session, money_boundary, monkeypatch, tmp_path, reembed, capsys
):
    money_boundary.deny_at = 1
    monkeypatch.setattr(ingest_corpus, "get_session_factory", lambda: lambda: corpus_session)
    monkeypatch.setattr(corpus_ingest, "build_provider", lambda: provider("voyage"))
    if reembed:
        seed_documents(corpus_session, chunks=True)
        args = ["--reembed", "--batch-size", "1"]
    else:
        install_pdf_parser(monkeypatch, tmp_path)
        args = ["--court", "hc", "--years", "2026,2025", "--path", str(tmp_path)]
    with unmarked_offline_request():
        exit_code = ingest_corpus.main(args)
    assert exit_code == 1
    assert len(money_boundary.reservations) == 1, money_boundary.events
    assert money_boundary.transports == []
    output = capsys.readouterr().out
    assert "year=2025" not in output and "sentinel-private-money-detail" not in output
    assert "ai_money_budget_denied" in output


@pytest.mark.parametrize("name", ["voyage", "gemini"])
@pytest.mark.parametrize("boundary_name", ["reserve", "dispatch"])
def test_real_money_denial_has_distinct_safe_embedding_type(
    money_boundary, monkeypatch, name, boundary_name
):
    money_boundary.deny_at = 1 if boundary_name == "reserve" else None
    if boundary_name == "dispatch":
        def deny_dispatch(receipt):
            assert receipt in money_boundary.receipts
            raise ai_money_budget.AiMoneyBudgetError("sentinel-private-money-detail")

        monkeypatch.setattr(ai_money_budget, "assert_paid_ai_dispatch", deny_dispatch)
    with (
        unmarked_offline_request(),
        pytest.raises(embeddings.EmbeddingMoneyBudgetError) as caught,
    ):
        provider(name).embed(["offline source"])
    assert isinstance(caught.value, embeddings.EmbeddingProviderError)
    assert isinstance(caught.value.__cause__, ai_money_budget.AiMoneyBudgetError)
    assert "Check billing reconciliation and available budget" in str(caught.value)
    assert "sentinel-private" not in str(caught.value)
    assert money_boundary.transports == [] and money_boundary.usage == []
    assert len(money_boundary.receipts) == (1 if boundary_name == "dispatch" else 0)


@pytest.mark.parametrize("name", ["voyage", "gemini"])
def test_nonfinancial_provider_error_is_not_reclassified_as_money_denial(boundary, name):
    boundary.budget_error = "ordinary legacy provider failure"
    with unmarked_offline_request(), pytest.raises(embeddings.EmbeddingProviderError) as caught:
        provider(name).embed(["offline source"])
    assert not isinstance(caught.value, embeddings.EmbeddingMoneyBudgetError)
    assert boundary.transports == []


def invoke_driver(operation, session, adapter, directory):
    if operation == "title":
        return backfill_title_chunks._run(
            session, embedder=adapter, limit=None, batch_size=1
        )
    if operation == "reembed":
        return corpus_ingest.reembed_corpus(session, embedding_provider=adapter, batch_size=1)
    if operation == "ingest":
        return corpus_ingest.ingest_local_directory(
            session, directory=directory, court="hc", forum_level="high_court",
            year=2026, embedding_provider=adapter,
        )
    if operation in {"hc", "sc"}:
        ingest = (
            corpus_ingest.ingest_hc_from_s3
            if operation == "hc" else corpus_ingest.ingest_sc_from_s3
        )
        return ingest(session, year=2026, temp_root=directory, embedding_provider=adapter)
    parsed = corpus_ingest.ParsedJudgment(
        title="Other Party v. State", court_name="Delhi High Court", forum_level="high_court",
        document_type=AuthorityDocumentType.JUDGMENT, decision_date=None, case_reference=None,
        canonical_key="new-offline-document", source="offline", adapter_name="offline",
        source_reference="new.pdf", summary="Source", document_text="Reasoned source text.",
    )
    return corpus_ingest.persist_judgment(session, parsed=parsed, embedding_provider=adapter)


@pytest.mark.parametrize("operation", ["title", "reembed", "ingest", "persist", "hc", "sc"])
@pytest.mark.parametrize("write_kind", ["staged", "flushed", "core", "savepoint"])
def test_transport_admission_rejects_without_discarding_caller_writes(
    corpus_session, money_boundary, tmp_path, operation, write_kind
):
    seed_documents(corpus_session, chunks=True)
    if write_kind == "core":
        corpus_session.execute(
            update(AuthorityDocument).where(AuthorityDocument.id == "document-0")
            .values(title="Caller retained v. State")
        )
    else:
        if write_kind == "savepoint":
            corpus_session.begin_nested()
        doc = corpus_session.get(AuthorityDocument, "document-0")
        doc.title = "Caller retained v. State"
        if write_kind in {"flushed", "savepoint"}:
            corpus_session.flush()
    with unmarked_offline_request(), pytest.raises(HTTPException) as caught:
        invoke_driver(operation, corpus_session, provider("voyage"), tmp_path)
    assert caught.value.status_code == 409 and corpus_session.in_transaction()
    assert money_boundary.reservations == [] and money_boundary.transports == []
    corpus_session.commit()
    with Session(corpus_session.get_bind()) as retained:
        assert retained.get(AuthorityDocument, "document-0").title == "Caller retained v. State"


@pytest.mark.parametrize("operation", ["title", "reembed", "ingest", "persist", "hc", "sc"])
def test_transport_admission_rejects_caller_owned_connection_transaction(
    corpus_session, money_boundary, tmp_path, operation
):
    seed_documents(corpus_session, chunks=True)
    engine = corpus_session.get_bind()
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            update(AuthorityDocument).where(AuthorityDocument.id == "document-0")
            .values(title="External caller v. State")
        )
        with Session(bind=connection, join_transaction_mode="control_fully") as supplied:
            with unmarked_offline_request(), pytest.raises(HTTPException) as caught:
                invoke_driver(operation, supplied, provider("voyage"), tmp_path)
            assert caught.value.status_code == 409
            assert transaction.is_active and not supplied.in_transaction()
            transaction.commit()
    assert money_boundary.reservations == [] and money_boundary.transports == []
    with Session(engine) as retained:
        assert retained.get(AuthorityDocument, "document-0").title == "External caller v. State"


def test_reembedding_does_not_overwrite_a_source_changed_during_transport(
    corpus_session, money_boundary
):
    seed_documents(corpus_session, chunks=True)
    adapter = provider("voyage")
    original = adapter._client.embed

    def embed(texts, **kwargs):
        assert not corpus_session.in_transaction()
        if texts == ["Old header 1"]:
            with Session(corpus_session.get_bind()) as writer:
                chunk = writer.get(AuthorityDocumentChunk, "chunk-1")
                chunk.content = "Corrected source body"
                writer.commit()
        return original(texts, **kwargs)

    adapter._client.embed = embed
    with unmarked_offline_request():
        summary = corpus_ingest.reembed_corpus(
            corpus_session, embedding_provider=adapter, batch_size=1
        )
    assert summary.reembedded_chunks == 3 and summary.failed_chunks == 1
    assert summary.stop_reason is None
    chunk = corpus_session.get(AuthorityDocumentChunk, "chunk-1")
    assert chunk.content == "Corrected source body" and chunk.embedding_model == "old-model"
    assert chunk.embedding_json == "[1,0,0,0]"
    assert len(money_boundary.receipts) == len(money_boundary.transports) == 4


@pytest.mark.parametrize(
    "changed_field", ["title", "parties_json", "content_hash", "source_version"]
)
def test_title_rechecks_current_source_before_replacing_metadata(
    corpus_session, money_boundary, changed_field
):
    seed_documents(corpus_session, chunks=True)
    adapter = provider("voyage")
    original = adapter._client.embed

    def embed(texts, **kwargs):
        assert not corpus_session.in_transaction()
        if texts[0].startswith("Party 1 v. State"):
            with Session(corpus_session.get_bind()) as writer:
                document = writer.get(AuthorityDocument, "document-1")
                setattr(document, changed_field, {
                    "title": "Corrected Party v. State",
                    "parties_json": '["Corrected Party", "State"]',
                    "content_hash": "f" * 64,
                    "source_version": "corrected-source-version",
                }[changed_field])
                writer.commit()
        return original(texts, **kwargs)

    adapter._client.embed = embed
    with unmarked_offline_request():
        summary = backfill_title_chunks._run(
            corpus_session, embedder=adapter, limit=None, batch_size=1, refresh=True
        )
    assert summary.inserted == 3 and summary.errors == 1 and summary.refreshed_dropped == 3
    assert summary.stop_reason is None
    chunk = corpus_session.get(AuthorityDocumentChunk, "chunk-1")
    assert chunk is not None and chunk.content == "Old header 1"
    assert chunk.embedding_model == "old-model" and chunk.embedding_json == "[1,0,0,0]"
    assert len(money_boundary.receipts) == len(money_boundary.transports) == 4


def test_reembed_warmed_aware_timestamp_survives_sqlite_reload_without_false_conflict(
    corpus_session, money_boundary
):
    seed_documents(corpus_session, chunks=True)
    retained_chunks = list(corpus_session.scalars(select(AuthorityDocumentChunk)))
    for chunk in retained_chunks:
        chunk.embedded_at = datetime(2026, 10, 1, tzinfo=UTC)
    corpus_session.commit()
    assert all(chunk.embedded_at.tzinfo is UTC for chunk in retained_chunks)
    with unmarked_offline_request():
        summary = corpus_ingest.reembed_corpus(
            corpus_session, embedding_provider=provider("voyage"), batch_size=4, force=True
        )
    assert summary.reembedded_chunks == 4 and summary.failed_chunks == 0
    assert summary.errors == [] and summary.stop_reason is None
    assert all(chunk.embedding_model == "voyage-4-large" for chunk in retained_chunks)
    assert len(money_boundary.receipts) == len(money_boundary.transports) == 1


@pytest.mark.parametrize("court", ["hc", "sc"])
@pytest.mark.parametrize("deny_at", [1, 2, None])
def test_s3_money_stop_preserves_staged_pdfs_and_stops_later_downloads(
    corpus_session, money_boundary, monkeypatch, tmp_path, court, deny_at
):
    root = tmp_path / "staging"
    root.mkdir()
    install_pdf_parser(monkeypatch, tmp_path)
    downloads = []
    listed = []

    def keys(client, *, prefix, **kwargs):
        listed.append(prefix)
        return iter(["0.pdf", "1.pdf", "2.pdf", "3.pdf"] if court == "hc" else ["0.tar", "1.tar"])

    def download(bucket, key, destination):
        downloads.append(key)
        if court == "hc":
            Path(destination).write_bytes(b"offline retained PDF")
        else:
            with tarfile.open(destination, "w") as archive:
                for index in range(2):
                    data = b"offline retained PDF"
                    info = tarfile.TarInfo(f"{len(downloads) - 1}-{index}.pdf")
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

    monkeypatch.setattr(corpus_ingest, "_iter_s3_keys", keys)
    monkeypatch.setattr(
        corpus_ingest, "_open_s3_client", lambda: SimpleNamespace(download_file=download)
    )
    money_boundary.deny_at = deny_at
    with unmarked_offline_request():
        if court == "hc":
            summary = corpus_ingest.ingest_hc_from_s3(
                corpus_session, year=2026, limit=4, batch_size=2, temp_root=root,
                embedding_provider=provider("voyage"),
                hc_courts=[("delhi", "Delhi High Court"), ("bombay", "Bombay High Court")],
            )
        else:
            summary = corpus_ingest.ingest_sc_from_s3(
                corpus_session, year=2026, limit=2, temp_root=root,
                embedding_provider=provider("voyage"),
            )
    if deny_at is None:
        assert summary.stop_reason is None and summary.failed_files == 0
        assert list(root.iterdir()) == []
        assert len(downloads) == (8 if court == "hc" else 2)
    else:
        assert summary.stop_reason == "ai_money_budget_denied" and summary.failed_files == 0
        assert len(money_boundary.reservations) == deny_at
        assert len(money_boundary.transports) == summary.inserted_documents == deny_at - 1
        assert len(downloads) == (2 if court == "hc" else 1) and len(listed) == 1
        retained = list(root.rglob("*.pdf"))
        assert len(retained) == 3 - deny_at
        assert all(path.read_bytes() == b"offline retained PDF" for path in retained)


@pytest.mark.parametrize("court", ["hc", "sc"])
def test_repeated_remote_denial_does_not_accumulate_unprocessed_workdirs(
    corpus_session, money_boundary, monkeypatch, tmp_path, court
):
    root = tmp_path / "staging"
    root.mkdir()
    install_pdf_parser(monkeypatch, tmp_path)
    downloads = []

    def download(bucket, key, destination):
        downloads.append(key)
        if court == "hc":
            Path(destination).write_bytes(b"offline retained PDF")
        else:
            with tarfile.open(destination, "w") as archive:
                data = b"offline retained PDF"
                info = tarfile.TarInfo("retained.pdf")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def deny(**kwargs):
        money_boundary.reservations.append(kwargs)
        raise ai_money_budget.AiMoneyBudgetError("offline denial")

    monkeypatch.setattr(ai_money_budget, "reserve_paid_ai_call", deny)
    monkeypatch.setattr(
        corpus_ingest, "_iter_s3_keys",
        lambda *args, **kwargs: iter(["source.pdf" if court == "hc" else "source.tar"]),
    )
    monkeypatch.setattr(
        corpus_ingest, "_open_s3_client", lambda: SimpleNamespace(download_file=download)
    )
    ingest = corpus_ingest.ingest_hc_from_s3 if court == "hc" else corpus_ingest.ingest_sc_from_s3
    with unmarked_offline_request():
        first = ingest(
            corpus_session, year=2026, temp_root=root, embedding_provider=provider("voyage")
        )
        retained = {path: path.read_bytes() for path in root.rglob("*.pdf")}
        second = ingest(
            corpus_session, year=2026, temp_root=root, embedding_provider=provider("voyage")
        )
    assert first.stop_reason == "ai_money_budget_denied" and len(retained) == 1
    assert len(downloads) == 1, {"downloads": downloads, "workdirs": list(root.iterdir())}
    assert second.stop_reason == "corpus_staging_pending"
    assert len(money_boundary.reservations) == 1 and money_boundary.transports == []
    assert {path: path.read_bytes() for path in root.rglob("*.pdf")} == retained


@pytest.mark.parametrize("court", ["hc", "sc"])
@pytest.mark.parametrize("over_bytes", [False, True])
def test_retained_sources_stop_before_remote_sdk_and_preserve_unrelated_directories(
    corpus_session, money_boundary, tmp_path, court, over_bytes
):
    root = tmp_path / "staging"
    pending = root / ("caseops-sc-legacy" if court == "hc" else "caseops-hc-legacy")
    pending.mkdir(parents=True)
    pdf = pending / "original.pdf"
    data = b"original PDF" if not over_bytes else b"x" * (1024 * 1024 + 1)
    pdf.write_bytes(data)
    unrelated = root / "not-caseops"
    unrelated.mkdir()
    (unrelated / "keep.pdf").write_bytes(b"unrelated original")
    ingest = corpus_ingest.ingest_hc_from_s3 if court == "hc" else corpus_ingest.ingest_sc_from_s3
    summary = ingest(corpus_session, year=2026, temp_root=root, max_workdir_mb=1)
    assert summary.stop_reason == (
        "corpus_staging_unavailable" if over_bytes else "corpus_staging_pending"
    )
    assert summary.processed_files == summary.failed_files == 0
    assert money_boundary.reservations == money_boundary.transports == []
    assert pdf.read_bytes() == data
    assert (unrelated / "keep.pdf").read_bytes() == b"unrelated original"
    assert set(root.iterdir()) == {pending, unrelated}
    if not over_bytes:
        assert f"1 pending candidate(s), 1 file(s), {len(data)} bytes" in summary.errors[0]
        assert "--path" in summary.errors[0] and "billing recovery" in summary.errors[0]


def test_staging_inventory_bounds_total_entries_without_scanning_unrelated_children(
    monkeypatch, tmp_path
):
    pending = tmp_path / "caseops-hc-legacy"
    pending.mkdir()
    for index in range(8):
        (pending / f"{index}.pdf").write_bytes(b"retained")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "do-not-scan.pdf").write_bytes(b"unrelated")
    visited = []
    inspected = []
    original = corpus_ingest.os.scandir

    @contextmanager
    def scan(path):
        visited.append(Path(path))
        with original(path) as entries:
            def bounded_entries():
                for entry in entries:
                    inspected.append(entry.path)
                    yield entry
            yield bounded_entries()

    monkeypatch.setattr(corpus_ingest, "_STAGING_SCAN_LIMIT", 5)
    monkeypatch.setattr(corpus_ingest.os, "scandir", scan)
    with pytest.raises(ValueError, match="entry bound"):
        corpus_ingest._staging_inventory(tmp_path.resolve(), 1024 * 1024)
    assert len(inspected) == 6  # One overflow detection, not a silently truncated inventory.
    assert visited == [tmp_path, pending] and unrelated not in visited
    assert len(list(pending.iterdir())) == 8


@pytest.mark.parametrize("failure", ["alias", "unreadable"])
def test_staging_inventory_fails_closed_without_following_aliases_or_removing_sources(
    corpus_session, monkeypatch, tmp_path, failure
):
    pending = tmp_path / "caseops-sc-legacy"
    pending.mkdir()
    pdf = pending / "original.pdf"
    pdf.write_bytes(b"original")
    visited = []
    original = corpus_ingest.os.scandir

    @contextmanager
    def scan(path):
        visited.append(Path(path))
        if Path(path) == pending:
            raise PermissionError("offline inaccessible directory")
        with original(path) as entries:
            if failure == "alias":
                yield iter([
                    SimpleNamespace(
                        name=pending.name, path=str(pending),
                        stat=lambda **kwargs: SimpleNamespace(st_mode=stat.S_IFLNK),
                    )
                ])
            else:
                yield entries

    monkeypatch.setattr(corpus_ingest.os, "scandir", scan)
    summary = corpus_ingest.ingest_sc_from_s3(corpus_session, year=2026, temp_root=tmp_path)
    assert summary.stop_reason == "corpus_staging_unavailable" and pdf.read_bytes() == b"original"
    assert visited == ([tmp_path] if failure == "alias" else [tmp_path, pending])


def test_staging_atomic_admission_preserves_an_intervening_claim(monkeypatch, tmp_path):
    original = corpus_ingest._staging_available
    other = tmp_path / corpus_ingest._STAGING_SLOT

    def available(root, max_workdir_mb, summary):
        admitted = original(root, max_workdir_mb, summary)
        other.mkdir()
        (other / "other-worker.pdf").write_bytes(b"another invocation owns this source")
        return admitted

    monkeypatch.setattr(corpus_ingest, "_staging_available", available)
    summary = corpus_ingest.IngestionSummary()
    assert corpus_ingest._create_staging_workdir(tmp_path, "caseops-hc-", 500, summary) is None
    assert summary.stop_reason == "corpus_staging_pending"
    assert list(other.iterdir()) == [other / "other-worker.pdf"]
    assert (other / "other-worker.pdf").read_bytes() == b"another invocation owns this source"


def test_staging_cleanup_cannot_remove_an_unowned_computed_path(tmp_path):
    unrelated = tmp_path / "caseops-hc-not-a-slot-child"
    unrelated.mkdir()
    pdf = unrelated / "keep.pdf"
    pdf.write_bytes(b"original")
    corpus_ingest._finish_staging_workdir(unrelated, tmp_path, retain=False)
    assert pdf.read_bytes() == b"original"
