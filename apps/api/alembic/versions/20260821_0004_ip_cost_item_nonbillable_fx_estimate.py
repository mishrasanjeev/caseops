"""Let an IP cost be nonbillable, converted, estimated, or rate-confidential.

Revision ID: 20260821_0004
Revises: 20260821_0003

DATA-GOVERNANCE-MAP: updated
Every column added here extends the existing ``ip_cost_items`` record.
``fx_rate``/``fx_rate_source``/``fx_converted_at``/``base_amount_minor``/
``base_currency`` are further financial evidence under that table's existing
retention class; ``billable``, ``cost_nature`` and ``rate_confidential`` are
classification flags over the same row. No new retention class, subprocessor,
or export boundary is introduced.

IPLF-039F. Four of the seven UJ-52 paths had no representation in the schema,
and the slice blocker recorded one of them as actively contradicted:

* **UJ-52-EXC-01** ``matter_id`` was ``NOT NULL``, so a docket with no billing
  Matter could not record a cost at all. The journey requires the opposite:
  "No billing Matter blocks billable time/invoicing **but not nonbillable
  legal-cost capture**". An official fee paid to the registry is incurred
  whether or not a billing profile exists; refusing it loses the evidence
  rather than deferring the billing decision. ``matter_id`` becomes nullable
  and ``billable`` records the decision explicitly.
* **UJ-52-EXC-02** there was no way to state that an amount is a conversion.
  ``amount_minor``/``currency`` keep meaning the *original* amount as
  incurred - the five FX columns are additive and record what it was converted
  to, at what rate, from which source, and when.
* **UJ-52-EXC-04** the category enum described what a cost was *for*, never
  whether it had happened. ``cost_nature`` separates a provider's estimate
  from an actual expense.
* **UJ-52-EXC-05** rates were visible to every reader of the docket.
  ``rate_confidential`` marks the row so the read path can withhold the amount
  from a caller without ``ip:fees_manage``.

The CHECK constraints are the point of this revision, not decoration. Each one
is an invariant the service also enforces, placed where a future route, an
import, a backfill, or a psql session must also pass:

* a cost with no Matter cannot be billable, and cannot carry a billing link -
  there is no ledger for it to link to;
* a nonbillable cost carries no billing link, so it can never be reconciled
  into client billing by accident;
* an *estimate* carries no billing link, because a provider's quote is not an
  expense and must never reconcile as one;
* the five FX columns are all-or-nothing - a rate with no source, or a
  converted amount with no rate, is not a preserved conversion;
* a conversion into the currency it started in is not a conversion.

``ck_ip_cost_item_billing_link_pair`` is added alongside these because the
"together or not at all" rule for ``billing_link_type``/``billing_link_id``
previously lived only in the Pydantic request model. The four constraints
above test ``billing_link_type``; without the pair rule a row carrying only
``billing_link_id`` would slip past all four.

Existing rows satisfy every constraint: all have a Matter, and the three new
flags take their defaults (``billable`` true, ``cost_nature`` 'actual',
``rate_confidential`` false). No backfill is required and none is performed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260821_0004"
down_revision = "20260821_0003"
branch_labels = None
depends_on = None

TABLE = "ip_cost_items"

_FX_COLUMNS = (
    "fx_rate",
    "fx_rate_source",
    "fx_converted_at",
    "base_amount_minor",
    "base_currency",
)

_ALL_FX_NULL = " AND ".join(f"{column} IS NULL" for column in _FX_COLUMNS)
_ALL_FX_PRESENT = " AND ".join(f"{column} IS NOT NULL" for column in _FX_COLUMNS)

# ``billable`` and ``rate_confidential`` are compared against 0/1 rather than
# against a boolean literal so one expression is valid on both SQLite, which
# has no boolean type, and PostgreSQL, which accepts the integer comparison.
_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "ck_ip_cost_item_cost_nature",
        "cost_nature IN ('actual', 'estimate')",
    ),
    (
        "ck_ip_cost_item_billing_link_pair",
        "(billing_link_type IS NULL) = (billing_link_id IS NULL)",
    ),
    # UJ-52-EXC-01. Without a Matter there is no accounting owner, so the cost
    # may exist only as nonbillable evidence and may not point at a ledger row.
    (
        "ck_ip_cost_item_matterless_is_nonbillable",
        "matter_id IS NOT NULL OR (billable = false AND billing_link_type IS NULL)",
    ),
    (
        "ck_ip_cost_item_nonbillable_has_no_billing_link",
        "billable = true OR billing_link_type IS NULL",
    ),
    # UJ-52-EXC-04. An estimate is not an expense; it has nothing to reconcile.
    (
        "ck_ip_cost_item_estimate_has_no_billing_link",
        "cost_nature = 'actual' OR billing_link_type IS NULL",
    ),
    # UJ-52-EXC-02. Preserve original amount/rate/source/time, or none of it.
    (
        "ck_ip_cost_item_fx_complete",
        f"({_ALL_FX_NULL}) OR ({_ALL_FX_PRESENT})",
    ),
    (
        "ck_ip_cost_item_fx_rate_positive",
        "fx_rate IS NULL OR fx_rate > 0",
    ),
    (
        "ck_ip_cost_item_base_amount_nonnegative",
        "base_amount_minor IS NULL OR base_amount_minor >= 0",
    ),
    (
        "ck_ip_cost_item_base_currency",
        "base_currency IS NULL OR length(base_currency) = 3",
    ),
    # Converting INR into INR records no conversion fact worth preserving.
    (
        "ck_ip_cost_item_fx_distinct_currency",
        "base_currency IS NULL OR base_currency <> currency",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # Batch mode on both dialects: SQLite cannot drop the NOT NULL on
    # ``matter_id`` or add a CHECK in place, and PostgreSQL follows the same
    # deterministic shape so the two databases cannot diverge.
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            "matter_id",
            existing_type=sa.String(36),
            nullable=True,
        )
        batch.add_column(
            sa.Column(
                "billable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "cost_nature",
                sa.String(16),
                nullable=False,
                server_default="actual",
            )
        )
        batch.add_column(
            sa.Column(
                "rate_confidential",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("fx_rate", sa.Numeric(20, 10), nullable=True))
        batch.add_column(sa.Column("fx_rate_source", sa.String(120), nullable=True))
        batch.add_column(
            sa.Column("fx_converted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("base_amount_minor", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("base_currency", sa.String(3), nullable=True))
        for name, expression in _CHECKS:
            batch.create_check_constraint(name, expression)


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        for name, _expression in reversed(_CHECKS):
            batch.drop_constraint(name, type_="check")
        for column in _FX_COLUMNS:
            batch.drop_column(column)
        batch.drop_column("rate_confidential")
        batch.drop_column("cost_nature")
        batch.drop_column("billable")
        # Restoring NOT NULL is only safe because a matterless cost can only
        # have been created after this revision; a downgrade past it must
        # therefore be preceded by removing those rows.
        batch.alter_column(
            "matter_id",
            existing_type=sa.String(36),
            nullable=False,
        )
