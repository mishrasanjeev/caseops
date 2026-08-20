"""Make an issued invoice number immutable and non-blank at the database.

DATA-GOVERNANCE-MAP: updated

EH-SGR-04. The gap ledger recorded invoice-number immutability as existing
"only because no edit endpoint was written - no CHECK, trigger or revision
table". That is not a control; it is the absence of an opportunity. Any future
route, a maintenance script, or a psql session could rewrite the number on an
issued invoice and nothing would object.

Under Indian GST a tax invoice number is fixed once the invoice is issued -
corrections are made by credit or debit note, never by altering the original.
So immutability here is a statutory expectation, not a nicety, and it belongs
at the level that every writer must pass through.

Two controls:

1. ``ck_matter_invoice_number_not_blank`` - a number that is empty or only
   whitespace is not a number. Cheap, and it also holds on SQLite because the
   constraint is declared on the model.
2. ``matter_invoices_invoice_number_immutable`` - a BEFORE UPDATE trigger that
   raises when ``invoice_number`` changes. Absolute rather than conditional on
   status: no code path in the repository updates the column today (only
   equality comparisons in ``services/matters.py``), so this locks in current
   behaviour rather than changing it.

A revision table is deliberately NOT added. The ledger lists it as one of three
absent mechanisms, but a revision history records permitted changes; once the
column cannot change there is nothing for it to record. Adding one would imply
a mutation path that must not exist.

PostgreSQL only. SQLite ignores what it cannot parse here, and the
``@pytest.mark.postgres`` regression is what proves the trigger actually fires -
a green SQLite run would prove nothing about production.
"""

from __future__ import annotations

from alembic import op

revision = "20260820_0002"
down_revision = "20260820_0001"
branch_labels = None
depends_on = None

_TRIGGER = "matter_invoices_invoice_number_immutable"
_FUNCTION = "caseops_reject_invoice_number_change"
_CHECK = "ck_matter_invoice_number_not_blank"


def upgrade() -> None:
    bind = op.get_bind()

    # The CHECK applies on every dialect so the model declaration is true
    # everywhere. Test databases are built by replaying these revisions, not by
    # ``metadata.create_all``, so a PostgreSQL-only constraint would leave the
    # model asserting something the SQLite suite does not enforce.
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            ALTER TABLE matter_invoices
            ADD CONSTRAINT {_CHECK}
            CHECK (btrim(invoice_number) <> '')
            NOT VALID
            """
        )
        # NOT VALID then VALIDATE: the check applies to every new and updated
        # row immediately, while the scan of existing rows takes only a SHARE
        # UPDATE EXCLUSIVE lock instead of blocking writes for the full scan.
        op.execute(f"ALTER TABLE matter_invoices VALIDATE CONSTRAINT {_CHECK}")
    else:
        with op.batch_alter_table("matter_invoices") as batch:
            batch.create_check_constraint(_CHECK, "trim(invoice_number) <> ''")
        # The trigger below is PostgreSQL-only; SQLite gets the CHECK and
        # nothing else. That is why the immutability regression is marked
        # @pytest.mark.postgres rather than run on the default suite.
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            IF NEW.invoice_number IS DISTINCT FROM OLD.invoice_number THEN
                RAISE EXCEPTION
                    'invoice_number is immutable (invoice %, % -> %)',
                    OLD.id, OLD.invoice_number, NEW.invoice_number
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE ON matter_invoices
        FOR EACH ROW
        WHEN (NEW.invoice_number IS DISTINCT FROM OLD.invoice_number)
        EXECUTE FUNCTION {_FUNCTION}()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        with op.batch_alter_table("matter_invoices") as batch:
            batch.drop_constraint(_CHECK, type_="check")
        return
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON matter_invoices")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}()")
    op.execute(f"ALTER TABLE matter_invoices DROP CONSTRAINT IF EXISTS {_CHECK}")
