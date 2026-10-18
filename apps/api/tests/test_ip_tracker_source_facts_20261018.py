"""Current-date SQL projection must retain the existing source-reader fences."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select

from caseops_api.db.models import AuditEvent, IpDocketRecord, IpTrademarkParticularVersion
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.ip_portfolio_dates import current_date_facts, current_dates
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload
from tests.test_ip_renewal_tracker_20261015 import _clock


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def source_client(request):
    return request.getfixturevalue(request.param)


def test_staged_dates_preserve_validation_manual_precedence_and_exact_provenance(
    source_client, monkeypatch
):
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(source_client)
    raw_dates = (
        "2028-02-29",
        "2027-02-29",
        "2000-02-29",
        "1900-02-29",
        "0000-01-01",
        "0001-01-01",
        "9999-12-31",
        "2028-13-01",
        "2028-00-01",
        "2028-04-31",
        "2028-01-00",
        "2028-xx-01",
        "2028-1-01",
        "2028-01-01-extra",
        None,
    )
    variants = len(raw_dates) + 5
    preview = _upload(
        source_client,
        actor,
        ["Trademark", "Application Date", "Renewal Date"],
        [[f"IP18 date fence {index}", "2020-01-15", "2028-03-15"] for index in range(variants)],
    )
    committed = _commit(source_client, actor, preview)
    ids = [row["created_docket_id"] for row in committed["rows"]]
    assert len(ids) == len(set(ids)) == variants and all(ids)
    company_id = actor["company"]["id"]
    revised = source_client.patch(
        f"/api/ip/dockets/{ids[-5]}/portfolio-dates",
        headers=actor["headers"],
        json={
            "expected_current_version": 1,
            "application_date": "2028-02-29",
            "reason": "Current-version source projection control",
        },
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["current_version"] == 2
    with get_session_factory()() as session:
        versions = {
            version.docket_id: version
            for version in session.scalars(
                select(IpTrademarkParticularVersion)
                .join(
                    IpDocketRecord,
                    (IpDocketRecord.id == IpTrademarkParticularVersion.docket_id)
                    & (IpDocketRecord.company_id == IpTrademarkParticularVersion.company_id)
                    & (IpDocketRecord.current_version == IpTrademarkParticularVersion.version),
                )
                .where(
                    IpTrademarkParticularVersion.company_id == company_id,
                    IpDocketRecord.id.in_(ids),
                )
            )
        }
        assert versions[ids[-5]].version == 2
        for docket_id, raw in zip(ids[: len(raw_dates)], raw_dates, strict=True):
            data = deepcopy(versions[docket_id].representation_json)
            data["portfolio_import"]["application_date"] = raw
            data["portfolio_import"]["renewal_due_date"] = raw
            versions[docket_id].representation_json = data
        manual, cleared, wrong_docket, missing_audit, absent_row = ids[-5:]
        for docket_id, raw in ((manual, "2028-02-29"), (cleared, None)):
            data = deepcopy(versions[docket_id].representation_json)
            data["portfolio_dates"] = {
                field: {"origin": "manual", "value": raw}
                for field in ("application_date", "renewal_due_date")
            }
            versions[docket_id].representation_json = data
        for docket_id, source_id in (
            (
                wrong_docket,
                versions[ids[0]].representation_json["portfolio_import"]["source_row_id"],
            ),
            (absent_row, str(uuid4())),
        ):
            data = deepcopy(versions[docket_id].representation_json)
            data["portfolio_import"]["source_row_id"] = source_id
            versions[docket_id].representation_json = data
        session.execute(
            delete(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.ip_docket_id == missing_audit,
                AuditEvent.action == "ip_docket.source_materialized",
            )
        )
        session.commit()
        candidates = select(IpDocketRecord.id).where(
            IpDocketRecord.company_id == company_id, IpDocketRecord.id.in_(ids)
        )
        facts = current_date_facts(candidates, company_id=company_id)
        projected = {row.docket_id: row for row in session.execute(select(facts))}
        assert set(projected) == set(ids)
        for docket_id, version in versions.items():
            expected = current_dates(session, version=version, docket_id=docket_id)
            actual = projected[docket_id]
            for column, field in (
                ("application_on", "source_application_on"),
                ("renewal_due_on", "source_renewal_due_on"),
            ):
                value = expected[field]
                assert getattr(actual, column) == (value.isoformat() if value else None)
            assert actual.version_id == version.id
        for docket_id in (wrong_docket, missing_audit, absent_row):
            assert projected[docket_id].import_proven is False
            assert projected[docket_id].application_on is None
            assert projected[docket_id].renewal_due_on is None
        assert projected[manual].application_on == "2028-02-29"
        assert projected[cleared].application_on is None
        assert projected[ids[0]].import_proven is True

        excluded = current_date_facts(
            candidates.where(IpDocketRecord.id != ids[0]), company_id=company_id
        )
        assert {row.docket_id for row in session.execute(select(excluded))} == set(ids[1:])
        foreign = current_date_facts(candidates, company_id=str(uuid4()))
        assert session.execute(select(foreign)).all() == []


def test_portfolio_date_facts_keep_broader_party_search_and_fresh_export_access(
    source_client, monkeypatch
):
    client = source_client
    _clock(monkeypatch, datetime(2028, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    run = uuid4().hex
    party = f"IP18 sole proprietor {run}"
    committed = _commit(
        client,
        actor,
        _upload(
            client,
            actor,
            ["Trademark", "Applicant Name(s)", "Application Date", "Renewal Due Date"],
            [
                [f"Independent public title {run}", party, "2020-01-15", "2028-03-15"],
                [f"Independent secret title {run}", party, "2020-01-15", "2028-03-15"],
            ],
        ),
    )
    public_id, secret_id = [row["created_docket_id"] for row in committed["rows"]]
    assert public_id and secret_id and public_id != secret_id
    filters = {
        "query": party,
        "application_date_from": "2020-01-01",
        "application_date_to": "2020-12-31",
        "renewal_tracker_state": ["upcoming"],
    }
    company_id = actor["company"]["id"]
    measured = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "from audit_events" in lowered and "from ip_import_rows" in lowered:
            measured.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        owner = client.get("/api/ip/portfolio", headers=actor["headers"], params=filters)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert owner.status_code == 200, owner.text
    assert owner.json()["counts"]["total"] == 2
    with get_session_factory()() as session:
        secret = session.get(IpDocketRecord, secret_id)
        assert secret.company_id == company_id
        secret.restricted = True
        session.commit()
    tracker = client.get(
        "/api/ip/portfolio/renewal-tracker", headers=actor["headers"], params={"query": party}
    )
    assert tracker.status_code == 200, tracker.text
    assert tracker.json()["rows"] == [], "Party-only search must remain portfolio-specific."
    email = f"ip18-scope-{run}@ip18source.in"
    member = client.post(
        "/api/companies/current/users",
        headers=actor["headers"],
        json={
            "full_name": "IP18 scope member",
            "email": email,
            "password": "SyntheticScope123!",
            "role": "admin",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "SyntheticScope123!",
            "company_slug": actor["company"]["slug"],
        },
    )
    assert login.status_code == 200, login.text
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    client.cookies.clear()
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["membership"]["id"] == member.json()["membership_id"]
    listing = client.get("/api/ip/portfolio", headers=headers, params=filters)
    assert listing.status_code == 200, listing.text
    assert listing.json()["counts"]["total"] == 1
    assert [row["docket_id"] for row in listing.json()["rows"]] == [public_id]
    assert secret_id not in listing.text
    tracker_filters = {
        "application_date_from": "2020-01-01",
        "application_date_to": "2020-12-31",
    }
    scoped_tracker = client.get(
        "/api/ip/portfolio/renewal-tracker", headers=headers, params=tracker_filters
    )
    assert scoped_tracker.status_code == 200, scoped_tracker.text
    assert [row["docket_id"] for row in scoped_tracker.json()["rows"]] == [public_id]
    assert scoped_tracker.json()["counts"] == {
        "upcoming": 1,
        "active": 0,
        "due_today": 0,
        "overdue": 0,
        "missing": 0,
        "failed": 0,
    }
    assert secret_id not in scoped_tracker.text
    families = client.get(
        "/api/ip/portfolio/families", headers=headers, params={**filters, "grouping": "mark"}
    )
    assert families.status_code == 200, families.text
    assert [
        row["docket_id"] for family in families.json()["families"] for row in family["members"]
    ] == [public_id]
    payload = {"filters": filters, "columns": ["mark", "application_date"], "row_limit": 50000}
    preview = client.post("/api/ip/portfolio/exports/preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 1 and preview.json()["truncated"] is False
    with get_session_factory()() as session:
        public = session.get(IpDocketRecord, public_id)
        assert public.company_id == company_id
        public.restricted = True
        session.commit()
    stale = client.post(
        "/api/ip/portfolio/exports",
        headers=headers,
        json={**payload, "preview_token": preview.json()["preview_token"]},
    )
    assert stale.status_code == 409, stale.text
    fresh = client.post("/api/ip/portfolio/exports/preview", headers=headers, json=payload)
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["row_count"] == 0
    revoked_tracker = client.get(
        "/api/ip/portfolio/renewal-tracker", headers=headers, params=tracker_filters
    )
    assert revoked_tracker.status_code == 200, revoked_tracker.text
    assert revoked_tracker.json()["rows"] == []
    assert all(count == 0 for count in revoked_tracker.json()["counts"].values())
    assert measured, "The dated portfolio scope must execute its source-proof SQL."
    shapes = [
        (
            len(sql.encode()),
            sql.lower().count("from audit_events"),
            sql.lower().count("from ip_import_rows"),
        )
        for sql in measured
    ]
    assert all(
        size <= 65_536 and audit <= 2 and imported <= 2 for size, audit, imported in shapes
    ), shapes
