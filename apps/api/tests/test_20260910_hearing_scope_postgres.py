"""Shared-actor admission and the post-transport bookmark-read/write boundary."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from caseops_api.db.models import (
    Matter,
    ProviderSpendReservation,
    TrackedCaseBookmark,
    TrackedCaseProviderSnapshot,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import case_tracking
from tests.test_20260904_auto_next_hearing_sync import DatedSyncProvider
from tests.test_20260910_hearing_matching import snapshot
from tests.test_20260910_hearing_matching_races import setup_case
from tests.test_auth_company import auth_headers
from tests.test_case_tracking import _context_from_bootstrap
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_today_view_matter_access import _invite_member

pytestmark = pytest.mark.postgres


def bookmark(client, headers, matter_id=None):
    response = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010091232026",
            "case_number": "WP(C) 9123/2026",
            "court_name": "Delhi High Court",
            "case_title": "Public provider case",
            "matter_id": matter_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("own_scope", ["unlinked", "authorized_matter"])
def test_other_actor_private_bookmark_does_not_block_or_leak_into_own_refresh(
    isolated_postgres_client, monkeypatch, own_scope
):
    client = isolated_postgres_client
    boot, owner_headers, private = setup_case(client, monkeypatch)
    owner_bookmark = bookmark(client, owner_headers, private["id"])
    with get_session_factory()() as session:
        hidden = session.get(Matter, private["id"])
        hidden.restricted_access = True
        hidden.title = "PRIVATE-MATTER-SENTINEL"
        hidden.opposing_party = "PRIVATE-PARTY-SENTINEL"
        session.commit()
    _, token = _invite_member(client, str(boot["access_token"]), "hearing-member@example.com")
    member_headers = auth_headers(token)
    assert client.get(f"/api/matters/{private['id']}", headers=member_headers).status_code == 404
    own_matter_id = None
    if own_scope == "authorized_matter":
        made = client.post(
            "/api/matters/",
            headers=owner_headers,
            json={
                "title": "Authorized Matter",
                "matter_code": "AUTHORIZED-SEP10",
                "practice_area": "litigation",
                "forum_level": "high_court",
                "status": "active",
            },
        )
        assert made.status_code == 200, made.text
        own_matter_id = made.json()["id"]
        with get_session_factory()() as session:
            session.get(Matter, own_matter_id).cnr_number = "DLHC010091232026"
            session.commit()
    own = bookmark(client, member_headers, own_matter_id)
    assert own["tracked_case_id"] == owner_bookmark["tracked_case_id"]
    provider = DatedSyncProvider(
        replace(snapshot(), next_hearing_on=date.today() + timedelta(days=7))
    )
    monkeypatch.setattr(case_tracking, "get_case_tracking_provider", lambda: provider)
    response = client.post(
        f"/api/case-tracking/bookmarks/{own['id']}/refresh", headers=member_headers
    )
    assert response.status_code == 200, response.text
    assert (
        "PRIVATE-MATTER-SENTINEL" not in response.text
        and "PRIVATE-PARTY-SENTINEL" not in response.text
    )
    with get_session_factory()() as session:
        assert session.get(Matter, private["id"]).next_hearing_on is None
        if own_matter_id:
            assert session.get(Matter, own_matter_id).next_hearing_on == date.today() + timedelta(
                days=7
            )
    rows = client.get("/api/case-tracking/bookmarks", headers=member_headers)
    assert rows.status_code == 200 and len(rows.json()["bookmarks"]) == 1
    assert "PRIVATE-MATTER-SENTINEL" not in rows.text and "PRIVATE-PARTY-SENTINEL" not in rows.text


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize("change", ["archive", "retarget"])
def test_bookmark_write_after_posttransport_scope_read_cannot_publish_stale_date(
    isolated_postgres_client, monkeypatch, boundary, change
):
    client = isolated_postgres_client
    boot, headers, original = setup_case(client, monkeypatch)
    linked = bookmark(client, headers, original["id"])
    replacement = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Retarget destination",
            "matter_code": "RETARGET-SEP10",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert replacement.status_code == 200, replacement.text
    replacement_id = replacement.json()["id"]
    captured, release = Event(), Event()
    real_capture = case_tracking.capture_hearing_scopes
    calls = []

    def pause_after_scope_query(session, **kwargs):
        if not kwargs.get("lock"):
            return real_capture(session, **kwargs)
        scalars = session.scalars
        paused = False

        def inspect_query(statement, *args, **options):
            nonlocal paused
            result = scalars(statement, *args, **options)
            descriptions = getattr(statement, "column_descriptions", ())
            if not paused and descriptions and descriptions[0].get("entity") is TrackedCaseBookmark:
                paused = True
                rows = list(result)
                assert calls, "Gate must occur after provider delivery, not during transport"
                captured.set()
                assert release.wait(20), "Concurrent bookmark writer did not finish"
                return iter(rows)
            return result

        session.scalars = inspect_query
        try:
            return real_capture(session, **kwargs)
        finally:
            session.scalars = scalars

    monkeypatch.setattr(case_tracking, "capture_hearing_scopes", pause_after_scope_query)
    result = replace(snapshot(), next_hearing_on=date.today() + timedelta(days=7))

    def worker():
        with get_session_factory()() as session:

            class Provider(DatedSyncProvider):
                def get_case_by_cnr(self, *, cnr):
                    assert not session.in_transaction()
                    calls.append(cnr)
                    return self.snapshot

                def refresh_cases(self, *, cnrs):
                    assert not session.in_transaction()
                    calls.extend(cnrs)
                    return super().refresh_cases(cnrs=cnrs)

            provider = Provider(result)
            if boundary == "scheduled":
                return case_tracking.poll_tracked_cases(session, provider=provider, force=True)
            try:
                return case_tracking.refresh_bookmark(
                    session,
                    context=_context_from_bootstrap(boot),
                    bookmark_id=linked["id"],
                    provider=provider,
                    enforce_manual_limit=False,
                )
            except HTTPException as error:
                return error

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        try:
            assert captured.wait(25), "Post-transport scope read was not reached"
            with get_session_factory()() as writer:
                row = writer.get(TrackedCaseBookmark, linked["id"])
                if change == "archive":
                    row.is_archived = True
                    row.active_scope_key = None
                else:
                    row.matter_id = replacement_id
                    row.scope_key = f"matter:{replacement_id}"
                    row.active_scope_key = row.scope_key
                writer.commit()
            assert not future.done(), "The writer must commit between scope read and publication"
        finally:
            release.set()
        outcome = future.result(timeout=25)
    with get_session_factory()() as session:
        assert session.get(Matter, original["id"]).next_hearing_on is None
        assert session.get(Matter, replacement_id).next_hearing_on is None
        assert session.scalar(select(func.count(TrackedCaseProviderSnapshot.id))) == 0
        assert session.scalar(select(ProviderSpendReservation.status)) == "settled"
    if boundary == "manual":
        assert isinstance(outcome, HTTPException) and outcome.status_code == 409


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize("change", ["archive", "retarget"])
def test_publication_holds_bookmark_fence_until_date_write(
    isolated_postgres_client, monkeypatch, boundary, change
):
    client = isolated_postgres_client
    boot, headers, original = setup_case(client, monkeypatch)
    linked = bookmark(client, headers, original["id"])
    destination = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Locked retarget destination",
            "matter_code": "LOCKED-RETARGET-SEP10",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert destination.status_code == 200, destination.text
    destination_id = destination.json()["id"]
    real_apply = case_tracking.apply_snapshot
    inspected = []

    def inspect_publication(session, **kwargs):
        with get_session_factory()() as writer:
            writer.execute(text("SET LOCAL lock_timeout = '200ms'"))
            values = (
                {"is_archived": True, "active_scope_key": None}
                if change == "archive"
                else {"matter_id": destination_id}
            )
            with pytest.raises(DBAPIError) as blocked:
                writer.execute(
                    update(TrackedCaseBookmark)
                    .where(TrackedCaseBookmark.id == linked["id"])
                    .values(**values)
                )
            assert blocked.value.orig.sqlstate == "55P03"
            writer.rollback()
        inspected.append(change)
        return real_apply(session, **kwargs)

    monkeypatch.setattr(case_tracking, "apply_snapshot", inspect_publication)
    nearest = date.today() + timedelta(days=7)
    provider = DatedSyncProvider(replace(snapshot(), next_hearing_on=nearest))
    with get_session_factory()() as session:
        if boundary == "scheduled":
            case_tracking.poll_tracked_cases(session, provider=provider, force=True)
        else:
            case_tracking.refresh_bookmark(
                session,
                context=_context_from_bootstrap(boot),
                bookmark_id=linked["id"],
                provider=provider,
                enforce_manual_limit=False,
            )
    assert inspected == [change]
    with get_session_factory()() as session:
        assert session.get(Matter, original["id"]).next_hearing_on == nearest
        assert session.get(Matter, destination_id).next_hearing_on is None
        current = session.get(TrackedCaseBookmark, linked["id"])
        assert current.matter_id == original["id"] and current.is_archived is False
