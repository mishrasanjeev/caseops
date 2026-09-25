"""Release backfill accepts production-sized tenant history and remains replayable."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterHearing,
    MatterHearingStatus,
    MatterNextHearingHistory,
)
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_next_hearings as command
from caseops_api.services.next_hearing import apply_next_hearing_update
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_release_backfill_materializes_1200_legacy_dates_and_replays(
    isolated_postgres_client, monkeypatch, capsys
) -> None:
    boot = bootstrap_company(isolated_postgres_client)
    company_id = str(boot["company"]["id"])
    hearing_on = date(2026, 11, 4)
    terminal = {
        status: str(uuid4())
        for status in (
            MatterHearingStatus.COMPLETED,
            MatterHearingStatus.CANCELLED,
            MatterHearingStatus.ADJOURNED,
        )
    }
    with get_session_factory()() as session:
        session.execute(
            insert(Matter),
            [
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "title": f"Legacy hearing {index}",
                    "matter_code": f"LEGACY-VOLUME-{index}",
                    "practice_area": "litigation",
                    "forum_level": "high_court",
                    "next_hearing_on": hearing_on,
                }
                for index in range(1200)
            ],
        )
        session.execute(
            insert(Matter),
            [
                {
                    "id": matter_id,
                    "company_id": company_id,
                    "title": f"Terminal {status} hearing",
                    "matter_code": f"LEGACY-{status}",
                    "practice_area": "litigation",
                    "forum_level": "high_court",
                    "next_hearing_on": hearing_on,
                }
                for status, matter_id in terminal.items()
            ],
        )
        session.execute(
            insert(MatterHearing),
            [
                {
                    "company_id": company_id,
                    "matter_id": matter_id,
                    "hearing_on": hearing_on,
                    "forum_name": "Delhi High Court",
                    "purpose": "Historical hearing",
                    "source": "unknown",
                    "status": status,
                }
                for status, matter_id in terminal.items()
            ],
        )
        session.commit()

    assert command.main() == 0
    output = capsys.readouterr().out
    assert f'"{company_id}": 1200' in output
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterHearing)
                .where(MatterHearing.company_id == company_id)
            )
            == 1203
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterNextHearingHistory)
                .where(MatterNextHearingHistory.company_id == company_id)
            )
            == 1200
        )
        for status, matter_id in terminal.items():
            retained = session.scalar(
                select(MatterHearing).where(MatterHearing.matter_id == matter_id)
            )
            assert retained is not None and retained.status == status
    assert command.main() == 0
    output = capsys.readouterr().out
    assert f'"{company_id}": 0' in output
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterHearing)
                .where(MatterHearing.company_id == company_id)
            )
            == 1203
        )
        for status, matter_id in terminal.items():
            retained = session.scalar(
                select(MatterHearing).where(MatterHearing.matter_id == matter_id)
            )
            assert retained is not None and retained.status == status


def test_release_backfill_includes_active_company_without_active_membership(
    isolated_postgres_client, capsys
) -> None:
    boot = bootstrap_company(isolated_postgres_client)
    company_id = str(boot["company"]["id"])
    matter_id = str(uuid4())
    with get_session_factory()() as session:
        session.execute(
            insert(Matter),
            [
                {
                    "id": matter_id,
                    "company_id": company_id,
                    "title": "Orphaned tenant legacy date",
                    "matter_code": "LEGACY-NO-MEMBER",
                    "practice_area": "litigation",
                    "forum_level": "high_court",
                    "next_hearing_on": date(2026, 11, 4),
                }
            ],
        )
        membership = session.get(CompanyMembership, str(boot["membership"]["id"]))
        assert membership is not None
        membership.is_active = False
        session.commit()

    assert command.main() == 0
    assert f'"{company_id}": 1' in capsys.readouterr().out
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterHearing)
                .where(MatterHearing.matter_id == matter_id)
            )
            == 1
        )


def test_next_hearing_update_keeps_completed_source_row_terminal(
    isolated_postgres_client,
) -> None:
    boot = bootstrap_company(isolated_postgres_client)
    company_id = str(boot["company"]["id"])
    matter_id = str(uuid4())
    original = date.today() - timedelta(days=1)
    replacement = date.today() + timedelta(days=10)
    with get_session_factory()() as session:
        session.execute(
            insert(Matter),
            [
                {
                    "id": matter_id,
                    "company_id": company_id,
                    "title": "Retained completed hearing",
                    "matter_code": "HEARING-TERMINAL",
                    "practice_area": "litigation",
                    "forum_level": "high_court",
                    "next_hearing_on": original,
                }
            ],
        )
        historical = MatterHearing(
            company_id=company_id,
            matter_id=matter_id,
            hearing_on=original,
            forum_name="Delhi High Court",
            purpose="Completed hearing",
            source="case_tracking",
            source_ref_type="tracked_case_snapshot",
            source_ref_id="snapshot-1",
            status=MatterHearingStatus.COMPLETED,
        )
        session.add(historical)
        session.flush()
        historical_id = historical.id
        matter = session.get(Matter, matter_id)
        assert matter is not None
        unchanged = apply_next_hearing_update(
            session,
            matter=matter,
            new_date=original,
            source="case_tracking",
            source_ref_type="tracked_case_snapshot",
            source_ref_id="snapshot-1",
        )
        assert not unchanged.applied
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterHearing)
                .where(MatterHearing.matter_id == matter_id)
            )
            == 1
        )
        result = apply_next_hearing_update(
            session,
            matter=matter,
            new_date=replacement,
            source="case_tracking",
            source_ref_type="tracked_case_snapshot",
            source_ref_id="snapshot-1",
            authoritative_automatic=True,
        )
        assert result.applied
        session.commit()
        session.expire_all()
        retained = session.get(MatterHearing, historical_id)
        assert retained is not None
        assert retained.status == MatterHearingStatus.COMPLETED
        assert retained.hearing_on == original
        scheduled = list(
            session.scalars(
                select(MatterHearing).where(
                    MatterHearing.matter_id == matter_id,
                    MatterHearing.status == MatterHearingStatus.SCHEDULED,
                )
            )
        )
        assert len(scheduled) == 1
        assert scheduled[0].id != historical_id
        assert scheduled[0].hearing_on == replacement


def test_manual_adjournment_keeps_one_open_hearing_and_one_calendar_event(
    isolated_postgres_client,
) -> None:
    client = isolated_postgres_client
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    matter_response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Adjournment calendar identity",
            "matter_code": f"ADJ-{uuid4().hex[:12]}",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    matter_id = matter_response.json()["id"]
    first_date = date.today() + timedelta(days=5)
    adjourned_date = first_date + timedelta(days=7)
    hearing_response = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=headers,
        json={
            "hearing_on": first_date.isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Arguments",
        },
    )
    assert hearing_response.status_code == 200, hearing_response.text
    hearing_id = hearing_response.json()["id"]
    updated = client.patch(
        f"/api/matters/{matter_id}/hearings/{hearing_id}",
        headers=headers,
        json={"status": "adjourned", "hearing_on": adjourned_date.isoformat()},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "adjourned"
    with get_session_factory()() as session:
        hearings = list(
            session.scalars(select(MatterHearing).where(MatterHearing.matter_id == matter_id))
        )
        assert len(hearings) == 1
        assert hearings[0].id == hearing_id
        assert hearings[0].status == MatterHearingStatus.ADJOURNED
        assert hearings[0].hearing_on == adjourned_date
        matter = session.get(Matter, matter_id)
        assert matter is not None
        assert matter.next_hearing_on == adjourned_date
        assert matter.next_hearing_source_ref_id == hearing_id
    calendar = client.get(
        "/api/calendar/events",
        headers=headers,
        params={"from": first_date.isoformat(), "to": adjourned_date.isoformat()},
    )
    assert calendar.status_code == 200, calendar.text
    events = [
        event
        for event in calendar.json()["events"]
        if event["kind"] == "hearing" and event["matter_id"] == matter_id
    ]
    assert len(events) == 1
    assert events[0]["occurs_on"] == adjourned_date.isoformat()


def test_manual_adjourned_create_and_closed_reconciliation_do_not_duplicate(
    isolated_postgres_client,
) -> None:
    client = isolated_postgres_client
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    matter_response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Adjourned replacement identity",
            "matter_code": f"ADJ-{uuid4().hex[:12]}",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    matter_id = matter_response.json()["id"]
    replacement_date = date.today() + timedelta(days=7)
    current_date = replacement_date + timedelta(days=7)
    replacement_response = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=headers,
        json={
            "hearing_on": replacement_date.isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Replacement",
            "status": "adjourned",
        },
    )
    assert replacement_response.status_code == 200, replacement_response.text
    replacement_id = replacement_response.json()["id"]
    current_response = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=headers,
        json={
            "hearing_on": current_date.isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Current",
        },
    )
    assert current_response.status_code == 200, current_response.text
    closed = client.patch(
        f"/api/matters/{matter_id}/hearings/{current_response.json()['id']}",
        headers=headers,
        json={"status": "cancelled"},
    )
    assert closed.status_code == 200, closed.text
    with get_session_factory()() as session:
        hearings = list(
            session.scalars(select(MatterHearing).where(MatterHearing.matter_id == matter_id))
        )
        assert len(hearings) == 2
        replacement = session.get(MatterHearing, replacement_id)
        assert replacement is not None
        assert replacement.status == MatterHearingStatus.ADJOURNED
        matter = session.get(Matter, matter_id)
        assert matter is not None
        assert matter.next_hearing_on == replacement_date
        assert matter.next_hearing_source_ref_id == replacement_id
