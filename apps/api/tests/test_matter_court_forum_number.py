from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def test_court_forum_number_round_trips_through_create_read_and_update(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)

    created = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Court number persistence",
            "matter_code": "COURT-NUM-1",
            "practice_area": "Civil",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "court_forum_number": "  Court 7  ",
        },
    )

    assert created.status_code == 200, created.text
    created_record = created.json()
    assert created_record["court_forum_number"] == "Court 7"
    with get_session_factory()() as session:
        created_audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "matter.created",
                AuditEvent.matter_id == created_record["id"],
            )
        )
        assert created_audit is not None
        assert json.loads(created_audit.metadata_json)["court_forum_number"] == "Court 7"

    read = client.get(
        f"/api/matters/{created_record['id']}",
        headers=headers,
    )
    assert read.status_code == 200, read.text
    assert read.json()["court_forum_number"] == "Court 7"

    searched = client.get(
        "/api/matters/?q=Court%207",
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    assert created_record["id"] in {
        record["id"] for record in searched.json()["matters"]
    }

    updated = client.patch(
        f"/api/matters/{created_record['id']}",
        headers=headers,
        json={
            "court_forum_number": "  Bench 12  ",
            "expected_updated_at": read.json()["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_record = updated.json()
    assert updated_record["court_forum_number"] == "Bench 12"

    cleared = client.patch(
        f"/api/matters/{created_record['id']}",
        headers=headers,
        json={
            "court_forum_number": "   ",
            "expected_updated_at": updated_record["updated_at"],
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["court_forum_number"] is None
