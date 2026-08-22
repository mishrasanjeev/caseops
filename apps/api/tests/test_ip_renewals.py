from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _deadline(
    *,
    company_id: str,
    docket_id: str,
    event_id: str,
    rule_version_id: str,
    calendar_version_id: str,
    membership_id: str,
    kind: str,
    title: str,
    result_on: date,
    state: str = "confirmed",
) -> IpDeadline:
    now = datetime.now(UTC)
    return IpDeadline(
        company_id=company_id,
        docket_id=docket_id,
        trigger_event_id=event_id,
        rule_version_id=rule_version_id,
        calendar_version_id=calendar_version_id,
        deadline_kind=kind,
        title=title,
        trigger_kind="registration",
        base_date=date(2026, 8, 1),
        duration_value=10,
        duration_unit="years",
        calendar_method="calendar_years",
        timezone="Asia/Kolkata",
        date_precision="date",
        certainty="verified",
        result_on=result_on,
        calculation_inputs_json={"registration_date": "2026-08-01"},
        calculation_trace_json=[{"operation": "add_years", "value": 10}],
        explanation="Verified renewal fixture",
        rule_citation="Trade Marks Act and applicable rules",
        engine_version="test-v1",
        source_version="registry-fixture-v1",
        state=state,
        version=1,
        confirmed_by_membership_id=membership_id if state == "confirmed" else None,
        confirmer_label_snapshot="Owner" if state == "confirmed" else None,
        confirmed_at=now if state == "confirmed" else None,
        created_by_membership_id=membership_id,
        creator_label_snapshot="Owner",
    )


def _seed_renewal_fixture(client: TestClient) -> tuple[dict, dict[str, str], dict[str, str]]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="ASTER renewal",
            primary_identifier="TM-RENEWAL-1",
            status="draft",
            created_by_membership_id=membership_id,
        )
        session.add(docket)
        session.flush()
        registration = IpDocketEvent(
            company_id=company_id,
            docket_id=docket.id,
            sequence=1,
            event_kind="registration",
            source="registry",
            source_reference="registry://registration/1",
            effective_at=now - timedelta(days=30),
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=["registry://registration/1"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="candidate",
            payload_json={"registration_number": "123456"},
        )
        filing = IpDocketEvent(
            company_id=company_id,
            docket_id=docket.id,
            sequence=2,
            event_kind="renewal_filing",
            source="registry",
            source_reference="registry://filing/1",
            effective_at=now,
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=["registry://filing/1"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={"acknowledgement": "ACK-1"},
        )
        acceptance = IpDocketEvent(
            company_id=company_id,
            docket_id=docket.id,
            sequence=3,
            event_kind="renewal_acceptance",
            source="registry",
            source_reference="registry://acceptance/1",
            effective_at=now,
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=["registry://acceptance/1"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={"acceptance_number": "ACC-1"},
        )
        session.add_all([registration, filing, acceptance])
        calendar = LegalWorkingCalendar(
            company_id=company_id,
            key="in-trademark-renewal",
            name="India trademark renewal calendar",
            jurisdiction="IN",
            office="Trade Marks Registry",
            created_by_membership_id=membership_id,
        )
        rule_set = IpRuleSet(
            key=f"renewal-{company_id}",
            rule_kind="deadline",
            jurisdiction="IN",
            office="Trade Marks Registry",
            right_kind="trademark",
            stage="registered",
        )
        session.add_all([calendar, rule_set])
        session.flush()
        calendar_version = LegalWorkingCalendarVersion(
            company_id=company_id,
            calendar_id=calendar.id,
            version=1,
            status="active",
            timezone="Asia/Kolkata",
            weekend_days_json=[5, 6],
            holidays_json=[],
            exceptional_working_days_json=[],
            source_priority_json=["registry"],
            source_reference="registry://calendar/v1",
            source_hash="a" * 64,
            effective_from=date(2026, 1, 1),
            approved_by_membership_id=membership_id,
            approver_label_snapshot="Owner",
            approved_at=now,
            proposer_label_snapshot="System fixture",
        )
        rule_version = IpRuleVersion(
            rule_set_id=rule_set.id,
            version=1,
            status="active",
            source_record_id="renewal-rule-v1",
            source_hash="b" * 64,
            source_reference="registry://rules/renewal/v1",
            effective_from=date(2026, 1, 1),
            engine_compatibility="test-v1",
            fixture_set_json=[],
            definition_json={"duration": 10, "unit": "years"},
            proposer_label_snapshot="System fixture",
            legal_approved_by_membership_id=membership_id,
            legal_approver_label_snapshot="Owner",
            fixtures_passed_at=now,
            activated_at=now,
        )
        session.add_all([calendar_version, rule_version])
        session.flush()
        renewal = _deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=registration.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal",
            title="Renewal due",
            result_on=date(2036, 8, 1),
            state="candidate",
        )
        grace = _deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=registration.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal_grace",
            title="Renewal grace period ends",
            result_on=date(2037, 2, 1),
        )
        next_term = _deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=acceptance.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal",
            title="Next renewal due",
            result_on=date(2046, 8, 1),
        )
        fee = IpCostItem(
            company_id=company_id,
            docket_id=docket.id,
            matter_id=None,
            category="official_fee",
            description="Renewal official fee quote",
            amount_minor=900000,
            currency="INR",
            billable=False,
            cost_nature="estimate",
            evidence_reference="registry://fees/renewal-v1",
            created_by_membership_id=membership_id,
        )
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="renewal_certificate",
            label="Renewal certificate",
            updated_by_membership_id=membership_id,
        )
        session.add_all([renewal, grace, next_term, fee, taxonomy])
        session.flush()
        certificate = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Accepted renewal certificate",
            current_version=1,
            created_by_membership_id=membership_id,
        )
        session.add(certificate)
        session.flush()
        certificate_version = IpDocumentVersion(
            company_id=company_id,
            document_id=certificate.id,
            version=1,
            original_filename="renewal-certificate.pdf",
            display_name="renewal-certificate.pdf",
            storage_key=f"test/{certificate.id}/1.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256_hex="c" * 64,
            processing_status="indexed",
            extracted_char_count=10,
            state="accepted",
            uploaded_by_membership_id=membership_id,
        )
        session.add(certificate_version)
        session.flush()
        session.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=certificate.id,
                version_id=certificate_version.id,
                target_type="docket",
                target_id=docket.id,
                docket_id=docket.id,
                created_by_membership_id=membership_id,
            )
        )
        session.commit()
        ids = {
            "docket": docket.id,
            "registration": registration.id,
            "filing": filing.id,
            "acceptance": acceptance.id,
            "renewal": renewal.id,
            "grace": grace.id,
            "next_term": next_term.id,
            "fee": fee.id,
            "certificate": certificate.id,
        }
    return bootstrap, headers, ids


def _confirm_sources(ids: dict[str, str]) -> None:
    with get_session_factory()() as session:
        event = session.get(IpDocketEvent, ids["registration"])
        deadline = session.get(IpDeadline, ids["renewal"])
        assert event is not None and deadline is not None
        event.candidate_status = "confirmed"
        deadline.state = "confirmed"
        session.commit()


def test_ip_renewal_full_backend_contract_and_evidence_gates(client: TestClient) -> None:
    _, headers, ids = _seed_renewal_fixture(client)
    base = f"/api/ip/dockets/{ids['docket']}/renewal-terms"

    contract = client.get("/api/ip/renewals/foundation-contract", headers=headers)
    assert contract.status_code == 200
    assert contract.json()["cost_owner"] == "ip_cost_items"
    assert "never completes" in contract.json()["completion_rule"]

    create_payload = {
        "registration_event_id": ids["registration"],
        "renewal_deadline_id": ids["renewal"],
        "grace_deadline_id": ids["grace"],
        "fee_cost_item_id": ids["fee"],
    }
    unverified_event = client.post(base, headers=headers, json=create_payload)
    assert unverified_event.status_code == 409
    assert unverified_event.json()["code"] == "ip_renewal_event_not_verified"

    with get_session_factory()() as session:
        event = session.get(IpDocketEvent, ids["registration"])
        assert event is not None
        event.candidate_status = "confirmed"
        session.commit()
    unconfirmed_deadline = client.post(base, headers=headers, json=create_payload)
    assert unconfirmed_deadline.status_code == 409
    assert unconfirmed_deadline.json()["code"] == "ip_renewal_deadline_not_confirmed"
    _confirm_sources(ids)

    created = client.post(base, headers=headers, json=create_payload)
    assert created.status_code == 201, created.text
    term = created.json()
    assert term["state"] == "due"
    assert term["fee_cost_item_id"] == ids["fee"]

    instruction_payload = {
        "decision": "renew",
        "scope": {"classes": [9, 42], "jurisdiction": "IN"},
        "options": [{"key": "standard", "selected": True}],
        "source_channel": "client_portal",
        "authority_name": "Authorized client contact",
        "authority_reference": "BOARD-2026-08",
        "evidence_refs": ["portal://instruction/1"],
        "received_at": datetime.now(UTC).isoformat(),
    }
    instruction_response = client.post(
        f"{base}/{term['id']}/instructions", headers=headers, json=instruction_payload
    )
    assert instruction_response.status_code == 201, instruction_response.text
    instruction_term = instruction_response.json()
    first_instruction = instruction_term["instructions"][0]
    assert first_instruction["status"] == "pending"

    acknowledged = client.post(
        f"{base}/{term['id']}/instructions/{first_instruction['id']}/acknowledge",
        headers=headers,
        json={
            "expected_status": "pending",
            "expected_row_version": first_instruction["row_version"],
            "expected_updated_at": first_instruction["updated_at"],
            "status": "accepted",
            "reason": "Authority and renewal scope verified.",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text
    term = acknowledged.json()
    assert term["state"] == "instructed"

    stale_revision = client.post(
        f"{base}/{term['id']}/instructions",
        headers=headers,
        json={
            **instruction_payload,
            "authority_reference": "BOARD-2026-08-REV2",
            "expected_current_instruction_id": first_instruction["id"],
            "expected_current_row_version": 1,
        },
    )
    assert stale_revision.status_code == 409

    first_current = term["instructions"][0]
    revised = client.post(
        f"{base}/{term['id']}/instructions",
        headers=headers,
        json={
            **instruction_payload,
            "authority_reference": "BOARD-2026-08-REV2",
            "expected_current_instruction_id": first_current["id"],
            "expected_current_row_version": first_current["row_version"],
        },
    )
    assert revised.status_code == 201, revised.text
    term = revised.json()
    assert [row["status"] for row in term["instructions"]] == ["superseded", "pending"]
    second_instruction = term["instructions"][1]
    acknowledged_revision = client.post(
        f"{base}/{term['id']}/instructions/{second_instruction['id']}/acknowledge",
        headers=headers,
        json={
            "expected_status": "pending",
            "expected_row_version": second_instruction["row_version"],
            "expected_updated_at": second_instruction["updated_at"],
            "status": "accepted",
            "reason": "Revised authority and scope verified.",
        },
    )
    assert acknowledged_revision.status_code == 200, acknowledged_revision.text
    term = acknowledged_revision.json()

    initiated_payload = {
        "expected_state": term["state"],
        "expected_version": term["version"],
        "expected_updated_at": term["updated_at"],
        "target_state": "filing_in_progress",
        "reason": "Provider filing and fee payment were initiated.",
        "fee_cost_item_id": ids["fee"],
        "filing_initiated_reference": "provider://attempt/1",
    }
    initiated = client.post(
        f"{base}/{term['id']}/transition", headers=headers, json=initiated_payload
    )
    assert initiated.status_code == 200, initiated.text
    term = initiated.json()
    assert term["state"] == "filing_in_progress"
    assert term["acceptance_event_id"] is None
    assert term["completed_at"] is None

    stale = client.post(
        f"{base}/{term['id']}/transition", headers=headers, json=initiated_payload
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ip_renewal_term_stale"

    filed = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "filed",
            "reason": "Registry filing acknowledgement recorded.",
            "filing_event_id": ids["filing"],
        },
    )
    assert filed.status_code == 200, filed.text
    term = filed.json()

    acceptance_without_registry_evidence = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "accepted",
            "reason": "A provider claimed acceptance without registry evidence.",
            "filing_event_id": ids["filing"],
        },
    )
    assert acceptance_without_registry_evidence.status_code == 422

    replaced_filing_evidence = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "accepted",
            "reason": "Attempt to replace the recorded filing evidence.",
            "filing_event_id": ids["registration"],
            "acceptance_event_id": ids["acceptance"],
        },
    )
    assert replaced_filing_evidence.status_code == 409
    assert replaced_filing_evidence.json()["code"] == "ip_renewal_evidence_immutable"

    accepted = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "accepted",
            "reason": "Registry acceptance evidence verified.",
            "filing_event_id": ids["filing"],
            "acceptance_event_id": ids["acceptance"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    term = accepted.json()
    assert term["state"] == "accepted"
    assert term["completed_at"] is None

    mismatched_next_term = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "completed",
            "reason": "Attempt to use a deadline from the prior registration event.",
            "filing_event_id": ids["filing"],
            "acceptance_event_id": ids["acceptance"],
            "certificate_document_id": ids["certificate"],
            "next_term_deadline_id": ids["renewal"],
        },
    )
    assert mismatched_next_term.status_code == 409
    assert mismatched_next_term.json()["code"] == (
        "ip_renewal_next_term_trigger_mismatch"
    )

    completed = client.post(
        f"{base}/{term['id']}/transition",
        headers=headers,
        json={
            "expected_state": term["state"],
            "expected_version": term["version"],
            "expected_updated_at": term["updated_at"],
            "target_state": "completed",
            "reason": "Accepted certificate and next renewal term verified.",
            "filing_event_id": ids["filing"],
            "acceptance_event_id": ids["acceptance"],
            "certificate_document_id": ids["certificate"],
            "next_term_deadline_id": ids["next_term"],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    assert completed.json()["completed_at"] is not None

    listed = client.get(base, headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["state"] == "completed"


def test_ip_renewal_reads_are_tenant_isolated(client: TestClient) -> None:
    _, _, ids = _seed_renewal_fixture(client)
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Legal LLP",
            "company_slug": "second-legal",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondlegal.in",
            "owner_password": "SecondPass123!",
        },
    )
    assert response.status_code == 200, response.text
    second_headers = auth_headers(response.json()["access_token"])
    isolated = client.get(
        f"/api/ip/dockets/{ids['docket']}/renewal-terms",
        headers=second_headers,
    )
    assert isolated.status_code == 404
