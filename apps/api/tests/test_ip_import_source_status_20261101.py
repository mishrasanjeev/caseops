"""B4-ADJ-11: a portfolio import's Status column sets the real filing phase.

Before, every imported application was created in ``draft`` whatever the
source said, so a registered portfolio read Draft. The import now maps the
Status cell through a validated vocabulary to the phase the interactive
create command can set (two-path write parity), keeps later legal milestones
(registered, objected, ...) as the declared, unverified source status, and
refuses what it cannot read at the field instead of guessing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import NotificationDeliveryIntent, TrademarkApplication
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_renewals
from caseops_api.services.ip_imports import source_status_key
from tests.test_ip_manual_application_workflow import _payload as manual_payload
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload

HEADERS = ["Trademark", "Application No.", "Class", "Applicant", "Status", "Renewal Due Date"]


def _row(mark: str, number: str, status: str, renewal: str = "") -> list[str]:
    return [mark, number, "9", "Source Owner LLP", status, renewal]


def test_source_status_vocabulary_is_explicit() -> None:
    assert source_status_key("Registered") == "registered"
    assert source_status_key("  ACCEPTED & ADVERTISED ") == "advertised"
    assert source_status_key("Formalities Chk Pass") == "formalities"
    assert source_status_key("Pre-filing") == "pre_filing"
    assert source_status_key("Regsitered") is None
    assert source_status_key("Maybe") is None


def test_import_maps_status_to_phase_and_keeps_declared_status(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(ip_renewals, "_now", lambda: datetime(2030, 1, 1, tzinfo=UTC))
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        HEADERS,
        [
            _row("REGISTERED MARK", "TM/ADJ11/1", "Registered", "31/03/2030"),
            _row("FILED MARK", "TM/ADJ11/2", "Filed"),
            _row("OBJECTED MARK", "TM/ADJ11/3", "Objected"),
            _row("PREFILING MARK", "", "Pre-filing"),
            _row("DRAFT MARK", "", "Draft"),
            _row("NO STATUS MARK", "", "N/A"),
            _row("ABANDONED MARK", "TM/ADJ11/4", "Abandoned", "31/03/2030"),
        ],
    )
    rows = preview["rows"]
    assert [row["validation_status"] for row in rows] == ["valid"] * 7
    assert [row["normalized"].get("filing_phase") for row in rows] == [
        "filed",
        "filed",
        "filed",
        "pre_filing",
        "draft",
        None,
        "filed",
    ]
    assert rows[0]["normalized"]["declared_status"] == "registered"
    assert {"field": "source_status", "code": "declared_status_unverified"} in rows[0][
        "normalized"
    ]["_warnings"]
    assert {"field": "source_status", "code": "terminal_status_no_alert"} in rows[6][
        "normalized"
    ]["_warnings"]
    mapping = {item["source"]: item for item in rows[0]["normalized"]["_column_mapping"]}
    assert mapping["Status"] == {
        "source": "Status",
        "target": "source_status",
        "handling": "canonical",
    }

    saved = _commit(client, actor, preview, key="adj11-status-import-0001")
    assert saved["job"]["status"] == "committed", saved
    assert saved["job"]["committed_rows"] == 7
    docket_ids = [row["created_docket_id"] for row in saved["rows"]]
    with get_session_factory()() as session:
        phases = {
            row.docket_id: row.filing_phase
            for row in session.scalars(
                select(TrademarkApplication).where(
                    TrademarkApplication.docket_id.in_(docket_ids)
                )
            )
        }
        intents = list(session.scalars(select(NotificationDeliveryIntent)))
    assert [phases[docket_id] for docket_id in docket_ids] == [
        "filed",
        "filed",
        "filed",
        "pre_filing",
        "draft",
        "draft",
        "filed",
    ]
    # The registered mark keeps its renewal alert; the abandoned one gets none.
    assert len(intents) == 1
    assert saved["rows"][0]["normalized"]["_renewal_reminder"]["status"] != "not_scheduled"
    assert saved["rows"][6]["normalized"]["_renewal_reminder"]["status"] == "not_scheduled"

    portfolio = client.get("/api/ip/portfolio", headers=actor["headers"], params={"limit": 50})
    assert portfolio.status_code == 200, portfolio.text
    by_docket = {row["docket_id"]: row for row in portfolio.json()["rows"]}
    registered = by_docket[docket_ids[0]]
    assert registered["filing_phase"] == "filed"
    assert registered["source_declared_status"] == "registered"
    assert by_docket[docket_ids[4]]["source_declared_status"] == "draft"
    assert by_docket[docket_ids[5]]["source_declared_status"] is None


def test_import_refuses_unreadable_status_and_filed_status_without_number(
    client: TestClient,
) -> None:
    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        HEADERS,
        [
            _row("TYPO MARK", "TM/ADJ11/9", "Regsitered"),
            _row("NUMBERLESS MARK", "", "Registered"),
        ],
    )
    typo, numberless = preview["rows"]
    assert typo["validation_status"] == "invalid"
    assert {"field": "source_status", "code": "unsupported_status"} in typo["errors"]
    assert numberless["validation_status"] == "invalid"
    assert {"field": "application_number", "code": "required_for_source_status"} in numberless[
        "errors"
    ]
    refused = client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=actor["headers"],
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": "adj11-status-refusal-0001",
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_import_no_eligible_rows"
    with get_session_factory()() as session:
        assert session.scalar(select(TrademarkApplication.id)) is None


def test_two_path_parity_with_the_interactive_create_command(client: TestClient) -> None:
    """What the manual create command accepts, the import accepts; and both
    refuse a filed phase without an application number."""

    actor = _actor(client)
    headers = actor["headers"]
    manual = "/api/ip/trademark-applications/manual"
    for phase, number in (("filed", "TM/PARITY/1"), ("pre_filing", None)):
        payload = manual_payload(number=number)
        payload["filing_phase"] = phase
        created = client.post(manual, headers=headers, json=payload)
        assert created.status_code == 201, created.text
        assert created.json()["application"]["filing_phase"] == phase
    refused = manual_payload(number=None)
    refused["filing_phase"] = "filed"
    interactive = client.post(manual, headers=headers, json=refused)
    assert interactive.status_code == 409, interactive.text

    preview = _upload(
        client,
        actor,
        HEADERS,
        [
            _row("PARITY FILED", "TM/PARITY/2", "Filed"),
            _row("PARITY PREFILING", "", "Pre-filing"),
            _row("PARITY REFUSED", "", "Filed"),
        ],
    )
    assert [row["validation_status"] for row in preview["rows"]] == ["valid", "valid", "invalid"]
    saved = _commit(client, actor, preview, key="adj11-status-parity-0001")
    docket_ids = [row["created_docket_id"] for row in saved["rows"][:2]]
    with get_session_factory()() as session:
        phases = [
            session.scalar(
                select(TrademarkApplication.filing_phase).where(
                    TrademarkApplication.docket_id == docket_id
                )
            )
            for docket_id in docket_ids
        ]
    assert phases == ["filed", "pre_filing"]


def test_import_phase_stays_tenant_scoped(client: TestClient) -> None:
    actor = _actor(client)
    preview = _upload(client, actor, HEADERS, [_row("TENANT MARK", "TM/ADJ11/T", "Registered")])
    saved = _commit(client, actor, preview, key="adj11-status-tenant-0001")
    docket_id = saved["rows"][0]["created_docket_id"]
    with TestClient(client.app) as other_client:
        other = other_client.post(
            "/api/bootstrap/company",
            json={
                "company_name": "Other Import LLP",
                "company_slug": "other-import-adj11",
                "company_type": "law_firm",
                "owner_full_name": "Other Owner",
                "owner_email": "owner@other-import.example",
                "owner_password": "OtherFounder123!",
            },
        )
        assert other.status_code == 200, other.text
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        foreign = other_client.get(f"/api/ip/dockets/{docket_id}", headers=other_headers)
        assert foreign.status_code == 404, foreign.text
        listed = other_client.get("/api/ip/portfolio", headers=other_headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["rows"] == []
