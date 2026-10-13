"""Fence post-index compliance tails without stamping historical runs.

Revision ID: 20261010_0004
Revises: 20261010_0003
DATA-GOVERNANCE-MAP: updated at integration by Main; adds only the nullable
matter_compliance_extraction_runs.persistence_protocol execution marker.
MIGRATION-LOCK-RISK: acknowledged: no scan, index build or backfill; ADD COLUMN
and trigger installation use env.py's dedicated bounded migration lock timeout.
An in-flight old run holding this table makes installation fail, not certify.
MIGRATION-ROLLBACK: restore-forward: application rollback retains both the
marker and database fence. Only an explicitly opted-in empty rehearsal may
remove them; any retained run refuses downgrade, including an unstamped run.
"""

import sqlalchemy as sa

from alembic import context, op

revision = "20261010_0004"
down_revision = "20261010_0003"
branch_labels = None
depends_on = None

FUNCTION_SQL = """
CREATE FUNCTION caseops_compliance_tail_protocol() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    context_text text;
    identity jsonb;
    attempt jsonb;
    expected_number integer;
    expected_start timestamptz;
BEGIN
    IF NEW.model_run_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.model_run_id IS DISTINCT FROM OLD.model_run_id)
       AND NOT EXISTS (
           SELECT 1 FROM public.model_runs WHERE id = NEW.model_run_id
           AND company_id = NEW.company_id AND matter_id = NEW.matter_id
           AND purpose = 'compliance_extraction'
       ) THEN
        RAISE EXCEPTION 'Compliance model provenance mismatch.' USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.id, NEW.company_id, NEW.matter_id, NEW.court_order_id,
               NEW.source_type, NEW.trigger, NEW.parser_version, NEW.source_hash,
               NEW.started_at, NEW.created_at, NEW.persistence_protocol)
           IS DISTINCT FROM
           ROW(OLD.id, OLD.company_id, OLD.matter_id, OLD.court_order_id,
               OLD.source_type, OLD.trigger, OLD.parser_version, OLD.source_hash,
               OLD.started_at, OLD.created_at, OLD.persistence_protocol) THEN
            RAISE EXCEPTION 'Compliance run provenance is immutable.' USING ERRCODE = '55000';
        END IF;
        IF NEW.attachment_id IS DISTINCT FROM OLD.attachment_id AND NOT (
            OLD.attachment_id IS NOT NULL AND NEW.attachment_id IS NULL
            AND NOT EXISTS (SELECT 1 FROM public.matter_attachments WHERE id = OLD.attachment_id)
        ) THEN
            RAISE EXCEPTION 'Compliance attachment provenance is immutable.'
                USING ERRCODE = '55000';
        END IF;
        IF NEW.created_by_membership_id IS DISTINCT FROM OLD.created_by_membership_id AND NOT (
            OLD.created_by_membership_id IS NOT NULL AND NEW.created_by_membership_id IS NULL
            AND NOT EXISTS (SELECT 1 FROM public.company_memberships
                            WHERE id = OLD.created_by_membership_id)
        ) THEN
            RAISE EXCEPTION 'Compliance actor provenance is immutable.' USING ERRCODE = '55000';
        END IF;
        IF TG_ARGV[0] = 'provenance' THEN
            RETURN NEW;
        END IF;
    END IF;
    IF NEW.persistence_protocol IS DISTINCT FROM 'compliance-tail-v1' THEN
        RAISE EXCEPTION 'Compliance run protocol is required.' USING ERRCODE = '55000';
    END IF;
    context_text := NULLIF(current_setting('caseops.compliance_tail', true), '');
    IF context_text IS NULL OR octet_length(context_text) > 4096 THEN
        RAISE EXCEPTION 'Compliance execution context is required.' USING ERRCODE = '55000';
    END IF;
    BEGIN
        identity := context_text::jsonb;
        IF jsonb_typeof(identity) IS DISTINCT FROM 'object'
           OR NOT identity ?& ARRAY['protocol', 'run_id', 'company_id', 'matter_id',
               'court_order_id', 'attachment_id', 'actor_membership_id', 'source_type',
               'trigger', 'source_hash', 'document_attempt']
           OR identity - ARRAY['protocol', 'run_id', 'company_id', 'matter_id',
               'court_order_id', 'attachment_id', 'actor_membership_id', 'source_type',
               'trigger', 'source_hash', 'document_attempt'] <> '{}'::jsonb
           OR EXISTS (SELECT 1 FROM jsonb_each(identity) AS field
                      WHERE field.key <> 'document_attempt'
                        AND jsonb_typeof(field.value) NOT IN ('string', 'null')) THEN
            RAISE EXCEPTION 'Invalid compliance execution context.';
        END IF;
        IF identity->>'protocol' IS DISTINCT FROM NEW.persistence_protocol
           OR identity->>'run_id' IS DISTINCT FROM NEW.id
           OR identity->>'company_id' IS DISTINCT FROM NEW.company_id
           OR identity->>'matter_id' IS DISTINCT FROM NEW.matter_id
           OR identity->>'court_order_id' IS DISTINCT FROM NEW.court_order_id
           OR identity->>'attachment_id' IS DISTINCT FROM NEW.attachment_id
           OR identity->>'actor_membership_id' IS DISTINCT FROM NEW.created_by_membership_id
           OR identity->>'source_type' IS DISTINCT FROM NEW.source_type
           OR identity->>'trigger' IS DISTINCT FROM NEW.trigger
           OR identity->>'source_hash' IS DISTINCT FROM NEW.source_hash THEN
            RAISE EXCEPTION 'Compliance execution identity mismatch.';
        END IF;
        attempt := identity->'document_attempt';
        IF jsonb_typeof(attempt) IS DISTINCT FROM 'null' THEN
            IF jsonb_typeof(attempt) IS DISTINCT FROM 'object'
               OR NOT attempt ?& ARRAY['id', 'attempt_count', 'started_at']
               OR attempt - ARRAY['id', 'attempt_count', 'started_at'] <> '{}'::jsonb
               OR jsonb_typeof(attempt->'id') IS DISTINCT FROM 'string'
               OR jsonb_typeof(attempt->'attempt_count') IS DISTINCT FROM 'number'
               OR attempt->>'attempt_count' !~ '^[1-9][0-9]*$'
               OR jsonb_typeof(attempt->'started_at') IS DISTINCT FROM 'string'
               OR attempt->>'started_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
                RAISE EXCEPTION 'Invalid compliance document attempt.';
            END IF;
            expected_number := (attempt->>'attempt_count')::integer;
            expected_start := (attempt->>'started_at')::timestamptz;
            IF NOT EXISTS (
                SELECT 1 FROM public.document_processing_jobs
                WHERE id = attempt->>'id' AND company_id = NEW.company_id
                  AND attachment_id = NEW.attachment_id AND target_type = 'matter_attachment'
                  AND status = 'completed' AND attempt_count = expected_number
                  AND started_at = expected_start
                  AND started_at > clock_timestamp() - interval '15 minutes'
            ) THEN
                RAISE EXCEPTION 'Compliance document attempt mismatch.';
            END IF;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'Compliance execution context rejected.' USING ERRCODE = '55000';
    END;
    IF NOT EXISTS (SELECT 1 FROM public.matters WHERE id = NEW.matter_id
                   AND company_id = NEW.company_id)
       OR (NEW.court_order_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM public.matter_court_orders WHERE id = NEW.court_order_id
           AND matter_id = NEW.matter_id
       ))
       OR (NEW.attachment_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM public.matter_attachments WHERE id = NEW.attachment_id
           AND matter_id = NEW.matter_id
       ))
       OR (NEW.created_by_membership_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM public.company_memberships WHERE id = NEW.created_by_membership_id
           AND company_id = NEW.company_id
       )) THEN
        RAISE EXCEPTION 'Compliance source scope mismatch.' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column(
        "matter_compliance_extraction_runs",
        sa.Column(
            "persistence_protocol",
            sa.String(length=32),
            nullable=True,
        ),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(FUNCTION_SQL)
    op.execute("""
        CREATE TRIGGER compliance_tail_execution
        BEFORE INSERT OR UPDATE OF status, skip_reason, completed_at,
                                   error_message_redacted, metadata_json
        ON matter_compliance_extraction_runs
        FOR EACH ROW EXECUTE FUNCTION caseops_compliance_tail_protocol('execution')
    """)
    op.execute("""
        CREATE TRIGGER compliance_tail_provenance
        BEFORE UPDATE ON matter_compliance_extraction_runs
        FOR EACH ROW EXECUTE FUNCTION caseops_compliance_tail_protocol('provenance')
    """)


def downgrade() -> None:
    opted_in = (
        context.get_x_argument(as_dictionary=True).get("compliance_tail_fresh_downgrade") == "true"
    )
    refusal = (
        "Compliance protocol must be retained; restore-forward. "
        "Only an empty rehearsal with -x compliance_tail_fresh_downgrade=true may downgrade."
    )
    if not opted_in:
        raise RuntimeError(refusal)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Keep env.py's bounded lock budget; hold through the check and DDL.
        bind.execute(
            sa.text("LOCK TABLE matter_compliance_extraction_runs IN ACCESS EXCLUSIVE MODE")
        )
    if bind.execute(sa.text("SELECT 1 FROM matter_compliance_extraction_runs LIMIT 1")).scalar():
        raise RuntimeError(refusal)
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER compliance_tail_execution ON matter_compliance_extraction_runs")
        op.execute("DROP TRIGGER compliance_tail_provenance ON matter_compliance_extraction_runs")
        op.execute("DROP FUNCTION caseops_compliance_tail_protocol()")
    op.drop_column("matter_compliance_extraction_runs", "persistence_protocol")
