"""Index existing public admissions without scheduling historical notifications.

Revision ID: 20261021_0001
Revises: 20261020_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; additive classification and index on the
existing enrollment table under the canonical migration lock/statement budgets.
An insert-only compatibility trigger uses the inserted row and, on SQLite,
one primary-key update; it never scans enrollment history on admission.
MIGRATION-ROLLBACK: roll-forward or restore only. Downgrade refuses before
changing classification, indexes, enrollment/outbox or commercial/audit records.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261021_0001"
down_revision = "20261020_0001"
branch_labels = None
depends_on = None
INDEX = "ix_billing_enrollments_public_lead_created_id"
BRIDGE_TRIGGER = "trg_billing_enrollments_legacy_public_lead_insert"
BRIDGE_FUNCTION = "caseops_classify_legacy_public_lead_insert"


def _public_proof(status, timestamps):
    return sa.or_(
        status == "demo_requested",
        timestamps["demo_admission"]["contract_version"]
        .as_string()
        .in_(["seo_demo_20261009", "legacy_public_demo_v1"]),
        # This original admission timestamp survives conversion.
        timestamps["demo_requested_at"].as_string().like("____-__-__T__:__:__%+00:00"),
    )


def _legacy_public_predicate(status, timestamps, dialect):
    proof = _public_proof(status, timestamps)
    if dialect.name == "postgresql":
        purpose_present = sa.cast(timestamps, JSONB)["demo_admission"].bool_op("?")(
            "notification_purpose"
        )
        return sa.and_(sa.not_(sa.func.coalesce(purpose_present, sa.false())), proof)
    # CASE guarantees malformed SQLite text never reaches JSON extraction.
    return sa.case(
        (timestamps.is_(None), status == "demo_requested"),
        (
            sa.func.json_valid(timestamps),
            sa.and_(
                sa.func.json_type(timestamps, "$.demo_admission.notification_purpose").is_(None),
                proof,
            ),
        ),
        else_=sa.false(),
    )


def _install_insert_bridge():
    bind = op.get_bind()
    proof = str(
        _legacy_public_predicate(
            sa.literal_column("NEW.status", type_=sa.String()),
            sa.literal_column("NEW.status_timestamps_json", type_=sa.JSON()),
            bind.dialect,
        ).compile(dialect=bind.dialect, compile_kwargs={"literal_binds": True})
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {BRIDGE_FUNCTION}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT NEW.is_public_lead
                   AND ({proof}) THEN
                    NEW.is_public_lead := true;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            f"CREATE TRIGGER {BRIDGE_TRIGGER} BEFORE INSERT ON billing_enrollments "
            f"FOR EACH ROW EXECUTE FUNCTION {BRIDGE_FUNCTION}()"
        )
    else:
        op.execute(
            f"""
            CREATE TRIGGER {BRIDGE_TRIGGER} AFTER INSERT ON billing_enrollments
            WHEN NEW.is_public_lead = 0 AND ({proof})
            BEGIN
                UPDATE billing_enrollments SET is_public_lead = 1 WHERE id = NEW.id;
            END
            """
        )


def upgrade():
    op.add_column(
        "billing_enrollments",
        sa.Column(
            "is_public_lead",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Earlier old-writer inserts are swept below; later ones meet this bridge.
    _install_insert_bridge()
    enrollments = sa.table(
        "billing_enrollments",
        sa.column("is_public_lead", sa.Boolean()),
        sa.column("status", sa.String()),
        sa.column("status_timestamps_json", sa.JSON()),
    )
    op.get_bind().execute(
        enrollments.update()
        .where(
            _legacy_public_predicate(
                enrollments.c.status, enrollments.c.status_timestamps_json, op.get_bind().dialect
            )
        )
        .values(is_public_lead=True)
    )
    op.create_index(INDEX, "billing_enrollments", ["is_public_lead", "created_at", "id"])


def downgrade():
    raise RuntimeError(
        "Public lead classification is retained release data; "
        "downgrade requires roll-forward or restore."
    )
