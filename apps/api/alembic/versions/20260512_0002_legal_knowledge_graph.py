"""Legal knowledge graph materialization foundation.

Revision ID: 20260512_0002
Revises: 20260512_0001
Create Date: 2026-05-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260512_0002"
down_revision = "20260512_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NODE_TYPES = (
    "'matter', 'proceeding_signal', 'affidavit_statement', "
    "'affidavit_question', 'mock_hearing_question', 'mock_hearing_response', "
    "'predictive_signal', 'bench_context', 'legal_source', "
    "'statute_or_issue', 'review_action'"
)
_EDGE_TYPES = (
    "'supports', 'contradicts', 'references', 'derived_from', "
    "'prompts', 'relates_to', 'has_limitation'"
)
_SOURCE_TYPES = (
    "'matter', 'matter_court_order', 'matter_proceeding_signal', "
    "'matter_document', 'matter_attachment_chunk', 'affidavit_statement', "
    "'affidavit_question', 'mock_hearing_session', 'mock_hearing_question', "
    "'mock_hearing_response', 'predictive_signal_item', 'predictive_signal_run', "
    "'authority_document', 'aggregate_snapshot', "
    "'litigation_intelligence_review_action', 'unavailable'"
)


def upgrade() -> None:
    op.create_table(
        "legal_knowledge_graph_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_data_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("limitation_note", sa.Text(), nullable=False),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('completed', 'no_source_records')",
            name="ck_legal_knowledge_graph_runs_status",
        ),
        sa.UniqueConstraint(
            "company_id",
            "matter_id",
            name="uq_legal_knowledge_graph_run_matter",
        ),
    )
    for column in ("company_id", "matter_id", "created_by_membership_id", "status"):
        op.create_index(
            f"ix_legal_knowledge_graph_runs_{column}",
            "legal_knowledge_graph_runs",
            [column],
        )

    op.create_table(
        "legal_knowledge_graph_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("legal_knowledge_graph_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_key", sa.String(length=180), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.String(length=32), nullable=True),
        sa.Column("review_status", sa.String(length=64), nullable=True),
        sa.Column("limitation_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"node_type in ({_NODE_TYPES})",
            name="ck_legal_knowledge_graph_nodes_node_type",
        ),
        sa.CheckConstraint(
            f"source_type in ({_SOURCE_TYPES})",
            name="ck_legal_knowledge_graph_nodes_source_type",
        ),
        sa.UniqueConstraint(
            "run_id",
            "node_key",
            name="uq_legal_knowledge_graph_node_run_key",
        ),
    )
    for column in (
        "run_id",
        "company_id",
        "matter_id",
        "node_key",
        "node_type",
        "source_type",
        "source_id",
        "review_status",
    ):
        op.create_index(
            f"ix_legal_knowledge_graph_nodes_{column}",
            "legal_knowledge_graph_nodes",
            [column],
        )

    op.create_table(
        "legal_knowledge_graph_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("legal_knowledge_graph_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_node_id",
            sa.String(length=36),
            sa.ForeignKey("legal_knowledge_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_node_id",
            sa.String(length=36),
            sa.ForeignKey("legal_knowledge_graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("edge_type", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.String(length=32), nullable=True),
        sa.Column("limitation_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"edge_type in ({_EDGE_TYPES})",
            name="ck_legal_knowledge_graph_edges_edge_type",
        ),
        sa.CheckConstraint(
            f"source_type in ({_SOURCE_TYPES})",
            name="ck_legal_knowledge_graph_edges_source_type",
        ),
        sa.UniqueConstraint(
            "run_id",
            "from_node_id",
            "to_node_id",
            "edge_type",
            "source_type",
            "source_id",
            name="uq_legal_knowledge_graph_edge_identity",
        ),
    )
    for column in (
        "run_id",
        "company_id",
        "matter_id",
        "from_node_id",
        "to_node_id",
        "edge_type",
        "source_type",
        "source_id",
    ):
        op.create_index(
            f"ix_legal_knowledge_graph_edges_{column}",
            "legal_knowledge_graph_edges",
            [column],
        )


def downgrade() -> None:
    for column in (
        "source_id",
        "source_type",
        "edge_type",
        "to_node_id",
        "from_node_id",
        "matter_id",
        "company_id",
        "run_id",
    ):
        op.drop_index(
            f"ix_legal_knowledge_graph_edges_{column}",
            table_name="legal_knowledge_graph_edges",
        )
    op.drop_table("legal_knowledge_graph_edges")

    for column in (
        "review_status",
        "source_id",
        "source_type",
        "node_type",
        "node_key",
        "matter_id",
        "company_id",
        "run_id",
    ):
        op.drop_index(
            f"ix_legal_knowledge_graph_nodes_{column}",
            table_name="legal_knowledge_graph_nodes",
        )
    op.drop_table("legal_knowledge_graph_nodes")

    for column in ("status", "created_by_membership_id", "matter_id", "company_id"):
        op.drop_index(
            f"ix_legal_knowledge_graph_runs_{column}",
            table_name="legal_knowledge_graph_runs",
        )
    op.drop_table("legal_knowledge_graph_runs")
