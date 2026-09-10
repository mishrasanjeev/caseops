from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CaseTrackingSupportMatrix,
    Matter,
    TrackedCaseBackfillCursor,
    TrackedCaseBookmark,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    _system_contexts,
    backfill_existing_matter_case_tracking,
    poll_tracked_cases,
)
from tests.test_20260904_auto_next_hearing_sync import (
    DatedSyncProvider,
    _enable_tracking,
    _future_snapshot,
)
from tests.test_auth_company import auth_headers, bootstrap_company


@contextmanager
def legacy_tracking_creation(monkeypatch):
    try:
        with monkeypatch.context() as seed_policy:
            seed_policy.setenv("CASEOPS_CASE_TRACKING_ENABLED", "false")
            get_settings.cache_clear()
            yield
    finally:
        get_settings.cache_clear()


def test_blocked_oldest_batch_does_not_starve_supported_later_matter(client, monkeypatch):
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    headers = auth_headers(token)
    # Use real public creation and distinct case identities, never invalid ORM rows.
    created_ids = []
    initial_tracking = get_settings().case_tracking_enabled
    with legacy_tracking_creation(monkeypatch):
        for index in range(51):
            response = client.post(
                "/api/matters/",
                headers=headers,
                json={
                    "title": f"Backfill admission {index}",
                    "matter_code": f"BACKFILL-BOUND-{index:03}",
                    "practice_area": "litigation",
                    "forum_level": "high_court",
                    "court_name": "Delhi High Court" if index == 50 else "Bombay High Court",
                    "case_number": (
                        "WP(C) 9123/2026" if index == 50 else f"WP(C) {index + 1000}/2026"
                    ),
                    "status": "intake",
                },
            )
            assert response.status_code == 200, response.text
            created_ids.append(response.json()["id"])
    assert get_settings().case_tracking_enabled is initial_tracking
    with get_session_factory()() as seed_check:
        assert seed_check.scalar(select(func.count()).select_from(TrackedCaseBookmark)) == 0
    _enable_tracking(monkeypatch)
    try:
        with get_session_factory()() as session:
            support = session.scalar(select(CaseTrackingSupportMatrix))
            assert support is not None
            support.court = "Delhi High Court"
            session.commit()
            provider = DatedSyncProvider(
                _future_snapshot(hearing_on=datetime.now(UTC).date() + timedelta(days=12))
            )
            first = poll_tracked_cases(session, provider=provider, force=True)
            second = poll_tracked_cases(session, provider=provider, force=True)
            bookmark = session.scalar(
                select(TrackedCaseBookmark).where(TrackedCaseBookmark.matter_id == created_ids[-1])
            )
            assert bookmark is not None, [
                run.metadata.get("auto_link_backfill") for run in (*first, *second)
            ]
            target = session.get(Matter, created_ids[-1])
            assert target.next_hearing_on == provider.snapshot.next_hearing_on
            assert target.status == "intake"
            assert target.lifecycle_version == 0
            assert len(provider.search_calls) == 1
            assert first[0].metadata["auto_link_backfill"]["evaluated_count"] == 50
            assert second[0].metadata["auto_link_backfill"]["evaluated_count"] == 1
            cursor = session.get(TrackedCaseBackfillCursor, (boot["company"]["id"], "ecourtsindia"))
            assert cursor.last_matter_id is None

            # A new complete cycle reconsiders previously unsupported records.
            support.court = "*"
            session.commit()
            context = _system_contexts(session)[0]
            third = backfill_existing_matter_case_tracking(
                session, context=context, provider_key="ecourtsindia"
            )
            assert third.evaluated_count == 50
            assert third.linked_count == 50
            session.commit()
            fourth = backfill_existing_matter_case_tracking(
                session, context=context, provider_key="ecourtsindia"
            )
            assert fourth.evaluated_count == 1
            assert fourth.linked_count == 0
            assert fourth.skipped_count == 1
            session.commit()
            assert session.scalar(select(func.count()).select_from(TrackedCaseBookmark)) == 51
            assert set(session.execute(select(Matter.status, Matter.lifecycle_version))) == {
                ("intake", 0)
            }
    finally:
        get_settings.cache_clear()


def test_failed_backfill_rolls_back_cursor_and_keeps_poll_session_usable(client, monkeypatch):
    bootstrap_company(client)
    _enable_tracking(monkeypatch)
    provider = DatedSyncProvider(_future_snapshot(hearing_on=None))
    with get_session_factory()() as probe:
        engine = probe.get_bind()

    def fail_cursor_update(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE tracked_case_backfill_cursors"):
            connection.exec_driver_sql("SELECT * FROM deliberate_missing_backfill_table")

    event.listen(engine, "before_cursor_execute", fail_cursor_update)
    try:
        with get_session_factory()() as session:
            runs = poll_tracked_cases(session, provider=provider, force=True)
            assert runs[0].metadata["auto_link_backfill"]["status"] == "failed"
            assert session.scalar(select(func.count()).select_from(TrackedCaseBackfillCursor)) == 0
            assert session.scalar(select(func.count()).select_from(Matter)) == 0
            assert provider.bulk_calls == provider.search_calls == []
            assert session.is_active
    finally:
        event.remove(engine, "before_cursor_execute", fail_cursor_update)
        get_settings.cache_clear()


@pytest.mark.parametrize("count", [0, 50, 51, 10000])
def test_raw_scan_is_bounded_and_advances_even_for_incomplete_rows(client, monkeypatch, count):
    boot = bootstrap_company(client)
    _enable_tracking(monkeypatch)
    company_id = str(boot["company"]["id"])
    try:
        with get_session_factory()() as session:
            # All required fields and the real tenant parent are present. No
            # provider identity is claimed for these valid intake records.
            session.add_all(
                [
                    Matter(
                        company_id=company_id,
                        title=f"Incomplete intake {index}",
                        matter_code=f"SCAN-{index:05}",
                        practice_area="litigation",
                        forum_level="high_court",
                        status="intake",
                    )
                    for index in range(count)
                ]
            )
            session.commit()
            context = _system_contexts(session)[0]
            queries = []

            def capture(connection, cursor, statement, parameters, context, executemany):
                queries.append(statement)

            event.listen(session.get_bind(), "before_cursor_execute", capture)
            try:
                first = backfill_existing_matter_case_tracking(
                    session, context=context, provider_key="ecourtsindia"
                )
                session.commit()
            finally:
                event.remove(session.get_bind(), "before_cursor_execute", capture)
            assert first.evaluated_count == min(count, 50)
            assert first.skipped_count == min(count, 50)
            assert first.linked_count == first.blocked_count == 0
            assert len(queries) <= 10, queries
            cursor = session.get(TrackedCaseBackfillCursor, (company_id, "ecourtsindia"))
            previous = cursor.last_matter_id
            second = backfill_existing_matter_case_tracking(
                session, context=context, provider_key="ecourtsindia"
            )
            session.commit()
            assert second.evaluated_count == (1 if count == 51 else min(count, 50))
            if count > 50:
                assert cursor.last_matter_id != previous
            assert session.scalar(select(func.count()).select_from(TrackedCaseBookmark)) == 0
    finally:
        get_settings.cache_clear()
