"""Shared membership fixtures retain full UUID email identity on PostgreSQL."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, User
from tests import test_postgres_validation as seeds
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_same_prefix_membership_user_uuids_persist_distinct_emails(pg_engine, monkeypatch):
    # A fresh namespace avoids fixed IDs across retained runs; low-bit changes
    # deterministically give two distinct user UUIDs with the same eight-character prefix.
    namespace = uuid4().int & ~3
    identities = tuple(UUID(int=namespace | offset) for offset in range(4))
    user_ids = (str(identities[0]), str(identities[2]))
    membership_ids = (str(identities[1]), str(identities[3]))
    assert len(set(identities)) == 4
    assert user_ids[0][:8] == user_ids[1][:8]
    assert user_ids[0] != user_ids[1]

    with Session(pg_engine) as setup:
        company_id = seeds._seed_company(setup)
        setup.commit()

    generated = iter(identities)
    with monkeypatch.context() as patch:
        patch.setattr(seeds, "uuid4", lambda: next(generated))
        with Session(pg_engine) as first:
            assert seeds._seed_membership(first, company_id) == membership_ids[0]
            first.commit()

        with Session(pg_engine) as first_reload:
            assert first_reload.get(User, user_ids[0]) is not None
            assert first_reload.get(CompanyMembership, membership_ids[0]).user_id == user_ids[0]

        with Session(pg_engine) as second:
            assert seeds._seed_membership(second, company_id) == membership_ids[1]
            second.commit()

    expected_emails = {user_id: f"notice-pg-{user_id}@example.com" for user_id in user_ids}
    assert len(set(expected_emails.values())) == 2
    with Session(pg_engine) as reload:
        assert dict(reload.execute(
            select(User.id, User.email).where(User.id.in_(user_ids)),
        ).all()) == expected_emails
        assert set(reload.execute(
            select(CompanyMembership.id, CompanyMembership.company_id, CompanyMembership.user_id)
            .where(CompanyMembership.id.in_(membership_ids)),
        ).all()) == {
            (membership_ids[0], company_id, user_ids[0]),
            (membership_ids[1], company_id, user_ids[1]),
        }

        duplicate_user_id = str(UUID(int=namespace ^ 4))
        assert duplicate_user_id not in user_ids
        with pytest.raises(IntegrityError) as caught, reload.begin_nested():
            reload.add(User(
                id=duplicate_user_id,
                email=expected_emails[user_ids[0]],
                full_name="Exact duplicate fixture email control",
                password_hash="not-used",
                is_active=True,
            ))
            reload.flush()
        assert caught.value.orig.sqlstate == "23505"
        assert caught.value.orig.diag.constraint_name == "users_email_key"
        assert reload.get(User, duplicate_user_id) is None
