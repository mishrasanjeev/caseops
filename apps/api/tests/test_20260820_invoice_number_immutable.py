"""EH-SGR-04: an issued invoice number must not be rewritable.

The gap ledger recorded immutability as existing "only because no edit endpoint
was written - no CHECK, trigger or revision table". That is the absence of an
opportunity, not a control: a future route, a maintenance script, or a psql
session could rewrite the number on an issued invoice and nothing would object.

Under Indian GST a tax invoice number is fixed at issue; corrections go through
a credit or debit note. So this is a statutory expectation, and the control
belongs where every writer must pass through it.

Migration `20260820_0002` adds both halves.

This file holds only the assertions that run everywhere. The trigger itself is
PostgreSQL-only and is proven in `tests/test_postgres_validation.py`, because
the `postgres-validation` CI job runs exactly one file:

    uv run pytest -q -m postgres tests/test_postgres_validation.py

A `@pytest.mark.postgres` test in any other module is skipped on the default
shards AND never selected by that job - it runs nowhere while still reading as
coverage. The first draft of this file made exactly that mistake, and its four
"skipped" results looked like evidence of a control nobody had exercised.
"""

from __future__ import annotations

import pathlib
import re

_MIGRATION = pathlib.Path(
    "alembic/versions/20260820_0002_invoice_number_immutable.py"
)


class TestTheControlIsDeclaredNotIncidental:
    """Cheap assertions that run on every shard, including plain SQLite."""

    def test_model_declares_the_non_blank_check(self) -> None:
        from caseops_api.db.models import MatterInvoice

        names = {
            c.name for c in MatterInvoice.__table__.constraints if c.name is not None
        }
        assert "ck_matter_invoice_number_not_blank" in names

    def test_no_code_path_assigns_invoice_number_after_creation(self) -> None:
        """The trigger locks in current behaviour; prove that is still true.

        If a legitimate rewrite path is ever added, this fails first and forces
        the question to be answered deliberately, rather than discovered as a
        production exception when the trigger rejects the UPDATE.
        """
        assign = re.compile(r"\.invoice_number\s*=(?!=)")
        offenders: list[str] = []
        for path in pathlib.Path("src/caseops_api").rglob("*.py"):
            for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if assign.search(line):
                    offenders.append(f"{path}:{i}: {line.strip()}")
        assert not offenders, (
            "invoice_number is assigned outside creation; the immutability "
            "trigger will reject this at runtime:\n" + "\n".join(offenders)
        )

    def test_migration_is_dialect_guarded_and_carries_the_marker(self) -> None:
        body = _MIGRATION.read_text(encoding="utf-8")
        assert "DATA-GOVERNANCE-MAP: updated" in body
        assert 'dialect.name == "postgresql"' in body
        # Conditional on the column actually changing, or every unrelated
        # invoice UPDATE pays for a function call.
        assert "IS DISTINCT FROM OLD.invoice_number)" in body


class TestTheTriggerProofIsSomewhereCIRunsIt:
    """Guard against the coverage illusion this file was briefly an example of.

    A `@pytest.mark.postgres` test only executes if it lives in the single file
    the `postgres-validation` job names. If the trigger assertions drift back
    out of that file, they stop running and nothing else notices.
    """

    def test_the_trigger_assertions_live_in_the_file_ci_runs(self) -> None:
        pg_suite = pathlib.Path("tests/test_postgres_validation.py").read_text(
            encoding="utf-8"
        )
        assert "test_invoice_number_cannot_be_rewritten_on_postgres" in pg_suite
        assert "test_blank_invoice_number_is_rejected_on_postgres" in pg_suite

    def test_this_file_declares_no_postgres_tests(self) -> None:
        """If someone adds one here, it would silently never run."""
        body = pathlib.Path(__file__).read_text(encoding="utf-8")
        decorators = [
            line
            for line in body.splitlines()
            if line.strip().startswith("@pytest.mark.postgres")
        ]
        assert not decorators, (
            "a @pytest.mark.postgres test in this module runs nowhere: it is "
            "skipped on the default shards and not selected by the "
            "postgres-validation job. Move it to tests/test_postgres_validation.py"
        )
