"""B4-ADJ-20: manual-only journal watch never records a polling run, and every
path that claims an automated journal source is gated by watch_operations.

The readiness contract (``ip_capability_catalog``): watch_operations is the
automated feature (capability ip:watch_manage, entitlement ip_watch, rollout
ip_watch_enabled) with manual docketing as its fallback. The watch page tells
the user that manual intake needs only journal-watch management, so manual
profiles and manual captures stay capability-gated, and a profile or capture
that claims an external journal source needs the whole automated decision.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    BillingSubscription,
    IpJournalIngestionRun,
    IpWatchProfile,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_watch import run_journal_watch_scheduler
from tests.test_auth_company import auth_headers
from tests.test_ip_journal_watch import _fixture, _ingest, _profile, _publication


def _runs(company_id: str) -> list[IpJournalIngestionRun]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(IpJournalIngestionRun).where(
                    IpJournalIngestionRun.company_id == company_id
                )
            )
        )


def test_scheduler_records_no_run_for_a_manual_only_profile(client: TestClient) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "MANUALONLY")
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    # A new manual profile schedules no poll at all.
    assert profile["next_poll_at"] is None
    scheduled_at = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    for legacy_next_poll in (None, scheduled_at):
        with get_session_factory()() as session:
            row = session.get(IpWatchProfile, profile["id"])
            assert row is not None
            assert row.provider_key == "manual-journal"
            # Production rows written before the fix carry a next poll.
            row.next_poll_at = legacy_next_poll
            version = row.version
            session.commit()
            result = run_journal_watch_scheduler(session, now=scheduled_at)
            assert result == type(result)(
                due_profiles=0,
                checked_profiles=0,
                cost_paused_profiles=0,
                provider_paused_profiles=0,
                external_calls=0,
                manual_profiles=0,
            )
            session.refresh(row)
            # Nothing was polled, so nothing claims it was.
            assert row.last_polled_at is None
            assert row.poll_status == "active"
            assert row.version == version
    assert _runs(bootstrap["company"]["id"]) == []


def test_scheduler_still_resets_a_manual_profile_cost_period(client: TestClient) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "MANUALQUOTA")
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
        max_cost=100,
    )
    with get_session_factory()() as session:
        row = session.get(IpWatchProfile, profile["id"])
        assert row is not None
        row.frequency = "daily"
        row.spent_cost_minor_in_period = 100
        row.last_polled_at = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
        row.next_poll_at = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
        row.poll_status = "paused_cost_quota"
        row.pause_reason = "Prior UTC-day quota exhausted."
        session.commit()
        version_before = row.version
        result = run_journal_watch_scheduler(
            session, now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        )
        assert (result.due_profiles, result.manual_profiles, result.checked_profiles) == (
            1,
            1,
            0,
        )
        session.refresh(row)
        assert row.poll_status == "active"
        assert row.pause_reason is None
        assert row.spent_cost_minor_in_period == 0
        # The reset changed the profile, so a client holding the old version
        # must reload before changing its status.
        assert row.version == version_before + 1
        assert row.next_poll_at is None
        assert row.last_polled_at == datetime(2026, 10, 31, 18, 0) or (
            row.last_polled_at == datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
        )
    assert _runs(bootstrap["company"]["id"]) == []


def test_workspace_hides_legacy_manual_scheduler_runs_but_keeps_real_intake(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client, "LEGACYRUN")
    _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    company_id = bootstrap["company"]["id"]
    with get_session_factory()() as session:
        # A row the old scheduler wrote: "succeeded 0/0", nothing contacted.
        for minute in range(25):
            stamp = datetime(2026, 10, 30, 6, minute, tzinfo=UTC)
            session.add(
                IpJournalIngestionRun(
                    company_id=company_id,
                    provider_key="manual-journal",
                    idempotency_key=f"scheduler:legacy-{minute}:{stamp:%Y%m%dT%H%M%SZ}",
                    request_sha256="0" * 64,
                    status="succeeded",
                    external_call=False,
                    cost_minor=0,
                    currency="INR",
                    publications_seen=0,
                    publications_created=0,
                    hits_created=0,
                    duplicate_hits=0,
                    stale_source_alert=False,
                    requested_by_membership_id=bootstrap["membership"]["id"],
                    started_at=stamp,
                    completed_at=stamp,
                )
            )
        session.commit()
    intake = _ingest(
        client,
        headers=headers,
        key="legacy-run-real-intake-0001",
        publication=_publication(application_id=application["id"]),
    )
    workspace = client.get("/api/ip/watch", headers=headers)
    assert workspace.status_code == 200, workspace.text
    runs = workspace.json()["ingestion_runs"]
    assert [run["id"] for run in runs] == [intake["run"]["id"]]
    assert not any(run["idempotency_key"].startswith("scheduler:") for run in runs)


def _set_watch_rollout(monkeypatch, enabled: bool) -> None:
    from caseops_api.core.settings import get_settings

    monkeypatch.setenv("CASEOPS_IP_WATCH_ENABLED", "true" if enabled else "false")
    get_settings.cache_clear()


def _grant_ip_watch(company_id: str) -> None:
    with get_session_factory()() as session:
        session.add(
            BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="b4_adj20_test",
                externally_billable=False,
                entitlement_overrides_json={"ip_workspace": True, "ip_watch": True},
            )
        )
        session.commit()


def _external_profile(client, headers, docket_id, recipient_id):
    return client.post(
        "/api/ip/watch/profiles",
        headers=headers,
        json={
            "docket_id": docket_id,
            "name": "Automated source watch",
            "provider_key": "ipindia-journal-feed",
            "word_terms": ["ASTER"],
            "frequency": "daily",
            "recipient_membership_ids": [recipient_id],
            "cost_currency": "INR",
        },
    )


def test_automated_watch_paths_need_watch_operations_manual_paths_do_not(
    client: TestClient, monkeypatch
) -> None:
    bootstrap, headers, docket, application = _fixture(client, "GATE")
    recipient = bootstrap["membership"]["id"]
    _set_watch_rollout(monkeypatch, False)
    try:
        # Manual intake is the documented fallback: no ip_watch entitlement, no rollout.
        manual = _profile(client, headers=headers, docket_id=docket["id"], recipient_id=recipient)
        assert manual["provider_key"] == "manual-journal"
        _ingest(
            client,
            headers=headers,
            key="gate-manual-intake-0001",
            publication=_publication(application_id=application["id"]),
        )

        # A profile that claims an automated source is refused: no ip_watch plan.
        refused = _external_profile(client, headers, docket["id"], recipient)
        assert refused.status_code == 403, refused.text
        detail = refused.json()
        assert detail["code"] == "ip_feature_unavailable"
        assert detail["feature_id"] == "watch_operations"
        assert detail["reason"] == "missing_entitlement"
        assert detail["entitlement_key"] == "ip_watch"

        external_capture = client.post(
            "/api/ip/watch/journal-ingestions",
            headers=headers,
            json={
                "idempotency_key": "gate-external-capture-0001",
                "provider_key": "ipindia-journal-feed",
                "external_call": True,
                "cost_minor": 0,
                "currency": "INR",
                "publications": [_publication(application_id=application["id"])],
            },
        )
        assert external_capture.status_code == 403, external_capture.text
        assert external_capture.json()["feature_id"] == "watch_operations"

        # Entitled, but the rollout is off: a 503 naming the rollout.
        _grant_ip_watch(bootstrap["company"]["id"])
        rollout_off = _external_profile(client, headers, docket["id"], recipient)
        assert rollout_off.status_code == 503, rollout_off.text
        assert rollout_off.json()["reason"] == "rollout_disabled"
        assert rollout_off.json()["rollout_flag"] == "ip_watch_enabled"

        with get_session_factory()() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IpWatchProfile)
                    .where(IpWatchProfile.company_id == bootstrap["company"]["id"])
                )
                == 1
            )

        # Entitled and rolled out: the automated profile is accepted.
        _set_watch_rollout(monkeypatch, True)
        accepted = _external_profile(client, headers, docket["id"], recipient)
        assert accepted.status_code == 201, accepted.text

        # Reactivating a paused automated profile re-checks the same decision.
        paused = client.post(
            f"/api/ip/watch/profiles/{accepted.json()['id']}/status",
            headers=headers,
            json={
                "poll_status": "paused",
                "reason": "Pause while the plan is reviewed",
                "expected_version": accepted.json()["version"],
            },
        )
        assert paused.status_code == 200, paused.text
        _set_watch_rollout(monkeypatch, False)
        resumed = client.post(
            f"/api/ip/watch/profiles/{accepted.json()['id']}/status",
            headers=headers,
            json={
                "poll_status": "active",
                "reason": "Resume",
                "expected_version": paused.json()["version"],
            },
        )
        assert resumed.status_code == 503, resumed.text
        # A manual profile resumes regardless.
        current = client.get("/api/ip/watch", headers=headers).json()["profiles"]
        manual_version = next(row["version"] for row in current if row["id"] == manual["id"])
        manual_paused = client.post(
            f"/api/ip/watch/profiles/{manual['id']}/status",
            headers=headers,
            json={
                "poll_status": "paused",
                "reason": "Pause manual watch",
                "expected_version": manual_version,
            },
        )
        assert manual_paused.status_code == 200, manual_paused.text
        manual_resumed = client.post(
            f"/api/ip/watch/profiles/{manual['id']}/status",
            headers=headers,
            json={
                "poll_status": "active",
                "reason": "Resume manual watch",
                "expected_version": manual_paused.json()["version"],
            },
        )
        assert manual_resumed.status_code == 200, manual_resumed.text
        assert manual_resumed.json()["next_poll_at"] is None
    finally:
        _set_watch_rollout(monkeypatch, False)


def test_manual_intake_stays_role_and_tenant_scoped(client: TestClient) -> None:
    bootstrap, headers, docket, application = _fixture(client, "SCOPE")
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    # A member (no ip:watch_manage) cannot record a manual capture.
    member = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": "Watch Member",
            "email": "watch-member-adj20@example.com",
            "password": "MemberPass!2026",
            "role": "member",
        },
    )
    assert member.status_code == 200, member.text
    with TestClient(client.app) as member_client:
        login = member_client.post(
            "/api/auth/login",
            json={
                "company_slug": bootstrap["company"]["slug"],
                "email": "watch-member-adj20@example.com",
                "password": "MemberPass!2026",
            },
        )
        assert login.status_code == 200, login.text
        member_headers = auth_headers(login.json()["access_token"])
        refused = member_client.post(
            "/api/ip/watch/journal-ingestions",
            headers=member_headers,
            json={
                "idempotency_key": "scope-member-capture-0001",
                "provider_key": "ipindia-journal-manual",
                "external_call": False,
                "cost_minor": 0,
                "currency": "INR",
                "publications": [_publication(application_id=application["id"])],
            },
        )
        assert refused.status_code == 403, refused.text
    # Another tenant cannot touch this tenant's manual profile.
    with TestClient(client.app) as other_client:
        other = other_client.post(
            "/api/bootstrap/company",
            json={
                "company_name": "Other Watch LLP",
                "company_slug": "other-watch-adj20",
                "company_type": "law_firm",
                "owner_full_name": "Other Owner",
                "owner_email": "owner@other-watch.example",
                "owner_password": "OtherFounder123!",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = auth_headers(str(other.json()["access_token"]))
        foreign = other_client.post(
            f"/api/ip/watch/profiles/{profile['id']}/status",
            headers=other_headers,
            json={"poll_status": "paused", "reason": "Cross tenant", "expected_version": 1},
        )
        assert foreign.status_code == 404, foreign.text
