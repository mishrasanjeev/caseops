"""IPLF-038B internal reporting workflow over canonical readers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_ip_report_foundation import _preview


def test_iplf_req_report_01_status_reports_preserve_registry_identifiers(
    client: TestClient,
) -> None:
    headers, _docket, application = _rich_portfolio_fixture(client)

    application_status = _preview(client, headers, "application_status")
    assert application_status.status_code == 200, application_status.text
    application_body = application_status.json()
    assert application_body["summary"] == {
        "total": 1,
        "returned": 1,
        "returned_by_filing_phase": {"filed": 1},
        "returned_application_numbered": 1,
    }
    assert application_body["rows"][0]["application_id"] == application["id"]
    assert application_body["rows"][0]["application_numbers"] == ["TM / 2026 / 00421"]

    opposition_status = _preview(client, headers, "opposition_status")
    assert opposition_status.status_code == 200, opposition_status.text
    opposition_body = opposition_status.json()
    assert opposition_body["summary"] == {
        "total": 1,
        "returned": 1,
        "returned_by_filing_phase": {"filed": 1},
        "returned_opposition_numbered": 1,
    }
    assert opposition_body["filters"]["portfolio"]["opposition_only"] is True
    assert opposition_body["rows"][0]["opposition_numbers"] == ["OPP / 88 / 2026"]


def test_iplf_req_report_01_operational_reports_are_honest(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    workload = _preview(client, headers, "workload")
    assert workload.status_code == 200, workload.text
    workload_body = workload.json()
    assert workload_body["summary"] == {
        "queue_count": 0,
        "escalation_count": 0,
        "counts_are_complete": True,
    }
    assert workload_body["freshness"]["status"] == "current"

    watch = _preview(client, headers, "watch")
    assert watch.status_code == 200, watch.text
    watch_body = watch.json()
    assert watch_body["summary"]["available"] is False
    assert watch_body["rows"] == []
    assert watch_body["freshness"]["status"] == "unavailable"
    assert watch_body["freshness"]["unavailable_sources"] == ["ip_watch_provider"]

    integration = _preview(client, headers, "integration_freshness", row_limit=2)
    assert integration.status_code == 200, integration.text
    integration_body = integration.json()
    assert integration_body["summary"]["total"] == 0
    assert integration_body["row_count"] == 0
    assert integration_body["freshness"]["status"] == "unavailable"
    assert integration_body["freshness"]["unavailable_sources"] == ["connector_health"]
    assert "connector_health" in integration_body["freshness"]["source_cutoffs"]


def test_iplf_req_report_02_rejects_filters_that_cannot_be_applied(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    for report_kind in ("watch", "workload", "integration_freshness"):
        response = _preview(
            client,
            headers,
            report_kind,
            filters={"jurisdiction": ["IN"]},
        )
        assert response.status_code == 422, (report_kind, response.text)

    renewal_filter = _preview(
        client,
        headers,
        "application_status",
        renewal_states=["due"],
    )
    assert renewal_filter.status_code == 422
