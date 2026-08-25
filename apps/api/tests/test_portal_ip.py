"""IPLF-055 client portal grants, publications, and instructions."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    MatterPortalGrant,
    NotificationDeliveryIntent,
    PortalUser,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.portal_ip import list_portal_ip_records, list_portal_publications
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture

TESTED_PORTAL_IP_ROUTE_TEMPLATES = (
    "/api/admin/portal/ip-grants",
    "/api/admin/portal/ip-grants/{grant_id}/revoke",
    "/api/ip/portal/report-publications",
    "/api/ip/portal/document-publications",
    "/api/ip/portal/client-instructions",
    "/api/ip/portal/client-instructions/{instruction_id}/acknowledge",
    "/api/portal/ip-records",
    "/api/portal/ip-records/{docket_id}",
    "/api/portal/publications",
    "/api/portal/publications/{publication_id}",
    "/api/portal/publications/{publication_id}/document",
    "/api/portal/publications/{publication_id}/instructions",
)


def _invite_ip_client(
    client: TestClient,
    headers: dict[str, str],
    *,
    docket_id: str,
    categories: list[str] | None = None,
) -> tuple[dict, str]:
    response = client.post(
        "/api/admin/portal/invitations",
        headers=headers,
        json={
            "email": "client-ip@example.com",
            "full_name": "IP Client",
            "role": "client",
            "ip_docket_ids": [docket_id],
            "event_kinds": ["registry_snapshot_accepted"],
            "deadline_kinds": ["opposition_evidence"],
            "document_categories": categories or ["evidence"],
            "can_submit_instructions": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["grants"][0]["target_type"] == "ip_docket"
    return body, str(body["debug_token"])


def _verify_portal(client: TestClient, debug_token: str) -> None:
    client.cookies.clear()
    response = client.post("/api/portal/auth/verify-link", json={"token": debug_token})
    assert response.status_code == 200, response.text


def _portal_csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("caseops_portal_csrf")
    assert token
    return {"X-Portal-CSRF-Token": token}


def _preview(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/ip/reports/preview",
        headers=headers,
        json={"report_kind": "portfolio_register", "row_limit": 50},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish_report(
    client: TestClient,
    headers: dict[str, str],
    *,
    invitation: dict,
    snapshot_sha256: str,
) -> dict:
    response = client.post(
        "/api/ip/portal/report-publications",
        headers=headers,
        json={
            "portal_user_id": invitation["portal_user"]["id"],
            "grant_ids": [invitation["grants"][0]["id"]],
            "title": "Portfolio status update",
            "report_kind": "portfolio_register",
            "row_limit": 50,
            "expected_snapshot_sha256": snapshot_sha256,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ip_portal_report_instruction_acknowledgement_and_revoke(
    client: TestClient,
) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, debug_token = _invite_ip_client(client, headers, docket_id=docket["id"])
    preview = _preview(client, headers)
    publication = _publish_report(
        client,
        headers,
        invitation=invitation,
        snapshot_sha256=preview["snapshot_sha256"],
    )
    assert publication["access_state"] == "available"
    assert publication["summary"] == {
        "published_record_count": 1,
        "report_kind": "portfolio_register",
    }
    assert len(publication["rows"]) == 1
    assert "provenance" not in publication["rows"][0]
    assert "source_refs" not in publication["rows"][0]

    _verify_portal(client, debug_token)
    records = client.get("/api/portal/ip-records")
    assert records.status_code == 200, records.text
    assert [row["id"] for row in records.json()["records"]] == [docket["id"]]
    assert records.json()["records"][0]["identifiers"] == [
        "TM / 2026 / 00421",
        "OPP / 88 / 2026",
    ]

    opened = client.get(f"/api/portal/publications/{publication['id']}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["access_state"] == "available"
    assert opened.json()["rows"][0]["opposition_numbers"] == ["OPP / 88 / 2026"]

    instruction = client.post(
        f"/api/portal/publications/{publication['id']}/instructions",
        headers=_portal_csrf(client),
        json={
            "decision": "proceed",
            "instruction_kind": "proceeding",
            "docket_id": docket["id"],
            "note": "Please proceed with the opposition response.",
        },
    )
    assert instruction.status_code == 201, instruction.text
    assert instruction.json()["status"] == "pending"

    firm_list = client.get(
        "/api/ip/portal/client-instructions",
        headers=headers,
    )
    assert firm_list.status_code == 200, firm_list.text
    assert [row["id"] for row in firm_list.json()["instructions"]] == [instruction.json()["id"]]
    acknowledged = client.post(
        f"/api/ip/portal/client-instructions/{instruction.json()['id']}/acknowledge",
        headers=headers,
        json={
            "expected_row_version": instruction.json()["row_version"],
            "status": "accepted",
            "reason": "Instruction checked against the current proceeding and accepted.",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "accepted"

    grant = invitation["grants"][0]
    revoked = client.post(
        f"/api/admin/portal/ip-grants/{grant['id']}/revoke",
        headers=headers,
        json={
            "expected_row_version": grant["row_version"],
            "reason": "Client engagement scope ended.",
        },
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["active"] is False
    assert client.get("/api/portal/ip-records").status_code == 401

    with get_session_factory()() as session:
        stored_docket = session.get(IpDocketRecord, docket["id"])
        assert stored_docket is not None and stored_docket.status == docket["status"]
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.action.in_(
                        (
                            "portal.report.published",
                            "portal.publication.opened",
                            "portal.client_instruction.submitted",
                            "portal.client_instruction.accepted",
                            "portal.ip_grant.revoked",
                        )
                    )
                )
            )
        )
        assert actions == {
            "portal.report.published",
            "portal.publication.opened",
            "portal.client_instruction.submitted",
            "portal.client_instruction.accepted",
            "portal.ip_grant.revoked",
        }


def test_report_publication_rejects_stale_preview_and_withholds_stale_targets(
    client: TestClient,
) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, debug_token = _invite_ip_client(client, headers, docket_id=docket["id"])
    preview = _preview(client, headers)
    stale = client.post(
        "/api/ip/portal/report-publications",
        headers=headers,
        json={
            "portal_user_id": invitation["portal_user"]["id"],
            "grant_ids": [invitation["grants"][0]["id"]],
            "title": "Unreviewed status update",
            "report_kind": "portfolio_register",
            "row_limit": 50,
            "expected_snapshot_sha256": "0" * 64,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "portal_report_preview_stale"

    blocked_kind = client.post(
        "/api/ip/portal/report-publications",
        headers=headers,
        json={
            "portal_user_id": invitation["portal_user"]["id"],
            "grant_ids": [invitation["grants"][0]["id"]],
            "title": "Internal workload",
            "report_kind": "workload",
            "expected_snapshot_sha256": "0" * 64,
        },
    )
    assert blocked_kind.status_code == 422

    publication = _publish_report(
        client,
        headers,
        invitation=invitation,
        snapshot_sha256=preview["snapshot_sha256"],
    )
    with get_session_factory()() as session:
        row = session.get(IpDocketRecord, docket["id"])
        assert row is not None
        row.current_version += 1
        session.commit()

    _verify_portal(client, debug_token)
    response = client.get(f"/api/portal/publications/{publication['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["access_state"] == "review_required"
    assert response.json()["rows"] is None
    assert response.json()["summary"] is None


def test_document_publication_allows_only_granted_approved_nonprivileged_version(
    client: TestClient,
) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, debug_token = _invite_ip_client(
        client, headers, docket_id=docket["id"], categories=["evidence"]
    )
    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket["id"])
        assert docket_row is not None
        company_id = docket_row.company_id
        membership_id = docket_row.created_by_membership_id
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="evidence",
            label="Evidence",
            updated_by_membership_id=membership_id,
        )
        session.add(taxonomy)
        session.flush()
        documents: list[tuple[IpDocument, IpDocumentVersion]] = []
        for privileged, state in ((False, "accepted"), (True, "accepted"), (False, "draft")):
            document = IpDocument(
                company_id=company_id,
                taxonomy_entry_id=taxonomy.id,
                title=f"Evidence {len(documents) + 1}",
                is_privileged=privileged,
                created_by_membership_id=membership_id,
            )
            session.add(document)
            session.flush()
            version = IpDocumentVersion(
                company_id=company_id,
                document_id=document.id,
                version=1,
                original_filename=f"evidence-{len(documents) + 1}.pdf",
                display_name=f"evidence-{len(documents) + 1}.pdf",
                storage_key=f"test/{document.id}/1.pdf",
                content_type="application/pdf",
                size_bytes=10,
                sha256_hex=str(len(documents) + 1) * 64,
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
                    target_id=docket["id"],
                    docket_id=docket["id"],
                    created_by_membership_id=membership_id,
                )
            )
            documents.append((document, version))
        session.commit()
        document_ids = [(document.id, version.version) for document, version in documents]

    payload = {
        "portal_user_id": invitation["portal_user"]["id"],
        "grant_id": invitation["grants"][0]["id"],
        "version_number": 1,
        "title": "Approved evidence",
    }
    for document_id, expected_code in (
        (document_ids[1][0], "portal_document_not_shareable"),
        (document_ids[2][0], "portal_document_not_shareable"),
    ):
        response = client.post(
            "/api/ip/portal/document-publications",
            headers=headers,
            json={**payload, "document_id": document_id},
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == expected_code

    shared = client.post(
        "/api/ip/portal/document-publications",
        headers=headers,
        json={**payload, "document_id": document_ids[0][0]},
    )
    assert shared.status_code == 201, shared.text
    assert shared.json()["document_filename"] == "evidence-1.pdf"
    _verify_portal(client, debug_token)
    visible = client.get(f"/api/portal/publications/{shared.json()['id']}")
    assert visible.status_code == 200, visible.text
    assert visible.json()["document_id"] == document_ids[0][0]

    with get_session_factory()() as session:
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.schedule_source_type == "portal_publication"
                )
            )
        )
        portal_intents = [
            intent for intent in intents if intent.recipient_portal_user_id is not None
        ]
        escalation_intents = [
            intent for intent in intents if intent.recipient_membership_id is not None
        ]
        assert len(portal_intents) == 1
        assert len(escalation_intents) == 1
        assert portal_intents[0].recipient_snapshot_json["destination"] == "client-ip@example.com"


def test_portal_lists_keep_a_fixed_query_budget_as_rows_grow(client: TestClient) -> None:
    headers, docket, _application = _rich_portfolio_fixture(client)
    invitation, _debug_token = _invite_ip_client(client, headers, docket_id=docket["id"])
    preview = _preview(client, headers)
    for index in range(3):
        response = client.post(
            "/api/ip/portal/report-publications",
            headers=headers,
            json={
                "portal_user_id": invitation["portal_user"]["id"],
                "grant_ids": [invitation["grants"][0]["id"]],
                "title": f"Portfolio status update {index}",
                "report_kind": "portfolio_register",
                "row_limit": 50,
                "expected_snapshot_sha256": preview["snapshot_sha256"],
            },
        )
        assert response.status_code == 201, response.text

    with get_session_factory()() as session:
        source = session.get(IpDocketRecord, docket["id"])
        portal_user = session.get(PortalUser, invitation["portal_user"]["id"])
        source_grant = session.get(MatterPortalGrant, invitation["grants"][0]["id"])
        assert source is not None and portal_user is not None and source_grant is not None
        for index in range(2):
            extra = IpDocketRecord(
                company_id=source.company_id,
                matter_id=source.matter_id,
                record_type=source.record_type,
                title=f"Portal query budget {index}",
                status=source.status,
                restricted=False,
                created_by_membership_id=source.created_by_membership_id,
            )
            session.add(extra)
            session.flush()
            session.add(
                MatterPortalGrant(
                    company_id=source.company_id,
                    portal_user_id=portal_user.id,
                    ip_docket_record_id=extra.id,
                    role="client",
                    scope_json=source_grant.scope_json,
                    granted_by_membership_id=source_grant.granted_by_membership_id,
                    granted_by_label_snapshot=source_grant.granted_by_label_snapshot,
                )
            )
        session.commit()

        query_count = 0

        def count_query(*_args: object) -> None:
            nonlocal query_count
            query_count += 1

        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", count_query)
        try:
            records = list_portal_ip_records(session, portal_user=portal_user)
        finally:
            event.remove(bind, "before_cursor_execute", count_query)
        assert len(records.records) == 3
        assert query_count <= 4

        query_count = 0
        event.listen(bind, "before_cursor_execute", count_query)
        try:
            publications = list_portal_publications(session, portal_user=portal_user)
        finally:
            event.remove(bind, "before_cursor_execute", count_query)
        assert len(publications.publications) == 3
        assert query_count <= 5
