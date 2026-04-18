"""Evaluation-run recorder (§7.3)."""
from __future__ import annotations

import json

from caseops_api.db.session import get_session_factory
from caseops_api.services.draft_validators import DraftFinding
from caseops_api.services.evaluation import (
    CASE_STATUS_ERROR,
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    CaseMetrics,
    finalize_run,
    open_run,
    record_case,
)


def _blocker(code: str) -> DraftFinding:
    return DraftFinding(code=code, severity="blocker", message="bad")


def _warning(code: str) -> DraftFinding:
    return DraftFinding(code=code, severity="warning", message="heads-up")


def test_pass_and_fail_are_both_recorded(client) -> None:  # noqa: ARG001
    Session = get_session_factory()
    with Session() as session:
        run = open_run(session, suite_name="drafting", provider="mock", model="m1")
        record_case(
            session,
            run=run,
            case_key="bail-clean",
            findings=[_warning("citation.coverage_gap")],
            metrics=CaseMetrics(body_chars=4200, verified_citation_count=2),
        )
        record_case(
            session,
            run=run,
            case_key="bail-hallucinated-statute",
            findings=[_blocker("statute.bns_bnss_confusion"), _warning("c")],
            metrics=CaseMetrics(body_chars=4100, verified_citation_count=0),
        )
        record_case(
            session,
            run=run,
            case_key="bail-provider-crashed",
            findings=[],
            error="LLMProviderError: 429 rate limited",
        )
        finalize_run(session, run)
        session.commit()

        session.refresh(run)

    assert run.case_count == 3
    assert run.pass_count == 1
    assert run.fail_count == 2
    assert run.completed_at is not None

    metrics = json.loads(run.metrics_json or "{}")
    assert metrics["by_status"] == {
        CASE_STATUS_PASS: 1,
        CASE_STATUS_FAIL: 1,
        CASE_STATUS_ERROR: 1,
    }
    assert metrics["total_blockers"] == 1
    assert metrics["total_warnings"] == 2
    assert metrics["avg_verified_citations"] == (2 + 0 + 0) / 3


def test_findings_are_serialised_on_the_case(client) -> None:  # noqa: ARG001
    Session = get_session_factory()
    with Session() as session:
        run = open_run(session, suite_name="drafting", provider="mock", model="m1")
        case = record_case(
            session,
            run=run,
            case_key="bail-sample",
            findings=[
                _blocker("statute.bns_bnss_confusion"),
                _warning("citation.coverage_gap"),
            ],
            metrics=CaseMetrics(body_chars=5000, verified_citation_count=1),
        )
        session.commit()
        session.refresh(case)

    payload = json.loads(case.findings_json or "{}")
    codes = [f["code"] for f in payload["findings"]]
    assert codes == [
        "statute.bns_bnss_confusion",
        "citation.coverage_gap",
    ]
    assert case.blocker_count == 1
    assert case.warning_count == 1
    assert case.status == CASE_STATUS_FAIL


def test_open_run_carries_provenance(client) -> None:  # noqa: ARG001
    Session = get_session_factory()
    with Session() as session:
        run = open_run(
            session,
            suite_name="drafting",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            git_sha="abc1234",
        )
        session.commit()
        session.refresh(run)
    assert run.suite_name == "drafting"
    assert run.provider == "anthropic"
    assert run.model == "claude-haiku-4-5-20251001"
    assert run.git_sha == "abc1234"
    assert run.started_at is not None
