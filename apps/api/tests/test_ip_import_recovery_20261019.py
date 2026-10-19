"""BUG-008 / UJ-02: saved original rows, context fences and draft-only notes."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from caseops_api.db.models import IpImportRow, TrademarkApplication
from caseops_api.db.session import get_session_factory
from tests.test_ip_portfolio_spec_20261013 import _actor, _commit, _upload


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def import_client(request):
    return request.getfixturevalue(request.param)


def _configure(client, actor, jurisdictions, offices):
    response = client.get("/api/ip/workspace/configuration", headers=actor["headers"])
    assert response.status_code == 200, response.text
    current = response.json()["configuration"]
    response = client.put(
        "/api/ip/workspace/configuration",
        headers=actor["headers"],
        json={
            "expected_version": current["version"] if current else None,
            "enabled_asset_types": ["trademark"],
            "jurisdictions": jurisdictions,
            "offices": offices,
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
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("context", ["absent", "ambiguous"])
def test_saved_original_revalidation_requires_unique_context_and_preserves_source(
    import_client, context
):
    client = import_client
    actor = _actor(client, configure=False)
    if context == "ambiguous":
        _configure(client, actor, ["IN", "US"], ["IP India", "USPTO"])
    columns = ["Trademark", "Application No.", "Trademark Image", "Jurisdiction", "Office"]
    source = [
        ["Synthetic recovery", "RECOVERY/19", "synthetic-image-reference", "", ""],
        ["Synthetic explicit", "EXPLICIT/19", "", "US", "USPTO"],
        ["", "", "", "", ""],
    ]
    blocked = _upload(client, actor, columns, source)
    row = blocked["rows"][0]
    assert row["validation_status"] == "invalid"
    assert row["errors"] == [
        {"field": "jurisdiction", "code": "workspace_context_required"},
        {"field": "office", "code": "workspace_context_required"},
    ]
    assert "jurisdiction" not in row["normalized"] and "office" not in row["normalized"]
    assert blocked["rows"][1]["validation_status"] == "valid"
    assert blocked["rows"][2]["errors"] == [{"field": "row", "code": "blank_row"}]
    path = f"/api/ip/imports/{blocked['job']['id']}"
    with get_session_factory()() as session:
        originals = deepcopy(list(session.scalars(select(IpImportRow.raw_json).where(
            IpImportRow.job_id == blocked["job"]["id"]
        ).order_by(IpImportRow.row_number))))
    assert originals == [dict(zip(columns, values, strict=True)) for values in source]
    unchanged = client.post(f"{path}/revalidate", headers=actor["headers"])
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["rows"][0]["errors"] == row["errors"]
    assert client.get("/api/ip/dockets", headers=actor["headers"]).json()["count"] == 0

    # Legitimate tenant configuration changes; never invent facts in the source.
    _configure(client, actor, ["IN"], ["IP India"])
    response = client.post(f"{path}/revalidate", headers=actor["headers"])
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["job"]["source_sha256"] == blocked["job"]["source_sha256"]
    assert refreshed["job"]["version"] > blocked["job"]["version"]
    assert refreshed["job"]["preview_token"] != blocked["job"]["preview_token"]
    assert refreshed["job"]["valid_rows"] == 2 and refreshed["job"]["invalid_rows"] == 1
    for index, values in enumerate(originals):
        assert refreshed["rows"][index]["normalized"]["_source_values"] == values
    normalized = refreshed["rows"][0]["normalized"]
    assert normalized["jurisdiction"] == "IN" and normalized["office"] == "IP India"
    assert {"field": "specification", "code": "source_incomplete_draft"} in normalized["_warnings"]
    assert {"field": "image_reference", "code": "source_reference_only"} in normalized["_warnings"]
    assert "specification" not in normalized
    assert refreshed["rows"][0]["errors"] == []
    assert refreshed["rows"][1]["normalized"]["jurisdiction"] == "US"
    assert refreshed["rows"][1]["normalized"]["office"] == "USPTO"
    saved = _commit(client, actor, refreshed, "recovered-source-19")
    assert saved["job"]["committed_rows"] == 2 and saved["job"]["failed_rows"] == 0
    assert saved["rows"][2]["commit_status"] == "skipped"
    for row in saved["rows"][:2]:
        response = client.get(
            f"/api/ip/dockets/{row['created_docket_id']}", headers=actor["headers"]
        )
        assert response.status_code == 200, response.text
        docket = response.json()
        assert docket["status"] == "draft"
        assert docket["current_particulars"]["readiness_status"] == "incomplete"
        assert docket["current_particulars"]["classes_json"] == []
        with get_session_factory()() as session:
            application = session.scalar(select(TrademarkApplication).where(
                TrademarkApplication.docket_id == row["created_docket_id"]
            ))
            assert application.jurisdiction == row["normalized"]["jurisdiction"]
            assert application.office == row["normalized"]["office"]
    replay = client.post(f"{path}/commit", headers=actor["headers"], json={
        "preview_token": refreshed["job"]["preview_token"],
        "idempotency_key": "recovered-source-19",
    })
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] and replay.json()["rows"] == saved["rows"]
    duplicate = _upload(client, actor, columns, source)
    skipped = _commit(client, actor, duplicate, "duplicates-only-19")
    assert skipped["job"]["committed_rows"] == 0
    assert [row["commit_error_code"] for row in skipped["rows"][:2]] == ["duplicate_skipped"] * 2
    assert all(row["created_docket_id"] is None for row in skipped["rows"])
    assert client.get("/api/ip/dockets", headers=actor["headers"]).json()["count"] == 2
    with get_session_factory()() as session:
        assert list(session.scalars(select(IpImportRow.raw_json).where(
            IpImportRow.job_id == blocked["job"]["id"]
        ).order_by(IpImportRow.row_number))) == originals
