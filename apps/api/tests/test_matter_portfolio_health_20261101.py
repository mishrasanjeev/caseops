"""GET /api/matters/portfolio-health counts every visible Matter (B4-ADJ-03).

The portfolio page asked for 500 Matters, the list endpoint returns at most
200, and the page computed its totals and buckets from that one page. This
fixture holds 230 Matters, the distinctive ones created first (sorted last by
recency), so a one-page reader cannot produce the expected counts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update

from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ethical_walls import _create_matter, _invite_member

BULK = 226


def _bulk_matters(company_id: str) -> None:
    with get_session_factory()() as session:
        for index in range(BULK):
            session.add(
                Matter(
                    company_id=company_id,
                    title=f"Bulk matter {index:03d}",
                    matter_code=f"BULK-{index:03d}",
                    status="active",
                    practice_area="Commercial",
                    forum_level="high_court",
                )
            )
        session.commit()


def test_portfolio_health_counts_past_the_list_page_and_respects_walls(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    owner = str(boot["access_token"])
    company_id = boot["company"]["id"]
    # Created first, so the least recently updated: last on any recency page.
    tax = _create_matter(client, owner, "TAX-OLD-1")
    walled = _create_matter(client, owner, "WALL-OLD-1")
    idle = _create_matter(client, owner, "IDLE-OLD-1")
    with get_session_factory()() as session:
        session.execute(
            update(Matter)
            .where(Matter.id == tax)
            .values(practice_area="Tax", forum_level="tribunal", status="intake")
        )
        session.execute(
            update(Matter)
            .where(Matter.id == idle)
            .values(status="active", updated_at=datetime.now(UTC) - timedelta(days=45))
        )
        session.commit()
    _bulk_matters(company_id)

    total = BULK + 3
    first_page = client.get("/api/matters/", headers=auth_headers(owner), params={"limit": 500})
    assert first_page.status_code == 200
    assert len(first_page.json()["matters"]) == 200  # the old portfolio read stopped here

    response = client.get("/api/matters/portfolio-health", headers=auth_headers(owner))
    assert response.status_code == 200, response.text
    health = response.json()
    assert health["total_visible_count"] == total
    assert sum(bucket["count"] for bucket in health["status_counts"]) == total
    assert {"key": "intake", "count": 2} in health["status_counts"]  # TAX and WALL
    assert {"key": "Tax", "count": 1} in health["practice_area_counts"]
    assert {"key": "tribunal", "count": 1} in health["forum_level_counts"]
    assert health["intake_matters_count"] == 2
    assert health["idle_after_days"] == 30
    assert health["idle_active_count"] == 1
    assert [row["id"] for row in health["idle_active_matters"]] == [idle]

    member_mid, member = _invite_member(client, owner, "portfolio@asterlegal.in")
    wall = client.post(
        f"/api/matters/{walled}/access/walls",
        headers=auth_headers(owner),
        json={"excluded_membership_id": member_mid, "reason": "Conflict."},
    )
    assert wall.status_code == 200, wall.text
    member_view = client.get("/api/matters/portfolio-health", headers=auth_headers(member))
    assert member_view.status_code == 200
    assert member_view.json()["total_visible_count"] == total - 1
    assert sum(bucket["count"] for bucket in member_view.json()["status_counts"]) == total - 1

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Portfolio Other LLP",
            "company_slug": "portfolio-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@portfolio-other.example",
            "owner_password": "PortfolioOther123!",
        },
    )
    assert other.status_code == 200, other.text
    foreign = client.get(
        "/api/matters/portfolio-health", headers=auth_headers(other.json()["access_token"])
    ).json()
    assert foreign["total_visible_count"] == 0
    assert foreign["status_counts"] == []
    assert foreign["idle_active_matters"] == []

    client.cookies.clear()
    assert client.get("/api/matters/portfolio-health").status_code == 401
