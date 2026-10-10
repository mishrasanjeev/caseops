"""Arbitrate document execution updates across legacy and current workers.

Revision ID: 20261010_0003
Revises: 20261010_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-ROLLBACK: restore-forward: retain execution/provenance guards on
application rollback. Only an explicit, locked-empty document and compliance
rehearsal may remove them; any retained receipt refuses before guard removal.
"""

import sqlalchemy as sa

from alembic import context, op

revision = "20261010_0003"
down_revision = "20261010_0002"
branch_labels = None
depends_on = None

FUNCTION_SQL = """
CREATE FUNCTION caseops_document_execution_protocol() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    identity jsonb;
    expected_start timestamptz;
    expected_number integer;
    context_text text;
BEGIN
    IF ROW(NEW.id, NEW.company_id, NEW.target_type, NEW.attachment_id,
           NEW.action, NEW.queued_at, NEW.no_paid_providers)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.company_id, OLD.target_type, OLD.attachment_id,
           OLD.action, OLD.queued_at, OLD.no_paid_providers) THEN
        RAISE EXCEPTION 'Document execution provenance is immutable.' USING ERRCODE = '55000';
    END IF;
    IF NEW.requested_by_membership_id IS DISTINCT FROM OLD.requested_by_membership_id
       AND NOT (OLD.requested_by_membership_id IS NOT NULL
                AND NEW.requested_by_membership_id IS NULL) THEN
        RAISE EXCEPTION 'Document execution requester is immutable.' USING ERRCODE = '55000';
    END IF;
    -- Execution's UPDATE OF trigger also fences identical-value final writes.
    -- Separate provenance checks allow FK SET NULL and timestamp bookkeeping.
    IF TG_ARGV[0] = 'provenance' THEN
        RETURN NEW;
    END IF;
    context_text := NULLIF(current_setting('caseops.document_job_attempt', true), '');
    IF context_text IS NULL THEN
        RAISE EXCEPTION 'Document execution context is required.' USING ERRCODE = '55000';
    END IF;
    BEGIN
        identity := context_text::jsonb;
        IF jsonb_typeof(identity) IS DISTINCT FROM 'object'
           OR jsonb_typeof(identity->'id') IS DISTINCT FROM 'string'
           OR jsonb_typeof(identity->'attempt_count') IS DISTINCT FROM 'number'
           OR (identity->>'attempt_count') !~ '^[0-9]+$'
           OR NOT (identity ? 'started_at')
           OR jsonb_typeof(identity->'started_at') NOT IN ('string', 'null') THEN
            RAISE EXCEPTION 'Invalid document execution context.';
        END IF;
        expected_number := (identity->>'attempt_count')::integer;
        expected_start := (identity->>'started_at')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'Invalid document execution context.' USING ERRCODE = '55000';
    END;
    IF (identity->>'id') IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'Document execution identity mismatch.' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'queued' AND NEW.status = 'processing'
       AND NEW.attempt_count = OLD.attempt_count + 1
       AND NEW.started_at IS NOT NULL AND NEW.completed_at IS NULL
       AND NEW.processed_char_count = 0 AND NEW.error_message IS NULL
       AND expected_number = NEW.attempt_count
       AND expected_start IS NOT DISTINCT FROM NEW.started_at THEN
        RETURN NEW;
    END IF;
    IF expected_number IS DISTINCT FROM OLD.attempt_count
       OR expected_start IS DISTINCT FROM OLD.started_at
       OR NEW.attempt_count IS DISTINCT FROM OLD.attempt_count THEN
        RAISE EXCEPTION 'Document execution attempt mismatch.' USING ERRCODE = '55000';
    END IF;
    IF identity->>'operation' = 'cancel' THEN
        IF OLD.status IN ('queued', 'processing') AND NEW.status = 'failed'
           AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
           AND NEW.processed_char_count = OLD.processed_char_count
           AND NEW.completed_at IS NOT NULL
           AND NEW.error_message = 'Cancelled because the matter was disposed.' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Document cancellation transition rejected.' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'processing' AND NEW.status = 'queued'
       AND NEW.started_at IS NULL AND NEW.completed_at IS NULL
       AND NEW.processed_char_count = OLD.processed_char_count
       AND NEW.error_message = 'Recovered stale processing job for retry.'
       AND (OLD.started_at <= clock_timestamp() - interval '15 minutes'
            OR (OLD.started_at IS NULL
                AND OLD.updated_at <= clock_timestamp() - interval '15 minutes')) THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'processing' AND OLD.started_at IS NOT NULL
       AND OLD.started_at > clock_timestamp() - interval '15 minutes'
       AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
       AND NEW.processed_char_count >= 0
       AND ((NEW.status IN ('completed', 'failed') AND NEW.completed_at IS NOT NULL)
            OR (NEW.status = 'processing' AND NEW.completed_at IS NULL)) THEN
        RETURN NEW;
    END IF;
    -- A completed indexing attempt may annotate a downstream compliance failure.
    IF OLD.status IN ('completed', 'failed') AND NEW.status = OLD.status
       AND OLD.started_at IS NOT NULL
       AND NEW.started_at IS NOT DISTINCT FROM OLD.started_at
       AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
       AND NEW.processed_char_count = OLD.processed_char_count THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Document execution transition rejected.' USING ERRCODE = '55000';
END;
$$;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(FUNCTION_SQL)
    op.execute("""
        CREATE TRIGGER document_execution_protocol
        BEFORE UPDATE OF status, attempt_count, started_at, completed_at,
                         processed_char_count, error_message ON document_processing_jobs
        FOR EACH ROW EXECUTE FUNCTION caseops_document_execution_protocol('execution')
    """)
    op.execute("""
        CREATE TRIGGER document_execution_provenance
        BEFORE UPDATE ON document_processing_jobs
        FOR EACH ROW EXECUTE FUNCTION caseops_document_execution_protocol('provenance')
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    refusal = (
        "Document execution protocol must be retained; restore-forward. "
        "Only an empty rehearsal with -x document_execution_fresh_downgrade=true may downgrade."
    )
    opted_in = context.get_x_argument(as_dictionary=True).get(
        "document_execution_fresh_downgrade"
    ) == "true"
    if not opted_in:
        raise RuntimeError(refusal)
    # Keep env.py's bounded migration lock budget through emptiness checks and DDL.
    for table in ("document_processing_jobs", "matter_compliance_extraction_runs"):
        bind.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in ("document_processing_jobs", "matter_compliance_extraction_runs"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).scalar():
            raise RuntimeError(refusal)
    op.execute("DROP TRIGGER document_execution_protocol ON document_processing_jobs")
    op.execute("DROP TRIGGER document_execution_provenance ON document_processing_jobs")
    op.execute("DROP FUNCTION caseops_document_execution_protocol()")
