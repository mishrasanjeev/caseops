"""Seed source-backed renewal evidence for the IPLF-037B browser journey."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from caseops_api.db.models import (
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpResponsibilityAssignment,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
)
from caseops_api.db.session import get_session_factory


def deadline(
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
        base_date=date.today(),
        duration_value=10,
        duration_unit="years",
        calendar_method="calendar_years",
        timezone="Asia/Kolkata",
        date_precision="date",
        certainty="verified",
        result_on=result_on,
        calculation_inputs_json={"registration_date": date.today().isoformat()},
        calculation_trace_json=[{"operation": "add_years", "value": 10}],
        explanation="Verified registry renewal fixture",
        rule_citation="Trade Marks Act and applicable rules",
        engine_version="iplf-037b-e2e-v1",
        source_version="registry-renewal-rules-2026-v1",
        state="confirmed",
        version=1,
        confirmed_by_membership_id=membership_id,
        confirmer_label_snapshot="Renewal Partner",
        confirmed_at=now,
        created_by_membership_id=membership_id,
        creator_label_snapshot="Renewal Partner",
    )


def main() -> None:
    company_id = os.environ["CASEOPS_E2E_COMPANY_ID"]
    membership_id = os.environ["CASEOPS_E2E_MEMBERSHIP_ID"]
    now = datetime.now(UTC)
    unique = uuid4().hex[:12]
    with get_session_factory()() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="ASTER renewal",
            primary_identifier=f"TM-RENEW-{unique}",
            status="ready",
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
            source_reference=f"registry://registration/{unique}",
            effective_at=now - timedelta(days=30),
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=[f"registry://registration/{unique}"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={"registration_number": unique},
        )
        filing = IpDocketEvent(
            company_id=company_id,
            docket_id=docket.id,
            sequence=2,
            event_kind="renewal_filing",
            source="registry",
            source_reference=f"registry://renewal-filing/{unique}",
            effective_at=now,
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=[f"registry://renewal-filing/{unique}"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={"acknowledgement": f"ACK-{unique}"},
        )
        acceptance = IpDocketEvent(
            company_id=company_id,
            docket_id=docket.id,
            sequence=3,
            event_kind="renewal_acceptance",
            source="registry",
            source_reference=f"registry://renewal-acceptance/{unique}",
            effective_at=now,
            responsible_membership_id=membership_id,
            entered_by_membership_id=membership_id,
            evidence_refs_json=[f"registry://renewal-acceptance/{unique}"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={"acceptance_number": f"ACC-{unique}"},
        )
        calendar = LegalWorkingCalendar(
            company_id=company_id,
            key=f"renewal-calendar-{unique}",
            name="India trademark renewal calendar",
            jurisdiction="IN",
            office="Trade Marks Registry",
            created_by_membership_id=membership_id,
        )
        rule_set = IpRuleSet(
            key=f"renewal-{unique}",
            rule_kind="deadline",
            jurisdiction="IN",
            office="Trade Marks Registry",
            right_kind="trademark",
            stage="registered",
        )
        session.add_all([registration, filing, acceptance, calendar, rule_set])
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
            source_reference=f"registry://calendar/{unique}",
            source_hash="a" * 64,
            effective_from=date(2026, 1, 1),
            approved_by_membership_id=membership_id,
            approver_label_snapshot="Renewal Partner",
            approved_at=now,
            proposer_label_snapshot="E2E fixture",
        )
        rule_version = IpRuleVersion(
            rule_set_id=rule_set.id,
            version=1,
            status="active",
            source_record_id=f"renewal-rule-{unique}",
            source_hash="b" * 64,
            source_reference=f"registry://renewal-rule/{unique}",
            effective_from=date(2026, 1, 1),
            engine_compatibility="iplf-037b-e2e-v1",
            fixture_set_json=[],
            definition_json={"duration": 10, "unit": "years"},
            proposer_label_snapshot="E2E fixture",
            legal_approved_by_membership_id=membership_id,
            legal_approver_label_snapshot="Renewal Partner",
            fixtures_passed_at=now,
            activated_at=now,
        )
        session.add_all([calendar_version, rule_version])
        session.flush()
        renewal = deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=registration.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal",
            title="Renewal due",
            result_on=date.today() + timedelta(days=120),
        )
        grace = deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=registration.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal_grace",
            title="Renewal grace period ends",
            result_on=date.today() + timedelta(days=300),
        )
        next_term = deadline(
            company_id=company_id,
            docket_id=docket.id,
            event_id=acceptance.id,
            rule_version_id=rule_version.id,
            calendar_version_id=calendar_version.id,
            membership_id=membership_id,
            kind="renewal",
            title="Next renewal due",
            result_on=date.today() + timedelta(days=3770),
        )
        fee = IpCostItem(
            company_id=company_id,
            docket_id=docket.id,
            category="official_fee",
            description="Renewal official fee quote",
            amount_minor=900000,
            currency="INR",
            billable=False,
            cost_nature="estimate",
            evidence_reference=f"registry://fees/{unique}",
            reconciliation_status="nonbillable",
            created_by_membership_id=membership_id,
        )
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key=f"renewal_certificate_{unique}",
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
            storage_key=f"e2e/{certificate.id}/1.pdf",
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
        session.add_all(
            [
                IpDocumentLink(
                    company_id=company_id,
                    document_id=certificate.id,
                    version_id=certificate_version.id,
                    target_type="docket",
                    target_id=docket.id,
                    docket_id=docket.id,
                    created_by_membership_id=membership_id,
                ),
                IpResponsibilityAssignment(
                    company_id=company_id,
                    docket_id=docket.id,
                    deadline_id=renewal.id,
                    membership_id=membership_id,
                    membership_label_snapshot="Renewal Partner",
                    role="primary",
                    effective_from=now - timedelta(days=1),
                    accepted_at=now,
                    replacement_source="iplf-037b-e2e",
                    escalation_policy_json={"supervisor_after_days": 0},
                    version=1,
                    created_by_membership_id=membership_id,
                    creator_label_snapshot="Renewal Partner",
                ),
                IpResponsibilityAssignment(
                    company_id=company_id,
                    docket_id=docket.id,
                    deadline_id=renewal.id,
                    membership_id=membership_id,
                    membership_label_snapshot="Supervising renewal partner",
                    role="supervisor",
                    effective_from=now - timedelta(days=1),
                    accepted_at=now,
                    replacement_source="iplf-037b-e2e",
                    escalation_policy_json={"supervisor_after_days": 0},
                    version=1,
                    created_by_membership_id=membership_id,
                    creator_label_snapshot="Renewal Partner",
                ),
            ]
        )
        session.commit()
        print(
            json.dumps(
                {
                    "docket": docket.id,
                    "registration": registration.id,
                    "renewal": renewal.id,
                    "grace": grace.id,
                    "fee": fee.id,
                    "filing": filing.id,
                    "acceptance": acceptance.id,
                    "certificate": certificate.id,
                    "next_term": next_term.id,
                }
            )
        )


if __name__ == "__main__":
    main()
