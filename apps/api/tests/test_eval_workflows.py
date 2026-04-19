"""Sprint 11 — workflow eval CLI plumbing (hearing-pack + recommendation)."""
from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from sqlalchemy import select

from caseops_api.db.models import EvaluationCase, EvaluationRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_drafting import BAIL_SUITE
from caseops_api.scripts.eval_workflows import (
    _validate_hearing_pack,
    _validate_recommendation,
    main,
)
from caseops_api.services.recommendations import SUPPORTED_TYPES
from tests.test_auth_company import bootstrap_company


def _slug(client) -> str:
    return str(bootstrap_company(client)["company"]["slug"])


def test_dry_run_records_both_suites(client) -> None:
    slug = _slug(client)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--suite", "all", "--tenant", slug, "--dry-run"])
    assert rc == 0
    report = buf.getvalue()
    assert "# Workflow eval" in report
    assert "hearing-pack" in report
    assert "recommendation" in report

    Session = get_session_factory()
    with Session() as session:
        runs = list(
            session.scalars(
                select(EvaluationRun).order_by(EvaluationRun.created_at.asc())
            )
        )
    suite_names = {r.suite_name for r in runs}
    assert "hearing-pack" in suite_names
    assert "recommendation" in suite_names

    hp = next(r for r in runs if r.suite_name == "hearing-pack")
    assert hp.case_count == len(BAIL_SUITE)
    assert hp.pass_count == len(BAIL_SUITE)  # dry-run forces pass

    rec = next(r for r in runs if r.suite_name == "recommendation")
    # Cross-product: 4 cases × (rec_types - 'authority') = 4 × 3
    rec_types = sorted(t for t in SUPPORTED_TYPES if t != "authority")
    assert rec.case_count == len(BAIL_SUITE) * len(rec_types)


def test_dry_run_single_suite_only_hearing_pack(client) -> None:
    slug = _slug(client)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--suite", "hearing-pack", "--tenant", slug, "--dry-run"])
    assert rc == 0
    Session = get_session_factory()
    with Session() as session:
        runs = list(session.scalars(select(EvaluationRun)))
        assert {r.suite_name for r in runs} == {"hearing-pack"}


def test_unknown_tenant_exits_clean(client) -> None:
    bootstrap_company(client)
    with pytest.raises(SystemExit) as exc:
        main(["--suite", "all", "--tenant", "no-such-tenant"])
    assert "company" in str(exc.value).lower()


def test_validate_hearing_pack_flags_empty_summary_and_no_items() -> None:
    class _Pack:
        summary = ""
        items: list[object] = []

    findings = _validate_hearing_pack(_Pack())
    codes = [f.code for f in findings]
    assert "empty_pack_summary" in codes
    assert "no_pack_items" in codes


def test_validate_hearing_pack_flags_authority_card_without_source_ref() -> None:
    class _Item:
        def __init__(self, item_type, rank, source_ref):
            self.id = f"item-{rank}"
            self.item_type = item_type
            self.rank = rank
            self.source_ref = source_ref

    class _Pack:
        summary = "Pack ready for review"
        items = [
            _Item("chronology", 1, None),
            _Item("authority_card", 2, None),  # missing source_ref → blocker
            _Item("authority_card", 3, "AUTH-XYZ"),  # ok
        ]

    findings = _validate_hearing_pack(_Pack())
    codes = [f.code for f in findings]
    assert "authority_card_missing_source_ref" in codes
    assert "no_pack_items" not in codes


def test_validate_hearing_pack_flags_unknown_kind_as_warning() -> None:
    class _Item:
        def __init__(self, item_type, rank, source_ref=None):
            self.id = f"item-{rank}"
            self.item_type = item_type
            self.rank = rank
            self.source_ref = source_ref

    class _Pack:
        summary = "ok"
        items = [_Item("frobnicate", 1)]

    findings = _validate_hearing_pack(_Pack())
    codes_severities = [(f.code, f.severity) for f in findings]
    assert ("unknown_pack_item_type", "warning") in codes_severities


def test_validate_recommendation_flags_too_few_options() -> None:
    class _Opt:
        label = "x"
        rationale = "y"
        supporting_citations_json = "[]"

    class _Rec:
        options = [_Opt()]
        primary_option_index = 0
        rationale = "Some reasoning"

    findings = _validate_recommendation(_Rec())
    codes = [f.code for f in findings]
    assert "too_few_recommendation_options" in codes


def test_validate_recommendation_flags_primary_index_out_of_range() -> None:
    class _Opt:
        label = "x"
        supporting_citations_json = "[]"

    class _Rec:
        options = [_Opt(), _Opt()]
        primary_option_index = 5
        rationale = "ok"

    findings = _validate_recommendation(_Rec())
    codes = [f.code for f in findings]
    assert "primary_index_out_of_range" in codes


def test_validate_recommendation_flags_primary_without_citations_as_warning() -> None:
    class _Opt:
        def __init__(self, cites_json: str):
            self.label = "x"
            self.supporting_citations_json = cites_json

    class _Rec:
        options = [_Opt("[]"), _Opt('["[CITE-1]"]')]
        primary_option_index = 0  # primary has no citations
        rationale = "ok"

    findings = _validate_recommendation(_Rec())
    codes_severities = [(f.code, f.severity) for f in findings]
    assert ("primary_option_no_citations", "warning") in codes_severities


def test_each_dry_run_record_persists_findings_json(client) -> None:
    """Plumbing: record_case writes findings_json with the metrics
    extra dict so downstream analytics can group by rec_type."""
    slug = _slug(client)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--suite", "all", "--tenant", slug, "--dry-run"])
    Session = get_session_factory()
    with Session() as session:
        cases = list(session.scalars(select(EvaluationCase)))
    assert len(cases) > 0
    import json
    rec_types_seen: set[str] = set()
    for c in cases:
        payload = json.loads(c.findings_json)
        if c.case_key.startswith("rec."):
            rec_types_seen.add(payload["extra"]["rec_type"])
    rec_types = sorted(t for t in SUPPORTED_TYPES if t != "authority")
    assert rec_types_seen == set(rec_types)
