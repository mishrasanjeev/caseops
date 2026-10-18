"""Family continuations retain the exact SQL ordering and authenticated scope."""

import hashlib
import hmac
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import IpAsset, IpDocketRecord, IpWorkspaceConfiguration
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_recipient_renewal_content_20261014 import _bootstrap_foreign
from tests.test_ip_renewal_tracker_20261015 import _clock


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def family_cursor_client(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def family_scope(family_cursor_client, monkeypatch):
    client = family_cursor_client
    _clock(monkeypatch, datetime(2028, 1, 1, 4, tzinfo=UTC))
    actor = _actor(client)
    committed = _commit(
        client,
        actor,
        _upload(
            client,
            actor,
            ["Trademark", "Application Date", "Renewal Due Date"],
            [
                [name, "2020-01-15", "2028-03-15"]
                for name in ("Stra\u00dfe cursor proof", "Tango cursor proof", "Zulu cursor proof")
            ],
        ),
    )
    assert committed["job"]["committed_rows"] == 3
    ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(set(ids)) == 3 and all(ids)
    return client, actor, ids


def _page(client, headers, **params):
    return client.get(
        "/api/ip/portfolio/families",
        headers=headers,
        params={"grouping": "mark", "limit": 1, **params},
    )


def _first(client, actor):
    response = _page(client, actor["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["families"]) == 1 and body["next_cursor"]
    return body


def _member_headers(client, actor):
    email = f"family-cursor-{uuid4().hex}@familycursor.in"
    password = "SyntheticFamilyCursor123!"
    created = client.post(
        "/api/companies/current/users",
        headers=actor["headers"],
        json={
            "full_name": "Family cursor member",
            "email": email,
            "password": password,
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "company_slug": actor["company"]["slug"]},
    )
    assert login.status_code == 200, login.text
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    client.cookies.clear()
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["membership"]["id"] == created.json()["membership_id"]
    return headers


def test_unicode_family_pages_use_exact_emitted_sql_sort_value(family_scope):
    client, actor, ids = family_scope
    body = _first(client, actor)
    first = body["families"][0]
    assert first["label"] == "Stra\u00dfe cursor proof"
    cursor = body["next_cursor"]
    seen = []
    for _ in range(3):
        group = body["families"][0]
        assert group["family_key"] not in seen, "A prior Unicode family repeated."
        seen.append(group["family_key"])
        if body["next_cursor"] is None:
            break
        response = _page(client, actor["headers"], cursor=body["next_cursor"])
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["families"]) == 1
    assert len(seen) == 3 and body["next_cursor"] is None
    complete = _page(client, actor["headers"], limit=100)
    assert complete.status_code == 200, complete.text
    assert seen == [group["family_key"] for group in complete.json()["families"]]
    assert sorted(
        member["docket_id"] for group in complete.json()["families"] for member in group["members"]
    ) == sorted(ids)
    with get_session_factory()() as session:
        sql_label = session.scalar(
            select(func.lower(IpAsset.title)).where(
                IpAsset.company_id == actor["company"]["id"],
                IpAsset.id == first["family_key"],
            )
        )
    payload = json.loads(urlsafe_b64decode(cursor.split(".")[0]))
    assert payload[-2] == sql_label


def test_unfiltered_family_page_does_not_read_renewal_policy_or_clock(family_scope, monkeypatch):
    client, actor, _ids = family_scope

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Unfiltered family reads must not resolve renewal policy or time.")

    monkeypatch.setattr(ip_renewal_tracker, "policy", unexpected)
    monkeypatch.setattr(ip_renewal_tracker, "_now", unexpected)
    body = _first(client, actor)
    assert len(body["families"]) == 1 and body["next_cursor"]


def test_family_page_rejects_a_local_day_change_during_the_request(family_scope, monkeypatch):
    client, actor, _ids = family_scope
    before = datetime(2028, 1, 1, 4, tzinfo=UTC)
    after = before + timedelta(days=1)
    calls = []

    def now():
        calls.append(True)
        return before if len(calls) < 3 else after

    monkeypatch.setattr(ip_renewal_tracker, "_now", now)
    params = {"renewal_tracker_state": "upcoming"}
    response = _page(client, actor["headers"], **params)
    assert len(calls) >= 3
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["detail"] == "Family filter day changed; reload."
    assert "families" not in body and "next_cursor" not in body
    fresh = _page(client, actor["headers"], **params)
    assert fresh.status_code == 200, fresh.text
    assert len(fresh.json()["families"]) == 1 and fresh.json()["next_cursor"]


@pytest.mark.parametrize(
    "changed",
    [
        {"application_date_from": "2020-01-01"},
        {"application_date_to": "2020-12-31"},
        {"renewal_due_from": "2028-03-01"},
        {"renewal_due_to": "2028-03-31"},
        {"renewal_tracker_state": "upcoming"},
        {"grouping": "client"},
        {"query": "cursor proof"},
        {"include_inactive": True},
        {"limit": 2},
    ],
)
def test_family_cursor_rejects_changed_complete_filter_scope(family_scope, changed):
    client, actor, _ids = family_scope
    first = _first(client, actor)
    response = _page(client, actor["headers"], cursor=first["next_cursor"], **changed)
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("other_actor", ["member", "company"])
def test_family_cursor_rejects_another_authenticated_actor(family_scope, other_actor):
    client, actor, _ids = family_scope
    first = _first(client, actor)
    if other_actor == "member":
        headers = _member_headers(client, actor)
        response = _page(client, headers, cursor=first["next_cursor"])
        fresh = _page(client, headers)
        assert fresh.status_code == 200 and len(fresh.json()["families"]) == 1
    else:
        with TestClient(client.app) as foreign_client:
            other = _bootstrap_foreign(foreign_client)
            assert other["company"]["id"] != actor["company"]["id"]
            headers = {
                "Authorization": f"Bearer {other['access_token']}",
                "X-CaseOps-Automated-Test": "no-paid-providers",
            }
            response = _page(foreign_client, headers, cursor=first["next_cursor"])
            fresh = _page(foreign_client, headers)
            assert fresh.status_code == 200 and fresh.json()["families"] == []
    assert response.status_code == 400, response.text


@pytest.mark.parametrize("changed", ["local_day", "policy", "timezone"])
def test_category_family_cursor_rejects_changed_policy_or_local_day(
    family_scope, monkeypatch, changed
):
    client, actor, _ids = family_scope
    params = {"renewal_tracker_state": "upcoming"}
    first = _page(client, actor["headers"], **params)
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor
    if changed == "local_day":
        _clock(monkeypatch, datetime(2028, 1, 2, 4, tzinfo=UTC))
    else:
        with get_session_factory()() as session:
            config = session.scalar(
                select(IpWorkspaceConfiguration).where(
                    IpWorkspaceConfiguration.company_id == actor["company"]["id"]
                )
            )
            if changed == "timezone":
                config.timezone = "UTC"
            else:
                config.renewal_reminder_policy_json = {
                    **config.renewal_reminder_policy_json,
                    "cadence_days": 2,
                }
            config.version += 1
            session.commit()
    response = _page(client, actor["headers"], cursor=cursor, **params)
    assert response.status_code == 400, response.text
    fresh = _page(client, actor["headers"], **params)
    assert fresh.status_code == 200 and len(fresh.json()["families"]) == 1


def test_family_cursor_rejects_legacy_tampered_and_bounded_malformed_tokens(family_scope):
    client, actor, _ids = family_scope
    first = _first(client, actor)
    cursor = first["next_cursor"]
    encoded, _, signature = cursor.partition(".")
    payload = json.loads(urlsafe_b64decode(encoded))
    payload[0] = payload[0] + 1
    tampered = urlsafe_b64encode(json.dumps(payload).encode()).decode()
    if signature:
        tampered += "." + signature
    legacy = urlsafe_b64encode(json.dumps([1, "strasse cursor proof", "legacy"]).encode()).decode()

    def signed(raw):
        digest = hmac.new(get_settings().auth_secret.encode(), raw, hashlib.sha256).hexdigest()
        return urlsafe_b64encode(raw).decode() + "." + digest

    malformed = [
        legacy,
        tampered,
        "x" * 8193,
        "*." + "0" * 64,
        signed(b"{}"),
        signed(json.dumps([1, "ip-portfolio-family", "0" * 64, True, "x", "y"]).encode()),
        signed(b"[" * 1000),
    ]
    for token in malformed:
        response = _page(client, actor["headers"], cursor=token)
        assert response.status_code == 400, response.text
    unchanged = _page(client, actor["headers"], cursor=cursor)
    assert unchanged.status_code == 200, unchanged.text


def test_family_continuation_rechecks_current_acl(family_scope):
    client, actor, ids = family_scope
    headers = _member_headers(client, actor)
    first = _page(client, headers)
    assert first.status_code == 200, first.text
    first = first.json()
    assert len(first["families"]) == 1 and first["next_cursor"]
    retained_id = first["families"][0]["members"][0]["docket_id"]
    with get_session_factory()() as session:
        rows = session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == actor["company"]["id"],
                IpDocketRecord.id.in_(ids),
                IpDocketRecord.id != retained_id,
            )
        ).all()
        assert len(rows) == 2
        for row in rows:
            row.restricted = True
        session.commit()
    next_page = _page(client, headers, cursor=first["next_cursor"])
    assert next_page.status_code == 200, next_page.text
    assert next_page.json()["families"] == [] and next_page.json()["next_cursor"] is None
    fresh = _page(client, headers, limit=100)
    assert fresh.status_code == 200, fresh.text
    assert [
        member["docket_id"] for group in fresh.json()["families"] for member in group["members"]
    ] == [retained_id]
