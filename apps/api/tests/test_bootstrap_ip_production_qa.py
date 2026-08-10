from sqlalchemy import func, select

from caseops_api.db.models import BillingSubscription, Company, CompanyMembership, User
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.bootstrap_ip_production_qa import ensure_ip_production_qa


def test_bootstrap_ip_production_qa_is_bounded_and_idempotent(client) -> None:
    del client
    factory = get_session_factory()
    payload = {
        "company_name": "CaseOps IP QA LLP",
        "company_slug": "caseops-ip-qa-test",
        "owner_full_name": "CaseOps IP QA Bot",
        "owner_email": "ip-qa-test@caseops.ai",
        "owner_password": "ProductionQa2026!Safe",
    }
    with factory() as session:
        created = ensure_ip_production_qa(session, **payload)
        repeated = ensure_ip_production_qa(session, **payload)

        company = session.scalar(select(Company).where(Company.slug == payload["company_slug"]))
        assert company is not None
        membership = session.scalar(
            select(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company.id,
                User.email == payload["owner_email"],
            )
        )
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company.id)
        )
        assert membership is not None
        assert subscription is not None
        assert subscription.status == "manual_active"
        assert subscription.source == "ip_production_qa"
        assert subscription.externally_billable is False
        assert subscription.entitlement_overrides_json == {"ip_workspace": True}
        assert subscription.metadata_json == {"synthetic_qa": True, "scope": "IPLF-025B"}
        assert (
            session.scalar(
                select(func.count())
                .select_from(BillingSubscription)
                .where(BillingSubscription.company_id == company.id)
            )
            == 1
        )

    assert created.created_company is True
    assert created.created_subscription is True
    assert repeated.company_id == created.company_id
    assert repeated.membership_id == created.membership_id
    assert repeated.subscription_id == created.subscription_id
    assert repeated.created_company is False
    assert repeated.created_subscription is False


def test_bootstrap_ip_production_qa_rejects_non_qa_identity(client) -> None:
    del client
    with get_session_factory()() as session:
        try:
            ensure_ip_production_qa(
                session,
                company_name="Customer LLP",
                company_slug="customer",
                owner_full_name="Customer Owner",
                owner_email="customer@example.com",
                owner_password="ProductionQa2026!Safe",
            )
        except ValueError as exc:
            assert "Production IP QA" in str(exc)
        else:
            raise AssertionError("Non-QA identity was accepted")
