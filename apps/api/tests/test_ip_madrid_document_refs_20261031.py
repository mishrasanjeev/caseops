"""BUG-008 sibling: Madrid's Linked document picker and its validator share one rule.

The Madrid action validator used to hand-copy the docket/event/deadline document
predicate and skipped the viewer's document access, so a colleague could cite a
deed co-linked to a docket they cannot see. Both now use
``docket_scoped_document_links`` plus the batched document-access decision.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_taxonomy_provisioning_20261031 import enable_ip_workspace
from tests.test_ip_international import _action_payload, _registration_payload
from tests.test_ip_record_workflow import _application, _asset, _docket
from tests.test_ip_recordal_instruments_20261031 import _colleague, _restricted_docket, _upload


def test_madrid_document_refs_follow_the_picker_and_viewer_access(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    enable_ip_workspace(client, owner, str(bootstrap["membership"]["id"]))
    basic_docket = _docket(client, owner, "ASTER MADRID BASIC")
    asset = _asset(client, owner, basic_docket["id"], "ASTER")
    application = _application(client, owner, basic_docket["id"], asset["id"])
    registration = client.post(
        "/api/ip/international-registrations",
        headers=owner,
        json=_registration_payload(basic_application_id=application["id"], ir_number="1888131"),
    )
    assert registration.status_code == 201, registration.text
    record = registration.json()
    walled_docket = _restricted_docket(client, owner)
    colleague = _colleague(client, owner, "aster-legal")
    colleague_id = client.get("/api/auth/me", headers=colleague).json()["membership"]["id"]

    shared = _upload(client, owner, title="WIPO certificate",
                     links=[{"target_type": "docket", "target_id": record["docket_id"]}])
    co_linked = _upload(client, owner, title="Certificate also filed on the walled docket",
                        links=[{"target_type": "docket", "target_id": record["docket_id"]},
                               {"target_type": "docket", "target_id": walled_docket}])

    def picker(headers: dict[str, str]) -> set[str]:
        workspace = client.get(
            f"/api/ip/international-registrations/{record['id']}/workspace", headers=headers
        )
        assert workspace.status_code == 200, workspace.text
        return {row["id"] for row in workspace.json()["documents"]}

    def act(headers: dict[str, str], membership_id: str, version: int, document_id: str):
        current = client.get(f"/api/ip/international-registrations/{record['id']}/workspace",
                             headers=headers).json()
        return client.post(
            f"/api/ip/international-registrations/{record['id']}/actions",
            headers=headers,
            json=_action_payload(
                membership_id=membership_id,
                expected_version=version,
                action_kind="source_snapshot",
                authority="wipo",
                source_url="https://www.wipo.int/madrid/monitor/en/showData.jsp?ID=1888131",
                source_reference=f"WIPO-IR-1888131:{document_id[:8]}",
                document_refs=[document_id],
                expected_lifecycle_version=current["docket"]["lifecycle_version"],
                wipo_status="recorded",
            ),
        )

    assert picker(colleague) == {shared}
    refused = act(colleague, colleague_id, record["version"], co_linked)
    assert refused.status_code == 422, refused.text
    assert "linked to this designation docket" in refused.text
    accepted = act(colleague, colleague_id, record["version"], shared)
    assert accepted.status_code in {200, 201}, accepted.text

    assert picker(owner) == {shared, co_linked}
    owner_version = client.get(
        f"/api/ip/international-registrations/{record['id']}", headers=owner
    ).json()["version"]
    owner_cited = act(owner, str(bootstrap["membership"]["id"]), owner_version, co_linked)
    assert owner_cited.status_code in {200, 201}, owner_cited.text
