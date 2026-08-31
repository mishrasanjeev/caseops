from datetime import UTC, datetime

from sqlalchemy import func, select

from caseops_api.db.models import (
    AuthorityDocument,
    BillingSubscription,
    Company,
    CompanyMembership,
    Court,
    IpDocketRecord,
    IpProceeding,
    Judge,
    JudgeDecisionIndex,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts.bootstrap_ip_production_qa import (
    ensure_ip_production_qa,
    ensure_ip_production_qa_judge_fixture,
    ensure_ip_production_qa_private_retrieval_fixture,
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


def test_bootstrap_private_retrieval_fixture_is_release_scoped_and_idempotent(
    client,
) -> None:
    del client
    release_sha = "a" * 40
    with get_session_factory()() as session:
        tenant = ensure_ip_production_qa(
            session,
            company_name="CaseOps IP QA Private Retrieval",
            company_slug="caseops-ip-qa-private-retrieval",
            owner_full_name="CaseOps IP QA Bot",
            owner_email="ip-qa-private-retrieval@caseops.ai",
            owner_password="ProductionQa2026!Safe",
        )
        created = ensure_ip_production_qa_private_retrieval_fixture(
            session,
            company_id=tenant.company_id,
            membership_id=tenant.membership_id,
            release_sha=release_sha,
        )
        legacy_attachment = session.get(MatterAttachment, created.attachment_id)
        assert legacy_attachment is not None
        legacy_attachment.storage_key = f"synthetic-qa/iplf-066b/{release_sha}"
        session.commit()
        repeated = ensure_ip_production_qa_private_retrieval_fixture(
            session,
            company_id=tenant.company_id,
            membership_id=tenant.membership_id,
            release_sha=release_sha,
        )

        matter = session.get(Matter, created.matter_id)
        attachment = session.get(MatterAttachment, created.attachment_id)
        chunks = list(
            session.scalars(
                select(MatterAttachmentChunk).where(
                    MatterAttachmentChunk.attachment_id == created.attachment_id
                )
            )
        )
        generation = session.get(PrivateIndexGeneration, created.generation_id)
        docket = session.get(IpDocketRecord, created.docket_id)
        proceeding = session.get(IpProceeding, created.proceeding_id)
        projections = list(
            session.scalars(
                select(PrivateIndexProjection).where(
                    PrivateIndexProjection.company_id == tenant.company_id,
                    PrivateIndexProjection.generation_id == created.generation_id,
                    PrivateIndexProjection.source_id == created.attachment_id,
                    PrivateIndexProjection.is_tombstoned.is_(False),
                )
            )
        )

    assert created.created_fixture is True
    assert repeated.created_fixture is False
    assert repeated.matter_id == created.matter_id
    assert repeated.attachment_id == created.attachment_id
    assert repeated.generation_id == created.generation_id
    assert created.matter_code == "IPLF-066B-AAAAAAAAAAAA"
    assert created.docket_title == "IPLF-063B exact-release review aaaaaaaaaaaa"
    assert matter is not None and matter.status == "active" and matter.is_active is True
    assert attachment is not None and attachment.processing_status == "indexed"
    assert docket is not None and docket.primary_identifier == "QA-063B-AAAAAAAAAAAA"
    assert proceeding is not None and proceeding.docket_id == docket.id
    assert proceeding.proceeding_kind == "opposition"
    assert proceeding.side == "opponent"
    assert "Aurora-aaaaaaaaaaaa" in (attachment.extracted_text or "")
    assert len(chunks) == 1
    assert generation is not None and generation.state == "active"
    assert len(projections) == 1
    assert repeated.docket_id == created.docket_id
    assert repeated.proceeding_id == created.proceeding_id


def test_bootstrap_private_retrieval_fixture_is_tenant_scoped_for_one_release(
    client,
) -> None:
    del client
    release_sha = "c" * 40
    with get_session_factory()() as session:
        first = ensure_ip_production_qa(
            session,
            company_name="CaseOps IP QA Private Retrieval First",
            company_slug="caseops-ip-qa-private-first",
            owner_full_name="CaseOps IP QA Bot",
            owner_email="ip-qa-private-first@caseops.ai",
            owner_password="ProductionQa2026!Safe",
        )
        second = ensure_ip_production_qa(
            session,
            company_name="CaseOps IP QA Private Retrieval Second",
            company_slug="caseops-ip-qa-private-second",
            owner_full_name="CaseOps IP QA Bot",
            owner_email="ip-qa-private-second@caseops.ai",
            owner_password="ProductionQa2026!Safe",
        )

        first_fixture = ensure_ip_production_qa_private_retrieval_fixture(
            session,
            company_id=first.company_id,
            membership_id=first.membership_id,
            release_sha=release_sha,
        )
        second_fixture = ensure_ip_production_qa_private_retrieval_fixture(
            session,
            company_id=second.company_id,
            membership_id=second.membership_id,
            release_sha=release_sha,
        )
        first_attachment = session.get(MatterAttachment, first_fixture.attachment_id)
        second_attachment = session.get(MatterAttachment, second_fixture.attachment_id)
        first_docket = session.get(IpDocketRecord, first_fixture.docket_id)
        second_docket = session.get(IpDocketRecord, second_fixture.docket_id)

    assert first_attachment is not None
    assert second_attachment is not None
    assert first_attachment.storage_key != second_attachment.storage_key
    assert first_attachment.storage_key == (
        f"synthetic-qa/{first.company_id}/iplf-066b/{release_sha}"
    )
    assert second_attachment.storage_key == (
        f"synthetic-qa/{second.company_id}/iplf-066b/{release_sha}"
    )
    assert first_docket is not None and second_docket is not None
    assert first_docket.id != second_docket.id
    assert first_docket.company_id == first.company_id
    assert second_docket.company_id == second.company_id


def test_bootstrap_private_retrieval_fixture_refuses_terminal_resurrection(
    client,
) -> None:
    del client
    with get_session_factory()() as session:
        tenant = ensure_ip_production_qa(
            session,
            company_name="CaseOps IP QA Private Retrieval Terminal",
            company_slug="caseops-ip-qa-private-retrieval-terminal",
            owner_full_name="CaseOps IP QA Bot",
            owner_email="ip-qa-private-terminal@caseops.ai",
            owner_password="ProductionQa2026!Safe",
        )
        fixture = ensure_ip_production_qa_private_retrieval_fixture(
            session,
            company_id=tenant.company_id,
            membership_id=tenant.membership_id,
            release_sha="b" * 40,
        )
        matter = session.get(Matter, fixture.matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()

        try:
            ensure_ip_production_qa_private_retrieval_fixture(
                session,
                company_id=tenant.company_id,
                membership_id=tenant.membership_id,
                release_sha="b" * 40,
            )
        except RuntimeError as exc:
            assert "refusing to resurrect" in str(exc)
        else:
            raise AssertionError("A terminal private retrieval QA fixture was resurrected")
