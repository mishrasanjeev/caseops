"""IPLF-032A: reminders retain provenance but display current canonical facts."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    InAppNotification,
    IpDeadline,
    IpIdentifier,
    IpImportRow,
    IpRenewalTerm,
    IpTrademarkParticularVersion,
    IpWorkspaceConfiguration,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker, ip_renewals, notification_delivery
from tests.test_auth_company import auth_headers, bootstrap_company

_NOW = datetime(2028, 3, 20, tzinfo=UTC)
_PRIVATE = "FAKE_INTERNAL_REMARK_DO_NOT_NOTIFY"


@pytest.fixture
def reminder_clock(monkeypatch):
    monkeypatch.setattr(ip_renewals, "_now", lambda: _NOW)
    monkeypatch.setattr(notification_delivery, "_now", lambda: _NOW)


@pytest.mark.parametrize("facts", ["current", "empty", "nontext-mark"])
def test_scheduler_uses_canonical_facts_not_caller_import_snapshot(monkeypatch, facts):
    docket = SimpleNamespace(id=str(uuid4()), title="Canonical docket label", current_version=2)
    row_id = str(uuid4())
    version = SimpleNamespace(
        id=str(uuid4()),
        representation_json={
            "text": "Current mark",
            "portfolio_import": {
                "source_row_id": row_id,
                "renewal_due_date": "2028-03-30",
                "internal_remarks": _PRIVATE,
            },
        },
        classes_json=[{"class_number": 42}, {"class_number": 45}],
        parties_json=[
            {"role": "applicant", "name": "Current Applicant"},
            {"role": "agent", "name": _PRIVATE},
        ],
    )
    number = "CURRENT/2028"
    if facts == "empty":
        version.representation_json.pop("text")
        version.classes_json = version.parties_json = []
        number = None
    elif facts == "nontext-mark":
        version.representation_json["text"] = {"internal_remarks": _PRIVATE}
    captured = {}

    def locked_docket(_session, _context, docket_id, *, write):
        assert docket_id == docket.id and write is True
        return docket

    class Session:
        def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is IpTrademarkParticularVersion:
                return version
            if entity is IpWorkspaceConfiguration:
                return SimpleNamespace(timezone="UTC", renewal_reminder_policy_json={}, version=1)
            assert entity is IpIdentifier
            return number

    def enqueue(_session, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(metadata_json={})

    monkeypatch.setattr(ip_renewals, "_docket", locked_docket)
    monkeypatch.setattr(ip_renewals, "_imported_source_row", lambda *args, **kwargs: object())
    monkeypatch.setattr(ip_renewals, "enqueue_notification_delivery_intent", enqueue)
    monkeypatch.setattr(ip_renewals, "_now", lambda: _NOW)
    linked = []
    monkeypatch.setattr(
        ip_renewal_tracker, "synchronize_series", lambda _session, **kwargs: linked.append(kwargs)
    )
    context = SimpleNamespace(
        company=SimpleNamespace(id=str(uuid4()), timezone="UTC"), membership=object()
    )
    intent = ip_renewals.schedule_imported_renewal_reminder(
        Session(),
        context=context,
        docket_id=docket.id,
        row_id=row_id,
        normalized={
            "renewal_due_date": "2028-03-30",
            "title": "IMPORT SNAPSHOT",
            "applicant_name": "IMPORT APPLICANT",
            "application_number": "IMPORT/OLD",
            "class_numbers": [9],
            "internal_remarks": _PRIVATE,
        },
    )
    body = captured["body"]
    assert linked == [
        {"context": context, "docket_id": docket.id, "legacy_intent": intent, "now": _NOW}
    ]
    assert "IMPORT" not in body and _PRIVATE not in body
    assert captured["source_id"] == version.id and captured["channel"] == "in_app"
    assert intent.metadata_json["source_due_on"] == "2028-03-30"
    assert "not a verified legal deadline" in body
    if facts == "empty":
        assert body.startswith("Canonical docket label;")
        assert "application not recorded; classes not recorded; applicant not recorded." in body
    else:
        assert body.startswith("Current mark;" if facts == "current" else "Canonical docket label;")
        assert "application CURRENT/2028; classes 42, 45; applicant Current Applicant." in body


def _import_source(client):
    actor = bootstrap_company(client)
    actor["headers"] = {
        **auth_headers(str(actor["access_token"])),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    configured = client.put(
        "/api/ip/workspace/configuration",
        headers=actor["headers"],
        json={
            "enabled_asset_types": ["trademark"],
            "jurisdictions": ["IN"],
            "offices": ["IP India"],
            "timezone": "Asia/Kolkata",
            "holiday_calendar_key": "source-fixture",
            "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
            "document_taxonomy_version": "fixture-v1",
            "event_catalog_version": "fixture-v1",
            "deadline_rule_versions": {},
            "notification_channels": ["in_app"],
            "critical_event_policy": {"escalation_after_minutes": 60},
            "escalation_owner_membership_id": actor["membership"]["id"],
        },
    )
    assert configured.status_code == 200, configured.text
    uploaded = client.post(
        "/api/ip/imports/upload",
        headers=actor["headers"],
        files={
            "file": (
                "current-source.csv",
                (
                    "Trademark,Applicant,Class,Goods/Services,Application No.,"
                    "Renewal Date,Internal Remarks\n"
                    f"Original mark,Original Applicant,9,Software,OLD/2026,2028-03-31,{_PRIVATE}\n"
                ).encode(),
                "text/csv",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    preview = uploaded.json()
    committed = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert committed.status_code == 200, committed.text
    row = committed.json()["rows"][0]
    assert row["commit_status"] == "committed"
    return actor, row


def _correct_number(client, actor, docket_id):
    with get_session_factory()() as session:
        previous = session.scalar(
            select(IpIdentifier).where(
                IpIdentifier.company_id == actor["company"]["id"],
                IpIdentifier.docket_id == docket_id,
                IpIdentifier.is_primary.is_(True),
            )
        )
        payload = {
            "application_id": previous.application_id,
            "identifier_kind": "application",
            "raw_value": "CURRENT/2028",
            "office": previous.office,
            "jurisdiction": previous.jurisdiction,
            "source": "reviewed source correction",
            "effective_from": "2028-03-20",
            "is_primary": True,
            "supersedes_identifier_id": previous.id,
            "correction_reason": "Corrected against current canonical application source",
        }
        identifier_id = previous.id
    response = client.post(
        f"/api/ip/dockets/{docket_id}/identifiers/{identifier_id}/corrections",
        headers=actor["headers"],
        json=payload,
    )
    assert response.status_code == 201, response.text


def _append_current(client, actor, docket_id, *, due="2028-03-30"):
    response = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"])
    assert response.status_code == 200, response.text
    docket = response.json()
    previous_version = docket["current_version"]
    correction_version = previous_version + 1
    reason = f"Correct imported source date before particulars version {previous_version + 2}"
    corrected = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-renewal-date",
        headers=actor["headers"],
        json={
            "expected_current_version": previous_version,
            "renewal_due_date": due,
            "reason": reason,
        },
    )
    assert corrected.status_code == 200, corrected.text
    dated = corrected.json()
    assert dated["current_version"] == correction_version
    particulars = dated["current_particulars"]
    assert particulars["representation_json"]["portfolio_import"]["renewal_due_date"] == due
    with get_session_factory()() as session:
        intermediate = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.ip_docket_id == docket_id,
                    NotificationDeliveryIntent.status == "queued",
                )
            )
        )
        assert len(intermediate) == int(due is not None)
        assert all(intent.source_id == particulars["id"] for intent in intermediate)
        intermediate_ids = [intent.id for intent in intermediate]
    version = correction_version + 1
    representation = deepcopy(particulars["representation_json"])
    representation["text"] = f"Current mark v{version}"
    changed = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=actor["headers"],
        json={
            "expected_current_version": correction_version,
            "form_key": particulars["form_key"],
            "form_version": particulars["form_version"],
            "mark_kind": particulars["mark_kind"],
            "representation": representation,
            "classes": [
                {"class_number": 42, "specification": "Current legal services"},
                {"class_number": 45, "specification": "Current professional services"},
            ],
            "parties": [
                {"role": "applicant", "name": f"Current Applicant v{version}"},
                {"role": "applicant", "name": "Current Joint Applicant"},
                {"role": "agent", "name": _PRIVATE},
            ],
            "filing_manifest": particulars["filing_manifest_json"],
            "finalize": False,
        },
    )
    assert changed.status_code == 200, changed.text
    current = changed.json()
    assert current["current_version"] == version
    for key in ("portfolio_import", "portfolio_dates"):
        assert (
            current["current_particulars"]["representation_json"][key]
            == particulars["representation_json"][key]
        )
    stale = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-renewal-date",
        headers=actor["headers"],
        json={
            "expected_current_version": previous_version,
            "renewal_due_date": None,
            "reason": "Stale source correction cannot replace current dates",
        },
    )
    assert stale.status_code == 409, stale.text
    with get_session_factory()() as session:
        assert list(
            session.scalars(
                select(IpTrademarkParticularVersion.version)
                .where(IpTrademarkParticularVersion.docket_id == docket_id)
                .order_by(IpTrademarkParticularVersion.version)
            )
        ) == list(range(1, version + 1))
        events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == actor["company"]["id"],
                    AuditEvent.ip_docket_id == docket_id,
                    AuditEvent.action.in_(
                        ("ip_docket.version_created", "ip_portfolio.dates_corrected")
                    ),
                )
            )
        )
        for saved_version in (correction_version, version):
            writes = [
                event
                for event in events
                if event.action == "ip_docket.version_created"
                and json.loads(event.metadata_json)["version"] == saved_version
            ]
            assert len(writes) == 1
            assert writes[0].actor_membership_id == actor["membership"]["id"]
        corrections = [
            event
            for event in events
            if event.action == "ip_portfolio.dates_corrected"
            and json.loads(event.metadata_json)["version"] == correction_version
        ]
        assert len(corrections) == 1
        assert corrections[0].actor_membership_id == actor["membership"]["id"]
        metadata = json.loads(corrections[0].metadata_json)
        assert metadata["previous_version"] == previous_version and metadata["reason"] == reason
        assert metadata["changed_fields"] == ["renewal_due_date"]
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.ip_docket_id == docket_id
                )
            )
        )
        queued = [intent for intent in intents if str(intent.status) == "queued"]
        assert len(queued) == int(due is not None)
        assert all(
            intent.source_id == current["current_particulars"]["id"]
            and intent.metadata_json["source_due_on"] == due
            for intent in queued
        )
        assert all(str(intent.status) == "cancelled" for intent in intents if intent not in queued)
        assert all(
            str(session.get(NotificationDeliveryIntent, identity).status) == "cancelled"
            for identity in intermediate_ids
        )
    return current


@pytest.mark.parametrize("corrections", [1, 2], ids=["first-correction", "repeated-correction"])
@pytest.mark.parametrize(
    "client_fixture",
    [
        pytest.param("client", id="sqlite"),
        pytest.param("isolated_postgres_client", id="postgres", marks=pytest.mark.postgres),
    ],
)
def test_actual_dispatch_uses_exact_current_version_facts(
    request,
    client_fixture,
    reminder_clock,
    corrections,
):
    client = request.getfixturevalue(client_fixture)
    actor, row = _import_source(client)
    docket_id = row["created_docket_id"]
    original = deepcopy(row["normalized"])
    _correct_number(client, actor, docket_id)
    for _ in range(corrections):
        current = _append_current(client, actor, docket_id)
    version = 1 + 2 * corrections
    assert current["current_version"] == version
    with get_session_factory()() as session:
        intents = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == actor["company"]["id"],
                NotificationDeliveryIntent.ip_docket_id == docket_id,
            )
        ).all()
        pending = [intent for intent in intents if str(intent.status) == "queued"]
        assert len(pending) == 1
        intent = pending[0]
        assert all(str(other.status) == "cancelled" for other in intents if other.id != intent.id)
        assert intent.source_id == current["current_particulars"]["id"]
        assert intent.metadata_json["source_due_on"] == "2028-03-30"
        assert str(intent.channel) == "in_app"
        delivered = notification_delivery.process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            company_id=actor["company"]["id"],
        )
        assert delivered.delivered and str(delivered.status) == "delivered"
        session.commit()
        session.expire_all()
        notes = session.scalars(
            select(InAppNotification).where(
                InAppNotification.company_id == actor["company"]["id"],
                InAppNotification.source_type == "ip_trademark_particular_version",
            )
        ).all()
        assert len(notes) == 1 and notes[0].source_id == current["current_particulars"]["id"]
        body = notes[0].body
        assert body.startswith(f"Current mark v{version};")
        assert "application CURRENT/2028; classes 42, 45;" in body
        assert f"applicant Current Applicant v{version}, Current Joint Applicant." in body
        assert "Source renewal date 2028-03-30 (not a verified legal deadline)." in body
        assert "10 days remaining on the alert date." in body
        assert f"/app/ip?docket={docket_id}" in body
        assert all(
            value not in body
            for value in (
                "Original mark",
                "Original Applicant",
                "OLD/2026",
                "classes 9",
                "2028-03-31",
                _PRIVATE,
            )
        )
        assert session.get(IpImportRow, row["id"]).normalized_json == original
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpDeadline)
                .where(IpDeadline.company_id == actor["company"]["id"])
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpRenewalTerm)
                .where(IpRenewalTerm.company_id == actor["company"]["id"])
            )
            == 0
        )


@pytest.mark.parametrize("boundary", ["revoked-recipient", "retained-old-version", "removed-date"])
def test_current_facts_do_not_bypass_delivery_fences(client, reminder_clock, boundary):
    actor, row = _import_source(client)
    docket_id = row["created_docket_id"]
    _append_current(
        client, actor, docket_id, due=None if boundary == "removed-date" else "2028-03-30"
    )
    with get_session_factory()() as session:
        intents = session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.ip_docket_id == docket_id,
            )
        ).all()
        if boundary == "removed-date":
            assert all(str(intent.status) == "cancelled" for intent in intents)
            intent = session.get(
                NotificationDeliveryIntent, row["normalized"]["_renewal_reminder"]["intent_id"]
            )
            expected = "cancelled"
        elif boundary == "retained-old-version":
            intent = session.get(
                NotificationDeliveryIntent, row["normalized"]["_renewal_reminder"]["intent_id"]
            )
            intent.status = "queued"
            session.commit()
            expected = "blocked"
        else:
            intent = next(intent for intent in intents if str(intent.status) == "queued")
            session.get(CompanyMembership, actor["membership"]["id"]).is_active = False
            session.commit()
            expected = "blocked"
        result = notification_delivery.process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            company_id=actor["company"]["id"],
        )
        session.commit()
        assert str(result.status) == expected and not result.delivered
        assert (
            session.scalar(
                select(func.count())
                .select_from(InAppNotification)
                .where(InAppNotification.company_id == actor["company"]["id"])
            )
            == 0
        )
