from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    MatterAccessGrant,
    MembershipRole,
    Team,
    TeamMembership,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _particulars(mark: str) -> dict[str, object]:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {"text": mark},
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "parties": [{"role": "applicant", "name": "Access Fixture LLP"}],
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": "fixture:record-access",
            }
        ],
    }


def _invite_member(
    client: TestClient,
    owner_token: str,
) -> tuple[str, dict[str, str]]:
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Restricted IP Member",
            "email": "restricted-ip-member@asterlegal.in",
            "role": "admin",
            "password": "MemberPass123!",
        },
    )
    assert created.status_code == 200, created.text
    membership_id = str(created.json()["membership_id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.OWNER
        session.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "restricted-ip-member@asterlegal.in",
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, auth_headers(
        str(login.json()["access_token"])
    )


def _create_restricted_docket(
    client: TestClient,
    headers: dict[str, str],
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Restricted ASTER",
            "restricted": True,
            "particulars": _particulars("ASTER"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_document(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
) -> tuple[str, str]:
    seeded = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    response = client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": "evidence",
                    "title": "Restricted evidence",
                    "confidentiality": "restricted",
                    "is_privileged": True,
                    "client_code": "ASTER",
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "application_no": "ACL-1",
                    "document_date": "2026-08-11",
                    "links": [{"target_type": "docket", "target_id": docket_id}],
                }
            )
        },
        files={
            "upload": (
                "restricted-source.txt",
                b"Restricted source evidence for access-policy verification.",
                "text/plain",
            )
        },
    )
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    return str(document["id"]), str(document["versions"][0]["id"])


def _assert_hidden_everywhere(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    document_id: str,
    version_id: str,
) -> None:
    listed = client.get("/api/ip/dockets", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 0
    assert listed.json()["dockets"] == []
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=headers).status_code == 404
    assert (
        client.get(f"/api/ip/dockets/{docket_id}/audit", headers=headers).status_code
        == 404
    )
    documents = client.get("/api/ip/documents", headers=headers)
    assert documents.status_code == 200, documents.text
    assert documents.json()["total"] == 0
    assert documents.json()["items"] == []
    source = client.get(
        f"/api/source-actions/targets/ip_document_version/{version_id}/open",
        headers=headers,
        params={"origin": "ip_document"},
        follow_redirects=False,
    )
    assert source.status_code == 404
    assert (
        client.get(f"/api/ip/documents/{document_id}", headers=headers).status_code
        == 404
    )


def test_restricted_ip_policy_is_shared_across_list_document_source_and_audit(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id, member_headers = _invite_member(client, owner_token)

    docket = _create_restricted_docket(client, owner_headers)
    docket_id = str(docket["id"])
    assert docket["access_policy_version"] == 1
    contract = client.get("/api/ip/access/foundation-contract", headers=owner_headers)
    assert contract.status_code == 200, contract.text
    assert contract.json()["owner_bypass"] == {
        "matter": True,
        "ip_docket": False,
    }
    reconciliation = client.get(
        "/api/ip/access/reconciliation",
        headers=owner_headers,
    )
    assert reconciliation.status_code == 200, reconciliation.text
    assert reconciliation.json()["healthy"] is True
    document_id, version_id = _upload_document(client, owner_headers, docket_id)

    _assert_hidden_everywhere(
        client,
        headers=member_headers,
        docket_id=docket_id,
        document_id=document_id,
        version_id=version_id,
    )

    with get_session_factory()() as session:
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket_id,
                membership_id=member_id,
                reason="Focused IP review.",
                granted_by_membership_id=owner_membership_id,
            )
        )
        stored = session.get(IpDocketRecord, docket_id)
        assert stored is not None
        stored.access_policy_version += 1
        session.commit()

    listed = client.get("/api/ip/dockets", headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    assert listed.json()["dockets"][0]["id"] == docket_id
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200
    documents = client.get("/api/ip/documents", headers=member_headers)
    assert documents.status_code == 200, documents.text
    assert documents.json()["total"] == 1
    assert documents.json()["items"][0]["id"] == document_id
    source = client.get(
        f"/api/source-actions/targets/ip_document_version/{version_id}/open",
        headers=member_headers,
        params={"origin": "ip_document"},
        follow_redirects=False,
    )
    assert source.status_code == 307, source.text
    assert source.headers["location"].endswith(
        f"/api/ip/documents/{document_id}/versions/1/download"
    )
    audit = client.get(f"/api/ip/dockets/{docket_id}/audit", headers=member_headers)
    assert audit.status_code == 200, audit.text
    assert audit.json()["total"] >= 2
    assert all(
        row["ip_docket_id"] == docket_id for row in audit.json()["events"]
    )
    assert {
        row["action"] for row in audit.json()["events"]
    }.issuperset({"ip_docket.created", "source_access.opened"})

    with get_session_factory()() as session:
        active_grant = session.query(MatterAccessGrant).filter_by(
            ip_docket_id=docket_id,
            membership_id=member_id,
            revoked_at=None,
        ).one()
        active_grant.revoked_at = datetime.now(UTC)
        active_grant.revoked_by_membership_id = owner_membership_id
        active_grant.record_version += 1
        stored = session.get(IpDocketRecord, docket_id)
        assert stored is not None
        stored.access_policy_version += 1
        session.commit()
    _assert_hidden_everywhere(
        client,
        headers=member_headers,
        docket_id=docket_id,
        document_id=document_id,
        version_id=version_id,
    )

    export = client.post(
        "/api/admin/audit/export/async",
        headers=member_headers,
        json={"format": "jsonl"},
    )
    assert export.status_code == 202, export.text
    job_id = str(export.json()["id"])
    status_response = client.get(
        f"/api/admin/audit/export/jobs/{job_id}",
        headers=member_headers,
    )
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "completed"
    download = client.get(
        f"/api/admin/audit/export/jobs/{job_id}/download",
        headers=member_headers,
    )
    assert download.status_code == 200, download.text
    exported_rows = [
        json.loads(line) for line in download.text.splitlines() if line.strip()
    ]
    assert all(row["ip_docket_id"] != docket_id for row in exported_rows)
    assert not any(
        row["action"].startswith("ip_document.") for row in exported_rows
    )

    with get_session_factory()() as session:
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket_id,
                membership_id=member_id,
                reason="Expired fixture.",
                effective_from=datetime.now(UTC) - timedelta(days=2),
                expires_at=datetime.now(UTC) - timedelta(days=1),
                granted_by_membership_id=owner_membership_id,
            )
        )
        session.commit()
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 404

    with get_session_factory()() as session:
        team = Team(
            company_id=company_id,
            name="Restricted IP team",
            slug="restricted-ip-team",
        )
        session.add(team)
        session.flush()
        session.add(TeamMembership(team_id=team.id, membership_id=member_id))
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket_id,
                team_id=team.id,
                reason="Team review scope.",
                granted_by_membership_id=owner_membership_id,
            )
        )
        session.commit()
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=member_headers
    ).status_code == 200

    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=company_id,
                ip_docket_id=docket_id,
                excluded_membership_id=member_id,
                reason="Conflict discovered.",
                created_by_membership_id=owner_membership_id,
            )
        )
        session.commit()
    _assert_hidden_everywhere(
        client,
        headers=member_headers,
        docket_id=docket_id,
        document_id=document_id,
        version_id=version_id,
    )

    with get_session_factory()() as session:
        session.add(
            EthicalWall(
                company_id=company_id,
                ip_docket_id=docket_id,
                excluded_membership_id=owner_membership_id,
                reason="No owner bypass for restricted IP.",
                created_by_membership_id=owner_membership_id,
            )
        )
        session.commit()
    assert client.get(
        f"/api/ip/dockets/{docket_id}", headers=owner_headers
    ).status_code == 404
