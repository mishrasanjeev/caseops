"""B4-ADJ-11: a portfolio import's Status column sets the real filing phase.

Before, every imported application was created in ``draft`` whatever the
source said, so a registered portfolio read Draft. The import now maps the
Status cell through a validated vocabulary to the phase the interactive
create command can set (two-path write parity), keeps later legal milestones
(registered, objected, ...) as the declared, unverified source status, and
shows that source wording as the mark's headline status, marked unverified.
Wording it does not recognise never blocks a row that imported before: the
row imports in the draft phase with a warning and its wording kept.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    IpDocketRecord,
    IpTrademarkParticularVersion,
    NotificationDeliveryIntent,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_portfolio import IpPortfolioRow
from caseops_api.services import ip_renewals
from caseops_api.services.ip_imports import source_status_key
from caseops_api.services.ip_portfolio_workflow import EXPORT_COLUMNS, portfolio_status_text
from tests.test_ip_manual_application_workflow import _payload as manual_payload
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload

HEADERS = ["Trademark", "Application No.", "Class", "Applicant", "Status", "Renewal Due Date"]


def _row(mark: str, number: str, status: str, renewal: str = "") -> list[str]:
    return [mark, number, "9", "Source Owner LLP", status, renewal]


def _status(row: dict) -> str:
    return portfolio_status_text(IpPortfolioRow.model_validate(row))


def test_source_status_vocabulary_is_explicit() -> None:
    assert source_status_key("Registered") == "registered"
    assert source_status_key("  ACCEPTED & ADVERTISED ") == "advertised"
    assert source_status_key("Formalities Chk Pass") == "formalities"
    assert source_status_key("Pre-filing") == "pre_filing"
    assert source_status_key("Ready for Show Cause Hearing") == "hearing"
    assert source_status_key("Under Objection") == "objected"
    assert source_status_key("Regsitered") is None
    assert source_status_key("Registered (Not In Use)") is None
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
    assert registered["source_status_text"] == "Registered"
    assert by_docket[docket_ids[4]]["source_declared_status"] == "draft"
    assert by_docket[docket_ids[5]]["source_declared_status"] is None
    # The Status column (screen and export) leads with the source wording,
    # marked unverified, never with Draft; the record status is its own column.
    assert [_status(by_docket[docket_id]) for docket_id in docket_ids] == [
        "Registered (source, unverified)",
        "Filed",
        "Objected (source, unverified)",
        "Pre-filing",
        "Draft",
        "Draft",
        "Abandoned (source, unverified)",
    ]
    assert EXPORT_COLUMNS["record_status"][0] == "Record status"
    assert EXPORT_COLUMNS["status"][1](IpPortfolioRow.model_validate(registered)) == (
        "Registered (source, unverified)"
    )
    # The imported particulars still need their source verified, against the
    # registry for a filed mark rather than "before filing".
    docket = client.get(f"/api/ip/dockets/{docket_ids[0]}", headers=actor["headers"]).json()
    assert [item["label"] for item in docket["current_particulars"]["filing_manifest_json"]] == [
        "Verify imported source against the registry record"
    ]
    draft = client.get(f"/api/ip/dockets/{docket_ids[4]}", headers=actor["headers"]).json()
    assert [item["label"] for item in draft["current_particulars"]["filing_manifest_json"]] == [
        "Verify imported source before filing"
    ]


def test_real_registry_status_wording_imports_and_unrecognised_wording_is_kept(
    client: TestClient,
) -> None:
    """Rows that imported before the mapping still import (the bulk path never
    narrows): recognised wording sets the phase, anything else imports as
    draft with a warning and its wording shown as the unverified status."""

    actor = _actor(client)
    preview = _upload(
        client,
        actor,
        HEADERS,
        [
            _row("SHOW CAUSE MARK", "TM/ADJ11/10", "Ready for Show Cause Hearing"),
            _row("OBJECTION MARK", "TM/ADJ11/11", "Under Objection"),
            _row("NOT IN USE MARK", "TM/ADJ11/12", "Registered (Not In Use)"),
            _row("RECTIFICATION MARK", "TM/ADJ11/13", "Rectification Filed"),
            _row("TYPO MARK", "TM/ADJ11/9", "Regsitered"),
        ],
    )
    rows = preview["rows"]
    assert [row["validation_status"] for row in rows] == ["valid"] * 5
    assert [row["normalized"].get("filing_phase") for row in rows] == [
        "filed",
        "filed",
        None,
        None,
        None,
    ]
    for row in rows[2:]:
        assert row["errors"] == []
        assert {"field": "source_status", "code": "unrecognised_status"} in row["normalized"][
            "_warnings"
        ]
    saved = _commit(client, actor, preview, key="adj11-status-registry-0001")
    assert saved["job"]["committed_rows"] == 5
    docket_ids = [row["created_docket_id"] for row in saved["rows"]]
    portfolio = client.get("/api/ip/portfolio", headers=actor["headers"], params={"limit": 50})
    by_docket = {row["docket_id"]: row for row in portfolio.json()["rows"]}
    shown = [
        (
            by_docket[docket_id]["filing_phase"],
            by_docket[docket_id]["source_declared_status"],
            _status(by_docket[docket_id]),
        )
        for docket_id in docket_ids
    ]
    assert shown == [
        ("filed", "hearing", "Ready for Show Cause Hearing (source, unverified)"),
        ("filed", "objected", "Under Objection (source, unverified)"),
        ("draft", None, "Registered (Not In Use) (source, unverified)"),
        ("draft", None, "Rectification Filed (source, unverified)"),
        ("draft", None, "Regsitered (source, unverified)"),
    ]


def test_import_refuses_a_filed_status_without_its_application_number(
    client: TestClient,
) -> None:
    actor = _actor(client)
    preview = _upload(client, actor, HEADERS, [_row("NUMBERLESS MARK", "", "Registered")])
    (numberless,) = preview["rows"]
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


def test_a_registered_mark_imported_before_the_mapping_reads_its_source_status(
    client: TestClient,
) -> None:
    """Production rows imported earlier kept only the wording and the draft phase."""

    actor = _actor(client)
    preview = _upload(client, actor, HEADERS, [_row("LEGACY MARK", "TM/ADJ11/L", "Registered")])
    saved = _commit(client, actor, preview, key="adj11-status-legacy-0001")
    docket_id = saved["rows"][0]["created_docket_id"]
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        assert docket is not None
        version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.docket_id == docket_id,
                IpTrademarkParticularVersion.version == docket.current_version,
            )
        )
        assert version is not None
        representation = dict(version.representation_json)
        imported = dict(representation["portfolio_import"])
        imported.pop("declared_status")
        representation["portfolio_import"] = imported
        version.representation_json = representation
        application = session.scalar(
            select(TrademarkApplication).where(TrademarkApplication.docket_id == docket_id)
        )
        assert application is not None
        application.filing_phase = "draft"
        session.commit()
    portfolio = client.get("/api/ip/portfolio", headers=actor["headers"])
    (row,) = [item for item in portfolio.json()["rows"] if item["docket_id"] == docket_id]
    assert (row["filing_phase"], row["source_declared_status"], row["source_status_text"]) == (
        "draft",
        "registered",
        "Registered",
    )
    assert _status(row) == "Registered (source, unverified)"


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
