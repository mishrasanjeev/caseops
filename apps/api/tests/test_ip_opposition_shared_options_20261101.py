"""B4-ADJ-02 / B4-ADJ-22: opposition choices come from the validators' predicates.

The shared and specialized opposition forms asked for a "Target record ID"
and a "Related application ID", and offered every stage event as a
disposition trigger although the validator accepts only outcome events. The
shared-workflow read now carries the exact choices each write accepts:

- ``appeal_proceedings``: appeal proceedings on this IP record with their
  current appeal numbers (the appeal-link validator);
- ``related_applications``: the other applications on this IP record (the
  scope-review validator, which previously accepted any application in the
  company, including one on a docket the actor may not see);
- ``disposition_trigger_events``: this opposition's order or outcome events
  (the disposition-review validator).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, TrademarkApplication
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_nice_classes_20261031 import _member_without_ip_read
from tests.test_ip_opposition_applicant_workflow import _fixture, _stage
from tests.test_ip_opposition_foundation import _complete_workspace
from tests.test_ip_opposition_shared_workflow import _post_action, _route, _skip_to
from tests.test_ip_record_workflow import _application, _asset, _particulars


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _workflow(client: TestClient, headers: dict[str, str], docket: dict, proceeding: dict):
    return client.get(_route(docket, proceeding, "opposition-shared-workflow"), headers=headers)


def _restricted_docket_with_application(
    client: TestClient, headers: dict[str, str]
) -> tuple[dict, dict]:
    docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Walled ASTER division",
            "restricted": True,
            "particulars": _particulars("WALLED ASTER"),
        },
    )
    assert docket.status_code == 201, docket.text
    asset = _asset(client, headers, docket.json()["id"], "WALLED ASTER")
    return docket.json(), _application(client, headers, docket.json()["id"], asset["id"])


def _colleague(client: TestClient, owner: dict[str, str]) -> dict[str, str]:
    created = client.post(
        "/api/companies/current/users",
        headers=owner,
        json={
            "full_name": "Walled Colleague",
            "email": "walled-options@asterlegal.in",
            "role": "admin",
            "password": "WalledPass123!",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "walled-options@asterlegal.in",
            "password": "WalledPass123!",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return auth_headers(str(login.json()["access_token"]))


def _scope_review(scope_id: str, related_application_id: str) -> dict[str, object]:
    return {
        "revision": 1,
        "source_scope_certainty": "certain",
        "related_application_id": related_application_id,
        "amendment_or_division_reference": "registry-division:2026-11-01",
        "decisions": [
            {
                "application_scope_id": scope_id,
                "challenged_segment": "Downloadable software",
                "status": "challenged",
            }
        ],
        "preserve_unlisted_scopes": True,
    }


def test_related_application_choices_are_this_records_other_applications(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(client, bootstrap=bootstrap, docket=docket, proceeding=proceeding)
    with get_session_factory()() as session:
        opposed = session.get(TrademarkApplication, proceeding["application_id"])
        assert opposed is not None
        canonical_asset_id = opposed.asset_id

    before = _workflow(client, owner, docket, proceeding)
    assert before.status_code == 200, before.text
    # The opposed application itself is never a related application.
    assert before.json()["related_applications"] == []
    assert before.json()["appeal_proceedings"] == []

    division = _application(client, owner, docket["id"], canonical_asset_id)
    number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=owner,
        json={
            "identifier_kind": "application",
            "raw_value": "TM-DIV-2026-11-01",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry_division_fixture",
            "effective_from": "2026-10-01",
            "is_primary": True,
            "application_id": division["id"],
        },
    )
    assert number.status_code == 201, number.text
    _, walled_application = _restricted_docket_with_application(client, owner)

    workflow = _workflow(client, owner, docket, proceeding).json()
    assert workflow["related_applications"] == [
        {
            "id": division["id"],
            "application_number": "TM-DIV-2026-11-01",
            "office": "IP India",
            "filing_phase": "draft",
        }
    ]
    scope_id = workflow["application_scopes"][0]["id"]

    # An application on another docket (here a walled one) is neither offered
    # nor accepted: before this change the validator accepted any company
    # application by id.
    refused = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="scope_review_recorded",
        expected_status=409,
        scope_review=_scope_review(scope_id, walled_application["id"]),
    )
    assert "Related amendment or division application not found" in str(refused)

    accepted = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="scope_review_recorded",
        scope_review=_scope_review(scope_id, division["id"]),
    )
    review = accepted["shared_actions"][-1]["payload_json"]["scope_review"]
    assert review["related_application_id"] == division["id"]


def test_scope_review_refuses_an_application_on_another_docket(client: TestClient) -> None:
    """Before this change any application in the company was accepted by id."""
    bootstrap, _, docket, proceeding = _fixture(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(client, bootstrap=bootstrap, docket=docket, proceeding=proceeding)
    _, walled_application = _restricted_docket_with_application(client, owner)
    scope_id = _workflow(client, owner, docket, proceeding).json()["application_scopes"][0]["id"]
    refused = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="scope_review_recorded",
        expected_status=409,
        scope_review=_scope_review(scope_id, walled_application["id"]),
    )
    assert "Related amendment or division application not found" in str(refused)


def test_disposition_and_appeal_choices_follow_their_validators(client: TestClient) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(client, bootstrap=bootstrap, docket=docket, proceeding=proceeding)
    proceeding = _skip_to(
        client, bootstrap=bootstrap, docket=docket, proceeding=proceeding,
        to_stage="hearing_pending",
    )
    workflow = _workflow(client, owner, docket, proceeding).json()
    # A non-outcome stage event is not a disposition trigger.
    assert workflow["disposition_trigger_events"] == []

    outcome = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="withdrawn",
        transition_kind="skipped",
        authority_reference="registry-withdrawal-order:adj-22",
        authorized_confirmation="Withdrawal reviewed by responsible IP counsel.",
        effective_at="2026-10-21T12:30:00+05:30",
    )
    workflow = _workflow(client, owner, docket, outcome["proceeding"]).json()
    assert [row["id"] for row in workflow["disposition_trigger_events"]] == [outcome["event"]["id"]]

    appeal = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=owner,
        json={
            "application_id": proceeding["application_id"],
            "proceeding_kind": "appeal",
            "side": "respondent",
            "office": "High Court of Delhi",
            "jurisdiction": "IN",
            "stage": "filed",
            "origin_kind": "registry_event",
        },
    )
    assert appeal.status_code == 201, appeal.text
    workflow = _workflow(client, owner, docket, outcome["proceeding"]).json()
    # An appeal proceeding without an appeal number cannot be linked yet: it
    # is listed with no numbers so the form can say so.
    assert workflow["appeal_proceedings"] == [
        {"id": appeal.json()["id"], "office": "High Court of Delhi", "stage": "filed",
         "appeal_identifiers": []}
    ]
    numbered = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=owner,
        json={
            "identifier_kind": "appeal",
            "raw_value": "C.A.(COMM.IPD-TM) 1101/2026",
            "office": "High Court of Delhi",
            "jurisdiction": "IN",
            "source": "court-filing:adj-02",
            "effective_from": "2026-11-01",
            "is_primary": True,
            "proceeding_id": appeal.json()["id"],
        },
    )
    assert numbered.status_code == 201, numbered.text
    workflow = _workflow(client, owner, docket, outcome["proceeding"]).json()
    assert workflow["appeal_proceedings"][0]["appeal_identifiers"] == [
        "C.A.(COMM.IPD-TM) 1101/2026"
    ]

    # Reading choices is not an auditable mutation.
    with get_session_factory()() as session:
        actions = set(session.scalars(select(AuditEvent.action)))
    assert not any("option" in action for action in actions)


def test_choices_are_not_readable_across_tenant_wall_or_role(client: TestClient) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    owner = auth_headers(str(bootstrap["access_token"]))
    walled_docket, walled_application = _restricted_docket_with_application(client, owner)
    walled_proceeding = client.post(
        f"/api/ip/dockets/{walled_docket['id']}/proceedings",
        headers=owner,
        json={
            "application_id": walled_application["id"],
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": "registry_event",
            "source_pending_identifier_allocation": True,
        },
    )
    assert walled_proceeding.status_code == 201, walled_proceeding.text
    assert _workflow(client, owner, walled_docket, walled_proceeding.json()).status_code == 200

    colleague = _colleague(client, owner)
    hidden = _workflow(client, colleague, walled_docket, walled_proceeding.json())
    assert hidden.status_code == 404, hidden.text
    assert walled_application["id"] not in hidden.text
    # The open record still works for the colleague and never lists the walled application.
    visible = _workflow(client, colleague, docket, proceeding)
    assert visible.status_code == 200, visible.text
    assert walled_application["id"] not in visible.text

    clerk = _member_without_ip_read(client, owner)
    assert _workflow(client, clerk, docket, proceeding).status_code in {403, 404}

    outsider = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Options Outsider LLP",
            "company_slug": "options-outsider",
            "company_type": "law_firm",
            "owner_full_name": "Outside Counsel",
            "owner_email": "options-outsider@example.com",
            "owner_password": "OutsiderPass123!",
        },
    )
    assert outsider.status_code == 200, outsider.text
    client.cookies.clear()
    outsider_headers = auth_headers(str(outsider.json()["access_token"]))
    foreign = _workflow(client, outsider_headers, docket, proceeding)
    assert foreign.status_code == 404
    client.cookies.clear()
    assert client.get(_route(docket, proceeding, "opposition-shared-workflow")).status_code == 401
