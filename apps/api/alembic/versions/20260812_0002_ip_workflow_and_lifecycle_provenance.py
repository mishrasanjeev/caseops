"""Add inert IP workflow versions and shared-child lifecycle provenance.

Revision ID: 20260812_0002
Revises: 20260812_0001

The workflow tables are deliberately company-scoped and unseeded. Existing
IP dockets remain unpinned, so this expand migration cannot silently activate
or infer a legal workflow. Shared-work provenance is nullable for mixed
revisions and is populated only by a committed IP lifecycle event.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260812_0002"
down_revision = "20260812_0001"
branch_labels = None
depends_on = None


_PROVENANCE_TABLES = (
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
    "notification_delivery_intents",
    "calendar_event_syncs",
)

# The FK-index validator works at individual-column granularity.  These
# component columns are covered by the composite indexes created below, whose
# leading columns are the lifecycle event or actor membership identifiers.
FK_INDEXES: tuple[tuple[str, str], ...] = (
    ("matter_tasks", "neutralized_by_ip_lifecycle_version"),
    ("matter_hearings", "neutralized_by_ip_lifecycle_version"),
    ("hearing_reminders", "neutralized_by_ip_lifecycle_version"),
    ("matter_next_hearing_suggestions", "neutralized_by_ip_lifecycle_version"),
    ("matter_deadlines", "neutralized_by_ip_lifecycle_version"),
    ("notification_delivery_intents", "neutralized_by_ip_lifecycle_version"),
    ("calendar_event_syncs", "neutralized_ip_docket_id"),
    ("calendar_event_syncs", "neutralized_by_ip_lifecycle_version"),
    ("ip_workflow_versions", "proposed_by_membership_company_id"),
    ("ip_workflow_versions", "reviewed_by_membership_company_id"),
    ("ip_workflow_versions", "legal_approved_by_membership_company_id"),
)

_DOWNGRADE_LOCK_TABLES = (
    "ip_workflow_definitions",
    "ip_workflow_versions",
    "ip_docket_records",
    "ip_docket_events",
    *_PROVENANCE_TABLES,
)


def _assert_downgrade_is_evidence_free(bind: sa.Connection) -> None:
    """Refuse a schema rollback that would erase workflow or lifecycle facts."""

    if bind.dialect.name == "postgresql":
        # Bound deploy-time lock acquisition instead of waiting indefinitely
        # behind a mixed-revision writer. A timeout fails the migration safely.
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        for table_name in _DOWNGRADE_LOCK_TABLES:
            bind.execute(
                sa.text(f'LOCK TABLE "{table_name}" IN ACCESS EXCLUSIVE MODE')
            )

    populated: dict[str, int] = {}
    for table_name in ("ip_workflow_definitions", "ip_workflow_versions"):
        count = int(
            bind.scalar(sa.text(f'SELECT count(*) FROM "{table_name}"')) or 0
        )
        if count:
            populated[table_name] = count

    pinned_dockets = int(
        bind.scalar(
            sa.text(
                "SELECT count(*) FROM ip_docket_records "
                "WHERE workflow_definition_id IS NOT NULL "
                "OR workflow_version_id IS NOT NULL "
                "OR workflow_version_number IS NOT NULL"
            )
        )
        or 0
    )
    if pinned_dockets:
        populated["ip_docket_records.workflow_pin"] = pinned_dockets

    versioned_events = int(
        bind.scalar(
            sa.text(
                "SELECT count(*) FROM ip_docket_events "
                "WHERE resulting_lifecycle_version IS NOT NULL"
            )
        )
        or 0
    )
    if versioned_events:
        populated["ip_docket_events.resulting_lifecycle_version"] = versioned_events

    for table_name in _PROVENANCE_TABLES:
        count = int(
            bind.scalar(
                sa.text(
                    f'SELECT count(*) FROM "{table_name}" '
                    "WHERE neutralized_by_ip_lifecycle_event_id IS NOT NULL "
                    "OR neutralized_by_ip_lifecycle_version IS NOT NULL "
                    "OR neutralized_at IS NOT NULL"
                )
            )
            or 0
        )
        if count:
            populated[f"{table_name}.lifecycle_provenance"] = count

    if populated:
        raise RuntimeError(
            "IP workflow/lifecycle evidence exists; retain the additive schema "
            "and roll application code forward instead of deleting facts: "
            f"{populated}"
        )


def _provenance_prefix(table_name: str) -> str:
    return {
        "matter_tasks": "matter_task",
        "matter_hearings": "matter_hearing",
        "hearing_reminders": "hearing_reminder",
        "matter_next_hearing_suggestions": "next_hearing_suggestion",
        "matter_deadlines": "matter_deadline",
        "notification_delivery_intents": "notification_delivery",
        "calendar_event_syncs": "calendar_event_sync",
    }[table_name]


def _provenance_index_name(table_name: str) -> str:
    return {
        "matter_tasks": "ix_matter_tasks_ip_lifecycle_event",
        "matter_hearings": "ix_matter_hearings_ip_lifecycle_event",
        "hearing_reminders": "ix_hearing_reminders_ip_lifecycle_event",
        "matter_next_hearing_suggestions": "ix_next_hearing_suggestions_ip_lifecycle_event",
        "matter_deadlines": "ix_matter_deadlines_ip_lifecycle_event",
        "notification_delivery_intents": "ix_notification_intents_ip_lifecycle_event",
        "calendar_event_syncs": "ix_calendar_event_syncs_ip_lifecycle_event",
    }[table_name]


def _neutral_status_expression(table_name: str) -> str:
    return {
        "matter_tasks": "status = 'cancelled'",
        "matter_hearings": "status = 'cancelled'",
        "hearing_reminders": "status = 'cancelled'",
        "matter_next_hearing_suggestions": "status = 'rejected'",
        "matter_deadlines": "status = 'cancelled'",
        "notification_delivery_intents": "status IN ('blocked', 'cancelled')",
        "calendar_event_syncs": "sync_status IN ('delete_pending', 'deleted')",
    }[table_name]


def _provenance_target_expression(table_name: str, target_column: str) -> str:
    if table_name == "calendar_event_syncs":
        # This column exists only to identify the docket neutralized by the
        # lifecycle event, so it must be absent until provenance is stamped.
        return (
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            f"{target_column} IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            f"{target_column} IS NOT NULL)"
        )
    # The other tables already use ip_docket_id as their live aggregate
    # target. Existing and newly-created operational rows may therefore carry
    # an IP docket while lifecycle provenance is still null.
    return (
        "neutralized_by_ip_lifecycle_event_id IS NULL OR "
        f"{target_column} IS NOT NULL"
    )


def _add_lifecycle_provenance(table_name: str) -> None:
    prefix = _provenance_prefix(table_name)
    target_column = (
        "neutralized_ip_docket_id"
        if table_name == "calendar_event_syncs"
        else "ip_docket_id"
    )
    op.add_column(
        table_name,
        sa.Column("neutralized_by_ip_lifecycle_event_id", sa.String(36), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("neutralized_by_ip_lifecycle_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("neutralized_at", sa.DateTime(timezone=True), nullable=True),
    )
    if table_name == "calendar_event_syncs":
        op.add_column(
            table_name,
            sa.Column("neutralized_ip_docket_id", sa.String(36), nullable=True),
        )
    op.create_index(
        _provenance_index_name(table_name),
        table_name,
        [
            "neutralized_by_ip_lifecycle_event_id",
            "company_id",
            target_column,
            "neutralized_by_ip_lifecycle_version",
        ],
    )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.create_foreign_key(
            f"fk_{prefix}_neutralized_event_company",
            "ip_docket_events",
            [
                "neutralized_by_ip_lifecycle_event_id",
                "company_id",
                target_column,
                "neutralized_by_ip_lifecycle_version",
            ],
            ["id", "company_id", "docket_id", "resulting_lifecycle_version"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            f"ck_{prefix}_ip_lifecycle_provenance_complete",
            "(neutralized_by_ip_lifecycle_event_id IS NULL AND "
            "neutralized_by_ip_lifecycle_version IS NULL AND neutralized_at IS NULL) OR "
            "(neutralized_by_ip_lifecycle_event_id IS NOT NULL AND "
            "neutralized_by_ip_lifecycle_version IS NOT NULL AND neutralized_at IS NOT NULL "
            "AND company_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            f"ck_{prefix}_ip_lifecycle_version_positive",
            "neutralized_by_ip_lifecycle_version IS NULL OR "
            "neutralized_by_ip_lifecycle_version > 0",
        )
        batch_op.create_check_constraint(
            f"ck_{prefix}_ip_lifecycle_provenance_target",
            _provenance_target_expression(table_name, target_column),
        )
        batch_op.create_check_constraint(
            f"ck_{prefix}_ip_lifecycle_terminal_state",
            "neutralized_by_ip_lifecycle_event_id IS NULL OR "
            f"{_neutral_status_expression(table_name)}",
        )


def _create_workflow_version_immutability_guard(bind: sa.Connection) -> None:
    actor_reference_pairs = (
        ("proposed_by_membership_id", "proposed_by_membership_company_id"),
        ("reviewed_by_membership_id", "reviewed_by_membership_company_id"),
        (
            "legal_approved_by_membership_id",
            "legal_approved_by_membership_company_id",
        ),
    )
    immutable_columns = (
        "company_id",
        "definition_id",
        "version",
        "schema_version",
        "transition_table_json",
        "fixture_set_json",
        "source_reference",
        "source_hash",
        "content_hash",
        "engine_compatibility",
        "effective_from",
        "effective_until",
        "proposer_membership_id_snapshot",
        "proposer_user_id_snapshot",
        "proposer_label_snapshot",
        "proposer_authority_snapshot_json",
    )
    approval_evidence_columns = (
        "reviewer_membership_id_snapshot",
        "reviewer_user_id_snapshot",
        "reviewer_label_snapshot",
        "reviewer_authority_snapshot_json",
        "legal_approver_membership_id_snapshot",
        "legal_approver_user_id_snapshot",
        "legal_approver_label_snapshot",
        "legal_approver_authority_snapshot_json",
        "fixtures_passed_at",
        "approved_at",
    )
    definition_identity_columns = (
        "id",
        "company_id",
        "key",
        "aggregate_type",
        "initial_state",
        "created_at",
    )
    if bind.dialect.name == "postgresql":
        changed = " OR ".join(
            f"NEW.{column_name} IS DISTINCT FROM OLD.{column_name}"
            for column_name in immutable_columns
        )
        approval_evidence_changed = " OR ".join(
            f"NEW.{column_name} IS DISTINCT FROM OLD.{column_name}"
            for column_name in approval_evidence_columns
        )
        actor_reference_repointed = " OR ".join(
            f"((NEW.{actor_id} IS DISTINCT FROM OLD.{actor_id} OR "
            f"NEW.{actor_company} IS DISTINCT FROM OLD.{actor_company}) AND NOT "
            f"(OLD.{actor_id} IS NOT NULL AND OLD.{actor_company} IS NOT NULL "
            f"AND NEW.{actor_id} IS NULL AND NEW.{actor_company} IS NULL))"
            for actor_id, actor_company in actor_reference_pairs
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION caseops_reject_ip_workflow_version_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION
                            'IP workflow versions are retained; retire instead of delete';
                    END IF;
                    IF (OLD.status <> 'candidate' OR NEW.status <> 'candidate')
                       AND ({changed}) THEN
                        RAISE EXCEPTION
                            'Published IP workflow contract content is immutable';
                    END IF;
                    IF OLD.status <> 'candidate'
                       AND ({approval_evidence_changed}) THEN
                        RAISE EXCEPTION
                            'Published IP workflow approval evidence is immutable';
                    END IF;
                    IF NOT (
                        (OLD.status = 'candidate' AND
                         NEW.status IN ('candidate', 'approved', 'disabled')) OR
                        (OLD.status = 'approved' AND
                         NEW.status IN ('approved', 'active', 'retired', 'disabled')) OR
                        (OLD.status = 'active' AND
                         NEW.status IN ('active', 'retired', 'disabled')) OR
                        (OLD.status = 'retired' AND NEW.status = 'retired') OR
                        (OLD.status = 'disabled' AND NEW.status = 'disabled')
                    ) THEN
                        RAISE EXCEPTION
                            'IP workflow version state cannot move backwards or reopen';
                    END IF;
                    IF OLD.status <> 'candidate'
                       AND ({actor_reference_repointed}) THEN
                        RAISE EXCEPTION
                            'Published IP workflow actor references may only be cleared';
                    END IF;
                    IF NEW.activated_at IS DISTINCT FROM OLD.activated_at
                       AND NOT (
                           OLD.status = 'approved' AND NEW.status = 'active' AND
                           OLD.activated_at IS NULL AND NEW.activated_at IS NOT NULL
                       ) THEN
                        RAISE EXCEPTION
                            'IP workflow activation evidence is immutable';
                    END IF;
                    IF NEW.retired_at IS DISTINCT FROM OLD.retired_at
                       AND NOT (
                           OLD.status NOT IN ('retired', 'disabled') AND
                           NEW.status IN ('retired', 'disabled') AND
                           OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
                       ) THEN
                        RAISE EXCEPTION
                            'IP workflow retirement evidence is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_workflow_versions_immutable
                BEFORE UPDATE OR DELETE ON ip_workflow_versions
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_ip_workflow_version_mutation()
                """
            )
        )
        definition_identity_changed = " OR ".join(
            f"NEW.{column_name} IS DISTINCT FROM OLD.{column_name}"
            for column_name in definition_identity_columns
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION caseops_reject_ip_workflow_definition_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION
                            'IP workflow definitions are retained; retire instead of delete';
                    END IF;
                    IF {definition_identity_changed} THEN
                        RAISE EXCEPTION
                            'IP workflow definition identity is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_workflow_definitions_immutable
                BEFORE UPDATE OR DELETE ON ip_workflow_definitions
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_ip_workflow_definition_mutation()
                """
            )
        )
        return

    if bind.dialect.name == "sqlite":
        changed = " OR ".join(
            f"OLD.{column_name} IS NOT NEW.{column_name}"
            for column_name in immutable_columns
        )
        columns = ", ".join(immutable_columns)
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_ip_workflow_versions_immutable_update
                BEFORE UPDATE OF {columns} ON ip_workflow_versions
                FOR EACH ROW
                WHEN (OLD.status <> 'candidate' OR NEW.status <> 'candidate')
                     AND ({changed})
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Published IP workflow contract content is immutable'
                    );
                END;
                """
            )
        )
        approval_evidence_changed = " OR ".join(
            f"OLD.{column_name} IS NOT NEW.{column_name}"
            for column_name in approval_evidence_columns
        )
        approval_columns = ", ".join(approval_evidence_columns)
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_ip_workflow_versions_approval_immutable_update
                BEFORE UPDATE OF {approval_columns} ON ip_workflow_versions
                FOR EACH ROW
                WHEN OLD.status <> 'candidate' AND ({approval_evidence_changed})
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Published IP workflow approval evidence is immutable'
                    );
                END;
                """
            )
        )
        actor_reference_repointed = " OR ".join(
            f"((OLD.{actor_id} IS NOT NEW.{actor_id} OR "
            f"OLD.{actor_company} IS NOT NEW.{actor_company}) AND NOT "
            f"(OLD.{actor_id} IS NOT NULL AND OLD.{actor_company} IS NOT NULL "
            f"AND NEW.{actor_id} IS NULL AND NEW.{actor_company} IS NULL))"
            for actor_id, actor_company in actor_reference_pairs
        )
        state_columns = ", ".join(
            (
                "status",
                "activated_at",
                "retired_at",
                *(column for pair in actor_reference_pairs for column in pair),
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_ip_workflow_versions_state_guard
                BEFORE UPDATE OF {state_columns} ON ip_workflow_versions
                FOR EACH ROW
                WHEN NOT (
                         (OLD.status = 'candidate' AND
                          NEW.status IN ('candidate', 'approved', 'disabled')) OR
                         (OLD.status = 'approved' AND
                          NEW.status IN ('approved', 'active', 'retired', 'disabled')) OR
                         (OLD.status = 'active' AND
                          NEW.status IN ('active', 'retired', 'disabled')) OR
                         (OLD.status = 'retired' AND NEW.status = 'retired') OR
                         (OLD.status = 'disabled' AND NEW.status = 'disabled')
                     )
                     OR (
                         OLD.status <> 'candidate' AND
                         ({actor_reference_repointed})
                     )
                     OR (
                         OLD.activated_at IS NOT NEW.activated_at AND NOT (
                             OLD.status = 'approved' AND NEW.status = 'active' AND
                             OLD.activated_at IS NULL AND NEW.activated_at IS NOT NULL
                         )
                     )
                     OR (
                         OLD.retired_at IS NOT NEW.retired_at AND NOT (
                             OLD.status NOT IN ('retired', 'disabled') AND
                             NEW.status IN ('retired', 'disabled') AND
                             OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
                         )
                     )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'IP workflow version state or actor evidence mutation rejected'
                    );
                END;
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_workflow_versions_immutable_delete
                BEFORE DELETE ON ip_workflow_versions
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'IP workflow versions are retained; retire instead of delete'
                    );
                END;
                """
            )
        )
        definition_identity_changed = " OR ".join(
            f"OLD.{column_name} IS NOT NEW.{column_name}"
            for column_name in definition_identity_columns
        )
        definition_identity_update_columns = ", ".join(definition_identity_columns)
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_ip_workflow_definitions_immutable_update
                BEFORE UPDATE OF {definition_identity_update_columns}
                ON ip_workflow_definitions
                FOR EACH ROW
                WHEN {definition_identity_changed}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'IP workflow definition identity is immutable'
                    );
                END;
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_workflow_definitions_retained
                BEFORE DELETE ON ip_workflow_definitions
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'IP workflow definitions are retained; retire instead of delete'
                    );
                END;
                """
            )
        )


def _drop_workflow_version_immutability_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_ip_workflow_definitions_immutable "
                "ON ip_workflow_definitions"
            )
        )
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS "
                "caseops_reject_ip_workflow_definition_mutation()"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_ip_workflow_versions_immutable "
                "ON ip_workflow_versions"
            )
        )
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS "
                "caseops_reject_ip_workflow_version_mutation()"
            )
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_ip_workflow_definitions_retained"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_ip_workflow_definitions_immutable_update"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_ip_workflow_versions_immutable_update"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_ip_workflow_versions_approval_immutable_update"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_ip_workflow_versions_state_guard"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_ip_workflow_versions_immutable_delete"
            )
        )


def upgrade() -> None:
    op.create_table(
        "ip_workflow_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "aggregate_type",
            sa.String(64),
            nullable=False,
            server_default="ip_docket_record",
        ),
        sa.Column("initial_state", sa.String(64), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_workflow_definition_id_company"),
        sa.UniqueConstraint("company_id", "key", name="uq_ip_workflow_definition_company_key"),
        sa.CheckConstraint(
            "aggregate_type = 'ip_docket_record'",
            name="ck_ip_workflow_definition_aggregate_type",
        ),
    )
    op.create_index(
        "ix_ip_workflow_definitions_company_id",
        "ip_workflow_definitions",
        ["company_id"],
    )

    op.create_table(
        "ip_workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("definition_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="candidate"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("transition_table_json", sa.JSON(), nullable=False),
        sa.Column("fixture_set_json", sa.JSON(), nullable=False),
        sa.Column("source_reference", sa.String(512), nullable=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("engine_compatibility", sa.String(80), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("proposed_by_membership_company_id", sa.String(36), nullable=True),
        sa.Column("proposer_membership_id_snapshot", sa.String(36), nullable=True),
        sa.Column("proposer_user_id_snapshot", sa.String(36), nullable=True),
        sa.Column("proposer_label_snapshot", sa.String(255), nullable=True),
        sa.Column("proposer_authority_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("reviewed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_membership_company_id", sa.String(36), nullable=True),
        sa.Column("reviewer_membership_id_snapshot", sa.String(36), nullable=True),
        sa.Column("reviewer_user_id_snapshot", sa.String(36), nullable=True),
        sa.Column("reviewer_label_snapshot", sa.String(255), nullable=True),
        sa.Column("reviewer_authority_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("legal_approved_by_membership_id", sa.String(36), nullable=True),
        sa.Column(
            "legal_approved_by_membership_company_id", sa.String(36), nullable=True
        ),
        sa.Column(
            "legal_approver_membership_id_snapshot", sa.String(36), nullable=True
        ),
        sa.Column("legal_approver_user_id_snapshot", sa.String(36), nullable=True),
        sa.Column("legal_approver_label_snapshot", sa.String(255), nullable=True),
        sa.Column("legal_approver_authority_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("fixtures_passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id", "company_id"],
            ["ip_workflow_definitions.id", "ip_workflow_definitions.company_id"],
            name="fk_ip_workflow_version_definition_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_membership_id", "proposed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_proposer_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id", "reviewed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_reviewer_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            [
                "legal_approved_by_membership_id",
                "legal_approved_by_membership_company_id",
            ],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workflow_version_legal_approver_company",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_workflow_version_id_company"),
        sa.UniqueConstraint(
            "definition_id",
            "company_id",
            "version",
            name="uq_ip_workflow_version_definition_company_number",
        ),
        sa.UniqueConstraint(
            "id",
            "company_id",
            "definition_id",
            "version",
            name="uq_ip_workflow_version_pin",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_workflow_version_positive"),
        sa.CheckConstraint("schema_version > 0", name="ck_ip_workflow_schema_version_positive"),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_ip_workflow_version_status",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR "
            "effective_until >= effective_from",
            name="ck_ip_workflow_version_effective_range",
        ),
        sa.CheckConstraint(
            "proposed_by_membership_id IS NULL OR reviewed_by_membership_id IS NULL OR "
            "proposed_by_membership_id <> reviewed_by_membership_id",
            name="ck_ip_workflow_version_reviewer_distinct",
        ),
        sa.CheckConstraint(
            "proposed_by_membership_id IS NULL OR legal_approved_by_membership_id IS NULL OR "
            "proposed_by_membership_id <> legal_approved_by_membership_id",
            name="ck_ip_workflow_version_legal_approver_distinct",
        ),
        sa.CheckConstraint(
            "(proposed_by_membership_id IS NULL AND "
            "proposed_by_membership_company_id IS NULL) OR "
            "(proposed_by_membership_id IS NOT NULL AND "
            "proposed_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_proposer_company_complete",
        ),
        sa.CheckConstraint(
            "(reviewed_by_membership_id IS NULL AND "
            "reviewed_by_membership_company_id IS NULL) OR "
            "(reviewed_by_membership_id IS NOT NULL AND "
            "reviewed_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_reviewer_company_complete",
        ),
        sa.CheckConstraint(
            "(legal_approved_by_membership_id IS NULL AND "
            "legal_approved_by_membership_company_id IS NULL) OR "
            "(legal_approved_by_membership_id IS NOT NULL AND "
            "legal_approved_by_membership_company_id = company_id)",
            name="ck_ip_workflow_version_legal_approver_company_complete",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND length(source_hash) = 64",
            name="ck_ip_workflow_version_hash_lengths",
        ),
        sa.CheckConstraint(
            "(status = 'candidate' AND approved_at IS NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'approved' AND approved_at IS NOT NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'active' AND approved_at IS NOT NULL AND activated_at IS NOT NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'retired' AND approved_at IS NOT NULL AND retired_at IS NOT NULL) OR "
            "(status = 'disabled' AND retired_at IS NOT NULL)",
            name="ck_ip_workflow_version_status_timestamps",
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'active', 'retired') OR "
            "(proposer_membership_id_snapshot IS NOT NULL AND "
            "proposer_user_id_snapshot IS NOT NULL AND proposer_label_snapshot IS NOT NULL "
            "AND proposer_authority_snapshot_json IS NOT NULL AND "
            "reviewer_membership_id_snapshot IS NOT NULL AND "
            "reviewer_user_id_snapshot IS NOT NULL AND reviewer_label_snapshot IS NOT NULL "
            "AND reviewer_authority_snapshot_json IS NOT NULL AND "
            "legal_approver_membership_id_snapshot IS NOT NULL AND "
            "legal_approver_user_id_snapshot IS NOT NULL "
            "AND legal_approver_label_snapshot IS NOT NULL "
            "AND legal_approver_authority_snapshot_json IS NOT NULL "
            "AND fixtures_passed_at IS NOT NULL)",
            name="ck_ip_workflow_version_approved_evidence",
        ),
    )
    op.create_index(
        "ix_ip_workflow_versions_company_status",
        "ip_workflow_versions",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_ip_workflow_versions_definition_id",
        "ip_workflow_versions",
        ["definition_id"],
    )
    for actor_column, actor_company_column in (
        ("proposed_by_membership_id", "proposed_by_membership_company_id"),
        ("reviewed_by_membership_id", "reviewed_by_membership_company_id"),
        (
            "legal_approved_by_membership_id",
            "legal_approved_by_membership_company_id",
        ),
    ):
        op.create_index(
            f"ix_ip_workflow_versions_{actor_column}",
            "ip_workflow_versions",
            [actor_column, actor_company_column],
        )
    _create_workflow_version_immutability_guard(op.get_bind())

    op.add_column(
        "ip_docket_records",
        sa.Column("workflow_definition_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "ip_docket_records",
        sa.Column("workflow_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "ip_docket_records",
        sa.Column("workflow_version_number", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_ip_docket_records_workflow_definition_id",
        "ip_docket_records",
        ["workflow_definition_id"],
    )
    op.create_index(
        "ix_ip_docket_records_workflow_version_id",
        "ip_docket_records",
        ["workflow_version_id"],
    )
    op.create_index(
        "ix_ip_docket_records_workflow_version_number",
        "ip_docket_records",
        ["workflow_version_number"],
    )
    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.create_foreign_key(
            "fk_ip_docket_workflow_definition_company",
            "ip_workflow_definitions",
            ["workflow_definition_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_ip_docket_workflow_version_pin",
            "ip_workflow_versions",
            [
                "workflow_version_id",
                "company_id",
                "workflow_definition_id",
                "workflow_version_number",
            ],
            ["id", "company_id", "definition_id", "version"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_workflow_pin_complete",
            "(workflow_definition_id IS NULL AND workflow_version_id IS NULL AND "
            "workflow_version_number IS NULL) OR "
            "(workflow_definition_id IS NOT NULL AND workflow_version_id IS NOT NULL AND "
            "workflow_version_number IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_workflow_version_positive",
            "workflow_version_number IS NULL OR workflow_version_number > 0",
        )

    op.add_column(
        "ip_docket_events",
        sa.Column("resulting_lifecycle_version", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("ip_docket_events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_ip_docket_event_lifecycle_provenance",
            ["id", "company_id", "docket_id", "resulting_lifecycle_version"],
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_event_lifecycle_provenance_source",
            "resulting_lifecycle_version IS NULL OR "
            "(resulting_lifecycle_version > 0 AND "
            "event_kind = 'lifecycle_transition' AND candidate_status = 'confirmed')",
        )

    for table_name in _PROVENANCE_TABLES:
        _add_lifecycle_provenance(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    _assert_downgrade_is_evidence_free(bind)

    for table_name in reversed(_PROVENANCE_TABLES):
        prefix = _provenance_prefix(table_name)
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                f"ck_{prefix}_ip_lifecycle_terminal_state", type_="check"
            )
            batch_op.drop_constraint(
                f"ck_{prefix}_ip_lifecycle_provenance_target", type_="check"
            )
            batch_op.drop_constraint(
                f"ck_{prefix}_ip_lifecycle_version_positive", type_="check"
            )
            batch_op.drop_constraint(
                f"ck_{prefix}_ip_lifecycle_provenance_complete", type_="check"
            )
            batch_op.drop_constraint(
                f"fk_{prefix}_neutralized_event_company", type_="foreignkey"
            )
        op.drop_index(
            _provenance_index_name(table_name),
            table_name=table_name,
        )
        op.drop_column(table_name, "neutralized_at")
        op.drop_column(table_name, "neutralized_by_ip_lifecycle_version")
        op.drop_column(table_name, "neutralized_by_ip_lifecycle_event_id")
        if table_name == "calendar_event_syncs":
            op.drop_column(table_name, "neutralized_ip_docket_id")

    with op.batch_alter_table("ip_docket_events") as batch_op:
        batch_op.drop_constraint(
            "ck_ip_docket_event_lifecycle_provenance_source", type_="check"
        )
        batch_op.drop_constraint(
            "uq_ip_docket_event_lifecycle_provenance", type_="unique"
        )
    op.drop_column("ip_docket_events", "resulting_lifecycle_version")

    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.drop_constraint("ck_ip_docket_workflow_version_positive", type_="check")
        batch_op.drop_constraint("ck_ip_docket_workflow_pin_complete", type_="check")
        batch_op.drop_constraint("fk_ip_docket_workflow_version_pin", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_ip_docket_workflow_definition_company", type_="foreignkey"
        )
    op.drop_index(
        "ix_ip_docket_records_workflow_version_number",
        table_name="ip_docket_records",
    )
    op.drop_index(
        "ix_ip_docket_records_workflow_version_id", table_name="ip_docket_records"
    )
    op.drop_index(
        "ix_ip_docket_records_workflow_definition_id", table_name="ip_docket_records"
    )
    op.drop_column("ip_docket_records", "workflow_version_number")
    op.drop_column("ip_docket_records", "workflow_version_id")
    op.drop_column("ip_docket_records", "workflow_definition_id")

    _drop_workflow_version_immutability_guard(bind)
    for actor_column in reversed(
        (
            "proposed_by_membership_id",
            "reviewed_by_membership_id",
            "legal_approved_by_membership_id",
        )
    ):
        op.drop_index(
            f"ix_ip_workflow_versions_{actor_column}",
            table_name="ip_workflow_versions",
        )
    op.drop_index("ix_ip_workflow_versions_definition_id", table_name="ip_workflow_versions")
    op.drop_index("ix_ip_workflow_versions_company_status", table_name="ip_workflow_versions")
    op.drop_table("ip_workflow_versions")
    op.drop_index(
        "ix_ip_workflow_definitions_company_id", table_name="ip_workflow_definitions"
    )
    op.drop_table("ip_workflow_definitions")
