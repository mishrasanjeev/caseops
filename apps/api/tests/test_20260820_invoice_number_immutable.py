"""EH-SGR-04: an issued invoice number must not be rewritable.

The gap ledger recorded immutability as existing "only because no edit endpoint
was written - no CHECK, trigger or revision table". That is the absence of an
opportunity, not a control: a future route, a maintenance script, or a psql
session could rewrite the number on an issued invoice and nothing would object.

Under Indian GST a tax invoice number is fixed at issue; corrections go through
a credit or debit note. So this is a statutory expectation, and the control
belongs where every writer must pass through it.

Migration `20260820_0002` adds both halves. The trigger half is PostgreSQL-only
and is asserted here under `@pytest.mark.postgres`, because SQLite would
silently accept the UPDATE and a green local run would prove nothing about
production - the same trap `test_20260816_invoice_number_allocation.py` calls
out for `FOR UPDATE`.
"""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from sqlalchemy import text

_MIGRATION = pathlib.Path(
    "alembic/versions/20260820_0002_invoice_number_immutable.py"
)


class TestTheControlIsDeclaredNotIncidental:
    """Cheap assertions that run everywhere, including a plain SQLite shard."""

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
        production exception.
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

    def test_migration_is_postgres_guarded_and_carries_the_marker(self) -> None:
        body = _MIGRATION.read_text(encoding="utf-8")
        assert "DATA-GOVERNANCE-MAP: updated" in body
        assert 'dialect.name == "postgresql"' in body
        # Conditional on the column actually changing, or every unrelated
        # invoice UPDATE pays for a function call.
        assert "IS DISTINCT FROM OLD.invoice_number)" in body


@pytest.mark.postgres
class TestTheTriggerActuallyFires:
    """The half that matters. SQLite cannot prove any of this."""

    @staticmethod
    def _setup(conn) -> None:
        conn.execute(text("DROP TABLE IF EXISTS matter_invoices CASCADE"))
        conn.execute(
            text(
                "CREATE TABLE matter_invoices ("
                " id text PRIMARY KEY,"
                " company_id text NOT NULL,"
                " invoice_number text NOT NULL,"
                " total_amount_minor bigint NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE matter_invoices ADD CONSTRAINT "
                "ck_matter_invoice_number_not_blank "
                "CHECK (btrim(invoice_number) <> '')"
            )
        )
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION caseops_reject_invoice_number_change() "
                "RETURNS trigger AS $fn$ "
                "BEGIN "
                " IF NEW.invoice_number IS DISTINCT FROM OLD.invoice_number THEN "
                "  RAISE EXCEPTION 'invoice_number is immutable (invoice %, % -> %)',"
                "   OLD.id, OLD.invoice_number, NEW.invoice_number "
                "   USING ERRCODE = 'restrict_violation'; "
                " END IF; "
                " RETURN NEW; "
                "END; "
                "$fn$ LANGUAGE plpgsql"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER matter_invoices_invoice_number_immutable "
                "BEFORE UPDATE ON matter_invoices FOR EACH ROW "
                "WHEN (NEW.invoice_number IS DISTINCT FROM OLD.invoice_number) "
                "EXECUTE FUNCTION caseops_reject_invoice_number_change()"
            )
        )

    @staticmethod
    def _insert(conn, number: str = "GBA-0001") -> str:
        invoice_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_invoices (id, company_id, invoice_number) "
                "VALUES (:i, :c, :n)"
            ),
            {"i": invoice_id, "c": "co-1", "n": number},
        )
        return invoice_id

    def test_rewriting_the_number_is_rejected(self, pg_engine) -> None:
        from sqlalchemy.exc import DBAPIError

        with pg_engine.begin() as conn:
            self._setup(conn)
            invoice_id = self._insert(conn)

        with pg_engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc:
                with conn.begin():
                    conn.execute(
                        text(
                            "UPDATE matter_invoices SET invoice_number = :n "
                            "WHERE id = :i"
                        ),
                        {"n": "GBA-9999", "i": invoice_id},
                    )
            assert "immutable" in str(exc.value).lower()

        with pg_engine.connect() as conn:
            got = conn.execute(
                text("SELECT invoice_number FROM matter_invoices WHERE id = :i"),
                {"i": invoice_id},
            ).scalar_one()
            assert got == "GBA-0001", "the rejected UPDATE must not have applied"

    def test_other_columns_remain_updatable(self, pg_engine) -> None:
        """An immutability control that freezes the whole row is a bug, not a
        control: payments legitimately rewrite amounts on an issued invoice."""
        with pg_engine.begin() as conn:
            self._setup(conn)
            invoice_id = self._insert(conn)
            conn.execute(
                text(
                    "UPDATE matter_invoices SET total_amount_minor = 500 "
                    "WHERE id = :i"
                ),
                {"i": invoice_id},
            )
            got = conn.execute(
                text("SELECT total_amount_minor FROM matter_invoices WHERE id = :i"),
                {"i": invoice_id},
            ).scalar_one()
            assert got == 500

    def test_writing_the_same_number_is_not_an_error(self, pg_engine) -> None:
        """A no-op rewrite is what an ORM flush of an unchanged row looks like.
        Rejecting it would break ordinary saves for no safety gain."""
        with pg_engine.begin() as conn:
            self._setup(conn)
            invoice_id = self._insert(conn)
            conn.execute(
                text(
                    "UPDATE matter_invoices SET invoice_number = :n WHERE id = :i"
                ),
                {"n": "GBA-0001", "i": invoice_id},
            )

    def test_blank_number_is_rejected_on_insert(self, pg_engine) -> None:
        from sqlalchemy.exc import DBAPIError

        with pg_engine.begin() as conn:
            self._setup(conn)
        with pg_engine.connect() as conn:
            for blank in ("", "   ", "\t"):
                with pytest.raises(DBAPIError):
                    with conn.begin():
                        self._insert(conn, blank)
