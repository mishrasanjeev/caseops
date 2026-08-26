from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.api.routes.courts import _judge_authority_page, _judge_mapping_counts
from caseops_api.db.models import (
    AuthorityDocument,
    Bench,
    Court,
    Judge,
    JudgeAlias,
    JudgeDecisionIndex,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.judge_aliases import normalise
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_catalog(*, name: str = "IPLF 060B Test Court") -> tuple[str, str]:
    court_id = str(uuid4())
    judge_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            Court(
                id=court_id,
                name=f"{name} {court_id}",
                short_name=f"I60B-{court_id[:6]}",
                forum_level="high_court",
                jurisdiction="India",
                is_active=True,
            )
        )
        session.add(
            Judge(
                id=judge_id,
                court_id=court_id,
                full_name="Justice Canonical Example",
                current_position="Puisne Judge",
                source_name="official_court",
                source_url="https://example.gov.in/judges/canonical-example",
                source_reference="official-roster-060b",
                is_active=True,
            )
        )
        session.flush()
        session.add(
            JudgeAlias(
                judge_id=judge_id,
                alias_text="J. Canonical Example",
                alias_normalised=normalise("J. Canonical Example"),
                source="official_court",
                source_url="https://example.gov.in/judges/canonical-example",
            )
        )
        session.commit()
    return court_id, judge_id


def _add_mapping(
    session,
    *,
    court: Court,
    judge_id: str,
    ordinal: int,
    confidence: str = "exact",
    eligible: bool = True,
    source: str = "delhi_high_court_recent_judgments",
    source_reference: str | None = None,
) -> str:
    document = AuthorityDocument(
        source=source,
        adapter_name="iplf-060b-test-v1",
        court_name=court.name,
        forum_level=court.forum_level,
        document_type="judgment",
        title=f"Canonical mapped authority {ordinal}",
        case_reference=f"TEST {ordinal}/2026",
        bench_name="Untrusted free text must not drive identity",
        neutral_citation=f"2026 TEST {ordinal}",
        decision_date=date(2026, 8, ordinal + 1),
        canonical_key=f"iplf-060b:{uuid4()}",
        source_reference=(
            source_reference or f"https://delhihighcourt.nic.in/judgments/060b-{ordinal}.pdf"
        ),
        summary="Bounded source-backed metadata for the judge workflow.",
        judges_json=json.dumps(["Coincidental Name"]),
        sections_cited_json=json.dumps(["Section 11 Arbitration Act"]),
    )
    session.add(document)
    session.flush()
    session.add(
        JudgeDecisionIndex(
            judge_id=judge_id,
            authority_document_id=document.id,
            role="sat_on",
            year=2026,
            matched_alias="J. Canonical Example",
            match_confidence=confidence,
            raw_judge_name="J. Canonical Example",
            source_ordinal=ordinal,
            mapping_status="auto_confirmed" if eligible else "needs_review",
            resolver_version="judge-alias-v2-test",
            evidence_json={"source": "judges_json", "ordinal": ordinal},
            is_analytics_eligible=eligible,
        )
    )
    return document.id


def test_uj20_normal_is_canonical_paginated_source_backed_and_bounded(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    court_id, judge_id = _seed_catalog()
    with get_session_factory()() as session:
        court = session.get(Court, court_id)
        assert court is not None
        for ordinal in range(3):
            _add_mapping(
                session,
                court=court,
                judge_id=judge_id,
                ordinal=ordinal,
                confidence="low" if ordinal == 0 else "exact",
                eligible=ordinal != 0,
            )
        session.add(
            AuthorityDocument(
                source="delhi_high_court_recent_judgments",
                adapter_name="iplf-060b-test-v1",
                court_name=court.name,
                forum_level=court.forum_level,
                document_type="judgment",
                title="Coincidental free-text authority",
                bench_name="Justice Canonical Example",
                decision_date=date(2026, 8, 20),
                canonical_key=f"iplf-060b-unmapped:{uuid4()}",
                source_reference="https://delhihighcourt.nic.in/judgments/unmapped.pdf",
                summary="Raw source record without a canonical judge mapping.",
                judges_json=json.dumps(["Justice Canonical Example"]),
            )
        )
        session.commit()

    profile = client.get(f"/api/courts/judges/{judge_id}", headers=headers)
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["authority_document_count"] == 3
    assert body["analytics_eligible_authority_count"] == 2
    assert body["mapping_coverage_percent"] == 67
    assert body["coverage_state"] == "mapped_results"
    assert body["identity_source_action"]["state"] == "available"
    assert body["aliases"][0]["alias_text"] == "J. Canonical Example"
    assert "Coincidental free-text authority" not in {
        item["title"] for item in body["recent_authorities"]
    }
    low = next(item for item in body["recent_authorities"] if not item["analytics_eligible"])
    assert low["mapping_confidence"] == "low"
    assert low["mapping_evidence"] == {"source": "judges_json", "ordinal": 0}

    listing = client.get(f"/api/courts/{court_id}/judges", headers=headers)
    assert listing.status_code == 200, listing.text
    listed_judge = next(item for item in listing.json()["judges"] if item["id"] == judge_id)
    assert listed_judge["mapped_authority_count"] == 3
    assert listed_judge["analytics_eligible_authority_count"] == 2

    first = client.get(f"/api/courts/judges/{judge_id}/authorities?limit=2", headers=headers)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["returned_count"] == 2
    assert first_body["has_more"] is True
    assert first_body["next_cursor"]
    assert all(
        item["source_action"]["target_type"] == "authority_document"
        for item in first_body["authorities"]
    )

    second = client.get(
        f"/api/courts/judges/{judge_id}/authorities",
        headers=headers,
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["returned_count"] == 1
    assert second.json()["has_more"] is False
    assert {item["id"] for item in first_body["authorities"]}.isdisjoint(
        {item["id"] for item in second.json()["authorities"]}
    )

    with get_session_factory()() as session:
        judge = session.get(Judge, judge_id)
        assert judge is not None
        query_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        event.listen(session.bind, "before_cursor_execute", count_query)
        try:
            assert _judge_mapping_counts(session, judge=judge) == (3, 2, 3)
            rows, _, _ = _judge_authority_page(session, judge=judge, limit=2)
            assert len(rows) == 2
        finally:
            event.remove(session.bind, "before_cursor_execute", count_query)
    assert query_count == 3


def test_uj20_empty_states_distinguish_mapping_coverage(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    court_id, judge_id = _seed_catalog(name="IPLF 060B Empty Court")

    empty = client.get(f"/api/courts/judges/{judge_id}/authorities", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["coverage_state"] == "no_mapped_corpus"

    with get_session_factory()() as session:
        court = session.get(Court, court_id)
        assert court is not None
        other = Judge(
            court_id=court_id,
            full_name="Justice Other Mapped Example",
            source_name="official_court",
            source_url="https://example.gov.in/judges/other-example",
        )
        session.add(other)
        session.flush()
        _add_mapping(session, court=court, judge_id=other.id, ordinal=4)
        session.commit()

    no_judgments = client.get(f"/api/courts/judges/{judge_id}/authorities", headers=headers)
    assert no_judgments.status_code == 200
    assert no_judgments.json()["coverage_state"] == "no_judgments_for_judge"


def test_uj20_filters_and_cursor_fail_closed(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    court_id, judge_id = _seed_catalog(name="IPLF 060B Filter Court")
    with get_session_factory()() as session:
        court = session.get(Court, court_id)
        assert court is not None
        _add_mapping(session, court=court, judge_id=judge_id, ordinal=6)
        session.commit()

    filtered = client.get(
        f"/api/courts/judges/{judge_id}/authorities?year_from=2025&year_to=2025",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["coverage_state"] == "no_filter_matches"
    invalid_range = client.get(
        f"/api/courts/judges/{judge_id}/authorities?year_from=2027&year_to=2026",
        headers=headers,
    )
    assert invalid_range.status_code == 422
    invalid_cursor = client.get(
        f"/api/courts/judges/{judge_id}/authorities?cursor=not-a-cursor",
        headers=headers,
    )
    assert invalid_cursor.status_code == 422
    non_object_cursor = client.get(
        f"/api/courts/judges/{judge_id}/authorities?cursor=W10",
        headers=headers,
    )
    assert non_object_cursor.status_code == 422


def test_curator_catalogs_return_server_owned_ids_and_versions(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    court_id, judge_id = _seed_catalog(name="IPLF 060B Curator Court")
    bench_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            Bench(
                id=bench_id,
                court_id=court_id,
                name="Canonical Division Bench",
                source_name="official_court",
                source_url="https://example.gov.in/benches/division",
            )
        )
        session.commit()

    judges = client.get(
        "/api/judge-mapping/catalog/judges",
        headers=headers,
        params={"court_id": court_id, "q": "Canonical", "limit": 20},
    )
    assert judges.status_code == 200, judges.text
    judge = next(item for item in judges.json()["judges"] if item["id"] == judge_id)
    assert judge["record_version"] == 0
    assert judge["identity_version"] == 1

    benches = client.get(
        "/api/judge-mapping/catalog/benches",
        headers=headers,
        params={"court_id": court_id, "q": "Division", "limit": 20},
    )
    assert benches.status_code == 200, benches.text
    assert benches.json()["benches"][0]["id"] == bench_id
    assert benches.json()["benches"][0]["record_version"] == 0


def test_judge_mapping_pilot_courts_are_source_openable(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    pilots = (
        (
            "Delhi High Court",
            "delhi_high_court_recent_judgments",
            "https://delhihighcourt.nic.in/judgments/060b.pdf",
        ),
        (
            "Bombay High Court",
            "bombay_high_court_recent_orders_judgments",
            "https://bombayhighcourt.nic.in/judgments/060b.pdf",
        ),
        (
            "Madras High Court",
            "madras_high_court_operational_orders",
            "https://mhc.tn.gov.in/judgments/060b.pdf",
        ),
    )
    judge_ids: list[str] = []
    with get_session_factory()() as session:
        for index, (court_name, source, source_url) in enumerate(pilots):
            court = session.query(Court).filter_by(name=court_name).one()
            judge = Judge(
                court_id=court.id,
                full_name=f"Justice Pilot Source {index}",
                source_name="official_court",
                source_url=source_url,
            )
            session.add(judge)
            session.flush()
            _add_mapping(
                session,
                court=court,
                judge_id=judge.id,
                ordinal=index + 10,
                source=source,
                source_reference=source_url,
            )
            judge_ids.append(judge.id)
        session.commit()

    for judge_id in judge_ids:
        response = client.get(f"/api/courts/judges/{judge_id}/authorities", headers=headers)
        assert response.status_code == 200, response.text
        authority = response.json()["authorities"][0]
        assert authority["source_action"]["state"] == "available"
        assert authority["source_action"]["open_url"]
