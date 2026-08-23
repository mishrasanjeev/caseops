"""IPLF-030B portfolio workflow, saved-view and export proof."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    IpDocketEvent,
    IpDocketRecord,
    IpPortfolioExportJob,
    Team,
    TeamMembership,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_portfolio_listing import _application, _asset, _portfolio


def _identifier(
    client: TestClient,
    headers: dict[str, str],
    *,
    docket_id: str,
    kind: str,
    value: str,
    application_id: str | None = None,
    proceeding_id: str | None = None,
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/identifiers",
        headers=headers,
        json={
            "identifier_kind": kind,
            "raw_value": value,
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "source": "registry_fixture",
            "effective_from": "2026-08-21",
            "is_primary": True,
            "application_id": application_id,
            "proceeding_id": proceeding_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["identifier"]


def _rich_portfolio_fixture(client: TestClient) -> tuple[dict[str, str], dict, dict]:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-PORT-030B")
    docket_response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Aster Device Mark",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": {
                "form_key": "TM-A",
                "form_version": "2026.1",
                "mark_kind": "device",
                "representation": {
                    "document_reference": "document:device-mark",
                    "evidence_reference": "filing-manifest:device-mark",
                },
                "classes": [
                    {
                        "class_number": 9,
                        "specification": "Downloadable legal workflow software",
                    }
                ],
                "use_priority": None,
                "parties": [
                    {"role": "applicant", "name": "Aster Products Private Limited"}
                ],
                "agent": {"name": "Rao Trademark Agents"},
                "filing_manifest": [
                    {
                        "key": "representation",
                        "label": "Mark representation",
                        "required": True,
                        "evidence_reference": "filing-manifest:device-mark",
                    }
                ],
            },
        },
    )
    assert docket_response.status_code == 201, docket_response.text
    docket = docket_response.json()
    asset = _asset(client, headers, docket_id=docket["id"], title="Aster Device")
    application = _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset["id"],
    )
    _identifier(
        client,
        headers,
        docket_id=docket["id"],
        kind="application",
        value="TM / 2026 / 00421",
        application_id=application["id"],
    )
    filed = client.patch(
        f"/api/ip/applications/{application['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 1, "filing_phase": "filed"},
    )
    assert filed.status_code == 200, filed.text
    proceeding_response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "stage": "draft",
        },
    )
    assert proceeding_response.status_code == 201, proceeding_response.text
    _identifier(
        client,
        headers,
        docket_id=docket["id"],
        kind="opposition",
        value="OPP / 88 / 2026",
        proceeding_id=proceeding_response.json()["id"],
    )

    return headers, docket, application


def test_uj04_normal_exact_identifier_lookup_and_register_depth(
    client: TestClient,
) -> None:
    """IPLF-UJ-04-NORMAL: either registry number reaches the enriched row."""

    headers, docket, application = _rich_portfolio_fixture(client)
    for query in ("tm-2026-00421", "opp 88 2026"):
        response = _portfolio(client, headers, query=query)
        assert response.status_code == 200, response.text
        assert [row["application_id"] for row in response.json()["rows"]] == [application["id"]]

    row = _portfolio(client, headers, query="OPP/88/2026").json()["rows"][0]
    assert row["docket_id"] == docket["id"]
    assert row["primary_identifier"] == "TM / 2026 / 00421"
    assert row["application_numbers"] == ["TM / 2026 / 00421"]
    assert row["opposition_numbers"] == ["OPP / 88 / 2026"]
    assert row["nice_classes"] == [9]
    assert row["goods_services"] == ["Downloadable legal workflow software"]
    assert row["representation_kinds"] == ["device"]
    assert row["proprietors"] == ["Aster Products Private Limited"]
    assert row["agents"] == ["Rao Trademark Agents"]
    assert row["registry_sync_state"] == "unavailable"
    assert "Identifier: registry_fixture" in row["provenance"]
    assert "Docket particulars: version 1" in row["provenance"]


def test_portfolio_counts_cover_filter_scope_not_only_current_page(
    client: TestClient,
) -> None:
    headers, docket, _application_row = _rich_portfolio_fixture(client)
    asset_id = _portfolio(client, headers).json()["rows"][0]["asset_id"]
    _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset_id,
        office="UKIPO",
        jurisdiction="GB",
        filing_phase="draft",
    )
    response = _portfolio(client, headers, limit=1)
    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == 1
    assert response.json()["counts"]["total"] == 2
    assert response.json()["next_cursor"] is not None


def test_portfolio_filters_and_stale_registry_state_use_canonical_owners(
    client: TestClient,
) -> None:
    headers, docket, application = _rich_portfolio_fixture(client)
    with get_session_factory()() as session:
        docket_row = session.get(IpDocketRecord, docket["id"])
        assert docket_row is not None and docket_row.created_by_membership_id
        created_by = docket_row.created_by_membership_id
        session.add(
            IpDocketEvent(
                company_id=docket_row.company_id,
                docket_id=docket["id"],
                sequence=1,
                application_id=application["id"],
                event_kind="registry_snapshot_accepted",
                source="registry_sync",
                source_reference="registry-fixture:stale",
                effective_at=datetime.now(UTC) - timedelta(days=3),
                entered_at=datetime.now(UTC) - timedelta(days=3),
                responsible_membership_id=created_by,
                entered_by_membership_id=created_by,
                candidate_status="confirmed",
            )
        )
        session.commit()

    response = _portfolio(
        client,
        headers,
        proprietor=["Aster Products Private Limited"],
        nice_class=[9],
        opposition_only=True,
        registry_sync_state=["stale"],
    )
    assert response.status_code == 200, response.text
    assert [row["application_id"] for row in response.json()["rows"]] == [application["id"]]
    assert response.json()["rows"][0]["registry_sync_state"] == "stale"
    assert response.json()["counts"]["stale_sync_records"] == 1
    assert response.json()["counts"]["sync_failure_records"] is None


def test_saved_views_are_personal_versioned_and_audited(client: TestClient) -> None:
    headers, docket_row, _application_row = _rich_portfolio_fixture(client)
    created = client.post(
        "/api/ip/portfolio/views",
        headers=headers,
        json={
            "name": "India filings",
            "filters": {"jurisdiction": ["IN"], "filing_phase": ["filed"]},
            "columns": ["mark", "application_numbers", "classes", "status"],
            "is_default": True,
        },
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["version"] == 1
    assert view["is_default"] is True

    duplicate = client.post(
        "/api/ip/portfolio/views",
        headers=headers,
        json={"name": "India filings", "filters": {}, "columns": ["mark"]},
    )
    assert duplicate.status_code == 409

    stale = client.put(
        f"/api/ip/portfolio/views/{view['id']}",
        headers=headers,
        json={
            "name": "India filed marks",
            "filters": {"jurisdiction": ["IN"]},
            "columns": ["mark", "status"],
            "is_default": True,
            "expected_version": 99,
        },
    )
    assert stale.status_code == 409

    updated = client.put(
        f"/api/ip/portfolio/views/{view['id']}",
        headers=headers,
        json={
            "name": "India filed marks",
            "filters": {"jurisdiction": ["IN"]},
            "columns": ["mark", "status"],
            "is_default": True,
            "expected_version": 1,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    listed = client.get("/api/ip/portfolio/views", headers=headers)
    assert [row["name"] for row in listed.json()["views"]] == ["India filed marks"]

    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_row["id"])
        assert docket is not None and docket.created_by_membership_id
        team = Team(
            company_id=docket.company_id,
            name="Trademark prosecution",
            slug="trademark-prosecution",
        )
        session.add(team)
        session.flush()
        session.add(
            TeamMembership(
                team_id=team.id,
                membership_id=docket.created_by_membership_id,
                is_lead=True,
            )
        )
        session.commit()
        team_id = team.id
    team_view = client.post(
        "/api/ip/portfolio/views",
        headers=headers,
        json={
            "name": "Team opposition register",
            "filters": {"opposition_only": True},
            "columns": ["mark", "opposition_numbers", "status"],
            "scope": "team",
            "team_id": team_id,
        },
    )
    assert team_view.status_code == 201, team_view.text
    assert team_view.json()["scope"] == "team"
    assert team_view.json()["team_id"] == team_id
    assert team_view.json()["editable"] is True

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Saved Views Firm",
            "company_slug": "other-saved-views-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "other-saved-view@example.com",
            "owner_password": "OtherSavedView123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    assert client.get("/api/ip/portfolio/views", headers=other_headers).json()["views"] == []


def test_uj04_exc03_export_is_background_access_scoped_and_audited(
    client: TestClient,
) -> None:
    headers, _docket_row, _application_row = _rich_portfolio_fixture(client)
    payload = {
        "format": "csv",
        "filters": {"jurisdiction": ["IN"]},
        "columns": [
            "mark",
            "application_numbers",
            "opposition_numbers",
            "provenance",
        ],
        "row_limit": 50000,
    }
    preview = client.post(
        "/api/ip/portfolio/exports/preview",
        headers=headers,
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 1
    assert preview.json()["omitted_restricted_count"] is None
    tampered = client.post(
        "/api/ip/portfolio/exports",
        headers=headers,
        json={
            **payload,
            "filters": {"jurisdiction": ["GB"]},
            "preview_token": preview.json()["preview_token"],
        },
    )
    assert tampered.status_code == 409
    response = client.post(
        "/api/ip/portfolio/exports",
        headers=headers,
        json={**payload, "preview_token": preview.json()["preview_token"]},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    completed = client.get(f"/api/ip/portfolio/exports/{job_id}", headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["row_count"] == 1
    assert completed.json()["download_ready"] is True

    download = client.get(
        f"/api/ip/portfolio/exports/{job_id}/download",
        headers=headers,
    )
    assert download.status_code == 200, download.text
    assert download.headers["cache-control"] == "private, no-store"
    text = download.content.decode("utf-8-sig")
    assert "Application numbers" in text
    assert "TM / 2026 / 00421" in text
    assert "OPP / 88 / 2026" in text
    assert "CaseOps legal record" in text

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Export Firm",
            "company_slug": "other-export-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Export Owner",
            "owner_email": "other-export@example.com",
            "owner_password": "OtherExport123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    assert (
        client.get(f"/api/ip/portfolio/exports/{job_id}", headers=other_headers).status_code == 404
    )

    with get_session_factory()() as session:
        job = session.get(IpPortfolioExportJob, job_id)
        assert job is not None
        job.status = "failed"
        job.error = "temporary worker failure"
        session.commit()
    retried = client.post(
        f"/api/ip/portfolio/exports/{job_id}/retry",
        headers=headers,
    )
    assert retried.status_code == 202, retried.text
    assert (
        client.get(f"/api/ip/portfolio/exports/{job_id}", headers=headers).json()["status"]
        == "completed"
    )

    with get_session_factory()() as session:
        actions = set(session.scalars(select(AuditEvent.action)).all())
    assert {
        "ip_portfolio.export.enqueued",
        "ip_portfolio.export.completed",
        "ip_portfolio.export.downloaded",
        "ip_portfolio.export.previewed",
        "ip_portfolio.export.retry_enqueued",
    }.issubset(actions)
