"""Adjacent source applicability and category/write-admission boundaries."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from caseops_api.db.models import TrademarkApplication
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker
from tests.test_ip_renewal_tracker_20261015 import _clock, _imported


def test_cadence_only_http_edit_retains_existing_provider_consent_and_resets_readiness(client):
    from caseops_api.db.models import IpWorkspaceConfiguration
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_ip_workspace_configuration import _configuration

    actor = bootstrap_company(client)
    headers = {
        **auth_headers(actor["access_token"]),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    payload = _configuration(actor["membership"]["id"], provider_keys=["ipindia-registry"])
    first = client.put("/api/ip/workspace/configuration", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    before = first.json()["configuration"]
    assert (
        before["provider_terms_accepted_at"] and before["provider_terms_accepted_by_membership_id"]
    )
    with get_session_factory()() as session:
        consent_before = session.execute(
            select(
                IpWorkspaceConfiguration.provider_terms_accepted_at,
                IpWorkspaceConfiguration.provider_terms_accepted_by_membership_id,
            ).where(IpWorkspaceConfiguration.company_id == actor["company"]["id"])
        ).one()
    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={
            "expected_config_version": 1,
            "enabled_automations": [],
        },
    )
    assert (
        enabled.status_code == 200 and enabled.json()["configuration"]["workspace_enabled"] is True
    )
    payload.update(
        expected_version=1,
        accept_provider_terms=False,
        renewal_reminder_cadence_days=2,
        renewal_reminder_delivery_time="10:15",
    )
    edited = client.put("/api/ip/workspace/configuration", headers=headers, json=payload)
    assert edited.status_code == 200, edited.text
    after = edited.json()["configuration"]
    assert after["version"] == 2 and after["workspace_enabled"] is False
    assert after["enabled_automations_json"] == [] and edited.json()["tests"] == []
    for field in (
        "provider_terms_accepted_by_membership_id",
        "provider_terms_version",
        "provider_keys_json",
        "jurisdictions_json",
        "offices_json",
        "deadline_rule_versions_json",
        "working_day_policy_json",
        "notification_channels_json",
    ):
        assert after[field] == before[field], field

    def utc_stamp(value):
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)

    assert utc_stamp(after["provider_terms_accepted_at"]) == utc_stamp(
        before["provider_terms_accepted_at"]
    )
    with get_session_factory()() as session:
        consent_after = session.execute(
            select(
                IpWorkspaceConfiguration.provider_terms_accepted_at,
                IpWorkspaceConfiguration.provider_terms_accepted_by_membership_id,
            ).where(IpWorkspaceConfiguration.company_id == actor["company"]["id"])
        ).one()
        assert consent_after == consent_before
    assert (
        after["renewal_reminder_cadence_days"] == 2
        and after["renewal_reminder_delivery_time"] == "10:15"
    )
    stale = client.put("/api/ip/workspace/configuration", headers=headers, json=payload)
    assert stale.status_code == 409, stale.text


def test_new_editor_then_legacy_correct_and_clear_agree_across_current_surfaces(
    client, monkeypatch
):
    from caseops_api.db.models import NotificationDeliveryIntent

    actor, docket_id = _imported(client, monkeypatch)
    first = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "renewal_due_date": "2028-04-30",
            "reason": "New editor source correction",
        },
    )
    assert first.status_code == 200, first.text
    for version, due in ((2, "2028-05-31"), (3, None)):
        legacy = client.patch(
            f"/api/ip/dockets/{docket_id}/portfolio-renewal-date",
            headers=actor["headers"],
            json={
                "expected_current_version": version,
                "renewal_due_date": due,
                "reason": "Legacy imported source correction",
            },
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["current_version"] == version + 1
        for url in ("/api/ip/portfolio", "/api/ip/portfolio/renewal-tracker"):
            response = client.get(url, headers=actor["headers"])
            assert response.status_code == 200, response.text
            row = next(row for row in response.json()["rows"] if row["docket_id"] == docket_id)
            assert row["source_renewal_due_on"] == due
            assert row["source_renewal_state"] == ("manual" if due else "missing")
        with get_session_factory()() as session:
            pending = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.ip_docket_id == docket_id,
                        NotificationDeliveryIntent.status.in_(("queued", "retry_scheduled")),
                    )
                )
            )
            assert len(pending) == int(due is not None)
            if pending:
                assert pending[0].metadata_json["source_due_on"] == due


@pytest.mark.parametrize("origin", ["manual", "verified"])
def test_generic_particular_writers_cannot_inject_reserved_date_corrections(client, origin):
    from tests.test_ip_039a_filing_particulars import _particulars
    from tests.test_ip_portfolio_spec_20261013 import _actor

    actor = _actor(client)
    particulars = _particulars("Reserved date boundary")
    injected = deepcopy(particulars)
    injected["representation"]["portfolio_dates"] = {
        "renewal_due_date": {"value": "2028-03-31", "origin": origin}
    }
    created = client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "Reserved date boundary",
            "restricted": False,
            "particulars": injected,
        },
    )
    assert created.status_code == 422, created.text
    normal = client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "Reserved date boundary",
            "restricted": False,
            "particulars": particulars,
        },
    )
    assert normal.status_code == 201, normal.text
    docket_id = normal.json()["id"]
    appended = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=actor["headers"],
        json={**injected, "expected_current_version": 1},
    )
    assert appended.status_code == 422, appended.text
    current = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    assert current["current_version"] == 1


def test_generic_append_preserves_saved_dates_but_cannot_change_or_remove_them(client):
    from tests.test_ip_039a_filing_particulars import _particulars
    from tests.test_ip_portfolio_spec_20261013 import _actor

    actor = _actor(client)
    body = _particulars("Preserve reserved date boundary")
    created = client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "Preserve reserved date boundary",
            "restricted": False,
            "particulars": body,
        },
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]
    edited = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "renewal_due_date": "2028-03-31",
            "reason": "Explicit source correction",
        },
    )
    assert edited.status_code == 200, edited.text
    saved = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()[
        "current_particulars"
    ]["representation_json"]["portfolio_dates"]
    for version, representation in (
        (2, body["representation"]),
        (3, {**body["representation"], "portfolio_dates": saved}),
    ):
        appended = client.post(
            f"/api/ip/dockets/{docket_id}/versions",
            headers=actor["headers"],
            json={
                **body,
                "representation": representation,
                "expected_current_version": version,
            },
        )
        assert appended.status_code == 200, appended.text
    for replacement in (
        None,
        {},
        {"renewal_due_date": {"value": "2029-03-31", "origin": "manual"}},
    ):
        denied = client.post(
            f"/api/ip/dockets/{docket_id}/versions",
            headers=actor["headers"],
            json={
                **body,
                "representation": {**body["representation"], "portfolio_dates": replacement},
                "expected_current_version": 4,
            },
        )
        assert denied.status_code == 422, denied.text
    dates = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"]).json()[
        "rows"
    ][0]
    assert dates["current_version"] == 4 and dates["source_renewal_due_on"] == "2028-03-31"


def test_generic_append_cannot_alter_or_rebind_materialized_import_dates(client, monkeypatch):
    from uuid import uuid4

    from caseops_api.db.models import AuditEvent, IpImportRow, NotificationDeliveryIntent
    from tests.test_ip_039a_filing_particulars import _particulars

    actor, docket_id = _imported(client, monkeypatch)
    original = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    source = original["current_particulars"]["representation_json"]["portfolio_import"]
    with get_session_factory()() as session:
        row = session.get(IpImportRow, source["source_row_id"])
        ledger = deepcopy((row.raw_json, row.normalized_json))
        before_intents = deepcopy(
            session.execute(
                select(
                    NotificationDeliveryIntent.id,
                    NotificationDeliveryIntent.status,
                    NotificationDeliveryIntent.source_id,
                    NotificationDeliveryIntent.scheduled_for,
                    NotificationDeliveryIntent.metadata_json,
                ).where(NotificationDeliveryIntent.ip_docket_id == docket_id)
            ).all()
        )
        before_audit = list(
            session.scalars(select(AuditEvent.id).where(AuditEvent.ip_docket_id == docket_id))
        )
    for replacement in (
        {**source, "renewal_due_date": "2029-04-30"},
        {**source, "application_date": "2021-04-30"},
        {**source, "source_row_id": str(uuid4())},
        None,
        {},
        {**source, "date_correction": {"writer": "portfolio_dates", "reason": "Forged reason"}},
    ):
        denied = client.post(
            f"/api/ip/dockets/{docket_id}/versions",
            headers=actor["headers"],
            json={
                **_particulars("Unrelated mark edit"),
                "representation": {"text": "Unrelated mark edit", "portfolio_import": replacement},
                "expected_current_version": 1,
            },
        )
        assert denied.status_code == 422, denied.text
    current = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    assert current["current_version"] == 1
    assert current["current_particulars"] == original["current_particulars"]
    for url in ("/api/ip/portfolio", "/api/ip/portfolio/renewal-tracker"):
        response = client.get(url, headers=actor["headers"])
        assert response.status_code == 200, response.text
        dates = next(row for row in response.json()["rows"] if row["docket_id"] == docket_id)
        assert dates["source_application_on"] == "2020-03-31"
        assert dates["source_renewal_due_on"] == "2028-03-31"
        assert (
            dates["source_application_state"]
            == dates["source_renewal_state"]
            == "imported_unverified"
        )
    with get_session_factory()() as session:
        row = session.get(IpImportRow, source["source_row_id"])
        assert (row.raw_json, row.normalized_json) == ledger
        assert (
            session.execute(
                select(
                    NotificationDeliveryIntent.id,
                    NotificationDeliveryIntent.status,
                    NotificationDeliveryIntent.source_id,
                    NotificationDeliveryIntent.scheduled_for,
                    NotificationDeliveryIntent.metadata_json,
                ).where(NotificationDeliveryIntent.ip_docket_id == docket_id)
            ).all()
            == before_intents
        )
        assert set(
            session.scalars(select(AuditEvent.id).where(AuditEvent.ip_docket_id == docket_id))
        ) == set(before_audit)


def test_generic_append_preserves_import_source_and_unbound_create_stays_missing(
    client, monkeypatch
):
    from caseops_api.db.models import AuditEvent, IpImportRow, NotificationDeliveryIntent
    from tests.test_ip_039a_filing_particulars import _particulars

    actor, docket_id = _imported(client, monkeypatch)
    original = client.get(f"/api/ip/dockets/{docket_id}", headers=actor["headers"]).json()
    source = original["current_particulars"]["representation_json"]["portfolio_import"]
    with get_session_factory()() as session:
        row = session.get(IpImportRow, source["source_row_id"])
        ledger = deepcopy((row.raw_json, row.normalized_json))
    for expected in (1, 2):
        representation = {"text": f"Ordinary mark edit {expected}"}
        if expected == 2:
            representation["portfolio_import"] = deepcopy(source)
        saved = client.post(
            f"/api/ip/dockets/{docket_id}/versions",
            headers=actor["headers"],
            json={
                **_particulars(representation=representation),
                "expected_current_version": expected,
            },
        )
        assert saved.status_code == 200, saved.text
        assert (
            saved.json()["current_particulars"]["representation_json"]["portfolio_import"] == source
        )
        for url in ("/api/ip/portfolio", "/api/ip/portfolio/renewal-tracker"):
            response = client.get(url, headers=actor["headers"])
            assert response.status_code == 200, response.text
            dates = next(row for row in response.json()["rows"] if row["docket_id"] == docket_id)
            assert dates["current_version"] == expected + 1
            assert dates["source_application_on"] == "2020-03-31"
            assert dates["source_renewal_due_on"] == "2028-03-31"
            assert (
                dates["source_application_state"]
                == dates["source_renewal_state"]
                == "imported_unverified"
            )
        with get_session_factory()() as session:
            queued = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.ip_docket_id == docket_id,
                        NotificationDeliveryIntent.status == "queued",
                    )
                )
            )
            assert len(queued) == 1 and queued[0].metadata_json["source_due_on"] == "2028-03-31"
    unbound = client.post(
        "/api/ip/dockets",
        headers=actor["headers"],
        json={
            "title": "Unbound imported-looking record",
            "restricted": False,
            "particulars": _particulars(
                representation={
                    "text": "Unbound imported-looking record",
                    "portfolio_import": {
                        **source,
                        "date_correction": {"writer": "portfolio_dates", "reason": "Forged reason"},
                    },
                }
            ),
        },
    )
    assert unbound.status_code == 201, unbound.text
    unbound_id = unbound.json()["id"]
    # Generic docket creation does not materialize a portfolio application.
    portfolio = client.get("/api/ip/portfolio", headers=actor["headers"])
    assert portfolio.status_code == 200, portfolio.text
    assert all(row["docket_id"] != unbound_id for row in portfolio.json()["rows"])
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert response.status_code == 200, response.text
    dates = next(row for row in response.json()["rows"] if row["docket_id"] == unbound_id)
    assert dates["source_application_on"] is None and dates["source_renewal_due_on"] is None
    assert dates["source_application_state"] == dates["source_renewal_state"] == "missing"
    with get_session_factory()() as session:
        row = session.get(IpImportRow, source["source_row_id"])
        assert (row.raw_json, row.normalized_json) == ledger
        assert (
            session.scalar(
                select(TrademarkApplication.id).where(TrademarkApplication.docket_id == unbound_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.ip_docket_id == unbound_id,
                    AuditEvent.action == "ip_docket.source_materialized",
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(NotificationDeliveryIntent.id).where(
                    NotificationDeliveryIntent.ip_docket_id == unbound_id
                )
            )
            is None
        )


@pytest.mark.parametrize("case", ["later_active", "tied_ambiguous", "later_completed"])
def test_current_renewal_term_wins_over_historical_sibling_and_categories(
    client, monkeypatch, case
):
    from datetime import date

    from caseops_api.db.models import IpDeadline, IpRenewalTerm, IpTrademarkParticularVersion
    from tests.test_ip_renewals import _seed_renewal_fixture

    actor, headers, ids = _seed_renewal_fixture(client)
    now = datetime(2036, 7, 10, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    with get_session_factory()() as session:
        version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.docket_id == ids["docket"]
            )
        )
        # Explicit retained source fixture, not an HTTP bypass of the reserved-field guard.
        version.representation_json = {
            **version.representation_json,
            "portfolio_dates": {
                "renewal_due_date": {"value": "2036-08-01", "origin": "manual"},
            },
        }
        session.get(IpDeadline, ids["grace"]).result_on = date(2036, 8, 1)
        for index, deadline_id in enumerate((ids["renewal"], ids["grace"])):
            completed = index == 0 or case == "later_completed"
            session.add(
                IpRenewalTerm(
                    company_id=actor["company"]["id"],
                    docket_id=ids["docket"],
                    term_sequence=1 if index == 0 or case == "tied_ambiguous" else 2,
                    registration_event_id=ids["registration"],
                    renewal_deadline_id=deadline_id,
                    state="completed" if completed else "due",
                    filing_event_id=ids["filing"] if completed else None,
                    acceptance_event_id=ids["acceptance"] if completed else None,
                    certificate_document_id=ids["certificate"] if completed else None,
                    next_term_deadline_id=ids["next_term"] if completed else None,
                    completed_at=now if completed else None,
                    created_by_membership_id=actor["membership"]["id"],
                    updated_by_membership_id=actor["membership"]["id"],
                )
            )
        session.commit()
    with get_session_factory()() as session:
        result = ip_renewal_tracker.reconcile_renewal_series(session)
        assert result["advanced"] == int(case == "later_active")
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=headers)
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["docket_operational"] is True
    if case == "later_active":
        assert row["status"] == "active" and response.json()["counts"]["active"] == 1
    else:
        assert row["status"] == "cancelled" and all(
            count == 0 for count in response.json()["counts"].values()
        )
        assert row["last_error"]
    if case == "later_completed":
        edited = client.patch(
            f"/api/ip/dockets/{ids['docket']}/portfolio-dates",
            headers=headers,
            json={
                "expected_current_version": 1,
                "renewal_due_date": "2037-08-01",
                "reason": "Explicit next source date after completed term",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["tracker"]["docket_operational"] is True


def test_inactive_historical_application_does_not_cancel_current_record(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    with get_session_factory()() as session:
        current = session.scalar(
            select(TrademarkApplication).where(TrademarkApplication.docket_id == docket_id)
        )
        session.add(
            TrademarkApplication(
                company_id=current.company_id,
                docket_id=docket_id,
                asset_id=current.asset_id,
                office=current.office,
                jurisdiction=current.jurisdiction,
                filing_phase="closed",
                is_active=False,
            )
        )
        session.commit()
    with get_session_factory()() as session:
        result = ip_renewal_tracker.reconcile_renewal_series(session)
        assert result["advanced"] == 1
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["status"] == "active"
    assert response.json()["counts"]["active"] == 1


def test_delayed_legacy_delivery_dedupes_today_after_source_and_policy_resets(client, monkeypatch):
    from sqlalchemy import func

    from caseops_api.db.models import (
        InAppNotification,
        IpPortfolioRenewalSeries,
        IpWorkspaceConfiguration,
    )
    from tests.test_ip_renewal_tracker_20261015 import _dispatch

    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    delivered = _dispatch(actor)
    assert len(delivered) == 1 and delivered[0].delivered
    with get_session_factory()() as session:
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        assert series.last_delivery_key
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 1
    corrected = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "application_date": "2020-04-01",
            "reason": "Same due date source version reset",
        },
    )
    assert corrected.status_code == 200, corrected.text
    with get_session_factory()() as session:
        config = session.scalar(
            select(IpWorkspaceConfiguration).where(
                IpWorkspaceConfiguration.company_id == actor["company"]["id"]
            )
        )
        config.version += 1
        session.commit()
        ip_renewal_tracker.reconcile_renewal_series(session)
    assert _dispatch(actor) == []
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 1


def test_closed_missing_date_is_not_editable_or_an_outstanding_category(client, monkeypatch):
    actor, docket_id = _imported(client, monkeypatch)
    cleared = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "renewal_due_date": None,
            "reason": "Source date withdrawn",
        },
    )
    assert cleared.status_code == 200, cleared.text
    closed = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle",
        headers=actor["headers"],
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Close record under explicit lifecycle control",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:reviewed-closure",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["docket_operational"] is False and row["status"] == "cancelled"
    assert all(count == 0 for count in response.json()["counts"].values())
    edit = client.patch(
        f"/api/ip/dockets/{docket_id}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 2,
            "application_date": None,
            "reason": "Closed record must reject date writes",
        },
    )
    assert edit.status_code == 404, edit.text


def test_closed_past_failed_record_is_not_an_outstanding_filter_or_export(client, monkeypatch):
    from caseops_api.db.models import NotificationDeliveryIntent
    from caseops_api.services import notification_delivery

    actor, docket_id = _imported(client, monkeypatch)
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    with get_session_factory()() as session:
        ip_renewal_tracker.reconcile_renewal_series(session)
        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.source_type == ip_renewal_tracker.SOURCE
            )
        )
        notification_delivery.record_notification_delivery_failure(
            session,
            intent=intent,
            raw_error="Deterministic terminal local failure",
            retryable=False,
        )
        session.commit()
    closed = client.post(
        f"/api/ip/dockets/{docket_id}/lifecycle",
        headers=actor["headers"],
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Close record with retained failed delivery",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:reviewed-closure",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    _clock(monkeypatch, datetime(2028, 4, 1, 4, tzinfo=UTC))
    for category in ("overdue", "failed"):
        response = client.get(
            "/api/ip/portfolio/renewal-tracker",
            headers=actor["headers"],
            params={"category": category},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == [] and response.json()["counts"][category] == 0
        response = client.get(
            "/api/ip/portfolio",
            headers=actor["headers"],
            params={"include_inactive": True, "renewal_tracker_state": category},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows"] == []
        response = client.post(
            "/api/ip/portfolio/exports/preview",
            headers=actor["headers"],
            json={
                "format": "csv",
                "columns": ["mark", "renewal_due_date"],
                "row_limit": 50000,
                "filters": {"include_inactive": True, "renewal_tracker_state": [category]},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["row_count"] == 0


@pytest.mark.parametrize(
    "bad", [{"cadence_days": 0}, {"cadence_days": True}, {"delivery_time": "25:61"}, []]
)
@pytest.mark.parametrize("legacy_without_series", [False, True])
def test_corrupt_persisted_policy_is_controlled_and_does_not_abort_other_tenant(
    client, monkeypatch, bad, legacy_without_series
):
    from caseops_api.db.models import IpPortfolioRenewalSeries, IpWorkspaceConfiguration
    from tests.test_auth_company import auth_headers
    from tests.test_ip_portfolio_spec_20261013 import _commit, _upload
    from tests.test_ip_workspace_configuration import _bootstrap_tenant

    if legacy_without_series:
        with monkeypatch.context() as scope:
            scope.setattr(ip_renewal_tracker, "synchronize_series", lambda *args, **kwargs: None)
            actor, docket_id = _imported(client, monkeypatch)
        with get_session_factory()() as session:
            assert (
                session.scalar(
                    select(IpPortfolioRenewalSeries).where(
                        IpPortfolioRenewalSeries.docket_id == docket_id
                    )
                )
                is None
            )
    else:
        actor, docket_id = _imported(client, monkeypatch)
    other = _bootstrap_tenant(client, slug="other-policy", email="owner@otherpolicy.in")
    other["headers"] = {
        **auth_headers(other["access_token"]),
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    configured = client.put(
        "/api/ip/workspace/configuration",
        headers=other["headers"],
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
            "escalation_owner_membership_id": other["membership"]["id"],
        },
    )
    assert configured.status_code == 200, configured.text
    preview = _upload(
        client, other, ["Trademark", "Renewal Date"], [["Other policy tenant", "2028-03-31"]]
    )
    _commit(client, other, preview)
    with get_session_factory()() as session:
        config = session.scalar(
            select(IpWorkspaceConfiguration).where(
                IpWorkspaceConfiguration.company_id == actor["company"]["id"]
            )
        )
        config.renewal_reminder_policy_json = bad
        config.version += 1
        session.commit()
    _clock(monkeypatch, datetime(2028, 3, 1, 4, tzinfo=UTC))
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=actor["headers"])
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "ip_renewal_reminder_policy_invalid"
    with get_session_factory()() as session:
        result = ip_renewal_tracker.reconcile_renewal_series(session)
        assert result["advanced"] == 1 and result["invalid_policy"] == 1
        assert not session.in_transaction()
    with get_session_factory()() as session:
        assert ip_renewal_tracker.reconcile_renewal_series(session)["examined"] == 0
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        assert series.policy_error == "ip_renewal_reminder_policy_invalid"
        assert series.next_reminder_at is None and series.reconcile_after
        if legacy_without_series:
            assert (
                series.timezone is None
                and series.cadence_days is None
                and series.delivery_time is None
            )
        config = session.scalar(
            select(IpWorkspaceConfiguration).where(
                IpWorkspaceConfiguration.company_id == actor["company"]["id"]
            )
        )
        config.renewal_reminder_policy_json = {}
        config.version += 1
        session.commit()
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == 1


def test_tracker_foreign_keys_reject_cross_tenant_source_recipient_and_receipt(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from caseops_api.db.models import (
        Company,
        CompanyMembership,
        IpPortfolioRenewalOccurrence,
        IpPortfolioRenewalSeries,
    )
    from caseops_api.services.notification_delivery import enqueue_notification_delivery_intent
    from caseops_api.services.session_context import SessionContext
    from tests.test_ip_workspace_configuration import _bootstrap_tenant

    actor, docket_id = _imported(client, monkeypatch)
    other = _bootstrap_tenant(client, slug="other-structural", email="owner@otherstructural.in")
    with get_session_factory()() as session:
        series = session.scalar(
            select(IpPortfolioRenewalSeries).where(IpPortfolioRenewalSeries.docket_id == docket_id)
        )
        for changes in (
            {"company_id": other["company"]["id"]},
            {"recipient_membership_id": other["membership"]["id"]},
            {"source_version": 999999},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    IpPortfolioRenewalOccurrence(
                        company_id=series.company_id,
                        docket_id=docket_id,
                        series_id=series.id,
                        generation=100,
                        source_version=series.source_version,
                        recipient_membership_id=series.recipient_membership_id,
                        due_on=series.due_on,
                        local_on=series.start_on,
                        scheduled_for=datetime.now(UTC),
                    )
                )
                occurrence = next(
                    row for row in session.new if isinstance(row, IpPortfolioRenewalOccurrence)
                )
                for key, value in changes.items():
                    setattr(occurrence, key, value)
                session.flush()
        membership = session.get(CompanyMembership, other["membership"]["id"])
        context = SessionContext(
            company=session.get(Company, other["company"]["id"]),
            membership=membership,
            user=membership.user,
        )
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel="in_app",
            event_type="structural_fixture",
            source_type="fixture",
            source_id="other-tenant",
            title="Tenant receipt fixture",
            body="Structural integrity only",
        )
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            series.last_delivery_key = intent.idempotency_key
            session.flush()
