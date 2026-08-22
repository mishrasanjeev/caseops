"""What a step-up purpose actually enforces, and what it only labels.

`STEP_UP_PURPOSES` reads like a set of separately-governed controls, and its own
comments say purposes are named separately "so an audit trail says which control
was satisfied, and so the two can be governed independently later". The word
doing the work there is **later**: at enforcement time they are not independent.

`require_recent_step_up` falls back to any purpose:

    if recent_step_up_expires_at(session, context=context, purpose=purpose):
        return
    if purpose != "step_up" and recent_step_up_expires_at(session, context=context):
        return

The second call passes no purpose, so it matches *any* unexpired step-up row. A
step-up completed to read a matter summary therefore satisfies a later
requirement to release a legal hold, for the whole TTL (15 minutes by default).

These tests pin that, and pin the fact that `require_step_up_always` - used by
the irreversible actions - does not share it. Neither behaviour is asserted
anywhere else, so without this file a change to either would be silent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    User,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.security import (
    STEP_UP_PURPOSES,
    require_recent_step_up,
    require_step_up_always,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company

MILD = "matter_summary"
IRREVERSIBLE = "legal_hold_change"


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def actor(client, session: Session) -> SessionContext:
    bootstrap = bootstrap_company(client)
    company = session.get(Company, str(bootstrap["company"]["id"]))
    membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    # Enrolled, so the CONDITIONAL gate actually engages. Un-enrolled is the
    # separate fail-open covered by EH-SEC-01.
    session.add(UserMFASetting(user_id=user.id, status="enrolled"))
    session.flush()
    return SessionContext(company=company, user=user, membership=membership)


def _step_up(session: Session, context: SessionContext, *, purpose: str) -> None:
    now = datetime.now(UTC)
    session.add(
        UserMFAStepUp(
            user_id=context.user.id,
            membership_id=context.membership.id,
            purpose=purpose,
            method="totp",
            completed_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )
    session.flush()


def _permits(fn, session: Session, context: SessionContext, *, purpose: str) -> bool:
    try:
        fn(session, context=context, purpose=purpose)
        return True
    except HTTPException:
        return False


def test_a_step_up_for_one_purpose_satisfies_another(
    session: Session, actor: SessionContext
) -> None:
    """Documenting current behaviour, not endorsing it.

    Recorded as EH-SEC-02. Whether the conditional gate SHOULD accept a
    cross-purpose step-up is a product decision - re-prompting for MFA on every
    distinct purpose within one working session has a real cost. What must not
    happen is for it to be true by accident, or to change without anyone
    noticing.
    """

    _step_up(session, actor, purpose=MILD)

    assert _permits(require_recent_step_up, session, actor, purpose=IRREVERSIBLE), (
        "if this now fails, the cross-purpose fallback was removed - that is "
        "very likely an improvement, but EH-SEC-02 and this test must be "
        "updated deliberately rather than left contradicting the code"
    )


def test_the_irreversible_gate_does_not_accept_a_cross_purpose_step_up(
    session: Session, actor: SessionContext
) -> None:
    """The property that makes the EH-SEC-01 hardening worth having twice over.

    `require_step_up_always` matches the purpose exactly, so releasing a legal
    hold cannot be authorised by a step-up someone completed to read a matter
    summary ten minutes earlier.
    """

    _step_up(session, actor, purpose=MILD)

    assert not _permits(require_step_up_always, session, actor, purpose=IRREVERSIBLE)

    # ...and it opens for the right purpose, or it is a wall rather than a gate.
    _step_up(session, actor, purpose=IRREVERSIBLE)
    assert _permits(require_step_up_always, session, actor, purpose=IRREVERSIBLE)


def test_every_purpose_the_irreversible_gate_uses_is_registered(
    session: Session, actor: SessionContext
) -> None:
    """An unregistered purpose is silently rewritten to a generic "step_up".

    `complete_step_up` records
    ``purpose if purpose in STEP_UP_PURPOSES else "step_up"``. So a typo in a
    caller's purpose string produces a row labelled `step_up`, which
    `require_step_up_always` - matching exactly - would never accept. The
    control would refuse forever rather than fail open, which is the safe
    direction, but it would be an outage nobody could diagnose from the message.
    """

    for purpose in ("data_operation_execution", "retention_policy_activation", IRREVERSIBLE):
        assert purpose in STEP_UP_PURPOSES, (
            f"{purpose} is used with require_step_up_always but is not registered; "
            "completed step-ups would be recorded as 'step_up' and never match"
        )
