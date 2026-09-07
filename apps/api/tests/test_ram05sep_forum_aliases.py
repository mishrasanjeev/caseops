from __future__ import annotations

import csv
import importlib.util
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from caseops_api.db.models import (
    ForumCatalogAlias,
    ForumCatalogEntry,
    MatterBulkImportJob,
    MatterImportJobStatus,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company

CASES = (
    ("Tis Hazari", "Tis Hazari (West)", "district:india-gov:delhi:westdelhi"),
    ("Dwarka_SWCF", "Dwarka-Consumer Forum", "consumer:dcdrc:delhi:dwarka"),
    ("TDSAT- New Delhi", "", "tdsat:delhi"),
)


@pytest.mark.parametrize("forum,court,entry_id", CASES)
def test_reported_qualified_alias_round_trips_manual_preview_commit(client, forum, court, entry_id):
    boot = bootstrap_company(client)
    headers = auth_headers(boot["access_token"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Matter Title", "Matter Code", "Practice Area", "Forum", "Court"])
    writer.writerow(["Qualified source court", "QUALIFIED-BULK", "Civil", forum, court])
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={"file": ("qualified.csv", output.getvalue().encode(), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 1, preview.text
    committed = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
    assert committed.status_code == 200, committed.text
    matter_id = committed.json()["created_matter_ids"][0]
    saved = client.get(f"/api/matters/{matter_id}", headers=headers).json()
    assert saved["forum_catalog_entry_id"] == entry_id
    with get_session_factory()() as session:
        entry = session.get(ForumCatalogEntry, entry_id)
        level = entry.forum_level
        assert saved["forum_state"] == entry.state
        assert saved["forum_district"] == entry.district
    manual = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Manual qualified source court",
            "matter_code": "QUALIFIED-MANUAL",
            "practice_area": "Civil",
            "forum_level": level,
            "forum_catalog_entry_id": entry_id,
            "court_name": court or forum,
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["forum_catalog_entry_id"] == entry_id
    replay = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["created_matter_ids"] == [matter_id]


def test_alias_upgrade_replay_preserves_review_and_deactivation(client):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20260905_0003_reported_forum_aliases.py"
    )
    spec = importlib.util.spec_from_file_location("ram05_alias_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with get_session_factory()() as session:
        alias = session.scalar(
            select(ForumCatalogAlias).where(ForumCatalogAlias.normalized_alias == "tishazariwest")
        )
        alias.is_active = False
        alias.verification_status = "rejected"
        alias.record_version = 2
        session.commit()
        engine = session.get_bind()
    for _ in range(2):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
    with get_session_factory()() as session:
        aliases = session.scalars(
            select(ForumCatalogAlias).where(ForumCatalogAlias.normalized_alias == "tishazariwest")
        ).all()
        assert len(aliases) == 1
        assert not aliases[0].is_active
        assert aliases[0].verification_status == "rejected"
        assert aliases[0].record_version == 2
    module.downgrade()
    with get_session_factory()() as session:
        assert session.scalar(select(ForumCatalogAlias.record_version).where(
            ForumCatalogAlias.normalized_alias == "tishazariwest")) == 2


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("change", ["deactivate", "retarget"])
def test_alias_revalidation_rejects_changes_between_preview_and_commit(client, recover, change):
    boot = bootstrap_company(client)
    headers = auth_headers(boot["access_token"])
    preview = client.post(
        "/api/matters/imports/preview",
        headers=headers,
        files={
            "file": (
                "qualified.csv",
                b"Matter Title,Matter Code,Practice Area,Forum,Court\n"
                b"Qualified source court,QUALIFIED-BULK,Civil,Tis Hazari,Tis Hazari (West)\n",
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 1, preview.text
    with get_session_factory()() as session:
        alias = session.scalar(
            select(ForumCatalogAlias).where(ForumCatalogAlias.normalized_alias == "tishazariwest")
        )
        if change == "deactivate":
            alias.is_active = False
        else:
            alias.forum_catalog_entry_id = "district:india-gov:delhi:centraldelhi"
        if recover:
            saved_job = session.get(MatterBulkImportJob, job["id"])
            saved_job.status = MatterImportJobStatus.IMPORTING
            saved_job.updated_at = datetime.now(UTC) - timedelta(minutes=15)
        session.commit()
    committed = client.post(f"/api/matters/imports/{job['id']}/commit", headers=headers)
    assert committed.status_code == (200 if recover else 400), committed.text
    if not recover:
        assert "No valid matter rows remain" in committed.text
    else:
        assert committed.json()["created_matter_ids"] == []
    replay = client.get(f"/api/matters/imports/{job['id']}", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["rows"][0]["created_matter_id"] is None
