"""Slice A (MOD-TS-001-B) — JudgeAppointment career-history tests.

Maps to FT-024C-1 .. FT-024C-5 in
``docs/PRD_BENCH_MAPPING_2026-04-25.md`` §3 Slice A.
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Judge, JudgeAppointment
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_judge(session, *, court_id: str, name: str) -> Judge:
    j = Judge(
        court_id=court_id,
        full_name=name,
        honorific="Justice",
        current_position=f"Judge of {court_id}",
        is_active=True,
    )
    session.add(j)
    session.flush()
    return j


def test_ft_024c_1_backfill_inserts_appointment_per_sc_judge(
    client: TestClient,
) -> None:
    """SC judge with parent_high_court text should produce ≥ 1
    JudgeAppointment row covering the prior HC AND the current SC
    appointment. Exercises the real seed_data JSON shipped with the
    repo so a regression in the parser is caught."""
    from caseops_api.db.session import get_session_factory
    from caseops_api.scripts.backfill_sc_judge_career import _backfill
    from caseops_api.scripts.seed_sci_judges import _seed as _seed_sci

    # Bootstrap establishes the test company; we just need DB ready.
    bootstrap_company(client)
    with get_session_factory()() as session:
        _seed_sci(session)
        sci, _scu, hci = _backfill(session)
    assert sci > 0, "expected SC current-appointment rows on first run"
    # The seed JSON has at least 4 entries that map to one of our 6
    # known HCs (Bombay, Delhi, Karnataka, Madras, Telangana, Patna).
    assert hci > 0, "expected at least one HC prior-appointment row"


def test_ft_024c_2_sitting_judge_current_appointment_has_null_end_date(
    client: TestClient,
) -> None:
    """The current-court appointment row uses end_date IS NULL —
    that's how the UI knows which row is the active one."""
    from caseops_api.db.session import get_session_factory

    bootstrap_company(client)
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="supreme-court-india", name="Test Sitting Judge",
        )
        s.add(
            JudgeAppointment(
                judge_id=judge.id,
                court_id="supreme-court-india",
                role="judge_supreme_court",
                start_date=date(2025, 1, 1),
                end_date=None,
                source_url="https://example.test/judge",
                source_evidence_text="Sworn in.",
            ),
        )
        s.commit()
        appts = list(
            s.scalars(
                select(JudgeAppointment).where(
                    JudgeAppointment.judge_id == judge.id
                )
            ).all()
        )
        assert len(appts) == 1
        assert appts[0].end_date is None, (
            "sitting appointment must have end_date IS NULL"
        )


def test_ft_024c_3_inactive_judge_filtered_from_court_listing(
    client: TestClient,
) -> None:
    """Tenant-isolation + soft-delete coverage. An inactive judge
    must not appear in the court's public judges list, even if
    JudgeAppointment rows exist for it."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        judge = Judge(
            court_id="bombay-hc",
            full_name="Justice Inactive",
            is_active=False,
        )
        s.add(judge)
        s.flush()
        s.add(
            JudgeAppointment(
                judge_id=judge.id, court_id="bombay-hc",
                role="puisne_judge",
                source_url="https://example.test",
                source_evidence_text="—",
            ),
        )
        s.commit()

    judges_resp = client.get(
        "/api/courts/bombay-hc/judges", headers=auth_headers(token),
    )
    assert judges_resp.status_code == 200
    names = {j["full_name"] for j in judges_resp.json()["judges"]}
    assert "Justice Inactive" not in names, (
        "list_court_judges filters on is_active; soft-deleted leak"
    )


def test_ft_024c_4_career_endpoint_surfaces_source_url(
    client: TestClient,
) -> None:
    """Profile route returns career[].source_url so the UI can render
    a clickable verifiable link to sci.gov.in / HC site."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="supreme-court-india",
            name="Justice Career Url Test",
        )
        s.add(
            JudgeAppointment(
                judge_id=judge.id,
                court_id="supreme-court-india",
                role="judge_supreme_court",
                start_date=date(2024, 5, 1),
                source_url="https://www.sci.gov.in/judge/test/",
                source_evidence_text="Elevated as Judge of the SC.",
            ),
        )
        s.commit()
        judge_id = judge.id

    resp = client.get(
        f"/api/courts/judges/{judge_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "career" in body
    assert len(body["career"]) >= 1
    appt = body["career"][0]
    assert appt["source_url"] == "https://www.sci.gov.in/judge/test/"
    assert appt["source_evidence_text"]
    assert appt["court_name"] == "Supreme Court of India"


def test_ft_024c_5_empty_career_returns_empty_array_not_null(
    client: TestClient,
) -> None:
    """An HC judge before the per-HC scraper runs has no
    JudgeAppointment rows. The profile must return ``career: []``
    (empty array, never null) so the UI's empty-state branch fires
    cleanly without a TypeError."""
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        judge = _seed_judge(
            s, court_id="bombay-hc", name="Justice No Career Yet",
        )
        s.commit()
        judge_id = judge.id

    resp = client.get(
        f"/api/courts/judges/{judge_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["career"] == [], (
        "must serialise as [] not null — UI's career.length check "
        "would TypeError on null"
    )
