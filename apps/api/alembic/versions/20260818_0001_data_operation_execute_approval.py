"""Replace the dry-run-only fence with a four-eyes execute fence.

DATA-GOVERNANCE-MAP: updated

``tenant_data_operations`` governs tenant export, retention purge, offboarding
and restore validation - the operations that can destroy or export a client's
entire record set. Three CHECK constraints currently pin it to dry run:

    ck_tenant_data_operation_dry_run_only        execution_mode = 'dry_run'
    ck_tenant_data_operation_execute_approval_closed   approval_status = 'not_requested'
    ck_tenant_data_operation_item_never_execute  safe_to_execute = false

DATA-GOV-06 and DATA-GOV-08 require a dry-run THEN execute operation, so those
constraints eventually have to move. The dangerous way to do that is to drop
them: the table has no approver columns at all, so relaxing the fence would
remove the last-resort guarantee and put nothing in its place. Every control
would then live in application code, on the one table where a bug deletes a
firm's matters.

So this replaces rather than relaxes. Execute becomes expressible only when it
is approved by a SECOND person, enforced in the database, mirroring
``ck_legal_hold_activation_approval`` and ``ck_legal_hold_approver_distinct``
which already govern legal holds this way.

After this migration a dry-run row is exactly as constrained as before, and an
execute row is impossible without a distinct company-scoped approver. No service
writes execute rows yet; this is the schema prerequisite, deliberately landed on
its own so the export and purge slices do not each carry it.

MIGRATION-LOCK-RISK: acknowledged - tenant_data_operations holds only governance
dry-run manifests (single-digit rows in every environment), so the ALTER and the
constraint validation scan are bounded.

MIGRATION-ROLLBACK: restore-forward - downgrade restores the original
dry-run-only fence and drops the approver columns. That is data-destroying for
any approved execute row, which is why downgrade also refuses to run if one
exists rather than silently discarding the approval evidence.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260818_0001"
down_revision = "20260815_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.add_column(sa.Column("approved_by_membership_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("approved_by_membership_company_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(sa.Column("approver_label_snapshot", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))

        batch.drop_constraint("ck_tenant_data_operation_dry_run_only", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_execute_approval_closed", type_="check")

        batch.create_check_constraint(
            "ck_tenant_data_operation_execution_mode",
            "execution_mode IN ('dry_run', 'execute')",
        )
        batch.create_check_constraint(
            "ck_tenant_data_operation_approval_status",
            "approval_status IN ('not_requested', 'requested', 'approved', 'rejected')",
        )
        # A dry run may never carry an approval, so an approved row cannot be
        # downgraded to "just a simulation" while keeping its signature.
        batch.create_check_constraint(
            "ck_tenant_data_operation_dry_run_unapproved",
            "execution_mode <> 'dry_run' OR approval_status = 'not_requested'",
        )
        # The fence that replaces dry-run-only: execute requires a completed,
        # company-scoped approval and a recorded approver.
        batch.create_check_constraint(
            "ck_tenant_data_operation_execute_requires_approval",
            "execution_mode <> 'execute' OR ("
            "approval_status = 'approved' "
            "AND approved_at IS NOT NULL "
            "AND approved_by_membership_id IS NOT NULL "
            "AND approved_by_membership_company_id = company_id "
            "AND requested_by_membership_id IS NOT NULL "
            "AND requested_by_membership_company_id = company_id)",
        )
        # Four eyes. The requester cannot approve their own destructive
        # operation, which is the same rule legal holds already enforce.
        batch.create_check_constraint(
            "ck_tenant_data_operation_approver_distinct",
            "requested_by_membership_id IS NULL "
            "OR approved_by_membership_id IS NULL "
            "OR requested_by_membership_id <> approved_by_membership_id",
        )
        batch.create_check_constraint(
            "ck_tenant_data_operation_approver_company_complete",
            "(approved_by_membership_id IS NULL AND approved_by_membership_company_id IS NULL) "
            "OR (approved_by_membership_id IS NOT NULL "
            "AND approved_by_membership_company_id = company_id)",
        )


def downgrade() -> None:
    # Refuse rather than discard. An approved execute row carries who authorised
    # a destructive operation; dropping the columns would erase that evidence
    # while leaving the operation recorded as having happened.
    bind = op.get_bind()
    approved = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM tenant_data_operations "
            "WHERE execution_mode = 'execute' OR approval_status <> 'not_requested'"
        )
    ).scalar_one()
    if approved:
        raise RuntimeError(
            f"refusing to downgrade: {approved} tenant_data_operations row(s) carry "
            "execute mode or approval evidence that this downgrade would destroy. "
            "Roll forward, or resolve those rows deliberately first."
        )

    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.drop_constraint("ck_tenant_data_operation_approver_company_complete", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_approver_distinct", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_execute_requires_approval", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_dry_run_unapproved", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_approval_status", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_execution_mode", type_="check")

        batch.create_check_constraint(
            "ck_tenant_data_operation_dry_run_only", "execution_mode = 'dry_run'"
        )
        batch.create_check_constraint(
            "ck_tenant_data_operation_execute_approval_closed",
            "approval_status = 'not_requested'",
        )

        batch.drop_column("approved_at")
        batch.drop_column("approver_label_snapshot")
        batch.drop_column("approved_by_membership_company_id")
        batch.drop_column("approved_by_membership_id")
