from pathlib import Path

import pytest

from caseops_api.scripts.autonomous_corpus_controller import (
    BucketPlan,
    BucketState,
    CorpusController,
    EvalMetrics,
    HygieneMetrics,
    StopLinePolicy,
    acquire_lock,
    autonomous_sweep_plan,
    classify_bucket,
    default_wave3_plan,
    parse_eval_report,
    release_lock,
    score_rating,
)


def _metrics(recall: float, mrr: float, rank: float) -> EvalMetrics:
    return EvalMetrics(
        recall_at_10=recall,
        mrr=mrr,
        mean_rank=rank,
        pass_count=int(recall * 30),
        total_count=30,
    )


def test_parse_eval_report_and_rating_rubric() -> None:
    report = """
# HNSW recall@10 benchmark
- **recall@10**: 28/30 (93.3 %)
- **MRR**: 0.917
- **mean rank (when found)**: 1.04
"""

    metrics = parse_eval_report(report)

    assert metrics.pass_count == 28
    assert metrics.total_count == 30
    assert metrics.recall_at_10 == pytest.approx(0.933)
    assert metrics.mrr == 0.917
    assert metrics.mean_rank == 1.04
    assert score_rating(metrics) == 4.8


def test_classification_accepts_target_quality() -> None:
    result = classify_bucket(
        metrics=_metrics(0.967, 0.95, 1.1),
        hygiene=HygieneMetrics(docs=100, dirty_metadata_chunks=0),
        policy=StopLinePolicy(),
        recovery_attempts=0,
    )

    assert result.state == BucketState.ACCEPTED
    assert result.rating == 5.0


def test_classification_accepts_clean_redline_quality_with_caveat_by_default() -> None:
    result = classify_bucket(
        metrics=_metrics(1.0, 0.931, 1.37),
        hygiene=HygieneMetrics(docs=4342, dirty_metadata_chunks=0),
        policy=StopLinePolicy(max_recovery_attempts=2),
        recovery_attempts=0,
    )

    assert result.state == BucketState.ACCEPTED_WITH_CAVEAT
    assert result.rating == 4.0


def test_classification_can_require_targeted_recovery_before_caveat() -> None:
    policy = StopLinePolicy(max_recovery_attempts=2, recover_below_target=True)

    first = classify_bucket(
        metrics=_metrics(1.0, 0.931, 1.37),
        hygiene=HygieneMetrics(docs=4342, dirty_metadata_chunks=0),
        policy=policy,
        recovery_attempts=0,
    )
    final = classify_bucket(
        metrics=_metrics(1.0, 0.931, 1.37),
        hygiene=HygieneMetrics(docs=4342, dirty_metadata_chunks=0),
        policy=policy,
        recovery_attempts=2,
    )

    assert first.state == BucketState.RECOVERY_REQUIRED
    assert first.rating == 4.0
    assert final.state == BucketState.ACCEPTED_WITH_CAVEAT
    assert final.reason.startswith("clean bucket remains below target")


def test_classification_pauses_on_red_lines() -> None:
    policy = StopLinePolicy()

    unembedded = classify_bucket(
        metrics=_metrics(1.0, 0.95, 1.0),
        hygiene=HygieneMetrics(docs=100, unembedded_chunks_global=1),
        policy=policy,
        recovery_attempts=0,
    )
    drift = classify_bucket(
        metrics=_metrics(1.0, 0.95, 1.0),
        hygiene=HygieneMetrics(docs=100, embedding_drift_chunks_global=1),
        policy=policy,
        recovery_attempts=0,
    )
    low_rating = classify_bucket(
        metrics=_metrics(0.70, 0.60, 2.0),
        hygiene=HygieneMetrics(docs=100),
        policy=policy,
        recovery_attempts=2,
    )

    assert unembedded.state == BucketState.PAUSED_FOR_HUMAN
    assert drift.state == BucketState.PAUSED_FOR_HUMAN
    assert low_rating.state == BucketState.PAUSED_FOR_HUMAN


def test_classification_recovers_dirty_metadata_until_cap() -> None:
    result = classify_bucket(
        metrics=_metrics(1.0, 0.95, 1.0),
        hygiene=HygieneMetrics(docs=100, dirty_metadata_chunks=2),
        policy=StopLinePolicy(dirty_title_rate_cap=0.01),
        recovery_attempts=0,
    )

    assert result.state == BucketState.RECOVERY_REQUIRED
    assert "dirty metadata rate" in result.reason


def test_controller_lock_is_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / "controller.lock"

    acquire_lock(lock_path)
    try:
        with pytest.raises(RuntimeError, match="controller lock already exists"):
            acquire_lock(lock_path)
    finally:
        release_lock(lock_path)

    assert not lock_path.exists()


def test_controller_dry_run_only_plans_without_db_or_paid_commands(tmp_path: Path) -> None:
    controller = CorpusController(
        base_dir=tmp_path,
        tenant_slug="aster-demo",
        policy=StopLinePolicy(),
        dry_run=True,
    )

    assert controller.run([default_wave3_plan()[0]]) == 0

    ledger = (tmp_path / "controller-ledger.jsonl").read_text(encoding="utf-8")
    assert '"controller_started"' in ledger
    assert '"planned"' in ledger
    assert not (tmp_path / "controller.lock").exists()


def test_default_wave3_plan_is_scoped_and_non_destructive() -> None:
    plan = default_wave3_plan()

    assert plan[0] == BucketPlan(
        label="delhi-hc-remaining-2026",
        forum_level="high_court",
        court_name="Delhi High Court",
        source_year=2026,
        language="english",
        limit=10,
    )
    assert [bucket.label for bucket in plan[1:]] == [
        "sc-non-en-2024",
        "sc-non-en-2023",
        "sc-non-en-2022",
    ]
    assert all(bucket.language == "non_english" for bucket in plan[1:])


def test_autonomous_sweep_plan_prioritizes_sc_then_supported_high_courts() -> None:
    plan = autonomous_sweep_plan()

    assert plan[0] == BucketPlan(
        label="supreme-court-2025",
        forum_level="supreme_court",
        court_name="Supreme Court of India",
        source_year=2025,
        language="any",
    )
    assert plan[35].label == "supreme-court-1990"
    assert plan[36] == BucketPlan(
        label="delhi-high-court-2025",
        forum_level="high_court",
        court_name="Delhi High Court",
        source_year=2025,
        language="any",
        court_key="delhi",
    )
    assert any(bucket.court_name == "Patna High Court" for bucket in plan)
