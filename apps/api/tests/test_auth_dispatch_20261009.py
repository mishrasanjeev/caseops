"""A blocked auth fence must not block the serving instance's event loop."""

from __future__ import annotations

import inspect
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import pytest
import uvicorn
from fastapi import HTTPException

from caseops_api.api.routes import auth, matters, notices
from tests.test_auth_company import bootstrap_company


@pytest.mark.parametrize(
    "name",
    [
        "login",
        "account_setup_complete",
        "password_reset_start",
        "password_reset_complete",
        "me",
        "security_status",
        "mfa_enroll",
        "mfa_enroll_verify",
        "mfa_step_up",
        "mfa_recovery_codes_regenerate",
        "mfa_disable",
        "refresh",
    ],
)
def test_synchronous_auth_services_use_worker_dispatch(name):
    assert not inspect.iscoroutinefunction(inspect.unwrap(getattr(auth, name)))


@pytest.mark.parametrize(
    "name",
    [
        "current_company_notices",
        "post_current_company_notice",
        "get_current_company_notice_owners",
        "get_current_company_notice",
        "patch_current_company_notice",
        "post_current_company_notice_file",
        "download_current_company_notice_file",
    ],
)
def test_synchronous_notice_services_use_worker_dispatch(name):
    assert not inspect.iscoroutinefunction(getattr(notices, name))


def test_synchronous_matter_upload_uses_worker_dispatch():
    assert not inspect.iscoroutinefunction(matters.post_current_company_matter_attachment)


@pytest.mark.parametrize("operation", ["login", "notice-upload", "matter-upload"])
def test_blocked_handler_leaves_real_http_build_request_responsive(client, monkeypatch, operation):
    entered, release = Event(), Event()

    def blocked_authentication(*_args, **_kwargs):
        entered.set()
        assert release.wait(5), "Controlled authentication fence was not released"
        raise HTTPException(status_code=503, detail="controlled auth fence")

    token = None
    if operation == "login":
        route, service, path = auth, "authenticate_user", "/api/auth/login"
    else:
        token = bootstrap_company(client)["access_token"]
        if operation == "notice-upload":
            route, service, path = notices, "upload_notice_file", "/api/notices/notice-test/file"
        else:
            route, service, path = (
                matters,
                "create_matter_attachment",
                "/api/matters/matter-test/attachments",
            )
    monkeypatch.setattr(route, service, blocked_authentication)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    # The canonical client fixture already owns this app's migrated lifespan.
    server = uvicorn.Server(uvicorn.Config(client.app, lifespan="off", log_level="error"))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert server.started
        origin = f"http://127.0.0.1:{port}"
        headers = {"X-CaseOps-Automated-Test": "no-paid-providers"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(base_url=origin, headers=headers, timeout=6) as http:
            assert http.get("/api/build").status_code == 200
            with ThreadPoolExecutor(max_workers=1) as pool:
                if operation == "login":
                    pending = pool.submit(
                        http.post,
                        path,
                        json={
                            "company_slug": "dispatch-test",
                            "email": "dispatch@example.com",
                            "password": "DispatchPass123!",
                        },
                    )
                else:
                    pending = pool.submit(
                        http.post,
                        path,
                        files={"file": ("dispatch.txt", b"local regression", "text/plain")},
                        data={"expected_updated_at": "2026-10-09T00:00:00Z"},
                    )
                try:
                    assert entered.wait(3), "Actual auth handler did not reach its service"
                    start = monotonic()
                    build = http.get("/api/build", timeout=0.6)
                    assert build.status_code == 200
                    assert monotonic() - start < 0.6
                    assert not pending.done(), (
                        "The unrelated read ran only after the handler finished"
                    )
                finally:
                    release.set()
                denied = pending.result(timeout=3)
                assert denied.status_code == 503
                assert denied.json()["detail"] == "controlled auth fence"
    finally:
        release.set()
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "Owned HTTP server did not stop"
