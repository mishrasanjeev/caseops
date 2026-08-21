"""IP-PORT-08 controlled CSV/XLSX import and reconciliation proof."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from tests.test_auth_company import auth_headers, bootstrap_company


def _actor(client: TestClient) -> dict:
    bootstrap = bootstrap_company(client)
    return {
        "headers": auth_headers(str(bootstrap["access_token"])),
        "membership_id": bootstrap["membership"]["id"],
    }


def _csv(mark: str, application_number: str, *, class_number: int = 9) -> bytes:
    return (
        "title,mark,class,applicant,goods/services,application number,jurisdiction,office\n"
        f"{mark},{mark},{class_number},Aster Products LLP,Legal software,"
        f"{application_number},IN,Trade Marks Registry Mumbai\n"
    ).encode()


def _commit(client: TestClient, headers: dict[str, str], preview: dict, key: str):
    return client.post(
        f"/api/ip/imports/{preview['job']['id']}/commit",
        headers=headers,
        json={
            "preview_token": preview["job"]["preview_token"],
            "idempotency_key": key,
        },
    )


def test_ip_port_08_csv_upload_materializes_searchable_portfolio(
    client: TestClient,
) -> None:
    actor = _actor(client)
    staged = client.post(
        "/api/ip/imports/upload",
        headers=actor["headers"],
        files={"file": ("portfolio.csv", _csv("ASTER IMPORT", "TM/2026/9001"), "text/csv")},
    )
    assert staged.status_code == 201, staged.text
    preview = staged.json()
    assert preview["rows"][0]["duplicate_candidates"] == []

    committed = _commit(client, actor["headers"], preview, "csv-import-9001")
    assert committed.status_code == 200, committed.text
    assert committed.json()["job"]["committed_rows"] == 1

    portfolio = client.get(
        "/api/ip/portfolio",
        headers=actor["headers"],
        params={"query": "tm 2026 9001"},
    )
    assert portfolio.status_code == 200, portfolio.text
    row = portfolio.json()["rows"][0]
    assert row["application_numbers"] == ["TM/2026/9001"]
    assert row["nice_classes"] == [9]
    assert row["goods_services"] == ["Legal software"]
    assert row["proprietors"] == ["Aster Products LLP"]


def test_ip_port_08_xlsx_validation_history_and_error_report(client: TestClient) -> None:
    actor = _actor(client)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["title", "mark", "class", "applicant"])
    sheet.append(["INVALID CLASS", "INVALID CLASS", 99, "Aster Products LLP"])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()

    staged = client.post(
        "/api/ip/imports/upload",
        headers=actor["headers"],
        files={
            "file": (
                "portfolio.xlsx",
                stream.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert staged.status_code == 201, staged.text
    preview = staged.json()
    assert preview["job"]["invalid_rows"] == 1
    assert preview["rows"][0]["errors"] == [
        {"field": "class_number", "code": "out_of_range"}
    ]

    history = client.get("/api/ip/imports/history", headers=actor["headers"])
    assert history.status_code == 200, history.text
    assert history.json()["jobs"][0]["id"] == preview["job"]["id"]
    report = client.get(
        f"/api/ip/imports/{preview['job']['id']}/errors",
        headers=actor["headers"],
    )
    assert report.status_code == 200, report.text
    assert report.headers["cache-control"] == "private, no-store"
    assert "class_number:out_of_range" in report.content.decode("utf-8-sig")


def test_ip_port_08_duplicate_requires_audited_reconciliation(client: TestClient) -> None:
    actor = _actor(client)
    first = client.post(
        "/api/ip/imports/upload",
        headers=actor["headers"],
        files={"file": ("first.csv", _csv("ASTER DUP", "TM/2026/9002"), "text/csv")},
    ).json()
    assert _commit(client, actor["headers"], first, "duplicate-source-9002").status_code == 200

    second_response = client.post(
        "/api/ip/imports/upload",
        headers=actor["headers"],
        files={"file": ("second.csv", _csv("ASTER DUP", "TM 2026 9002"), "text/csv")},
    )
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    candidate = second["rows"][0]["duplicate_candidates"][0]
    assert "exact_application_number" in candidate["match_reasons"]

    blocked = _commit(client, actor["headers"], second, "duplicate-link-9002")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ip_import_duplicate_decision_required"

    reconciled = client.post(
        f"/api/ip/imports/{second['job']['id']}/reconcile",
        headers=actor["headers"],
        json={
            "expected_job_version": second["job"]["version"],
            "decisions": [
                {
                    "row_id": second["rows"][0]["id"],
                    "decision": "link_existing",
                    "target_docket_id": candidate["docket_id"],
                }
            ],
        },
    )
    assert reconciled.status_code == 200, reconciled.text
    result = _commit(client, actor["headers"], reconciled.json(), "duplicate-link-9002")
    assert result.status_code == 200, result.text
    row = result.json()["rows"][0]
    assert row["commit_status"] == "committed"
    assert row["created_docket_id"] is None
    assert row["reconciled_target_docket_id"] == candidate["docket_id"]
