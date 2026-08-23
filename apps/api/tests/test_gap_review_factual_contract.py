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
    assert gate["BUCKET_THRESHOLDS"]["schemas"][1] is None
    assert all(
        gate["BUCKET_THRESHOLDS"][bucket][1] is not None
        for bucket in ("api", "core", "db", "services")
    )
    assert gate["TOTAL_LINE_MIN"] > 0
    assert gate["TOTAL_BRANCH_MIN"] > 0

    review = _read("docs/STRATEGIC_GAP_REVIEW_2026-08-16.md")
    ledger = _read("docs/STRICT_ENTERPRISE_GAP_TASKLIST.md")
    for document in (review, ledger):
        compact = _compact(document)
        assert "9 direct per-file floors" in compact
        assert "line floors" in compact
        assert "5 `api`/`core`/`db`/`schemas`/`services` buckets" in compact
        assert "branch floors for `api`/`core`/`db`/`services`" in compact
        assert "not `schemas`" in compact or "has no branch floor" in compact
        assert "overall line/branch floors" in compact
        assert "untracked modules are ungated" not in compact
        assert "coverage is measured but never gated" not in compact.lower()

def test_workflow_activation_is_runtime_state_not_a_project_gate() -> None:
    backlog = _read("docs/EXECUTION_BACKLOG.md")
    feedback = _read("docs/FEEDBACK_MERGE_BACKLOG_2026-08-16.md")
    resolutions = _read("docs/OPEN_ITEM_RESOLUTIONS_2026-08-16.md")
    ownership = _read("docs/ip-implementation/OWNERSHIP_LEDGER.yaml")
    models = _read("apps/api/src/caseops_api/db/models.py")

    assert "No manual project approval or sign-off gates" in backlog
    assert "Machine-enforced runtime controls remain" in backlog
    for document in (feedback, resolutions):
        compact = _compact(document)
        assert "No workflow service or route exists today" in compact
        assert "existing approval path" not in compact
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
    assert "`EH-SGR-09`, `EH-SGR-17`" in backlog
    assert "Turn on useful observability and enforce legal holds/retention" in backlog
    assert "`EH-SGR-13`, `EH-SGR-14`" in backlog
    assert "one primary-identifier rule and one terminal-status definition" in backlog
