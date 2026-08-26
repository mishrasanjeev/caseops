from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    Bench,
    CompanyMembership,
    Court,
    Judge,
    JudgeAlias,
    JudgeDecisionIndex,
    JudgeMappingReview,
    MembershipRole,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import predictive_intelligence, predictive_outcomes
from caseops_api.services.judge_aliases import normalise
from tests.test_auth_company import auth_headers, bootstrap_company


def _authority(*, court_name: str, judges: list[str]) -> AuthorityDocument:
    return AuthorityDocument(
        source="official_test_reporter",
        adapter_name="test",
        court_name=court_name,
        forum_level="high_court",
        document_type="judgment",
        title="IPLF-060A mapping authority",
        decision_date=date(2026, 8, 20),
        canonical_key=f"iplf-060a:{uuid4()}",
        source_reference="https://example.test/judgment/060a",
        summary="Test source-backed authority.",
        document_text="Test judgment text.",
        judges_json=json.dumps(judges),
    )


def _catalog(
    *, alias_one: str = "Justice Alpha Example", alias_two: str = "Justice Beta Example"
) -> tuple[str, str, str]:
    court_id = str(uuid4())
    judge_one_id = str(uuid4())
    judge_two_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            Court(
                id=court_id,
                name=f"IPLF 060A High Court {court_id}",
                short_name="I60A",
                forum_level="high_court",
                jurisdiction="india",
                is_active=True,
            )
        )
        session.add_all(
            [
                Judge(
                    id=judge_one_id,
                    court_id=court_id,
                    full_name="Alpha Example",
                    is_active=True,
                ),
                Judge(
                    id=judge_two_id,
                    court_id=court_id,
                    full_name="Beta Example",
                    is_active=True,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                JudgeAlias(
                    judge_id=judge_one_id,
                    alias_text=alias_one,
                    alias_normalised=normalise(alias_one),
                    source="official_court",
                ),
                JudgeAlias(
                    judge_id=judge_two_id,
                    alias_text=alias_two,
                    alias_normalised=normalise(alias_two),
                    source="official_court",
                ),
            ]
        )
        session.commit()
    return court_id, judge_one_id, judge_two_id


def test_collision_fails_closed_and_curator_resolution_is_versioned_and_audited(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    _, judge_one_id, _ = _catalog(
        alias_one="Justice Shared Example",
        alias_two="Justice Shared Example",
    )
    with get_session_factory()() as session:
        court = session.get(Judge, judge_one_id)
        assert court is not None
        court_name = session.get(Court, court.court_id).name
        document = _authority(court_name=court_name, judges=["Justice Shared Example"])
        session.add(document)
        session.commit()
        authority_id = document.id

    remap = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    assert remap.status_code == 200, remap.text
    assert remap.json()["mapped"] == 0
    assert remap.json()["collisions"] == 1

    queue = client.get("/api/judge-mapping/reviews", headers=headers)
    assert queue.status_code == 200, queue.text
    review = queue.json()["reviews"][0]
    assert review["reason"] == "collision"
    assert len(review["candidates"]) == 2

    resolved = client.post(
        f"/api/judge-mapping/reviews/{review['id']}/resolve",
        headers=headers,
        json={
            "judge_id": judge_one_id,
            "expected_record_version": review["record_version"],
            "note": "Official order identifies Alpha Example.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    stale = client.post(
        f"/api/judge-mapping/reviews/{review['id']}/resolve",
        headers=headers,
        json={
            "judge_id": judge_one_id,
            "expected_record_version": review["record_version"],
            "note": "Stale duplicate curator resolution attempt.",
        },
    )
    assert stale.status_code == 409

    with get_session_factory()() as session:
        mapping = session.scalar(
            select(JudgeDecisionIndex).where(
                JudgeDecisionIndex.authority_document_id == authority_id
            )
        )
        assert mapping is not None
        assert mapping.mapping_status == "curator_confirmed"
        assert mapping.is_analytics_eligible is True
        assert mapping.raw_judge_name == "Justice Shared Example"
        assert session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "judge_mapping.review.resolve"
            )
        ) is not None


def test_alias_upsert_reprocesses_review_and_rejects_same_court_collision(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, judge_one_id, judge_two_id = _catalog()
    with get_session_factory()() as session:
        court_name = session.get(Court, court_id).name
        document = _authority(court_name=court_name, judges=["Justice New Alias"])
        session.add(document)
        session.commit()
        authority_id = document.id

    first = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    assert first.status_code == 200
    assert first.json()["unresolved"] == 1

    alias = client.post(
        f"/api/judge-mapping/judges/{judge_one_id}/aliases",
        headers=headers,
        json={
            "alias_text": "Justice New Alias",
            "source": "official_court",
            "source_url": "https://example.test/roster",
            "source_evidence_text": "Published roster dated 20 August 2026.",
        },
    )
    assert alias.status_code == 200, alias.text
    assert alias.json()["alias_normalised"] == "justice new alias"

    collision = client.post(
        f"/api/judge-mapping/judges/{judge_two_id}/aliases",
        headers=headers,
        json={
            "alias_text": "Justice New Alias",
            "source": "manual_curator",
            "source_evidence_text": "Should fail closed on collision.",
        },
    )
    assert collision.status_code == 409

    with get_session_factory()() as session:
        mapping = session.scalar(
            select(JudgeDecisionIndex).where(
                JudgeDecisionIndex.authority_document_id == authority_id
            )
        )
        review = session.scalar(
            select(JudgeMappingReview).where(
                JudgeMappingReview.authority_document_id == authority_id
            )
        )
        assert mapping is not None and mapping.judge_id == judge_one_id
        assert review is not None and review.status == "auto_resolved"


def test_curator_override_replaces_the_automatic_mapping_for_one_evidence_slot(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, automatic_judge_id, curator_judge_id = _catalog()
    with get_session_factory()() as session:
        court = session.get(Court, court_id)
        assert court is not None
        document = _authority(
            court_name=court.name,
            judges=["Justice Alpha Example"],
        )
        session.add(document)
        session.commit()
        authority_id = document.id

    first = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["mapped"] == 1

    with get_session_factory()() as session:
        review = JudgeMappingReview(
            authority_document_id=authority_id,
            court_id=court_id,
            raw_judge_name="Justice Alpha Example",
            raw_judge_name_normalised="justice alpha example",
            source_ordinal=0,
            reason="curator_override",
            candidate_judge_ids_json=[automatic_judge_id, curator_judge_id],
            status="open",
            resolver_version="test",
        )
        session.add(review)
        session.commit()
        review_id = review.id
        review_version = review.record_version

    resolved = client.post(
        f"/api/judge-mapping/reviews/{review_id}/resolve",
        headers=headers,
        json={
            "judge_id": curator_judge_id,
            "expected_record_version": review_version,
            "note": "Official order confirms the second canonical judge.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    with get_session_factory()() as session:
        mappings = list(
            session.scalars(
                select(JudgeDecisionIndex).where(
                    JudgeDecisionIndex.authority_document_id == authority_id
                )
            )
        )
        assert len(mappings) == 1
        assert mappings[0].judge_id == curator_judge_id
        assert mappings[0].mapping_status == "curator_confirmed"


def test_reprocess_is_stable_and_removes_stale_automatic_mapping(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, judge_one_id, judge_two_id = _catalog()
    with get_session_factory()() as session:
        court_name = session.get(Court, court_id).name
        document = _authority(court_name=court_name, judges=["Justice Alpha Example"])
        session.add(document)
        session.commit()
        authority_id = document.id

    first = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    second = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    assert first.json()["mapped"] == 1
    assert first.json()["inserted"] == 1
    assert second.json()["mapped"] == 1
    assert second.json()["inserted"] == 0
    with get_session_factory()() as session:
        first_id = session.scalar(
            select(JudgeDecisionIndex.id).where(
                JudgeDecisionIndex.authority_document_id == authority_id
            )
        )
        document = session.get(AuthorityDocument, authority_id)
        document.judges_json = json.dumps(["Justice Beta Example"])
        session.commit()

    changed = client.post(
        f"/api/judge-mapping/authorities/{authority_id}/reprocess", headers=headers
    )
    assert changed.json()["mapped"] == 1
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(JudgeDecisionIndex).where(
                    JudgeDecisionIndex.authority_document_id == authority_id
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].judge_id == judge_two_id
        assert rows[0].judge_id != judge_one_id
        assert rows[0].id != first_id


def test_revoked_mapping_is_excluded_from_every_predictive_consumer(
    client: TestClient,
) -> None:
    del client
    court_id, judge_id, _ = _catalog()
    with get_session_factory()() as session:
        court = session.get(Court, court_id)
        assert court is not None
        document = _authority(court_name=court.name, judges=["Justice Alpha Example"])
        document.source = "delhi_high_court_recent_judgments"
        document.document_text = "The petition is dismissed after hearing both sides."
        session.add(document)
        session.flush()
        mapping = JudgeDecisionIndex(
            judge_id=judge_id,
            authority_document_id=document.id,
            role="sat_on",
            year=2026,
            matched_alias="Justice Alpha Example",
            match_confidence="exact",
            raw_judge_name="Justice Alpha Example",
            source_ordinal=0,
            mapping_status="auto_confirmed",
            resolver_version="test",
            is_analytics_eligible=True,
        )
        session.add(mapping)
        session.flush()
        classifications = predictive_outcomes.classify_authority_document(
            session, document, only_unclassified=False
        )
        assert classifications
        assert predictive_intelligence._load_bench_documents(session, [judge_id])

        mapping.is_analytics_eligible = False
        session.flush()

        assert predictive_intelligence._load_bench_documents(session, [judge_id]) == ()
        assert predictive_outcomes._select_authority_documents(
            session,
            forum_level=None,
            court_name=None,
            year_range=None,
            judge_id=judge_id,
            matter_type=None,
            limit=None,
            only_unclassified=False,
        ) == []
        assert predictive_outcomes._select_classifications_for_aggregation(
            session,
            court_name=None,
            forum_level=None,
            judge_id=judge_id,
            matter_type=None,
            party_side=None,
            year_range=None,
            include_private=False,
        ) == []


def test_duplicate_merge_reconciles_aliases_mappings_and_review_candidates(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, source_id, destination_id = _catalog(
        alias_one="Justice Duplicate Example",
        alias_two="Justice Destination Example",
    )
    with get_session_factory()() as session:
        court_name = session.get(Court, court_id).name
        source_doc = _authority(court_name=court_name, judges=[])
        destination_doc = _authority(court_name=court_name, judges=[])
        review_doc = _authority(court_name=court_name, judges=[])
        session.add_all([source_doc, destination_doc, review_doc])
        session.flush()
        session.add_all(
            [
                JudgeDecisionIndex(
                    judge_id=source_id,
                    authority_document_id=source_doc.id,
                    mapping_status="auto_confirmed",
                    resolver_version="test",
                ),
                JudgeDecisionIndex(
                    judge_id=destination_id,
                    authority_document_id=destination_doc.id,
                    mapping_status="auto_confirmed",
                    resolver_version="test",
                ),
                JudgeMappingReview(
                    authority_document_id=review_doc.id,
                    court_id=court_id,
                    raw_judge_name="Duplicate Example",
                    raw_judge_name_normalised="duplicate example",
                    source_ordinal=0,
                    reason="collision",
                    candidate_judge_ids_json=[source_id, destination_id],
                    status="open",
                    resolver_version="test",
                ),
            ]
        )
        session.commit()

    merged = client.post(
        f"/api/judge-mapping/judges/{source_id}/merge",
        headers=headers,
        json={
            "destination_judge_id": destination_id,
            "expected_source_version": 0,
            "expected_destination_version": 0,
            "reason": "Official roster confirms these records are duplicates.",
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["id"] == destination_id
    with get_session_factory()() as session:
        source = session.get(Judge, source_id)
        assert source is not None
        assert source.is_active is False
        assert source.merged_into_judge_id == destination_id
        assert session.scalar(
            select(JudgeDecisionIndex).where(
                JudgeDecisionIndex.judge_id == source_id
            )
        ) is None
        assert len(
            list(
                session.scalars(
                    select(JudgeDecisionIndex).where(
                        JudgeDecisionIndex.judge_id == destination_id
                    )
                )
            )
        ) == 2
        review = session.scalar(select(JudgeMappingReview))
        assert review is not None
        assert review.candidate_judge_ids_json == [destination_id]


def test_duplicate_merge_rejects_third_judge_alias_collision_atomically(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, source_id, destination_id = _catalog(
        alias_one="Justice Shared Merge Alias",
        alias_two="Justice Destination Merge Alias",
    )
    third_id = str(uuid4())
    with get_session_factory()() as session:
        session.add(
            Judge(
                id=third_id,
                court_id=court_id,
                full_name="Justice Third Merge Example",
                source_name="official_court",
                source_url="https://example.test/judges/third",
            )
        )
        session.add(
            JudgeAlias(
                judge_id=third_id,
                alias_text="Justice Shared Merge Alias",
                alias_normalised=normalise("Justice Shared Merge Alias"),
                source="official_court",
            )
        )
        session.commit()

    response = client.post(
        f"/api/judge-mapping/judges/{source_id}/merge",
        headers=headers,
        json={
            "destination_judge_id": destination_id,
            "expected_source_version": 0,
            "expected_destination_version": 0,
            "reason": "Attempted duplicate consolidation.",
        },
    )

    assert response.status_code == 409
    assert "ambiguous" in response.json()["detail"].lower()
    with get_session_factory()() as session:
        source = session.get(Judge, source_id)
        destination = session.get(Judge, destination_id)
        assert source is not None and source.is_active is True
        assert source.merged_into_judge_id is None
        assert source.record_version == 0
        assert destination is not None and destination.record_version == 0
        source_alias = session.scalar(
            select(JudgeAlias).where(JudgeAlias.judge_id == source_id)
        )
        assert source_alias is not None and source_alias.is_active is True


def test_curator_routes_reject_non_staff_members(client: TestClient) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    membership_id = str(boot["membership"]["id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.MEMBER
        session.commit()
    response = client.get("/api/judge-mapping/reviews", headers=headers)
    assert response.status_code == 403
    assert "court_sync:run" in response.text


def test_bench_alias_is_sourced_and_audited(client: TestClient) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    court_id, _, _ = _catalog()
    with get_session_factory()() as session:
        bench = Bench(court_id=court_id, name="IP Division Bench")
        session.add(bench)
        session.commit()
        bench_id = bench.id
    response = client.post(
        f"/api/judge-mapping/benches/{bench_id}/aliases",
        headers=headers,
        json={
            "alias_text": "IPDB",
            "source": "official_court",
            "source_url": "https://example.test/bench-roster",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["alias_normalised"] == "ipdb"
    with get_session_factory()() as session:
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.action == "bench_catalog.alias.upsert")
        ) is not None
