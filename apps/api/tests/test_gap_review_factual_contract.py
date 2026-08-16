"""Factual contract for the 2026-08-16 gap-review correction."""
from __future__ import annotations

import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _compact(value: str) -> str:
    return " ".join(value.split())


def test_documented_coverage_scope_matches_the_gate() -> None:
    gate = runpy.run_path(str(REPO_ROOT / "scripts" / "coverage_gate.py"))
    assert len(gate["THRESHOLDS"]) == 9
    assert set(gate["BUCKET_THRESHOLDS"]) == {
        "api",
        "core",
        "db",
        "schemas",
        "services",
    }
    assert gate["TOTAL_LINE_MIN"] > 0
    assert gate["TOTAL_BRANCH_MIN"] > 0

    review = _read("docs/STRATEGIC_GAP_REVIEW_2026-08-16.md")
    ledger = _read("docs/STRICT_ENTERPRISE_GAP_TASKLIST.md")
    for document in (review, ledger):
        compact = _compact(document)
        assert "9 direct per-file floors" in compact
        assert "5 `api`/`core`/`db`/`schemas`/`services` buckets" in compact
        assert "overall line/branch floors" in compact
        assert "untracked modules are ungated" not in compact
        assert "coverage is measured but never gated" not in compact.lower()


def test_workflow_approval_is_not_claimed_without_runtime_state() -> None:
    backlog = _read("docs/EXECUTION_BACKLOG.md")
    ownership = _read("docs/ip-implementation/OWNERSHIP_LEDGER.yaml")
    models = _read("apps/api/src/caseops_api/db/models.py")

    assert "No active workflow definition" in backlog
    assert "must first be seeded as `candidate`" in backlog
    assert "version 1 already approved" not in backlog.lower()
    assert "seeds no active workflow" in ownership
    assert 'default="candidate"' in models


def test_residency_and_eval_claims_remain_evidence_bounded() -> None:
    review = _read("docs/STRATEGIC_GAP_REVIEW_2026-08-16.md")
    corpus_ingest = _read("apps/api/src/caseops_api/services/corpus_ingest.py")
    evaluation = _read("apps/api/src/caseops_api/services/evaluation.py")
    safety_eval = _read("apps/api/src/caseops_api/scripts/eval_ai_safety.py")
    drafting_result = _read("docs/EVAL_DRAFTING_QUALITY.md")

    assert "does **not** prove end-to-end India-resident processing" in review
    assert 'region_name="us-east-1"' in corpus_ingest
    assert "does not itself drive a benchmark loop" in evaluation
    assert "fixture-only" in safety_eval
    assert "4.41/5" in drafting_result
    assert "Target: **4.8/5**" in drafting_result
    assert "eval harness (T2-11, good suite" not in review


def test_historical_benchmark_sources_keep_names_and_urls() -> None:
    april = _read("docs/PRODUCT_GAP_ANALYSIS_2026-04-30.md")
    may = _read("docs/PRODUCT_GAP_ANALYSIS_2026-05-01.md")
    expected_urls = {
        "https://www.scconline.com/ai-pro",
        "https://www.manupatra.ai/legal-research",
        "https://www.clio.com/features/",
        "https://legal.thomsonreuters.com/en/legal/financial-management/"
        "outside-counsel-spend",
        "https://legal.thomsonreuters.com/en/products/cocounsel-legal",
        "https://support.ironcladapp.com/hc/en-us/articles/12947738534935-"
        "Ironclad-AI-Overview",
        "https://www.harvey.ai/platform",
    }
    for url in expected_urls:
        assert url in april
        assert url in may
    assert "https://www.lexisnexis.com/en-us/products/lexis-plus-ai.page" in may


def test_gst_and_owner_contracts_are_scoped_and_collision_free() -> None:
    review = _read("docs/STRATEGIC_GAP_REVIEW_2026-08-16.md")
    ledger = _read("docs/STRICT_ENTERPRISE_GAP_TASKLIST.md")
    backlog = _read("docs/EXECUTION_BACKLOG.md")

    for document in (review, ledger):
        assert "recipient's address on record when it exists" in document
        assert "supplier's location only" in document
        assert "unregistered clients resolve to the supplier's state" not in document
    assert "GO for continued repository implementation" in review
    assert "does not block unrelated repository implementation" in _compact(ledger)
    assert "| Either |" not in backlog
    for service in (
        "services/matter_billing.py",
        "services/matters.py",
        "services/portal_outside_counsel.py",
        "services/pine_labs.py",
        "services/court_sync_sources.py",
        "services/hearing_reminders.py",
        "services/ip_records.py",
        "services/ip_lifecycle.py",
    ):
        assert service in backlog
