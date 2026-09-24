"""Release backfill accepts production-sized tenant history and remains replayable."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select

from caseops_api.db.models import Matter, MatterHearing, MatterNextHearingHistory
from caseops_api.db.session import get_session_factory
from caseops_api.scripts import backfill_next_hearings as command
from tests.test_auth_company import bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_release_backfill_materializes_1200_legacy_dates_and_replays(
    isolated_postgres_client, monkeypatch, capsys
) -> None:
    boot = bootstrap_company(isolated_postgres_client)
    company_id = str(boot["company"]["id"])
    hearing_on = date(2026, 11, 4)
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
        session.commit()

    assert command.main() == 0
    output = capsys.readouterr().out
    assert f'"{company_id}": 1200' in output
    with get_session_factory()() as session:
        for model in (MatterHearing, MatterNextHearingHistory):
            assert session.scalar(
                select(func.count()).select_from(model).where(model.company_id == company_id)
            ) == 1200
    assert command.main() == 0
    output = capsys.readouterr().out
    assert f'"{company_id}": 0' in output
    with get_session_factory()() as session:
        for model in (MatterHearing, MatterNextHearingHistory):
            assert session.scalar(
                select(func.count()).select_from(model).where(model.company_id == company_id)
            ) == 1200
