"""evaluation runs and cases

Revision ID: 20260418_0005
Revises: 20260418_0004
Create Date: 2026-04-18 14:00:00

Adds a minimal evaluation harness surface:

- ``evaluation_runs`` — one row per invocation of a named suite against
  one (provider, model, git_sha) triple. Carries aggregated pass / fail
  counts and a JSON metrics snapshot.
- ``evaluation_cases`` — per-case detail (which test case, what body
  the model produced, which validator findings fired, any error).

This is deliberately a thin audit layer. It does NOT try to be a
full ML experiment tracker — the point is to catch regressions in
the drafting pipeline (and later the recommendation pipeline) on a
fixed seed set before they ship.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0005"
down_revision = "20260418_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("suite_name", sa.String(length=80), nullable=False, index=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("git_sha", sa.String(length=64), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("case_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("blocker_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("body_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "verified_citation_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "case_key", name="uq_eval_case_key_per_run"),
    )


def downgrade() -> None:
    op.drop_table("evaluation_cases")
    op.drop_table("evaluation_runs")
