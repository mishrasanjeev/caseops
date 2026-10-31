"""Provision default IP document classifications for enabled IP workspaces.

Revision ID: 20261031_0001
Revises: 20261026_0001
DATA-GOVERNANCE-MAP: updated
Map: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml (current_change_note).
Tenants whose IP workspace was enabled before default provisioning existed
have no document taxonomy, so every IP document upload fails. For each such
tenant with zero taxonomy entries this inserts the frozen default
classifications into the existing tenant-scoped ip_document_taxonomy_entries
and ip_document_taxonomy_aliases classes, attributed to the tenant's earliest
active owner membership, and records one audit event. A tenant that owns any
entry (custom, renamed or deactivated) is never touched; a tenant without an
active owner is skipped and logged. No DDL, provider transmission, retention
or disposition change. Re-running inserts nothing.
MIGRATION-ROLLBACK: restore-forward. downgrade() is a deliberate no-op: the
classifications are valid at the previous revision, belong to the tenant once
created and may already classify documents through a RESTRICT foreign key.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic import op

revision = "20261031_0001"
down_revision = "20261026_0001"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

TAXONOMY_VERSION = "ip-document-taxonomy-v1"
AUDIT_ACTION = "ip_document_taxonomy.defaults_provisioned"
ACTOR_LABEL = f"CaseOps release migration {revision}"
# Frozen copy of services.ip_documents.DEFAULT_TAXONOMY at this revision:
# (key, label, normalized alias). Later product changes must not alter it.
DEFAULT_TAXONOMY: tuple[tuple[str, str, str], ...] = (
    ("trademark_filing", "Trademark filing", "trademark filing"),
    ("examination", "Examination", "examination"),
    ("opposition", "Opposition", "opposition"),
    ("evidence", "Evidence", "evidence"),
    ("hearing", "Hearing", "hearing"),
    ("order", "Order", "order"),
    ("appeal", "Appeal", "appeal"),
    ("renewal", "Renewal", "renewal"),
    ("assignment", "Assignment", "assignment"),
    ("licence", "Licence", "licence"),
    ("correspondence", "Correspondence", "correspondence"),
    ("search", "Search", "search"),
    ("watch", "Watch", "watch"),
    ("invoice", "Invoice", "invoice"),
)

_entries = sa.table(
    "ip_document_taxonomy_entries",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("key", sa.String),
    sa.column("label", sa.String),
    sa.column("description", sa.Text),
    sa.column("sort_order", sa.Integer),
    sa.column("is_seeded", sa.Boolean),
    sa.column("is_active", sa.Boolean),
    sa.column("version", sa.Integer),
    sa.column("updated_by_membership_id", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_aliases = sa.table(
    "ip_document_taxonomy_aliases",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("taxonomy_entry_id", sa.String),
    sa.column("alias", sa.String),
    sa.column("normalized_alias", sa.String),
    sa.column("source", sa.String),
    sa.column("created_by_membership_id", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_audit_events = sa.table(
    "audit_events",
    sa.column("id", sa.String),
    sa.column("company_id", sa.String),
    sa.column("actor_type", sa.String),
    sa.column("actor_membership_id", sa.String),
    sa.column("actor_label", sa.String),
    sa.column("action", sa.String),
    sa.column("target_type", sa.String),
    sa.column("target_id", sa.String),
    sa.column("result", sa.String),
    sa.column("metadata_json", sa.Text),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

_TENANTS_WITHOUT_TAXONOMY = sa.text(
    """
    SELECT configuration.company_id
      FROM ip_workspace_configurations AS configuration
     WHERE configuration.workspace_enabled = :enabled
       AND NOT EXISTS (
           SELECT 1
             FROM ip_document_taxonomy_entries AS entry
            WHERE entry.company_id = configuration.company_id
       )
     ORDER BY configuration.company_id
    """
).bindparams(sa.bindparam("enabled", type_=sa.Boolean))
_EARLIEST_ACTIVE_OWNER = sa.text(
    """
    SELECT membership.id
      FROM company_memberships AS membership
      JOIN users AS member_user ON member_user.id = membership.user_id
     WHERE membership.company_id = :company_id
       AND membership.role = 'owner'
       AND membership.is_active = :active
       AND member_user.is_active = :active
     ORDER BY membership.created_at, membership.id
     LIMIT 1
    """
).bindparams(sa.bindparam("active", type_=sa.Boolean))
_HAS_TAXONOMY = sa.text(
    "SELECT 1 FROM ip_document_taxonomy_entries WHERE company_id = :company_id LIMIT 1"
)


def _provision(connection: sa.Connection, *, company_id: str, actor_id: str) -> None:
    now = datetime.now(UTC)
    entry_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []
    for sort_order, (key, label, normalized) in enumerate(DEFAULT_TAXONOMY, start=10):
        entry_id = str(uuid4())
        entry_rows.append(
            {
                "id": entry_id,
                "company_id": company_id,
                "key": key,
                "label": label,
                "description": f"CaseOps seeded {label.casefold()} document category.",
                "sort_order": sort_order,
                "is_seeded": True,
                "is_active": True,
                "version": 1,
                "updated_by_membership_id": actor_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        alias_rows.append(
            {
                "id": str(uuid4()),
                "company_id": company_id,
                "taxonomy_entry_id": entry_id,
                "alias": label,
                "normalized_alias": normalized,
                "source": "seed",
                "created_by_membership_id": actor_id,
                "created_at": now,
            }
        )
    connection.execute(_entries.insert(), entry_rows)
    connection.execute(_aliases.insert(), alias_rows)
    connection.execute(
        _audit_events.insert().values(
            id=str(uuid4()),
            company_id=company_id,
            actor_type="system",
            actor_membership_id=actor_id,
            actor_label=ACTOR_LABEL,
            action=AUDIT_ACTION,
            target_type="ip_document_taxonomy",
            target_id=company_id,
            result="success",
            metadata_json=json.dumps(
                {
                    "taxonomy_version": TAXONOMY_VERSION,
                    "keys": [key for key, _label, _normalized in DEFAULT_TAXONOMY],
                    "trigger": "release_backfill",
                    "migration_revision": revision,
                }
            ),
            created_at=now,
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    company_ids = list(
        connection.execute(_TENANTS_WITHOUT_TAXONOMY, {"enabled": True}).scalars()
    )
    for company_id in company_ids:
        actor_id = connection.execute(
            _EARLIEST_ACTIVE_OWNER, {"company_id": company_id, "active": True}
        ).scalar()
        if actor_id is None:
            logger.warning(
                "IP document taxonomy defaults skipped for company %s: "
                "no active owner membership to attribute them to.",
                company_id,
            )
            continue
        savepoint = connection.begin_nested()
        try:
            # Re-check inside the savepoint: an application request may have
            # provisioned this tenant since the candidate query ran.
            if connection.execute(_HAS_TAXONOMY, {"company_id": company_id}).first():
                savepoint.rollback()
                continue
            _provision(connection, company_id=company_id, actor_id=str(actor_id))
            savepoint.commit()
        except IntegrityError:
            # A concurrent provisioner won the (company_id, key) constraint;
            # its rows stand and this tenant needs nothing more.
            savepoint.rollback()
            logger.info(
                "IP document taxonomy defaults for company %s were provisioned concurrently.",
                company_id,
            )


def downgrade() -> None:
    # Deliberate no-op (restore-forward). Removing the rows would delete tenant
    # data that documents may already reference; the rows are valid at 20261026_0001.
    return None
