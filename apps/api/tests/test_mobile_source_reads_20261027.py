"""Bounded source readers; these are API/service proofs, not native acceptance."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, update
from sqlalchemy.exc import InvalidRequestError

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Contract,
    ContractActivity,
    ContractAttachment,
    ContractAttachmentChunk,
    ContractClause,
    ContractLegalReference,
    ContractObligation,
    ContractPlaybookRule,
    ContractTermSuggestion,
    EthicalWall,
    IpDocketRecord,
    MatterAccessGrant,
    Team,
    TeamMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.contracts import get_contract
from caseops_api.services.ip_operations import get_ip_docket_summary
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company

STAMP = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)
CONTRACT_ID = "f3000000-0000-4000-8000-000000000001"


def _context(session, seeded):
    return SessionContext(
        company=session.get(Company, seeded["company"]["id"]),
        membership=session.get(CompanyMembership, seeded["membership"]["id"]),
        user=session.get(User, seeded["user"]["id"]),
    )


def _contract_fixture(session, seeded, child_count):
    company_id = seeded["company"]["id"]
    owner_id = seeded["membership"]["id"]
    session.add(
        Contract(
            id=CONTRACT_ID,
            company_id=company_id,
            owner_membership_id=owner_id,
            title="Retained source NDA",
            contract_code="MOBILE-SOURCE-01",
            counterparty_name="Synthetic supplier",
            contract_type="NDA",
            contract_type_key=None,
            contract_type_notes=None,
            status="under_review",
            jurisdiction="IN",
            effective_on=date(2024, 2, 29),
            expires_on=None,
            renewal_on=date(2028, 2, 29),
            auto_renewal=True,
            currency="INR",
            total_value_minor=1,
            summary="Recorded terms only",
            created_at=STAMP,
            updated_at=STAMP,
        )
    )
    session.flush()
    for index in range(child_count):
        attachment = ContractAttachment(
            contract_id=CONTRACT_ID,
            uploaded_by_membership_id=owner_id,
            original_filename=f"synthetic-{index}.txt",
            storage_key=f"source-test-{index}",
            content_type="text/plain",
            size_bytes=4,
            sha256_hex="a" * 64,
        )
        session.add(attachment)
        session.flush()
        session.add_all(
            [
                ContractAttachmentChunk(attachment_id=attachment.id, chunk_index=0, content="Text"),
                ContractClause(
                    contract_id=CONTRACT_ID,
                    created_by_membership_id=owner_id,
                    title="Recorded clause",
                    clause_type="general",
                    clause_text="Synthetic",
                ),
                ContractObligation(
                    contract_id=CONTRACT_ID,
                    owner_membership_id=owner_id,
                    title="Recorded obligation",
                    due_on=date(2026, 10, 27),
                ),
                ContractPlaybookRule(
                    contract_id=CONTRACT_ID,
                    created_by_membership_id=owner_id,
                    rule_name="Recorded rule",
                    clause_type="general",
                    expected_position="Review",
                ),
                ContractLegalReference(
                    contract_id=CONTRACT_ID,
                    company_id=company_id,
                    act_name="Synthetic reference",
                    evidence_attachment_id=attachment.id,
                ),
                ContractTermSuggestion(
                    contract_id=CONTRACT_ID,
                    company_id=company_id,
                    source_attachment_id=attachment.id,
                ),
                ContractActivity(
                    contract_id=CONTRACT_ID,
                    actor_membership_id=owner_id,
                    event_type="created",
                    title="Recorded activity",
                ),
            ]
        )
    session.commit()


def _expected_contract(seeded):
    # Independent whole-DTO oracle, including nullable fields and legacy type normalization.
    return {
        "id": CONTRACT_ID,
        "company_id": seeded["company"]["id"],
        "linked_matter_id": None,
        "owner_membership_id": seeded["membership"]["id"],
        "title": "Retained source NDA",
        "contract_code": "MOBILE-SOURCE-01",
        "counterparty_name": "Synthetic supplier",
        "contract_type": "NDA",
        "contract_type_key": "nda",
        "contract_type_notes": None,
        "status": "under_review",
        "jurisdiction": "IN",
        "effective_on": "2024-02-29",
        "expires_on": None,
        "renewal_on": "2028-02-29",
        "auto_renewal": True,
        "currency": "INR",
        "total_value_minor": 1,
        "summary": "Recorded terms only",
        "created_at": "2026-10-27T01:02:03",
        "updated_at": "2026-10-27T01:02:03",
    }


@pytest.mark.parametrize("child_count", [0, 25])
def test_contract_source_cold_read_has_whole_dto_and_one_scalar_query(client, child_count):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        _contract_fixture(session, seeded, child_count)
    with get_session_factory()() as session:
        context = _context(session, seeded)
        assert not any(isinstance(row, Contract) for row in session.identity_map.values())
        statements = []
        loaded = []

        def retain(_session, instance):
            loaded.append(instance)

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(session.bind, "before_cursor_execute", capture)
        event.listen(session, "loaded_as_persistent", retain)
        try:
            record = get_contract(session, context=context, contract_id=CONTRACT_ID)
            assert record.model_dump(mode="json") == _expected_contract(seeded)
            assert len(statements) == 1
            assert "FROM contracts" in statements[0]
            stored = next(row for row in loaded if isinstance(row, Contract))
            assert {
                "clauses",
                "attachments",
                "obligations",
                "playbook_rules",
                "legal_references",
                "term_suggestions",
                "activity_events",
            } <= inspect(stored).unloaded
            with pytest.raises(InvalidRequestError, match="lazy='raise'"):
                _ = stored.clauses
        finally:
            event.remove(session.bind, "before_cursor_execute", capture)
            event.remove(session, "loaded_as_persistent", retain)
    response = client.get(
        f"/api/contracts/{CONTRACT_ID}", headers=auth_headers(seeded["access_token"])
    )
    assert response.status_code == 200, response.text
    assert response.json() == _expected_contract(seeded)


def test_contract_source_exact_tenant_missing_and_warmed_scalar_refresh(client):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        _contract_fixture(session, seeded, 0)
        context = _context(session, seeded)
        warmed = session.get(Contract, CONTRACT_ID)
        assert warmed.title == "Retained source NDA"
        session.execute(
            update(Contract)
            .where(Contract.id == CONTRACT_ID)
            .values(title="Current source")
            .execution_options(synchronize_session=False)
        )
        record = get_contract(session, context=context, contract_id=CONTRACT_ID)
        assert record.title == "Current source"
        foreign = Company(
            name="Other tenant",
            slug="other-mobile-source",
            company_type="law_firm",
            tenant_key="other-mobile-source",
        )
        session.add(foreign)
        session.flush()
        foreign_context = SessionContext(
            company=foreign, user=context.user, membership=context.membership
        )
        for requested_context, identity in [(context, "missing"), (foreign_context, CONTRACT_ID)]:
            with pytest.raises(HTTPException) as error:
                get_contract(session, context=requested_context, contract_id=identity)
            assert error.value.status_code == 404


def _docket(session, seeded, record_type="patent", **changes):
    values = dict(
        company_id=seeded["company"]["id"],
        record_type=record_type,
        title=f"Synthetic {record_type}",
        primary_identifier="SOURCE-01",
        status="draft",
        is_active=True,
        lifecycle_version=3,
        access_policy_version=2,
        current_version=4,
        updated_at=STAMP,
        created_at=STAMP,
    )
    values.update(changes)
    row = IpDocketRecord(**values)
    session.add(row)
    session.commit()
    return row.id


@pytest.mark.parametrize("record_type", ["trademark", "patent", "design"])
def test_generic_ip_source_is_exact_scalar_dto_without_trademark_children(client, record_type):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        docket_id = _docket(session, seeded, record_type)
    with get_session_factory()() as session:
        context = _context(session, seeded)
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(session.bind, "before_cursor_execute", capture)
        try:
            record = get_ip_docket_summary(session, context=context, docket_id=docket_id)
        finally:
            event.remove(session.bind, "before_cursor_execute", capture)
        assert len(statements) == 2  # Exact scalar lookup and current canonical visibility policy.
        assert all(
            "trademark_applications" not in sql and "ip_docket_events" not in sql
            for sql in statements
        )
        expected = {
            "id": docket_id,
            "company_id": seeded["company"]["id"],
            "matter_id": None,
            "record_type": record_type,
            "title": f"Synthetic {record_type}",
            "primary_identifier": "SOURCE-01",
            "status": "draft",
            "is_active": True,
            "lifecycle_version": 3,
            "access_policy_version": 2,
            "current_version": 4,
            "updated_at": "2026-10-27T01:02:03Z",
        }
        assert record.model_dump(mode="json") == expected
    response = client.get(
        f"/api/ip/dockets/{docket_id}/summary", headers=auth_headers(seeded["access_token"])
    )
    assert response.status_code == 200, response.text
    assert response.json() == expected
    client.cookies.clear()
    anonymous = client.get(f"/api/ip/dockets/{docket_id}/summary")
    assert anonymous.status_code == 401


def test_generic_ip_source_current_grants_walls_and_team_revocation_even_for_owner(client):
    seeded = bootstrap_company(client)
    company_id, membership_id = seeded["company"]["id"], seeded["membership"]["id"]
    headers = auth_headers(seeded["access_token"])
    with get_session_factory()() as session:
        docket_id = _docket(session, seeded, restricted=True)
    path = f"/api/ip/dockets/{docket_id}/summary"
    denied = client.get(path, headers=headers)
    assert denied.status_code == 404  # No owner bypass of the canonical restricted IP policy.
    with get_session_factory()() as session:
        team = Team(company_id=company_id, name="Source readers", slug="source-readers")
        session.add(team)
        session.flush()
        team_id = team.id
        member = TeamMembership(team_id=team_id, membership_id=membership_id)
        session.add(member)
        grant = MatterAccessGrant(
            company_id=company_id,
            ip_docket_id=docket_id,
            team_id=team_id,
            reason="Synthetic team grant",
            granted_by_membership_id=membership_id,
        )
        session.add(grant)
        session.commit()
        member_id = member.id
    allowed = client.get(path, headers=headers)
    assert allowed.status_code == 200, allowed.text
    with get_session_factory()() as session:
        session.delete(session.get(TeamMembership, member_id))
        session.commit()
    revoked = client.get(path, headers=headers)
    assert revoked.status_code == 404
    with get_session_factory()() as session:
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket_id,
                membership_id=membership_id,
                reason="Direct source grant",
                granted_by_membership_id=membership_id,
            )
        )
        session.commit()
    direct = client.get(path, headers=headers)
    assert direct.status_code == 200
    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=company_id,
                ip_docket_id=docket_id,
                excluded_membership_id=membership_id,
                reason="Synthetic wall",
                created_by_membership_id=membership_id,
            )
        )
        session.commit()
    walled = client.get(path, headers=headers)
    assert walled.status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "archived", "is_active": False},
        {"archived_by_matter_disposal": True},
    ],
)
def test_generic_ip_source_inactive_and_disposed_records_stay_hidden(client, changes):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        docket_id = _docket(session, seeded, **changes)
    response = client.get(
        f"/api/ip/dockets/{docket_id}/summary", headers=auth_headers(seeded["access_token"])
    )
    assert response.status_code == 404


def test_generic_ip_source_missing_cross_tenant_and_expired_grant_stay_hidden(client):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        docket_id = _docket(session, seeded, restricted=True)
        context = _context(session, seeded)
        expired_at = datetime.now(UTC) - timedelta(days=1)
        session.add(
            MatterAccessGrant(
                company_id=context.company.id,
                ip_docket_id=docket_id,
                membership_id=context.membership.id,
                reason="Expired source grant",
                granted_by_membership_id=context.membership.id,
                effective_from=expired_at - timedelta(days=1),
                expires_at=expired_at,
            )
        )
        session.commit()
        foreign = Company(
            name="Other IP tenant",
            slug="other-ip-source",
            company_type="law_firm",
            tenant_key="other-ip-source",
        )
        session.add(foreign)
        session.flush()
        foreign_context = SessionContext(
            company=foreign, user=context.user, membership=context.membership
        )
        for current, identity in [
            (context, docket_id),
            (context, "missing"),
            (foreign_context, docket_id),
        ]:
            with pytest.raises(HTTPException) as error:
                get_ip_docket_summary(session, context=current, docket_id=identity)
            assert error.value.status_code == 404


def test_contract_source_retained_nullable_metadata_is_not_promoted_or_hidden(client):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        _contract_fixture(session, seeded, 0)
        row = session.get(Contract, CONTRACT_ID)
        row.owner_membership_id = None
        row.counterparty_name = None
        row.contract_type = "Retained custom label"
        row.effective_on = row.expires_on = row.renewal_on = None
        row.total_value_minor = None
        row.summary = row.jurisdiction = None
        session.commit()
    response = client.get(
        f"/api/contracts/{CONTRACT_ID}", headers=auth_headers(seeded["access_token"])
    )
    assert response.status_code == 200, response.text
    expected = _expected_contract(seeded)
    expected.update(
        owner_membership_id=None,
        counterparty_name=None,
        contract_type="Retained custom label",
        contract_type_key="other",
        contract_type_notes="Retained custom label",
        effective_on=None,
        expires_on=None,
        renewal_on=None,
        total_value_minor=None,
        summary=None,
        jurisdiction=None,
    )
    # updated_at legitimately changes on mutation; bind its actual persisted value.
    with get_session_factory()() as session:
        persisted = session.get(Contract, CONTRACT_ID)
        expected["updated_at"] = persisted.updated_at.isoformat()
    assert response.json() == expected


@pytest.mark.postgres
def test_generic_ip_source_populated_postgres_response_has_explicit_utc(isolated_postgres_client):
    client = isolated_postgres_client
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        docket_id = _docket(session, seeded, "design")
    response = client.get(
        f"/api/ip/dockets/{docket_id}/summary", headers=auth_headers(seeded["access_token"])
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": docket_id,
        "company_id": seeded["company"]["id"],
        "matter_id": None,
        "record_type": "design",
        "title": "Synthetic design",
        "primary_identifier": "SOURCE-01",
        "status": "draft",
        "is_active": True,
        "lifecycle_version": 3,
        "access_policy_version": 2,
        "current_version": 4,
        "updated_at": "2026-10-27T01:02:03Z",
    }


def test_http_source_readers_bind_the_authenticated_company_not_caller_ids(client):
    seeded = bootstrap_company(client)
    with get_session_factory()() as session:
        _contract_fixture(session, seeded, 0)
        docket_id = _docket(session, seeded, "patent")
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other source tenant",
            "company_slug": "other-source-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other synthetic owner",
            "owner_email": "other-source@example.com",
            "owner_password": "OtherSourcePass123!",
        },
    )
    assert second.status_code == 200, second.text
    other_headers = auth_headers(second.json()["access_token"])
    for path in [f"/api/contracts/{CONTRACT_ID}", f"/api/ip/dockets/{docket_id}/summary"]:
        response = client.get(path, headers=other_headers)
        assert response.status_code == 404
