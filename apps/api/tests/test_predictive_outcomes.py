from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from caseops_api.db.models import (
    AuthorityDocument,
    AuthorityDocumentType,
    Court,
    Judge,
    JudgeDecisionIndex,
    Matter,
    MatterCourtOrder,
    ModelRun,
    PredictiveOutcomeAggregateSnapshot,
    PredictiveOutcomeClassification,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.backfill_predictive_outcomes import main as backfill_main
from caseops_api.services import predictive_outcomes
from caseops_api.services.llm import LLMCallContext, LLMCompletion, LLMMessage
from caseops_api.services.predictive_outcomes import (
    classify_authority_document,
    classify_matter_court_order,
    refresh_predictive_aggregate_snapshots,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_predictive_intelligence import _enable_predictive_policy

OFFICIAL_TEST_SOURCE = "delhi_high_court_recent_judgments"


class _StubProvider:
    name = "openai"
    model = "gpt-5.1-test"


def _seed_doc(
    *,
    court_name: str | None = None,
    judge_id: str | None = None,
    text: str,
    title: str = "Predictive outcome test judgment",
    forum_level: str = "high_court",
    decision_year: int = 2026,
    source: str = OFFICIAL_TEST_SOURCE,
    use_document_text: bool = True,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        doc = AuthorityDocument(
            id=str(uuid4()),
            source=source,
            adapter_name=(
                "caseops-delhi-high-court-authorities-v1"
                if source == OFFICIAL_TEST_SOURCE
                else "test"
            ),
            court_name=court_name or f"Predictive Outcome Court {uuid4().hex[:8]}",
            forum_level=forum_level,
            document_type=AuthorityDocumentType.JUDGMENT,
            title=title,
            case_reference=f"PO/{uuid4().hex[:8]}",
            bench_name="Justice Outcome",
            neutral_citation=f"2026 TEST {uuid4().hex[:4]}",
            decision_date=date(decision_year, 1, 1),
            canonical_key=f"predictive-outcome:{uuid4()}",
            source_reference=f"fixture:po:{uuid4()}",
            summary=text,
            document_text=(
                f"Official licensed source text. {text}" if use_document_text else None
            ),
            extracted_char_count=200 if use_document_text else 0,
            judges_json=json.dumps(["Justice Outcome"]),
            outcome_label=None,
        )
        session.add(doc)
        session.flush()
        if judge_id:
            session.add(
                JudgeDecisionIndex(
                    id=str(uuid4()),
                    judge_id=judge_id,
                    authority_document_id=doc.id,
                    role="sat_on",
                    year=decision_year,
                    matched_alias="Justice Outcome",
                    match_confidence="high",
                )
            )
        session.commit()
        return doc.id


def _create_court_and_judge() -> tuple[str, str]:
    factory = get_session_factory()
    with factory() as session:
        court = Court(
            id=str(uuid4()),
            name=f"Predictive Outcomes High Court {uuid4().hex[:8]}",
            short_name="POHC",
            forum_level="high_court",
            jurisdiction="india",
            is_active=True,
        )
        judge = Judge(
            id=str(uuid4()),
            court_id=court.id,
            full_name=f"Justice Outcomes {uuid4().hex[:6]}",
            honorific="Justice",
            is_active=True,
        )
        session.add_all([court, judge])
        session.commit()
        return court.name, judge.id


def test_deterministic_classification_happy_paths(client: TestClient) -> None:
    doc_id = _seed_doc(
        text=(
            "The petitioner seeks interim relief. Interim relief is granted. "
            "Notice is issued returnable in four weeks."
        )
    )

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        rows = classify_authority_document(session, doc)
        session.commit()

        labels = {row.classification_label for row in rows}
        assert {"interim_relief_granted", "notice_issued"} <= labels
        assert all(row.source_id == doc_id for row in rows)
        assert all(row.status == "classified" for row in rows)


def test_summary_only_authority_document_is_skipped(client: TestClient) -> None:
    doc_id = _seed_doc(
        text="Summary says notice is issued but raw source text is unavailable.",
        use_document_text=False,
    )

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        rows = classify_authority_document(session, doc)
        session.commit()

        assert rows == []
        assert (
            session.scalar(
                select(PredictiveOutcomeClassification).where(
                    PredictiveOutcomeClassification.source_id == doc_id
                )
            )
            is None
        )


def test_summary_only_matter_court_order_is_skipped(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Summary only predictive order",
            "matter_code": f"PI-SUMMARY-ORDER-{uuid4().hex[:6]}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    matter_id = str(response.json()["id"])

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        order = MatterCourtOrder(
            id=str(uuid4()),
            matter_id=matter_id,
            order_date=date(2026, 1, 10),
            title="Summary-only order",
            summary="The summary says notice is issued to the respondent.",
            order_text=None,
            source="test_fixture",
            source_reference="fixture:summary-only-order",
        )
        session.add(order)
        session.flush()
        rows = classify_matter_court_order(session, order, matter=matter)
        session.commit()

        assert rows == []
        assert (
            session.scalar(
                select(PredictiveOutcomeClassification).where(
                    PredictiveOutcomeClassification.source_id == order.id
                )
            )
            is None
        )


def test_llm_classification_is_source_bound_and_model_run_persisted(
    client: TestClient,
    monkeypatch,
) -> None:
    doc_id = _seed_doc(text="The Court records the operative result in terms stated below.")

    def fake_generate_structured(
        provider: _StubProvider,
        *,
        schema,
        messages: list[LLMMessage],
        context: LLMCallContext,
        on_model_run,
        **_kwargs,
    ):
        completion = LLMCompletion(
            text=json.dumps(
                {
                    "outcomes": [
                        {
                            "label": "settlement_recorded",
                            "rationale_snippet": "terms stated below",
                        }
                    ]
                }
            ),
            provider=provider.name,
            model=provider.model,
            prompt_tokens=12,
            completion_tokens=8,
            latency_ms=3,
        )
        on_model_run(completion, context, messages)
        return schema.model_validate(json.loads(completion.text)), completion

    monkeypatch.setattr(
        predictive_outcomes,
        "generate_structured",
        fake_generate_structured,
    )

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        rows = classify_authority_document(
            session,
            doc,
            use_llm=True,
            provider=_StubProvider(),
        )
        session.commit()

        assert {row.classification_label for row in rows} == {"settlement_recorded"}
        assert all(row.model_run_id for row in rows)
        run = session.scalar(
            select(ModelRun).where(ModelRun.purpose == "predictive_outcome_classification")
        )
        assert run is not None
        assert run.provider == "openai"
        assert run.prompt_hash


def test_malformed_llm_output_is_quarantined(client: TestClient, monkeypatch) -> None:
    doc_id = _seed_doc(text="The Court records the operative result in terms stated below.")

    def fake_generate_structured(*_args, **_kwargs):
        raise ValueError("not controlled JSON")

    monkeypatch.setattr(
        predictive_outcomes,
        "generate_structured",
        fake_generate_structured,
    )

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        rows = classify_authority_document(
            session,
            doc,
            use_llm=True,
            provider=_StubProvider(),
        )
        session.commit()

        assert len(rows) == 1
        assert rows[0].status == "quarantined"
        assert rows[0].model_run_id is not None
        run = session.get(ModelRun, rows[0].model_run_id)
        assert run is not None
        assert run.status == "malformed_output"


def test_llm_probability_field_is_quarantined(client: TestClient, monkeypatch) -> None:
    doc_id = _seed_doc(text="The Court records the operative result in terms stated below.")

    def fake_generate_structured(
        provider: _StubProvider,
        *,
        schema,
        messages: list[LLMMessage],
        context: LLMCallContext,
        on_model_run,
        **_kwargs,
    ):
        completion = LLMCompletion(
            text=json.dumps(
                {
                    "outcomes": [
                        {
                            "label": "notice_issued",
                            "rationale_snippet": "90% chance notice will issue",
                        }
                    ]
                }
            ),
            provider=provider.name,
            model=provider.model,
            prompt_tokens=10,
            completion_tokens=7,
            latency_ms=2,
        )
        on_model_run(completion, context, messages)
        return schema.model_validate(json.loads(completion.text)), completion

    monkeypatch.setattr(
        predictive_outcomes,
        "generate_structured",
        fake_generate_structured,
    )

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        rows = classify_authority_document(
            session,
            doc,
            use_llm=True,
            provider=_StubProvider(),
        )
        session.commit()

        assert rows[0].status == "quarantined"
        assert "probability" not in (rows[0].rationale_snippet or "").lower()


def test_aggregation_sample_size_confidence_and_weak_sample(client: TestClient) -> None:
    court_name, judge_id = _create_court_and_judge()
    for index in range(5):
        _seed_doc(
            court_name=court_name,
            judge_id=judge_id,
            text=f"Notice is issued to the respondent in matter {index}.",
        )
    for index in range(4):
        _seed_doc(
            court_name=court_name,
            judge_id=judge_id,
            text=f"Stay is granted in connected matter {index}.",
        )

    factory = get_session_factory()
    with factory() as session:
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        session.commit()

        notice = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.court_name == court_name,
                PredictiveOutcomeAggregateSnapshot.signal_type == "notice_issuance_likelihood",
            )
        )
        assert notice is not None
        assert notice.status == "supported"
        assert notice.sample_size == 5
        assert notice.confidence_label == "low"
        assert notice.confidence_band_low is not None
        assert json.loads(notice.evidence_source_ids_json)

        stay = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.court_name == court_name,
                PredictiveOutcomeAggregateSnapshot.signal_type == "stay_likelihood",
            )
        )
        assert stay is not None
        assert stay.status == "insufficient_evidence"
        assert stay.sample_size == 4
        assert stay.confidence_band_low is None


def test_unsupported_authority_source_skipped_from_public_backfill(
    client: TestClient,
) -> None:
    court_name = f"Unsupported Predictive Court {uuid4().hex[:8]}"
    for index in range(5):
        _seed_doc(
            court_name=court_name,
            source="test_fixture",
            text=f"Notice is issued to the respondent in unsupported source {index}.",
        )

    factory = get_session_factory()
    with factory() as session:
        stats = predictive_outcomes.backfill_predictive_outcomes(
            session,
            court_name=court_name,
            use_llm=False,
        )
        session.commit()

        assert stats.processed == 0
        assert session.scalar(select(PredictiveOutcomeClassification.id)) is None
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refreshed = refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        assert refreshed == 0
        assert (
            session.scalar(
                select(PredictiveOutcomeAggregateSnapshot).where(
                    PredictiveOutcomeAggregateSnapshot.court_name == court_name
                )
            )
            is None
        )


def test_refresh_predictive_aggregate_snapshots_removes_stale_supported_snapshot(
    client: TestClient,
) -> None:
    court_name, judge_id = _create_court_and_judge()
    for index in range(5):
        _seed_doc(
            court_name=court_name,
            judge_id=judge_id,
            text=f"Notice is issued to the respondent in stale test matter {index}.",
        )

    factory = get_session_factory()
    with factory() as session:
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        snapshot = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.court_name == court_name,
                PredictiveOutcomeAggregateSnapshot.signal_type == "notice_issuance_likelihood",
                PredictiveOutcomeAggregateSnapshot.status == "supported",
            )
        )
        assert snapshot is not None
        snapshot_id = snapshot.id

        session.execute(
            delete(PredictiveOutcomeClassification).where(
                PredictiveOutcomeClassification.court_name == court_name
            )
        )
        refreshed = refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        session.commit()

        assert refreshed == 0
        assert session.get(PredictiveOutcomeAggregateSnapshot, snapshot_id) is None


def test_refresh_predictive_aggregate_snapshots_removes_stale_matter_type_snapshot(
    client: TestClient,
) -> None:
    court_name, judge_id = _create_court_and_judge()
    for index in range(5):
        _seed_doc(
            court_name=court_name,
            judge_id=judge_id,
            text=(
                "Notice is issued to the respondent in commercial dispute "
                f"matter {index}."
            ),
        )

    factory = get_session_factory()
    with factory() as session:
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session)
        snapshot = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.scope_type == "matter_type",
                PredictiveOutcomeAggregateSnapshot.matter_type == "commercial",
                PredictiveOutcomeAggregateSnapshot.party_side.is_(None),
                PredictiveOutcomeAggregateSnapshot.signal_type
                == "notice_issuance_likelihood",
                PredictiveOutcomeAggregateSnapshot.status == "supported",
            )
        )
        assert snapshot is not None
        snapshot_id = snapshot.id
        features = json.loads(snapshot.feature_summary_json or "{}")
        assert court_name in features.get("source_court_names", [])
        assert judge_id in features.get("source_judge_ids", [])

        session.execute(
            delete(PredictiveOutcomeClassification).where(
                PredictiveOutcomeClassification.court_name == court_name
            )
        )
        refreshed = refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        session.commit()

        assert refreshed == 0
        assert session.get(PredictiveOutcomeAggregateSnapshot, snapshot_id) is None


def test_scoped_refresh_does_not_overwrite_unrelated_matter_type_snapshot(
    client: TestClient,
) -> None:
    court_a, judge_a = _create_court_and_judge()
    court_b, judge_b = _create_court_and_judge()
    for index in range(5):
        _seed_doc(
            court_name=court_b,
            judge_id=judge_b,
            text=(
                "Notice is issued to the respondent in commercial recovery "
                f"matter B-{index}."
            ),
        )

    factory = get_session_factory()
    with factory() as session:
        docs_b = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_b)
        )
        for doc in docs_b:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session)
        snapshot = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.scope_type == "matter_type",
                PredictiveOutcomeAggregateSnapshot.matter_type == "commercial",
                PredictiveOutcomeAggregateSnapshot.party_side.is_(None),
                PredictiveOutcomeAggregateSnapshot.signal_type
                == "notice_issuance_likelihood",
                PredictiveOutcomeAggregateSnapshot.status == "supported",
            )
        )
        assert snapshot is not None
        snapshot_id = snapshot.id
        original_features = json.loads(snapshot.feature_summary_json or "{}")
        assert original_features.get("source_court_names") == [court_b]
        assert original_features.get("source_judge_ids") == [judge_b]

        for index in range(5):
            doc = AuthorityDocument(
                id=str(uuid4()),
                source=OFFICIAL_TEST_SOURCE,
                adapter_name="caseops-delhi-high-court-authorities-v1",
                court_name=court_a,
                forum_level="high_court",
                document_type=AuthorityDocumentType.JUDGMENT,
                title="Predictive outcome commercial notice judgment",
                case_reference=f"PO-A/{uuid4().hex[:8]}",
                bench_name="Justice Outcome",
                neutral_citation=f"2026 TEST A{uuid4().hex[:4]}",
                decision_date=date(2026, 1, 1),
                canonical_key=f"predictive-outcome:a:{uuid4()}",
                source_reference=f"fixture:po:a:{uuid4()}",
                summary="Notice issued in commercial recovery matter.",
                document_text=(
                    "Official licensed source text. Notice is issued to the "
                    f"respondent in commercial recovery matter A-{index}."
                ),
                extracted_char_count=200,
                judges_json=json.dumps(["Justice Outcome"]),
            )
            session.add(doc)
            session.flush()
            session.add(
                JudgeDecisionIndex(
                    id=str(uuid4()),
                    judge_id=judge_a,
                    authority_document_id=doc.id,
                    role="sat_on",
                    year=2026,
                    matched_alias="Justice Outcome",
                    match_confidence="high",
                )
            )
            classify_authority_document(session, doc)

        refresh_predictive_aggregate_snapshots(session, court_name=court_a)
        session.commit()

        preserved = session.get(PredictiveOutcomeAggregateSnapshot, snapshot_id)
        assert preserved is not None
        preserved_features = json.loads(preserved.feature_summary_json or "{}")
        assert preserved_features.get("source_court_names") == [court_b]
        assert preserved_features.get("source_judge_ids") == [judge_b]


def test_predictive_route_uses_aggregate_evidence(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    _enable_predictive_policy(client, token)
    matter = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Predictive aggregate route",
            "matter_code": f"PI-AGG-{uuid4().hex[:6]}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter.status_code == 200, matter.text
    matter_id = str(matter.json()["id"])

    court_name, judge_id = _create_court_and_judge()
    factory = get_session_factory()
    with factory() as session:
        db_matter = session.get(Matter, matter_id)
        assert db_matter is not None
        db_matter.court_name = court_name
        session.commit()
    for label_text in (
        "The petitioner application is allowed.",
        "The appellant appeal is partly allowed.",
        "The petitioner writ petition is dismissed.",
        "The applicant bail is granted with conditions.",
        "The applicant bail is denied on recorded reasons.",
    ):
        _seed_doc(court_name=court_name, judge_id=judge_id, text=label_text)
    with factory() as session:
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(session, court_name=court_name)
        session.commit()

    response = client.get(
        f"/api/matters/{matter_id}/predictive-intelligence",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.text
    signals = {item["signal_type"]: item for item in response.json()["bench_summary"]["signals"]}
    signal = signals["bench_party_side_tendency"]
    assert signal["status"] == "supported"
    assert signal["sample_size"] == 5
    assert signal["evidence"]
    assert all(item["source_id"] for item in signal["evidence"])


def test_private_matter_order_not_included_in_public_aggregate(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Private predictive order",
            "matter_code": f"PI-PRIVATE-{uuid4().hex[:6]}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter.status_code == 200, matter.text
    matter_id = str(matter.json()["id"])
    court_name, judge_id = _create_court_and_judge()
    for index in range(5):
        _seed_doc(
            court_name=court_name,
            judge_id=judge_id,
            text=f"Notice is issued to the respondent in public matter {index}.",
        )

    factory = get_session_factory()
    with factory() as session:
        db_matter = session.get(Matter, matter_id)
        assert db_matter is not None
        db_matter.court_name = court_name
        order = MatterCourtOrder(
            id=str(uuid4()),
            matter_id=matter_id,
            order_date=date(2026, 1, 10),
            title="Private order",
            summary="Private matter order summary. Notice is issued to the respondent.",
            order_text="Private matter order text. Notice is issued to the respondent.",
            source="test_fixture",
            source_reference="private:order",
        )
        session.add(order)
        session.flush()
        classify_matter_court_order(session, order, matter=db_matter)
        docs = session.scalars(
            select(AuthorityDocument).where(AuthorityDocument.court_name == court_name)
        )
        for doc in docs:
            classify_authority_document(session, doc)
        refresh_predictive_aggregate_snapshots(
            session,
            court_name=court_name,
            include_private=False,
        )
        session.commit()

        snapshot = session.scalar(
            select(PredictiveOutcomeAggregateSnapshot).where(
                PredictiveOutcomeAggregateSnapshot.court_name == court_name,
                PredictiveOutcomeAggregateSnapshot.signal_type == "notice_issuance_likelihood",
            )
        )
        assert snapshot is not None
        assert snapshot.sample_size == 5
        evidence_json = json.dumps(json.loads(snapshot.evidence_source_ids_json))
        assert order.id not in evidence_json


def test_cli_dry_run_and_limit_behavior(client: TestClient, capsys) -> None:
    court_name, _judge_id = _create_court_and_judge()
    for index in range(3):
        _seed_doc(
            court_name=court_name,
            text=f"Notice is issued to the respondent in CLI matter {index}.",
        )

    code = backfill_main(
        [
            "--court-name",
            court_name,
            "--limit",
            "1",
            "--dry-run",
            "--no-llm",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["processed"] == 1
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(PredictiveOutcomeClassification.id)) is None


def test_idempotent_rerun_does_not_duplicate_classifications(client: TestClient) -> None:
    doc_id = _seed_doc(text="Notice is issued to the respondent.")

    factory = get_session_factory()
    with factory() as session:
        doc = session.get(AuthorityDocument, doc_id)
        assert doc is not None
        classify_authority_document(session, doc)
        classify_authority_document(session, doc)
        session.commit()

        rows = list(
            session.scalars(
                select(PredictiveOutcomeClassification).where(
                    PredictiveOutcomeClassification.source_id == doc_id
                )
            )
        )
        assert len(rows) == 2
        assert {row.signal_type for row in rows} == {
            "notice_issuance_likelihood",
            "forum_practice_pattern",
        }
