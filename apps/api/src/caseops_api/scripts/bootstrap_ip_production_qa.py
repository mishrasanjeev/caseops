"""Create the isolated, entitled tenant used by production IP canaries.

The normal CaseOps QA tenant intentionally remains unentitled so production
regressions can prove fail-closed behavior. This command creates a separate
synthetic tenant and grants only the ``ip_workspace`` entitlement override.
Credentials are read from the configured secret environment and are never
printed. Re-running the command is idempotent.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.password_policy import enforce_password_policy
from caseops_api.core.security import hash_password
from caseops_api.db.models import (
    BillingSubscription,
    Company,
    CompanyMembership,
    MembershipRole,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.companies import BootstrapCompanyRequest
from caseops_api.services.identity import register_company_owner

_ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing", "grace", "manual_active"}
_SOURCE = "ip_production_qa"


@dataclass(frozen=True)
class IpProductionQaResult:
    company_id: str
    membership_id: str
    subscription_id: str
    created_company: bool
    created_subscription: bool
    # Reported so an operator can tell "the credential was reset" from "the
    # tenant already existed and nothing changed" - the ambiguity that made a
    # wrong QA password unfixable without deleting the tenant.
    rotated_owner_credential: bool = False
    entitlement_key: str = "ip_workspace"


def _validate_identity(*, company_name: str, company_slug: str, owner_email: str) -> None:
    if not company_slug.startswith("caseops-ip-qa"):
        raise ValueError("Production IP QA slugs must start with 'caseops-ip-qa'.")
    if "qa" not in company_name.lower():
        raise ValueError("Production IP QA company names must identify themselves as QA.")
    if not owner_email.lower().endswith("@caseops.ai"):
        raise ValueError("Production IP QA owners must use a caseops.ai address.")


def ensure_ip_production_qa(
    session: Session,
    *,
    company_name: str,
    company_slug: str,
    owner_full_name: str,
    owner_email: str,
    owner_password: str,
    rotate_owner_credential: bool = False,
) -> IpProductionQaResult:
    normalized_slug = company_slug.strip().lower()
    normalized_email = owner_email.strip().lower()
    _validate_identity(
        company_name=company_name,
        company_slug=normalized_slug,
        owner_email=normalized_email,
    )

    company = session.scalar(select(Company).where(Company.slug == normalized_slug))
    created_company = company is None
    rotated = False
    if company is None:
        auth = register_company_owner(
            session,
            BootstrapCompanyRequest(
                company_name=company_name,
                company_slug=normalized_slug,
                company_type="law_firm",
                owner_full_name=owner_full_name,
                owner_email=normalized_email,
                owner_password=owner_password,
            ),
        )
        company = session.get(Company, auth.company.id)
        membership = session.get(CompanyMembership, auth.membership.id)
        assert company is not None and membership is not None
    else:
        if company.name != company_name or company.tenant_key != normalized_slug:
            raise RuntimeError("Existing production QA tenant identity does not match.")
        membership = session.scalar(
            select(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company.id,
                CompanyMembership.is_active.is_(True),
                CompanyMembership.role == MembershipRole.OWNER,
                User.email == normalized_email,
                User.is_active.is_(True),
            )
        )
        if membership is None:
            raise RuntimeError("Existing production QA tenant has no matching active owner.")
        # Rotation is opt-in and never a side effect of the idempotent path.
        # Before this the password could only be set at tenant CREATION, so a
        # QA credential that drifted from the configured secret could not be
        # corrected without deleting the tenant - and therefore could not be
        # rotated on a schedule or after exposure either.
        if rotate_owner_credential:
            # Owner identity is already guaranteed above: the membership lookup
            # joins on User.email == normalized_email and raises if it finds
            # nothing, so a mismatched owner never reaches this branch. An extra
            # identity check here could not fire, and a guard that cannot fire
            # reads as protection that is not there.
            owner = session.get(User, membership.user_id)
            assert owner is not None
            # Validate to the SAME policy as creation. hash_password alone will
            # happily hash anything, so calling it directly would have made
            # rotation the one path that could install a weak credential.
            enforce_password_policy(owner_password)
            owner.password_hash = hash_password(owner_password)
            session.flush()
            rotated = True
        else:
            rotated = False

    subscription = session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.company_id == company.id,
            BillingSubscription.status.in_(_ACTIVE_SUBSCRIPTION_STATUSES),
        )
        .with_for_update()
    )
    created_subscription = subscription is None
    if subscription is None:
        subscription = BillingSubscription(
            company_id=company.id,
            status="manual_active",
            segment="law_firm",
            source=_SOURCE,
            externally_billable=False,
            entitlement_overrides_json={"ip_workspace": True},
            metadata_json={"synthetic_qa": True, "scope": "IPLF-025B"},
        )
        session.add(subscription)
    else:
        if subscription.source != _SOURCE or subscription.externally_billable:
            raise RuntimeError("Refusing to modify a non-QA billing subscription.")
        overrides = dict(subscription.entitlement_overrides_json or {})
        overrides["ip_workspace"] = True
        subscription.entitlement_overrides_json = overrides
        metadata = dict(subscription.metadata_json or {})
        metadata.update({"synthetic_qa": True, "scope": "IPLF-025B"})
        subscription.metadata_json = metadata

    session.commit()
    session.refresh(subscription)
    return IpProductionQaResult(
        company_id=company.id,
        membership_id=membership.id,
        subscription_id=subscription.id,
        created_company=created_company,
        created_subscription=created_subscription,
        rotated_owner_credential=rotated,
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required.")
    return value


def main() -> None:
    with get_session_factory()() as session:
        result = ensure_ip_production_qa(
            session,
            company_name=os.environ.get("CASEOPS_IP_QA_COMPANY_NAME", "CaseOps IP QA LLP"),
            company_slug=os.environ.get("CASEOPS_IP_QA_SLUG", "caseops-ip-qa"),
            owner_full_name=os.environ.get("CASEOPS_IP_QA_OWNER_NAME", "CaseOps IP QA Bot"),
            owner_email=os.environ.get("CASEOPS_IP_QA_EMAIL", "ip-qa-bot@caseops.ai"),
            owner_password=_required_env("CASEOPS_IP_QA_PASSWORD"),
            # Explicit and separate from the password itself: possessing the
            # secret must not be sufficient to overwrite a live credential.
            rotate_owner_credential=os.environ.get(
                "CASEOPS_IP_QA_ROTATE_CREDENTIAL", ""
            ).strip().lower()
            == "true",
        )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
