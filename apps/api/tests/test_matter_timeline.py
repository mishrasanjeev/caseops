"""Sprint Q8 — tests for the matter timeline builder.

Two layers: a pure-function pass that seeds events across the three
source tables and asserts the merge + sort, and an HTTP integration
pass that bootstraps a company and verifies tenant isolation on
``build_matter_timeline_by_id``.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    Matter,
    MatterCourtOrder,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterHearingStatus,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.matter_timeline import (
    build_matter_timeline,
    build_matter_timeline_by_id,
)


def _seed_hearing(matter_id: str, on: date, purpose: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        session.add(
            MatterHearing(
                matter_id=matter_id,
                hearing_on=on,
                forum_name="Delhi High Court",
                judge_name="Vikram Nath",
                purpose=purpose,
                status=MatterHearingStatus.SCHEDULED,
            )
        )
        session.commit()


def _seed_deadline(matter_id: str, due: date, title: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        session.add(
            MatterDeadline(
                matter_id=matter_id,
                source="manual",
                kind="filing",
                title=title,
                due_on=due,
                status=MatterDeadlineStatus.OPEN,
            )
        )
        session.commit()


def _seed_court_order(matter_id: str, on: date, title: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        session.add(
            MatterCourtOrder(
                matter_id=matter_id,
                order_date=on,
                title=title,
                summary="Order summary text.",
                source="court-sync",
                synced_at=datetime.now(UTC),
            )
        )
        session.commit()


def _create_matter(client: TestClient, *, matter_code: str, headers) -> str:
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": matter_code,
            "title": f"Timeline test {matter_code}",
            "practice_area": "Civil / Contract",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "description": "Timeline fixture.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_timeline_merges_three_sources_in_date_order(
    client: TestClient,
) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, matter_code="TL-001", headers=headers)

    _seed_hearing(matter_id, date(2026, 4, 10), "First listing")
    _seed_deadline(matter_id, date(2026, 4, 15), "File reply")
    _seed_court_order(matter_id, date(2026, 4, 5), "Order dated 05-Apr")
    _seed_hearing(matter_id, date(2026, 4, 20), "Arguments")

    factory = get_session_factory()
    with factory() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id))
        assert matter is not None
        timeline = build_matter_timeline(session=session, matter=matter)

    # 4 events total.
    assert len(timeline.events) == 4
    # Ascending by date.
    dates = [e.event_date for e in timeline.events]
    assert dates == sorted(dates)
    # Kinds are tagged correctly.
    kinds = [e.kind for e in timeline.events]
    assert kinds[0] == "court_order"
    assert "hearing" in kinds
    assert "deadline" in kinds


def test_timeline_same_date_tie_break_hearing_then_order_then_deadline(
    client: TestClient,
) -> None:
    """Three events on the same day must come out in
    hearing / court_order / deadline order — the lawyer's expected scan."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, matter_code="TL-002", headers=headers)

    same_day = date(2026, 5, 1)
    _seed_deadline(matter_id, same_day, "Same-day deadline")
    _seed_court_order(matter_id, same_day, "Same-day order")
    _seed_hearing(matter_id, same_day, "Same-day hearing")

    factory = get_session_factory()
    with factory() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id))
        timeline = build_matter_timeline(session=session, matter=matter)

    kinds = [e.kind for e in timeline.events]
    assert kinds == ["hearing", "court_order", "deadline"]


def test_timeline_is_empty_for_bare_matter(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, matter_code="TL-003", headers=headers)

    factory = get_session_factory()
    with factory() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id))
        timeline = build_matter_timeline(session=session, matter=matter)

    assert timeline.events == []
    assert timeline.matter_id == matter_id


def test_build_timeline_by_id_rejects_cross_tenant(client: TestClient) -> None:
    """Tenant A's matter must 404 for Tenant B."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    a = bootstrap_company(client)
    token_a = str(a["access_token"])
    headers_a = auth_headers(token_a)
    matter_id_a = _create_matter(client, matter_code="TL-ISO", headers=headers_a)

    # Tenant B.
    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B LLP",
            "company_slug": "tenant-b-tl",
            "company_type": "law_firm",
            "owner_full_name": "Tenant B Owner",
            "owner_email": "b@b.example",
            "owner_password": "TenantB-Strong!234",
        },
    )
    assert resp_b.status_code == 200
    context_b_payload = resp_b.json()
    # Reconstruct a context by loading the identity from the session
    # factory — the bench matcher test does the same thing via an HTTP
    # wrapper; we keep this at the service layer to exercise the
    # tenancy-safe wrapper directly.
    from caseops_api.db.models import Company, CompanyMembership, User
    from caseops_api.services.identity import SessionContext

    factory = get_session_factory()
    with factory() as session:
        company_b = session.scalar(
            select(Company).where(Company.id == context_b_payload["company"]["id"])
        )
        user_b = session.scalar(
            select(User).where(User.id == context_b_payload["user"]["id"])
        )
        membership_b = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == context_b_payload["membership"]["id"]
            )
        )
        assert company_b and user_b and membership_b
        context_b = SessionContext(
            company=company_b, user=user_b, membership=membership_b,
        )

        # Tenant B requesting Tenant A's matter → 404.
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            build_matter_timeline_by_id(
                session=session, context=context_b, matter_id=matter_id_a,
            )
        assert exc.value.status_code == 404


def test_timeline_hearing_summary_includes_judge(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, matter_code="TL-004", headers=headers)

    _seed_hearing(matter_id, date(2026, 6, 1), "Final arguments")

    factory = get_session_factory()
    with factory() as session:
        matter = session.scalar(select(Matter).where(Matter.id == matter_id))
        timeline = build_matter_timeline(session=session, matter=matter)

    assert len(timeline.events) == 1
    event = timeline.events[0]
    assert event.kind == "hearing"
    assert event.title == "Final arguments"
    assert "Vikram Nath" in event.summary
