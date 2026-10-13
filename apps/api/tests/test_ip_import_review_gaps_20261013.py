"""Reviewed context, durable recovery and bounded commit admission."""

from __future__ import annotations

from time import sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from caseops_api.db.models import IpTrademarkParticularVersion
from caseops_api.db.session import get_engine
from caseops_api.services import ip_imports
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def import_client(request):
    return request.getfixturevalue(request.param)


def test_separate_fallback_is_honored_but_exact_identifier_is_not_overridden(import_client):
    client = import_client
    actor = _actor(client)
    headers = ["Trademark", "Applicant", "Class"]
    first = _upload(client, actor, headers, [["Same mark", "Same owner", "9,36"]])
    first_saved = _commit(client, actor, first, "initial-fallback-20261013")
    second = _upload(client, actor, headers, [["Same mark", "Same owner", "36,9"]])
    assert second["rows"][0]["reconciliation_decision"] == "skip"
    choice = client.post(
        f"/api/ip/imports/{second['job']['id']}/reconcile",
        headers=actor["headers"],
        json={
            "expected_job_version": second["job"]["version"],
            "decisions": [{"row_id": second["rows"][0]["id"], "decision": "create_separate"}],
        },
    )
    assert choice.status_code == 200, choice.text
    saved = _commit(client, actor, choice.json(), "separate-fallback-20261013")
    assert saved["job"]["committed_rows"] == 1
    assert saved["rows"][0]["created_docket_id"] != first_saved["rows"][0]["created_docket_id"]
    numbered = _upload(client, actor, ["Trademark", "Application No."], [["Numbered", "EXACT/13"]])
    _commit(client, actor, numbered, "numbered-first-20261013")
    duplicate = _upload(
        client, actor, ["Trademark", "Application No."], [["Another mark", "EXACT 13"]]
    )
    selected = client.post(
        f"/api/ip/imports/{duplicate['job']['id']}/reconcile",
        headers=actor["headers"],
        json={
            "expected_job_version": duplicate["job"]["version"],
            "decisions": [{"row_id": duplicate["rows"][0]["id"], "decision": "create_separate"}],
        },
    )
    assert selected.status_code == 409, selected.text
    assert selected.json()["code"] == "ip_import_exact_identity_conflict"
    result = _commit(client, actor, duplicate, "numbered-override-20261013")
    assert result["job"]["committed_rows"] == 0
    assert result["rows"][0]["commit_status"] == "skipped"


def _change_context(client, actor):
    configuration = client.get("/api/ip/workspace/configuration", headers=actor["headers"])
    assert configuration.status_code == 200, configuration.text
    # The canonical update DTO is the same setup contract used by the fixture.
    payload = {
        "expected_version": configuration.json()["configuration"]["version"],
        "enabled_asset_types": ["trademark"],
        "jurisdictions": ["US"],
        "offices": ["USPTO"],
        "timezone": "Asia/Kolkata",
        "holiday_calendar_key": "source-fixture",
        "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
        "document_taxonomy_version": "fixture-v1",
        "event_catalog_version": "fixture-v1",
        "deadline_rule_versions": {},
        "notification_channels": ["in_app"],
        "critical_event_policy": {"escalation_after_minutes": 60},
        "escalation_owner_membership_id": actor["membership"]["id"],
    }
    response = client.put("/api/ip/workspace/configuration", headers=actor["headers"], json=payload)
    assert response.status_code == 200, response.text


def test_changed_derived_context_requires_reviewed_preview(import_client):
    client = import_client
    actor = _actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Reviewed source context"]])
    _change_context(client, actor)
    rejected = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": "changed-context-20261013",
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "ip_import_preview_context_changed"
    retained = client.get(
        f"/api/ip/imports/{preview['job']['id']}", headers=actor["headers"]
    ).json()
    assert retained["job"]["status"] == "preview_ready"
    assert retained["rows"][0]["normalized"]["jurisdiction"] == "IN"
    refreshed = client.post(
        f"/api/ip/imports/{preview['job']['id']}/revalidate", headers=actor["headers"]
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["rows"][0]["normalized"]["jurisdiction"] == "US"
    saved = _commit(client, actor, refreshed.json(), "reviewed-new-context-20261013")
    assert saved["job"]["committed_rows"] == 1


def test_creator_recovery_survives_lost_key_and_context_refresh(import_client, monkeypatch):
    client = import_client
    actor = _actor(client)
    preview = _upload(
        client, actor, ["Trademark"], [["Recovered source one"], ["Recovered source two"]]
    )
    real = ip_imports._materialize_import_row

    def crash_after_first(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("synthetic exit after atomic source materialization")

    monkeypatch.setattr(ip_imports, "_materialize_import_row", crash_after_first)
    with pytest.raises(RuntimeError, match="synthetic exit"):
        _commit(client, actor, preview, "durable-claim-kept-server-side")
    monkeypatch.setattr(ip_imports, "_materialize_import_row", real)
    history_url = f"/api/ip/imports/{preview['job']['id']}"
    retained = client.get(history_url, headers=actor["headers"]).json()
    assert retained["job"]["recovery_available"] is True
    assert "idempotency_key" not in retained["job"]
    foreign_client = TestClient(
        client.app, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}
    )
    foreign = foreign_client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other isolated portfolio",
            "company_slug": "other-isolated-portfolio",
            "company_type": "law_firm",
            "owner_full_name": "Other source owner",
            "owner_email": "other-portfolio@example.com",
            "owner_password": "OtherSourcePass123!",
        },
    )
    assert foreign.status_code == 200, foreign.text
    denied = foreign_client.post(
        history_url + "/resume",
        headers={
            "Authorization": f"Bearer {foreign.json()['access_token']}",
            "X-CaseOps-Automated-Test": "no-paid-providers",
        },
        json={
            "expected_job_version": retained["job"]["version"],
        },
    )
    assert denied.status_code == 404, denied.text
    foreign_client.close()
    stale = client.post(
        history_url + "/resume",
        headers=actor["headers"],
        json={
            "expected_job_version": retained["job"]["version"] - 1,
        },
    )
    assert stale.status_code == 409, stale.text
    _change_context(client, actor)
    blocked = client.post(
        history_url + "/resume",
        headers=actor["headers"],
        json={
            "expected_job_version": retained["job"]["version"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_import_preview_context_changed"
    refreshed = client.post(history_url + "/revalidate", headers=actor["headers"])
    assert refreshed.status_code == 200, refreshed.text
    reviewed = refreshed.json()
    assert reviewed["rows"][0]["commit_status"] == "committed"
    assert reviewed["rows"][0]["normalized"]["jurisdiction"] == "IN"
    assert reviewed["rows"][1]["normalized"]["jurisdiction"] == "US"
    recovered = client.post(
        history_url + "/resume",
        headers=actor["headers"],
        json={
            "expected_job_version": reviewed["job"]["version"],
            "preview_token": reviewed["job"]["preview_token"],
        },
    )
    assert recovered.status_code == 200, recovered.text
    result = recovered.json()
    assert result["job"]["committed_rows"] == 2
    assert len({row["created_docket_id"] for row in result["rows"]}) == 2
    assert result["rows"][0]["created_docket_id"] == reviewed["rows"][0]["created_docket_id"]


def test_unusable_no_work_rejected_but_safe_duplicates_are_nonfatal(import_client):
    client = import_client
    actor = _actor(client)
    empty = _upload(client, actor, ["Comment"], [["Only source notes"]])
    response = client.post(
        f"/api/ip/imports/{empty['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": empty["job"]["preview_token"],
            "idempotency_key": "unusable-no-work-20261013",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ip_import_no_eligible_rows"
    first = _upload(
        client, actor, ["Trademark", "Application No."], [["Safe duplicate", "SAFE/13"]]
    )
    _commit(client, actor, first, "safe-first-20261013")
    duplicate = _upload(
        client, actor, ["Trademark", "Application No."], [["Safe duplicate", "SAFE 13"]]
    )
    result = _commit(client, actor, duplicate, "safe-skip-20261013")
    assert result["job"]["committed_rows"] == 0
    assert result["job"]["failed_rows"] == 0
    assert result["rows"][0]["commit_error_code"] == "duplicate_skipped"


@pytest.mark.postgres
def test_thousand_same_mark_distinct_applicants_commit_has_linear_materialization(
    isolated_postgres_client, record_property,
):
    client = isolated_postgres_client
    actor = _actor(client)
    count = 1000
    preview = _upload(
        client,
        actor,
        ["Trademark", "Applicant", "Class"],
        [
            ["Shared bounded mark", f"Distinct source owner {number}", "9,36"]
            for number in range(count)
        ],
    )
    queries = loaded = 0

    def query(*args):
        nonlocal queries
        queries += 1

    def materialized(session, instance):
        nonlocal loaded
        if isinstance(instance, IpTrademarkParticularVersion):
            loaded += 1

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", query)
    event.listen(Session, "loaded_as_persistent", materialized)
    try:
        result = _commit(client, actor, preview, "bounded-thousand-commit-20261013")
    finally:
        event.remove(engine, "before_cursor_execute", query)
        event.remove(Session, "loaded_as_persistent", materialized)
    assert result["job"]["committed_rows"] == count
    assert result["job"]["failed_rows"] == 0
    assert len({row["created_docket_id"] for row in result["rows"]}) == count
    assert loaded <= 12 * count, (loaded, count)
    assert queries <= 180 * count + 200, (queries, count)
    record_property("materialized_particulars", loaded)
    record_property("total_sql_statements", queries)
    record_property("created_dockets", count)


def test_duplicate_work_budget_still_fails_closed():
    budget = ip_imports._DuplicateWorkBudget(remaining=2)
    budget.charge(2)
    with pytest.raises(HTTPException) as denied:
        budget.charge(1)
    assert denied.value.status_code == 422
    assert denied.value.detail["code"] == "ip_import_candidate_limit"


def test_successful_bounded_batches_are_not_terminal_and_resume_without_client_key(
    client, monkeypatch
):
    monkeypatch.setattr(ip_imports, "COMMIT_BATCH_SIZE", 2)
    actor = _actor(client)
    preview = _upload(client, actor, ["Trademark"], [[f"Bounded source {i}"] for i in range(5)])
    response = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": "bounded-batch-source-key",
        },
    )
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["job"]["status"] == "staged"
    assert result["job"]["committed_rows"] == 2
    assert result["job"]["committed_at"] is None
    assert result["job"]["commit_batch_size"] == 2
    assert result["job"]["recovery_available"] is True
    for expected, status in [(4, 202), (5, 200)]:
        response = client.post(
            f"/api/ip/imports/{preview['job']['id']}/resume",
            headers=actor["headers"],
            json={
                "expected_job_version": result["job"]["version"],
            },
        )
        assert response.status_code == status, response.text
        result = response.json()
        assert result["job"]["committed_rows"] == expected
    assert result["job"]["status"] == "committed"
    assert len({row["created_docket_id"] for row in result["rows"]}) == 5


@pytest.mark.postgres
def test_import_claim_is_session_owned_without_idle_transaction(pg_engine):
    captured = {}

    def capture_claim(connection, cursor, statement, parameters, context, executemany):
        if "SELECT pg_advisory_lock(" in statement and not captured:
            captured["connection"] = connection
            connection.exec_driver_sql("SET idle_in_transaction_session_timeout = '1s'")

    event.listen(pg_engine, "before_cursor_execute", capture_claim)
    resource = f"isolated-import-claim:{uuid4()}"
    try:
        with Session(pg_engine) as session:
            with ip_imports._import_commit_locks(session, resource) as owned:
                assert owned is not None
                owned()
                pid = captured["connection"].scalar(text("SELECT pg_backend_pid()"))
                with pg_engine.connect() as observer:
                    state = observer.scalar(
                        text("SELECT state FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid}
                    )
                assert state == "idle", state
                sleep(1.3)
                owned()
            with pg_engine.connect() as observer:
                held = observer.scalar(
                    text("SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory'"),
                    {"pid": pid},
                )
                assert held == 0
    finally:
        event.remove(pg_engine, "before_cursor_execute", capture_claim)


@pytest.mark.postgres
def test_import_claim_loss_rejects_writer_and_discards_connection(pg_engine):
    captured = {}
    discarded = []

    def capture_claim(connection, cursor, statement, parameters, context, executemany):
        if "SELECT pg_advisory_lock(" in statement and not captured:
            captured["connection"] = connection
            captured["driver_connection"] = connection.connection.dbapi_connection

    def capture_discard(connection, connection_record, exception):
        discarded.append(connection)

    event.listen(pg_engine, "before_cursor_execute", capture_claim)
    event.listen(pg_engine, "invalidate", capture_discard)
    resource = f"isolated-lost-import-claim:{uuid4()}"
    try:
        with Session(pg_engine) as session:
            with pytest.raises(HTTPException) as rejected:
                with ip_imports._import_commit_locks(session, resource) as owned:
                    assert owned is not None
                    owned()
                    assert captured["connection"].scalar(
                        text("SELECT pg_advisory_unlock(hashtextextended(:resource, 0))"),
                        {"resource": resource},
                    ) is True
                    owned()
                    pytest.fail("A writer continued after losing its claim.")
            assert rejected.value.status_code == 409
            assert rejected.value.detail["code"] == "ip_import_claim_lost"
            assert discarded == [captured["driver_connection"]]
            assert captured["driver_connection"].closed
            with ip_imports._import_commit_locks(session, resource) as replacement:
                assert replacement is not None
                replacement()
    finally:
        event.remove(pg_engine, "before_cursor_execute", capture_claim)
        event.remove(pg_engine, "invalidate", capture_discard)
