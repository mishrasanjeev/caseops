"""The hearing follow-up queues page to the end (B4-ADJ-15).

GET /api/matters/hearing-follow-up returned at most one page of each queue
and the hearings page pointed at an unfiltered matter list for the rest. The
queues now take ``offset`` and ``queue`` so the page can load every row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update

from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ethical_walls import _create_matter, _invite_member

OVERDUE = 7
MISSING = 9


def _bulk(company_id: str) -> None:
    base = datetime.now(UTC) - timedelta(days=30)
    with get_session_factory()() as session:
        for index in range(OVERDUE):
            session.add(
                Matter(
                    company_id=company_id,
                    title=f"Overdue matter {index:02d}",
                    matter_code=f"FU-OD-{index:02d}",
                    status="active",
                    practice_area="Commercial",
                    forum_level="high_court",
                    next_hearing_on=date.today() - timedelta(days=index + 1),
                    created_at=base + timedelta(minutes=index),
                )
            )
        for index in range(MISSING):
            session.add(
                Matter(
                    company_id=company_id,
                    title=f"Missing matter {index:02d}",
                    matter_code=f"FU-MD-{index:02d}",
                    status="active",
                    practice_area="Commercial",
                    forum_level="high_court",
                    created_at=base + timedelta(minutes=index),
                )
            )
        session.commit()


def _read_queue(client: TestClient, token: str, queue: str, key: str) -> list[str]:
    ids: list[str] = []
    offset = 0
    while True:
        response = client.get(
            "/api/matters/hearing-follow-up",
            headers=auth_headers(token),
            params={"queue": queue, "offset": offset, "limit": 4},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["offset"] == offset
        other = "missing_date_matters" if key == "overdue_matters" else "overdue_matters"
        assert body[other] == []  # only the asked queue is read
        ids.extend(row["id"] for row in body[key])
        offset += len(body[key])
        if not body["truncated"]:
            return ids


def test_follow_up_queues_page_to_the_end_and_respect_walls(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner = str(boot["access_token"])
    company_id = boot["company"]["id"]
    _bulk(company_id)
    walled = _create_matter(client, owner, "FU-WALLED")
    with get_session_factory()() as session:
        session.execute(update(Matter).where(Matter.id == walled).values(status="active"))
        session.commit()

    first = client.get(
        "/api/matters/hearing-follow-up", headers=auth_headers(owner), params={"limit": 4}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["overdue_count"] == OVERDUE
    assert body["missing_date_count"] == MISSING + 1
    assert len(body["overdue_matters"]) == 4 and len(body["missing_date_matters"]) == 4
    assert body["truncated"] is True and body["offset"] == 0

    overdue = _read_queue(client, owner, "overdue", "overdue_matters")
    missing = _read_queue(client, owner, "missing_date", "missing_date_matters")
    assert len(overdue) == len(set(overdue)) == OVERDUE
    assert len(missing) == len(set(missing)) == MISSING + 1
    assert walled in missing

    member_id, member = _invite_member(client, owner, "follow-up@asterlegal.in")
    wall = client.post(
        f"/api/matters/{walled}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": member_id, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text
    member_missing = _read_queue(client, member, "missing_date", "missing_date_matters")
    assert walled not in member_missing
    assert len(member_missing) == MISSING
    member_body = client.get(
        "/api/matters/hearing-follow-up", headers=auth_headers(member)
    ).json()
    assert member_body["missing_date_count"] == MISSING

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Follow Up Other LLP",
            "company_slug": "follow-up-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@follow-up-other.example",
            "owner_password": "FollowUpOther123!",
        },
    )
    assert other.status_code == 200, other.text
    foreign = client.get(
        "/api/matters/hearing-follow-up",
        headers=auth_headers(other.json()["access_token"]),
        params={"queue": "missing_date", "offset": 0},
    ).json()
    assert foreign["missing_date_count"] == 0 and foreign["missing_date_matters"] == []
    assert foreign["overdue_count"] == 0

    assert (
        client.get(
            "/api/matters/hearing-follow-up",
            headers=auth_headers(owner),
            params={"offset": -1},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/matters/hearing-follow-up",
            headers=auth_headers(owner),
            params={"queue": "closed"},
        ).status_code
        == 422
    )
    client.cookies.clear()
    assert client.get("/api/matters/hearing-follow-up").status_code == 401
