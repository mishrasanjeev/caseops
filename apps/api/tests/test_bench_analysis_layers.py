"""Tests for the bench-strategy L-A/L-B/L-C aggregators."""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from caseops_api.db.models import (
    AuthorityCitation,
    AuthorityDocument,
    AuthorityDocumentType,
    AuthorityStatuteReference,
    Court,
    Judge,
    JudgeAlias,
    JudgeAuthorityAffinity,
    JudgeDecisionIndex,
    JudgeMappingReview,
    JudgeStatuteFocus,
    Statute,
    StatuteSection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import bench_analysis_layers as bal
from caseops_api.services.judge_aliases import normalise

pytestmark = pytest.mark.postgres


def _seed_court_and_judges(session, court_id: str, court_name: str) -> dict:
    """Insert court if absent (some conftest paths pre-seed common
    courts; courts table has UNIQUE on both id and name)."""
    existing = session.get(Court, court_id)
    if existing is None:
        existing = session.query(Court).filter(Court.name == court_name).first()
    if existing is None:
        session.add(Court(
            id=court_id, name=court_name, short_name=court_name,
            forum_level="high_court" if court_id != "supreme-court-india" else "supreme_court",
            jurisdiction="india", is_active=True,
        ))
        session.commit()
    else:
        court_id = existing.id  # use whatever the seeded one is

    j1 = Judge(
        id=str(uuid4()), court_id=court_id, full_name="Yashwant Varma",
        honorific="Justice", is_active=True,
    )
    j2 = Judge(
        id=str(uuid4()), court_id=court_id, full_name="V. Kameswar Rao",
        honorific="Justice", is_active=True,
    )
    session.add_all([j1, j2])
    session.flush()
    for j, a in [(j1, "Yashwant Varma"), (j1, "Hon'ble Mr. Justice Yashwant Varma"),
                 (j2, "V. Kameswar Rao"), (j2, "V. Kameswar Rao, J.")]:
        session.add(JudgeAlias(
            id=str(uuid4()), judge_id=j.id,
            alias_text=a, alias_normalised=normalise(a),
            source="seed",
        ))
    session.commit()
    return {"j1": j1.id, "j2": j2.id}


def _seed_authority_doc(session, *, court_name, judges, year=2024, doc_id=None):
    doc = AuthorityDocument(
        id=doc_id or str(uuid4()),
        source="test_seed",
        adapter_name="test",
        title="Sample Judgment",
        document_type=AuthorityDocumentType.JUDGMENT,
        court_name=court_name,
        forum_level="high_court",
        decision_date=date(year, 6, 15),
        canonical_key=str(uuid4()),
        summary="test",
        document_text="test",
        judges_json=json.dumps(judges),
    )
    session.add(doc)
    session.commit()
    return doc.id


def test_la_inserts_judge_decision_index_with_alias_match(
    isolated_postgres_client: TestClient,
) -> None:
    factory = get_session_factory()
    with factory() as session:
        judges = _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        # Doc with both judges (variant spellings)
        _seed_authority_doc(
            session,
            court_name="Delhi High Court",
            judges=["Yashwant Varma", "V. Kameswar Rao, J."],
            year=2024,
        )
        s = bal.refresh_judge_decision_index(session)

    assert s.judge_decision_index_inserted == 2
    with factory() as session:
        rows = session.query(JudgeDecisionIndex).all()
    assert {r.judge_id for r in rows} == {judges["j1"], judges["j2"]}
    assert all(r.year == 2024 for r in rows)
    assert all(r.role == "sat_on" for r in rows)


def test_la_idempotent_on_rerun(isolated_postgres_client: TestClient) -> None:
    """Second call must not double-insert."""
    factory = get_session_factory()
    with factory() as session:
        _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        _seed_authority_doc(
            session,
            court_name="Delhi High Court",
            judges=["Yashwant Varma"],
            year=2024,
        )
        bal.refresh_judge_decision_index(session)
        s2 = bal.refresh_judge_decision_index(session)
    assert s2.judge_decision_index_inserted == 0  # already-inserted skipped
    with factory() as session:
        assert session.query(JudgeDecisionIndex).count() == 1


def test_la_skips_unknown_court(isolated_postgres_client: TestClient) -> None:
    """A doc whose court_name doesn't match any known court_id is
    skipped (not inserted)."""
    factory = get_session_factory()
    with factory() as session:
        _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        unknown_court = f"Unlisted Bench Fixture {uuid4().hex}"
        assert session.query(Court).filter(Court.name == unknown_court).first() is None
        document_id = _seed_authority_doc(
            session,
            court_name=unknown_court,
            judges=["Yashwant Varma"],
            year=2024,
        )
        s = bal.refresh_judge_decision_index(session)
    assert s.judge_decision_index_inserted == 0
    assert s.skipped_unmatched_judges == 1
    with factory() as session:
        assert session.query(JudgeDecisionIndex).count() == 0
        reviews = session.query(JudgeMappingReview).filter(
            JudgeMappingReview.authority_document_id == document_id
        ).all()
        assert len(reviews) == 1
        assert reviews[0].reason == "unresolved_court"
        assert reviews[0].status == "open"
        assert reviews[0].court_id is None


def test_la_counts_unmatched_judges(isolated_postgres_client: TestClient) -> None:
    """A judge name not in our judges table is counted as
    skipped_unmatched_judges (not silently dropped)."""
    factory = get_session_factory()
    with factory() as session:
        _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        _seed_authority_doc(
            session,
            court_name="Delhi High Court",
            judges=["Yashwant Varma", "Some Random Name Not In Aliases"],
            year=2024,
        )
        s = bal.refresh_judge_decision_index(session)
    assert s.judge_decision_index_inserted == 1  # only Yashwant Varma matches
    assert s.skipped_unmatched_judges == 1


def test_lb_aggregates_citations_per_judge(isolated_postgres_client: TestClient) -> None:
    """L-B groups authority_citations by (judge, cited_authority).
    Uses the migrated PostgreSQL fixture for gen_random_uuid and array_agg."""
    factory = get_session_factory()
    with factory() as session:
        judges = _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        # Judge1 sat on doc1 + doc2; both cite cited_X
        cited_x = _seed_authority_doc(
            session, court_name="Delhi High Court", judges=[], year=2020,
        )
        doc1 = _seed_authority_doc(
            session, court_name="Delhi High Court",
            judges=["Yashwant Varma"], year=2024,
        )
        doc2 = _seed_authority_doc(
            session, court_name="Delhi High Court",
            judges=["Yashwant Varma"], year=2023,
        )
        # Add citations
        for src in [doc1, doc2]:
            session.add(AuthorityCitation(
                id=str(uuid4()),
                source_authority_document_id=src,
                cited_authority_document_id=cited_x,
                citation_text="(2020) 1 SCC 1",
                normalized_reference=f"cited_x:{src}",
            ))
        session.commit()
        bal.refresh_judge_decision_index(session)
        s = bal.refresh_judge_authority_affinity(session)

    assert s.judge_authority_affinity_rows == 1  # one (judge, cited_x) pair
    with factory() as session:
        rows = session.query(JudgeAuthorityAffinity).all()
    assert len(rows) == 1
    assert rows[0].judge_id == judges["j1"]
    assert rows[0].cited_authority_document_id == cited_x
    assert rows[0].citation_count == 2
    assert rows[0].last_year == 2024  # max of 2024, 2023


def test_lc_aggregates_statute_refs_per_judge(isolated_postgres_client: TestClient) -> None:
    """L-C groups authority_statute_references by (judge, section).
    The migrated PostgreSQL fixture owns the global aggregate tables."""
    factory = get_session_factory()
    with factory() as session:
        judges = _seed_court_and_judges(session, "delhi-hc", "Delhi High Court")
        # Statute + section
        statute_id = f"bench-statute-{uuid4().hex}"
        st = Statute(
            id=statute_id, short_name="Bench fixture",
            long_name="Indian Penal Code", enacted_year=1860,
            jurisdiction="india", source_url=None, is_active=True,
        )
        sec = StatuteSection(
            id=str(uuid4()), statute_id=statute_id, section_number="300",
            section_label="Murder", is_active=True, ordinal=1,
        )
        session.add(st)
        session.flush()
        session.add(sec)
        session.flush()
        doc1 = _seed_authority_doc(
            session, court_name="Delhi High Court",
            judges=["Yashwant Varma"], year=2024,
        )
        # statute reference
        session.add(AuthorityStatuteReference(
            authority_id=doc1, section_id=sec.id, source="local_bench_fixture",
        ))
        session.commit()
        bal.refresh_judge_decision_index(session)
        s = bal.refresh_judge_statute_focus(session)

    assert s.judge_statute_focus_rows == 1
    with factory() as session:
        rows = session.query(JudgeStatuteFocus).all()
    assert len(rows) == 1
    assert rows[0].judge_id == judges["j1"]
    assert rows[0].statute_section_id == sec.id
    assert rows[0].citation_count == 1
