"""Give an approval somewhere to point and a refusal something to say.

DATA-GOVERNANCE-MAP: updated

20260819_0001 made 'requested' and 'rejected' reachable. Building the workflow on
top of that surfaced two things the table could not yet express.

**What an execute row approves.** Nothing linked an execute row to the dry run
whose manifest was reviewed. Two consequences, both bad: the same manifest could
be approved twice, producing two execute rows from one review, and no execute row
could be traced back to what its approver actually saw. `approves_operation_id`
is therefore required on execute and unique - one manifest, at most one approved
execution - and forbidden on a dry run, which approves nothing. Requiring it also
closes a wider hole: an execute row with no originating dry run bypassed manifest
review entirely, and the schema had no objection.

**Why a request was refused.** The obvious shortcut was to reuse `blocked_reason`
and it is wrong: "a legal hold stopped this" and "a person refused this" are
different states with different remedies, and one column means the later one
silently overwrites the earlier. An operator asking six months from now why a
tenant purge never ran needs both answers, not the most recent one.

That constraint is a biconditional rather than a one-sided NOT NULL: a rejection
cannot be recorded without a reason, AND a reason cannot linger on a row that is
not rejected. The second half holds because rejection is terminal - a refused
manifest is not re-requestable, the operator produces a fresh dry run - so a row
carrying a reason in any other state is a bug that already happened.

MIGRATION-LOCK-RISK: acknowledged - tenant_data_operations holds governance
dry-run manifests only, single-digit rows in every environment. Both added
columns are nullable with no default, so the ADD COLUMNs are metadata-only, and
the CHECK/UNIQUE/FK validation scans are bounded by that same row count.

MIGRATION-ROLLBACK: restore-forward - downgrade drops both columns and would
therefore discard recorded refusal reasons and the link between an approval and
the manifest it authorised. It refuses to run while any row carries either,
rather than destroying evidence that was deliberately recorded.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260820_0001"
down_revision = "20260819_0001"
branch_labels = None
depends_on = None

_REASON_MATCHES_STATE = (
    "(approval_status = 'rejected' AND rejection_reason IS NOT NULL) "
    "OR (approval_status <> 'rejected' AND rejection_reason IS NULL)"
)
_EXECUTE_CITES_MANIFEST = "execution_mode <> 'execute' OR approves_operation_id IS NOT NULL"
_DRY_RUN_APPROVES_NOTHING = "execution_mode <> 'dry_run' OR approves_operation_id IS NULL"


def upgrade() -> None:
    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.add_column(sa.Column("rejection_reason", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("approves_operation_id", sa.String(length=36), nullable=True))
        batch.create_check_constraint(
            "ck_tenant_data_operation_rejection_reason", _REASON_MATCHES_STATE
        )
        batch.create_check_constraint(
            "ck_tenant_data_operation_execute_cites_manifest", _EXECUTE_CITES_MANIFEST
        )
        batch.create_check_constraint(
            "ck_tenant_data_operation_dry_run_approves_nothing", _DRY_RUN_APPROVES_NOTHING
        )
        batch.create_foreign_key(
            "fk_tenant_data_operation_approves_operation_company",
            "tenant_data_operations",
            ["approves_operation_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        # NULLs do not collide, so every dry run is unaffected; two execute rows
        # citing one manifest do collide, which is the point.
        batch.create_unique_constraint(
            "uq_tenant_data_operation_approves_operation",
            ["approves_operation_id", "company_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    recorded = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM tenant_data_operations "
            "WHERE rejection_reason IS NOT NULL OR approves_operation_id IS NOT NULL"
        )
    ).scalar_one()
    if recorded:
        raise RuntimeError(
            f"refusing to downgrade: {recorded} operation(s) carry a recorded refusal "
            "reason or an approval's link to the manifest it authorised, both of which "
            "dropping these columns would destroy. Export them first, or roll forward."
        )

    with op.batch_alter_table("tenant_data_operations") as batch:
        batch.drop_constraint("uq_tenant_data_operation_approves_operation", type_="unique")
        batch.drop_constraint(
            "fk_tenant_data_operation_approves_operation_company", type_="foreignkey"
        )
        batch.drop_constraint(
            "ck_tenant_data_operation_dry_run_approves_nothing", type_="check"
        )
        batch.drop_constraint("ck_tenant_data_operation_execute_cites_manifest", type_="check")
        batch.drop_constraint("ck_tenant_data_operation_rejection_reason", type_="check")
        batch.drop_column("approves_operation_id")
        batch.drop_column("rejection_reason")
