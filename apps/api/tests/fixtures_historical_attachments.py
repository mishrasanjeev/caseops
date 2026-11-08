"""Attachment setup for the dated document protocol fixtures."""

import json
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text
from sqlalchemy.orm import defer, sessionmaker
from sqlalchemy.sql.selectable import Select

from caseops_api.db.models import MatterAttachment, utcnow

NATIVE_ATTACHMENT_COLUMN = "native_local_processing_only"
HISTORICAL_ATTACHMENT_LOAD = defer(MatterAttachment.native_local_processing_only, raiseload=True)


def seed_historical_attachment(
    session, *, matter_id, uploaded_by_membership_id, original_filename,
    storage_key, content_type, size_bytes, sha256_hex, document_type=None,
):
    """Write the exact pre-provenance columns without using today's ORM defaults."""
    attachment_id = str(uuid4())
    session.flush()
    session.execute(text("""
        INSERT INTO matter_attachments (
            id, matter_id, uploaded_by_membership_id, original_filename,
            storage_key, content_type, size_bytes, sha256_hex, document_type,
            processing_status, extracted_char_count, notice_currency,
            notice_reply_required, notice_reply_sent, notice_document_role, created_at
        ) VALUES (
            :id, :matter_id, :uploader, :filename, :storage_key, :content_type,
            :size_bytes, :sha256_hex, :document_type,
            'pending', 0, 'INR', false, false, 'notice', :created_at
        )
    """), {
        "id": attachment_id, "matter_id": matter_id, "uploader": uploaded_by_membership_id,
        "filename": original_filename, "storage_key": storage_key, "content_type": content_type,
        "size_bytes": size_bytes, "sha256_hex": sha256_hex, "document_type": document_type,
        "created_at": utcnow(),
    })
    return attachment_id


def historical_attachment_sessions(engine):
    """Defer the absent column only in the frozen worker's own Sessions."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def load_historical_attachment(state):
        if not state.is_select or not isinstance(state.statement, Select):
            return
        if any(
            row.get("entity") is MatterAttachment and row.get("expr") is MatterAttachment
            for row in state.statement.column_descriptions
        ):
            state.statement = state.statement.options(HISTORICAL_ATTACHMENT_LOAD)

    event.listen(factory, "do_orm_execute", load_historical_attachment)
    return factory


def project_current_worker_attachment_column(engine, cfg, *, historical_revision):
    """Use the real new column only for current-worker tests of an older protocol."""
    revision_sql = text("SELECT version_num FROM alembic_version")
    migration = ScriptDirectory.from_config(cfg).get_revision("20261108_0003")
    with engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        revision = connection.scalar(revision_sql)
        assert revision == historical_revision
        before = {
            column["name"] for column in inspect(connection).get_columns("matter_attachments")
        }
        assert NATIVE_ATTACHMENT_COLUMN not in before
        with Operations.context(MigrationContext.configure(connection)):
            migration.module.upgrade()
        after = {
            column["name"]: column
            for column in inspect(connection).get_columns("matter_attachments")
        }
        assert set(after) == before | {NATIVE_ATTACHMENT_COLUMN}
        assert after[NATIVE_ATTACHMENT_COLUMN]["nullable"] is False
        assert str(after[NATIVE_ATTACHMENT_COLUMN]["type"]) == "BOOLEAN"
        retained_native = connection.scalar(text(
            "SELECT count(*) FROM matter_attachments WHERE native_local_processing_only"
        ))
        assert retained_native == 0
        retained_revision = connection.scalar(revision_sql)
        assert retained_revision == historical_revision
    print(json.dumps({
        "event": "fixture_current_worker_attachment_schema_projection",
        "historical_revision": historical_revision,
        "projected_migration": migration.revision,
        "retained_catalogue_test": False,
    }))
