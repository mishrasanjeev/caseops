"""Real PostgreSQL serialization of PKCE, refresh replay and identity cutoff."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from caseops_api.core.native_auth import decode_native_access_token
from caseops_api.db.models import CompanyMembership, NativeDeviceSession, NativeRefreshToken
from caseops_api.schemas.native_auth import NativeAuthorizeRequest, NativeTokenRequest
from caseops_api.services import native_auth
from caseops_api.services.identity import get_session_context
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
VERIFIER = "v" * 64


def _grant(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id, role="owner")
        session.commit()
        context = get_session_context(
            session,
            membership_id,
            token_issued_at=datetime.now(UTC).timestamp(),
        )
        grant = native_auth.authorize(
            session,
            context,
            NativeAuthorizeRequest(
                code_challenge=native_auth.pkce_challenge(VERIFIER),
                state="s" * 32,
                platform="ios",
                redirect_uri="caseops://oauth/callback",
            ),
        )
    return membership_id, NativeTokenRequest(
        code=grant.code,
        code_verifier=VERIFIER,
        platform="ios",
        redirect_uri="caseops://oauth/callback",
    )


def _run(engine, operation):
    with Session(engine) as session:
        session.execute(text("SET LOCAL lock_timeout = '3s'"))
        try:
            return operation(session)
        except HTTPException as exc:
            return exc.status_code


@pytest.mark.parametrize("operation", ["code", "refresh"])
def test_concurrent_native_exchange_is_single_use_and_refresh_replay_revokes_winner(
    pg_engine,
    monkeypatch,
    operation,
):
    membership_id, grant = _grant(pg_engine)
    if operation == "code":

        def invoke(session):
            return native_auth.exchange(session, grant)
    else:
        first = _run(pg_engine, lambda session: native_auth.exchange(session, grant))

        def invoke(session):
            return native_auth.rotate(session, first.refresh_token)

    entered, release, contended = Event(), Event(), Event()
    original = native_auth._issue

    def held_issue(session, context, device):
        result = original(session, context, device)
        if not entered.is_set():
            entered.set()
            assert release.wait(5), "Native issuance fence was not released"
        return result

    def lock_conflict(context):
        if getattr(context.original_exception, "sqlstate", None) == "55P03":
            contended.set()

    monkeypatch.setattr(native_auth, "_issue", held_issue)
    event.listen(pg_engine, "handle_error", lock_conflict)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_run, pg_engine, invoke)
            assert entered.wait(3)
            replay = pool.submit(_run, pg_engine, invoke)
            try:
                assert contended.wait(3), "Second connection never reached the real authority lock"
            finally:
                release.set()
            result = winner.result(timeout=5)
            assert not isinstance(result, int)
            assert replay.result(timeout=5) == 401
    finally:
        release.set()
        event.remove(pg_engine, "handle_error", lock_conflict)
    with Session(pg_engine) as session:
        families = list(
            session.scalars(
                select(NativeDeviceSession).where(
                    NativeDeviceSession.membership_id == membership_id,
                )
            )
        )
        assert len(families) == 1
        count = session.scalar(
            select(func.count())
            .select_from(NativeRefreshToken)
            .where(
                NativeRefreshToken.session_id == families[0].id,
            )
        )
        assert count == (1 if operation == "code" else 2)
        if operation == "refresh":
            assert families[0].revocation_reason == "refresh_replay"
            assert families[0].revoked_at is not None
            with pytest.raises(HTTPException) as denial:
                native_auth.native_context(session, decode_native_access_token(result.access_token))
            assert denial.value.status_code == 401
        else:
            assert families[0].revoked_at is None


def test_cutoff_committed_while_native_refresh_waits_wins_without_new_credentials(
    pg_engine,
):
    membership_id, grant = _grant(pg_engine)
    first = _run(pg_engine, lambda session: native_auth.exchange(session, grant))
    contended = Event()

    def lock_conflict(context):
        if getattr(context.original_exception, "sqlstate", None) == "55P03":
            contended.set()

    event.listen(pg_engine, "handle_error", lock_conflict)
    try:
        with Session(pg_engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
            member = writer.scalar(
                select(CompanyMembership)
                .where(
                    CompanyMembership.id == membership_id,
                )
                .with_for_update()
            )
            member.sessions_valid_after = datetime.now(UTC)
            writer.flush()
            refresh = pool.submit(
                _run,
                pg_engine,
                lambda session: native_auth.rotate(session, first.refresh_token),
            )
            try:
                assert contended.wait(3), "Refresh did not overlap the locked cutoff writer"
            finally:
                writer.commit()
            assert refresh.result(timeout=5) == 401
    finally:
        event.remove(pg_engine, "handle_error", lock_conflict)
    with Session(pg_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(NativeRefreshToken)
                .where(
                    NativeRefreshToken.session_id == first.session_id,
                )
            )
            == 1
        )
        with pytest.raises(HTTPException) as denial:
            native_auth.native_context(session, decode_native_access_token(first.access_token))
        assert denial.value.status_code == 401


def test_replay_revokes_family_even_after_identity_disabled(pg_engine):
    membership_id, grant = _grant(pg_engine)
    first = _run(pg_engine, lambda session: native_auth.exchange(session, grant))
    second = _run(pg_engine, lambda session: native_auth.rotate(session, first.refresh_token))
    with Session(pg_engine) as session:
        session.get(CompanyMembership, membership_id).is_active = False
        session.commit()
    assert _run(pg_engine, lambda session: native_auth.rotate(session, first.refresh_token)) == 401
    with Session(pg_engine) as session:
        family = session.get(NativeDeviceSession, first.session_id)
        assert family.revoked_at is not None
        assert family.revocation_reason == "refresh_replay"
        session.get(CompanyMembership, membership_id).is_active = True
        session.commit()
    assert _run(pg_engine, lambda session: native_auth.rotate(session, second.refresh_token)) == 401


def test_native_postgres_http_real_work_vertical_slice(isolated_postgres_client, http_pg_engine):
    from tests.test_auth_company import bootstrap_company
    from tests.test_native_auth_20261024 import _authorize, _exchange, _headers

    client = isolated_postgres_client
    assert http_pg_engine.dialect.name == "postgresql"
    auth = bootstrap_company(client)
    login = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    csrf = client.cookies.get("caseops_csrf")
    browser = {
        "Cookie": f"caseops_session={login.json()['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }
    client.cookies.clear()
    matter_payload = {
        "title": "Native HTTP acceptance record",
        "matter_code": "NATIVE-HTTP-01",
        "practice_area": "litigation",
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "client_name": "Synthetic QA Client",
        "opposing_party": "Synthetic QA Respondent",
    }
    created = client.post("/api/matters/", headers=browser, json=matter_payload)
    assert created.status_code == 200, created.text
    matter_id = created.json()["id"]
    grant = _authorize(client, browser)
    assert grant.status_code == 200, grant.text
    response = _exchange(client, grant.json()["code"])
    assert response.status_code == 200, response.text
    device = response.json()
    headers = {**_headers(device), "X-CaseOps-Client": "native"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    for key in ("company", "user", "membership", "capabilities"):
        assert me.json()[key] == device[key]
    assert me.json()["company"]["id"] == auth["company"]["id"]
    today = client.get("/api/me/today", headers=headers)
    assert today.status_code == 200, today.text
    assert today.json()["horizon_days"] == 7
    listed = client.get("/api/matters/?limit=25", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["company_id"] == auth["company"]["id"]
    assert [row["id"] for row in listed.json()["matters"]] == [matter_id]
    path = f"/api/matters/{matter_id}/workspace"
    workspace = client.get(path, headers=headers)
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["matter"]["id"] == matter_id
    assert workspace.json()["matter"]["matter_code"] == "NATIVE-HTTP-01"
    notes_path = f"/api/matters/{matter_id}/notes"
    rejected_cookie = client.post(
        notes_path,
        headers={"Cookie": browser["Cookie"]},
        json={"body": "CSRF must fail"},
    )
    assert rejected_cookie.status_code == 403
    original_version = workspace.json()["matter"]["lifecycle_version"]
    missing_version = client.post(notes_path, headers=headers, json={"body": "Missing version"})
    assert missing_version.status_code == 422, missing_version.text
    note = client.post(
        notes_path,
        headers=headers,
        json={
            "body": "Synthetic native saved note",
            "expected_lifecycle_version": original_version,
        },
    )
    assert note.status_code == 200, note.text
    assert note.json()["matter_id"] == matter_id
    assert note.json()["author_membership_id"] == auth["membership"]["id"]
    reloaded = client.get(path, headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert [(row["id"], row["body"]) for row in reloaded.json()["notes"]] == [
        (note.json()["id"], "Synthetic native saved note"),
    ]
    current = reloaded.json()["matter"]
    disposed = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=browser,
        json={
            "to_status": "disposed",
            "expected_from_status": current["status"],
            "expected_updated_at": current["updated_at"],
            "reason": "Synthetic QA terminal-parent acceptance",
        },
    )
    assert disposed.status_code == 200, disposed.text
    rejected_native = client.post(notes_path, headers=headers, json={"body": "Must not persist"})
    assert rejected_native.status_code == 409, rejected_native.text
    final = client.get(path, headers=headers)
    assert final.status_code == 200, final.text
    assert final.json()["matter"]["status"] == "disposed"
    assert final.json()["matter"]["is_active"] is False
    assert [row["id"] for row in final.json()["notes"]] == [note.json()["id"]]
    terminal = final.json()["matter"]
    reopened = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=browser,
        json={
            "to_status": "intake",
            "expected_from_status": "disposed",
            "expected_updated_at": terminal["updated_at"],
            "reason": "Synthetic QA explicit same-day reopening",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["lifecycle_version"] == original_version + 2
    assert reopened.json()["updated_at"][:10] == disposed.json()["updated_at"][:10]
    stale_payload = {
        "body": "Stale native draft must not save",
        "expected_lifecycle_version": original_version,
    }
    for authority in (headers, browser):
        stale = client.post(notes_path, headers=authority, json=stale_payload)
        assert stale.status_code == 409, stale.text
    after_stale = client.get(path, headers=headers)
    assert [row["id"] for row in after_stale.json()["notes"]] == [note.json()["id"]]
    fresh = client.post(
        notes_path,
        headers=headers,
        json={
            "body": "Fresh native lifecycle version",
            "expected_lifecycle_version": original_version + 2,
        },
    )
    assert fresh.status_code == 200, fresh.text
    # Existing browser clients remain compatible when the optional token is absent.
    legacy = client.post(notes_path, headers=browser, json={"body": "Legacy browser note"})
    assert legacy.status_code == 200, legacy.text
    current = client.get(path, headers=headers).json()["matter"]
    second_close = client.patch(
        f"/api/matters/{matter_id}/lifecycle/status",
        headers=browser,
        json={
            "to_status": "disposed",
            "expected_from_status": "intake",
            "expected_updated_at": current["updated_at"],
            "reason": "Synthetic QA second closure",
        },
    )
    assert second_close.status_code == 200, second_close.text
    assert second_close.json()["lifecycle_version"] == original_version + 3
    assert (
        client.post(
            notes_path,
            headers=headers,
            json={
                "body": "Terminal must stay closed",
                "expected_lifecycle_version": original_version + 3,
            },
        ).status_code
        == 409
    )
    refreshed = client.post(
        "/api/auth/native/refresh", json={"refresh_token": device["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["session_id"] == device["session_id"]
    assert (
        client.get(path, headers=_headers(refreshed.json())).json()["matter"]["status"]
        == "disposed"
    )
