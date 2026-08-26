"""IPLF-060A canonical judge, bench alias, and mapping-review foundation.

Revision ID: 20260826_0002
Revises: 20260826_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260826_0002"
down_revision = "20260826_0001"
branch_labels = None
depends_on = None

# MIGRATION-LOCK-RISK: acknowledged: existing judge/index owners are bounded
# catalog tables and PostgreSQL lock acquisition is capped at five seconds;
# indexes on the two new tables are built before those tables can hold rows.
# MIGRATION-ROLLBACK: restore-forward: once catalog provenance, curator reviews,
# or mapping evidence is written, removing this schema would destroy committed
# legal-source lineage; downgrade is limited to an unused pre-release revision.
# DATA-GOVERNANCE-MAP: updated in the reviewed schema inventory.


def _assert_downgrade_unused() -> None:
    checks = {
        "bench aliases": "SELECT 1 FROM bench_aliases LIMIT 1",
        "judge mapping reviews": "SELECT 1 FROM judge_mapping_reviews LIMIT 1",
        "judge identity provenance": """
            SELECT 1 FROM judges
            WHERE source_name IS NOT NULL
               OR source_url IS NOT NULL
               OR source_reference IS NOT NULL
               OR identity_version <> 1
               OR record_version <> 0
               OR merged_into_judge_id IS NOT NULL
            LIMIT 1
        """,
        "bench provenance": """
            SELECT 1 FROM benches
            WHERE source_name IS NOT NULL
               OR source_url IS NOT NULL
               OR source_reference IS NOT NULL
               OR record_version <> 0
            LIMIT 1
        """,
        "judge alias provenance": """
            SELECT 1 FROM judge_aliases
            WHERE source_url IS NOT NULL
               OR source_evidence_text IS NOT NULL
               OR is_active = false
               OR record_version <> 0
            LIMIT 1
        """,
        "judge mapping evidence": """
            SELECT 1 FROM judge_decision_index
            WHERE raw_judge_name IS NOT NULL
               OR source_ordinal IS NOT NULL
               OR mapping_status <> 'legacy_confirmed'
               OR resolver_version <> 'legacy-v1'
               OR evidence_json IS NOT NULL
            LIMIT 1
        """,
    }
    connection = op.get_bind()
    for owner, query in checks.items():
        if connection.execute(sa.text(query)).first() is not None:
            raise RuntimeError(
                f"Restore-forward required: {owner} contains IPLF-060A data."
            )


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.add_column("judges", sa.Column("source_name", sa.String(160), nullable=True))
    op.add_column("judges", sa.Column("source_url", sa.String(500), nullable=True))
    op.add_column("judges", sa.Column("source_reference", sa.String(500), nullable=True))
    op.add_column(
        "judges",
        sa.Column("identity_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "judges",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
    )
    merged_column_args: tuple[object, ...] = (sa.String(36),)
    if dialect_name != "sqlite":
        merged_column_args += (sa.ForeignKey("judges.id", ondelete="RESTRICT"),)
    op.add_column(
        "judges",
        sa.Column("merged_into_judge_id", *merged_column_args, nullable=True),
    )
    op.create_index(
        "ix_judges_merged_into_judge_id", "judges", ["merged_into_judge_id"]
    )

    op.add_column("benches", sa.Column("source_name", sa.String(160), nullable=True))
    op.add_column("benches", sa.Column("source_url", sa.String(500), nullable=True))
    op.add_column("benches", sa.Column("source_reference", sa.String(500), nullable=True))
    op.add_column(
        "benches",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column("judge_aliases", sa.Column("source_url", sa.String(500), nullable=True))
    op.add_column(
        "judge_aliases", sa.Column("source_evidence_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "judge_aliases",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "judge_aliases",
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "judge_decision_index", sa.Column("raw_judge_name", sa.String(255), nullable=True)
    )
    op.add_column(
        "judge_decision_index", sa.Column("source_ordinal", sa.Integer(), nullable=True)
    )
    op.add_column(
        "judge_decision_index",
        sa.Column(
            "mapping_status",
            sa.String(32),
            nullable=False,
            server_default="legacy_confirmed",
        ),
    )
    op.add_column(
        "judge_decision_index",
        sa.Column(
            "resolver_version",
            sa.String(64),
            nullable=False,
            server_default="legacy-v1",
        ),
    )
    op.add_column("judge_decision_index", sa.Column("evidence_json", sa.JSON(), nullable=True))
    op.add_column(
        "judge_decision_index",
        sa.Column(
            "is_analytics_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    legacy_mapping = sa.table(
        "judge_decision_index",
        sa.column("match_confidence", sa.String(24)),
        sa.column("is_analytics_eligible", sa.Boolean()),
    )
    op.execute(
        legacy_mapping.update().values(
            is_analytics_eligible=sa.func.lower(
                sa.func.coalesce(legacy_mapping.c.match_confidence, "")
            ).in_(("exact", "initial_surname", "curator_confirmed"))
        )
    )
    updated_at_column = sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=dialect_name == "sqlite",
        server_default=(
            None if dialect_name == "sqlite" else sa.text("CURRENT_TIMESTAMP")
        ),
    )
    op.add_column("judge_decision_index", updated_at_column)
    if dialect_name == "sqlite":
        op.execute(
            sa.text(
                """
                UPDATE judge_decision_index
                SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                WHERE updated_at IS NULL
                """
            )
        )
        with op.batch_alter_table("judge_decision_index") as batch_op:
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
    op.create_index(
        "ix_judge_decision_index_analytics",
        "judge_decision_index",
        ["judge_id", "is_analytics_eligible", "year"],
    )

    op.create_table(
        "bench_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bench_id",
            sa.String(36),
            sa.ForeignKey("benches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias_text", sa.String(255), nullable=False),
        sa.Column("alias_normalised", sa.String(255), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "bench_id", "alias_normalised", name="uq_bench_aliases_unique"
        ),
    )
    op.create_index("ix_bench_aliases_bench_id", "bench_aliases", ["bench_id"])
    op.create_index("ix_bench_aliases_alias_text", "bench_aliases", ["alias_text"])
    op.create_index(
        "ix_bench_aliases_alias_normalised", "bench_aliases", ["alias_normalised"]
    )

    op.create_table(
        "judge_mapping_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "authority_document_id",
            sa.String(36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "court_id",
            sa.String(36),
            sa.ForeignKey("courts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("raw_judge_name", sa.String(255), nullable=False),
        sa.Column("raw_judge_name_normalised", sa.String(255), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("candidate_judge_ids_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("resolver_version", sa.String(64), nullable=False),
        sa.Column(
            "resolved_judge_id",
            sa.String(36),
            sa.ForeignKey("judges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "authority_document_id",
            "source_ordinal",
            "raw_judge_name_normalised",
            name="uq_judge_mapping_reviews_evidence",
        ),
    )
    for column in (
        "authority_document_id",
        "court_id",
        "reason",
        "status",
        "resolved_judge_id",
        "resolved_by_membership_id",
    ):
        op.create_index(
            f"ix_judge_mapping_reviews_{column}", "judge_mapping_reviews", [column]
        )


def downgrade() -> None:
    _assert_downgrade_unused()
    for column in (
        "resolved_by_membership_id",
        "resolved_judge_id",
        "status",
        "reason",
        "court_id",
        "authority_document_id",
    ):
        op.drop_index(
            f"ix_judge_mapping_reviews_{column}", table_name="judge_mapping_reviews"
        )
    op.drop_table("judge_mapping_reviews")

    op.drop_index("ix_bench_aliases_alias_normalised", table_name="bench_aliases")
    op.drop_index("ix_bench_aliases_alias_text", table_name="bench_aliases")
    op.drop_index("ix_bench_aliases_bench_id", table_name="bench_aliases")
    op.drop_table("bench_aliases")

    op.drop_index("ix_judge_decision_index_analytics", table_name="judge_decision_index")
    for column in (
        "updated_at",
        "is_analytics_eligible",
        "evidence_json",
        "resolver_version",
        "mapping_status",
        "source_ordinal",
        "raw_judge_name",
    ):
        op.drop_column("judge_decision_index", column)

    for column in ("record_version", "is_active", "source_evidence_text", "source_url"):
        op.drop_column("judge_aliases", column)

    for column in ("record_version", "source_reference", "source_url", "source_name"):
        op.drop_column("benches", column)

    op.drop_index("ix_judges_merged_into_judge_id", table_name="judges")
    for column in (
        "merged_into_judge_id",
        "record_version",
        "identity_version",
        "source_reference",
        "source_url",
        "source_name",
    ):
        op.drop_column("judges", column)
