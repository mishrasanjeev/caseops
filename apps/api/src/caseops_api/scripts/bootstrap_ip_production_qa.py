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
        )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
