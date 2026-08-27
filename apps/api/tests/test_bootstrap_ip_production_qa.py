from datetime import UTC, datetime

from sqlalchemy import func, select

from caseops_api.db.models import (
    AuthorityDocument,
    BillingSubscription,
    Company,
    CompanyMembership,
    Court,
    Judge,
    JudgeDecisionIndex,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.bootstrap_ip_production_qa import (
    ensure_ip_production_qa,
    ensure_ip_production_qa_judge_fixture,
    ensure_ip_production_qa_review_fixture,
)
from caseops_api.services.source_actions import authority_source_verified


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


def test_bootstrap_ip_production_qa_judge_fixture_is_bounded_and_idempotent(
    client,
) -> None:
    del client
    with get_session_factory()() as session:
        created = ensure_ip_production_qa_judge_fixture(session)
        repeated = ensure_ip_production_qa_judge_fixture(session)

        judges = list(
            session.scalars(select(Judge).where(Judge.source_name == "ip_production_qa"))
        )
        authorities = list(
            session.scalars(
                select(AuthorityDocument).where(
                    AuthorityDocument.adapter_name
                    == "caseops-ip-production-qa-judge-authorities-v1"
                )
            )
        )
        mappings = list(
            session.scalars(
                select(JudgeDecisionIndex).where(
                    JudgeDecisionIndex.resolver_version
                    == "iplf-060b-production-qa-v1"
                )
            )
        )

    assert created.pilot_courts == 3
    assert created.created_judges == 3
    assert created.created_authorities == 3
    assert created.created_mappings == 3
    assert repeated.created_judges == 0
    assert repeated.created_authorities == 0
    assert repeated.created_mappings == 0
    assert len(judges) == 3
    assert len(authorities) == 3
    assert len(mappings) == 3
    assert all(item.is_analytics_eligible is False for item in mappings)
    assert all(item.mapping_status == "curator_confirmed" for item in mappings)
    assert all(
        authority_source_verified(item.source, item.source_reference)
        for item in authorities
    )


def test_bootstrap_ip_production_qa_judge_fixture_refuses_non_qa_collision(
    client,
) -> None:
    del client
    with get_session_factory()() as session:
        court = session.scalar(select(Court).where(Court.name == "Delhi High Court"))
        assert court is not None
        session.add(
            Judge(
                court_id=court.id,
                full_name="Justice CaseOps QA Pilot - Delhi",
                source_name="official_court",
                is_active=True,
            )
        )
        session.commit()

        try:
            ensure_ip_production_qa_judge_fixture(session)
        except RuntimeError as exc:
            assert "non-QA judge fixture collision" in str(exc)
        else:
            raise AssertionError("A non-QA judge fixture collision was adopted")

        fixture_authorities = session.scalar(
            select(func.count())
            .select_from(AuthorityDocument)
            .where(
                AuthorityDocument.adapter_name
                == "caseops-ip-production-qa-judge-authorities-v1"
            )
        )
        assert fixture_authorities == 0


def test_bootstrap_ip_production_qa_review_fixture_is_bounded_and_idempotent(
    client,
) -> None:
    del client
    with get_session_factory()() as session:
        created = ensure_ip_production_qa_review_fixture(session)
        repeated = ensure_ip_production_qa_review_fixture(session)
        authorities = list(
            session.scalars(
                select(AuthorityDocument).where(
                    AuthorityDocument.adapter_name
                    == "caseops-ip-production-qa-intelligent-review-v1"
                )
            )
        )

    assert created.authority_count == 3
    assert created.created_authorities == 3
    assert repeated.created_authorities == 0
    assert len(authorities) == 3
    assert sum(item.source_access_state == "available" for item in authorities) == 2
    assert sum(item.source_access_state == "unavailable" for item in authorities) == 1
    assert all(item.authority_status == "synthetic_qa" for item in authorities)
    assert all(item.content_hash and item.source_version for item in authorities)


def test_bootstrap_ip_production_qa_review_fixture_refuses_non_qa_collision(
    client,
) -> None:
    del client
    with get_session_factory()() as session:
        session.add(
            AuthorityDocument(
                source="official",
                adapter_name="non-qa-owner",
                court_name="Synthetic QA Court",
                forum_level="tribunal",
                document_type="judgment",
                title="Collision",
                canonical_key="iplf-063b-production-qa-v1:supporting",
                source_reference="https://example.com/collision",
                summary="Non-QA collision fixture.",
                ingested_at=datetime(2026, 8, 28, tzinfo=UTC),
            )
        )
        session.commit()

        try:
            ensure_ip_production_qa_review_fixture(session)
        except RuntimeError as exc:
            assert "non-QA review fixture collision" in str(exc)
        else:
            raise AssertionError("A non-QA review fixture collision was adopted")
