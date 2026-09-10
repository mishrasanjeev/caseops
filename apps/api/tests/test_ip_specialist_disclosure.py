import pytest

from caseops_api.db.models import IpDocketRecord, IpDocumentLink
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_domain_policy import disclosable_ip_document_ids
from caseops_api.services.private_retrieval_jobs import _private_projection_inputs
from tests import test_ip_specialist as intake
from tests.test_ip_record_workflow import _docket

registered_intake = intake.registered_intake


@pytest.mark.parametrize("domain", intake.FACT_MODELS)
def test_specialist_document_cannot_gain_disclosure_through_trademark_link(
    client, registered_intake, domain
):
    headers, facts = intake.setup(client, domain)
    created = intake.create(client, headers, facts)
    assert created.status_code == 201, created.text
    record = created.json()
    document, _, content = intake.observation(client, headers, record)
    ordinary = _docket(client, headers, "Ordinary trademark survives disclosure filtering")
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, record["docket_id"])
        session.add(
            IpDocumentLink(
                company_id=docket.company_id,
                document_id=document["id"],
                target_type="docket",
                target_id=ordinary["id"],
                docket_id=ordinary["id"],
                created_by_membership_id=docket.created_by_membership_id,
            )
        )
        session.commit()
        assert (
            disclosable_ip_document_ids(
                session, company_id=docket.company_id, document_ids={document["id"]}
            )
            == set()
        )
        inputs = _private_projection_inputs(session, company_id=docket.company_id, limit=100)
        assert any(row.source_id == ordinary["id"] for row in inputs)
        assert not any(row.source_id in {docket.id, document["id"]} for row in inputs)
    policy = client.get(f"/api/ip/documents/{document['id']}/policy", headers=headers)
    assert policy.status_code == 200, policy.text
    for field in (
        "ai_retrieval_allowed",
        "portal_share_allowed",
        "export_allowed",
        "notification_content_allowed",
    ):
        assert policy.json()[field] is False, (domain, field, policy.text)
    read = client.get(f"/api/ip/documents/{document['id']}/versions/1/download", headers=headers)
    assert read.status_code == 200 and read.content == content
    listed = client.get("/api/ip/dockets", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["dockets"]] == [ordinary["id"]]
