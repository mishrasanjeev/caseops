"""IPLF-038B internal reporting workflow over canonical readers."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.db.models import IpRenewalTerm
from caseops_api.db.session import get_engine, get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_portfolio_listing import _application
from tests.test_ip_portfolio_workflow import _rich_portfolio_fixture
from tests.test_ip_renewals import _confirm_sources, _seed_renewal_fixture
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


def test_iplf_req_report_01_portfolio_deadline_and_quality_reports_are_bounded_and_complete(
    client: TestClient,
) -> None:
    headers, docket, _application_row = _rich_portfolio_fixture(client)
    first_portfolio = _preview(client, headers, "portfolio_register", row_limit=1)
    asset_id = first_portfolio.json()["rows"][0]["asset_id"]
    _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset_id,
        office="UKIPO",
        jurisdiction="GB",
        filing_phase="draft",
    )

    portfolio = _preview(client, headers, "portfolio_register", row_limit=1)
    assert portfolio.status_code == 200, portfolio.text
    portfolio_body = portfolio.json()
    assert portfolio_body["row_count"] == 1
    assert portfolio_body["truncated"] is True
    assert portfolio_body["summary"]["total"] == 2
    assert portfolio_body["summary"]["returned"] == 1
    assert portfolio_body["summary"]["counts_are_complete"] is True
    assert portfolio_body["summary"]["synchronized_records"] == 0
    assert portfolio_body["freshness"]["source_cutoffs"]["portfolio_records"]
    assert portfolio_body["freshness"]["unavailable_sources"] == ["registry_sync"]

    deadline = _preview(client, headers, "deadline_control", row_limit=1)
    assert deadline.status_code == 200, deadline.text
    deadline_body = deadline.json()
    assert deadline_body["row_count"] == 1
    assert deadline_body["rows"][0]["docket_id"] == docket["id"]
    assert deadline_body["rows"][0]["uncovered_deadline"] is True
    assert deadline_body["summary"]["counts_are_complete"] is True
    assert deadline_body["freshness"]["source_cutoffs"]["docket_control"]

    repeated = _preview(client, headers, "deadline_control", row_limit=1)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["snapshot_sha256"] == deadline_body["snapshot_sha256"]

    quality = _preview(client, headers, "data_quality", row_limit=20)
    assert quality.status_code == 200, quality.text
    quality_body = quality.json()
    assert quality_body["summary"]["total"] == 2
    assert quality_body["summary"]["counts_are_complete"] is True
    assert quality_body["summary"]["incomplete_records"] == 1
    assert {row["metric"]: row["value"] for row in quality_body["rows"]}[
        "synchronized_records"
    ] == 0


def test_iplf_req_report_01_renewal_report_returns_canonical_evidence(
    client: TestClient,
) -> None:
    _bootstrap, headers, ids = _seed_renewal_fixture(client)
    _confirm_sources(ids)
    created = client.post(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms",
        headers=headers,
        json={
            "registration_event_id": ids["registration"],
            "renewal_deadline_id": ids["renewal"],
            "grace_deadline_id": ids["grace"],
            "fee_cost_item_id": ids["fee"],
        },
    )
    assert created.status_code == 201, created.text

    with get_session_factory()() as session:
        first_term = session.get(IpRenewalTerm, created.json()["id"])
        assert first_term is not None
        session.add(
            IpRenewalTerm(
                company_id=first_term.company_id,
                docket_id=first_term.docket_id,
                term_sequence=2,
                registration_event_id=ids["acceptance"],
                renewal_deadline_id=ids["next_term"],
                state="due",
                created_by_membership_id=first_term.created_by_membership_id,
                updated_by_membership_id=first_term.updated_by_membership_id,
            )
        )
        session.commit()

    instruction_selects = 0

    def count_instruction_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        nonlocal instruction_selects
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "ip_client_instructions" in statement
        ):
            instruction_selects += 1

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", count_instruction_selects)
    try:
        renewal = _preview(
            client,
            headers,
            "renewal",
            row_limit=2,
            renewal_states=["due"],
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_instruction_selects)

    assert renewal.status_code == 200, renewal.text
    body = renewal.json()
    assert body["row_count"] == 2
    assert body["truncated"] is False
    assert body["summary"]["total"] == 2
    assert body["summary"]["returned"] == 2
    assert body["summary"]["scanned"] == 2
    assert body["summary"]["counts_are_complete"] is True
    assert body["rows"][0]["docket_id"] == ids["docket"]
    assert body["rows"][0]["renewal_deadline"]["source_version"]
    assert any(row["fee"] and row["fee"]["evidence_reference"] for row in body["rows"])
    assert instruction_selects == 1
