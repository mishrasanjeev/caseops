"""IPLF-032/UJ-02: unused import hydration, public DTO and transaction parity.

The bulk oracle bounds discarded response work, not historical timing causes.
The original import deadlines and public transaction semantics remain unchanged.
"""

import json
from collections import Counter
from contextlib import contextmanager
from threading import local
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, event, select
from sqlalchemy.sql import visitors

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    IpAsset,
    IpDocketRecord,
    IpIdentifier,
    IpImportRow,
    IpTrademarkParticularVersion,
    TrademarkApplication,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.schemas.ip_operations import (
    IpDocketCreateRequest,
    IpDocketRecordResponse,
)
from caseops_api.services import ip_imports, ip_operations
from caseops_api.services.ip_nice_classes import nice_catalogue_in_force
from caseops_api.services.session_context import SessionContext
from tests.sql_observation import is_read_only_select
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload

pytestmark = pytest.mark.postgres

_RICH_TABLES = (
    "ip_trademark_particular_versions",
    "company_notice_ip_links",
    "ip_evidence_candidates",
    "ip_deadline_coverages",
    "ip_deadline_incidents",
    "ip_title_interests",
    "ip_related_right_obligations",
    "ip_cost_items",
    "ip_cost_item_corrections",
)
_FACT_MODELS = (
    IpDocketRecord, IpTrademarkParticularVersion, IpAsset,
    TrademarkApplication, IpIdentifier,
)
_IMPORT_ACTIONS = (
    "ip_docket.created", "ip_docket.source_materialized",
    "ip_asset.created", "ip_application.created", "ip.import.committed",
)


@contextmanager
def _rich_probe(monkeypatch):
    """Observe the real rich path, without changing results or transaction policy."""
    engine = get_engine()
    assert engine.dialect.name == "postgresql"
    state = local()
    probe = {"serializer_ids": [], "loads": [], "queries": [], "overflow": False}
    real_serialize = ip_operations._serialize_docket
    real_load = ip_operations._load_docket_serialization_rows

    def serialize(session, docket, **kwargs):
        if len(probe["serializer_ids"]) < 16:
            probe["serializer_ids"].append(docket.id)
        else:
            probe["overflow"] = True
        return real_serialize(session, docket, **kwargs)

    def load(session, *, company_id, docket_ids):
        record = {"company_id": company_id, "docket_ids": list(docket_ids)}
        if len(probe["loads"]) < 16:
            probe["loads"].append(record)
        else:
            probe["overflow"] = True
        previous = getattr(state, "load", None)
        state.load = record
        try:
            return real_load(session, company_id=company_id, docket_ids=docket_ids)
        finally:
            state.load = previous

    def before(connection, cursor, statement, parameters, context, executemany):
        current = getattr(state, "load", None)
        if current is None:
            return
        if len(probe["queries"]) >= 128:
            probe["overflow"] = True
            return
        clause = getattr(getattr(context, "compiled", None), "statement", None)
        tables = sorted({
            node.name for node in visitors.iterate(clause) if isinstance(node, Table)
        }) if clause is not None else []
        record = {
            "docket_ids": current["docket_ids"],
            "tables": tables,
            "read_only": is_read_only_select(clause),
            "completed": False,
        }
        probe["queries"].append(record)
        context.ip_import_rich_probe_record = record

    def after(connection, cursor, statement, parameters, context, executemany):
        record = getattr(context, "ip_import_rich_probe_record", None)
        if record is not None:
            record["completed"] = True
            del context.ip_import_rich_probe_record

    with monkeypatch.context() as patch:
        patch.setattr(ip_operations, "_serialize_docket", serialize)
        patch.setattr(ip_operations, "_load_docket_serialization_rows", load)
        event.listen(engine, "before_cursor_execute", before)
        try:
            event.listen(engine, "after_cursor_execute", after)
            try:
                yield probe
            finally:
                event.remove(engine, "after_cursor_execute", after)
        finally:
            event.remove(engine, "before_cursor_execute", before)


def _complete_probe(probe):
    assert not probe["overflow"], "Rich-path observation overflowed; not valid work evidence."
    assert all(row["completed"] and row["read_only"] for row in probe["queries"]), probe


def _summary(probe):
    return {
        "serializer_ids": probe["serializer_ids"],
        "loads": probe["loads"],
        "query_count": len(probe["queries"]),
        "table_counts": dict(Counter(
            table for row in probe["queries"] for table in row["tables"]
        )),
        "complete": not probe["overflow"] and all(
            row["completed"] and row["read_only"] for row in probe["queries"]
        ),
    }


def _context(session, actor):
    context = SessionContext(
        company=session.get(Company, actor["company"]["id"]),
        membership=session.get(CompanyMembership, actor["membership"]["id"]),
        user=session.get(User, actor["user"]["id"]),
    )
    assert context.company and context.membership and context.user
    return context


def _public_payload(title):
    return {
        "title": title,
        "restricted": False,
        "particulars": {
            "form_key": "TM-A",
            "form_version": "2026.1",
            "mark_kind": "word",
            "representation": {"text": title},
            "classes": [{"class_number": 9, "specification": "Synthetic software"}],
            "parties": [{
                "role": "applicant", "name": "Synthetic profile applicant",
                "address": None, "country": None,
            }],
            "filing_manifest": [{
                "key": "profile_source_review",
                "label": "Synthetic source review",
                "required": True,
                "evidence_reference": None,
            }],
        },
    }


def _full_public_dto(data, payload):
    assert set(IpDocketRecordResponse.model_fields) <= set(data)
    IpDocketRecordResponse.model_validate(data)
    assert data["title"] == payload["title"]
    assert data["record_type"] == "trademark"
    assert data["status"] == "draft" and data["is_active"] is True
    assert data["current_version"] == 1 and data["lifecycle_version"] == 0
    assert data["matter_id"] is None and data["restricted"] is False
    particular = data["current_particulars"]
    assert particular["docket_id"] == data["id"] and particular["version"] == 1
    assert particular["form_key"] == "TM-A" and particular["form_version"] == "2026.1"
    assert particular["mark_kind"] == "word"
    assert particular["representation_json"] == payload["particulars"]["representation"]
    # The server stamps each class row with the Nice edition in force today.
    edition = nice_catalogue_in_force().edition
    assert particular["classes_json"] == [
        {**row, "nice_edition": edition} for row in payload["particulars"]["classes"]
    ]
    assert particular["parties_json"] == payload["particulars"]["parties"]
    assert particular["filing_manifest_json"] == payload["particulars"]["filing_manifest"]
    assert particular["readiness_status"] == "incomplete"
    assert particular["readiness_errors_json"] == [
        "Required filing item 'Synthetic source review' has no evidence reference."
    ]
    assert particular["finalized_at"] is None
    for key in (
        "notice_links", "evidence_candidates", "deadline_coverages",
        "deadline_incidents", "title_interests", "related_right_obligations", "cost_items",
    ):
        assert data[key] == [], key


def _facts(session, *, company_id, docket_id):
    facts = {}
    for model in _FACT_MODELS:
        parent = model.id if model is IpDocketRecord else model.docket_id
        facts[model.__tablename__] = list(session.scalars(
            select(model.id).where(model.company_id == company_id, parent == docket_id)
            .order_by(model.id)
        ))
    facts["audit_events"] = list(session.scalars(
        select(AuditEvent.id).where(
            AuditEvent.company_id == company_id,
            AuditEvent.ip_docket_id == docket_id,
            AuditEvent.action.in_(_IMPORT_ACTIONS),
        ).order_by(AuditEvent.id)
    ))
    return facts


def _snapshot(company_id):
    with get_session_factory()() as session:
        result = {
            model.__tablename__: list(session.scalars(
                select(model.id).where(model.company_id == company_id).order_by(model.id)
            ))
            for model in _FACT_MODELS
        }
        result["audit_events"] = list(session.scalars(
            select(AuditEvent.id).where(
                AuditEvent.company_id == company_id, AuditEvent.action.in_(_IMPORT_ACTIONS)
            ).order_by(AuditEvent.id)
        ))
        result["import_rows"] = list(session.execute(
            select(
                IpImportRow.id, IpImportRow.commit_status,
                IpImportRow.commit_error_code, IpImportRow.created_docket_id,
            ).where(IpImportRow.company_id == company_id).order_by(IpImportRow.id)
        ))
        return result


def _assert_imported(session, *, company_id, source_row_id, docket_id):
    docket = session.get(IpDocketRecord, docket_id)
    assert docket and docket.company_id == company_id
    assert docket.status == "draft" and docket.is_active and docket.current_version == 1
    facts = _facts(session, company_id=company_id, docket_id=docket_id)
    for table in (
        "ip_docket_records", "ip_trademark_particular_versions",
        "ip_assets", "trademark_applications",
    ):
        assert len(facts[table]) == 1, facts
    version = session.get(
        IpTrademarkParticularVersion, facts["ip_trademark_particular_versions"][0],
    )
    assert version.representation_json["portfolio_import"]["source_row_id"] == source_row_id
    assert version.readiness_status == "incomplete" and version.finalized_at is None
    provenance = list(session.scalars(
        select(AuditEvent.id).where(
            AuditEvent.company_id == company_id,
            AuditEvent.action == "ip_docket.source_materialized",
            AuditEvent.target_type == "ip_import_row",
            AuditEvent.target_id == source_row_id,
            AuditEvent.ip_docket_id == docket_id,
        )
    ))
    assert len(provenance) == 1


def test_bulk_http_new_rows_do_not_serialize_discarded_docket_dtos(
    isolated_postgres_client, monkeypatch, record_property,
):
    client = isolated_postgres_client
    actor = _actor(client)
    company_id = actor["company"]["id"]
    title = f"Import profile {uuid4().hex}"
    preview = _upload(client, actor, ["Trademark"], [[f"{title} {i}"] for i in range(3)])
    assert preview["job"]["valid_rows"] == 3
    assert all(row["validation_status"] == "valid" for row in preview["rows"])
    key = f"import-profile-{uuid4().hex}"

    with _rich_probe(monkeypatch) as observed:
        result = _commit(client, actor, preview, key=key)
    _complete_probe(observed)
    record_property("bulk_rich_serialization", json.dumps(_summary(observed), sort_keys=True))
    assert result["replayed"] is False and result["job"]["committed_rows"] == 3
    assert result["job"]["failed_rows"] == 0
    assert result["job"]["status"] == "committed"
    ids = [row["created_docket_id"] for row in result["rows"]]
    assert len(set(ids)) == 3 and all(ids)
    assert all(row["commit_status"] == "committed" for row in result["rows"])
    with get_session_factory()() as session:
        for row in result["rows"]:
            _assert_imported(
                session, company_id=company_id,
                source_row_id=row["id"], docket_id=row["created_docket_id"],
            )

    before = _snapshot(company_id)
    with _rich_probe(monkeypatch) as replay_observed:
        replay = _commit(client, actor, preview, key=key)
    _complete_probe(replay_observed)
    assert replay["replayed"] is True and replay["rows"] == result["rows"]
    assert replay["job"] == result["job"]
    assert not replay_observed["serializer_ids"] and not replay_observed["loads"]
    assert _snapshot(company_id) == before
    for docket_id in ids:
        reloaded = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"])
        assert reloaded.status_code == 200, reloaded.text
        dto = reloaded.json()
        assert set(IpDocketRecordResponse.model_fields) <= set(dto)
        assert dto["current_version"] == 1 and dto["status"] == "draft"
        assert dto["current_particulars"]["readiness_status"] == "incomplete"

    # All real materialization/reload/replay assertions precede the intended RED.
    assert not observed["serializer_ids"] and not observed["loads"], (
        "Bulk import discarded rich docket DTOs; expected zero rich calls. "
        + json.dumps(_summary(observed), sort_keys=True)
    )


def test_public_http_create_keeps_complete_default_dto(
    isolated_postgres_client, monkeypatch, record_property,
):
    client = isolated_postgres_client
    actor = _actor(client)
    payload = _public_payload(f"Public profile {uuid4().hex}")
    with _rich_probe(monkeypatch) as observed:
        response = client.post("/api/ip/dockets", headers=actor["headers"], json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    _full_public_dto(data, payload)
    _complete_probe(observed)
    record_property("public_rich_serialization", json.dumps(_summary(observed), sort_keys=True))
    assert observed["serializer_ids"] == [data["id"]]
    assert [row["docket_ids"] for row in observed["loads"]] == [[data["id"]]]
    assert len(observed["queries"]) == 9
    assert Counter(table for row in observed["queries"] for table in row["tables"]) == Counter(
        _RICH_TABLES
    )
    with get_session_factory()() as session:
        facts = _facts(session, company_id=actor["company"]["id"], docket_id=data["id"])
        assert facts["ip_docket_records"] == [data["id"]]
        assert len(facts["ip_trademark_particular_versions"]) == 1
        assert len(facts["audit_events"]) == 1
    reloaded = client.get(f"/api/ip/dockets/{data['id']}", headers=actor["headers"])
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json() == data


@pytest.mark.parametrize("finish", ["commit", "rollback"], ids=["commit", "rollback"])
def test_public_deferred_create_keeps_caller_owned_transaction(
    isolated_postgres_client, monkeypatch, finish,
):
    actor = _actor(isolated_postgres_client)
    company_id = actor["company"]["id"]
    payload = _public_payload(f"Deferred profile {uuid4().hex}")
    completed = []
    with get_session_factory()() as session:
        context = _context(session, actor)

        def committed(_session):
            completed.append("commit")

        event.listen(session, "after_commit", committed)
        with _rich_probe(monkeypatch) as observed:
            result = ip_operations.create_ip_docket(
                session, context=context,
                payload=IpDocketCreateRequest.model_validate(payload), commit=False,
            )
        assert isinstance(result, IpDocketRecordResponse)
        data = result.model_dump(mode="json")
        _full_public_dto(data, payload)
        _complete_probe(observed)
        assert observed["serializer_ids"] == [result.id]
        assert completed == [] and session.in_transaction()
        pending = _facts(session, company_id=company_id, docket_id=result.id)
        assert pending["ip_docket_records"] == [result.id]
        assert len(pending["ip_trademark_particular_versions"]) == 1
        assert len(pending["audit_events"]) == 1
        with get_session_factory()() as observer:
            assert all(not ids for ids in _facts(
                observer, company_id=company_id, docket_id=result.id,
            ).values())
        if finish == "commit":
            session.commit()
        else:
            session.rollback()
        assert completed == (["commit"] if finish == "commit" else [])

    with get_session_factory()() as observer:
        retained = _facts(observer, company_id=company_id, docket_id=result.id)
        assert retained == (pending if finish == "commit" else {
            table: [] for table in pending
        })
    if finish == "commit":
        response = isolated_postgres_client.get(
            f"/api/ip/dockets/{result.id}", headers=actor["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json() == data


def test_bulk_row_failure_rolls_back_canonical_facts_and_replay_preserves_sibling(
    isolated_postgres_client, monkeypatch,
):
    client = isolated_postgres_client
    actor = _actor(client)
    company_id = actor["company"]["id"]
    title = f"Atomic profile {uuid4().hex}"
    preview = _upload(client, actor, ["Trademark"], [[f"{title} good"], [f"{title} rejected"]])
    assert preview["job"]["valid_rows"] == 2
    by_number = {row["row_number"]: row for row in preview["rows"]}
    bad_id = ip_imports._import_docket_id(by_number[2]["id"])
    real_application = ip_imports.create_trademark_application
    reached = []

    def reject_after_real_application(session, **kwargs):
        result = real_application(session, **kwargs)
        reached.append(kwargs["docket_id"])
        if kwargs["docket_id"] == bad_id:
            assert kwargs["commit"] is False
            staged = _facts(session, company_id=company_id, docket_id=bad_id)
            for table in (
                "ip_docket_records", "ip_trademark_particular_versions",
                "ip_assets", "trademark_applications",
            ):
                assert len(staged[table]) == 1, staged
            assert len(staged["audit_events"]) == 4, staged
            raise HTTPException(409, {"code": "profile_injected_after_application"})
        return result

    monkeypatch.setattr(ip_imports, "create_trademark_application", reject_after_real_application)
    key = f"atomic-profile-{uuid4().hex}"
    result = _commit(client, actor, preview, key=key)
    assert result["job"]["status"] == "committed_with_errors"
    assert result["job"]["committed_rows"] == 1 and result["job"]["failed_rows"] == 1
    rows = {row["row_number"]: row for row in result["rows"]}
    good_id = rows[1]["created_docket_id"]
    assert rows[1]["commit_status"] == "committed" and good_id
    assert rows[2]["commit_status"] == "failed" and rows[2]["created_docket_id"] is None
    assert rows[2]["commit_error_code"] == "profile_injected_after_application"
    assert reached == [good_id, bad_id]
    with get_session_factory()() as session:
        _assert_imported(
            session, company_id=company_id,
            source_row_id=rows[1]["id"], docket_id=good_id,
        )
        assert all(not ids for ids in _facts(
            session, company_id=company_id, docket_id=bad_id,
        ).values())
        assert session.get(IpImportRow, rows[2]["id"]).commit_status == "failed"

    before = _snapshot(company_id)
    replay = _commit(client, actor, preview, key=key)
    assert replay["replayed"] is True
    assert replay["rows"] == result["rows"] and replay["job"] == result["job"]
    assert reached == [good_id, bad_id]
    assert _snapshot(company_id) == before
