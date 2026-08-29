"""WTD-11.4 offline AI safety eval harness foundation."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from sqlalchemy import select

from caseops_api.db.models import EvaluationCase, EvaluationRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_ai_safety import (
    DEFAULT_FIXTURE_PATH,
    RELEASE_FIXTURE_PATH,
    evaluate_case,
    evaluate_fixture_paths,
    load_suite,
    main,
    persist_results,
    release_gate_summary,
    results_payload,
)

FIXTURE_DIR = DEFAULT_FIXTURE_PATH.parent
NEGATIVE_FIXTURE_PATH = FIXTURE_DIR / "wtd114_negative_cases.json"
DETECTOR_FIXTURE_PATH = FIXTURE_DIR / "iplf065_detector_failures.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_eval_fixture_loading_covers_initial_ai_surfaces() -> None:
    suite = load_suite(DEFAULT_FIXTURE_PATH)

    assert suite.suite_id == "wtd-11.4-foundation-pass"
    assert len(suite.cases) >= 5
    assert len({case.case_id for case in suite.cases}) == len(suite.cases)
    assert {
        "matter_file_qa",
        "recommendation",
        "litigation_strategy",
        "hearing_pack",
    }.issubset({case.surface for case in suite.cases})


def test_passing_golden_suite_has_no_safety_failures() -> None:
    results = evaluate_fixture_paths([DEFAULT_FIXTURE_PATH])
    assert len(results) == 1
    result = results[0]

    assert result.fail_count == 0
    assert result.pass_count == len(result.case_results)
    assert result.expectation_fail_count == 0


def test_unsupported_legal_advice_and_prediction_case_fails() -> None:
    suite = load_suite(NEGATIVE_FIXTURE_PATH)
    case = next(
        item
        for item in suite.cases
        if item.case_id == "recommendation.legal_advice_and_prediction_rejected"
    )

    result = evaluate_case(case)

    assert result.status == "fail"
    assert {finding.code for finding in result.findings} >= {
        "forbidden_legal_advice",
        "forbidden_outcome_prediction",
    }


def test_missing_and_invalid_source_cases_fail() -> None:
    suite = load_suite(NEGATIVE_FIXTURE_PATH)
    by_id = {case.case_id: case for case in suite.cases}

    invalid = evaluate_case(by_id["matter_file_qa.invalid_source_rejected"])
    missing = evaluate_case(by_id["hearing_pack.missing_source_rejected"])

    assert invalid.status == "fail"
    assert "invalid_source_reference" in {finding.code for finding in invalid.findings}
    assert missing.status == "fail"
    assert "missing_source_references" in {finding.code for finding in missing.findings}


def test_prompt_injection_fixture_ignored_and_copying_rejected() -> None:
    pass_suite = load_suite(DEFAULT_FIXTURE_PATH)
    safe_case = next(
        item
        for item in pass_suite.cases
        if item.case_id == "matter_file_qa.prompt_injection_ignored"
    )
    assert evaluate_case(safe_case).status == "pass"

    negative_suite = load_suite(NEGATIVE_FIXTURE_PATH)
    unsafe_case = next(
        item
        for item in negative_suite.cases
        if item.case_id == "matter_file_qa.prompt_injection_copy_rejected"
    )
    unsafe_result = evaluate_case(unsafe_case)
    assert unsafe_result.status == "fail"
    assert "prompt_injection_copied_or_obeyed" in {
        finding.code for finding in unsafe_result.findings
    }


def test_sensitive_scoring_case_fails() -> None:
    suite = load_suite(NEGATIVE_FIXTURE_PATH)
    case = next(
        item
        for item in suite.cases
        if item.case_id == "litigation_strategy.sensitive_scoring_rejected"
    )
    result = evaluate_case(case)

    assert result.status == "fail"
    assert "forbidden_sensitive_scoring" in {finding.code for finding in result.findings}


def test_machine_readable_result_format_omits_raw_outputs() -> None:
    payload = results_payload(evaluate_fixture_paths([DEFAULT_FIXTURE_PATH]))
    encoded = json.dumps(payload)

    assert payload["harness"] == "caseops-ai-safety-eval"
    assert payload["mode"] == "offline-fixture-only"
    assert payload["summary"]["case_count"] >= 5
    first_case = payload["suites"][0]["cases"][0]
    assert {
        "case_id",
        "surface",
        "status",
        "rule_ids",
        "reason",
        "findings",
        "metrics",
    }.issubset(first_case)
    assert "source_grounding" in first_case["rule_ids"]
    assert first_case["reason"] == "passed all evaluated rules"
    assert "output" not in first_case
    assert "The complaint states that the respondent received" not in encoded


def test_cli_exit_code_and_output_file_behavior(tmp_path: Path) -> None:
    output_path = tmp_path / "ai-safety-result.json"
    stdout = StringIO()
    with redirect_stdout(stdout):
        rc = main(["--fixtures", str(DEFAULT_FIXTURE_PATH), "--output", str(output_path)])

    assert rc == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["fail_count"] == 0
    stdout_payload = json.loads(stdout.getvalue())
    assert stdout_payload["summary"]["case_count"] == payload["summary"]["case_count"]

    failing_stdout = StringIO()
    with redirect_stdout(failing_stdout):
        failing_rc = main(["--fixtures", str(NEGATIVE_FIXTURE_PATH)])
    assert failing_rc == 1
    assert json.loads(failing_stdout.getvalue())["summary"]["fail_count"] > 0


def test_release_gate_covers_every_required_surface_and_rule() -> None:
    results = evaluate_fixture_paths([RELEASE_FIXTURE_PATH])
    gate = release_gate_summary(results)

    assert gate["status"] == "pass"
    assert gate["missing_surfaces"] == []
    assert gate["missing_rules"] == []
    assert gate["fail_count"] == 0
    assert gate["expectation_fail_count"] == 0

    stdout = StringIO()
    with redirect_stdout(stdout):
        rc = main(["--release-gate"])
    payload = json.loads(stdout.getvalue())
    assert rc == 0
    assert payload["release_gate"]["status"] == "pass"
    assert "input" not in json.dumps(payload)
    assert "output" not in payload["suites"][0]["cases"][0]


def test_release_gate_rejects_incomplete_legacy_coverage() -> None:
    stdout = StringIO()
    with redirect_stdout(stdout):
        rc = main(
            [
                "--release-gate",
                "--fixtures",
                str(DEFAULT_FIXTURE_PATH),
            ]
        )
    payload = json.loads(stdout.getvalue())
    assert rc == 1
    assert payload["release_gate"]["status"] == "fail"
    assert payload["release_gate"]["missing_surfaces"]
    assert payload["release_gate"]["missing_rules"]


def test_each_iplf065_negative_detector_fails_closed() -> None:
    suite = load_suite(DETECTOR_FIXTURE_PATH)
    by_id = {case.case_id: evaluate_case(case) for case in suite.cases}

    assert all(result.status == "fail" for result in by_id.values())
    codes = {
        case_id: {finding.code for finding in result.findings}
        for case_id, result in by_id.items()
    }
    assert "unsupported_claim" in codes["detector.unsupported_claim"]
    assert {
        "inaccessible_source_reference",
        "unpermitted_source_reference",
        "unverified_source_reference",
    }.issubset(codes["detector.source_access_and_permission"])
    assert "irrelevant_authority_reference" in codes["detector.irrelevant_authority"]
    assert "contrary_authority_omitted" in codes["detector.contrary_authority_omitted"]
    assert "abstention_missing_suggested_search" in codes[
        "detector.abstention_without_search"
    ]
    assert "statute_mismatch" in codes["detector.statute_confusion"]
    assert "forbidden_token_exfiltration" in codes["detector.exfiltration"]


def test_release_results_use_canonical_evaluation_tables(client) -> None:  # noqa: ARG001
    results = evaluate_fixture_paths([RELEASE_FIXTURE_PATH])
    with get_session_factory()() as session:
        run = persist_results(session, results, git_sha="iplf065-test-sha")
        session.commit()
        session.refresh(run)

        assert isinstance(run, EvaluationRun)
        assert run.case_count == 8
        assert run.pass_count == 8
        assert run.fail_count == 0
        metrics = json.loads(run.metrics_json or "{}")
        assert metrics["release_gate"]["status"] == "pass"
        assert metrics["release_gate"]["missing_rules"] == []
        cases = list(
            session.scalars(
                select(EvaluationCase).where(EvaluationCase.run_id == run.id)
            )
        )
        assert len(cases) == 8
        for case in cases:
            persisted = json.loads(case.findings_json or "{}")
            assert "input" not in persisted
            assert "output" not in persisted
            assert set(persisted) <= {"findings", "extra"}


def test_docs_status_marks_wtd114_as_implemented_with_release_boundaries() -> None:
    strict = (REPO_ROOT / "docs" / "STRICT_ENTERPRISE_GAP_TASKLIST.md").read_text(
        encoding="utf-8"
    )
    wtd = (REPO_ROOT / "docs" / "WORK_TO_BE_DONE.md").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs" / "runbooks" / "ai-safety-eval-harness.md").read_text(
        encoding="utf-8"
    )

    assert "`WTD-11.4` `Implemented`" in strict
    assert "WTD-11.4 AI safety tests -- IMPLEMENTED" in wtd
    assert "--release-gate" in runbook
    for surface_label in (
        "drafting",
        "citation validation",
        "Matter File Q&A",
        "recommendations",
        "Litigation Strategy",
        "hearing packs",
        "Ask this Workspace",
        "intelligent review",
    ):
        assert surface_label.lower() in runbook.lower()
    assert "does not call an LLM provider" in runbook
    assert "live-provider benchmark requires separate approval" in runbook
