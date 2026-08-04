"""Allow tenant-owned Matter attachments in the source defect queue.

Revision ID: 20260804_0001
Revises: 20260803_0001
"""

from __future__ import annotations

from alembic import op

revision = "20260804_0001"
down_revision = "20260803_0001"
branch_labels = None
depends_on = None

_OLD_TARGETS = (
    "target_type in ('authority_document', 'statute_section', 'judge_appointment')"
)
_NEW_TARGETS = (
    "target_type in ('authority_document', 'statute_section', "
    "'judge_appointment', 'matter_attachment')"
)


def upgrade() -> None:
    with op.batch_alter_table("source_link_reports") as batch_op:
        batch_op.drop_constraint(
            "ck_source_link_reports_target_type", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_source_link_reports_target_type", _NEW_TARGETS
        )


def downgrade() -> None:
    with op.batch_alter_table("source_link_reports") as batch_op:
        batch_op.drop_constraint(
            "ck_source_link_reports_target_type", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_source_link_reports_target_type", _OLD_TARGETS
        )
