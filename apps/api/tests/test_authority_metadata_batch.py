from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.base import Base
from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk, ModelRun
from caseops_api.db.session import clear_engine_cache, get_engine, get_session_factory
from caseops_api.scripts import authority_metadata_batch as batch
from caseops_api.scripts import import_authority_metadata_batch as importer
from caseops_api.scripts import monitor_authority_metadata_batch as monitor
from caseops_api.scripts import submit_authority_metadata_batch as submit


@pytest.fixture
def batch_db(monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[3]
    db_dir = repo_root / ".tmp" / "test-dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"authority-batch-{uuid.uuid4().hex}.db"
    monkeypatch.setenv("CASEOPS_DATABASE_URL", f"sqlite+pysqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "caseops-mock-1")
    get_settings.cache_clear()
    clear_engine_cache()
    Base.metadata.create_all(get_engine())
    yield
    get_settings.cache_clear()
    clear_engine_cache()
    db_path.unlink(missing_ok=True)


def _doc(doc_id: str = "doc-1", structured_version: int | None = None) -> AuthorityDocument:
    return AuthorityDocument(
        id=doc_id,
        source="ecourts",
        adapter_name="corpus-ingest",
        court_name="Delhi High Court",
        forum_level="high_court",
        document_type="judgment",
        title="Old Title",
        case_reference=None,
        decision_date=date(2024, 1, 5),
        canonical_key=f"k-{doc_id}",
        source_reference="DLHC0001_2024-01-05.pdf",
        summary="fixture summary",
        document_text="Old Title\nThe petitioner argued facts. The court allowed the petition.",
        extracted_char_count=5000,
        structured_version=structured_version,
    )


def _payload() -> dict[str, object]:
    return {
        "case_title": "Arun Kumar v. Union of India",
        "judges": ["Justice A"],
        "parties": {"appellant": "Arun Kumar", "respondents": ["Union of India"]},
        "advocates": {"appellant_side": ["A. Counsel"], "respondent_side": ["R. Counsel"]},
        "case_number": "W.P.(C) 1/2024",
        "sections_cited": ["Art. 226"],
        "outcome": "Petition allowed",
        "chunks": [
            {
                "chunk_index": 0,
                "role": "facts",
                "sections_cited": ["Art. 226"],
                "authorities_cited": [],
                "outcome_tag": None,
                "related_chunk_indexes": [],
            }
        ],
    }


def _batch_line(doc_id: str = "doc-1") -> dict[str, object]:
    return {
        "custom_id": doc_id,
        "response": {
            "status_code": 200,
            "body": {
                "model": "gpt-5-mini",
                "choices": [{"message": {"content": json.dumps(_payload())}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        },
    }


def test_batch_request_uses_custom_id_and_strict_json_schema() -> None:
    document = _doc()
    chunk = AuthorityDocumentChunk(
        authority_document_id=document.id,
        chunk_index=0,
        content="fixture chunk",
        token_count=3,
    )

    request = batch.build_batch_request(document=document, chunks=[chunk], model="gpt-5-mini")

    assert request["custom_id"] == document.id
    assert request["url"] == "/v1/chat/completions"
    body = request["body"]
    assert body["model"] == "gpt-5-mini"
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert "case_title" in schema["schema"]["required"]


def test_candidate_sql_filters_backlog_language_and_duplicate_ledger() -> None:
    sql = batch.candidate_sql(exclude_count=2)

    assert "structured_version IS NULL OR d.structured_version < :target_version" in sql
    assert "d.id != ALL(:exclude_ids)" in sql
    assert "cast(:language as varchar) = 'english'" in sql
    assert ":non_en_suffix" in sql
    assert ":indic_re" in sql
    assert ":cid_re" in sql


def test_local_ledger_tracks_inflight_and_terminal_ids(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"

    batch.append_ledger_event(ledger, {"status": "exported", "custom_ids": ["a", "b"]})
    batch.append_ledger_event(ledger, {"status": "imported", "custom_ids": ["a"]})

    assert batch.load_inflight_doc_ids(ledger) == {"b"}


def test_import_persists_payload_idempotently_and_records_model_run(
    batch_db,
    tmp_path: Path,
) -> None:
    _ = batch_db
    factory = get_session_factory()
    with factory() as session:
        document = _doc()
        session.add(document)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=document.id,
                chunk_index=0,
                content="facts and issue text",
                token_count=5,
                embedding_model="voyage-4-large",
                embedding_dimensions=1024,
                embedding_json="[0.1]",
                chunk_role=None,
            )
        )
        session.commit()

    result_file = tmp_path / "result.jsonl"
    result_file.write_text(json.dumps(_batch_line()) + "\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"

    first = importer.import_results(
        result_files=[result_file],
        ledger_path=ledger,
        quarantine_path=quarantine,
    )
    second = importer.import_results(
        result_files=[result_file],
        ledger_path=ledger,
        quarantine_path=quarantine,
    )

    with factory() as session:
        document = session.get(AuthorityDocument, "doc-1")
        chunk = session.scalar(
            select(AuthorityDocumentChunk).where(
                AuthorityDocumentChunk.authority_document_id == "doc-1"
            )
        )
        runs = list(session.scalars(select(ModelRun)))

    assert first["imported"] == 1
    assert second["skipped"] == 1
    assert document is not None
    assert document.structured_version == 1
    assert document.title == "Arun Kumar v. Union of India"
    assert chunk is not None
    assert chunk.chunk_role == "facts"
    assert len(runs) == 1
    assert runs[0].provider == "openai"
    assert runs[0].model == "gpt-5-mini"


def test_import_strips_nul_bytes_from_batch_metadata(batch_db, tmp_path: Path) -> None:
    _ = batch_db
    factory = get_session_factory()
    with factory() as session:
        document = _doc()
        session.add(document)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=document.id,
                chunk_index=0,
                content="facts and issue text",
                token_count=5,
                embedding_model="voyage-4-large",
                embedding_dimensions=1024,
                embedding_json="[0.1]",
                chunk_role=None,
            )
        )
        session.commit()

    line = _batch_line()
    payload = _payload()
    payload["case_title"] = "Arun\x00 Kumar v. Union of India"
    payload["chunks"][0]["outcome_tag"] = "wife\x00s petition partly allowed"  # type: ignore[index]
    line["response"]["body"]["choices"][0]["message"]["content"] = json.dumps(payload)  # type: ignore[index]
    result_file = tmp_path / "nul.jsonl"
    result_file.write_text(json.dumps(line) + "\n", encoding="utf-8")

    result = importer.import_results(
        result_files=[result_file],
        ledger_path=tmp_path / "ledger.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
    )

    with factory() as session:
        document = session.get(AuthorityDocument, "doc-1")
        chunk = session.scalar(
            select(AuthorityDocumentChunk).where(
                AuthorityDocumentChunk.authority_document_id == "doc-1"
            )
        )

    assert result["imported"] == 1
    assert result["quarantined"] == 0
    assert document is not None
    assert document.title == "Arun Kumar v. Union of India"
    assert chunk is not None
    assert chunk.outcome_tag == "wifes petition partly allowed"


def test_import_quarantines_schema_failures(batch_db, tmp_path: Path) -> None:
    _ = batch_db
    factory = get_session_factory()
    with factory() as session:
        document = _doc()
        session.add(document)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=document.id,
                chunk_index=0,
                content="fixture",
                token_count=1,
            )
        )
        session.commit()

    bad_line = _batch_line()
    bad_line["response"]["body"]["choices"][0]["message"]["content"] = "{not-json"  # type: ignore[index]
    result_file = tmp_path / "bad.jsonl"
    result_file.write_text(json.dumps(bad_line) + "\n", encoding="utf-8")

    result = importer.import_results(
        result_files=[result_file],
        ledger_path=tmp_path / "ledger.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
    )

    assert result["quarantined"] == 1
    assert "doc-1" in (tmp_path / "quarantine.jsonl").read_text(encoding="utf-8")


def test_submit_and_monitor_dry_runs_do_not_require_openai(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "endpoint": "/v1/chat/completions",
            "shards": [{"path": str(tmp_path / "s1.jsonl"), "count": 2}],
        }),
        encoding="utf-8",
    )

    submit_result = submit.submit_manifest(
        manifest_path=manifest,
        ledger_path=tmp_path / "ledger.jsonl",
        dry_run=True,
    )
    monitor_result = monitor.monitor_batches(
        manifest_path=manifest,
        ledger_path=tmp_path / "ledger.jsonl",
        batch_ids=["batch_1"],
        output_dir=tmp_path,
        download_completed=False,
        dry_run=True,
    )

    assert submit_result["submitted"] == [
        {"path": str(tmp_path / "s1.jsonl"), "count": 2, "dry_run": True}
    ]
    assert monitor_result["batch_ids"] == ["batch_1"]


def test_monitor_serializes_openai_request_counts() -> None:
    counts = SimpleNamespace(total=10, completed=8, failed=2)

    assert monitor._jsonable(counts) == {"total": 10, "completed": 8, "failed": 2}
