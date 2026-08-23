"""Add the IPLF-040A opposition proceeding foundation.

Revision ID: 20260823_0001
Revises: 20260822_0002
Create Date: 2026-08-23

The existing ``ip_proceedings`` and ``ip_docket_events`` owners remain
canonical. This migration adds only typed opposition intake metadata and
database constraints, then enforces append-only opposition-stage evidence
below the ORM boundary without changing other existing event finalization.

MIGRATION-LOCK-RISK: acknowledged: three metadata columns and five constraints
are added to an existing table. Defaults deterministically classify legacy rows
without changing legal stage or identifier data.
MIGRATION-ROLLBACK: restore-forward: downgrade refuses while any opposition
event written under this contract exists, because removing its constraints or
append-only guard would weaken retained legal history.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260823_0001"
down_revision = "20260822_0002"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated

OPPOSITION_STAGES = (
    "draft",
    "notice_filed",
    "service_pending",
    "counterstatement_due",
    "counterstatement_filed",
    "opponent_evidence_due",
    "opponent_evidence_filed",
    "applicant_evidence_due",
    "applicant_evidence_filed",
    "reply_evidence_due",
    "reply_evidence_filed",
    "hearing_pending",
    "hearing_scheduled",
    "reserved_for_order",
    "decided",
    "appeal_pending",
    "appealed",
    "withdrawn",
    "closed",
)


def _stage_sql() -> str:
    return ", ".join(f"'{value}'" for value in OPPOSITION_STAGES)


def _create_event_append_only_trigger(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION reject_ip_docket_event_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF COALESCE(
                        (OLD.payload_json ->> 'opposition_stage_transition')::boolean,
                        false
                    ) THEN
                        RAISE EXCEPTION 'opposition stage events are append-only';
                    END IF;
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_docket_events_append_only
                BEFORE UPDATE OR DELETE ON ip_docket_events
                FOR EACH ROW EXECUTE FUNCTION reject_ip_docket_event_mutation()
                """
            )
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_docket_events_append_only_update
                BEFORE UPDATE ON ip_docket_events
                WHEN COALESCE(
                    json_extract(OLD.payload_json, '$.opposition_stage_transition'), 0
                ) = 1
                BEGIN
                    SELECT RAISE(ABORT, 'opposition stage events are append-only');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_docket_events_append_only_delete
                BEFORE DELETE ON ip_docket_events
                WHEN COALESCE(
                    json_extract(OLD.payload_json, '$.opposition_stage_transition'), 0
                ) = 1
                BEGIN
                    SELECT RAISE(ABORT, 'opposition stage events are append-only');
                END
                """
            )
        )


def _drop_event_append_only_trigger(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_ip_docket_events_append_only ON ip_docket_events")
        op.execute("DROP FUNCTION IF EXISTS reject_ip_docket_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ip_docket_events_append_only_update")
        op.execute("DROP TRIGGER IF EXISTS trg_ip_docket_events_append_only_delete")


def upgrade() -> None:
    with op.batch_alter_table("ip_proceedings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "origin_kind",
                sa.String(32),
                nullable=False,
                server_default="manual_intake",
            )
        )
        batch_op.add_column(
            sa.Column(
                "stage_template_version",
                sa.String(80),
                nullable=False,
                server_default="generic-v1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_pending_identifier_allocation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_check_constraint(
            "ck_ip_proceeding_origin_kind",
            "origin_kind IN ('linked_application', 'registry_event', 'watch_hit', "
            "'manual_intake')",
        )
        batch_op.create_check_constraint(
            "ck_ip_opposition_represented_side",
            "proceeding_kind <> 'opposition' OR side IN ('applicant', 'opponent')",
        )
        batch_op.create_check_constraint(
            "ck_ip_opposition_canonical_stage",
            f"proceeding_kind <> 'opposition' OR stage IN ({_stage_sql()})",
        )
        batch_op.create_check_constraint(
            "ck_ip_proceeding_stage_template_version",
            "length(trim(stage_template_version)) > 0",
        )

    op.execute(
        sa.text(
            "UPDATE ip_proceedings "
            "SET stage_template_version = CASE side "
            "WHEN 'applicant' THEN 'opposition-applicant-v1' "
            "WHEN 'opponent' THEN 'opposition-opponent-v1' "
            "ELSE stage_template_version END "
            "WHERE proceeding_kind = 'opposition'"
        )
    )
    with op.batch_alter_table("ip_proceedings") as batch_op:
        batch_op.create_check_constraint(
            "ck_ip_opposition_role_stage_template",
            "proceeding_kind <> 'opposition' OR "
            "(side = 'applicant' AND "
            "stage_template_version = 'opposition-applicant-v1') OR "
            "(side = 'opponent' AND "
            "stage_template_version = 'opposition-opponent-v1')",
        )

    _create_event_append_only_trigger(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    retained = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM ip_docket_events event
            JOIN ip_proceedings proceeding
              ON proceeding.id = event.proceeding_id
             AND proceeding.company_id = event.company_id
            WHERE proceeding.proceeding_kind = 'opposition'
              AND event.payload_json IS NOT NULL
            """
        )
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "refusing to downgrade: retained opposition stage evidence requires "
            "the IPLF-040A contract"
        )

    _drop_event_append_only_trigger(bind)
    with op.batch_alter_table("ip_proceedings") as batch_op:
        batch_op.drop_constraint(
            "ck_ip_opposition_role_stage_template", type_="check"
        )
        batch_op.drop_constraint(
            "ck_ip_proceeding_stage_template_version", type_="check"
        )
        batch_op.drop_constraint("ck_ip_opposition_canonical_stage", type_="check")
        batch_op.drop_constraint("ck_ip_opposition_represented_side", type_="check")
        batch_op.drop_constraint("ck_ip_proceeding_origin_kind", type_="check")
        batch_op.drop_column("source_pending_identifier_allocation")
        batch_op.drop_column("stage_template_version")
        batch_op.drop_column("origin_kind")
