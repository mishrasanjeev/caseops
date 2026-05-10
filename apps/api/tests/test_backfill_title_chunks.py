from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.base import Base
from caseops_api.db.models import AuthorityDocument, AuthorityDocumentChunk
from caseops_api.db.session import clear_engine_cache, get_engine, get_session_factory
from caseops_api.scripts import backfill_title_chunks as mod
from caseops_api.services.embeddings import MockProvider


@pytest.fixture
def title_db(monkeypatch: pytest.MonkeyPatch):
    repo_root = Path(__file__).resolve().parents[3]
    db_dir = repo_root / ".tmp" / "test-dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"title-chunks-{uuid.uuid4().hex}.db"
    monkeypatch.setenv("CASEOPS_DATABASE_URL", f"sqlite+pysqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "caseops-mock-1")
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_EMBEDDING_MODEL", "caseops-mock-embed")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    get_settings.cache_clear()
    clear_engine_cache()
    Base.metadata.create_all(get_engine())
    yield
    get_settings.cache_clear()
    clear_engine_cache()
    db_path.unlink(missing_ok=True)


def _doc(
    *,
    doc_id: str,
    title: str,
    forum_level: str = "supreme_court",
    court_name: str = "Supreme Court of India",
    decision_date: date | None = date(2024, 1, 1),
    source_reference: str | None = "sc/2024/2024_1_1_10_EN.pdf",
    case_reference: str | None = None,
    neutral_citation: str | None = None,
    parties_json: str | None = None,
) -> AuthorityDocument:
    return AuthorityDocument(
        id=doc_id,
        source="ecourts",
        adapter_name="corpus-ingest",
        court_name=court_name,
        forum_level=forum_level,
        document_type="judgment",
        title=title,
        canonical_key=f"k-{doc_id}",
        source_reference=source_reference,
        case_reference=case_reference,
        neutral_citation=neutral_citation,
        summary="fixture summary",
        document_text="fixture body",
        extracted_char_count=12,
        structured_version=1,
        decision_date=decision_date,
        parties_json=parties_json,
    )


def test_header_excludes_invalid_title_when_parties_recover_case_name() -> None:
    dirty_devanagari_title = "\u092d\u093e\u0930\u0924 \u0928\u094d\u092f\u093e\u092f"
    doc = _doc(
        doc_id="recoverable-parties",
        title=dirty_devanagari_title,
        parties_json=json.dumps({
            "petitioner": ["Arun Kumar"],
            "respondent": ["State of Karnataka"],
        }),
    )

    header = mod._build_header_from_row(doc)

    assert "Arun Kumar v. State of Karnataka" in header
    assert dirty_devanagari_title not in header


def test_header_returns_empty_for_unrecoverable_dirty_title() -> None:
    doc = _doc(
        doc_id="unrecoverable-cid",
        title="Basavaraj (cid:8117) v State",
        parties_json=None,
        case_reference=None,
        neutral_citation=None,
    )

    assert mod._build_header_from_row(doc) == ""


def test_header_omits_non_latin_detail_fields_when_citation_recovers() -> None:
    dirty_devanagari_party = "\u092d\u093e\u0930\u0924 \u0928\u094d\u092f\u093e\u092f"
    doc = _doc(
        doc_id="recoverable-citation",
        title=dirty_devanagari_party,
        neutral_citation="2024 INSC 651",
        parties_json=json.dumps({"petitioner": [dirty_devanagari_party]}),
    )
    doc.bench_name = dirty_devanagari_party

    header = mod._build_header_from_row(doc)

    assert "2024 INSC 651" in header
    assert dirty_devanagari_party not in header


def test_docs_needing_header_filters_invalid_sc_2024_before_limit(title_db) -> None:
    _ = title_db
    factory = get_session_factory()
    with factory() as session:
        session.add_all([
            _doc(
                doc_id="sc2024-good",
                title="Arun Kumar v. State of Karnataka",
                decision_date=date(2024, 1, 1),
            ),
            _doc(
                doc_id="sc2023-dirty",
                title="Short",
                decision_date=date(2023, 1, 1),
                source_reference="sc/2023/2023_1_1_10_EN.pdf",
            ),
            _doc(
                doc_id="hc2024-dirty",
                title="Short",
                forum_level="high_court",
                court_name="Delhi High Court",
                decision_date=date(2024, 1, 1),
                source_reference="delhi/2024/DLHC0001_2024.pdf",
            ),
            _doc(
                doc_id="sc2024-dirty",
                title="Short",
                decision_date=date(2024, 1, 1),
            ),
        ])
        session.commit()

        docs = mod._docs_needing_header(
            session,
            limit=1,
            refresh=True,
            forum_levels=("supreme_court",),
            year=2024,
            invalid_titles_only=True,
        )

    assert [doc.id for doc in docs] == ["sc2024-dirty"]


def test_docs_needing_header_filters_by_exact_court_name(title_db) -> None:
    _ = title_db
    factory = get_session_factory()
    with factory() as session:
        session.add_all([
            _doc(
                doc_id="delhi-2024",
                title="Arun Kumar v. State of Delhi",
                forum_level="high_court",
                court_name="Delhi High Court",
                decision_date=date(2024, 1, 1),
                source_reference="hc/delhi/2024/DLHC0001_2024-01-01.pdf",
            ),
            _doc(
                doc_id="bombay-2024",
                title="Arun Kumar v. State of Maharashtra",
                forum_level="high_court",
                court_name="Bombay High Court",
                decision_date=date(2024, 1, 1),
                source_reference="hc/bombay/2024/BMHC0001_2024-01-01.pdf",
            ),
        ])
        session.commit()

        docs = mod._docs_needing_header(
            session,
            limit=None,
            refresh=True,
            forum_levels=("high_court",),
            court_name="Delhi High Court",
            year=2024,
        )

    assert [doc.id for doc in docs] == ["delhi-2024"]


def test_docs_needing_header_can_filter_to_ids_file_scope(title_db) -> None:
    _ = title_db
    factory = get_session_factory()
    with factory() as session:
        session.add_all([
            _doc(
                doc_id="target-doc",
                title="Arun Kumar v. State of Delhi",
                forum_level="high_court",
                court_name="Delhi High Court",
                decision_date=None,
                source_reference="hc/delhi/2024/DLHC0001_2024-01-01.pdf",
            ),
            _doc(
                doc_id="same-bucket-not-targeted",
                title="Varun Kumar v. State of Delhi",
                forum_level="high_court",
                court_name="Delhi High Court",
                decision_date=None,
                source_reference="hc/delhi/2024/DLHC0002_2024-01-02.pdf",
            ),
        ])
        session.commit()

        docs = mod._docs_needing_header(
            session,
            limit=None,
            refresh=True,
            forum_levels=("high_court",),
            court_name="Delhi High Court",
            year=2024,
            document_ids=("target-doc",),
        )

    assert [doc.id for doc in docs] == ["target-doc"]


def test_refresh_replaces_dirty_metadata_header_with_recovered_parties(title_db) -> None:
    _ = title_db
    dirty_devanagari_title = "\u092d\u093e\u0930\u0924 \u0928\u094d\u092f\u093e\u092f"
    factory = get_session_factory()
    with factory() as session:
        doc = _doc(
            doc_id="refresh-recoverable-parties",
            title=dirty_devanagari_title,
            parties_json=json.dumps({
                "petitioner": ["Arun Kumar"],
                "respondent": ["State of Karnataka"],
            }),
        )
        session.add(doc)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=doc.id,
                chunk_index=0,
                content=f"OLD DIRTY HEADER\n{dirty_devanagari_title}",
                token_count=4,
                embedding_model="old-model",
                embedding_dimensions=8,
                embedding_json="[0.1]",
                chunk_role="metadata",
            )
        )
        session.commit()

        summary = mod._run(
            session,
            embedder=MockProvider(dimensions=8),
            limit=None,
            batch_size=8,
            refresh=True,
            forum_levels=("supreme_court",),
            year=2024,
            invalid_titles_only=True,
        )
        assert summary.inserted == 1
        assert summary.refreshed_dropped == 1

        metadata_chunks = list(
            session.scalars(
                select(AuthorityDocumentChunk).where(
                    AuthorityDocumentChunk.authority_document_id == doc.id,
                    AuthorityDocumentChunk.chunk_role == "metadata",
                )
            )
        )

    assert len(metadata_chunks) == 1
    assert "Arun Kumar v. State of Karnataka" in metadata_chunks[0].content
    assert dirty_devanagari_title not in metadata_chunks[0].content


def test_refresh_dirty_metadata_only_rebuilds_valid_title_with_safe_details(
    title_db,
) -> None:
    _ = title_db
    dirty_devanagari_detail = "\u092d\u093e\u0930\u0924 \u0928\u094d\u092f\u093e\u092f"
    factory = get_session_factory()
    with factory() as session:
        doc = _doc(
            doc_id="refresh-dirty-metadata",
            title="Arun Kumar v. State of Karnataka",
            parties_json=json.dumps({
                "petitioner": ["Arun Kumar"],
                "respondent": [dirty_devanagari_detail],
            }),
        )
        doc.bench_name = dirty_devanagari_detail
        session.add(doc)
        session.flush()
        session.add(
            AuthorityDocumentChunk(
                authority_document_id=doc.id,
                chunk_index=0,
                content=f"Arun Kumar v. State\n{dirty_devanagari_detail}",
                token_count=5,
                embedding_model="old-model",
                embedding_dimensions=8,
                embedding_json="[0.1]",
                chunk_role="metadata",
            )
        )
        session.commit()

        summary = mod._run(
            session,
            embedder=MockProvider(dimensions=8),
            limit=None,
            batch_size=8,
            refresh=True,
            forum_levels=("supreme_court",),
            year=2024,
            dirty_metadata_only=True,
        )

        metadata_chunks = list(
            session.scalars(
                select(AuthorityDocumentChunk).where(
                    AuthorityDocumentChunk.authority_document_id == doc.id,
                    AuthorityDocumentChunk.chunk_role == "metadata",
                )
            )
        )

    assert summary.inserted == 1
    assert summary.refreshed_dropped == 1
    assert len(metadata_chunks) == 1
    assert "Arun Kumar v. State of Karnataka" in metadata_chunks[0].content
    assert dirty_devanagari_detail not in metadata_chunks[0].content
