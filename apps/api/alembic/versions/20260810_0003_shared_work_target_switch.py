"""Switch shared-work integrity to one canonical Matter-or-IP target.

Revision ID: 20260810_0003
Revises: 20260810_0002

Tenant keys remain nullable for one mixed-revision window: the previous
application can still write a Matter row while traffic drains.  The new
writer always supplies ``company_id`` and reconciliation reports any legacy
tail before the later contract phase makes it mandatory.
"""

from __future__ import annotations

from alembic import op

revision = "20260810_0003"
down_revision = "20260810_0002"
branch_labels = None
depends_on = None

_TARGET_TABLES = (
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_history",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
)


def _names(table_name: str) -> tuple[str, str, str]:
    prefixes = {
        "matter_tasks": "matter_task",
        "matter_hearings": "matter_hearing",
        "hearing_reminders": "hearing_reminder",
        "matter_next_hearing_history": "next_hearing_history",
        "matter_next_hearing_suggestions": "next_hearing_suggestion",
        "matter_deadlines": "matter_deadline",
    }
    prefix = prefixes[table_name]
    return (
        f"fk_{prefix}_matter_company",
        f"fk_{prefix}_ip_docket_company",
        f"ck_{prefix}_exactly_one_target",
    )


def upgrade() -> None:
    for table_name in _TARGET_TABLES:
        matter_fk, docket_fk, target_check = _names(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_foreign_key(
                f"fk_{table_name}_ip_docket",
                "ip_docket_records",
                ["ip_docket_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_foreign_key(
                matter_fk,
                "matters",
                ["matter_id", "company_id"],
                ["id", "company_id"],
                ondelete="CASCADE",
            )
            batch_op.create_foreign_key(
                docket_fk,
                "ip_docket_records",
                ["ip_docket_id", "company_id"],
                ["id", "company_id"],
                ondelete="CASCADE",
            )
            batch_op.create_check_constraint(
                target_check,
                "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
                "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            )

    for table_name, constraint_name in (
        ("matter_tasks", "uq_matter_task_id_company"),
        ("matter_hearings", "uq_matter_hearing_id_company"),
        ("matter_deadlines", "uq_matter_deadline_id_company"),
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_unique_constraint(constraint_name, ["id", "company_id"])

    with op.batch_alter_table("matter_next_hearing_suggestions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ip_next_hearing_suggestion_source",
            [
                "ip_docket_id",
                "suggested_date",
                "source",
                "source_ref_type",
                "source_ref_id",
            ],
        )

    with op.batch_alter_table("matter_hearings") as batch_op:
        batch_op.create_foreign_key(
            "fk_matter_hearing_responsible_membership",
            "company_memberships",
            ["responsible_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.create_foreign_key(
            "fk_notification_delivery_ip_docket",
            "ip_docket_records",
            ["ip_docket_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_notification_delivery_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_notification_delivery_at_most_one_work_target",
            "matter_id IS NULL OR ip_docket_id IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.drop_constraint(
            "ck_notification_delivery_at_most_one_work_target", type_="check"
        )
        batch_op.drop_constraint(
            "fk_notification_delivery_ip_docket_company", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_notification_delivery_ip_docket", type_="foreignkey")

    with op.batch_alter_table("matter_hearings") as batch_op:
        batch_op.drop_constraint(
            "fk_matter_hearing_responsible_membership", type_="foreignkey"
        )

    with op.batch_alter_table("matter_next_hearing_suggestions") as batch_op:
        batch_op.drop_constraint("uq_ip_next_hearing_suggestion_source", type_="unique")

    for table_name, constraint_name in reversed(
        (
            ("matter_tasks", "uq_matter_task_id_company"),
            ("matter_hearings", "uq_matter_hearing_id_company"),
            ("matter_deadlines", "uq_matter_deadline_id_company"),
        )
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="unique")

    for table_name in reversed(_TARGET_TABLES):
        matter_fk, docket_fk, target_check = _names(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(target_check, type_="check")
            batch_op.drop_constraint(docket_fk, type_="foreignkey")
            batch_op.drop_constraint(matter_fk, type_="foreignkey")
            batch_op.drop_constraint(f"fk_{table_name}_ip_docket", type_="foreignkey")
