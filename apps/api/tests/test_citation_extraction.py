"""Tests for the citation-extraction service."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text

from caseops_api.db.models import (
    AuthorityCitationTreatment,
    AuthorityDocument,
    AuthorityDocumentType,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.citation_extraction import (
    extract_citations_from_text,
    extract_for_one_document,
)


def test_extract_scc_simple() -> None:
    body = "As held in (2018) 6 SCC 1, the petitioner..."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    norm, ctext, reporter = cites[0]
    assert reporter == "scc"
    assert ctext == "(2018) 6 SCC 1"
    assert norm == "scc:2018:6:1"


def test_extract_air_sc() -> None:
    body = "Following AIR 2020 SC 145, the court held..."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    _, ctext, reporter = cites[0]
    assert reporter == "air_sc"
    assert ctext == "AIR 2020 SC 145"


def test_extract_scc_online_sc() -> None:
    body = "See 2023 SCC OnLine SC 1234 for the full discussion."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    _, ctext, reporter = cites[0]
    assert reporter == "scc_online_sc"
    assert ctext == "2023 SCC OnLine SC 1234"


def test_extract_multiple_distinct() -> None:
    body = (
        "As held in (2018) 6 SCC 1, and earlier in AIR 2015 SC 234, "
        "and most recently in 2024 SCC OnLine SC 99..."
    )
    cites = extract_citations_from_text(body)
    assert len(cites) == 3
    reporters = {c[2] for c in cites}
    assert reporters == {"scc", "air_sc", "scc_online_sc"}


def test_dedupe_within_one_doc() -> None:
    """Same citation appearing twice in one judgment yields one row."""
    body = (
        "(2018) 6 SCC 1 holds that... Per (2018) 6 SCC 1, the rule is..."
    )
    cites = extract_citations_from_text(body)
    assert len(cites) == 1


def test_reject_implausible_year() -> None:
    """Citations with year < 1860 or > 2030 are rejected (almost
    certainly parser noise — page numbers being read as years)."""
    body = "(1850) 6 SCC 1 should not match. Nor (2050) 1 SCC 1."
    cites = extract_citations_from_text(body)
    assert cites == []


def test_reject_implausible_page() -> None:
    """Page < 1 or > 99999 rejected."""
    body = "(2018) 6 SCC 0 should not match. (2018) 6 SCC 999999 either."
    cites = extract_citations_from_text(body)
    assert cites == []


def test_handle_punctuation_variants() -> None:
    """S.C.C. with periods + extra spaces should still match."""
    body = "(2018) 6 S.C.C. 1 is binding."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "scc"


def test_empty_text_returns_empty() -> None:
    assert extract_citations_from_text("") == []
    assert extract_citations_from_text(None) == []  # type: ignore[arg-type]


def test_extract_scr() -> None:
    body = "See (2018) 13 SCR 1 for context."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "scr"
    assert cites[0][1] == "(2018) 13 SCR 1"


def test_extract_crlj() -> None:
    body = "(2017) 4 CrLJ 5421 was followed."
    cites = extract_citations_from_text(body)
    assert len(cites) == 1
    assert cites[0][2] == "crlj"


# ---------- PG-006 integration tests ----------


def _seed_authority_document(text_body: str) -> str:
    """Insert a stub AuthorityDocument with the given text. Returns id.

    Uses the SQLite test session set up by the `client` fixture in
    conftest.py — caller MUST receive `client` so the env vars are
    monkeypatched before this runs.
    """
    factory = get_session_factory()
    s = factory()
    try:
        doc = AuthorityDocument(
            id=str(uuid.uuid4()),
            source="test",
            adapter_name="test",
            court_name="Supreme Court of India",
            forum_level="supreme_court",
            document_type=AuthorityDocumentType.JUDGMENT.value,
            title="Test Judgment",
            canonical_key=f"test/{uuid.uuid4()}",
            summary="x",
            document_text=text_body,
            extracted_char_count=len(text_body),
            ingested_at=datetime.now(UTC),
        )
        s.add(doc)
        s.commit()
        return doc.id
    finally:
        s.close()


def test_extract_for_one_document_writes_treatment_overruled(
    client: TestClient,
) -> None:
    """End-to-end: extract_for_one_document on a citing case with an
    overruled cue verb writes treatment=OVERRULED + non-null evidence
    + non-null confidence on the resulting authority_citations row."""
    _ = client  # only here to trigger the SQLite-env fixture
    body = (
        "The view taken in (2010) 4 SCC 100 stands overruled by the "
        "present Constitution Bench. We hold otherwise."
    )
    src_id = _seed_authority_document(body)
    factory = get_session_factory()
    s = factory()
    try:
        n_extracted, n_resolved, by_reporter = extract_for_one_document(
            s, src_id, body,
        )
        s.commit()
        assert n_extracted == 1
        row = s.execute(
            text(
                "SELECT treatment, treatment_evidence_text, "
                "       treatment_confidence "
                "FROM authority_citations "
                "WHERE source_authority_document_id = :s"
            ),
            {"s": src_id},
        ).fetchone()
        assert row is not None
        treatment, evidence, confidence = row
        assert treatment == AuthorityCitationTreatment.OVERRULED.value
        assert evidence is not None
        assert "overruled" in evidence.lower()
        assert confidence is not None
        assert float(confidence) > 0
    finally:
        s.close()


def test_extract_for_one_document_neutral_when_no_cue(
    client: TestClient,
) -> None:
    """When no cue verb is in the window the row gets treatment=NEUTRAL
    and confidence stays NULL (so the LLM-assisted pass can find it)."""
    _ = client
    body = "The petitioner refers to (2018) 6 SCC 1 in support."
    src_id = _seed_authority_document(body)
    factory = get_session_factory()
    s = factory()
    try:
        extract_for_one_document(s, src_id, body)
        s.commit()
        row = s.execute(
            text(
                "SELECT treatment, treatment_confidence "
                "FROM authority_citations "
                "WHERE source_authority_document_id = :s"
            ),
            {"s": src_id},
        ).fetchone()
        assert row is not None
        treatment, confidence = row
        assert treatment == AuthorityCitationTreatment.NEUTRAL.value
        assert confidence is None
    finally:
        s.close()
