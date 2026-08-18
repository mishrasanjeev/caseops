"""The production QA credential must be rotatable without deleting the tenant.

``bootstrap_ip_production_qa`` set ``owner_password`` only when CREATING the
company. Its else-branch - the one that runs whenever the tenant already exists -
contained no password reference at all. So a QA credential that drifted from the
configured secret could not be corrected, which is what left prod-verify failing
on ``401 Invalid email or password`` with no in-repo way to fix it. The same gap
meant the credential could never be rotated on a schedule or after exposure.

Rotation is opt-in on purpose. Possessing ``CASEOPS_IP_QA_PASSWORD`` must not be
sufficient to overwrite a live credential, because the ordinary bootstrap runs
idempotently and a silent overwrite would be indistinguishable from a no-op.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.security import verify_password
from caseops_api.db.models import CompanyMembership, User
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.bootstrap_ip_production_qa import ensure_ip_production_qa

_SLUG = "caseops-ip-qa-rotation"
_EMAIL = "ip-qa-bot@caseops.ai"
_NAME = "CaseOps IP QA LLP"


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


def _password(prefix: str) -> str:
    """A policy-satisfying password: the policy applies to rotation too."""
    return f"{prefix}-{uuid4().hex[:12]}-Aa1!"


def _bootstrap(session: Session, password: str, *, rotate: bool = False):
    return ensure_ip_production_qa(
        session,
        company_name=_NAME,
        company_slug=_SLUG,
        owner_full_name="CaseOps IP QA Bot",
        owner_email=_EMAIL,
        owner_password=password,
        rotate_owner_credential=rotate,
    )


def _owner(session: Session, company_id: str) -> User:
    membership = session.scalar(
        select(CompanyMembership).where(CompanyMembership.company_id == company_id)
    )
    assert membership is not None
    owner = session.get(User, membership.user_id)
    assert owner is not None
    return owner


class TestFirstRunCreates:
    def test_creating_the_tenant_sets_the_credential(self, session: Session) -> None:
        first = _password("Initial")

        result = _bootstrap(session, first)

        assert result.created_company is True
        assert result.rotated_owner_credential is False
        assert verify_password(first, _owner(session, result.company_id).password_hash)


class TestRotationIsOptIn:
    def test_re_running_without_the_flag_leaves_the_credential_alone(
        self, session: Session
    ) -> None:
        # The idempotent path must stay idempotent. A silent overwrite here would
        # be indistinguishable from a no-op to the operator running it.
        first = _password("Initial")
        created = _bootstrap(session, first)
        original_hash = _owner(session, created.company_id).password_hash

        again = _bootstrap(session, _password("Different"))

        assert again.created_company is False
        assert again.rotated_owner_credential is False
        assert _owner(session, again.company_id).password_hash == original_hash

    def test_the_flag_rotates_the_credential(self, session: Session) -> None:
        first = _password("Initial")
        _bootstrap(session, first)
        replacement = _password("Rotated")

        rotated = _bootstrap(session, replacement, rotate=True)

        assert rotated.created_company is False
        assert rotated.rotated_owner_credential is True
        owner = _owner(session, rotated.company_id)
        assert verify_password(replacement, owner.password_hash)
        # The old credential must stop working, or rotation is theatre.
        assert not verify_password(first, owner.password_hash)

    def test_the_outcome_is_reported(self, session: Session) -> None:
        # An operator needs to tell "credential reset" from "tenant already
        # existed, nothing changed" - the ambiguity that made the wrong password
        # unfixable in the first place.
        created = _bootstrap(session, _password("Initial"))
        assert created.rotated_owner_credential is False

        rotated = _bootstrap(session, _password("Rotated"), rotate=True)
        assert rotated.rotated_owner_credential is True


class TestGuardsSurviveRotation:
    def test_a_non_qa_slug_is_still_refused(self, session: Session) -> None:
        with pytest.raises(ValueError, match="caseops-ip-qa"):
            ensure_ip_production_qa(
                session,
                company_name=_NAME,
                company_slug="acme-production",
                owner_full_name="Owner",
                owner_email=_EMAIL,
                owner_password=_password("Guard"),
                rotate_owner_credential=True,
            )

    def test_a_non_caseops_owner_is_still_refused(self, session: Session) -> None:
        with pytest.raises(ValueError, match="caseops.ai"):
            ensure_ip_production_qa(
                session,
                company_name=_NAME,
                company_slug=_SLUG,
                owner_full_name="Owner",
                owner_email="attacker@example.com",
                owner_password=_password("Guard"),
                rotate_owner_credential=True,
            )

    def test_rotation_refuses_when_the_expected_owner_is_absent(
        self, session: Session
    ) -> None:
        # Identity is enforced by the membership lookup, which joins on the
        # owner email. If the tenant's owner is not the configured one, rotation
        # stops there rather than overwriting whoever happens to be present.
        created = _bootstrap(session, _password("Initial"))
        owner = _owner(session, created.company_id)
        original_hash = owner.password_hash
        owner.email = "someone-else@caseops.ai"
        session.flush()

        with pytest.raises(RuntimeError, match="no matching active owner"):
            _bootstrap(session, _password("Rotated"), rotate=True)

        # And the credential it declined to rotate is untouched.
        session.refresh(owner)
        assert owner.password_hash == original_hash
