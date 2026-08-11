"""Switch record access to one tenant-correlated target and subject.

Revision ID: 20260811_0003
Revises: 20260811_0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260811_0003"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None

_ACTIVE_INDEXES = {
    "matter_access_grants": (
        (
            "uq_access_grant_active_matter_membership",
            ("matter_id", "membership_id"),
            "revoked_at IS NULL AND matter_id IS NOT NULL AND membership_id IS NOT NULL",
        ),
        (
            "uq_access_grant_active_matter_team",
            ("matter_id", "team_id"),
            "revoked_at IS NULL AND matter_id IS NOT NULL AND team_id IS NOT NULL",
        ),
        (
            "uq_access_grant_active_ip_membership",
            ("ip_docket_id", "membership_id"),
            "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND membership_id IS NOT NULL",
        ),
        (
            "uq_access_grant_active_ip_team",
            ("ip_docket_id", "team_id"),
            "revoked_at IS NULL AND ip_docket_id IS NOT NULL AND team_id IS NOT NULL",
        ),
    ),
    "ethical_walls": (
        (
            "uq_ethical_wall_active_matter_membership",
            ("matter_id", "excluded_membership_id"),
            "revoked_at IS NULL AND matter_id IS NOT NULL "
            "AND excluded_membership_id IS NOT NULL",
        ),
        (
            "uq_ethical_wall_active_matter_team",
            ("matter_id", "excluded_team_id"),
            "revoked_at IS NULL AND matter_id IS NOT NULL AND excluded_team_id IS NOT NULL",
        ),
        (
            "uq_ethical_wall_active_ip_membership",
            ("ip_docket_id", "excluded_membership_id"),
            "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
            "AND excluded_membership_id IS NOT NULL",
        ),
        (
            "uq_ethical_wall_active_ip_team",
            ("ip_docket_id", "excluded_team_id"),
            "revoked_at IS NULL AND ip_docket_id IS NOT NULL "
            "AND excluded_team_id IS NOT NULL",
        ),
    ),
}


def _drain_legacy_tail(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE matter_access_grants AS access
               SET company_id = matters.company_id,
                   effective_from = COALESCE(access.effective_from, access.created_at)
              FROM matters
             WHERE access.matter_id = matters.id
               AND access.company_id IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE ethical_walls AS wall
               SET company_id = matters.company_id,
                   effective_from = COALESCE(wall.effective_from, wall.created_at)
              FROM matters
             WHERE wall.matter_id = matters.id
               AND wall.company_id IS NULL
            """
        )
    )


def _assert_reconciled(connection: sa.Connection) -> None:
    for table_name, subject_columns in (
        ("matter_access_grants", ("membership_id", "team_id")),
        ("ethical_walls", ("excluded_membership_id", "excluded_team_id")),
    ):
        first_subject, second_subject = subject_columns
        invalid = connection.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                  FROM {table_name}
                 WHERE company_id IS NULL
                    OR ((matter_id IS NOT NULL) = (ip_docket_id IS NOT NULL))
                    OR (({first_subject} IS NOT NULL) = ({second_subject} IS NOT NULL))
                """
            )
        ).scalar_one()
        if invalid:
            raise RuntimeError(
                f"{table_name} contains {invalid} unreconciled access rows"
            )
        target_mismatch = connection.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                  FROM {table_name} AS access
             LEFT JOIN matters AS matter ON matter.id = access.matter_id
             LEFT JOIN ip_docket_records AS docket ON docket.id = access.ip_docket_id
                 WHERE (access.matter_id IS NOT NULL
                        AND (matter.id IS NULL OR matter.company_id <> access.company_id))
                    OR (access.ip_docket_id IS NOT NULL
                        AND (docket.id IS NULL OR docket.company_id <> access.company_id))
                """
            )
        ).scalar_one()
        if target_mismatch:
            raise RuntimeError(
                f"{table_name} contains {target_mismatch} cross-company targets"
            )


def _switch_grants() -> None:
    with op.batch_alter_table("matter_access_grants") as batch_op:
        batch_op.drop_constraint(
            "uq_matter_access_grants_matter_membership", type_="unique"
        )
        batch_op.create_foreign_key(
            "fk_access_grant_company",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_ip_docket",
            "ip_docket_records",
            ["ip_docket_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_team",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_revoker",
            "company_memberships",
            ["revoked_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_matter_company",
            "matters",
            ["matter_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_membership_company",
            "company_memberships",
            ["membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_access_grant_team_company",
            "teams",
            ["team_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "ck_access_grant_exactly_one_target",
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_access_grant_exactly_one_subject",
            "(CASE WHEN membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN team_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_access_grant_record_version_nonnegative",
            "record_version >= 0",
        )
        batch_op.create_check_constraint(
            "ck_access_grant_effective_window",
            "expires_at IS NULL OR effective_from IS NULL OR expires_at > effective_from",
        )


def _switch_walls() -> None:
    with op.batch_alter_table("ethical_walls") as batch_op:
        batch_op.drop_constraint("uq_ethical_walls_matter_excluded", type_="unique")
        batch_op.create_foreign_key(
            "fk_ethical_wall_company",
            "companies",
            ["company_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_ip_docket",
            "ip_docket_records",
            ["ip_docket_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_team",
            "teams",
            ["excluded_team_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_revoker",
            "company_memberships",
            ["revoked_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_matter_company",
            "matters",
            ["matter_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_ip_docket_company",
            "ip_docket_records",
            ["ip_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_membership_company",
            "company_memberships",
            ["excluded_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_ethical_wall_team_company",
            "teams",
            ["excluded_team_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "ck_ethical_wall_exactly_one_target",
            "(CASE WHEN matter_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN ip_docket_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_ethical_wall_exactly_one_subject",
            "(CASE WHEN excluded_membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN excluded_team_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch_op.create_check_constraint(
            "ck_ethical_wall_record_version_nonnegative",
            "record_version >= 0",
        )
        batch_op.create_check_constraint(
            "ck_ethical_wall_effective_window",
            "expires_at IS NULL OR effective_from IS NULL OR expires_at > effective_from",
        )


def upgrade() -> None:
    connection = op.get_bind()
    _drain_legacy_tail(connection)
    _assert_reconciled(connection)

    with op.batch_alter_table("teams") as batch_op:
        batch_op.create_unique_constraint(
            "uq_teams_id_company_id", ["id", "company_id"]
        )
    _switch_grants()
    _switch_walls()
    for table_name, index_specs in _ACTIVE_INDEXES.items():
        for name, columns, predicate in index_specs:
            op.create_index(
                name,
                table_name,
                list(columns),
                unique=True,
                postgresql_where=sa.text(predicate),
                sqlite_where=sa.text(predicate),
            )

    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.create_foreign_key(
            "fk_audit_event_ip_docket",
            "ip_docket_records",
            ["ip_docket_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("matters") as batch_op:
        batch_op.create_check_constraint(
            "ck_matters_access_policy_version_nonnegative",
            "access_policy_version >= 0",
        )
    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.create_check_constraint(
            "ck_ip_docket_access_policy_version_nonnegative",
            "access_policy_version >= 0",
        )
    with op.batch_alter_table("source_link_reports") as batch_op:
        batch_op.drop_constraint(
            "ck_source_link_reports_target_type", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_source_link_reports_target_type",
            "target_type in ('authority_document', 'statute_section', "
            "'judge_appointment', 'matter_attachment', 'ip_document_version')",
        )


def downgrade() -> None:
    with op.batch_alter_table("source_link_reports") as batch_op:
        batch_op.drop_constraint(
            "ck_source_link_reports_target_type", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_source_link_reports_target_type",
            "target_type in ('authority_document', 'statute_section', "
            "'judge_appointment', 'matter_attachment')",
        )
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("fk_audit_event_ip_docket", type_="foreignkey")
    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.drop_constraint(
            "ck_ip_docket_access_policy_version_nonnegative", type_="check"
        )
    with op.batch_alter_table("matters") as batch_op:
        batch_op.drop_constraint(
            "ck_matters_access_policy_version_nonnegative", type_="check"
        )

    for table_name, index_specs in _ACTIVE_INDEXES.items():
        for name, _columns, _predicate in index_specs:
            op.drop_index(name, table_name=table_name)

    with op.batch_alter_table("ethical_walls") as batch_op:
        for name, kind in (
            ("ck_ethical_wall_effective_window", "check"),
            ("ck_ethical_wall_record_version_nonnegative", "check"),
            ("ck_ethical_wall_exactly_one_subject", "check"),
            ("ck_ethical_wall_exactly_one_target", "check"),
            ("fk_ethical_wall_team_company", "foreignkey"),
            ("fk_ethical_wall_membership_company", "foreignkey"),
            ("fk_ethical_wall_ip_docket_company", "foreignkey"),
            ("fk_ethical_wall_matter_company", "foreignkey"),
            ("fk_ethical_wall_revoker", "foreignkey"),
            ("fk_ethical_wall_team", "foreignkey"),
            ("fk_ethical_wall_ip_docket", "foreignkey"),
            ("fk_ethical_wall_company", "foreignkey"),
        ):
            batch_op.drop_constraint(name, type_=kind)
        batch_op.create_unique_constraint(
            "uq_ethical_walls_matter_excluded",
            ["matter_id", "excluded_membership_id"],
        )

    with op.batch_alter_table("matter_access_grants") as batch_op:
        for name, kind in (
            ("ck_access_grant_effective_window", "check"),
            ("ck_access_grant_record_version_nonnegative", "check"),
            ("ck_access_grant_exactly_one_subject", "check"),
            ("ck_access_grant_exactly_one_target", "check"),
            ("fk_access_grant_team_company", "foreignkey"),
            ("fk_access_grant_membership_company", "foreignkey"),
            ("fk_access_grant_ip_docket_company", "foreignkey"),
            ("fk_access_grant_matter_company", "foreignkey"),
            ("fk_access_grant_revoker", "foreignkey"),
            ("fk_access_grant_team", "foreignkey"),
            ("fk_access_grant_ip_docket", "foreignkey"),
            ("fk_access_grant_company", "foreignkey"),
        ):
            batch_op.drop_constraint(name, type_=kind)
        batch_op.create_unique_constraint(
            "uq_matter_access_grants_matter_membership",
            ["matter_id", "membership_id"],
        )

    # The legacy schema cannot represent IP targets. These rows are migration
    # snapshots, not a second owner, and are safely rebuilt on re-upgrade.
    op.execute("DELETE FROM ethical_walls WHERE matter_id IS NULL")
    op.execute("DELETE FROM matter_access_grants WHERE matter_id IS NULL")
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("uq_teams_id_company_id", type_="unique")
