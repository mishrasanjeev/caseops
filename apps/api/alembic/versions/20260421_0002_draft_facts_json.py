"""Sprint R-UI — stepper → draft facts passthrough.

Adds two nullable columns to ``drafts``:

- ``facts_json``: the stepper-collected per-template fact dict, stored
  as JSON text so the generator has the structured facts to ground the
  body on (instead of re-asking the lawyer inside a focus note).
- ``template_type``: the R-UI template key (bail_application,
  civil_suit, …) so ``generate_draft_version`` can pick the right
  mandatory directives in ``drafting_prompts.py``.

Both are nullable — pre-existing drafts created before the stepper
keep working unchanged.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260421_0002"
down_revision = "20260421_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column("facts_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "drafts",
        sa.Column("template_type", sa.String(length=60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drafts", "template_type")
    op.drop_column("drafts", "facts_json")
