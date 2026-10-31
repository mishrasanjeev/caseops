"""Production-shaped preconditions for tests that exercise IP rule governance.

Rule and calendar governance writers enforce the company's ``ip_rule_governance``
entitlement on the server (IPLF-027B A1). A workspace is entitled in production
through a manual billing entitlement override, so tests that need an entitled
workspace use exactly that path; nothing here bypasses or monkeypatches the
server decision. Tests that prove the refusal simply do not call it.
"""

from __future__ import annotations

from sqlalchemy import select

from caseops_api.db.models import BillingSubscription
from caseops_api.db.session import get_session_factory

RULE_GOVERNANCE_ENTITLEMENT = "ip_rule_governance"


def grant_ip_rule_governance_entitlement(company_id: str) -> None:
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            session.add(
                BillingSubscription(
                    company_id=company_id,
                    status="manual_active",
                    segment="law_firm",
                    source="ip-rule-governance-test",
                    externally_billable=False,
                    entitlement_overrides_json={RULE_GOVERNANCE_ENTITLEMENT: True},
                )
            )
        else:
            subscription.entitlement_overrides_json = {
                **(subscription.entitlement_overrides_json or {}),
                RULE_GOVERNANCE_ENTITLEMENT: True,
            }
        session.commit()
