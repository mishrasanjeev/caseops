"""Bound attachment metadata hydration while preserving current source state.

Exercise PostgreSQL saves, no-ops, retained identities, complete DTO/workspace
responses, audit and notification provenance, and current authority fences.
Keep the real rich-loader control observable without changing product behavior.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, event, inspect, select
from sqlalchemy.orm import RelationshipProperty, Session
from sqlalchemy.sql import Select, operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList, TextClause
from sqlalchemy.sql.selectable import CompoundSelect, SelectStatementGrouping

from caseops_api.core.redaction import sanitize_audit_metadata
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    DocumentProcessingJob,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterCourtOrder,
    MatterDeadline,
    MatterNote,
    NotificationDeliveryIntent,
    Team,
    TeamMembership,
    User,
)
from caseops_api.schemas.document_processing import DocumentProcessingJobRecord
from caseops_api.schemas.matters import (
    MatterAttachmentMetadataUpdateRequest,
    MatterAttachmentRecord,
    MatterLifecycleStatusRequest,
)
from caseops_api.services import compliance_participants, matters
from tests.test_matter_metadata_load_profile_20261029_postgres import (
    profile_seed as _canonical_profile_seed,  # noqa: F401
)
from tests.test_matter_response_reload_20261029_postgres import (
    reload_seed as _canonical_reload_seed,  # noqa: F401
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
_WORKSPACE = {
    "tasks",
    "notes",
    "hearings",
    "activity_events",
    "tag_assignments",
    "cause_list_entries",
    "court_orders",
    "court_sync_runs",
    "court_sync_jobs",
    "attachments",
    "time_entries",
    "invoices",
}
_OLD_PATHS = Counter({(): 1, **{(key,): 1 for key in _WORKSPACE}})
_OLD_PATHS[("attachments", "chunks")] = 1
_CHILDREN = {inspect(Matter).relationships[key].mapper.class_ for key in _WORKSPACE}
_WATCHED = _CHILDREN | {Matter, MatterAttachmentChunk, CompanyMembership, User}
_HISTORY_TABLES = {inspect(model).local_table.name for model in _CHILDREN} - {
    "matter_attachments",
    "matter_court_orders",
}
_HISTORY_TABLES |= {
    inspect(Matter).relationships[parent].mapper.relationships[child].mapper.local_table.name
    for parent, child in (
        ("attachments", "chunks"),
        ("tag_assignments", "tag"),
        ("time_entries", "invoice_line_item"),
        ("invoices", "line_items"),
        ("invoices", "payment_attempts"),
    )
}
_META_COLUMNS = {
    "notice_reminder_offsets_json" if name == "notice_reminder_offsets" else name
    for name in MatterAttachmentMetadataUpdateRequest.model_fields
}
_TEXT = "The respondent shall file reply within 14 days from the date of this order."
_TAIL_CONTEXT_SELECT = "SELECT set_config('caseops.compliance_tail', :identity, true)"


@pytest.fixture
def offline_compliance(monkeypatch):
    # Direct-Session calls do not inherit the client fixture's mock settings.
    with monkeypatch.context() as offline:
        for key, value in {
            "CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED": "false",
            "CASEOPS_COMPLIANCE_AI_EXTRACTION_AUTO_RUN_ENABLED": "false",
            "CASEOPS_COMPLIANCE_AUTO_ACTIVATE_GENERATED_WORK_ENABLED": "false",
            "CASEOPS_LLM_PROVIDER": "mock",
            "CASEOPS_LLM_MODEL": "caseops-mock-1",
            "CASEOPS_LLM_MODEL_METADATA_EXTRACT": "caseops-mock-1",
            "CASEOPS_LLM_API_KEY": "",
            "CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED": "false",
        }.items():
            offline.setenv(key, value)
        get_settings.cache_clear()
        try:
            settings = get_settings()
            assert not settings.compliance_ai_extraction_enabled
            assert not settings.compliance_ai_extraction_auto_run_enabled
            assert not settings.compliance_auto_activate_generated_work_enabled
            assert settings.llm_provider == "mock" and not settings.llm_api_key
            assert not settings.notification_external_delivery_enabled
            yield
        finally:
            get_settings.cache_clear()


@pytest.fixture
def attachment_seed(request, pg_engine):
    seed = dict(request.getfixturevalue("_canonical_profile_seed"))
    with Session(pg_engine, expire_on_commit=False) as session:
        target = session.get(MatterAttachment, seed["attachment_id"])
        target.lifecycle_stage = "other"
        target.notice_subject = "Original subject"
        target.notice_response = "Retained response"
        target.sequence_index = 4
        sibling = MatterAttachment(
            matter_id=seed["matter_id"],
            original_filename="unrelated.txt",
            storage_key=f"attachment-profile/{uuid4()}",
            content_type="text/plain",
            size_bytes=9,
            sha256_hex=sha256(b"unrelated").hexdigest(),
            document_type="other",
        )
        foreign = MatterAttachment(
            matter_id=seed["foreign_matter_id"],
            original_filename="foreign.txt",
            storage_key=f"attachment-profile/{uuid4()}",
            content_type="text/plain",
            size_bytes=7,
            sha256_hex=sha256(b"foreign").hexdigest(),
            document_type="other",
        )
        session.add_all([sibling, foreign])
        session.flush()
        for attachment in (target, sibling):
            session.add(
                MatterAttachmentChunk(
                    attachment_id=attachment.id,
                    chunk_index=0,
                    content="Retained chunk",
                )
            )
        for index in range(1, 33):
            session.add(
                MatterAttachmentChunk(
                    attachment_id=sibling.id,
                    chunk_index=index,
                    content=f"Unrelated chunk {index}",
                )
            )
        job = DocumentProcessingJob(
            company_id=seed["company_id"],
            requested_by_membership_id=seed["actor_id"],
            target_type="matter_attachment",
            attachment_id=target.id,
            action="initial_index",
            status="queued",
            no_paid_providers=True,
        )
        session.add(job)
        foreign_matter = session.get(Matter, seed["foreign_matter_id"])
        seed["foreign_company_id"] = foreign_matter.company_id
        seed["foreign_actor_id"] = _seed_membership(
            session,
            foreign_matter.company_id,
            role="admin",
        )
        seed["other_uploader_id"] = _seed_membership(session, seed["company_id"])
        other_uploader = session.get(CompanyMembership, seed["other_uploader_id"])
        session.get(User, other_uploader.user_id).full_name = "Fresh attachment uploader"
        session.commit()
        seed.update(
            sibling_id=sibling.id,
            foreign_attachment_id=foreign.id,
            job_id=job.id,
            source_order_ids=(seed["order_id"],),
        )
    return seed


def _context(session, seed):
    return _ip_race_context(
        session,
        company_id=seed["company_id"],
        membership_id=seed["actor_id"],
    )


def _workspace(session, seed):
    return matters.get_matter_workspace(
        session,
        context=_context(session, seed),
        matter_id=seed["matter_id"],
    )


def _order_id_predicate(clause, compiled, parameters):
    # A matching UUID elsewhere in parameters is not a scoped CourtOrder read.
    # Require an id equality that bounds the whole WHERE (not one OR branch).
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return next(
            (
                value
                for part in clause.clauses
                if (value := _order_id_predicate(part, compiled, parameters)) is not None
            ),
            None,
        )
    if isinstance(clause, BinaryExpression) and clause.operator is operators.eq:
        for column, bound in ((clause.left, clause.right), (clause.right, clause.left)):
            if column.shares_lineage(MatterCourtOrder.__table__.c.id) and isinstance(
                bound, BindParameter
            ):
                name = compiled.bind_names.get(bound)
                value = parameters.get(name) if isinstance(parameters, Mapping) and name else None
                return value if isinstance(value, str) and len(value) == 36 else None
    return None


def _select_leaves(expression):
    if isinstance(expression, Select):
        return (expression,)
    if isinstance(expression, SelectStatementGrouping):
        return _select_leaves(expression.element)
    if isinstance(expression, CompoundSelect):
        branches = [_select_leaves(branch) for branch in expression.selects]
        if all(branches):
            return tuple(leaf for branch in branches for leaf in branch)
    return ()


@contextmanager
def _inventory(session, engine, tmp_path, record_property):
    # Adapt the validated 20261029 inventory: connection ownership, ORM paths,
    # paired SQL, phase/transaction attribution. Add resident-object refreshes.
    # Separate fixed caps accommodate the real compliance tail, not longer waits.
    receipt = dict(
        phase="prepare",
        sql=[],
        orm=[],
        objects=[],
        transactions=0,
        commits=0,
        rollbacks=0,
        overflow=False,
        finished=False,
    )
    owned, pending, active = [], [], {}

    def append(key, row, cap):
        if len(receipt[key]) >= cap:
            receipt["overflow"] = True
            return None
        row.update(phase=receipt["phase"], transaction=receipt["transactions"])
        receipt[key].append(row)
        return row

    def began(_session, transaction, connection):
        if transaction.parent is None:
            receipt["transactions"] += 1
            if len(owned) < 8:
                owned.append(connection)
            else:
                receipt["overflow"] = True

    def committed(_session):
        receipt["commits"] += 1

    def rolled_back(_session):
        receipt["rollbacks"] += 1

    def orm_select(state):
        leaves = _select_leaves(state.statement) if state.is_select else ()
        if leaves:
            row = append(
                "orm",
                dict(
                    path=[
                        part.key
                        for part in state.loader_strategy_path.path
                        if isinstance(part, RelationshipProperty)
                    ]
                    if state.is_relationship_load
                    else [],
                    matter_root=not state.is_relationship_load
                    and any(
                        item.get("expr") is Matter
                        for leaf in leaves
                        for item in leaf.column_descriptions
                    ),
                    paired=False,
                ),
                128,
            )
            if row is not None:
                pending.append(row)

    def before(connection, _cursor, sql, parameters, execution, _many):
        if not any(connection is item for item in owned):
            return
        expression = execution.compiled.statement if execution.compiled is not None else None
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
            return
        leaves = _select_leaves(expression)
        structured = bool(leaves)
        tables = (
            sorted(
                {
                    node.name
                    for leaf in leaves
                    for clause in leaf.get_final_froms()
                    for node in visitors.iterate(clause)
                    if isinstance(node, Table)
                }
            )
            if structured
            else []
        )
        # TextClause/driver SELECTs have no ORM producer and must never consume
        # the pending receipt for an enclosing ORM SELECT (e.g. during flush).
        orm = (
            next((row for row in reversed(pending) if not row["paired"]), None)
            if structured
            else None
        )
        if orm is not None:
            orm["paired"] = True
        encoded = sql.encode("utf-8")
        if len(encoded) > 32 * 1024:
            receipt["overflow"] = True
        row = append(
            "sql",
            dict(
                tables=tables,
                path=orm["path"] if orm else None,
                kind="structured" if structured else "textual_non_orm",
                compound=isinstance(expression, CompoundSelect),
                text_kind="compliance_tail_context"
                if isinstance(expression, TextClause) and expression.text == _TAIL_CONTEXT_SELECT
                else None,
                matter_root=orm["matter_root"] if orm else False,
                locking=structured and any(leaf._for_update_arg is not None for leaf in leaves),
                order_id_scope=_order_id_predicate(
                    expression.whereclause, execution.compiled, parameters
                )
                if isinstance(expression, Select) and "matter_court_orders" in tables
                else None,
                sql=sql if len(encoded) <= 32 * 1024 else None,
                completed=False,
                # Fixture-only identity predicates; never retain arbitrary parameters.
                target_ids=sorted(
                    {
                        value
                        for value in parameters.values()
                        if isinstance(value, str) and len(value) == 36
                    }
                )
                if isinstance(parameters, Mapping)
                else [],
            ),
            128,
        )
        if row is not None:
            active[id(execution)] = row

    def after(_connection, _cursor, _sql, _parameters, execution, _many):
        row = active.pop(id(execution), None)
        if row is not None:
            row["completed"] = True

    def loaded(_session, target):
        state = inspect(target)
        append(
            "objects",
            dict(
                kind="load",
                table=state.mapper.local_table.name,
                identity=list(state.identity or ()),
            ),
            256,
        )

    def refreshed(target, _context, _attrs):
        if inspect(target).session is session:
            state = inspect(target)
            append(
                "objects",
                dict(
                    kind="refresh",
                    table=state.mapper.local_table.name,
                    identity=list(state.identity or ()),
                ),
                256,
            )

    hooks = [
        (session, "after_begin", began),
        (session, "after_commit", committed),
        (session, "after_rollback", rolled_back),
        (session, "do_orm_execute", orm_select),
        (session, "loaded_as_persistent", loaded),
        (engine, "before_cursor_execute", before),
        (engine, "after_cursor_execute", after),
    ] + [(model, "refresh", refreshed) for model in _WATCHED]
    for target, name, callback in hooks:
        event.listen(target, name, callback)
    try:
        yield receipt
    finally:
        for target, name, callback in reversed(hooks):
            event.remove(target, name, callback)
        receipt["finished"] = True
        path = tmp_path / "attachment-metadata-inventory.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        record_property("attachment_metadata_inventory", str(path))


def _graph(receipt, *, first_only=False):
    return [
        row
        for row in receipt["sql"]
        if row["phase"] == "product"
        and (not first_only or row["transaction"] == 1)
        and (
            (row["path"] and row["path"][0] in _WORKSPACE)
            or (row["matter_root"] and not row["locking"] and len(row["tables"]) > 1)
        )
    ]


def _assert_work(receipt, seed, *, source=False, current_order_id=None):
    assert receipt["finished"] and not receipt["overflow"]
    assert all(row["paired"] for row in receipt["orm"]), receipt
    assert all(
        row["completed"]
        and (row["path"] is not None if row["kind"] == "structured" else row["path"] is None)
        for row in receipt["sql"]
    ), receipt
    assert not _graph(receipt), (
        "unused workspace graph",
        Counter(tuple(row["path"]) for row in _graph(receipt)),
        receipt,
    )
    product = [row for row in receipt["sql"] if row["phase"] == "product"]
    assert len(product) <= (112 if source else 32), product
    compounds = [row for row in product if row["compound"]]
    assert all(
        row["kind"] == "structured"
        and row["tables"] == ["company_memberships"]
        and row["path"] == []
        and not row["matter_root"]
        and not row["locking"]
        for row in compounds
    ), ("unexpected compound query", compounds)
    textual = [row for row in product if row["kind"] == "textual_non_orm"]
    assert len(textual) == (2 if source else 0), textual
    assert all(row["text_kind"] == "compliance_tail_context" for row in textual), textual
    assert not [row for row in product if _HISTORY_TABLES.intersection(row["tables"])], product
    attachment_reads = [row for row in product if "matter_attachments" in row["tables"]]
    assert attachment_reads and all(
        seed["attachment_id"] in row["target_ids"] for row in attachment_reads
    ), attachment_reads
    order_reads = [row for row in product if "matter_court_orders" in row["tables"]]
    assert len(order_reads) <= 4, order_reads
    for row in order_reads:
        if "matter_attachments" in row["tables"]:
            assert seed["attachment_id"] in row["target_ids"], row
        else:
            assert current_order_id is not None and row["order_id_scope"] == current_order_id, row
    parent_locks = [row for row in product if row["matter_root"] and row["locking"]]
    assert parent_locks and all(row["tables"] == ["matters"] for row in parent_locks)
    assert any(
        seed["company_id"] in row["target_ids"]
        and seed["matter_id"] in row["target_ids"]
        and "FOR UPDATE OF matters" in row["sql"]
        for row in parent_locks
    ), parent_locks
    for row in receipt["objects"]:
        if row["phase"] != "product":
            continue
        assert row["table"] not in _HISTORY_TABLES, row
        if row["table"] == "matter_attachments":
            assert row["identity"] == [seed["attachment_id"]], row
        if row["table"] == "matter_court_orders":
            assert current_order_id is not None and row["identity"] == [current_order_id], row
    order_objects = [
        row
        for row in receipt["objects"]
        if row["phase"] == "product" and row["table"] == "matter_court_orders"
    ]
    assert len(order_objects) <= 4, order_objects
    assert receipt["commits"] == 1 and receipt["rollbacks"] == 0, receipt
    assert any(row["transaction"] > 1 for row in product), product


def _columns(row):
    return {column.key: getattr(row, column.key) for column in inspect(type(row)).columns}


def _reference(value):
    return f"id:{sha256(value.encode('utf-8')).hexdigest()[:12]}" if value else None


def _stored(engine, seed):
    # Independent column oracle, not _attachment_record/_attachment_metadata_snapshot.
    with Session(engine) as session:
        row = session.get(MatterAttachment, seed["attachment_id"])
        columns = _columns(row)
        special = {
            "uploaded_by_name",
            "latest_job",
            "notice_reminder_offsets",
            "notice_reply_status",
            "notice_reply_days_remaining",
        }
        fields = set(MatterAttachmentRecord.model_fields) - special
        assert fields <= set(columns), "New attachment DTO field needs its own oracle."
        uploader_name = session.scalar(
            select(User.full_name)
            .join(
                CompanyMembership,
                CompanyMembership.user_id == User.id,
            )
            .where(CompanyMembership.id == row.uploaded_by_membership_id)
        )
        job = session.get(DocumentProcessingJob, seed["job_id"])
        job_fields = set(DocumentProcessingJobRecord.model_fields) - {"requested_by_name"}
        assert job_fields <= set(_columns(job))
        requester_name = session.scalar(
            select(User.full_name)
            .join(
                CompanyMembership,
                CompanyMembership.user_id == User.id,
            )
            .where(CompanyMembership.id == job.requested_by_membership_id)
        )
        dto = {name: columns[name] for name in fields}
        assert columns["document_type"] != "notice", (
            "Notice transitions stay in existing field tests."
        )
        assert columns["notice_reminder_offsets_json"] is None
        dto.update(
            uploaded_by_name=uploader_name,
            latest_job={
                **{name: getattr(job, name) for name in job_fields},
                "requested_by_name": requester_name,
            },
            notice_reminder_offsets=[7, 3, 1],
            notice_reply_status=None,
            notice_reply_days_remaining=None,
        )
        audits = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == seed["company_id"],
                    AuditEvent.target_id == row.id,
                    AuditEvent.action == "matter_attachment.metadata.updated",
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
                .limit(9)
            )
        )
        assert len(audits) <= 8
        activities = list(
            session.scalars(
                select(MatterActivity)
                .where(
                    MatterActivity.matter_id == seed["matter_id"],
                    MatterActivity.event_type == "attachment_metadata_updated",
                )
                .order_by(MatterActivity.created_at, MatterActivity.id)
                .limit(9)
            )
        )
        assert len(activities) <= 8
        attachments = list(
            session.scalars(
                select(MatterAttachment)
                .where(
                    MatterAttachment.id.in_([seed["sibling_id"], seed["foreign_attachment_id"]]),
                )
                .order_by(MatterAttachment.id)
                .limit(3)
            )
        )
        assert len(attachments) == 2
        chunks = list(
            session.scalars(
                select(MatterAttachmentChunk)
                .where(
                    MatterAttachmentChunk.attachment_id.in_(
                        [seed["attachment_id"], seed["sibling_id"]]
                    ),
                )
                .order_by(MatterAttachmentChunk.id)
                .limit(65)
            )
        )
        assert len(chunks) == 34
        assert 1 <= len(seed["source_order_ids"]) <= 2
        orders = list(
            session.scalars(
                select(MatterCourtOrder)
                .where(
                    MatterCourtOrder.id.in_(seed["source_order_ids"]),
                )
                .order_by(MatterCourtOrder.id)
                .limit(3)
            )
        )
        assert {order.id for order in orders} == set(seed["source_order_ids"])
        return dict(
            columns=columns,
            dto=dto,
            metadata={name: columns[name] for name in _META_COLUMNS},
            audits=[_columns(audit) for audit in audits],
            activities=[_columns(activity) for activity in activities],
            unrelated=[_columns(item) for item in attachments],
            chunks=[_columns(chunk) for chunk in chunks],
            orders={order.id: _columns(order) for order in orders},
        )


def _assert_output(engine, seed, response, before, *, changed):
    after = _stored(engine, seed)
    assert response.model_dump() == after["dto"]
    assert len(after["audits"]) == len(before["audits"]) + int(changed)
    assert after["audits"][: len(before["audits"])] == before["audits"]
    assert len(after["activities"]) == len(before["activities"]) + int(changed)
    assert after["activities"][: len(before["activities"])] == before["activities"]
    assert after["unrelated"] == before["unrelated"] and after["chunks"] == before["chunks"]
    assert after["orders"] == before["orders"]
    if changed:
        audit = after["audits"][-1]
        assert audit["actor_membership_id"] == seed["actor_id"]
        assert audit["matter_id"] == seed["matter_id"] and audit["result"] == "success"
        expected = sanitize_audit_metadata(
            dict(
                before=before["metadata"],
                after=after["metadata"],
                matter_code=None,
                filename=before["columns"]["original_filename"],
            )
        )
        with Session(engine) as session:
            expected["matter_code"] = session.get(Matter, seed["matter_id"]).matter_code
        assert json.loads(audit["metadata_json"]) == json.loads(json.dumps(expected, default=str))
    else:
        assert after == before
    return after


def _assert_workspace(session, engine, seed, response):
    workspace = _workspace(session, seed)
    assert {item.id for item in workspace.attachments} == {
        seed["attachment_id"],
        seed["sibling_id"],
    }
    assert next(item for item in workspace.attachments if item.id == response.id).model_dump() == (
        response.model_dump()
    )
    assert len(workspace.matter.tags) == 2 and len(workspace.court_orders) >= 1
    assert any(
        note.body == "Unrelated note must not be reloaded after commit." for note in workspace.notes
    )
    with Session(engine, expire_on_commit=False) as observer:
        expected = _workspace(observer, seed).model_dump()
    assert workspace.model_dump() == expected
    session.expire_all()
    assert _workspace(session, seed).model_dump() == expected


def test_attachment_metadata_avoids_unused_workspace_graph(
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
):
    """Primary source-RED: successful setup/save/DTO/audit, then unused-14 rejection."""
    seed = attachment_seed
    before = _stored(pg_engine, seed)
    with Session(pg_engine) as assignment_check:
        assert (
            assignment_check.get(Matter, seed["matter_id"]).assignee_membership_id
            == seed["actor_id"]
        )
    with Session(pg_engine, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            receipt["phase"] = "product"
            response = matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["matter_id"],
                attachment_id=seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(notice_subject="  Updated subject  "),
            )
        after = _assert_output(pg_engine, seed, response, before, changed=True)
        assert response.notice_subject == "Updated subject"
        assert after["metadata"] == {**before["metadata"], "notice_subject": "Updated subject"}
        _assert_workspace(session, pg_engine, seed, response)
        _assert_work(receipt, seed)
        assert sum(row["compound"] for row in receipt["sql"] if row["phase"] == "product") == 2


def test_team_metadata_counts_bounded_recipient_union_and_preserves_workspace(
    offline_compliance,
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
):
    seed = attachment_seed
    with Session(pg_engine) as setup:
        team = Team(
            company_id=seed["company_id"],
            name="Metadata team",
            slug=f"metadata-{uuid4().hex}",
            is_active=True,
        )
        setup.add(team)
        setup.flush()
        setup.add_all(
            [
                TeamMembership(team_id=team.id, membership_id=member_id)
                for member_id in (seed["actor_id"], seed["other_uploader_id"])
            ]
        )
        parent = setup.get(Matter, seed["matter_id"])
        parent.assignee_membership_id = None
        parent.team_id = team.id
        setup.commit()
    before = _stored(pg_engine, seed)
    with Session(pg_engine, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            receipt["phase"] = "product"
            response = matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["matter_id"],
                attachment_id=seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(notice_subject="Team metadata"),
            )
        _assert_output(pg_engine, seed, response, before, changed=True)
        assert response.notice_subject == "Team metadata"
        _assert_workspace(session, pg_engine, seed, response)
        _assert_work(receipt, seed)
        unions = [row for row in receipt["sql"] if row["phase"] == "product" and row["compound"]]
        assert len(unions) == 2 and all(row["tables"] == ["company_memberships"] for row in unions)


def test_work_oracle_rejects_non_recipient_compound_after_valid_save(
    offline_compliance,
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
):
    seed = attachment_seed
    before = _stored(pg_engine, seed)
    with Session(pg_engine, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            receipt["phase"] = "product"
            response = matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["matter_id"],
                attachment_id=seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(notice_subject="Compound control"),
            )
            prior_sql, prior_orm = len(receipt["sql"]), len(receipt["orm"])
            statement = select(Matter.id).where(
                Matter.id == seed["matter_id"],
                Matter.company_id == seed["company_id"],
            )
            assert session.execute(statement.union_all(statement)).all() == [
                (seed["matter_id"],),
                (seed["matter_id"],),
            ]
        _assert_output(pg_engine, seed, response, before, changed=True)
        _assert_workspace(session, pg_engine, seed, response)
        assert len(receipt["sql"]) == prior_sql + 1 and len(receipt["orm"]) == prior_orm + 1
        extra = receipt["sql"][-1]
        assert extra["completed"] and extra["compound"]
        assert extra["kind"] == "structured" and extra["tables"] == ["matters"]
        control = {**receipt, "sql": receipt["sql"][:prior_sql], "orm": receipt["orm"][:prior_orm]}
        _assert_work(control, seed)
        with pytest.raises(AssertionError, match="unexpected compound query"):
            _assert_work(receipt, seed)


@pytest.mark.parametrize(
    "warm,autoflush,expire,mode",
    [
        pytest.param(False, False, False, "change", id="cold-pending-no-autoflush-retained"),
        pytest.param(True, True, False, "change", id="warm-pending-autoflush-retained"),
        pytest.param(True, False, True, "empty", id="warm-pending-no-autoflush-expired-noop"),
        pytest.param(
            False, True, True, "normalized", id="cold-pending-autoflush-expired-normalized"
        ),
    ],
)
def test_pending_work_and_same_session_workspace(
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
    warm,
    autoflush,
    expire,
    mode,
):
    seed = attachment_seed
    before = _stored(pg_engine, seed)
    with Session(pg_engine, autoflush=autoflush, expire_on_commit=expire) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            retained = (
                matters._get_matter_model(
                    session,
                    context=context,
                    matter_id=seed["matter_id"],
                )
                if warm
                else None
            )
            held = (
                list(retained.attachments)
                + [chunk for item in retained.attachments for chunk in item.chunks]
                if warm
                else []
            )
            note = MatterNote(
                matter_id=seed["matter_id"],
                author_membership_id=seed["actor_id"],
                body="Pending attachment profile note",
            )
            session.add(note)
            receipt["phase"] = "product"
            response = matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["matter_id"],
                attachment_id=seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(
                    **(
                        {}
                        if mode == "empty"
                        else {
                            "notice_subject": " Original subject "
                            if mode == "normalized"
                            else "Pending-work subject",
                        }
                    )
                ),
            )
        _assert_output(pg_engine, seed, response, before, changed=mode == "change")
        with Session(pg_engine) as observer:
            assert note.id and observer.get(MatterNote, note.id).body == note.body
        assert not warm or held  # Keep real preloaded children alive through the measured call.
        _assert_workspace(session, pg_engine, seed, response)
        _assert_work(receipt, seed)


def test_work_oracle_rejects_exact_former_rich_graph(
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
):
    seed = attachment_seed
    before = _stored(pg_engine, seed)
    with Session(pg_engine, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            receipt["phase"] = "product"
            retained = matters._get_matter_model(
                session,
                context=context,
                matter_id=seed["matter_id"],
                lock_for_update=True,
            )
            assert {item.id for item in retained.attachments} == {
                seed["attachment_id"],
                seed["sibling_id"],
            }
        graph = _graph(receipt, first_only=True)
        assert len(graph) == 14 and Counter(tuple(row["path"]) for row in graph) == _OLD_PATHS
        with pytest.raises(AssertionError, match="unused workspace graph"):
            _assert_work(receipt, seed)
        session.rollback()
    assert _stored(pg_engine, seed) == before


@pytest.mark.parametrize("link", ["same", "replace", "clear"])
def test_retained_target_uses_committed_metadata_uploader_and_source(
    offline_compliance,
    pg_engine,
    attachment_seed,
    tmp_path,
    record_property,
    link,
):
    # AI and automatic activation are explicitly off; deterministic extraction,
    # admission, audit, and queued notification-intent persistence remain real.
    seed = attachment_seed
    with Session(pg_engine, expire_on_commit=False) as setup:
        target = setup.get(MatterAttachment, seed["attachment_id"])
        target.document_type = "order_judgment"
        target.linked_court_order_id = seed["order_id"]
        other = MatterCourtOrder(
            matter_id=seed["matter_id"],
            order_date=date(2026, 10, 3),
            title="Second retained source",
            summary="Valid source fixture",
            source="manual",
        )
        setup.add(other)
        setup.commit()
        other_id = other.id
        seed["source_order_ids"] = (seed["order_id"], other_id)
    with Session(pg_engine, expire_on_commit=False) as session:
        with _inventory(session, pg_engine, tmp_path, record_property) as receipt:
            context = _context(session, seed)
            retained = matters._get_matter_model(
                session, context=context, matter_id=seed["matter_id"]
            )
            target = next(item for item in retained.attachments if item.id == seed["attachment_id"])
            old_order = target.linked_court_order
            held_orders = list(retained.court_orders)
            held_chunks = [chunk for item in retained.attachments for chunk in item.chunks]
            assert old_order.id == seed["order_id"] and target.processing_status == "pending"
            with Session(pg_engine, expire_on_commit=False) as writer:
                actor = _context(writer, seed)
                compliance_participants.lock_compliance_participants(
                    writer,
                    company_id=seed["company_id"],
                    matter_id=seed["matter_id"],
                    actor_membership_id=seed["actor_id"],
                    context=actor,
                    required_capability="documents:manage",
                )
                fresh = writer.get(MatterAttachment, seed["attachment_id"])
                fresh.notice_response = "Committed competing response"
                fresh.uploaded_by_membership_id = seed["other_uploader_id"]
                fresh.extracted_text = _TEXT
                fresh.processing_status = "indexed"
                fresh.extracted_char_count = len(_TEXT)
                fresh.processed_at = datetime(2026, 10, 30, tzinfo=UTC)
                fresh.sha256_hex = sha256(_TEXT.encode()).hexdigest()
                fresh.size_bytes = len(_TEXT.encode())
                fresh.document_date = date(2026, 10, 8)
                fresh.linked_court_order_id = {
                    "same": seed["order_id"],
                    "replace": other_id,
                    "clear": None,
                }[link]
                for order_id in (seed["order_id"], other_id):
                    order = writer.get(MatterCourtOrder, order_id)
                    order.order_date = date(2026, 10, 12)
                    order.order_text = "Committed court-order source text"
                writer.commit()
            before = _stored(pg_engine, seed)
            receipt["phase"] = "product"
            response = matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["matter_id"],
                attachment_id=seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(notice_subject="Fresh-target edit"),
            )
        after = _assert_output(pg_engine, seed, response, before, changed=True)
        assert after["columns"] == {**before["columns"], "notice_subject": "Fresh-target edit"}
        assert target.extracted_text == _TEXT and target.processing_status == "indexed"
        assert response.uploaded_by_name == "Fresh attachment uploader"
        linked = target.linked_court_order
        assert (linked.id if linked else None) == before["columns"]["linked_court_order_id"]
        if linked is not None:
            assert _columns(linked) == before["orders"][linked.id]
        assert held_orders and held_chunks
        with Session(pg_engine) as observer:
            runs = list(
                observer.scalars(
                    select(MatterComplianceExtractionRun)
                    .where(
                        MatterComplianceExtractionRun.attachment_id == seed["attachment_id"],
                    )
                    .limit(3)
                )
            )
            assert len(runs) == 1 and runs[0].status == "completed"
            run = runs[0]
            current_order_id = before["columns"]["linked_court_order_id"]
            assert (run.company_id, run.matter_id, run.attachment_id, run.court_order_id) == (
                seed["company_id"],
                seed["matter_id"],
                seed["attachment_id"],
                current_order_id,
            )
            assert run.created_by_membership_id == seed["actor_id"]
            assert run.source_type == "manual_upload" and run.trigger == "manual_retry"
            assert run.completed_at is not None and run.skip_reason is None
            assert run.error_message_redacted is None and run.model_run_id is None
            assert run.source_hash == sha256(_TEXT.encode()).hexdigest()
            items = list(
                observer.scalars(
                    select(MatterComplianceItem)
                    .where(
                        MatterComplianceItem.extraction_run_id == run.id,
                    )
                    .order_by(MatterComplianceItem.id)
                    .limit(17)
                )
            )
            assert 0 < len(items) <= 16
            assert run.metadata_json["created_item_count"] == len(items)
            assert all(
                (
                    item.company_id,
                    item.matter_id,
                    item.attachment_id,
                    item.court_order_id,
                    item.extraction_run_id,
                    item.source_hash,
                    item.status,
                    item.review_status,
                )
                == (
                    seed["company_id"],
                    seed["matter_id"],
                    seed["attachment_id"],
                    current_order_id,
                    run.id,
                    run.source_hash,
                    "pending",
                    "review_required",
                )
                for item in items
            )
            base = linked.order_date if linked else date(2026, 10, 8)
            assert any(item.due_on == base + timedelta(weeks=2) for item in items)
            completed = list(
                observer.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.action == "matter_compliance.extraction.completed",
                        AuditEvent.target_id == run.id,
                    )
                    .limit(3)
                )
            )
            assert len(completed) == 1
            audit = completed[0]
            assert (
                audit.company_id,
                audit.matter_id,
                audit.target_type,
                audit.actor_membership_id,
                audit.actor_type,
                audit.result,
            ) == (
                seed["company_id"],
                seed["matter_id"],
                "matter_compliance_extraction_run",
                seed["actor_id"],
                "human",
                "success",
            )
            assert json.loads(audit.metadata_json) == {
                "status": "completed",
                "skip_reason": None,
                "created_item_count": len(items),
                "source_type": "manual_upload",
                "trigger": "manual_retry",
            }
            intents = list(
                observer.scalars(
                    select(NotificationDeliveryIntent)
                    .where(
                        NotificationDeliveryIntent.matter_id == seed["matter_id"],
                    )
                    .order_by(NotificationDeliveryIntent.id)
                    .limit(17)
                )
            )
            assert len(intents) == len(items)
            assert Counter(
                (intent.source_id, intent.recipient_membership_id) for intent in intents
            ) == (Counter({(item.id, seed["actor_id"]): 1 for item in items}))
            for intent in intents:
                assert (
                    intent.company_id,
                    intent.matter_id,
                    intent.channel,
                    intent.event_type,
                    intent.source_type,
                    intent.status,
                    intent.attempts,
                ) == (
                    seed["company_id"],
                    seed["matter_id"],
                    "in_app",
                    "compliance_review_required",
                    "matter_compliance_item",
                    "queued",
                    0,
                )
                assert (
                    intent.recipient_portal_user_id is None
                    and intent.recipient_external_ref is None
                )
                assert intent.ip_docket_id is None and intent.notification_rule_id is None
                assert intent.delivered_at is None and intent.failed_at is None
                assert intent.provider_event_id is None and intent.in_app_notification_id is None
                assert intent.dispatch_owner == "durable_intent"
                assert (intent.schedule_source_type, intent.schedule_source_id) == (
                    "matter_compliance_item",
                    intent.source_id,
                )
                assert intent.metadata_json == {
                    "notification_rule_ref": None,
                    "source_ref": _reference(intent.source_id),
                    "linked_court_order_ref": _reference(current_order_id),
                    "triggered_by_membership_ref": _reference(seed["actor_id"]),
                    "has_linked_court_order": current_order_id is not None,
                    "has_triggering_membership": True,
                }
                snapshot = intent.recipient_snapshot_json
                assert snapshot["target_type"] == "membership"
                assert snapshot["target_ref"] == seed["actor_id"]
                assert snapshot["destination"] is None and snapshot["channel"] == "in_app"
                assert snapshot["destination_version"] == intent.destination_version == 1
        _assert_workspace(session, pg_engine, seed, response)
        _assert_work(
            receipt, seed, source=True, current_order_id=before["columns"]["linked_court_order_id"]
        )


def _effects(engine, seed):
    with Session(engine) as session:
        result = {}
        for model in (
            MatterActivity,
            MatterDeadline,
            MatterComplianceExtractionRun,
            MatterComplianceItem,
            NotificationDeliveryIntent,
        ):
            rows = list(
                session.scalars(
                    select(model)
                    .where(
                        model.matter_id == seed["matter_id"],
                    )
                    .order_by(model.id)
                    .limit(65)
                )
            )
            assert len(rows) <= 64
            result[model.__name__] = [_columns(row) for row in rows]
        return result


@pytest.mark.parametrize(
    "denial",
    [
        "membership",
        "user",
        "capability",
        "foreign-matter",
        "foreign-attachment",
        "foreign-actor",
        "disposed",
    ],
)
def test_cached_authority_tenant_and_terminal_denial_preserve_attachment(
    pg_engine,
    attachment_seed,
    denial,
):
    seed = attachment_seed
    with Session(pg_engine, expire_on_commit=False) as session:
        context = _context(session, seed)
        retained = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        target = next(item for item in retained.attachments if item.id == seed["attachment_id"])
        with Session(pg_engine, expire_on_commit=False) as writer:
            actor = writer.get(CompanyMembership, seed["actor_id"])
            if denial == "membership":
                actor.is_active = False
            elif denial == "user":
                writer.get(User, actor.user_id).is_active = False
            elif denial == "capability":
                actor.role = "viewer"
            elif denial == "disposed":
                parent = writer.get(Matter, seed["matter_id"])
                matters.transition_matter_lifecycle_status(
                    writer,
                    context=_context(writer, seed),
                    matter_id=seed["matter_id"],
                    payload=MatterLifecycleStatusRequest(
                        to_status="disposed",
                        expected_from_status=parent.status,
                        expected_updated_at=parent.updated_at,
                        reason="Attachment profile terminal-state boundary",
                    ),
                )
            writer.commit()
        before, effects = _stored(pg_engine, seed), _effects(pg_engine, seed)
        if denial == "foreign-actor":
            context = _ip_race_context(
                session,
                company_id=seed["foreign_company_id"],
                membership_id=seed["foreign_actor_id"],
            )
        with pytest.raises(HTTPException) as rejected:
            matters.update_matter_attachment_metadata(
                session,
                context=context,
                matter_id=seed["foreign_matter_id"]
                if denial == "foreign-matter"
                else seed["matter_id"],
                attachment_id=seed["foreign_attachment_id"]
                if denial == "foreign-attachment"
                else seed["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(notice_subject="Must never persist"),
            )
        assert rejected.value.status_code == (
            404 if denial.startswith("foreign-") else 409 if denial == "disposed" else 403
        )
        session.rollback()
        assert target.id == seed["attachment_id"]
    assert _stored(pg_engine, seed) == before
    assert _effects(pg_engine, seed) == effects
    if denial == "disposed":
        with Session(pg_engine) as observer:
            parent = observer.get(Matter, seed["matter_id"])
            assert parent.status == "disposed" and parent.is_active is False


@pytest.mark.parametrize("autoflush", [False, True])
def test_workspace_reader_refreshes_committed_children_without_metadata_write(
    pg_engine,
    attachment_seed,
    autoflush,
):
    seed = attachment_seed
    with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
        context = _context(session, seed)
        retained = matters._get_matter_model(
            session,
            context=context,
            matter_id=seed["matter_id"],
        )
        held = list(retained.court_orders)
        previous = next(order for order in held if order.id == seed["order_id"])
        old_title = previous.title
        assert old_title != "Committed workspace-only order"
        assert not (session.new or session.dirty or session.deleted)
        with Session(pg_engine) as writer:
            order = writer.get(MatterCourtOrder, seed["order_id"])
            order.title = "Committed workspace-only order"
            order.order_date = date(2026, 10, 29)
            order.order_text = "Committed workspace-only source text"
            writer.commit()
        assert previous.title == old_title, "Establish the retained stale-child state."
        assert session.get(MatterCourtOrder, seed["order_id"]) is previous
        with Session(pg_engine, expire_on_commit=False) as observer:
            expected = _workspace(observer, seed).model_dump()
        expected_order = next(
            order for order in expected["court_orders"] if order["id"] == seed["order_id"]
        )
        assert expected_order["title"] == "Committed workspace-only order"
        actual = _workspace(session, seed).model_dump()
        actual_order = next(
            order for order in actual["court_orders"] if order["id"] == seed["order_id"]
        )
        assert actual_order["title"] == "Committed workspace-only order"
        assert actual == expected
        assert held and previous.title == "Committed workspace-only order"


@pytest.mark.parametrize(
    "mode",
    [
        "parent",
        "order",
        "new_note",
        "deleted_note",
        "collection_add",
        "collection_remove",
    ],
)
@pytest.mark.parametrize("autoflush,suppress", [(False, False), (True, False), (True, True)])
def test_workspace_read_preserves_pending_work_and_caller_rollback(
    pg_engine,
    attachment_seed,
    mode,
    autoflush,
    suppress,
):
    seed = attachment_seed
    with Session(pg_engine, autoflush=autoflush, expire_on_commit=False) as session:
        context = _context(session, seed)
        parent = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        order = next(row for row in parent.court_orders if row.id == seed["order_id"])
        note = parent.notes[0]
        original = (parent.title, order.title, tuple(row.id for row in parent.notes))
        transaction = session.get_transaction()
        pending = None
        if mode == "parent":
            parent.title = "Caller-owned pending Matter title"
        elif mode == "order":
            order.title = "Caller-owned pending order title"
        elif mode in {"new_note", "collection_add"}:
            pending = MatterNote(
                id=str(uuid4()),
                matter_id=seed["matter_id"],
                author_membership_id=seed["actor_id"],
                body="Caller-owned pending note",
                created_at=datetime.now(UTC),
            )
            if mode == "collection_add":
                pending.author_membership = context.membership
                parent.notes.append(pending)
            else:
                session.add(pending)
        elif mode == "deleted_note":
            session.delete(note)
        else:
            parent.notes.remove(note)
        assert session.new or session.dirty or session.deleted
        history = inspect(parent).attrs.notes.history
        before_history = (tuple(history.added), tuple(history.deleted))
        events = Counter()
        refresh_options = []

        def flushed(*_args):
            events["flush"] += 1

        def committed(*_args):
            events["commit"] += 1

        def rolled_back(*_args):
            events["rollback"] += 1

        def read(state):
            if (
                state.is_select
                and not state.is_relationship_load
                and any(row.get("expr") is Matter for row in state.statement.column_descriptions)
            ):
                refresh_options.append(bool(state.execution_options.get("populate_existing")))

        hooks = [
            ("before_flush", flushed),
            ("after_commit", committed),
            ("after_rollback", rolled_back),
            ("do_orm_execute", read),
        ]
        for name, callback in hooks:
            event.listen(session, name, callback)
        try:
            with session.no_autoflush if suppress else nullcontext():
                workspace = matters.get_matter_workspace(
                    session,
                    context=context,
                    matter_id=seed["matter_id"],
                )
        finally:
            for name, callback in reversed(hooks):
                event.remove(session, name, callback)
        should_flush = autoflush and not suppress
        assert events == Counter({"flush": 1}) if should_flush else not events
        assert refresh_options == [False]
        assert session.get_transaction() is transaction
        if mode == "parent":
            assert parent.title == workspace.matter.title == "Caller-owned pending Matter title"
        elif mode == "order":
            assert order.title == "Caller-owned pending order title"
            assert (
                next(row for row in workspace.court_orders if row.id == order.id).title
                == order.title
            )
        if not should_flush:
            after_history = inspect(parent).attrs.notes.history
            assert (tuple(after_history.added), tuple(after_history.deleted)) == before_history
            if pending is not None:
                assert pending in session.new
            if mode == "deleted_note":
                assert note in session.deleted
        with Session(pg_engine) as observer:
            assert observer.get(Matter, seed["matter_id"]).title == original[0]
            assert observer.get(MatterCourtOrder, seed["order_id"]).title == original[1]
            assert set(
                observer.scalars(
                    select(MatterNote.id).where(
                        MatterNote.matter_id == seed["matter_id"],
                    )
                )
            ) == set(original[2])
        session.rollback()
        assert session.get_transaction() is None
    with Session(pg_engine) as observer:
        assert observer.get(Matter, seed["matter_id"]).title == original[0]
        assert observer.get(MatterCourtOrder, seed["order_id"]).title == original[1]
        assert set(
            observer.scalars(
                select(MatterNote.id).where(
                    MatterNote.matter_id == seed["matter_id"],
                )
            )
        ) == set(original[2])


def test_workspace_read_keeps_pending_values_for_explicit_caller_commit(pg_engine, attachment_seed):
    seed = attachment_seed
    with Session(pg_engine, autoflush=False, expire_on_commit=False) as session:
        context = _context(session, seed)
        parent = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        parent.title = "Explicit caller workspace commit"
        note = MatterNote(
            matter_id=seed["matter_id"],
            author_membership_id=seed["actor_id"],
            body="Explicit caller note commit",
        )
        session.add(note)
        transaction = session.get_transaction()
        workspace = matters.get_matter_workspace(
            session,
            context=context,
            matter_id=seed["matter_id"],
        )
        assert workspace.matter.title == parent.title == "Explicit caller workspace commit"
        assert parent in session.dirty and note in session.new
        assert session.get_transaction() is transaction
        session.commit()
        note_id = note.id
    with Session(pg_engine) as observer:
        assert observer.get(Matter, seed["matter_id"]).title == "Explicit caller workspace commit"
        assert observer.get(MatterNote, note_id).body == "Explicit caller note commit"


def test_workspace_read_preserves_flushed_savepoint_rollback(pg_engine, attachment_seed):
    seed = attachment_seed
    with Session(pg_engine, autoflush=False, expire_on_commit=False) as session:
        context = _context(session, seed)
        parent = matters._get_matter_model(session, context=context, matter_id=seed["matter_id"])
        order = next(row for row in parent.court_orders if row.id == seed["order_id"])
        original, outer = order.title, session.get_transaction()
        nested = session.begin_nested()
        order.title = "Savepoint-owned workspace title"
        session.flush()
        assert not (session.new or session.dirty or session.deleted)
        workspace = matters.get_matter_workspace(
            session,
            context=context,
            matter_id=seed["matter_id"],
        )
        assert (
            next(row for row in workspace.court_orders if row.id == order.id).title == order.title
        )
        assert order.title == "Savepoint-owned workspace title"
        assert session.get_transaction() is outer and session.get_nested_transaction() is nested
        with Session(pg_engine) as observer:
            assert observer.get(MatterCourtOrder, order.id).title == original
        nested.rollback()
        assert session.get_transaction() is outer and session.get_nested_transaction() is None
        restored = matters.get_matter_workspace(
            session,
            context=context,
            matter_id=seed["matter_id"],
        )
        assert next(row for row in restored.court_orders if row.id == order.id).title == original


def test_workspace_reader_rechecks_retained_assignee_eligibility(pg_engine, attachment_seed):
    seed = attachment_seed
    with Session(pg_engine, autoflush=False, expire_on_commit=False) as session:
        context = _context(session, seed)
        held_membership = session.get(CompanyMembership, seed["other_uploader_id"])
        held_user = held_membership.user
        assert held_membership.is_active and held_user.is_active
        old_name = held_user.full_name
        assert not (session.new or session.dirty or session.deleted)
        with Session(pg_engine) as writer:
            user = writer.get(User, held_user.id)
            user.is_active = False
            user.full_name = "Committed workspace-only colleague"
            writer.commit()
        assert held_user.is_active and held_user.full_name == old_name
        with Session(pg_engine, expire_on_commit=False) as observer:
            expected = _workspace(observer, seed).model_dump()
        assert seed["other_uploader_id"] not in {
            row["membership_id"] for row in expected["available_assignees"]
        }
        actual = matters.get_matter_workspace(
            session,
            context=context,
            matter_id=seed["matter_id"],
        )
        assert seed["other_uploader_id"] not in {
            row.membership_id for row in actual.available_assignees
        }
        assert actual.model_dump() == expected
        assert not held_user.is_active
        assert held_user.full_name == "Committed workspace-only colleague"
