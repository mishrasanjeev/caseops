from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Matter
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create(client, headers, **values):
    response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Temporary filing matter",
            "matter_code": "TEMP-CASE-001",
            "practice_area": "Civil",
            "forum_level": "high_court",
            **values,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_temporary_identifier_retained_searchable_and_tenant_scoped(client):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    matter = _create(
        client, headers, temporary_e_case_number="  TEMP/2026/00125  ", filing_number="FILING-001"
    )
    assert matter["temporary_e_case_number"] == "TEMP/2026/00125"
    assert matter["case_number"] is None and matter["cnr_number"] is None
    found = client.get("/api/matters/", headers=headers, params={"q": "temp/2026/00125"})
    assert [row["id"] for row in found.json()["matters"]] == [matter["id"]]
    response = client.patch(
        f"/api/matters/{matter['id']}",
        headers=headers,
        json={
            "expected_updated_at": matter["updated_at"],
            "case_number": "1234/2026",
            "cnr_number": "DLHC010012342026",
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["temporary_e_case_number"] == "TEMP/2026/00125"
    assert updated["filing_number"] == "FILING-001"
    assert updated["lifecycle_version"] == matter["lifecycle_version"]
    assert updated["status"] == matter["status"]
    for identifier in ("TEMP/2026/00125", "1234/2026", "DLHC010012342026", "FILING-001"):
        found = client.get("/api/matters/", headers=headers, params={"q": identifier})
        assert [row["id"] for row in found.json()["matters"]] == [matter["id"]]
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Firm",
            "company_slug": "other-ecase",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "other@ecase.example.com",
            "owner_password": "OtherFixture123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(other.json()["access_token"])
    assert (
        client.get("/api/matters/", headers=other_headers, params={"q": "TEMP/2026/00125"}).json()[
            "matters"
        ]
        == []
    )
    assert client.get(f"/api/matters/{matter['id']}", headers=other_headers).status_code == 404
    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row.temporary_e_case_number == "TEMP/2026/00125"
        assert session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.company_id == boot["company"]["id"],
                AuditEvent.target_id == matter["id"],
                AuditEvent.action == "matter.created",
            )
        )


def test_temporary_identifier_obeys_stale_write_and_terminal_guards(client):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    matter = _create(client, headers, temporary_e_case_number="TEMP/2026/00125")
    url = f"/api/matters/{matter['id']}"
    disposed = client.patch(
        url + "/lifecycle/status",
        headers=headers,
        json={
            "to_status": "disposed",
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "September regression disposal.",
        },
    )
    assert disposed.status_code == 200, disposed.text
    for token in (matter["updated_at"], disposed.json()["updated_at"]):
        rejected = client.patch(
            url,
            headers=headers,
            json={
                "expected_updated_at": token,
                "temporary_e_case_number": "SHOULD-NOT-WRITE",
            },
        )
        assert rejected.status_code == 409, rejected.text
    current = client.get(url, headers=headers).json()
    assert current["status"] == "disposed" and current["is_active"] is False
    assert current["temporary_e_case_number"] == "TEMP/2026/00125"


@pytest.mark.parametrize("field", ["temporary_e_case_number", "cnr_number"])
def test_import_identifiers_enforce_existing_schema_bounds(client, field):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    data = io.StringIO()
    writer = csv.writer(data)
    writer.writerow(["Matter Title", "Matter Code", "Practice Area", "Forum", field])
    writer.writerow(["Invalid long identifier", "TOO-LONG", "Civil", "High Court", "X" * 121])
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("bounds.csv", data.getvalue().encode(), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalid_rows"] == 1


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_downloaded_template_has_no_unresolvable_assignment_examples(client, format):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    template = client.get(f"/api/matters/imports/template?format={format}", headers=headers)
    assert template.status_code == 200
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": (f"template.{format}", template.content, template.headers["content-type"])},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalid_rows"] == 0, preview.text
    assert preview.json()["valid_rows"] == 1


@pytest.mark.parametrize("identity", ["Matter Code", "Case Number", "title_client"])
def test_invalid_first_copy_cannot_suppress_later_valid_matter(client, identity):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    fields = [
        "Matter Title",
        "Matter Code",
        "Practice Area",
        "Forum",
        "Case Number",
        "Client Name",
        "Temporary E-Case Number",
        "CNR Number",
    ]
    rows = [
        [
            "First invalid row",
            "CODE-ONE",
            "Civil",
            "High Court",
            "CASE-ONE",
            "Client One",
            "TEMP/2026/00125",
            "DLHC010012342026",
        ],
        [
            "Second valid row",
            "CODE-TWO",
            "Civil",
            "High Court",
            "CASE-TWO",
            "Client Two",
            "TEMP/2026/00125",
            "DLHC010012342026",
        ],
    ]
    if identity == "title_client":
        rows[0][0], rows[0][5] = rows[1][0], rows[1][5]
    else:
        index = fields.index(identity)
        rows[0][index] = rows[1][index]
    rows[0][2] = ""  # The first copy cannot create anything.
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(fields)
    writer.writerows(rows)
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("first-invalid.csv", out.getvalue().encode(), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert [r["status"] for r in preview.json()["rows"]] == ["invalid", "valid"]


def test_bulk_temporary_and_final_identifiers_survive_commit_and_replay(client):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    data = (
        b"Matter Title,Matter Code,Practice Area,Forum,Temporary E-Case Number,CNR Number\n"
        b"Temporary import,TEMP-IMPORT,Civil,High Court,TEMP/2026/00125,DLHC010012342026\n"
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("temporary.csv", data, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 1, preview.text
    results = []
    for _ in range(2):
        result = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
        assert result.status_code == 200, result.text
        results.append(result.json()["created_matter_ids"])
    assert len(results[0]) == 1 and results[0] == results[1]
    row = client.get(f"/api/matters/{results[0][0]}", headers=headers).json()
    assert row["temporary_e_case_number"] == "TEMP/2026/00125"
    assert row["cnr_number"] == "DLHC010012342026"
    assert row["case_number"] is None


def test_skipped_existing_duplicate_cannot_claim_an_unused_identity(client):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    original = _create(client, headers, case_number="EXISTING-CASE")
    data = (
        b"Matter Title,Matter Code,Practice Area,Forum,Case Number\n"
        b"Skipped existing code,TEMP-CASE-001,Civil,High Court,NEW-CASE\n"
        b"Valid new matter,NEW-CODE,Civil,High Court,NEW-CASE\n"
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("duplicate-chain.csv", data, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert [r["status"] for r in job["rows"]] == ["duplicate", "valid"]
    commit = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
    assert commit.status_code == 200, commit.text
    assert len(commit.json()["created_matter_ids"]) == 1
    persisted = client.get(f"/api/matters/{original['id']}", headers=headers).json()
    assert persisted["case_number"] == "EXISTING-CASE"
    assert persisted["updated_at"] == original["updated_at"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("Forum State", "Karnataka"),
        ("Forum District", "Invented district"),
        ("Forum City", "Mumbai"),
        ("Forum Consumer Level", "district"),
    ],
)
@pytest.mark.parametrize("selection", ["id", "name"])
def test_explicit_catalog_selection_rejects_conflicting_lineage(client, field, value, selection):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["Matter Title", "Matter Code", "Practice Area", "Forum",
         "Forum Catalog Entry ID" if selection == "id" else "Court", field]
    )
    writer.writerow(
        ["Conflicting hierarchy", "BAD-LINEAGE", "Civil", "High Court",
         "hc:delhi" if selection == "id" else "Delhi High Court", value]
    )
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("lineage.csv", out.getvalue().encode(), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["invalid_rows"] == 1, preview.text
    assert "context does not match" in str(preview.json()["rows"][0]["errors"])

    payload_field = field.lower().replace(" ", "_")
    manual = client.post("/api/matters/", headers=headers, json={
        "title": "Manual conflicting hierarchy", "matter_code": "MANUAL-CONFLICT",
        "practice_area": "Civil", "forum_level": "high_court",
        "forum_catalog_entry_id": "hc:delhi", payload_field: value,
    })
    assert manual.status_code == 400, manual.text


@pytest.mark.parametrize("forum", ["tribunal", "Tribunal", "DRAT / DRT"])
def test_uncatalogued_court_preserves_supplied_context_without_invented_lineage(client, forum):
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    data = (
        "Matter Title,Matter Code,Practice Area,Forum,Court,Forum State,Forum City\n"
        f"Regional recovery,REGIONAL-001,Civil,{forum},"
        "Uncatalogued Recovery Bench,Maharashtra,Mumbai\n"
    )
    preview = client.post("/api/matters/imports/preview", headers=headers,
                          files={"file": ("regional.csv", data.encode(), "text/csv")})
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 1, preview.text
    result = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
    assert result.status_code == 200, result.text
    matter_id = result.json()["created_matter_ids"][0]
    matter = client.get(f"/api/matters/{matter_id}", headers=headers).json()
    assert matter["forum_catalog_entry_id"] is None
    assert matter["forum_state"] == "Maharashtra"
    assert matter["forum_city"] == "Mumbai"
