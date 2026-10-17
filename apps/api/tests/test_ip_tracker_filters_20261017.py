"""IP15-018 current-source filters, continuation and retained portfolio workflow."""

import csv
import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import NotificationDeliveryIntent, NotificationDeliveryStatus
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker, notification_delivery
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_renewal_tracker_20261015 import _clock


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def tracker_client(request):
    return request.getfixturevalue(request.param)


def _records(client, monkeypatch):
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        ["Trademark", "Application Number", "Application Date", "Renewal Date"],
        [
            ["IP18 source early", "IP18-1001", "2010-01-01", "2028-03-15"],
            ["IP18 source selected", "IP18-1002", "2020-01-01", "2028-03-16"],
            ["IP18 source outside", "IP18-1003", "2020-01-01", "2028-05-16"],
        ],
    )
    committed = _commit(client, actor, preview)
    return actor, [row["created_docket_id"] for row in committed["rows"]]


def _tracker(client, actor, **params):
    return client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"], params=params)


def test_tracker_date_ranges_filter_rows_and_all_category_counts(tracker_client, monkeypatch):
    actor, ids = _records(tracker_client, monkeypatch)
    response = _tracker(
        tracker_client,
        actor,
        query="IP18 source",
        application_date_from="2015-01-01",
        application_date_to="2020-12-31",
        renewal_due_from="2028-03-01",
        renewal_due_to="2028-03-31",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["docket_id"] for row in body["rows"]] == [ids[1]]
    assert body["counts"] == {
        "upcoming": 1,
        "active": 0,
        "due_today": 0,
        "overdue": 0,
        "missing": 0,
        "failed": 0,
    }
    assert body["rows"][0]["source_application_state"] == "imported_unverified"
    assert body["rows"][0]["source_renewal_state"] == "imported_unverified"


@pytest.mark.parametrize(
    "changed",
    [
        {"query": "IP18 source selected"},
        {"category": "missing"},
        {"application_date_from": "2020-01-01"},
        {"renewal_due_to": "2028-03-31"},
        {"horizon_days": 30},
        {"limit": 2},
    ],
)
def test_tracker_rejects_cursor_from_different_filter_scope(tracker_client, monkeypatch, changed):
    actor, _ = _records(tracker_client, monkeypatch)
    params = {"query": "IP18 source", "limit": 1}
    first = _tracker(tracker_client, actor, **params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    incompatible = _tracker(tracker_client, actor, **{**params, **changed, "cursor": cursor})
    assert incompatible.status_code == 400, incompatible.text
    assert incompatible.json()["detail"] == "Tracker continuation no longer matches these filters."


def test_tracker_cursor_distinguishes_lower_not_casefold_searches(tracker_client, monkeypatch):
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(tracker_client)
    searches = ("Stra\u00dfe", "STRASSE")
    preview = _upload(
        tracker_client,
        actor,
        ["Trademark", "Application Date", "Renewal Date"],
        [
            [f"IP18 {query} source {index}", "2020-01-01", "2028-03-15"]
            for query in searches
            for index in range(2)
        ],
    )
    committed = _commit(tracker_client, actor, preview)
    ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(ids) == len(set(ids)) == 4
    for query, expected in zip(searches, (ids[:2], ids[2:]), strict=True):
        response = _tracker(tracker_client, actor, query=query, limit=100)
        assert response.status_code == 200, response.text
        assert [row["docket_id"] for row in response.json()["rows"]] == sorted(expected)
        assert response.json()["next_cursor"] is None

    first = _tracker(tracker_client, actor, query=searches[0], limit=1)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    assert first.json()["rows"][0]["docket_id"] == min(ids[:2])
    same_search = _tracker(tracker_client, actor, query=searches[0], limit=1, cursor=cursor)
    assert same_search.status_code == 200, same_search.text
    assert [row["docket_id"] for row in same_search.json()["rows"]] == [max(ids[:2])]
    assert same_search.json()["next_cursor"] is None

    incompatible = _tracker(tracker_client, actor, query=searches[1], limit=1, cursor=cursor)
    assert incompatible.status_code == 400, incompatible.text
    assert incompatible.json()["detail"] == "Tracker continuation no longer matches these filters."


@pytest.mark.parametrize("field", ["application_date", "renewal_due"])
def test_tracker_rejects_reversed_date_ranges(tracker_client, monkeypatch, field):
    actor, _ = _records(tracker_client, monkeypatch)
    response = _tracker(
        tracker_client, actor, **{field + "_from": "2028-04-01", field + "_to": "2028-03-01"}
    )
    assert response.status_code == 422, response.text


def test_existing_date_filters_saved_view_and_csv_preserve_current_source(
    tracker_client, monkeypatch
):
    client = tracker_client
    actor, ids = _records(client, monkeypatch)
    filters = {
        "query": "IP18 source",
        "application_date_from": "2015-01-01",
        "application_date_to": "2020-12-31",
        "renewal_due_from": "2028-03-01",
        "renewal_due_to": "2028-03-31",
        "renewal_tracker_state": ["upcoming"],
    }
    columns = ["mark", "application_numbers", "application_date", "renewal_due_date"]
    saved = client.post(
        "/api/ip/portfolio/views",
        headers=actor["headers"],
        json={"name": "IP18 reviewed source dates", "filters": filters, "columns": columns},
    )
    assert saved.status_code == 201, saved.text
    view = saved.json()
    listing = client.get("/api/ip/portfolio/views", headers=actor["headers"])
    retained = next(row for row in listing.json()["views"] if row["id"] == view["id"])
    assert all(retained["filters"][key] == value for key, value in filters.items())
    assert retained["columns"] == columns
    portfolio = client.get("/api/ip/portfolio", headers=actor["headers"], params=filters)
    assert portfolio.status_code == 200, portfolio.text
    assert [row["docket_id"] for row in portfolio.json()["rows"]] == [ids[1]]
    payload = {"filters": retained["filters"], "columns": retained["columns"], "row_limit": 50}
    preview = client.post(
        "/api/ip/portfolio/exports/preview", headers=actor["headers"], json=payload
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 1
    queued = client.post(
        "/api/ip/portfolio/exports",
        headers=actor["headers"],
        json={**payload, "preview_token": preview.json()["preview_token"]},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]
    job = client.get(f"/api/ip/portfolio/exports/{job_id}", headers=actor["headers"])
    assert job.json()["status"] == "completed", job.text
    download = client.get(f"/api/ip/portfolio/exports/{job_id}/download", headers=actor["headers"])
    assert download.status_code == 200, download.text
    assert download.headers["cache-control"] == "private, no-store"
    records = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig"))))
    assert records == [
        {
            "Mark": "IP18 source selected",
            "Application numbers": "IP18-1002",
            "Application Date": "2020-01-01",
            "Renewal Due Date": "2028-03-16",
        }
    ]


@pytest.mark.parametrize(
    "category", ["upcoming", "active", "due_today", "overdue", "missing", "failed"]
)
def test_every_category_continues_to_exact_filtered_current_inventory(
    tracker_client, monkeypatch, category
):
    client = tracker_client
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    due = "" if category == "missing" else "2028-02-20" if category == "overdue" else "2028-03-15"
    preview = _upload(
        client,
        actor,
        ["Trademark", "Application Date", "Renewal Date"],
        [[f"IP18 category {index}", "2020-01-01", due] for index in range(4)]
        + [["IP18 category outside dates", "2010-01-01", due]],
    )
    committed = _commit(client, actor, preview)
    ids = [row["created_docket_id"] for row in committed["rows"]]
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    if category in {"active", "due_today", "failed"}:
        with get_session_factory()() as session:
            ip_renewal_tracker.reconcile_renewal_series(session)
            if category == "failed":
                intents = session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.company_id == actor["company"]["id"],
                        NotificationDeliveryIntent.source_type == ip_renewal_tracker.SOURCE,
                        NotificationDeliveryIntent.status == "queued",
                    )
                ).all()
                assert len(intents) == 5
                for intent in intents:
                    notification_delivery.record_notification_delivery_failure(
                        session,
                        intent=intent,
                        raw_error="Deterministic local receipt failure",
                        retryable=False,
                    )
                    assert intent.status == NotificationDeliveryStatus.DEAD_LETTER
                session.commit()
    closed = client.post(
        f"/api/ip/dockets/{ids[3]}/lifecycle",
        headers=actor["headers"],
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Close source before category paging",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:ip18-closed",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    params = {
        "query": "IP18 category",
        "category": category,
        "limit": 2,
        "application_date_from": "2019-01-01",
        "application_date_to": "2021-01-01",
    }
    seen, first_counts, cursor = [], None, None
    for _ in range(4):
        response = _tracker(client, actor, **params, **({"cursor": cursor} if cursor else {}))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["counts"][category] == 3
        if first_counts is None:
            first_counts = body["counts"]
        assert body["counts"] == first_counts
        assert 0 < len(body["rows"]) <= 2
        assert all(row["docket_operational"] for row in body["rows"])
        assert all(row["source_application_state"] == "imported_unverified" for row in body["rows"])
        if category == "failed":
            assert all(row["status"] == "failed" for row in body["rows"])
        seen.extend(row["docket_id"] for row in body["rows"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert cursor is None
    assert seen == sorted(ids[:3])
    assert len(seen) == len(set(seen)) == 3


def test_tracker_cursor_tampering_and_calendar_day_change_fail_closed(tracker_client, monkeypatch):
    actor, _ = _records(tracker_client, monkeypatch)
    first = _tracker(tracker_client, actor, query="IP18 source", limit=1)
    cursor = first.json()["next_cursor"]
    assert cursor
    tampered = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    for invalid in (tampered, first.json()["rows"][0]["docket_id"], "invalid", "a" * 513):
        response = _tracker(tracker_client, actor, query="IP18 source", limit=1, cursor=invalid)
        assert response.status_code in (400, 422), response.text
    _clock(monkeypatch, datetime(2028, 1, 2, tzinfo=UTC))
    response = _tracker(tracker_client, actor, query="IP18 source", limit=1, cursor=cursor)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Tracker continuation no longer matches these filters."


def test_tracker_cursor_is_bound_to_the_actual_tenant_member(tracker_client, monkeypatch):
    actor, _ = _records(tracker_client, monkeypatch)
    first = _tracker(tracker_client, actor, query="IP18 source", limit=1)
    cursor = first.json()["next_cursor"]
    assert cursor
    with TestClient(tracker_client.app) as separate:
        suffix = uuid4().hex
        created = separate.post(
            "/api/bootstrap/company",
            json={
                "company_name": "IP18 separate tenant",
                "company_slug": f"ip18-{suffix}",
                "company_type": "law_firm",
                "owner_full_name": "IP18 other owner",
                "owner_email": f"owner-{suffix}@ip18other.in",
                "owner_password": "SyntheticOtherTracker123!",
            },
        )
        assert created.status_code == 200, created.text
        other = created.json()
        other["headers"] = {
            "Authorization": f"Bearer {other['access_token']}",
            "X-CaseOps-Automated-Test": "no-paid-providers",
        }
        identity = separate.get("/api/auth/me", headers=other["headers"])
        assert identity.status_code == 200, identity.text
        assert identity.json()["company"]["id"] == other["company"]["id"]
        assert identity.json()["membership"]["id"] == other["membership"]["id"]
        assert other["company"]["id"] != actor["company"]["id"]
        rejected = _tracker(separate, other, query="IP18 source", limit=1, cursor=cursor)
        assert rejected.status_code == 400, rejected.text
        fresh = _tracker(separate, other, query="IP18 source", limit=1)
        assert fresh.status_code == 200, fresh.text
        assert fresh.json()["rows"] == []
        assert all(value == 0 for value in fresh.json()["counts"].values())


def test_category_continuation_rechecks_closed_source_and_global_counts(
    tracker_client, monkeypatch
):
    actor, _ = _records(tracker_client, monkeypatch)
    params = {"query": "IP18 source", "category": "upcoming", "limit": 1}
    first = _tracker(tracker_client, actor, **params)
    assert first.status_code == 200, first.text
    all_rows = _tracker(tracker_client, actor, **{**params, "limit": 100}).json()["rows"]
    assert len(all_rows) == 2 and first.json()["counts"]["upcoming"] == 2
    target = all_rows[1]["docket_id"]
    closed = tracker_client.post(
        f"/api/ip/dockets/{target}/lifecycle",
        headers=actor["headers"],
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Close source between tracker pages",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:ip18-current-close",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    second = _tracker(tracker_client, actor, **params, cursor=first.json()["next_cursor"])
    assert second.status_code == 200, second.text
    assert second.json()["rows"] == []
    assert second.json()["counts"]["upcoming"] == 1
    assert second.json()["next_cursor"] is None
