from uuid import uuid4

import pytest
from sqlalchemy import event, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.db.models import Company, DocumentProcessingJob, utcnow
from caseops_api.services import document_jobs
from caseops_api.services import qa_document_quiescence as gate
from tests.fixtures_document_jobs import legacy_document_processing_receipt
from tests.test_matter_writer_admission_postgres import _fixture
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_qa_document_quiescence_20261015 import Clock

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def queue_sessions(http_pg_engine, monkeypatch):
    monkeypatch.setattr(gate, "get_session_factory", lambda: sessionmaker(bind=http_pg_engine))


def seed(engine, *, pending_index=None):
    fixtures = [_fixture(engine, active=False) for _ in range(4)]
    with Session(engine) as session:
        for index, (slug, fixture) in enumerate(
            zip(sorted(gate.QA_SLUGS), fixtures[:3], strict=True)
        ):
            session.get(Company, fixture.company).slug = slug
            if index != pending_index:
                legacy_document_processing_receipt(session, fixture.job, status="completed")
        session.commit()
    return fixtures


def test_quiescence_snapshot_bounds_history_and_excludes_non_qa(http_pg_engine):
    fixtures = seed(http_pg_engine)
    selected = fixtures[0]
    with Session(http_pg_engine) as session:
        job = session.get(DocumentProcessingJob, selected.job)
        retained = {
            "company_id": job.company_id,
            "requested_by_membership_id": job.requested_by_membership_id,
            "target_type": job.target_type,
            "attachment_id": job.attachment_id,
            "action": job.action,
            "status": "failed",
            "no_paid_providers": True,
        }
        session.execute(
            insert(DocumentProcessingJob), [dict(retained, id=str(uuid4())) for _ in range(2000)]
        )
        session.commit()
    sql = []
    event.listen(
        http_pg_engine,
        "before_cursor_execute",
        capture := lambda _c, _x, statement, *_: sql.append(statement),
    )
    try:
        ids, pending = gate._pending_snapshot()
    finally:
        event.remove(http_pg_engine, "before_cursor_execute", capture)
    assert set(ids) == {fixture.company for fixture in fixtures[:3]}
    assert pending is False  # The fourth tenant's valid queued job remains untouched.
    reads = [statement for statement in sql if statement.startswith("SELECT")]
    assert len(reads) == 2
    assert all("LIMIT" in statement for statement in reads)
    assert not any(statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in sql)
    with Session(http_pg_engine) as session:
        assert session.get(DocumentProcessingJob, fixtures[3].job).status == "queued"


def test_quiescence_releases_transactions_before_worker_completion(http_pg_engine, monkeypatch):
    fixtures = seed(http_pg_engine, pending_index=0)
    selected = fixtures[0]
    with Session(http_pg_engine) as session:
        assert document_jobs._claim_job(session, selected.job) is not None
        attempt = session.info["document_job_attempt"]
        session.rollback()
    clock = Clock()
    completed = []
    readers = []

    class ReadSession(Session):
        def close(self):
            super().close()
            self.info["closed"] = True

    def reader():
        session = ReadSession(http_pg_engine)
        readers.append(session)
        return session

    monkeypatch.setattr(gate, "get_session_factory", lambda: reader)

    def sleep(seconds):
        assert readers and all(
            not row.in_transaction() and row.info.get("closed") for row in readers
        )
        if not completed:
            with Session(http_pg_engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '100ms'"))
                session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
                document_jobs._set_attempt_context(session, attempt)
                job = session.get(DocumentProcessingJob, selected.job)
                job.status = "completed"
                job.completed_at = utcnow()
                job.processed_char_count = 23
                session.commit()
        completed.append(True)
        clock.value += seconds

    monkeypatch.setattr(gate, "time", clock)
    monkeypatch.setattr(clock, "sleep", sleep)
    receipt = gate.wait_for_qa_document_quiescence()
    assert receipt["polls"] == 3
    assert receipt["stable_observations"] == 2
    assert len(completed) == 2
    with Session(http_pg_engine) as session:
        assert (
            session.scalar(
                select(DocumentProcessingJob.status).where(
                    DocumentProcessingJob.id == selected.job,
                )
            )
            == "completed"
        )


@pytest.mark.parametrize("change", ["missing", "inactive"])
def test_quiescence_missing_or_inactive_qa_is_not_empty_success(http_pg_engine, change):
    fixture = seed(http_pg_engine)[0]
    with Session(http_pg_engine) as session:
        company = session.get(Company, fixture.company)
        if change == "missing":
            company.slug = "not-a-qa-tenant"
        else:
            company.is_active = False
        session.commit()
    with pytest.raises(RuntimeError, match="qa_document_tenant_inventory_changed"):
        gate._pending_snapshot()
