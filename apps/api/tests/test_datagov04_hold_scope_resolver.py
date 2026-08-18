"""DATA-GOV-04: a legal hold covers what it targets, and nothing narrower.

The dry-run manifest previously treated ANY active hold as covering EVERY
target. That direction is safe - it can only over-block - but it makes a hold
scoped to one data class indistinguishable from a company-wide one, and reports
unrelated data as preserved. An operator reading that manifest would believe far
broader preservation had been ordered than actually was.

The safety property under test is asymmetric and worth stating plainly: getting
this wrong by over-blocking wastes an operator's time, and getting it wrong by
under-blocking destroys evidence under a legal hold. Every test here that proves
narrowing is paired with one proving the narrowing cannot go too far.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    LegalHold,
    LegalHoldItem,
    LegalHoldStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_governance import (
    HOLD_TARGET_TYPE_DATA_CLASS,
    resolve_hold_for_target,
)
from tests.test_auth_company import bootstrap_company

_CLASS_A = "legal_holds"
_CLASS_B = "legal_hold_items"
_HASH_ONE = "a" * 64
_HASH_TWO = "b" * 64


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client builds the schema
    factory = get_session_factory()
    with factory() as active:
        yield active


@pytest.fixture()
def company_id(client) -> str:
    """A real company, because an ACTIVE hold cannot be forged.

    ``ck_legal_hold_activation_approval`` requires an active hold to carry a
    creator AND a distinct approver, both memberships of the owning company.
    That constraint is DATA-GOV-05's dual approval enforced in the database, so
    a fixture that dodged it would be testing a state production cannot reach.
    """
    return str(bootstrap_company(client)["company"]["id"])


def _company_id() -> str:
    """A company id with no rows behind it, for negative cases only."""
    return str(uuid4())


def _approval_pair(session: Session, company_id: str) -> tuple[str, str]:
    """Two distinct memberships in one company: creator and approver."""
    ids: list[str] = []
    for index in range(2):
        user = User(
            email=f"hold-{index}-{uuid4().hex[:8]}@fixture.example",
            full_name=f"Hold Actor {index}",
            password_hash="fixture-only",
        )
        session.add(user)
        session.flush()
        membership = CompanyMembership(company_id=company_id, user_id=user.id, role="admin")
        session.add(membership)
        session.flush()
        ids.append(membership.id)
    return ids[0], ids[1]


def _hold(session: Session, company_id: str, *, key: str = "hold-1") -> LegalHold:
    now = datetime.now(UTC)
    creator_id, approver_id = _approval_pair(session, company_id)
    hold = LegalHold(
        company_id=company_id,
        key=key,
        title="Preservation order",
        authority_reference="Court order 2026/11",
        status=LegalHoldStatus.ACTIVE,
        activated_at=now,
        created_by_membership_id=creator_id,
        created_by_membership_company_id=company_id,
        creator_label_snapshot="Records owner",
        approved_by_membership_id=approver_id,
        approved_by_membership_company_id=company_id,
        approver_label_snapshot="Records approver",
        created_at=now,
        updated_at=now,
    )
    session.add(hold)
    session.flush()
    return hold


def _item(
    session: Session,
    hold: LegalHold,
    *,
    data_class_id: str,
    target_type: str,
    target_reference_hash: str,
) -> None:
    session.add(
        LegalHoldItem(
            company_id=hold.company_id,
            legal_hold_id=hold.id,
            data_class_id=data_class_id,
            target_type=target_type,
            target_reference_hash=target_reference_hash,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()


class TestNoHold:
    def test_no_active_hold_means_no_coverage(self, session: Session) -> None:
        assert (
            resolve_hold_for_target(
                session,
                company_id=_company_id(),
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_ONE,
            )
            is None
        )


class TestUnscopedHoldCoversEverything:
    """An itemless hold is company-wide. This is the live path today - nothing
    in the application writes LegalHoldItem yet - so it must not regress."""

    def test_itemless_hold_covers_any_target(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)

        for data_class_id in (_CLASS_A, _CLASS_B):
            assert (
                resolve_hold_for_target(
                    session,
                    company_id=company_id,
                    data_class_id=data_class_id,
                    target_type="tenant",
                    target_reference_hash=_HASH_ONE,
                )
                == hold.id
            )

    def test_itemless_hold_covers_a_target_with_no_reference(
        self, session: Session, company_id: str
    ) -> None:
        # A caller that cannot name a specific record must still be blocked.
        hold = _hold(session, company_id)

        assert (
            resolve_hold_for_target(
                session, company_id=company_id, data_class_id=_CLASS_A
            )
            == hold.id
        )


class TestDataClassScope:
    def test_data_class_item_covers_every_record_in_that_class(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(
            session,
            hold,
            data_class_id=_CLASS_A,
            target_type=HOLD_TARGET_TYPE_DATA_CLASS,
            target_reference_hash=_HASH_ONE,
        )

        # Any record of the held class, including one the item did not name.
        assert (
            resolve_hold_for_target(
                session,
                company_id=company_id,
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_TWO,
            )
            == hold.id
        )

    def test_data_class_item_does_not_cover_a_different_class(
        self, session: Session, company_id: str
    ) -> None:
        # The narrowing that motivates the whole change.
        hold = _hold(session, company_id)
        _item(
            session,
            hold,
            data_class_id=_CLASS_A,
            target_type=HOLD_TARGET_TYPE_DATA_CLASS,
            target_reference_hash=_HASH_ONE,
        )

        assert (
            resolve_hold_for_target(
                session,
                company_id=company_id,
                data_class_id=_CLASS_B,
                target_type="tenant",
                target_reference_hash=_HASH_ONE,
            )
            is None
        )


class TestRecordScope:
    def test_record_item_covers_the_named_record(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(
            session,
            hold,
            data_class_id=_CLASS_A,
            target_type="tenant",
            target_reference_hash=_HASH_ONE,
        )

        assert (
            resolve_hold_for_target(
                session,
                company_id=company_id,
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_ONE,
            )
            == hold.id
        )

    def test_record_item_does_not_cover_a_different_record(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(
            session,
            hold,
            data_class_id=_CLASS_A,
            target_type="tenant",
            target_reference_hash=_HASH_ONE,
        )

        assert (
            resolve_hold_for_target(
                session,
                company_id=company_id,
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_TWO,
            )
            is None
        )

    def test_a_scoped_hold_alongside_an_unscoped_hold_still_blocks(
        self, session: Session, company_id: str
    ) -> None:
        # The dangerous composition: adding a NARROW hold must never shrink the
        # coverage an existing broad hold already provides.
        broad = _hold(session, company_id, key="broad")
        narrow = _hold(session, company_id, key="narrow")
        _item(
            session,
            narrow,
            data_class_id=_CLASS_A,
            target_type="tenant",
            target_reference_hash=_HASH_ONE,
        )

        covering = resolve_hold_for_target(
            session,
            company_id=company_id,
            data_class_id=_CLASS_B,
            target_type="tenant",
            target_reference_hash=_HASH_TWO,
        )

        assert covering == broad.id


class TestTenantIsolation:
    def test_another_companys_hold_never_covers_this_company(
        self, session: Session, company_id: str
    ) -> None:
        _hold(session, company_id)

        assert (
            resolve_hold_for_target(
                session,
                company_id=_company_id(),
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_ONE,
            )
            is None
        )


class TestInactiveHolds:
    @pytest.mark.parametrize(
        "status", [LegalHoldStatus.DRAFT, LegalHoldStatus.RELEASED, LegalHoldStatus.CANCELLED]
    )
    def test_only_active_holds_block(
        self, session: Session, company_id: str, status: str
    ) -> None:
        # A non-active hold needs no approver: ck_legal_hold_activation_approval
        # only constrains status='active'.
        now = datetime.now(UTC)
        session.add(
            LegalHold(
                company_id=company_id,
                key=f"hold-{status}",
                title="Preservation order",
                authority_reference="Court order 2026/11",
                status=status,
                released_at=now if status == LegalHoldStatus.RELEASED else None,
                creator_label_snapshot="Records owner",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()

        assert (
            resolve_hold_for_target(
                session,
                company_id=company_id,
                data_class_id=_CLASS_A,
                target_type="tenant",
                target_reference_hash=_HASH_ONE,
            )
            is None
        )
