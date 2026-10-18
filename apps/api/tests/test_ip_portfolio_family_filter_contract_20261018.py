"""List and family views must admit the same current source-date filters."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign
from tests.test_ip_renewal_tracker_20261015 import _clock


def test_family_date_and_category_filters_match_the_list(client, monkeypatch):
    now = datetime(2026, 10, 17, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    actor = _actor(client)
    prefix = f"Family filter {uuid4().hex}"
    due = (now.date() + timedelta(days=60)).isoformat()
    later = (now.date() + timedelta(days=180)).isoformat()
    saved = _commit(
        client,
        actor,
        _upload(
            client,
            actor,
            ["Trademark", "Application Date", "Renewal Date"],
            [
                [f"{prefix} target", "2020-01-15", due],
                [f"{prefix} old application", "2010-01-15", due],
                [f"{prefix} missing renewal", "2020-01-15", ""],
                [f"{prefix} later renewal", "2020-01-15", later],
            ],
        ),
    )
    assert saved["job"]["committed_rows"] == 4
    ids = [row["created_docket_id"] for row in saved["rows"]]
    assert len(set(ids)) == 4 and all(ids)
    application = {"application_date_from": "2020-01-01", "application_date_to": "2020-12-31"}
    renewal = {"renewal_due_from": due, "renewal_due_to": due}
    profiles = [
        ({**application, **renewal, "renewal_tracker_state": ["upcoming"]}, [ids[0]]),
        ({**application, "renewal_tracker_state": ["missing"]}, [ids[2]]),
        (renewal, ids[:2]),
        (application, [ids[0], ids[2], ids[3]]),
    ]
    for filters, expected in profiles:
        params = {"query": prefix, **filters}
        listing = client.get("/api/ip/portfolio", headers=actor["headers"], params=params)
        assert listing.status_code == 200, listing.text
        assert sorted(row["docket_id"] for row in listing.json()["rows"]) == sorted(expected)
        family = client.get(
            "/api/ip/portfolio/families",
            headers=actor["headers"],
            params={**params, "grouping": "mark", "limit": 100},
        )
        assert family.status_code == 200, family.text
        body = family.json()
        assert body["next_cursor"] is None
        assert sorted(
            member["docket_id"] for group in body["families"] for member in group["members"]
        ) == sorted(expected)
    with TestClient(client.app) as foreign_client:
        other = _bootstrap_foreign(foreign_client)
        assert other["company"]["id"] != actor["company"]["id"]
        foreign = foreign_client.get(
            "/api/ip/portfolio/families",
            headers={
                **auth_headers(other["access_token"]),
                "X-CaseOps-Automated-Test": "no-paid-providers",
            },
            params={"query": prefix},
        )
        assert foreign.status_code == 200 and foreign.json()["families"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"application_date_from": "2026-13-40"},
        {"application_date_to": "invalid-date"},
        {"renewal_due_from": "invalid-date"},
        {"renewal_due_to": "invalid-date"},
        {"renewal_tracker_state": "invented-category"},
    ],
)
def test_family_date_filters_reject_invalid_values(client, params):
    actor = _actor(client)
    response = client.get("/api/ip/portfolio/families", headers=actor["headers"], params=params)
    assert response.status_code == 422, response.text


def test_family_openapi_declares_all_shared_date_filters(client):
    parameters = client.app.openapi()["paths"]["/api/ip/portfolio/families"]["get"]["parameters"]
    names = {item["name"] for item in parameters if item["in"] == "query"}
    assert {
        "application_date_from",
        "application_date_to",
        "renewal_due_from",
        "renewal_due_to",
        "renewal_tracker_state",
    } <= names
