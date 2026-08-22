"""IPLF-038A synchronous report-definition foundation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_portfolio_listing import _application, _asset, _docket


def _preview(
    client: TestClient,
    headers: dict[str, str],
    report_kind: str,
    **overrides: object,
):
    payload: dict[str, object] = {
        "report_kind": report_kind,
        "row_limit": 50,
        "audience": "internal",
        "confidentiality": "internal",
    }
    payload.update(overrides)
    return client.post("/api/ip/reports/preview", headers=headers, json=payload)


def test_iplf038a_contract_refuses_a_duplicate_report_control_plane(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    response = client.get("/api/ip/reports/foundation-contract", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    definitions = body.pop("definitions")
    assert body == {
        "contract_version": "iplf-038b-v1",
        "persistence": "none",
        "execution_mode": "synchronous",
        "artifact_storage": "none",
        "delivery": "not_available",
        "audience": "internal",
        "hidden_restricted_count_policy": "omit_without_count",
    }
    assert [definition["key"] for definition in definitions] == [
        "portfolio_register",
        "application_status",
        "opposition_status",
        "deadline_control",
        "renewal",
        "watch",
        "workload",
        "data_quality",
        "integration_freshness",
    ]
    assert all(definition["synchronous_preview"] is True for definition in definitions)
    assert all(definition["background_execution"] is False for definition in definitions)
    assert all(definition["scheduled_delivery"] is False for definition in definitions)


def test_iplf038a_portfolio_and_quality_previews_delegate_to_canonical_readers(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-REPORT-038A")
    docket = _docket(client, headers, matter_id=matter["id"], title="Report Mark")
    asset = _asset(client, headers, docket_id=docket["id"], title="Reportable Mark")
    application = _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset["id"],
    )

    portfolio = _preview(
        client,
        headers,
        "portfolio_register",
        filters={"query": "Reportable"},
        confidentiality="restricted",
    )
    assert portfolio.status_code == 200, portfolio.text
    body = portfolio.json()
    assert body["schema_version"] == "ip-portfolio-register-v1"
    assert body["audience"] == "internal"
    assert body["confidentiality"] == "restricted"
    assert body["timezone"] == "UTC"
    assert body["hidden_restricted_count_policy"] == "omit_without_count"
    assert body["row_count"] == 1
    assert body["truncated"] is False
    assert body["rows"][0]["application_id"] == application["id"]
    assert body["summary"]["total"] == 1
    assert body["freshness"]["status"] == "mixed"
    assert body["freshness"]["unavailable_sources"] == ["registry_sync"]
    assert len(body["snapshot_sha256"]) == 64

    quality = _preview(client, headers, "data_quality")
    assert quality.status_code == 200, quality.text
    quality_body = quality.json()
    assert quality_body["summary"]["total"] == 1
    assert quality_body["summary"]["sync_failure_records"] is None
    sync_metric = next(
        row for row in quality_body["rows"] if row["metric"] == "sync_failure_records"
    )
    assert sync_metric == {
        "metric": "sync_failure_records",
        "value": None,
        "available": False,
    }

    with get_session_factory()() as session:
        events = list(
            session.query(AuditEvent).filter(AuditEvent.action == "ip.report.previewed").all()
        )
    assert len(events) == 2
    assert {event.target_id for event in events} == {
        "portfolio_register",
        "data_quality",
    }


def test_iplf038a_deadline_and_renewal_empty_states_are_honest(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    deadline = _preview(client, headers, "deadline_control")
    assert deadline.status_code == 200, deadline.text
    deadline_body = deadline.json()
    assert deadline_body["row_count"] == 0
    assert deadline_body["summary"]["docket_count"] == 0
    assert deadline_body["freshness"]["status"] == "mixed"
    assert deadline_body["freshness"]["unavailable_sources"] == ["provider_freshness"]

    renewal = _preview(client, headers, "renewal", renewal_states=["due"])
    assert renewal.status_code == 200, renewal.text
    renewal_body = renewal.json()
    assert renewal_body["row_count"] == 0
    assert renewal_body["summary"]["total"] == 0
    assert renewal_body["filters"]["renewal_states"] == ["due"]
    assert "portfolio" not in renewal_body["filters"]
    assert renewal_body["freshness"]["status"] == "mixed"
    assert renewal_body["freshness"]["unavailable_sources"] == ["registry_freshness"]


def test_iplf038a_report_contract_fails_closed_on_unapproved_shape(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    portal = _preview(client, headers, "portfolio_register", audience="client")
    assert portal.status_code == 422

    unknown = _preview(client, headers, "portfolio_register", schedule="daily")
    assert unknown.status_code == 422

    misspelled_filter = _preview(
        client,
        headers,
        "portfolio_register",
        filters={"jurisdiciton": ["IN"]},
    )
    assert misspelled_filter.status_code == 422

    invalid_state = _preview(client, headers, "renewal", renewal_states=["invented"])
    assert invalid_state.status_code == 422

    ignored_portfolio_filter = _preview(
        client,
        headers,
        "renewal",
        filters={"jurisdiction": ["IN"]},
    )
    assert ignored_portfolio_filter.status_code == 422

    ignored_renewal_filter = _preview(
        client,
        headers,
        "deadline_control",
        renewal_states=["due"],
    )
    assert ignored_renewal_filter.status_code == 422

    client.cookies.clear()
    unauthenticated = client.get("/api/ip/reports/foundation-contract")
    assert unauthenticated.status_code == 401


def test_iplf038a_preview_omits_restricted_records_without_count_or_probe_leaks(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    created = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Report Associate",
            "email": "report-associate@asterlegal.in",
            "password": "ReportAssociate123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "report-associate@asterlegal.in",
            "password": "ReportAssociate123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    associate_headers = auth_headers(str(login.json()["access_token"]))

    matter = _mk_matter(client, owner_token, "IP-REPORT-038A-ACL")
    open_docket = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Open Report Mark",
    )
    restricted_docket = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Restricted Report Mark",
        restricted=True,
    )
    open_asset = _asset(client, owner_headers, docket_id=open_docket["id"])
    restricted_asset = _asset(
        client,
        owner_headers,
        docket_id=restricted_docket["id"],
        title="Confidential Report Mark",
    )
    _application(
        client,
        owner_headers,
        docket_id=open_docket["id"],
        asset_id=open_asset["id"],
    )
    restricted_application = _application(
        client,
        owner_headers,
        docket_id=restricted_docket["id"],
        asset_id=restricted_asset["id"],
    )

    owner_report = _preview(client, owner_headers, "portfolio_register").json()
    assert owner_report["summary"]["total"] == 2

    associate_report = _preview(client, associate_headers, "portfolio_register").json()
    assert associate_report["summary"]["total"] == 1
    assert associate_report["row_count"] == 1
    serialized = str(associate_report)
    assert restricted_docket["id"] not in serialized
    assert restricted_application["id"] not in serialized
    assert "Confidential Report Mark" not in serialized
    assert "Restricted Report Mark" not in serialized

    probe = _preview(
        client,
        associate_headers,
        "portfolio_register",
        filters={"query": "Confidential"},
    ).json()
    assert probe["summary"]["total"] == 0
    assert probe["row_count"] == 0
    assert probe["rows"] == []
