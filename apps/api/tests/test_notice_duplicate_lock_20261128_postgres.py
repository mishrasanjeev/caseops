"""Concurrent identical notice writes serialize on real PostgreSQL.

The duplicate rule is an application check, so two writers of the same notice
could each pass it before either commits. A register writer takes the
per-tenant duplicate-key advisory lock and then every linked Matter's row lock
(the lock matter notice writers already hold) before it checks. Each test
holds the lock a concurrent writer would hold, commits that writer's notice,
and proves the register write waited and then refused the duplicate.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyNotice, MatterAttachment
from caseops_api.schemas.notices import NoticeCreateRequest, NoticeUpdateRequest
from caseops_api.services import notices
from caseops_api.services.identity import get_session_context
from caseops_api.services.notice_rules import (
    lock_notice_duplicate_key,
    register_notice_duplicate_key,
)
from tests.test_auth_company import auth_headers
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres

RECEIVED = date(2026, 11, 2)
DETAILS = {
    "direction": "received",
    "subject": "Concurrent demand notice",
    "type": "Legal demand",
    "received_on": RECEIVED,
    "received_from": "Opposing counsel",
}


def _wait_until_blocked(engine, pids: dict[str, int], holder_pid: int, locktype: str) -> None:
    """Return once the writer's own backend waits on ``holder_pid`` for ``locktype``."""

    deadline = monotonic() + 10
    observed: tuple[object, ...] = ()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
        while monotonic() < deadline:
            writer_pid = pids.get("writer")
            if writer_pid is not None:
                observed = tuple(
                    observer.execute(
                        text(
                            "SELECT :holder = ANY(pg_blocking_pids(:writer)), locktype "
                            "FROM pg_locks WHERE pid = :writer AND NOT granted"
                        ),
                        {"holder": holder_pid, "writer": writer_pid},
                    ).first()
                    or ()
                )
                if observed and observed[0] is True:
                    assert observed[1] == locktype, observed
                    return
            sleep(0.02)
    raise AssertionError(
        f"The register write did not wait for the concurrent writer's lock: {observed}"
    )


def _bootstrap(client) -> dict[str, object]:  # type: ignore[no-untyped-def]
    nonce = uuid4().hex[:10]
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Notice lock QA",
            "company_slug": f"notice-lock-{nonce}",
            "company_type": "law_firm",
            "owner_full_name": "Notice lock owner",
            "owner_email": f"owner-{nonce}@example.com",
            "owner_password": f"Offline!{uuid4()}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _register(engine, pids: dict[str, int], actor_id: str, write):  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        session.execute(text("SET LOCAL lock_timeout='15s'"))
        pids["writer"] = session.scalar(text("SELECT pg_backend_pid()"))
        context = get_session_context(session, actor_id)
        try:
            return write(session, context)
        except HTTPException as exc:
            return exc


def test_concurrent_identical_register_creates_serialize(
    isolated_postgres_client, http_pg_engine
) -> None:
    client, engine = isolated_postgres_client, http_pg_engine
    boot = _bootstrap(client)
    company_id = boot["company"]["id"]
    actor_id = boot["membership"]["id"]
    payload = NoticeCreateRequest(**DETAILS)

    with Session(engine) as holder:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pids: dict[str, int] = {}
        # The first writer: holds the key lock and has inserted, not committed.
        lock_notice_duplicate_key(
            holder, company_id=company_id, key=register_notice_duplicate_key(payload)
        )
        first = CompanyNotice(
            company_id=company_id,
            created_by_membership_id=actor_id,
            direction="received",
            subject="Concurrent demand notice",
            notice_type="Legal demand",
            status="Open",
            received_on=RECEIVED,
            received_from="Opposing counsel",
            currency="INR",
            reply_required=False,
            reply_sent=False,
        )
        holder.add(first)
        holder.flush()
        first_id = first.id
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(
                _register,
                engine,
                pids,
                actor_id,
                lambda session, context: notices.create_notice(
                    session, context=context, payload=payload
                ),
            )
            _wait_until_blocked(engine, pids, holder_pid, "advisory")
            assert not second.done()
            holder.commit()
            outcome = second.result(timeout=20)

    assert isinstance(outcome, HTTPException), outcome
    assert outcome.status_code == 409
    assert outcome.detail["existing_notice"]["id"] == first_id
    listed = client.get("/api/notices/", headers=auth_headers(boot["access_token"]))
    assert [row["id"] for row in listed.json()["notices"]] == [first_id]


def test_register_edit_into_a_concurrent_notice_serializes(
    isolated_postgres_client, http_pg_engine
) -> None:
    client, engine = isolated_postgres_client, http_pg_engine
    boot = _bootstrap(client)
    company_id = boot["company"]["id"]
    actor_id = boot["membership"]["id"]
    headers = auth_headers(boot["access_token"])
    other = client.post(
        "/api/notices/",
        headers=headers,
        json={**DETAILS, "received_on": RECEIVED.isoformat(), "subject": "Other subject"},
    )
    assert other.status_code == 201, other.text
    edited = other.json()

    with Session(engine) as holder:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pids: dict[str, int] = {}
        lock_notice_duplicate_key(
            holder,
            company_id=company_id,
            key=register_notice_duplicate_key(NoticeCreateRequest(**DETAILS)),
        )
        first = CompanyNotice(
            company_id=company_id,
            created_by_membership_id=actor_id,
            direction="received",
            subject="Concurrent demand notice",
            notice_type="Legal demand",
            status="Open",
            received_on=RECEIVED,
            received_from="Opposing counsel",
            currency="INR",
            reply_required=False,
            reply_sent=False,
        )
        holder.add(first)
        holder.flush()
        first_id = first.id
        update = NoticeUpdateRequest(
            expected_updated_at=datetime.fromisoformat(edited["updated_at"]),
            subject="Concurrent demand notice",
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(
                _register,
                engine,
                pids,
                actor_id,
                lambda session, context: notices.update_notice(
                    session, context=context, notice_id=edited["id"], payload=update
                ),
            )
            _wait_until_blocked(engine, pids, holder_pid, "advisory")
            assert not second.done()
            holder.commit()
            outcome = second.result(timeout=20)

    assert isinstance(outcome, HTTPException), outcome
    assert outcome.status_code == 409
    assert outcome.detail["existing_notice"]["id"] == first_id
    stored = client.get(f"/api/notices/{edited['id']}", headers=headers).json()
    assert stored["subject"] == "Other subject"


def test_register_create_waits_for_a_matter_upload_of_the_same_notice(
    isolated_postgres_client, http_pg_engine
) -> None:
    client, engine = isolated_postgres_client, http_pg_engine
    boot = _bootstrap(client)
    actor_id = boot["membership"]["id"]
    headers = auth_headers(boot["access_token"])
    matter = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Notice lock matter",
            "matter_code": f"NL-{uuid4().hex[:8].upper()}",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter.status_code == 200, matter.text
    matter_id = matter.json()["id"]

    with Session(engine) as holder:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        pids: dict[str, int] = {}
        # A matter upload holds its Matter exclusively while it admits a notice.
        holder.execute(
            text("SELECT id FROM matters WHERE id = :id FOR UPDATE"), {"id": matter_id}
        )
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=actor_id,
            original_filename="notice.pdf",
            storage_key=f"locks/{uuid4()}/notice.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256_hex=uuid4().hex * 2,
            processing_status="indexed",
            extracted_char_count=0,
            document_type="notice",
            notice_direction="received",
            notice_document_role="notice",
            notice_subject="Concurrent demand notice",
            notice_type="Legal demand",
            notice_received_on=RECEIVED,
            notice_received_from="Opposing counsel",
            notice_reply_required=False,
        )
        holder.add(attachment)
        holder.flush()
        attachment_id = attachment.id
        payload = NoticeCreateRequest(**DETAILS, matter_ids=[matter_id])
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(
                _register,
                engine,
                pids,
                actor_id,
                lambda session, context: notices.create_notice(
                    session, context=context, payload=payload
                ),
            )
            _wait_until_blocked(engine, pids, holder_pid, "transactionid")
            assert not second.done()
            holder.commit()
            outcome = second.result(timeout=20)

    assert isinstance(outcome, HTTPException), outcome
    assert outcome.status_code == 409
    assert outcome.detail["existing_notice"]["id"] == attachment_id
    assert outcome.detail["existing_notice"]["source_kind"] == "legacy_attachment"
