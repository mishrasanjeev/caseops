from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from caseops_api.db.models import IpJournalIngestionRun, SourceLinkReport
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket
from tests.test_provider_operations import _bootstrap_named_company


def test_ip_provider_attempts_use_shared_operations_contract_without_secret_leakage(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    headers = auth_headers(token)
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    docket = _docket(client, headers, "PROVIDER OPS ASTER")
    asset = _asset(client, headers, docket["id"], "PROVIDER OPS ASTER")
    application = _application(client, headers, docket["id"], asset["id"])

    link_response = client.post(
        f"/api/ip/dockets/{docket['id']}/registry-links",
        headers=headers,
        json={
            "application_id": application["id"],
            "provider_key": "ipindia-registry",
            "office": "IP India",
            "jurisdiction": "IN",
            "identifier_kind": "application",
            "raw_identifier": "TM-056-2026",
            "source_url": "https://ipindia.gov.in/registry/TM-056-2026",
            "match_confidence": "0.91",
            "capability_version": "provider-operations-v1",
        },
    )
    assert link_response.status_code == 201, link_response.text
    link = link_response.json()
    registry_failure = client.post(
        f"/api/ip/registry-links/{link['id']}/failures",
        headers=headers,
        json={
            "expected_link_version": link["version"],
            "idempotency_key": "provider-ops-registry-failure-1",
            "response_class": "provider_outage",
            "error": (
                "Bearer registry-secret for lawyer@example.test at "
                "https://provider.example.test/private/TM-056-2026"
            ),
            "external_call": False,
        },
    )
    assert registry_failure.status_code == 201, registry_failure.text
    registry_attempt_id = registry_failure.json()["attempt"]["id"]

    now = datetime.now(UTC)
    factory = get_session_factory()
    with factory() as session:
        journal = IpJournalIngestionRun(
            company_id=company_id,
            provider_key="ipindia-journal",
            idempotency_key="provider-ops-journal-failure-1",
            request_sha256="5" * 64,
            status="paused_cost_quota",
            external_call=False,
            cost_minor=275,
            currency="INR",
            publications_seen=4,
            publications_created=0,
            hits_created=0,
            duplicate_hits=0,
            stale_source_alert=True,
            error_redacted="Cost quota exhausted before external provider access.",
            requested_by_membership_id=membership_id,
            started_at=now,
            completed_at=now,
            created_at=now,
        )
        source_report = SourceLinkReport(
            company_id=company_id,
            reported_by_membership_id=membership_id,
            target_type="authority_document",
            target_id="provider-source-secret-056",
            origin_surface="research",
            issue_type="wrong_document",
            description=(
                "Wrong source for lawyer@example.test at "
                "https://provider.example.test/private/source-056"
            ),
            source_reference_sha256="6" * 64,
            destination_class="verified_public_url",
            source_state="quarantined",
            status="queued",
        )
        session.add_all([journal, source_report])
        session.commit()
        journal_id = journal.id
        source_report_id = source_report.id

    response = client.get("/api/admin/provider-operations/jobs", headers=headers)
    assert response.status_code == 200, response.text
    assert "lawyer@example.test" not in response.text
    assert "provider.example.test" not in response.text
    assert "provider-source-secret-056" not in response.text
    operations = {row["job_kind"]: row for row in response.json()["operations"]}
    assert {
        "ip_registry_sync",
        "ip_journal_ingestion",
        "source_link_health",
    }.issubset(operations)
    assert operations["ip_registry_sync"]["response_class"] == "provider_outage"
    assert operations["ip_registry_sync"]["replay_available"] is False
    assert operations["ip_journal_ingestion"]["estimated_cost_minor"] == 275
    assert operations["ip_journal_ingestion"]["response_class"] == "rate_limit"
    assert operations["source_link_health"]["response_class"] == "changed_content"
    assert operations["source_link_health"]["mark_resolved_available"] is True

    exact = client.get(
        f"/api/admin/provider-operations/jobs/ip_registry_sync:{registry_attempt_id}",
        headers=headers,
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["source_ref"].startswith("id:")

    other = _bootstrap_named_company(
        client,
        slug="provider-ip-ops-other",
        email="owner@provider-ip-ops-other.example",
    )
    client.cookies.clear()
    cross_tenant = client.get(
        f"/api/admin/provider-operations/jobs/ip_registry_sync:{registry_attempt_id}",
        headers=auth_headers(str(other["access_token"])),
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    monkeypatch.setattr(
        "caseops_api.services.provider_operations.require_recent_step_up",
        lambda *args, **kwargs: None,
    )
    resolved = client.post(
        f"/api/admin/provider-operations/jobs/source_link_health:{source_report_id}/mark-resolved",
        headers=headers,
        json={"reason": "Verified the corrected canonical source and its current hash."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["operation"]["status"] == "resolved"
    assert resolved.json()["operation"]["operator_state"] == "resolved"

    replay_preview = client.post(
        "/api/admin/provider-operations/jobs/replay-preview",
        headers=headers,
        json={"operation_ids": [f"ip_journal_ingestion:{journal_id}"]},
    )
    assert replay_preview.status_code == 409, replay_preview.text
