"""Regression proof for the 2026-09-03 bulk Matter Exact Court enhancement."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from caseops_api.db.models import (
    ForumCatalogAlias,
    ForumCatalogEntry,
    Matter,
    MatterBulkImportRow,
)
from caseops_api.db.session import get_engine, get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _preview(client: TestClient, token: str, body: bytes) -> dict:
    response = client.post(
        "/api/matters/imports/preview",
        headers=auth_headers(token),
        files={"file": ("exact-courts.csv", body, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_courts_and_alias_resolve_full_lineage_preview_commit_and_audit(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    job = _preview(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court,Forum District\n"
        b"Tis Hazari exact,SEP03-TH,Commercial,Tis Hazari,,Central Delhi\n"
        b"ITO normalized,SEP03-ITO,Commercial,  iTo  ,,\n"
        b"Dwarka configured alias,SEP03-DW,Commercial,dwarka-swcf,,\n",
    )

    assert job["valid_rows"] == 3
    assert job["invalid_rows"] == 0
    expected = (
        (
            "district:india-gov:delhi:centraldelhi",
            "Central District Court, Delhi",
            "lower_court",
            None,
        ),
        (
            "consumer:dcdrc:delhi:ito",
            "District Consumer Commission, ITO",
            "tribunal",
            "district",
        ),
        (
            "consumer:dcdrc:delhi:dwarka",
            "District Consumer Commission, Dwarka",
            "tribunal",
            "district",
        ),
    )
    for row, (entry_id, court_name, forum_level, consumer_level) in zip(
        job["rows"], expected, strict=True
    ):
        assert row["status"] == "valid", row["errors"]
        assert row["normalized"]["forum_catalog_entry_id"] == entry_id
        assert row["normalized"]["forum_level"] == forum_level
        assert row["normalized"]["court_name"] == court_name
        assert row["normalized"]["forum_state"] == "Delhi"
        assert row["normalized"].get("forum_consumer_level") == consumer_level

    with get_session_factory()() as session:
        stored_rows = list(
            session.scalars(
                select(MatterBulkImportRow)
                .where(MatterBulkImportRow.job_id == job["id"])
                .order_by(MatterBulkImportRow.row_number)
            )
        )
        assert [row.raw_json["Forum"] for row in stored_rows] == [
            "Tis Hazari",
            "iTo",
            "dwarka-swcf",
        ]

    committed = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert committed.status_code == 200, committed.text
    assert len(committed.json()["created_matter_ids"]) == 3

    with get_session_factory()() as session:
        matters = list(
            session.scalars(
                select(Matter)
                .where(Matter.matter_code.in_(("SEP03-TH", "SEP03-ITO", "SEP03-DW")))
                .order_by(Matter.matter_code)
            )
        )
        assert len(matters) == 3
        by_code = {matter.matter_code: matter for matter in matters}
        assert by_code["SEP03-TH"].forum_catalog_entry_id == expected[0][0]
        assert by_code["SEP03-ITO"].forum_catalog_entry_id == expected[1][0]
        assert by_code["SEP03-DW"].forum_catalog_entry_id == expected[2][0]
        assert all(matter.forum_state == "Delhi" for matter in matters)
        assert by_code["SEP03-TH"].forum_consumer_level is None
        assert by_code["SEP03-ITO"].forum_consumer_level == "district"
        assert by_code["SEP03-DW"].forum_consumer_level == "district"


def test_alias_collision_is_rejected_at_its_row_and_never_guessed(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as session:
        for entry_id in (
            "consumer:dcdrc:delhi:ito",
            "consumer:dcdrc:delhi:tis-hazari",
        ):
            session.add(
                ForumCatalogAlias(
                    forum_catalog_entry_id=entry_id,
                    alias="Shared Delhi Alias",
                    normalized_alias="shareddelhialias",
                    source_name="Regression fixture",
                    source_url="https://example.test/forum-alias",
                    verification_status="verified",
                    is_active=True,
                )
            )
        session.commit()

    job = _preview(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum\n"
        b"Ambiguous alias,SEP03-AMB,Commercial,Shared Delhi Alias\n",
    )
    row = job["rows"][0]
    assert row["status"] == "invalid"
    message = " ".join(row["errors"])
    assert "Row 2" in message
    assert "Shared Delhi Alias" in message
    assert "multiple active Exact Court records" in message
    assert "will not guess" in message
    assert row["normalized"].get("forum_catalog_entry_id") is None


def test_explicit_catalog_id_accepts_the_same_normalized_alias_as_manual_entry(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    job = _preview(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court,ForumCatalogEntryId\n"
        b"Normalized explicit alias,SEP03-ID-ALIAS,Commercial,District Court,"
        b"Tis Hazari Court,district:india-gov:delhi:centraldelhi\n",
    )

    assert job["valid_rows"] == 1, job["rows"][0]["errors"]
    row = job["rows"][0]["normalized"]
    assert row["forum_catalog_entry_id"] == "district:india-gov:delhi:centraldelhi"
    assert row["court_name"] == "Central District Court, Delhi"


def test_exact_court_conflict_unknown_inactive_and_existing_validation_fail_closed(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as session:
        inactive = session.get(ForumCatalogEntry, "consumer:dcdrc:delhi:dwarka")
        assert inactive is not None
        inactive.is_active = False
        session.commit()

    job = _preview(
        client,
        token,
        b"Matter Title,Matter Code,Practice Area,Forum,Court,Forum State,Matter Owner\n"
        b"Conflict,SEP03-CONFLICT,Commercial,Tis Hazari,ITO,Delhi,\n"
        b"Inactive alias,SEP03-INACTIVE,Commercial,Dwarka_SWCF,,,\n"
        b"Unknown court,SEP03-UNKNOWN,Commercial,Imaginary Court,,,\n"
        b"Other validation,SEP03-OWNER,Commercial,ITO,,,Nobody Here\n",
    )

    assert job["invalid_rows"] == 4
    conflict, inactive, unknown, owner = job["rows"]
    assert "Row 2" in " ".join(conflict["errors"])
    assert "conflicts with the supplied" in " ".join(conflict["errors"])
    assert "Dwarka_SWCF" in " ".join(inactive["errors"])
    assert "did not match an active configured Exact Court" in " ".join(inactive["errors"])
    assert "Imaginary Court" in " ".join(unknown["errors"])
    assert "Nobody Here" in " ".join(owner["errors"])
    assert "work email or full name" in " ".join(owner["errors"])

    commit = client.post(
        f"/api/matters/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 400
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Matter).where(Matter.matter_code.like("SEP03-%"))
            )
            == 0
        )


def test_forum_catalog_api_exposes_only_configured_aliases(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    response = client.get("/api/courts/forum-catalog", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    entries = {entry["id"]: entry for entry in response.json()["entries"]}
    assert sorted(entries["consumer:dcdrc:delhi:dwarka"]["aliases"]) == [
        "Dwarka DCDRC",
        "Dwarka_SWCF",
    ]
    assert entries["consumer:dcdrc:delhi:ito"]["aliases"] == ["ITO"]
    assert entries["district:india-gov:delhi:centraldelhi"]["aliases"] == ["Tis Hazari"]
    assert entries["district:india-gov:delhi:westdelhi"]["aliases"] == ["Tis Hazari"]


def test_500_exact_court_rows_load_the_catalog_once(client: TestClient) -> None:
    """Production-size files must not rescan/query the catalog per row."""
    token = str(bootstrap_company(client)["access_token"])
    engine = get_engine()
    catalog_selects: list[str] = []

    def capture_catalog_select(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.casefold().split())
        if normalized.startswith("select") and "forum_catalog_entries" in normalized:
            catalog_selects.append(normalized)

    body = b"Matter Title,Matter Code,Practice Area,Forum\n" + b"".join(
        f"Scale row {index},SEP03-SCALE-{index:03d},Commercial,ITO\n".encode()
        for index in range(500)
    )
    event.listen(engine, "before_cursor_execute", capture_catalog_select)
    try:
        response = client.post(
            "/api/matters/imports/dry-run",
            headers=auth_headers(token),
            files={"mapping_file": ("scale.csv", body, "text/csv")},
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_catalog_select)

    assert response.status_code == 200, response.text
    assert len(response.json()["rows"]) == 500
    assert all(row["status"] == "valid" for row in response.json()["rows"])
    assert len(catalog_selects) == 1
