from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from caseops_api.services.matter_bulk_updates import HEADERS
from tests.test_auth_company import auth_headers, bootstrap_company

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_bulk_update_previews_and_applies_existing_matter_only(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Original bulk title",
            "matter_code": "BULK-UPDATE-1",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert matter_response.status_code == 200, matter_response.text

    values = [""] * len(HEADERS)
    values[0] = "Updated bulk title"
    values[1] = "BULK-UPDATE-1"
    values[5] = "Updated from the reviewed workbook"
    invalid = [""] * len(HEADERS)
    invalid[0] = "Must not be created"
    invalid[1] = "DOES-NOT-EXIST"
    content = _workbook_bytes([values, invalid])

    preview_response = client.post(
        "/api/matters/bulk-update/preview",
        headers=auth_headers(token),
        files={"file": ("updates.xlsx", content, XLSX_TYPE)},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["summary"] == {
        "total_rows": 2,
        "matched_rows": 1,
        "changed_rows": 1,
        "unchanged_rows": 0,
        "invalid_rows": 1,
    }

    apply_response = client.post(
        "/api/matters/bulk-update/apply",
        headers=auth_headers(token),
        data={"preview_token": preview["preview_token"]},
        files={"file": ("updates.xlsx", content, XLSX_TYPE)},
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["applied_rows"] == 1
    assert apply_response.json()["failed_rows"] == 0

    updated = client.get(
        f"/api/matters/{matter_response.json()['id']}",
        headers=auth_headers(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Updated bulk title"
    assert updated.json()["description"] == "Updated from the reviewed workbook"


def test_bulk_update_cannot_change_lifecycle_status(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Lifecycle bulk matter",
            "matter_code": "BULK-LIFECYCLE-1",
            "practice_area": "Civil",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    values = [""] * len(HEADERS)
    values[1] = "BULK-LIFECYCLE-1"
    values[4] = "Disposed"
    response = client.post(
        "/api/matters/bulk-update/preview",
        headers=auth_headers(token),
        files={"file": ("updates.xlsx", _workbook_bytes([values]), XLSX_TYPE)},
    )
    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["status"] == "invalid"
    assert "dedicated lifecycle workflow" in row["errors"][0]
