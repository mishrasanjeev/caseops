"""Sprint 11 — citation-quality eval CLI plumbing."""
from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import EvaluationCase, EvaluationRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_citations import (
    CITATION_SEEDS,
    CitationCase,
    _format_report,
    main,
)
from tests.test_auth_company import bootstrap_company


def _bootstrap_and_get_slug(client: TestClient) -> str:
    bootstrap_company(client)
    Session = get_session_factory()
    from caseops_api.db.models import Company

    with Session() as session:
        company = session.scalars(select(Company)).first()
        assert company is not None
        return company.slug


def test_seed_cases_are_well_formed() -> None:
    keys = [c.key for c in CITATION_SEEDS]
    assert len(keys) == len(set(keys)), "seed keys must be unique"
    for c in CITATION_SEEDS:
        assert c.query and len(c.query) >= 4
        assert c.expected_substrings, f"{c.key}: at least one expected_substring"
        assert all(s.strip() for s in c.expected_substrings)


def test_dry_run_records_a_full_run_without_calling_search(
    client: TestClient,
) -> None:
    slug = _bootstrap_and_get_slug(client)
    captured = StringIO()
    with patch("sys.stdout", captured):
        rc = main(["--tenant", slug, "--dry-run"])
    assert rc == 0
    report = captured.getvalue()
    assert "# Citation-quality eval" in report
    assert "## Aggregate" in report

    Session = get_session_factory()
    with Session() as session:
        run = session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.suite_name == "citation-quality")
            .order_by(EvaluationRun.created_at.desc())
        ).first()
        assert run is not None
        assert run.case_count == len(CITATION_SEEDS)
        assert run.pass_count == len(CITATION_SEEDS)
        assert run.fail_count == 0
        cases = session.scalars(
            select(EvaluationCase).where(EvaluationCase.run_id == run.id)
        ).all()
        assert len(cases) == len(CITATION_SEEDS)
        for case in cases:
            payload = json.loads(case.findings_json)
            assert payload["extra"]["dry_run"] is True


def test_unknown_tenant_exits_clean(client: TestClient) -> None:
    bootstrap_company(client)  # warm up DB
    with pytest.raises(SystemExit) as exc:
        main(["--tenant", "no-such-firm-12345"])
    assert "no company" in str(exc.value).lower()


def test_format_report_handles_empty_case_list() -> None:
    """Defensive — finalize emits an empty table cleanly."""

    class _StubRun:
        suite_name = "citation-quality"
        provider = "x"
        model = "y"
        case_count = 0
        pass_count = 0
        fail_count = 0

    out = _format_report(_StubRun(), [])
    assert "## Aggregate" in out
    assert "hit@1**: 0/1" in out  # zero-safe guard


def test_per_case_metrics_get_persisted_to_findings_json(
    client: TestClient,
) -> None:
    """The CaseMetrics(extra=...) dict makes it into findings_json so
    later analytics can group hit@5 by suite without re-running."""
    slug = _bootstrap_and_get_slug(client)
    captured = StringIO()
    with patch("sys.stdout", captured):
        main(["--tenant", slug, "--dry-run"])

    Session = get_session_factory()
    with Session() as session:
        run = session.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.suite_name == "citation-quality")
            .order_by(EvaluationRun.created_at.desc())
        ).first()
        case = session.scalars(
            select(EvaluationCase).where(EvaluationCase.run_id == run.id).limit(1)
        ).first()
        payload = json.loads(case.findings_json)
        assert "extra" in payload


def test_citation_case_query_terms_filters_short_words() -> None:
    case = CitationCase(
        key="t", query="of in by Section 482 quashing FIR",
        expected_substrings=("482",),
    )
    terms = case.query_terms()
    assert "of" not in terms and "in" not in terms and "by" not in terms
    assert "section" in terms and "482" in terms and "quashing" in terms
