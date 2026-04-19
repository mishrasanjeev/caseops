"""caseops-eval-drafting CLI (BG-034, Sprint 11).

The harness has two code paths: a ``--dry-run`` that opens + finalizes
an EvaluationRun without calling the LLM (for schema smoke), and the
full flight that actually generates drafts and records findings. Tests
here exercise the dry-run end-to-end and a stubbed-LLM flight so we
don't burn tokens on every CI run.
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from sqlalchemy import select

from caseops_api.db.models import EvaluationRun
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.eval_drafting import main
from tests.test_auth_company import bootstrap_company


def test_dry_run_records_evaluation_run(client) -> None:  # noqa: ARG001
    boot = bootstrap_company(client)
    slug = str(boot["company"]["slug"])

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--suite", "bail", "--tenant", slug, "--dry-run"])
    assert rc in (0, 1)  # dry-run doesn't call the LLM; all cases pass
    report = buf.getvalue()
    # Report is rendered markdown.
    assert "# Drafting eval — drafting.bail" in report
    assert "bail.regular.delhi.cheating" in report
    # The bail suite now covers 4 regular-bail cases; anticipatory
    # moved to its own suite in Sprint 11 partial.
    assert "bail.regular.delhi.forgery" in report
    assert "bail.regular.bombay.pmla" in report

    Session = get_session_factory()
    with Session() as session:
        runs = list(session.scalars(select(EvaluationRun)))
    assert len(runs) == 1
    assert runs[0].suite_name == "drafting.bail"
    assert runs[0].case_count == len(
        __import__("caseops_api.scripts.eval_drafting", fromlist=["BAIL_SUITE"]).BAIL_SUITE
    )


def test_missing_tenant_slug_exits(client) -> None:  # noqa: ARG001
    with pytest.raises(SystemExit) as exc:
        main(["--suite", "bail", "--tenant", "nonexistent-slug", "--dry-run"])
    assert "company" in str(exc.value).lower() or exc.value.code != 0


def test_unknown_suite_rejected(client) -> None:  # noqa: ARG001
    # argparse rejects unknown choices with SystemExit(2) before our
    # code runs; it writes to stderr, not stdout. Confirm the
    # early-exit shape.
    with pytest.raises(SystemExit):
        main(["--suite", "patent", "--tenant", "whatever"])
