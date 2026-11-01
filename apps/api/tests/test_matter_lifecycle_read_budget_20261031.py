"""Bound lifecycle hydration under real PostgreSQL fences, not historical latency."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import RelationshipProperty, Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterDeadline,
    MatterHearing,
    MatterNote,
    MatterTag,
    MatterTagAssignment,
    MatterTask,
    MatterTimeEntry,
    User,
)
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import matters
from tests.test_matter_writer_admission_postgres import (
    _ensure_migrations,  # noqa: F401
    _fixture,
    _mutate,
)
from tests.test_postgres_validation import _ip_race_context

pytestmark = pytest.mark.postgres

_HISTORY_ROWS = 3
_UNRELATED = {
    "tasks", "notes", "hearings", "activity_events", "cause_list_entries",
    "court_sync_runs", "court_sync_jobs", "attachments", "time_entries", "invoices",
}
_FENCES = (Company, CompanyMembership, User, Matter)
_HISTORY_COUNTS = {
    "matter_notes": 3,
    "matter_attachment_chunks": 3,
    "matter_time_entries": 3,
    "matter_attachments": 1,
    "matter_tags": 2,
    "matter_tag_assignments": 2,
    "matter_court_orders": 1,
}


def _timeouts(_session, transaction, connection):
    if transaction.parent is None:
        # Keep the canonical admission harness's original PostgreSQL limits.
        connection.execute(text("SET LOCAL statement_timeout = '15s'"))
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        connection.execute(text("SET LOCAL deadlock_timeout = '1s'"))


def _seed_history(engine):
    fixture = _fixture(engine)
    with Session(engine, expire_on_commit=False) as session:
        matter = session.get(Matter, fixture.matter)
        actor = session.get(CompanyMembership, fixture.actor)
        assert matter is not None and actor is not None
        assert (matter.status, matter.is_active, matter.lifecycle_version) == ("active", True, 0)
        fixture.user = actor.user_id
        matter.next_hearing_on = date(2026, 11, 15)
        matter.next_hearing_source = "manual"
        matter.next_hearing_manual_lock = True
        children = [
            MatterTask(
                company_id=fixture.company, matter_id=fixture.matter,
                created_by_membership_id=fixture.actor, owner_membership_id=fixture.actor,
                title="Lifecycle task", status="todo",
            ),
            MatterHearing(
                company_id=fixture.company, matter_id=fixture.matter,
                responsible_membership_id=fixture.actor, hearing_on=date(2026, 11, 15),
                forum_name="Lifecycle test forum", purpose="Listing", status="scheduled",
            ),
            MatterDeadline(
                company_id=fixture.company, matter_id=fixture.matter,
                created_by_membership_id=fixture.actor, source="manual", kind="filing",
                title="Lifecycle deadline", due_on=date(2026, 11, 15), status="open",
            ),
            MatterCourtSyncJob(
                company_id=fixture.company, matter_id=fixture.matter,
                requested_by_membership_id=fixture.actor, source="manual",
                status="queued", no_paid_providers=True,
            ),
        ]
        tags = [
            MatterTag(
                company_id=fixture.company, name=name, slug=slug, color_key=color,
                created_by_membership_id=fixture.actor,
            )
            for name, slug, color in (
                ("Zulu lifecycle", "lifecycle-zulu", "red"),
                ("alpha lifecycle", "lifecycle-alpha", "green"),
            )
        ]
        session.add_all(children + tags)
        for index in range(_HISTORY_ROWS):
            session.add_all([
                MatterNote(
                    matter_id=fixture.matter, author_membership_id=fixture.actor,
                    body=f"Retained lifecycle note {index}",
                    created_at=datetime(2026, 10, index + 1, tzinfo=UTC),
                ),
                MatterAttachmentChunk(
                    attachment_id=fixture.attachment, chunk_index=index,
                    content=f"Retained lifecycle document chunk {index}", token_count=6,
                ),
                MatterTimeEntry(
                    matter_id=fixture.matter, author_membership_id=fixture.actor,
                    work_date=date(2026, 10, index + 1),
                    description=f"Retained lifecycle time {index}",
                    duration_minutes=15, billable=False,
                ),
            ])
        session.add(MatterCourtOrder(
            matter_id=fixture.matter, order_date=date(2026, 10, 1),
            title="Retained lifecycle order", summary="Persisted DTO flag fixture",
            source="manual", order_kind="daily_order", is_interim_order=True,
            stay_status="granted",
        ))
        session.flush()
        session.add_all([
            MatterTagAssignment(
                company_id=fixture.company, matter_id=fixture.matter, tag_id=tag.id,
                created_by_membership_id=fixture.actor, source="manual",
            )
            for tag in tags
        ])
        fixture.children = [(type(child), child.id) for child in children]
        job = session.get(DocumentProcessingJob, fixture.job)
        assert job is not None and job.status == "queued"
        session.commit()
        fixture.updated = matter.updated_at
    return fixture


def _history(session, fixture):
    scopes = (
        (MatterNote, MatterNote.matter_id == fixture.matter),
        (MatterAttachmentChunk, MatterAttachmentChunk.attachment_id == fixture.attachment),
        (MatterTimeEntry, MatterTimeEntry.matter_id == fixture.matter),
        (MatterAttachment, MatterAttachment.id == fixture.attachment),
        (MatterTag, MatterTag.company_id == fixture.company),
        (MatterTagAssignment, MatterTagAssignment.matter_id == fixture.matter),
        (MatterCourtOrder, MatterCourtOrder.matter_id == fixture.matter),
    )
    return {
        model.__tablename__: [dict(row) for row in session.execute(
            select(model.__table__).where(scope).order_by(model.id)
        ).mappings()]
        for model, scope in scopes
    }


@contextmanager
def _read_inventory(session, tmp_path, record_property, operation):
    first_transaction = session.get_transaction()
    assert first_transaction is not None
    receipt = {"commits": 0, "rollbacks": 0, "events": []}
    held = []
    path = tmp_path / f"lifecycle-{operation}-relationship-loads.jsonl"
    record_property(f"matter_lifecycle_{operation}_read_inventory", str(path))
    with path.open("x", encoding="utf-8") as evidence:
        def record(kind, **values):
            row = {
                "kind": kind,
                "before_first_commit": receipt["commits"] == 0,
                "first_transaction": session.get_transaction() is first_transaction,
                "held_fences": list(held),
                **values,
            }
            receipt["events"].append(row)
            evidence.write(json.dumps(row, default=str, sort_keys=True) + "\n")
            evidence.flush()

        def execute(state):
            if not state.is_select:
                return None
            if state.is_relationship_load:
                relationships = [
                    part for part in state.loader_strategy_path.path
                    if isinstance(part, RelationshipProperty)
                ]
                record(
                    "relationship_load",
                    path=[f"{part.parent.class_.__name__}.{part.key}" for part in relationships],
                    unrelated=any(
                        part.parent.class_ is Matter and part.key in _UNRELATED
                        for part in relationships
                    ),
                )
            result = state.invoke_statement()
            lock = getattr(state.statement, "_for_update_arg", None)
            if lock is not None:
                for model in _FENCES:
                    if any(
                        description.get("entity") is model
                        for description in state.statement.column_descriptions
                    ):
                        if model.__name__ not in held:
                            held.append(model.__name__)
                        # Record only after the real PostgreSQL lock SELECT succeeded.
                        record(
                            "fence_acquired", model=model.__name__, read=lock.read,
                            key_share=lock.key_share,
                            targets=[table.name for table in (lock.of or ())],
                            parameters=state.statement.compile().params,
                        )
            return result

        def committed(_session):
            receipt["commits"] += 1
            record("after_commit")
            held.clear()

        def rolled_back(_session):
            receipt["rollbacks"] += 1
            record("after_rollback")
            held.clear()

        hooks = (
            ("do_orm_execute", execute),
            ("after_commit", committed),
            ("after_rollback", rolled_back),
        )
        for name, callback in hooks:
            options = {"retval": True} if name == "do_orm_execute" else {}
            event.listen(session, name, callback, **options)
        try:
            yield receipt
        finally:
            for name, callback in reversed(hooks):
                event.remove(session, name, callback)
            record("capture_finished")


def _assert_read_budget(receipt, fixture):
    events = receipt["events"]
    locks = [row for row in events if row["kind"] == "fence_acquired"
             and row["before_first_commit"]]
    first_locks = {}
    for row in locks:
        first_locks.setdefault(row["model"], row)
    assert list(first_locks) == [model.__name__ for model in _FENCES], locks
    identities = (fixture.company, fixture.actor, fixture.user, fixture.matter)
    for model, identity in zip(_FENCES, identities, strict=True):
        row = first_locks[model.__name__]
        assert row["first_transaction"] and not row["read"], row
        assert row["key_share"] is (model is Company), row
        assert row["targets"] == [model.__tablename__], row
        values = [
            item for value in row["parameters"].values()
            for item in (value if isinstance(value, (list, tuple)) else [value])
        ]
        assert identity in values, row
        if model in (CompanyMembership, Matter):
            assert fixture.company in values, row
    loads = [row for row in events if row["kind"] == "relationship_load"]
    assert all(row["path"] for row in loads), loads
    broad = [row for row in loads if row["before_first_commit"] and row["unrelated"]]
    assert all(
        row["first_transaction"] and row["held_fences"] == list(first_locks)
        for row in broad
    ), broad
    assert not broad, (
        "Unnecessary Matter workspace relationship loads before lifecycle commit", broad,
    )
    assert receipt["commits"] == 1 and receipt["rollbacks"] == 0, receipt
    assert any(row["kind"] == "after_commit" for row in events), receipt


def _assert_persisted(engine, fixture, result, history, *, status, version):
    with Session(engine) as check:
        context = _ip_race_context(
            check, company_id=fixture.company, membership_id=fixture.actor,
        )
        fresh = matters.get_matter(check, context=context, matter_id=fixture.matter)
        assert result.model_dump() == fresh.model_dump()
        assert (fresh.status, fresh.is_active, fresh.lifecycle_version) == (
            status, status != "disposed", version,
        )
        assert fresh.next_hearing_on is None and not fresh.next_hearing_manual_lock
        assert [tag.name for tag in fresh.tags] == ["alpha lifecycle", "Zulu lifecycle"]
        assert fresh.has_stay is True and fresh.has_interim_order is True
        assert _history(check, fixture) == history
        # The authorized full reader must still expose the retained child graph.
        row = matters._get_matter_model(check, context=context, matter_id=fixture.matter)
        assert (row.status, row.is_active, row.lifecycle_version) == (
            status, status != "disposed", version,
        )
        assert len(row.notes) == len(row.time_entries) == _HISTORY_ROWS
        assert len(row.attachments) == 1 and row.attachments[0].id == fixture.attachment
        assert len(row.attachments[0].chunks) == _HISTORY_ROWS
        neutralized = {}
        for model, identity in [*fixture.children, (DocumentProcessingJob, fixture.job)]:
            child = check.get(model, identity)
            assert child is not None and child.company_id == fixture.company
            assert child.status == (
                "failed" if model in (DocumentProcessingJob, MatterCourtSyncJob) else "cancelled"
            )
            if model in (MatterTask, MatterHearing, MatterDeadline):
                assert child.cancelled_by_matter_disposal is True
            if model is not MatterHearing:
                assert child.completed_at is not None
            if model in (DocumentProcessingJob, MatterCourtSyncJob):
                assert child.error_message == "Cancelled because the matter was disposed."
            neutralized[model.__tablename__] = {
                column.key: getattr(child, column.key) for column in model.__table__.columns
            }
        assert sorted(
            (activity.event_type, activity.actor_membership_id) for activity in row.activity_events
        ) == sorted([
            (event_type, fixture.actor)
            for event_type in ("matter_disposed", "matter_reopened")[:version]
        ])
        return neutralized


@pytest.mark.parametrize("autoflush", [False, True], ids=["autoflush-off", "autoflush-on"])
def test_lifecycle_avoids_unrelated_history_under_admission_locks(
    pg_engine, tmp_path, record_property, autoflush,
):
    assert pg_engine.dialect.name == "postgresql"
    fixture = _seed_history(pg_engine)
    with Session(pg_engine) as check:
        history = _history(check, fixture)
    assert {name: len(rows) for name, rows in history.items()} == _HISTORY_COUNTS

    with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
        event.listen(session, "after_begin", _timeouts)
        try:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor,
            )
            with _read_inventory(session, tmp_path, record_property, "dispose") as disposal_reads:
                disposed = _mutate(session, fixture, "dispose", context=context)
        finally:
            event.remove(session, "after_begin", _timeouts)
    _assert_read_budget(disposal_reads, fixture)
    neutralized = _assert_persisted(
        pg_engine, fixture, disposed, history, status="disposed", version=1,
    )

    with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
        event.listen(session, "after_begin", _timeouts)
        try:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor,
            )
            with _read_inventory(session, tmp_path, record_property, "reopen") as reopen_reads:
                reopened = matters.transition_matter_lifecycle_status(
                    session, context=context, matter_id=fixture.matter,
                    payload=MatterLifecycleStatusRequest(
                        to_status="intake", expected_from_status="disposed",
                        expected_updated_at=disposed.updated_at,
                        reason="Explicit controlled lifecycle reopen regression.",
                    ),
                )
        finally:
            event.remove(session, "after_begin", _timeouts)
    _assert_read_budget(reopen_reads, fixture)
    assert _assert_persisted(
        pg_engine, fixture, reopened, history, status="intake", version=2,
    ) == neutralized
