"""Compatible template readers still exclude editing/archiving on real PostgreSQL.

Only the service-level transport callback is emulated. HTTP fixture setup and
disposal keep the no-paid marker. This retains, but does not certify or repair,
the pre-existing Matter lock held during outbound transport.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, wait
from queue import Queue
from threading import Event, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import Communication, EmailTemplate, Matter
from caseops_api.schemas.email_templates import EmailSendRequest, EmailTemplateUpdateRequest
from caseops_api.services import communications, email_templates
from caseops_api.services.identity import get_session_context
from tests.test_auth_company import auth_headers
from tests.test_email_templates import _create_matter, _create_template, _preview_message
from tests.test_matter_lifecycle import _lifecycle

pytestmark = pytest.mark.postgres


def _observed_blockers(connection, pid, expected, *, require_all=False):
    deadline = monotonic() + 3
    observed = set()
    while monotonic() < deadline:
        observed = set(connection.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}))
        matches = expected <= observed if require_all else bool(expected & observed)
        if matches:
            return observed
        sleep(0.01)
    raise AssertionError(f"Expected actual PostgreSQL blockers {expected}; observed {observed}")


def _assert_parent_locked(engine, matter_id):
    # This is the existing disposal fence, not transaction-free-I/O acceptance.
    with engine.connect() as probe:
        with pytest.raises(DBAPIError) as blocked:
            probe.execute(
                text("SELECT id FROM matters WHERE id=:id FOR UPDATE NOWAIT"), {"id": matter_id}
            )
        assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        probe.rollback()


@pytest.mark.parametrize("mutation", ["edit", "archive"])
def test_parallel_matter_sends_share_template_fence_but_exclude_mutation(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    mutation,
):
    client, engine = isolated_postgres_client, http_pg_engine
    assert engine.dialect.name == "postgresql"
    assert client.headers.get("X-CaseOps-Automated-Test") == "no-paid-providers"
    nonce = str(uuid4())
    bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Comms template fence QA",
            "company_slug": f"comms-lock-{nonce}",
            "company_type": "law_firm",
            "owner_full_name": "Comms lock owner",
            "owner_email": f"owner-{nonce}@example.com",
            "owner_password": f"Offline!{uuid4()}",
        },
    )
    assert bootstrap.status_code == 200, bootstrap.text
    actor = bootstrap.json()
    token, actor_id = actor["access_token"], actor["membership"]["id"]
    headers = auth_headers(token)
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["membership"]["id"] == actor_id
    assert "communications:write" in identity.json()["capabilities"]
    assert "email_templates:manage" in identity.json()["capabilities"]
    codes = [f"COMMS-{index}-{uuid4().hex.upper()}" for index in range(2)]
    matter_ids = [_create_matter(client, headers, code) for code in codes]
    template = _create_template(
        client,
        headers,
        name=f"Shared template {nonce}",
        body_template="Matter {{matter_code}}.",
        required_vars=(),
    )
    payloads = [
        EmailSendRequest.model_validate(
            _preview_message(
                client,
                headers,
                matter_id,
                {
                    "template_id": template["id"],
                    "recipient_email": f"recipient-{index}-{nonce}@example.com",
                },
            )
        )
        for index, matter_id in enumerate(matter_ids)
    ]
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-template-lock-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "offline@example.com")
    get_settings.cache_clear()

    entered, release = [Event(), Event()], [Event(), Event()]
    writer_started = Event()
    thread = local()
    calls = Queue()
    pids = {}

    def transport(**message):
        index = thread.index
        pid = thread.session.scalar(text("SELECT pg_backend_pid()"))
        assert pid == pids[index]
        calls.put((index, message))
        entered[index].set()
        resumed = release[index].wait(20)
        assert resumed, "Emulated transport was not released by its owning test"
        return True, f"offline-template-share-{index}-{nonce}", None

    monkeypatch.setattr(communications, "_send_via_sendgrid", transport)

    def send(index):
        with Session(engine) as session:
            session.execute(text("SET LOCAL lock_timeout='8s'"))
            session.execute(text("SET LOCAL statement_timeout='12s'"))
            pids[index] = session.scalar(text("SELECT pg_backend_pid()"))
            context = get_session_context(session, actor_id)
            assert context.company.id == actor["company"]["id"]
            assert context.membership.role == "owner" and context.membership.is_active
            thread.index, thread.session = index, session
            return communications.send_matter_email(
                session,
                context=context,
                matter_id=matter_ids[index],
                payload=payloads[index],
            )

    def change_template():
        with Session(engine) as session:
            session.execute(text("SET LOCAL lock_timeout='8s'"))
            session.execute(text("SET LOCAL statement_timeout='12s'"))
            pids["writer"] = session.scalar(text("SELECT pg_backend_pid()"))
            context = get_session_context(session, actor_id)
            writer_started.set()
            if mutation == "edit":
                return email_templates.update_email_template(
                    session,
                    context=context,
                    template_id=template["id"],
                    payload=EmailTemplateUpdateRequest(body_template="Edited after both sends."),
                )
            return email_templates.archive_email_template(
                session,
                context=context,
                template_id=template["id"],
            )

    futures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            first = pool.submit(send, 0)
            futures.append(first)
            first_entered = entered[0].wait(5)
            assert first_entered, "First authorized send did not reach the emulator"
            second = pool.submit(send, 1)
            futures.append(second)
            second_entered = entered[1].wait(5)
            assert second_entered, "Different Matters must not serialize on one template"
            assert not first.done() and not second.done()
            assert pids[0] != pids[1]
            _assert_parent_locked(engine, matter_ids[0])
            _assert_parent_locked(engine, matter_ids[1])

            writer = pool.submit(change_template)
            futures.append(writer)
            started = writer_started.wait(3)
            assert started, "Template mutation did not acquire its own backend"
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                _observed_blockers(observer, pids["writer"], {pids[0], pids[1]})
                assert not writer.done()
                with Session(engine) as unchanged:
                    row = unchanged.get(EmailTemplate, template["id"])
                    assert row.is_active and row.body_template == template["body_template"]

                release[0].set()
                first_result = first.result(timeout=5)
                assert first_result.status == "sent"
                # A MultiXact writer may wait on just one reader at a time.
                # After the first reader commits, the second must still exclude it.
                _observed_blockers(observer, pids["writer"], {pids[1]}, require_all=True)
                assert not writer.done() and not second.done()
                _assert_parent_locked(engine, matter_ids[1])

                release[1].set()
                second_result = second.result(timeout=5)
                changed = writer.result(timeout=5)
                assert second_result.status == "sent"
                assert changed.is_active is (mutation == "edit")
        finally:
            primary = sys.exception()
            for gate in release:
                gate.set()
            done, pending = wait(futures, timeout=12)
            errors = [str(future.exception()) for future in done if future.exception() is not None]
            if pending or errors:
                detail = f"Owned race cleanup: pending={len(pending)}, worker_errors={errors}"
                if primary is not None:
                    primary.add_note(detail)
                else:
                    raise AssertionError(detail)

    assert calls.qsize() == 2
    with Session(engine) as check:
        rows = list(
            check.scalars(
                select(Communication).where(
                    Communication.matter_id.in_(matter_ids),
                )
            )
        )
        assert len(rows) == 2
        assert {row.matter_id for row in rows} == set(matter_ids)
        assert {row.body for row in rows} == {f"Matter {code}." for code in codes}
        assert all(row.status == "sent" for row in rows)
        current_template = check.get(EmailTemplate, template["id"])
        assert current_template.is_active is (mutation == "edit")
        if mutation == "edit":
            assert current_template.body_template == "Edited after both sends."
        assert all(check.get(Matter, identity).is_active for identity in matter_ids)

    # The unchanged real lifecycle guard still rejects later sends after disposal.
    current = client.get(f"/api/matters/{matter_ids[0]}", headers=headers)
    assert current.status_code == 200, current.text
    disposed = _lifecycle(client, token, current.json(), to_status="disposed")
    assert disposed.status_code == 200, disposed.text
    denied = client.post(
        f"/api/matters/{matter_ids[0]}/communications/send-email",
        headers=headers,
        json=payloads[0].model_dump(mode="json"),
    )
    assert denied.status_code == 409, denied.text
    assert "disposed" in denied.json()["detail"]
    assert calls.qsize() == 2
