"""Pre-feature document receipt setup, independent of the consuming test modules."""

from sqlalchemy.orm import Session

from caseops_api.db.models import DocumentProcessingJob

__all__ = ("legacy_document_processing_receipt",)


def legacy_document_processing_receipt(session: Session, job_id: str, **state):
    # Insert legacy initial state; never disable the execution trigger or
    # invent authorization for an UPDATE forbidden to production callers.
    old = session.get(DocumentProcessingJob, job_id)
    assert old is not None and old.status == "queued" and old.attempt_count == 0
    values = {column.key: getattr(old, column.key)
              for column in DocumentProcessingJob.__table__.columns}
    session.delete(old)
    session.flush()
    job = DocumentProcessingJob(**(values | state))
    session.add(job)
    session.flush()
    return job
