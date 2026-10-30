"""IPLF-032/UJ-02/NFT-005: scalar preflight, ordered fences, fresh row recovery."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    BulkImportJob,
    Company,
    CompanyMembership,
    IpAsset,
    IpDocketRecord,
    IpImportRow,
    TrademarkApplication,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.schemas.ip_imports import IpImportCommitRequest
from caseops_api.services import ip_imports
from caseops_api.services.session_context import SessionContext
from tests.sql_observation import is_read_only_select
from tests.test_ip_import_review_gaps_20261013 import _change_context
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def import_client(request):
    return request.getfixturevalue(request.param)


def _context(session, actor):
    context = SessionContext(
        company=session.get(Company, actor["company"]["id"]),
        membership=session.get(CompanyMembership, actor["membership"]["id"]),
        user=session.get(User, actor["user"]["id"]),
    )
    assert context.company and context.membership and context.user
    return context


def _other_actor(client):
    token = uuid4().hex
    foreign_client = TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    )
    try:
        response = foreign_client.post("/api/bootstrap/company", json={
            "company_name": "Preflight foreign tenant",
            "company_slug": f"preflight-{token}",
            "company_type": "law_firm",
            "owner_full_name": "Preflight foreign owner",
            "owner_email": f"preflight-{token}@example.com",
            "owner_password": "PreflightOwner123!",
        })
        assert response.status_code == 200, response.text
        return response.json()
    finally:
        foreign_client.close()


def _claim(preview):
    # Establish a retained claim without fabricating a successful materialization.
    key = f"preflight-retained-{uuid4().hex}"
    with get_session_factory()() as session:
        job = session.get(BulkImportJob, preview["job"]["id"])
        assert job is not None and job.status == "preview_ready"
        assert job.idempotency_key is None
        job.status = "staged"
        job.idempotency_key = key
        job.preview_token = None
        job.preview_expires_at = None
        session.commit()
    return key


def _reserve(session, actor, row_id):
    docket = IpDocketRecord(
        id=ip_imports._import_docket_id(row_id),
        company_id=actor["company"]["id"],
        created_by_membership_id=actor["membership"]["id"],
        record_type="trademark",
        title="Reserved identity negative fixture",
        status="draft",
    )
    session.add(docket)
    session.flush()
    return docket.id


def _audit(session, actor, row_id, docket_id, **overrides):
    facts = {
        "company_id": actor["company"]["id"],
        "actor_type": "membership",
        "actor_membership_id": actor["membership"]["id"],
        "action": ip_imports.IMPORT_MATERIALIZATION_ACTION,
        "target_type": "ip_import_row",
        "target_id": row_id,
        "ip_docket_id": docket_id,
    }
    facts.update(overrides)
    session.add(AuditEvent(**facts))


def _history(client, actor, preview):
    response = client.get(
        f"/api/ip/imports/{preview['job']['id']}", headers=actor["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def _scalar_probe(session):
    reads, loaded, bound = [], [], []

    def sql(conn, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        clause = getattr(compiled, "statement", None)
        if is_read_only_select(clause):
            reads.append(clause)
            bound.append(parameters)

    def hydrated(observed_session, instance):
        loaded.append(type(instance).__name__)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", sql)
    event.listen(session, "loaded_as_persistent", hydrated)
    try:
        yield reads, loaded, bound
    finally:
        event.remove(session, "loaded_as_persistent", hydrated)
        event.remove(engine, "before_cursor_execute", sql)


def test_claimed_thousand_row_preflight_is_one_scalar_read(
    import_client, monkeypatch, record_property,
):
    """IP-PF-01: unchanged public rejection isolates all pending-row preflight work."""
    client = import_client
    actor = _actor(client)
    preview = _upload(
        client, actor, ["Trademark"], [[f"Pending preflight {i}"] for i in range(1000)]
    )
    assert preview["job"]["valid_rows"] == 1000
    _claim(preview)
    before = _history(client, actor, preview)
    reads, recovery_calls, loaded = [], [], []
    active = False
    real_defaults = ip_imports._workspace_import_defaults
    real_recover = ip_imports._recover_materialized_docket

    def defaults(*args, **kwargs):
        nonlocal active
        result = real_defaults(*args, **kwargs)
        active = True
        return result

    def recover(*args, **kwargs):
        if active:
            recovery_calls.append(kwargs["row_id"])
        return real_recover(*args, **kwargs)

    def sql(conn, cursor, statement, parameters, context, executemany):
        if active:
            compiled = getattr(context, "compiled", None)
            clause = getattr(compiled, "statement", None)
            if is_read_only_select(clause):
                reads.append(clause)

    def hydrated(session, instance):
        if active:
            loaded.append(type(instance).__name__)

    monkeypatch.setattr(ip_imports, "_workspace_import_defaults", defaults)
    monkeypatch.setattr(ip_imports, "_recover_materialized_docket", recover)
    engine = get_engine()
    event.listen(engine, "before_cursor_execute", sql)
    event.listen(Session, "loaded_as_persistent", hydrated)
    try:
        response = client.post(
            f"/api/ip/imports/{preview['job']['id']}/commit",
            headers=actor["headers"],
            json={"preview_token": "retained-claim", "idempotency_key": "different-key"},
        )
    finally:
        active = False
        event.remove(Session, "loaded_as_persistent", hydrated)
        event.remove(engine, "before_cursor_execute", sql)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "Recover this import using its retained creator-authorized claim."
    )
    assert _history(client, actor, preview) == before
    record_property("pending_rows", 1000)
    record_property("preflight_selects", len(reads))
    record_property("per_row_preflight_recovery_calls", len(recovery_calls))
    record_property("preflight_orm_loads", loaded)
    # The baseline reaches this oracle: it calls the old recovery reader 1000 times.
    assert recovery_calls == [], recovery_calls
    assert len(reads) == 1, [str(clause) for clause in reads]
    assert len(list(reads[0].selected_columns)) == 2
    assert loaded == []


def test_scalar_facts_exclude_invalid_finished_and_foreign_reservations(import_client):
    """IP-PF-02: one scalar result per eligible reservation, not per audit history row."""
    client = import_client
    actor = _actor(client)
    foreign = _other_actor(client)
    preview = _upload(client, actor, ["Trademark"], [[f"Scalar facts {i}"] for i in range(8)])
    ids = [row["id"] for row in preview["rows"]]
    with get_session_factory()() as session:
        proven_id = _reserve(session, actor, ids[0])
        _reserve(session, actor, ids[1])
        _reserve(session, foreign, ids[2])
        for row_id in ids[3:7]:
            _reserve(session, actor, row_id)
        for _ in range(128):
            _audit(session, actor, ids[0], proven_id)
        session.get(IpImportRow, ids[3]).validation_status = "invalid"
        for row_id, state in zip(ids[4:7], ("committed", "failed", "skipped"), strict=True):
            session.get(IpImportRow, row_id).commit_status = state
        session.commit()

    with get_session_factory()() as session:
        context = _context(session, actor)
        rows = ip_imports._rows(session, session.get(BulkImportJob, preview["job"]["id"]))
        with _scalar_probe(session) as (reads, loaded, bound):
            facts = ip_imports._preflight_materialized_dockets(
                session, context=context, rows=rows,
            )
        assert facts == {ids[0]: True, ids[1]: False}
        assert len(reads) == 1 and loaded == []
        assert len(list(reads[0].selected_columns)) == 2
        assert len(facts) <= sum(
            row.commit_status == "pending" and row.validation_status == "valid" for row in rows
        )
        native = bound[0].values() if isinstance(bound[0], dict) else bound[0]
        supplied = {str(value) for value in native}
        for excluded in ids[3:7]:
            assert excluded not in supplied
            assert ip_imports._import_docket_id(excluded) not in supplied
        with _scalar_probe(session) as (reads, loaded, _bound):
            empty = ip_imports._preflight_materialized_dockets(
                session, context=context, rows=rows[3:7],
            )
        assert empty == {} and reads == [] and loaded == []


@pytest.mark.parametrize(
    "difference", ["none", "company_id", "action", "target_type", "target_id", "ip_docket_id"]
)
def test_preflight_provenance_matches_the_original_recovery_predicate(import_client, difference):
    """IP-PF-03: every original audit identity field remains significant."""
    client = import_client
    actor = _actor(client)
    foreign = _other_actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Exact provenance"]])
    row_id = preview["rows"][0]["id"]
    with get_session_factory()() as session:
        docket_id = _reserve(session, actor, row_id)
        alternate = _reserve(session, actor, str(uuid4()))
        replacements = {
            "company_id": foreign["company"]["id"],
            "action": "ip_docket.created",
            "target_type": "ip_docket_record",
            "target_id": str(uuid4()),
            "ip_docket_id": alternate,
        }
        overrides = {} if difference == "none" else {difference: replacements[difference]}
        # AuditEvent has scalar company/docket FKs, not a composite tenant FK.
        # This deliberately inconsistent negative receipt is never an admission.
        if difference == "company_id":
            overrides["actor_membership_id"] = foreign["membership"]["id"]
        for _ in range(2):
            _audit(session, actor, row_id, docket_id, **overrides)
        session.commit()

    with get_session_factory()() as session:
        context = _context(session, actor)
        rows = ip_imports._rows(session, session.get(BulkImportJob, preview["job"]["id"]))
        facts = ip_imports._preflight_materialized_dockets(session, context=context, rows=rows)
        assert facts == {row_id: difference == "none"}
        if difference == "none":
            recovered = ip_imports._recover_materialized_docket(
                session, context=context, row_id=row_id,
            )
            assert recovered.id == docket_id
        else:
            with pytest.raises(HTTPException) as denied:
                ip_imports._recover_materialized_docket(session, context=context, row_id=row_id)
            assert denied.value.status_code == 409
            assert denied.value.detail == {
                "code": "ip_import_materialization_provenance_missing",
                "message": "A reserved docket exists without matching import provenance.",
            }


@pytest.mark.parametrize(
    "layout", ["context-first", "provenance-first", "proven-first", "invalid-first",
               "finished-first", "foreign-first", "skip-first", "link-first"]
)
def test_claimed_preflight_preserves_ordered_rejections_before_key_checks(import_client, layout):
    """IP-PF-04: bulk collection cannot promote a later rejection over the first row."""
    client = import_client
    actor = _actor(client)
    foreign = _other_actor(client) if layout == "foreign-first" else None
    preview = _upload(client, actor, ["Trademark"], [["Ordered first"], ["Ordered second"]])
    ids = [row["id"] for row in preview["rows"]]
    _claim(preview)
    with get_session_factory()() as session:
        if layout == "context-first":
            _reserve(session, actor, ids[1])
        else:
            docket_id = _reserve(session, foreign or actor, ids[0])
            if layout == "proven-first":
                _audit(session, actor, ids[0], docket_id)
            elif layout == "invalid-first":
                session.get(IpImportRow, ids[0]).validation_status = "invalid"
            elif layout == "finished-first":
                session.get(IpImportRow, ids[0]).commit_status = "failed"
            elif layout == "skip-first":
                session.get(IpImportRow, ids[0]).reconciliation_decision = "skip"
            elif layout == "link-first":
                row = session.get(IpImportRow, ids[0])
                row.reconciliation_decision = "link_existing"
                row.reconciled_target_docket_id = docket_id
        session.commit()
    _change_context(client, actor)
    before = _history(client, actor, preview)
    response = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={"preview_token": "irrelevant", "idempotency_key": "wrong-retained-key"},
    )
    assert response.status_code == 409, response.text
    expected = (
        "ip_import_materialization_provenance_missing"
        if layout in {"provenance-first", "skip-first", "link-first"}
        else "ip_import_preview_context_changed"
    )
    assert response.json()["code"] == expected, response.text
    assert _history(client, actor, preview) == before


@pytest.mark.parametrize("late_kind", ["unproven-reservation", "canonical-materialization"])
def test_row_recovery_is_fresh_after_preflight_and_sibling_commit(
    import_client, monkeypatch, late_kind,
):
    """IP-PF-05: preflight facts cannot authorize or suppress an actual later row."""
    client = import_client
    actor = _actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Fresh sibling"], ["Late reservation"]])
    ids = [row["id"] for row in preview["rows"]]
    key = _claim(preview)
    before = _history(client, actor, preview)
    real_outcome = ip_imports._set_row_outcome
    inserted = []

    def outcome(session, **kwargs):
        real_outcome(session, **kwargs)
        if kwargs["row_id"] == ids[0] and kwargs["commit_status"] == "committed":
            assert not inserted
            with get_session_factory()() as writer:
                if late_kind == "canonical-materialization":
                    row = writer.get(IpImportRow, ids[1])
                    docket = ip_imports._materialize_import_row(
                        writer, context=_context(writer, actor), row_id=ids[1],
                        normalized=deepcopy(row.normalized_json),
                    )
                    inserted.append(docket.id)
                else:
                    inserted.append(_reserve(writer, actor, ids[1]))
                    writer.commit()

    monkeypatch.setattr(ip_imports, "_set_row_outcome", outcome)
    response = client.post(
        f"/api/ip/imports/{preview['job']['id']}/resume",
        headers=actor["headers"],
        json={"expected_job_version": before["job"]["version"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert inserted == [ip_imports._import_docket_id(ids[1])]
    good = late_kind == "canonical-materialization"
    assert result["job"]["committed_rows"] == (2 if good else 1)
    assert result["job"]["failed_rows"] == (0 if good else 1)
    assert result["rows"][0]["commit_status"] == "committed"
    second = result["rows"][1]
    assert second["commit_status"] == ("committed" if good else "failed")
    assert second["created_docket_id"] == (inserted[0] if good else None)
    assert second["commit_error_code"] == (
        None if good else "ip_import_materialization_provenance_missing"
    )
    with get_session_factory()() as session:
        assets = list(session.scalars(select(IpAsset.id).where(IpAsset.docket_id == inserted[0])))
        applications = list(session.scalars(select(TrademarkApplication.id).where(
            TrademarkApplication.docket_id == inserted[0],
        )))
        assert len(assets) == len(applications) == (1 if good else 0)
    replay = _commit(client, actor, preview, key=key)
    assert replay["replayed"] is True and replay["rows"] == result["rows"]
    assert _history(client, actor, preview)["rows"] == result["rows"]


def test_fresh_commit_and_terminal_replay_do_not_use_preflight_recovery(
    import_client, monkeypatch,
):
    """IP-PF-06: initial row recovery and terminal idempotence retain their own paths."""
    client = import_client
    actor = _actor(client)
    preview = _upload(
        client, actor, ["Trademark"], [["Fresh commit first"], ["Fresh commit second"]]
    )

    def unexpected(*args, **kwargs):
        pytest.fail("An unclaimed job or terminal replay reached claimed-job preflight.")

    monkeypatch.setattr(ip_imports, "_preflight_materialized_dockets", unexpected)
    key = f"fresh-preflight-{uuid4().hex}"
    result = _commit(client, actor, preview, key=key)
    assert result["job"]["committed_rows"] == 2 and result["job"]["failed_rows"] == 0
    assert len({row["created_docket_id"] for row in result["rows"]}) == 2
    for row in result["rows"]:
        response = client.get(
            f"/api/ip/dockets/{row['created_docket_id']}", headers=actor["headers"]
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "draft"
    replay = _commit(client, actor, preview, key=key)
    assert replay["replayed"] is True and replay["rows"] == result["rows"]


def test_noncreator_and_foreign_tenant_are_rejected_before_preflight(import_client, monkeypatch):
    """IP-PF-07: scalarization must not move admission ahead of creator ownership."""
    client = import_client
    actor = _actor(client)
    foreign = _other_actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Creator scoped source"]])
    key = _claim(preview)
    with get_session_factory()() as session:
        membership = CompanyMembership(
            company_id=actor["company"]["id"], user_id=foreign["user"]["id"],
            role="owner", is_active=True,
        )
        session.add(membership)
        session.commit()
        sibling_id = membership.id

    def unexpected(*args, **kwargs):
        pytest.fail("Unauthorized import ownership reached recovery preflight.")

    monkeypatch.setattr(ip_imports, "_preflight_materialized_dockets", unexpected)
    sibling = {
        **foreign, "company": actor["company"], "membership": {"id": sibling_id},
    }
    for rejected_actor in (sibling, foreign):
        with get_session_factory()() as session:
            with pytest.raises(HTTPException) as denied:
                ip_imports.commit_ip_import_job(
                    session, context=_context(session, rejected_actor),
                    job_id=preview["job"]["id"],
                    payload=IpImportCommitRequest(idempotency_key=key, preview_token="retained"),
                )
            assert denied.value.status_code == 404
            assert denied.value.detail == "Import job not found."
    retained = _history(client, actor, preview)
    assert retained["job"]["committed_rows"] == 0
    assert retained["rows"][0]["commit_status"] == "pending"


@pytest.mark.parametrize("reservation_scope", ["tenant", "foreign"])
def test_fresh_claim_keeps_invalid_and_reserved_row_outcomes(
    import_client, monkeypatch, reservation_scope,
):
    """IP-PF-08: a fresh collision is still a row failure, not preflight HTTP rejection."""
    client = import_client
    actor = _actor(client)
    reservation_actor = _other_actor(client) if reservation_scope == "foreign" else actor
    preview = _upload(client, actor, ["Trademark"], [["x"], ["Fresh reserved identity"]])
    assert [row["validation_status"] for row in preview["rows"]] == ["invalid", "valid"]
    with get_session_factory()() as session:
        for row in preview["rows"]:
            _reserve(session, reservation_actor, row["id"])
        session.commit()

    def unexpected(*args, **kwargs):
        pytest.fail("Fresh admission ran retained-claim preflight.")

    monkeypatch.setattr(ip_imports, "_preflight_materialized_dockets", unexpected)
    result = _commit(client, actor, preview, key=f"fresh-reserved-{uuid4().hex}")
    assert result["job"]["status"] == "committed_with_errors"
    assert result["job"]["committed_rows"] == 0 and result["job"]["failed_rows"] == 1
    assert [row["commit_status"] for row in result["rows"]] == ["skipped", "failed"]
    assert result["rows"][0]["commit_error_code"] is None
    assert result["rows"][1]["commit_error_code"] == (
        "ip_import_materialization_provenance_missing" if reservation_scope == "tenant"
        else "commit_rejected"
    )
    assert all(row["created_docket_id"] is None for row in result["rows"])
    with get_session_factory()() as session:
        reserved = session.get(
            IpDocketRecord, ip_imports._import_docket_id(preview["rows"][1]["id"])
        )
        assert reserved.company_id == reservation_actor["company"]["id"]
        assert reserved.title == "Reserved identity negative fixture"
        assert list(session.scalars(select(IpAsset.id).where(
            IpAsset.docket_id == reserved.id,
        ))) == []
        assert list(session.scalars(select(TrademarkApplication.id).where(
            TrademarkApplication.docket_id == reserved.id,
        ))) == []


@pytest.mark.parametrize("violation", ["context", "provenance"])
def test_preflight_rejects_later_rows_before_any_batch_materialization(import_client, violation):
    """IP-PF-09: retain full pending inventory checks, including beyond row 50."""
    client = import_client
    actor = _actor(client)
    preview = _upload(
        client, actor, ["Trademark", "Jurisdiction", "Office"],
        [[f"Explicit preflight {i}", "IN", "IP India"] for i in range(50)]
        + [["Later derived context", "", ""]],
    )
    assert preview["job"]["valid_rows"] == 51
    _claim(preview)
    if violation == "provenance":
        with get_session_factory()() as session:
            _reserve(session, actor, preview["rows"][-1]["id"])
            session.commit()
    _change_context(client, actor)
    before = _history(client, actor, preview)
    response = client.post(
        f"/api/ip/imports/{preview['job']['id']}/resume",
        headers=actor["headers"],
        json={"expected_job_version": before["job"]["version"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == (
        "ip_import_materialization_provenance_missing"
        if violation == "provenance"
        else "ip_import_preview_context_changed"
    )
    assert _history(client, actor, preview) == before
    with get_session_factory()() as session:
        owned_ids = [ip_imports._import_docket_id(row["id"]) for row in preview["rows"]]
        retained = list(session.scalars(select(IpDocketRecord.id).where(
            IpDocketRecord.company_id == actor["company"]["id"],
            IpDocketRecord.id.in_(owned_ids),
        )))
    assert retained == ([owned_ids[-1]] if violation == "provenance" else [])
