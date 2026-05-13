from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentType,
    Company,
    Court,
    Judge,
    JudgeDecisionIndex,
    Matter,
    MatterCauseListEntry,
    MatterCourtOrder,
    ModelRun,
    PredictiveOutcomeAggregateSnapshot,
    PredictiveSignalEvidence,
    PredictiveSignalItem,
    PredictiveSignalRun,
    Team,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.predictive_intelligence import PredictiveEvidence
from caseops_api.services.predictive_outcomes import (
    classify_authority_document,
    refresh_predictive_aggregate_snapshots,
)
from tests.test_auth_company import auth_headers, bootstrap_company

OFFICIAL_TEST_SOURCE = "delhi_high_court_recent_judgments"


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Predictive intelligence {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _enable_predictive_policy(client: TestClient, token: str) -> None:
    response = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"predictive_bench_strategy_enabled": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["predictive_bench_strategy_enabled"] is True


def _bootstrap_second_tenant(client: TestClient) -> str:
    slug = f"tenant-b-{uuid4().hex[:8]}"
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Tenant B Owner",
            "owner_email": f"owner-{slug}@example.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _invite_member(
    client: TestClient,
    owner_token: str,
    *,
    company_slug: str,
    email: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Conflict Member",
            "email": email,
            "role": "member",
            "password": "MemberPass123!",
        },
    )
    assert response.status_code == 200, response.text
    membership_id = str(response.json()["membership_id"])

    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _seed_source_backed_bench(matter_id: str) -> dict[str, str]:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        court = Court(
            id=str(uuid4()),
            name=f"Predictive Test High Court {uuid4().hex[:8]}",
            short_name="PTHC",
            forum_level="high_court",
            jurisdiction="india",
            is_active=True,
        )
        judge = Judge(
            id=str(uuid4()),
            court_id=court.id,
            full_name=f"Justice Predictive {uuid4().hex[:6]}",
            honorific="Justice",
            is_active=True,
        )
        session.add_all([court, judge])
        session.flush()
        matter.court_id = court.id
        matter.court_name = court.name
        matter.judge_name = judge.full_name
        session.add(
            MatterCauseListEntry(
                id=str(uuid4()),
                matter_id=matter.id,
                listing_date=date(2026, 5, 20),
                forum_name=court.name,
                bench_name=judge.full_name,
                judges_json=json.dumps(
                    [{"judge_id": judge.id, "matched_alias": judge.full_name}]
                ),
                stage="Final hearing",
                notes="Bench resolved from official test fixture.",
                source="test_fixture",
                source_reference="fixture:cause-list",
            )
        )

        outcomes = [
            ("allowed", "The petitioner application is allowed on cited legal grounds."),
            ("partly allowed", "The appellant appeal is partly allowed after hearing."),
            ("dismissed", "The petitioner writ petition is dismissed after arguments."),
            ("bail granted", "The applicant bail is granted with conditions."),
            ("bail denied", "The applicant bail is denied on recorded reasons."),
        ]
        doc_ids: list[str] = []
        for index, (outcome, source_text) in enumerate(outcomes, start=1):
            doc = AuthorityDocument(
                id=str(uuid4()),
                source=OFFICIAL_TEST_SOURCE,
                adapter_name="caseops-delhi-high-court-authorities-v1",
                court_name=court.name,
                forum_level="high_court",
                document_type=AuthorityDocumentType.JUDGMENT,
                title=f"Source-backed outcome judgment {index}",
                case_reference=f"PI/{index}/2026",
                bench_name=judge.full_name,
                neutral_citation=f"2026 TEST {index}",
                decision_date=date(2026, 1, index),
                canonical_key=f"predictive:{uuid4()}",
                source_reference=f"fixture:judgment:{index}",
                summary=source_text,
                document_text=f"Official source text: {source_text}",
                extracted_char_count=100,
                judges_json=json.dumps([judge.full_name]),
                outcome_label=outcome,
            )
            session.add(doc)
            session.flush()
            doc_ids.append(doc.id)
            session.add(
                JudgeDecisionIndex(
                    id=str(uuid4()),
                    judge_id=judge.id,
                    authority_document_id=doc.id,
                    role="sat_on",
                    year=2026,
                    matched_alias=judge.full_name,
                    match_confidence="high",
                )
            )
        session.commit()
        return {"judge_id": judge.id, "doc_id": doc_ids[0], "doc_ids": json.dumps(doc_ids)}


def _classify_seeded_bench(doc_ids_json: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        for doc_id in json.loads(doc_ids_json):
            doc = session.get(AuthorityDocument, doc_id)
            assert doc is not None
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session)
        session.commit()


def _predictive_response(client: TestClient, token: str, matter_id: str):
    return client.get(
        f"/api/matters/{matter_id}/predictive-intelligence",
        headers=auth_headers(token),
    )


def test_policy_disabled_blocks_predictive_intelligence(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "PI-POLICY-OFF")

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 403
    assert "tenant AI policy" in response.json()["detail"]


def test_predictive_intelligence_cross_tenant_denied(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token_a)
    matter_id = _create_matter(client, token_a, "PI-TENANT-A")

    token_b = _bootstrap_second_tenant(client)
    _enable_predictive_policy(client, token_b)

    response = _predictive_response(client, token_b, matter_id)

    assert response.status_code == 404


def test_predictive_intelligence_respects_ethical_wall(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    _enable_predictive_policy(client, owner_token)
    matter_id = _create_matter(client, owner_token, "PI-WALL")
    member_id, member_token = _invite_member(
        client,
        owner_token,
        company_slug=company_slug,
        email="predictive-wall@example.in",
    )
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text

    response = _predictive_response(client, member_token, matter_id)

    assert response.status_code == 404


def test_predictive_intelligence_restricted_matter_denied_for_ungranted_member(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    _enable_predictive_policy(client, owner_token)
    matter_id = _create_matter(client, owner_token, "PI-RESTRICTED")
    _member_id, member_token = _invite_member(
        client,
        owner_token,
        company_slug=company_slug,
        email="predictive-restricted@example.in",
    )
    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    response = _predictive_response(client, member_token, matter_id)

    assert response.status_code == 404


def test_predictive_intelligence_team_scoped_matter_denied_for_non_team_member(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    company_slug = str(boot["company"]["slug"])
    _enable_predictive_policy(client, owner_token)
    matter_id = _create_matter(client, owner_token, "PI-TEAM-SCOPED")
    _member_id, member_token = _invite_member(
        client,
        owner_token,
        company_slug=company_slug,
        email="predictive-team@example.in",
    )

    factory = get_session_factory()
    with factory() as session:
        company = session.get(Company, company_id)
        matter = session.get(Matter, matter_id)
        assert company is not None
        assert matter is not None
        team = Team(
            id=str(uuid4()),
            company_id=company_id,
            name="Predictive Scoped Team",
            slug=f"predictive-scoped-{uuid4().hex[:8]}",
        )
        session.add(team)
        session.flush()
        company.team_scoping_enabled = True
        matter.team_id = team.id
        session.commit()

    response = _predictive_response(client, member_token, matter_id)

    assert response.status_code == 404


def test_weak_evidence_returns_insufficient_evidence(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-WEAK")

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_policy_enabled"] is True
    assert body["bench_summary"]["evidence_quality"] == "insufficient"
    assert body["bench_context"]["status"] == "insufficient_evidence"
    assert body["bench_context"]["sample_size"] == 0
    assert body["bench_context"]["missing_data"]
    for signal in body["bench_summary"]["signals"]:
        assert signal["status"] == "insufficient_evidence"
        assert signal["confidence"]["confidence_band_low"] is None
        assert signal["confidence"]["confidence_band_high"] is None
        assert signal["missing_data"]
    assert body["matter_risk_summary"]["status"] == "insufficient_evidence"
    assert body["hearing_prep_scorecard"]["status"] == "insufficient_evidence"
    assert body["calibrated_signals"]
    assert all(
        signal["status"] == "insufficient_evidence"
        for signal in body["calibrated_signals"]
    )
    assert all(signal["observed_rate"] is None for signal in body["calibrated_signals"])


def test_summary_only_sources_do_not_support_predictive_markers_or_excerpts() -> None:
    from caseops_api.services.predictive_intelligence import (
        _document_has_any,
        _evidence_from_authority_docs,
        _evidence_from_court_orders,
        _is_stay_or_interim_order,
    )

    doc = AuthorityDocument(
        id=str(uuid4()),
        source=OFFICIAL_TEST_SOURCE,
        court_name="Delhi High Court",
        forum_level="high_court",
        document_type=AuthorityDocumentType.JUDGMENT,
        title="Summary-only notice document",
        summary="Generated summary only: notice is issued to the respondent.",
        document_text=None,
        canonical_key=f"summary-only:{uuid4()}",
    )
    order = MatterCourtOrder(
        id=str(uuid4()),
        matter_id=str(uuid4()),
        order_date=date(2026, 2, 1),
        title="Routine order",
        summary="Generated summary only: stay is granted and interim relief is recorded.",
        order_text=None,
        source="test_fixture",
        source_reference="fixture:summary-only-stay",
    )

    assert not _document_has_any(doc, ("notice",))
    assert not _is_stay_or_interim_order(order)
    assert _evidence_from_authority_docs([doc])[0].excerpt is None
    assert _evidence_from_court_orders([order])[0].excerpt is None


def test_bench_context_limited_when_judgments_have_no_aggregates(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-BENCH-LIMITED")
    seeded = _seed_source_backed_bench(matter_id)

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    context = response.json()["bench_context"]
    assert context["status"] == "limited_context"
    assert context["sample_size"] == 5
    assert context["scope"]["judge_ids"] == [seeded["judge_id"]]
    assert context["evidence"]
    assert context["observed_distribution"] == []
    assert "LI-S7B outcome aggregate snapshots" in json.dumps(context["missing_data"])


def test_strong_fixture_returns_source_backed_confidence_and_audit(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-STRONG")
    seeded = _seed_source_backed_bench(matter_id)
    _classify_seeded_bench(seeded["doc_ids"])

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    body = response.json()
    signals = {
        signal["signal_type"]: signal for signal in body["bench_summary"]["signals"]
    }
    outcome = signals["bench_outcome_tendency"]
    assert outcome["status"] == "supported"
    assert outcome["sample_size"] == 5
    assert outcome["confidence"]["label"] == "low"
    assert outcome["confidence"]["confidence_band_low"] is not None
    assert outcome["confidence"]["confidence_band_high"] is not None
    assert outcome["evidence"]
    assert all(evidence["source_id"] for evidence in outcome["evidence"])
    assert all(feature["evidence_ids"] for feature in outcome["features"])
    assert "not legal advice" in outcome["disclaimer"]
    assert outcome["decision_support_label"] == "decision support, not legal advice"
    bench_context = body["bench_context"]
    assert bench_context["status"] == "supported"
    assert bench_context["scope"]["judge_ids"] == [seeded["judge_id"]]
    assert bench_context["sample_size"] == 5
    assert bench_context["confidence"]["confidence_band_low"] is not None
    assert bench_context["evidence"]
    assert bench_context["observed_distribution"]
    assert all(item["sample_size"] >= 5 for item in bench_context["observed_distribution"])
    assert "not legal advice" in bench_context["disclaimer"]
    calibrated = {
        signal["signal_type"]: signal for signal in body["calibrated_signals"]
    }
    calibrated_outcome = calibrated["bench_outcome_tendency"]
    assert calibrated_outcome["status"] == "supported"
    assert calibrated_outcome["aggregate_snapshot_id"]
    assert calibrated_outcome["scope"]["judge_id"] == seeded["judge_id"]
    assert calibrated_outcome["sample_size"] == 5
    assert calibrated_outcome["observed_rate"] is not None
    assert calibrated_outcome["confidence"]["confidence_band_low"] is not None
    assert calibrated_outcome["confidence"]["confidence_band_high"] is not None
    assert calibrated_outcome["calibration_level"] == "low"
    assert calibrated_outcome["evidence"]
    assert all(evidence["source_id"] for evidence in calibrated_outcome["evidence"])
    assert "not legal advice" in calibrated_outcome["disclaimer"]
    assert "observed historical pattern" in calibrated_outcome["limitation_note"].lower()

    factory = get_session_factory()
    with factory() as session:
        runs = list(
            session.scalars(
                select(PredictiveSignalRun).where(
                    PredictiveSignalRun.company_id == company_id,
                    PredictiveSignalRun.matter_id == matter_id,
                )
            )
        )
        assert len(runs) == 1
        run = runs[0]
        assert session.scalar(
            select(PredictiveSignalItem).where(
                PredictiveSignalItem.run_id == run.id,
                PredictiveSignalItem.signal_type == "bench_outcome_tendency",
                PredictiveSignalItem.status == "supported",
            )
        )
        assert session.scalar(
            select(PredictiveSignalEvidence).where(
                PredictiveSignalEvidence.run_id == run.id,
                PredictiveSignalEvidence.source_type == "authority_document",
            )
        )
        assert session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.signal_type == "bench_party_side_tendency",
                PredictiveOutcomeAggregateSnapshot.status == "supported",
            )
        )
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "predictive_intelligence.generated",
                AuditEvent.matter_id == matter_id,
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert "bench_outcome_tendency" in metadata["supported_calibrated_signal_types"]
        assert (
            session.scalar(
                select(ModelRun).where(
                    ModelRun.company_id == company_id,
                    ModelRun.matter_id == matter_id,
                    ModelRun.purpose.like("%predictive%"),
                )
            )
            is None
        )


def test_calibrated_signal_requires_source_evidence_before_supported(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-CAL-EVIDENCE")
    court_name = f"Calibrated Evidence Court {uuid4().hex[:8]}"

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.court_name = court_name
        snapshot = PredictiveOutcomeAggregateSnapshot(
            id=str(uuid4()),
            scope_type="court_forum",
            scope_key=f"court_forum|{court_name}|high_court|interim_relief_likelihood",
            court_name=court_name,
            forum_level="high_court",
            signal_type="interim_relief_likelihood",
            sample_size=8,
            positive_count=6,
            negative_count=2,
            neutral_count=0,
            consistency=0.75,
            confidence_label="low",
            confidence_band_low=0.41,
            confidence_band_high=0.93,
            evidence_source_ids_json="[]",
            feature_summary_json=json.dumps({"source_court_names": [court_name]}),
            status="supported",
        )
        session.add(snapshot)
        session.commit()

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    calibrated = {
        signal["signal_type"]: signal
        for signal in response.json()["calibrated_signals"]
    }
    signal = calibrated["interim_relief_likelihood"]
    assert signal["status"] == "insufficient_evidence"
    assert signal["sample_size"] == 8
    assert signal["observed_rate"] is None
    assert signal["evidence"] == []
    assert "Resolvable source evidence IDs" in json.dumps(signal["missing_data"])


def test_no_unsupported_favorability_phrase_or_source_free_supported_signal(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-SAFE-COPY")
    seeded = _seed_source_backed_bench(matter_id)
    _classify_seeded_bench(seeded["doc_ids"])

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "judge is favorable" not in json.dumps(body).lower()
    assert "judge reputation" not in json.dumps(body).lower()
    assert "will win" not in json.dumps(body).lower()
    for signal in body["bench_summary"]["signals"]:
        if signal["status"] == "supported":
            assert signal["evidence"]
            assert all(evidence["source_id"] for evidence in signal["evidence"])


def test_hearing_scorecard_uses_observable_metrics_only(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _enable_predictive_policy(client, token)
    matter_id = _create_matter(client, token, "PI-HEARING")

    response = _predictive_response(client, token, matter_id)

    assert response.status_code == 200, response.text
    scorecard = response.json()["hearing_prep_scorecard"]
    metric_keys = {metric["feature_key"] for metric in scorecard["observable_metrics"]}
    assert metric_keys == {
        "response_consistency",
        "source_support_rate",
        "unsupported_new_fact_rate",
        "response_timing_discipline",
    }
    metric_text = json.dumps(scorecard["observable_metrics"]).lower()
    assert "emotional" not in metric_text
    assert "psychological" not in metric_text
    assert "diagnosis" not in metric_text
    assert "personality" not in metric_text


def test_unknown_predictive_evidence_source_type_rejected() -> None:
    try:
        PredictiveEvidence(
            id="e-unknown",
            source_type="manual_upload",
            source_id="manual-1",
            weight=1.0,
        )
    except ValidationError:
        return
    raise AssertionError("unknown predictive evidence source type was accepted")
