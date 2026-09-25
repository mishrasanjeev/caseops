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
from tests.test_auth_company import bootstrap_company
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
