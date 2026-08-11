"""Backfill tenant correlation and snapshot inherited IP visibility.

Revision ID: 20260811_0002
Revises: 20260811_0001

Linked IP records previously delegated every access decision to their Matter.
This migration snapshots that effective policy into the generalized canonical
rows once. Later Matter changes do not silently broaden or narrow IP access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def _insert_grant(
    connection: sa.Connection,
    *,
    company_id: str,
    docket_id: str,
    membership_id: str | None = None,
    team_id: str | None = None,
    reason: str,
    actor_id: str | None = None,
    effective_from: datetime | None = None,
    created_at: datetime | None = None,
) -> None:
    subject_column = "membership_id" if membership_id is not None else "team_id"
    subject_value = membership_id or team_id
    if subject_value is None:
        return
    exists = connection.execute(
        sa.text(
            f"""
            SELECT 1
              FROM matter_access_grants
             WHERE ip_docket_id = :docket_id
               AND {subject_column} = :subject_value
               AND revoked_at IS NULL
             LIMIT 1
            """
        ),
        {"docket_id": docket_id, "subject_value": subject_value},
    ).scalar()
    if exists:
        return
    now = created_at or datetime.now(UTC)
    connection.execute(
        sa.text(
            """
            INSERT INTO matter_access_grants (
                id, company_id, matter_id, ip_docket_id, membership_id, team_id,
                access_level, reason, granted_by_membership_id, effective_from,
                expires_at, revoked_at, revoked_by_membership_id, record_version,
                created_at
            ) VALUES (
                :id, :company_id, NULL, :docket_id, :membership_id, :team_id,
                'member', :reason, :actor_id, :effective_from,
                NULL, NULL, NULL, 0, :created_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "docket_id": docket_id,
            "membership_id": membership_id,
            "team_id": team_id,
            "reason": reason,
            "actor_id": actor_id,
            "effective_from": effective_from or now,
            "created_at": now,
        },
    )


def _insert_wall(
    connection: sa.Connection,
    *,
    company_id: str,
    docket_id: str,
    membership_id: str | None,
    team_id: str | None,
    reason: str | None,
    actor_id: str | None,
    effective_from: datetime | None,
    created_at: datetime,
) -> None:
    subject_column = (
        "excluded_membership_id" if membership_id is not None else "excluded_team_id"
    )
    subject_value = membership_id or team_id
    if subject_value is None:
        return
    exists = connection.execute(
        sa.text(
            f"""
            SELECT 1
              FROM ethical_walls
             WHERE ip_docket_id = :docket_id
               AND {subject_column} = :subject_value
               AND revoked_at IS NULL
             LIMIT 1
            """
        ),
        {"docket_id": docket_id, "subject_value": subject_value},
    ).scalar()
    if exists:
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO ethical_walls (
                id, company_id, matter_id, ip_docket_id,
                excluded_membership_id, excluded_team_id, reason,
                created_by_membership_id, effective_from, expires_at,
                revoked_at, revoked_by_membership_id, record_version, created_at
            ) VALUES (
                :id, :company_id, NULL, :docket_id,
                :membership_id, :team_id, :reason,
                :actor_id, :effective_from, NULL,
                NULL, NULL, 0, :created_at
            )
            """
        ),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "docket_id": docket_id,
            "membership_id": membership_id,
            "team_id": team_id,
            "reason": reason,
            "actor_id": actor_id,
            "effective_from": effective_from or created_at,
            "created_at": created_at,
        },
    )


def snapshot_linked_ip_access(connection: sa.Connection) -> None:
    dockets = connection.execute(
        sa.text(
            """
            SELECT d.id AS docket_id, d.company_id, d.restricted,
                   d.created_by_membership_id,
                   m.id AS matter_id, m.restricted_access,
                   m.assignee_membership_id, m.team_id,
                   c.team_scoping_enabled
              FROM ip_docket_records AS d
              JOIN matters AS m
                ON m.id = d.matter_id AND m.company_id = d.company_id
              JOIN companies AS c ON c.id = d.company_id
            """
        )
    ).mappings()
    for docket in dockets:
        company_id = str(docket["company_id"])
        docket_id = str(docket["docket_id"])
        matter_id = str(docket["matter_id"])

        matter_grants = list(
            connection.execute(
                sa.text(
                    """
                    SELECT membership_id, team_id, reason,
                           granted_by_membership_id, effective_from, created_at
                      FROM matter_access_grants
                     WHERE matter_id = :matter_id AND revoked_at IS NULL
                    """
                ),
                {"matter_id": matter_id},
            ).mappings()
        )
        for grant in matter_grants:
            _insert_grant(
                connection,
                company_id=company_id,
                docket_id=docket_id,
                membership_id=grant["membership_id"],
                team_id=grant["team_id"],
                reason=grant["reason"] or "Migrated from linked Matter access.",
                actor_id=grant["granted_by_membership_id"],
                effective_from=grant["effective_from"],
                created_at=grant["created_at"],
            )

        matter_walls = list(
            connection.execute(
                sa.text(
                    """
                    SELECT excluded_membership_id, excluded_team_id, reason,
                           created_by_membership_id, effective_from, created_at
                      FROM ethical_walls
                     WHERE matter_id = :matter_id AND revoked_at IS NULL
                    """
                ),
                {"matter_id": matter_id},
            ).mappings()
        )
        for wall in matter_walls:
            _insert_wall(
                connection,
                company_id=company_id,
                docket_id=docket_id,
                membership_id=wall["excluded_membership_id"],
                team_id=wall["excluded_team_id"],
                reason=wall["reason"],
                actor_id=wall["created_by_membership_id"],
                effective_from=wall["effective_from"],
                created_at=wall["created_at"],
            )

        docket_restricted = bool(docket["restricted"])
        matter_restricted = bool(docket["restricted_access"])
        team_scoped = bool(docket["team_scoping_enabled"] and docket["team_id"])
        if not (docket_restricted or matter_restricted or team_scoped):
            continue

        connection.execute(
            sa.text(
                """
                UPDATE ip_docket_records
                   SET restricted = true,
                       access_policy_version = access_policy_version + 1
                 WHERE id = :docket_id
                """
            ),
            {"docket_id": docket_id},
        )

        owner_ids = connection.execute(
            sa.text(
                """
                SELECT id
                  FROM company_memberships
                 WHERE company_id = :company_id
                   AND is_active = true
                   AND role = 'owner'
                """
            ),
            {"company_id": company_id},
        ).scalars()
        for membership_id in owner_ids:
            _insert_grant(
                connection,
                company_id=company_id,
                docket_id=docket_id,
                membership_id=str(membership_id),
                reason="Migration snapshot of legacy owner visibility.",
            )

        if docket["assignee_membership_id"]:
            _insert_grant(
                connection,
                company_id=company_id,
                docket_id=docket_id,
                membership_id=str(docket["assignee_membership_id"]),
                reason="Migration snapshot of linked Matter assignee visibility.",
            )

        if team_scoped and not matter_restricted:
            _insert_grant(
                connection,
                company_id=company_id,
                docket_id=docket_id,
                team_id=str(docket["team_id"]),
                reason="Migration snapshot of linked Matter team visibility.",
            )

        if docket_restricted and not matter_restricted and not team_scoped:
            membership_ids = connection.execute(
                sa.text(
                    """
                    SELECT id
                      FROM company_memberships
                     WHERE company_id = :company_id AND is_active = true
                    """
                ),
                {"company_id": company_id},
            ).scalars()
            for membership_id in membership_ids:
                _insert_grant(
                    connection,
                    company_id=company_id,
                    docket_id=docket_id,
                    membership_id=str(membership_id),
                    reason="Migration snapshot of legacy linked-record visibility.",
                )


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE matter_access_grants AS access
               SET company_id = matters.company_id,
                   effective_from = access.created_at
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
                   effective_from = wall.created_at
              FROM matters
             WHERE wall.matter_id = matters.id
               AND wall.company_id IS NULL
            """
        )
    )
    snapshot_linked_ip_access(connection)
    connection.execute(
        sa.text(
            """
            UPDATE audit_events AS audit
               SET ip_docket_id = docket.id
              FROM ip_docket_records AS docket
             WHERE audit.ip_docket_id IS NULL
               AND audit.target_type = 'ip_docket_record'
               AND audit.target_id = docket.id
               AND audit.company_id = docket.company_id
            """
        )
    )


def downgrade() -> None:
    # Tenant correlation and the one-time policy snapshot are correct derived
    # facts. The switch downgrade removes IP-only rows before the old shape is
    # restored, so clearing Matter backfill values here would be less safe.
    pass
