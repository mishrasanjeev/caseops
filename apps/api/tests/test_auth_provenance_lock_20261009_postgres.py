"""Auth serializes identity changes without blocking historical FK provenance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, User
from caseops_api.services.identity import issue_auth_session_under_fence
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


def _identity(engine):
    with Session(engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id, role="admin")
        user_id = session.scalar(
            select(CompanyMembership.user_id).where(
                CompanyMembership.id == membership_id,
            )
        )
        session.commit()
    return company_id, membership_id, user_id


@pytest.mark.parametrize("provenance", [CompanyMembership, User], ids=["membership", "user"])
def test_auth_fence_is_compatible_with_retained_provenance(pg_engine, provenance):
    company_id, membership_id, user_id = _identity(pg_engine)
    retained_id = membership_id if provenance is CompanyMembership else user_id
    with Session(pg_engine) as historical, Session(pg_engine) as login:
        historical.scalar(
            select(provenance.id)
            .where(provenance.id == retained_id)
            .with_for_update(read=True, key_share=True)
        )
        login.execute(text("SET LOCAL lock_timeout = '500ms'"))
        result = issue_auth_session_under_fence(
            login,
            company_id=company_id,
            membership_id=membership_id,
        )
        assert result.access_token
        assert result.membership.id == membership_id
        login.rollback()


@pytest.mark.parametrize("provenance", [CompanyMembership, User], ids=["membership", "user"])
def test_retained_provenance_is_compatible_when_auth_wins_first(pg_engine, provenance):
    company_id, membership_id, user_id = _identity(pg_engine)
    retained_id = membership_id if provenance is CompanyMembership else user_id
    with Session(pg_engine) as login, Session(pg_engine) as historical:
        assert issue_auth_session_under_fence(
            login,
            company_id=company_id,
            membership_id=membership_id,
        ).access_token
        historical.execute(text("SET LOCAL lock_timeout = '500ms'"))
        assert (
            historical.scalar(
                select(provenance.id)
                .where(provenance.id == retained_id)
                .with_for_update(read=True, key_share=True)
            )
            == retained_id
        )


@pytest.mark.parametrize("model", [CompanyMembership, User], ids=["membership", "user"])
def test_auth_fence_still_excludes_identity_deactivation(pg_engine, model):
    company_id, membership_id, user_id = _identity(pg_engine)
    target_id = membership_id if model is CompanyMembership else user_id
    started = Event()
    writer_pids = []

    def deactivate():
        with Session(pg_engine) as writer:
            writer.execute(text("SET LOCAL lock_timeout = '2s'"))
            writer_pids.append(writer.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            row = writer.scalar(select(model).where(model.id == target_id).with_for_update())
            row.is_active = False
            writer.commit()

    with Session(pg_engine) as login, ThreadPoolExecutor(max_workers=1) as pool:
        auth = issue_auth_session_under_fence(
            login,
            company_id=company_id,
            membership_id=membership_id,
        )
        assert auth.access_token
        login_pid = login.scalar(text("SELECT pg_backend_pid()"))
        writer = pool.submit(deactivate)
        try:
            assert started.wait(1)
            with Session(pg_engine) as observer:
                # The writer must be blocked by the real PostgreSQL auth transaction.
                deadline = monotonic() + 1
                blockers = []
                while monotonic() < deadline:
                    blockers = observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pids[0]}
                    )
                    if login_pid in blockers:
                        break
                    sleep(0.01)
                assert login_pid in blockers
        finally:
            login.rollback()
        writer.result(timeout=3)
    with Session(pg_engine) as after:
        with pytest.raises(HTTPException) as denial:
            issue_auth_session_under_fence(
                after, company_id=company_id, membership_id=membership_id
            )
        assert getattr(denial.value, "status_code", None) == 403
