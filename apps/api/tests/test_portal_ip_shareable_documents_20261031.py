"""BUG-015 (Ram 2026-10-31): the client-portal "Approved version" picker.

The picker listed every approved version in the tenant, so it offered
versions the publish endpoint refuses (wrong docket, category not granted)
and was a dead select when none existed. The shareable list and the publish
endpoint now share one predicate; these tests prove they agree in both
directions and that the list is tenant- and capability-scoped.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_portal_ip import _invite_ip_client

ROUTE = "/api/ip/portal/grants/{grant_id}/shareable-documents"


def _taxonomy(session, *, company_id: str, membership_id: str, key: str) -> IpDocumentTaxonomyEntry:
    entry = session.scalar(
        select(IpDocumentTaxonomyEntry).where(
            IpDocumentTaxonomyEntry.company_id == company_id,
            IpDocumentTaxonomyEntry.key == key,
        )
    )
    if entry is None:
        entry = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key=key,
            label=key.title(),
            updated_by_membership_id=membership_id,
        )
        session.add(entry)
        session.flush()
    return entry


def _seed_documents(docket_id: str) -> dict[str, str]:
    """Five versions; only "shareable" passes the publish predicate."""
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        assert docket is not None
        company_id = docket.company_id
        membership_id = docket.created_by_membership_id
        other_docket = IpDocketRecord(
            company_id=company_id, record_type="trademark", title="Other client mark",
            status="draft", restricted=False, created_by_membership_id=membership_id,
        )
        session.add(other_docket)
        session.flush()
        evidence = _taxonomy(
            session, company_id=company_id, membership_id=membership_id, key="evidence"
        )
        letters = _taxonomy(
            session, company_id=company_id, membership_id=membership_id, key="correspondence"
        )
        variants = {
            "shareable": (evidence, False, "accepted", docket_id),
            "privileged": (evidence, True, "accepted", docket_id),
            "draft": (evidence, False, "draft", docket_id),
            "category_not_granted": (letters, False, "accepted", docket_id),
            "other_docket": (evidence, False, "accepted", other_docket.id),
        }
        ids: dict[str, str] = {}
        for index, (name, (taxonomy, privileged, state, target)) in enumerate(variants.items()):
            document = IpDocument(
                company_id=company_id,
                taxonomy_entry_id=taxonomy.id,
                title=f"Portal {name}",
                is_privileged=privileged,
                created_by_membership_id=membership_id,
            )
            session.add(document)
            session.flush()
            version = IpDocumentVersion(
                company_id=company_id,
                document_id=document.id,
                version=1,
                original_filename=f"{name}.pdf",
                display_name=f"{name}.pdf",
                storage_key=f"test/{document.id}/1.pdf",
                content_type="application/pdf",
                size_bytes=10,
                sha256_hex=str(index + 1) * 64,
                state=state,
                uploaded_by_membership_id=membership_id,
            )
            session.add(version)
            session.flush()
            session.add(
                IpDocumentLink(
                    company_id=company_id,
                    document_id=document.id,
                    version_id=version.id,
                    target_type="docket",
                    target_id=target,
                    docket_id=target,
                    created_by_membership_id=membership_id,
                )
            )
            ids[name] = document.id
        session.commit()
    return ids


def test_shareable_list_and_publish_share_one_predicate(client: TestClient) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, _token = _invite_ip_client(
        client, headers, docket_id=docket["id"], categories=["evidence"]
    )
    grant_id = invitation["grants"][0]["id"]
    ids = _seed_documents(docket["id"])

    listed = client.get(ROUTE.format(grant_id=grant_id), headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["grant_id"] == grant_id
    assert body["document_categories"] == ["evidence"]
    assert [(row["document_id"], row["version_number"]) for row in body["documents"]] == [
        (ids["shareable"], 1)
    ]
    assert body["documents"][0]["taxonomy_key"] == "evidence"

    payload = {
        "portal_user_id": invitation["portal_user"]["id"],
        "grant_id": grant_id,
        "version_number": 1,
        "title": "Approved evidence",
    }
    # Every version the list withholds is one the publish endpoint refuses.
    for name, document_id in ids.items():
        if name == "shareable":
            continue
        refused = client.post(
            "/api/ip/portal/document-publications",
            headers=headers,
            json={**payload, "document_id": document_id},
        )
        assert refused.status_code in {404, 409}, (name, refused.text)
    # And the one it offers is accepted.
    published = client.post(
        "/api/ip/portal/document-publications",
        headers=headers,
        json={**payload, "document_id": ids["shareable"]},
    )
    assert published.status_code == 201, published.text


def test_shareable_list_is_tenant_capability_and_grant_scoped(client: TestClient) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, _token = _invite_ip_client(client, headers, docket_id=docket["id"])
    grant = invitation["grants"][0]
    _seed_documents(docket["id"])

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Legal LLP",
            "company_slug": "second-legal-portal",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondlegal-portal.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert second.status_code == 200, second.text
    other_headers = auth_headers(str(second.json()["access_token"]))
    cross = client.get(ROUTE.format(grant_id=grant["id"]), headers=other_headers)
    assert cross.status_code == 404, cross.text
    assert "Portal" not in cross.text

    member = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": "Portal Member",
            "email": "portal-member@asterlegal.in",
            "role": "member",
            "password": "MemberPass123!",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "portal-member@asterlegal.in",
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        ROUTE.format(grant_id=grant["id"]),
        headers=auth_headers(str(login.json()["access_token"])),
    )
    assert denied.status_code == 403, denied.text

    assert client.get(ROUTE.format(grant_id="missing-grant-id"), headers=headers).status_code == 404

    revoked = client.post(
        f"/api/admin/portal/ip-grants/{grant['id']}/revoke",
        headers=headers,
        json={"expected_row_version": 1, "reason": "Client access removed by the firm."},
    )
    assert revoked.status_code == 200, revoked.text
    after = client.get(ROUTE.format(grant_id=grant["id"]), headers=headers)
    assert after.status_code == 404, after.text
