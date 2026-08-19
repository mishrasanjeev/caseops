"""Make the approval request and rejection states reachable.

DATA-GOVERNANCE-MAP: updated

20260818_0001 added an approval_status enum of four values and two constraints:

    dry_run  =>  approval_status = 'not_requested'
    execute  =>  approval_status = 'approved'

Together those make 'requested' and 'rejected' unreachable by any row. A dry run
cannot hold them, and an execute row must already be approved. Verified by
insert, not by reading: both raise ck_tenant_data_operation_dry_run_unapproved.

So there is currently no way to record that an operator submitted a manifest for
approval, or that an approver refused it. The approval workflow has nowhere to
live, and a rejection would have to be represented by deleting the dry run -
destroying the evidence that someone asked and was told no.

The intended safety property was narrower than what was written: a dry run must
never be APPROVED, so an approved execute cannot be relabelled a simulation
while keeping its signature. That property is preserved exactly. What changes is
that a dry run may now also be 'requested' or 'rejected', which is where a
request naturally belongs - it is the manifest being submitted, not a second
kind of record.

Approval itself still creates a separate execute row carrying the approver, so
the four-eyes fence in ck_tenant_data_operation_execute_requires_approval is
untouched.

MIGRATION-LOCK-RISK: acknowledged - tenant_data_operations holds governance
dry-run manifests only, single-digit rows in every environment, so the
constraint swap and its validation scan are bounded.

MIGRATION-ROLLBACK: restore-forward - downgrade restores the stricter predicate
and therefore refuses to run while any row holds 'requested' or 'rejected',
rather than silently discarding a pending or refused approval request.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260819_0001"
down_revision = "20260818_0001"
branch_labels = None
depends_on = None

_RELAXED = (
    "execution_mode <> 'dry_run' "
    "OR approval_status IN ('not_requested', 'requested', 'rejected')"
)
_STRICT = "execution_mode <> 'dry_run' OR approval_status = 'not_requested'"


def upgrade() -> None:
    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.drop_constraint("ck_tenant_data_operation_dry_run_unapproved", type_="check")
        batch.create_check_constraint("ck_tenant_data_operation_dry_run_unapproved", _RELAXED)


def downgrade() -> None:
    bind = op.get_bind()
    pending = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM tenant_data_operations "
            "WHERE execution_mode = 'dry_run' "
            "AND approval_status IN ('requested', 'rejected')"
        )
    ).scalar_one()
    if pending:
        raise RuntimeError(
            f"refusing to downgrade: {pending} dry-run row(s) hold a pending or "
            "refused approval request that the stricter predicate cannot represent. "
            "Resolve them deliberately, or roll forward."
        )

    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.drop_constraint("ck_tenant_data_operation_dry_run_unapproved", type_="check")
        batch.create_check_constraint("ck_tenant_data_operation_dry_run_unapproved", _STRICT)
