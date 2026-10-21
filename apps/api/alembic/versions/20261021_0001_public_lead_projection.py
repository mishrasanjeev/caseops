"""Index existing public admissions without scheduling historical notifications.

Revision ID: 20261021_0001
Revises: 20261020_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; additive classification and index on the
existing enrollment table under the canonical migration lock/statement budgets.
MIGRATION-ROLLBACK: roll-forward or restore only. Downgrade refuses before
changing classification, indexes, enrollment/outbox or commercial/audit records.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261021_0001"
down_revision = "20261020_0001"
branch_labels = None
depends_on = None
INDEX = "ix_billing_enrollments_public_lead_created_id"


def upgrade():
    op.add_column(
        "billing_enrollments",
        sa.Column(
            "is_public_lead",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    enrollments = sa.table(
        "billing_enrollments",
        sa.column("is_public_lead", sa.Boolean()),
        sa.column("status", sa.String()),
        sa.column("status_timestamps_json", sa.JSON()),
    )
    op.get_bind().execute(
        enrollments.update()
        .where(
            sa.or_(
                enrollments.c.status == "demo_requested",
                enrollments.c.status_timestamps_json["demo_admission"]["contract_version"]
                .as_string()
                .in_(
                    ["seo_demo_20261009", "legacy_public_demo_v1"],
                ),
                # The pre-outbox public admission constructor persisted this UTC
                # timestamp. It survives conversion; a source-name guess does not.
                enrollments.c.status_timestamps_json["demo_requested_at"]
                .as_string()
                .like("____-__-__T__:__:__%+00:00"),
            )
        )
        .values(is_public_lead=True)
    )
    op.create_index(INDEX, "billing_enrollments", ["is_public_lead", "created_at", "id"])


def downgrade():
    raise RuntimeError(
        "Public lead classification is retained release data; "
        "downgrade requires roll-forward or restore."
    )
