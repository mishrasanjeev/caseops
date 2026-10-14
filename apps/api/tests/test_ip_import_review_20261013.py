"""Independent review regressions for the October 13 IP source workflow."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select

from caseops_api.db.models import (
    BulkImportJob,
    IpTrademarkParticularVersion,
    TrademarkApplication,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import ip_imports, ip_renewals, notification_delivery
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload


def _configure(client, actor, jurisdiction="US", office="USPTO"):
    status = client.get("/api/ip/workspace/configuration", headers=actor["headers"])
    assert status.status_code == 200, status.text
    response = client.put(
        "/api/ip/workspace/configuration",
        headers=actor["headers"],
        json={
            "expected_version": status.json()["configuration"]["version"],
            "enabled_asset_types": ["trademark"],
            "jurisdictions": [jurisdiction],
            "offices": [office],
            "timezone": "Asia/Kolkata",
            "holiday_calendar_key": "source-fixture",
            "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
            "document_taxonomy_version": "fixture-v1",
            "event_catalog_version": "fixture-v1",
            "deadline_rule_versions": {},
            "notification_channels": ["in_app"],
            "critical_event_policy": {"escalation_after_minutes": 60},
            "escalation_owner_membership_id": actor["membership"]["id"],
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("number", ["", "EXACT/1"], ids=["fallback-override", "exact-stays-unique"])
def test_explicit_create_separate_only_overrides_identifierless_fallback(client, number):
    actor = _actor(client)
    columns = ["Trademark", "Applicant", "Class", "Application No."]
    values = [["Reviewed shared mark", "Source Owner", "9", number]]
    first = _commit(client, actor, _upload(client, actor, columns, values))
    second = _upload(client, actor, columns, values)
    reconciled = client.post(
        f"/api/ip/imports/{second['job']['id']}/reconcile",
        headers=actor["headers"],
        json={
            "expected_job_version": second["job"]["version"],
            "decisions": [{"row_id": second["rows"][0]["id"], "decision": "create_separate"}],
        },
    )
    if number:
        assert reconciled.status_code == 409, reconciled.text
        assert reconciled.json()["code"] == "ip_import_exact_identity_conflict"
        result = _commit(client, actor, second, "separate-review-key")
        assert result["job"]["committed_rows"] == 0
        assert result["rows"][0]["commit_error_code"] == "duplicate_skipped"
        return
    assert reconciled.status_code == 200, reconciled.text
    result = _commit(client, actor, reconciled.json(), "separate-review-key")
    assert result["job"]["committed_rows"] == (0 if number else 1)
    if not number:
        assert result["rows"][0]["created_docket_id"] != first["rows"][0]["created_docket_id"]


def test_commit_requires_new_preview_when_derived_context_changes(client):
    actor = _actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Reviewed context"]])
    _configure(client, actor)
    response = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": "context-review-key",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ip_import_preview_context_changed"
    assert client.get("/api/ip/dockets", headers=actor["headers"]).json()["count"] == 0


def test_creator_can_resume_durable_claim_after_context_refresh_without_browser_key(
    client, monkeypatch
):
    actor = _actor(client)
    preview = _upload(client, actor, ["Trademark"], [["Recovered original"], ["Pending source"]])
    real = ip_imports._materialize_import_row

    def crash_after_commit(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("synthetic process loss after durable canonical commit")

    monkeypatch.setattr(ip_imports, "_materialize_import_row", crash_after_commit)
    with pytest.raises(RuntimeError, match="synthetic process loss"):
        _commit(client, actor, preview, "private-original-recovery-key")
    monkeypatch.setattr(ip_imports, "_materialize_import_row", real)
    _configure(client, actor)
    path = f"/api/ip/imports/{preview['job']['id']}"
    retained = client.get(path, headers=actor["headers"]).json()
    blocked = client.post(
        f"{path}/resume",
        headers=actor["headers"],
        json={
            "expected_job_version": retained["job"]["version"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_import_preview_context_changed"
    with get_session_factory()() as session:
        assert session.scalar(select(TrademarkApplication.jurisdiction)) == "IN"
    refreshed = client.post(f"{path}/revalidate", headers=actor["headers"])
    assert refreshed.status_code == 200, refreshed.text
    current = refreshed.json()
    assert current["rows"][0]["commit_status"] == "committed"
    assert current["rows"][0]["normalized"]["jurisdiction"] == "IN"
    assert current["rows"][1]["normalized"]["jurisdiction"] == "US"
    assert current["job"]["recovery_available"]
    recovered = client.post(
        f"{path}/resume",
        headers=actor["headers"],
        json={
            "expected_job_version": current["job"]["version"],
            "preview_token": current["job"]["preview_token"],
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["job"]["committed_rows"] == 2
    assert "private-original-recovery-key" not in recovered.text
    assert "private-original-recovery-key" not in client.get(path, headers=actor["headers"]).text
    with get_session_factory()() as session:
        assert (
            session.get(BulkImportJob, preview["job"]["id"]).idempotency_key
            == "private-original-recovery-key"
        )


def test_new_current_version_reminder_uses_current_particulars_not_original_source(
    client, monkeypatch
):
    actor = _actor(client)
    now = datetime(2028, 3, 20, tzinfo=UTC)
    monkeypatch.setattr(ip_renewals, "_now", lambda: now)
    monkeypatch.setattr(notification_delivery, "_now", lambda: now)
    preview = _upload(
        client,
        actor,
        ["Trademark", "Applicant", "Class", "Goods/Services", "Renewal Date"],
        [["Original mark", "Original Owner", "9", "Software", "2028-03-31"]],
    )
    row = _commit(client, actor, preview)["rows"][0]
    docket_id = row["created_docket_id"]
    docket = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    source = docket["current_particulars"]
    representation = source["representation_json"]
    representation["text"] = "Current source mark"
    representation["portfolio_import"]["renewal_due_date"] = "2028-03-30"
    changed = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "mark_kind": source["mark_kind"],
            "representation": representation,
            "classes": [{"class_number": 42, "specification": "Current legal services"}],
            "parties": [{"role": "applicant", "name": "Current Source Owner"}],
            "filing_manifest": source["filing_manifest_json"],
            "finalize": False,
        },
    )
    assert changed.status_code == 200, changed.text
    with get_session_factory()() as session:
        from caseops_api.db.models import InAppNotification, NotificationDeliveryIntent

        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.ip_docket_id == docket_id,
                NotificationDeliveryIntent.status == "queued",
            )
        )
        result = notification_delivery.process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            company_id=actor["company"]["id"],
        )
        assert result.delivered
        session.commit()
        body = session.scalar(
            select(InAppNotification.body).where(InAppNotification.source_id == intent.source_id)
        )
        assert (
            "Current source mark" in body
            and "Current Source Owner" in body
            and "classes 42" in body
        )
        assert (
            "Original mark" not in body and "Original Owner" not in body and "classes 9" not in body
        )


def test_fresh_all_unusable_rejects_but_all_duplicates_complete_honestly(client):
    actor = _actor(client)
    empty = _upload(client, actor, ["Unknown source field"], [[""]])
    refused = client.post(
        f"/api/ip/imports/{empty['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": empty["job"]["preview_token"],
            "idempotency_key": "no-work-source-key",
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_import_no_eligible_rows"
    columns, rows = ["Trademark", "Application No."], [["Existing source", "EXISTING/1"]]
    _commit(client, actor, _upload(client, actor, columns, rows))
    duplicates = _commit(
        client, actor, _upload(client, actor, columns, rows), "only-duplicates-key"
    )
    assert duplicates["job"]["committed_rows"] == 0
    assert duplicates["rows"][0]["commit_status"] == "skipped"
    assert duplicates["rows"][0]["commit_error_code"] == "duplicate_skipped"


def test_same_mark_real_materialization_has_one_bounded_candidate_scan(client):
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        ["Trademark", "Applicant", "Class"],
        [["Shared source mark", f"Distinct source owner {i}", "9"] for i in range(50)],
    )
    statements = []

    hydrated_candidates = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
        compiled = getattr(context, "compiled", None)
        columns = getattr(getattr(compiled, "statement", None), "selected_columns", ())
        if (
            any(
                getattr(column, "table", None) is IpTrademarkParticularVersion.__table__
                and column.name == "representation_json"
                for column in columns
            )
            and "JOIN trademark_applications" in statement
        ):
            hydrated_candidates.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        saved = _commit(client, actor, preview)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert saved["job"]["committed_rows"] == 50
    assert len(hydrated_candidates) <= 1, (
        f"Repeated current-particular candidate hydration: {len(hydrated_candidates)}"
    )
    assert len(statements) <= 180 * 50 + 200
