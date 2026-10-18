"""Native correlated term selection beside staged current-date facts."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from caseops_api.db.models import (
    IpDeadline,
    IpDocketRecord,
    IpRenewalTerm,
    IpTrademarkParticularVersion,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewal_tracker
from tests.test_ip_renewal_tracker_20261015 import _clock
from tests.test_ip_renewals import _seed_renewal_fixture

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("case", ["later_active", "tied_ambiguous", "later_completed"])
def test_native_current_term_correlates_and_correction_reclaims_exact_current_version(
    isolated_postgres_client, monkeypatch, case
):
    client = isolated_postgres_client
    actor, headers, ids = _seed_renewal_fixture(client)
    headers = {**headers, "X-CaseOps-Automated-Test": "no-paid-providers"}
    now = datetime(2036, 7, 10, 4, tzinfo=UTC)
    _clock(monkeypatch, now)
    with get_session_factory()() as session:
        version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.company_id == actor["company"]["id"],
                IpTrademarkParticularVersion.docket_id == ids["docket"],
                IpTrademarkParticularVersion.version == 1,
            )
        )
        version.representation_json = {
            **version.representation_json,
            "portfolio_dates": {
                "renewal_due_date": {"value": "2036-08-01", "origin": "manual"},
            },
        }
        session.get(IpDeadline, ids["grace"]).result_on = date(2036, 8, 1)
        # A second fact row must not supply the corrected docket's prior date.
        sentinel = IpDocketRecord(
            company_id=actor["company"]["id"],
            record_type="trademark",
            title="Retained source correlation sibling",
            status="draft",
            created_by_membership_id=actor["membership"]["id"],
        )
        session.add(sentinel)
        session.flush()
        sentinel_id = sentinel.id
        session.add(
            IpTrademarkParticularVersion(
                company_id=actor["company"]["id"],
                docket_id=sentinel_id,
                version=1,
                form_key="renewal_fixture",
                form_version="1",
                mark_kind="word",
                representation_json={
                    "text": "Retained sibling",
                    "portfolio_dates": {
                        "renewal_due_date": {"value": "2036-08-01", "origin": "manual"},
                    },
                },
                classes_json=[],
                parties_json=[],
                filing_manifest_json=[],
                readiness_status="draft",
                readiness_errors_json=[],
                created_by_membership_id=actor["membership"]["id"],
            )
        )
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
            session.flush()
        session.commit()
    closed = client.post(
        f"/api/ip/dockets/{sentinel_id}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Retained non-operational source correlation control",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "fixture:retained-source-correlation",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    with get_session_factory()() as session:
        terms = session.scalars(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.company_id == actor["company"]["id"],
                IpRenewalTerm.docket_id == ids["docket"],
            )
            .order_by(IpRenewalTerm.term_sequence, IpRenewalTerm.renewal_deadline_id)
        ).all()
        assert len(terms) == 2
        assert {term.renewal_deadline_id for term in terms} == {ids["renewal"], ids["grace"]}
        assert all(term.registration_event_id == ids["registration"] for term in terms)
        assert [term.term_sequence for term in terms] == (
            [1, 1] if case == "tied_ambiguous" else [1, 2]
        )
        assert ip_renewal_tracker.reconcile_renewal_series(session)["advanced"] == int(
            case == "later_active"
        )
    response = client.get("/api/ip/portfolio/renewal-tracker", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 2 and body["next_cursor"] is None
    row = next(row for row in body["rows"] if row["docket_id"] == ids["docket"])
    sibling = next(row for row in body["rows"] if row["docket_id"] == sentinel_id)
    assert sibling["status"] == "cancelled" and sibling["docket_operational"] is False
    assert sibling["source_renewal_due_on"] == "2036-08-01"
    assert row["docket_id"] == ids["docket"] and row["current_version"] == 1
    assert row["docket_operational"] is True
    assert row["source_renewal_due_on"] == "2036-08-01"
    assert row["source_renewal_state"] == "manual"
    zero = dict.fromkeys(("upcoming", "active", "due_today", "overdue", "missing", "failed"), 0)
    if case == "later_active":
        assert row["status"] == "active" and row["last_error"] is None
        assert body["counts"] == {**zero, "upcoming": 1, "active": 1, "due_today": 1}
    else:
        assert row["status"] == "cancelled" and row["last_error"]
        assert body["counts"] == zero
    edited = client.patch(
        f"/api/ip/dockets/{ids['docket']}/portfolio-dates",
        headers=headers,
        json={
            "expected_current_version": 1,
            "renewal_due_date": "2037-08-01",
            "reason": "Current source correction must not inherit a prior term stop",
        },
    )
    assert edited.status_code == 200, edited.text
    corrected = edited.json()["tracker"]
    assert corrected["current_version"] == 2 and corrected["docket_operational"] is True
    assert corrected["source_renewal_due_on"] == "2037-08-01"
    assert corrected["source_renewal_state"] == "manual"
    assert corrected["status"] == "scheduled" and corrected["last_error"] is None
    fresh = client.get("/api/ip/portfolio/renewal-tracker", headers=headers)
    assert fresh.status_code == 200, fresh.text
    assert len(fresh.json()["rows"]) == 2
    assert (
        next(row for row in fresh.json()["rows"] if row["docket_id"] == ids["docket"]) == corrected
    )
    assert next(row for row in fresh.json()["rows"] if row["docket_id"] == sentinel_id) == sibling
    assert fresh.json()["counts"] == zero
    with get_session_factory()() as session:
        retained = session.scalars(
            select(IpTrademarkParticularVersion)
            .where(IpTrademarkParticularVersion.docket_id == ids["docket"])
            .order_by(IpTrademarkParticularVersion.version)
        ).all()
        assert [version.version for version in retained] == [1, 2]
        assert retained[0].representation_json["portfolio_dates"]["renewal_due_date"]["value"] == (
            "2036-08-01"
        )
