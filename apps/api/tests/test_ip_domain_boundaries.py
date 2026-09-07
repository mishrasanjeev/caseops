from __future__ import annotations

from typing import get_args

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    IpAsset,
    IpDocketEvent,
    IpDocketRecord,
    IpDocumentLink,
    IpTrademarkParticularVersion,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_international import TrademarkInternationalRecordCreateRequest
from caseops_api.services.ip_domain_policy import (
    TRADEMARK_RECORD_TYPES,
    assert_trademark_docket,
    general_ip_disclosure_allowed,
)
from caseops_api.services.ip_lifecycle import (
    append_ip_docket_event,
    get_ip_prosecution_workspace,
    preview_ip_docket_event,
)
from caseops_api.services.matter_access import seed_restricted_ip_creator_access
from caseops_api.services.private_retrieval import (
    PrivateProjectionInput,
    ProjectionScopeInput,
    ensure_active_private_generation,
    hydrate_private_projection_results,
    prefilter_private_projection_ids,
    private_source_version,
    upsert_private_projection,
)
from caseops_api.services.private_retrieval_jobs import _private_projection_inputs
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_workflow import _upload
from tests.test_ip_lifecycle_service import _context, _manual_event
from tests.test_ip_record_workflow import _docket, _particulars
from tests.test_workspace_assistant_foundation import _create, _enable


def _restricted_domain(client: TestClient, domain: str = "patent"):
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        docket = IpDocketRecord(
            company_id=context.company.id,
            record_type=domain,
            title="Unpublished invention confidential substrate",
            status="draft",
            restricted=True,
            created_by_membership_id=context.membership.id,
        )
        session.add(docket)
        session.flush()
        seed_restricted_ip_creator_access(session, context=context, docket=docket)
        session.commit()
        return bootstrap, headers, docket.id


def test_every_existing_madrid_record_kind_keeps_its_trademark_domain() -> None:
    kind_field = TrademarkInternationalRecordCreateRequest.model_fields["record_kind"]
    kinds = get_args(kind_field.annotation)
    assert kinds
    assert set(kinds) < set(TRADEMARK_RECORD_TYPES)
    for kind in ("trademark", *kinds):
        docket = IpDocketRecord(record_type=kind)
        assert_trademark_docket(docket)
        assert general_ip_disclosure_allowed(docket)


@pytest.mark.parametrize("domain", ["patent", "design", "future_domain"])
def test_new_domain_does_not_break_trademark_list_or_accept_particulars(
    client: TestClient, domain: str
) -> None:
    bootstrap, headers, docket_id = _restricted_domain(client, domain)
    trademark = _docket(client, headers, "Existing trademark survives")
    listed = client.get("/api/ip/dockets", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["dockets"]] == [trademark["id"]]
    read = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert read.status_code == 409, read.text
    changed = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=headers,
        json={**_particulars("Wrong domain"), "expected_current_version": 1, "finalize": True},
    )
    assert changed.status_code == 409, changed.text
    assert "ip_domain_workflow_mismatch" in changed.text
    asset = client.post(
        f"/api/ip/dockets/{docket_id}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "title": "Wrong domain", "jurisdiction": "IN"},
    )
    assert asset.status_code == 409, asset.text
    with get_session_factory()() as session:
        row = session.get(IpDocketRecord, docket_id)
        assert row.current_version == 1 and row.status == "draft"
        for model in (IpTrademarkParticularVersion, IpAsset, TrademarkApplication):
            assert session.scalar(
                select(func.count()).select_from(model).where(model.docket_id == docket_id)
            ) == 0


@pytest.mark.parametrize("operation", ["preview", "append", "workspace"])
def test_trademark_prosecution_cannot_write_or_interpret_patent_events(
    client: TestClient, operation: str
) -> None:
    bootstrap, _headers, docket_id = _restricted_domain(client)
    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        call = {
            "preview": preview_ip_docket_event,
            "append": append_ip_docket_event,
            "workspace": get_ip_prosecution_workspace,
        }[operation]
        arguments = {"context": context, "docket_id": docket_id}
        if operation != "workspace":
            arguments["payload"] = _manual_event(membership_id=context.membership.id)
        with pytest.raises(HTTPException) as failure:
            call(session, **arguments)
        assert failure.value.status_code == 409
        session.commit()
    with get_session_factory()() as session:
        assert session.scalar(
            select(func.count())
            .select_from(IpDocketEvent)
            .where(IpDocketEvent.docket_id == docket_id)
        ) == 0


def test_patent_discovery_and_explicit_assistant_scope_fail_closed(client: TestClient) -> None:
    bootstrap, headers, docket_id = _restricted_domain(client)
    token = str(bootstrap["access_token"])
    _enable(client, token)
    trademark = _docket(client, headers, "Confidential substrate trademark")
    response = client.get(
        "/api/workspace-assistant/scope-options", headers=headers, params={"q": "substrate"}
    )
    assert response.status_code == 200, response.text
    assert trademark["id"] in response.text
    assert docket_id not in response.text and "Unpublished invention" not in response.text
    attempted = _create(
        client, token, scopes=[{"scope_type": "ip_docket", "scope_id": docket_id}]
    )
    assert attempted.status_code == 404, attempted.text


def test_patent_document_is_readable_but_never_generally_disclosable(client: TestClient) -> None:
    bootstrap, headers, docket_id = _restricted_domain(client)
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    content = b"Unpublished invention confidential substrate specification and claims. " * 20
    document = _upload(
        client, headers, filename="invention.txt", content=content, docket_id=docket_id
    )["document"]
    read = client.get(f"/api/ip/documents/{document['id']}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["versions"][0]["processing_status"] == "indexed"
    assert read.json()["versions"][0]["ai_eligible"] is False
    policy = client.get(f"/api/ip/documents/{document['id']}/policy", headers=headers)
    assert policy.status_code == 200, policy.text
    for key in (
        "ai_retrieval_allowed", "portal_share_allowed", "export_allowed",
        "notification_content_allowed",
    ):
        assert policy.json()[key] is False
    download = client.get(
        f"/api/ip/documents/{document['id']}/versions/1/download", headers=headers
    )
    assert download.status_code == 200 and download.content == content
    # An additional ordinary link may not launder the invention into discovery.
    sibling = _docket(client, headers, "Ordinary shared mark")
    with get_session_factory()() as session:
        session.add(IpDocumentLink(
            company_id=str(bootstrap["company"]["id"]), document_id=document["id"],
            target_type="docket", target_id=sibling["id"], docket_id=sibling["id"],
            created_by_membership_id=str(bootstrap["membership"]["id"]),
        ))
        session.commit()
        inputs = _private_projection_inputs(
            session, company_id=str(bootstrap["company"]["id"]), limit=100
        )
        assert any(row.source_id == sibling["id"] for row in inputs)
        assert not any(row.source_id in {docket_id, document["id"]} for row in inputs)


def test_old_patent_projection_is_denied_even_with_a_current_creator_grant(
    client: TestClient,
) -> None:
    bootstrap, _headers, docket_id = _restricted_domain(client)
    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        docket = session.get(IpDocketRecord, docket_id)
        generation = ensure_active_private_generation(session, company_id=context.company.id)
        projection = upsert_private_projection(
            session, company_id=context.company.id, generation_id=generation.id,
            expected_access_policy_generation=generation.access_policy_generation,
            expected_tombstone_generation=generation.tombstone_generation,
            payload=PrivateProjectionInput(
                source_type="ip_docket", source_id=docket.id,
                source_version=private_source_version(docket), chunk_ordinal=0,
                label=docket.title, content="Unpublished invention confidential substrate",
                scopes=(ProjectionScopeInput(scope_type="ip_docket", scope_id=docket.id,
                    access_policy_version=docket.access_policy_version),),
                embedding_model="caseops-test", embedding_version="1", embedding=(1.0, 0.0, 0.0),
            ),
        )
        session.commit()
        assert prefilter_private_projection_ids(
            session, context=context, query="confidential substrate"
        ) == ()
        assert hydrate_private_projection_results(
            session, context=context, projection_ids=[projection.id], query="confidential substrate"
        ) == ()
