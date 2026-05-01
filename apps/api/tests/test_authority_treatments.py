"""PG-006 Phase 1B — authority-treatment summarizer + route + validator.

Covers:
- summarize_treatments returns one bucket per treatment with samples,
  worst_treatment correctly picks overruled > reversed > doubted.
- compute_search_result_treatments bulk-resolves the page in one query
  and returns (worst, adverse_count) per id.
- find_authorities_with_adverse_treatment resolves citation strings
  against authority_documents.neutral_citation / case_reference and
  filters down to adverse-only authorities.
- check_adverse_treatment emits a DraftFinding when any cited
  authority has an adverse incoming citation.
- GET /api/authorities/{id}/treatments returns the same data.
"""
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
from caseops_api.services.authority_treatments import (
    compute_search_result_treatments,
    find_authorities_with_adverse_treatment,
    summarize_treatments,
)
from caseops_api.services.draft_validators import check_adverse_treatment
from tests.test_auth_company import auth_headers, bootstrap_company

# -----------------------------
# Helpers
# -----------------------------


def _seed_authority(
    *,
    title: str,
    neutral_citation: str | None = None,
    case_reference: str | None = None,
    document_text: str = "x",
) -> str:
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
            title=title,
            canonical_key=f"test/{uuid.uuid4()}",
            summary="x",
            neutral_citation=neutral_citation,
            case_reference=case_reference,
            document_text=document_text,
            extracted_char_count=len(document_text),
            ingested_at=datetime.now(UTC),
        )
        s.add(doc)
        s.commit()
        return doc.id
    finally:
        s.close()


def _insert_citation(
    *,
    source_id: str,
    cited_id: str | None,
    citation_text: str,
    treatment: AuthorityCitationTreatment,
    confidence: float | None = 0.7,
) -> None:
    factory = get_session_factory()
    s = factory()
    try:
        s.execute(
            text(
                "INSERT INTO authority_citations "
                "(id, source_authority_document_id, "
                " cited_authority_document_id, citation_text, "
                " normalized_reference, treatment, "
                " treatment_evidence_text, treatment_confidence, "
                " treatment_classified_at, created_at) "
                "VALUES (:id, :src, :cited, :ctext, :norm, :t, "
                " :ev, :conf, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()),
                "src": source_id,
                "cited": cited_id,
                "ctext": citation_text,
                "norm": citation_text.lower(),
                "t": treatment.value,
                "ev": f"...{treatment.value} cue snippet...",
                "conf": confidence,
            },
        )
        s.commit()
    finally:
        s.close()


# -----------------------------
# summarize_treatments
# -----------------------------


def test_summary_empty_when_no_incoming(client: TestClient) -> None:
    _ = client
    aid = _seed_authority(title="Quiet Case", neutral_citation="(2020) 1 SCC 1")
    factory = get_session_factory()
    s = factory()
    try:
        summary = summarize_treatments(s, aid)
    finally:
        s.close()
    assert summary.total_incoming == 0
    assert summary.adverse_count == 0
    assert summary.has_adverse_treatment is False
    assert summary.worst_treatment is None
    assert summary.buckets == []


def test_summary_picks_overruled_as_worst(client: TestClient) -> None:
    """Overruled beats reversed beats doubted in the worst-treatment
    pick when all three are present in the incoming graph."""
    _ = client
    target_id = _seed_authority(title="Target Case")
    src_overruled = _seed_authority(title="Overruling Case A")
    src_reversed = _seed_authority(title="Reversing Case B")
    src_doubted = _seed_authority(title="Doubting Case C")
    src_followed = _seed_authority(title="Following Case D")

    _insert_citation(
        source_id=src_overruled, cited_id=target_id,
        citation_text="(2020) 1 SCC 1",
        treatment=AuthorityCitationTreatment.OVERRULED,
    )
    _insert_citation(
        source_id=src_reversed, cited_id=target_id,
        citation_text="(2020) 1 SCC 1",
        treatment=AuthorityCitationTreatment.REVERSED,
    )
    _insert_citation(
        source_id=src_doubted, cited_id=target_id,
        citation_text="(2020) 1 SCC 1",
        treatment=AuthorityCitationTreatment.DOUBTED,
    )
    _insert_citation(
        source_id=src_followed, cited_id=target_id,
        citation_text="(2020) 1 SCC 1",
        treatment=AuthorityCitationTreatment.FOLLOWED,
    )

    factory = get_session_factory()
    s = factory()
    try:
        summary = summarize_treatments(s, target_id)
    finally:
        s.close()
    assert summary.total_incoming == 4
    assert summary.adverse_count == 3  # overruled + reversed + doubted
    assert summary.has_adverse_treatment is True
    assert (
        summary.worst_treatment == AuthorityCitationTreatment.OVERRULED.value
    )
    bucket_codes = {b.treatment for b in summary.buckets}
    assert AuthorityCitationTreatment.OVERRULED.value in bucket_codes
    assert AuthorityCitationTreatment.FOLLOWED.value in bucket_codes


def test_summary_caps_samples(client: TestClient) -> None:
    """When five citing cases give the same treatment we only keep
    samples_per_bucket=3 by default."""
    _ = client
    target_id = _seed_authority(title="Heavily Cited")
    for i in range(5):
        src = _seed_authority(title=f"Citing {i}")
        _insert_citation(
            source_id=src, cited_id=target_id,
            citation_text="(2020) 1 SCC 1",
            treatment=AuthorityCitationTreatment.FOLLOWED,
        )
    factory = get_session_factory()
    s = factory()
    try:
        summary = summarize_treatments(s, target_id)
    finally:
        s.close()
    [followed] = [
        b for b in summary.buckets
        if b.treatment == AuthorityCitationTreatment.FOLLOWED.value
    ]
    assert followed.count == 5
    assert len(followed.samples) == 3


# -----------------------------
# compute_search_result_treatments (bulk path)
# -----------------------------


def test_compute_bulk_returns_only_adverse_ids(client: TestClient) -> None:
    _ = client
    target_overruled = _seed_authority(title="Bad Law Case")
    target_clean = _seed_authority(title="Clean Case")
    src = _seed_authority(title="Citing Source")
    _insert_citation(
        source_id=src, cited_id=target_overruled,
        citation_text="(2018) 6 SCC 1",
        treatment=AuthorityCitationTreatment.OVERRULED,
    )
    _insert_citation(
        source_id=src, cited_id=target_clean,
        citation_text="(2019) 5 SCC 100",
        treatment=AuthorityCitationTreatment.FOLLOWED,
    )
    factory = get_session_factory()
    s = factory()
    try:
        out = compute_search_result_treatments(
            s, [target_overruled, target_clean],
        )
    finally:
        s.close()
    # Bad-law case has an entry; clean case is absent (no adverse).
    assert target_overruled in out
    assert out[target_overruled] == (
        AuthorityCitationTreatment.OVERRULED.value, 1,
    )
    assert target_clean not in out


def test_compute_bulk_empty_input(client: TestClient) -> None:
    _ = client
    factory = get_session_factory()
    s = factory()
    try:
        assert compute_search_result_treatments(s, []) == {}
    finally:
        s.close()


# -----------------------------
# find_authorities_with_adverse_treatment
# -----------------------------


def test_resolve_by_neutral_citation(client: TestClient) -> None:
    _ = client
    target = _seed_authority(
        title="Bad Law Case",
        neutral_citation="(2018) 6 SCC 1",
    )
    src = _seed_authority(title="Overruling Source")
    _insert_citation(
        source_id=src, cited_id=target,
        citation_text="(2018) 6 SCC 1",
        treatment=AuthorityCitationTreatment.OVERRULED,
    )
    factory = get_session_factory()
    s = factory()
    try:
        out = find_authorities_with_adverse_treatment(
            s, ["(2018) 6 SCC 1", "AIR 2099 SC 0"],  # second is unknown
        )
    finally:
        s.close()
    assert target in out
    assert out[target].has_adverse_treatment is True


# -----------------------------
# check_adverse_treatment validator
# -----------------------------


def test_validator_emits_finding_on_adverse(client: TestClient) -> None:
    _ = client
    target = _seed_authority(
        title="Overruled Case",
        neutral_citation="(2010) 4 SCC 100",
    )
    src = _seed_authority(title="Overruling Source")
    _insert_citation(
        source_id=src, cited_id=target,
        citation_text="(2010) 4 SCC 100",
        treatment=AuthorityCitationTreatment.OVERRULED,
    )
    factory = get_session_factory()
    s = factory()
    try:
        findings = check_adverse_treatment(s, ["(2010) 4 SCC 100"])
    finally:
        s.close()
    assert len(findings) == 1
    assert findings[0].code == "citation.adverse_treatment"
    assert findings[0].severity == "warning"
    assert "overruled" in findings[0].message.lower()


def test_validator_silent_when_no_adverse(client: TestClient) -> None:
    _ = client
    target = _seed_authority(
        title="Clean Case",
        neutral_citation="(2018) 6 SCC 1",
    )
    src = _seed_authority(title="Following Source")
    _insert_citation(
        source_id=src, cited_id=target,
        citation_text="(2018) 6 SCC 1",
        treatment=AuthorityCitationTreatment.FOLLOWED,
    )
    factory = get_session_factory()
    s = factory()
    try:
        findings = check_adverse_treatment(s, ["(2018) 6 SCC 1"])
    finally:
        s.close()
    assert findings == []


def test_validator_skips_unknown_citations(client: TestClient) -> None:
    _ = client
    factory = get_session_factory()
    s = factory()
    try:
        # Citation not in corpus → no finding (treatment unknown).
        findings = check_adverse_treatment(s, ["(1999) 1 SCC 1"])
    finally:
        s.close()
    assert findings == []


# -----------------------------
# GET /api/authorities/{id}/treatments
# -----------------------------


def test_treatment_route_returns_summary(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    target = _seed_authority(
        title="Route Smoke Target",
        neutral_citation="(2021) 9 SCC 11",
    )
    src = _seed_authority(title="Citing Source")
    _insert_citation(
        source_id=src, cited_id=target,
        citation_text="(2021) 9 SCC 11",
        treatment=AuthorityCitationTreatment.OVERRULED,
    )

    resp = client.get(
        f"/api/authorities/{target}/treatments",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["authority_document_id"] == target
    assert body["has_adverse_treatment"] is True
    assert body["worst_treatment"] == "overruled"
    assert body["adverse_count"] == 1
    assert any(
        b["treatment"] == "overruled" and b["count"] == 1
        for b in body["buckets"]
    )


def test_treatment_route_requires_auth(client: TestClient) -> None:
    resp = client.get(
        f"/api/authorities/{uuid.uuid4()}/treatments",
    )
    assert resp.status_code in {401, 403}
