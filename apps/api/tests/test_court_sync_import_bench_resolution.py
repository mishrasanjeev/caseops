"""MOD-TS-018 (2026-04-26 PM): inline bench resolution on court-sync import.

Before this change, POST /api/matters/{id}/court-sync/import wrote
bench_name as a free-text string but left judges_json NULL until the
periodic resolve_cause_list_benches.py job ran. That meant the
bench-strategy panel showed "insufficient evidence" right after a
lawyer attached a listing, even when the bench was a known judge.

This test proves: the resolver runs INLINE inside the import service,
so judges_json is populated by the time the response returns.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from caseops_api.db.models import Court, Judge, JudgeAlias
from caseops_api.db.session import get_session_factory
from caseops_api.services.judge_aliases import normalise
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_court_and_judge(session, court_name: str, judge_full_name: str) -> tuple[str, str]:
    """Insert (or reuse) a Court + Judge + JudgeAlias for the test.
    Returns (court_id, judge_id). court_name/short_name are used as
    look-up keys to avoid UNIQUE-violation on re-seed."""
    court = session.query(Court).filter(Court.name == court_name).first()
    if court is None:
        court = Court(
            id=str(uuid4()), name=court_name, short_name=court_name[:32],
            forum_level="high_court", jurisdiction="india", is_active=True,
        )
        session.add(court)
        session.flush()

    judge = (
        session.query(Judge)
        .filter(Judge.court_id == court.id, Judge.full_name == judge_full_name)
        .first()
    )
    if judge is None:
        judge = Judge(
            id=str(uuid4()), court_id=court.id, full_name=judge_full_name,
            honorific="Justice", is_active=True,
        )
        session.add(judge)
        session.flush()
        for alias in (
            judge_full_name,
            f"Justice {judge_full_name}",
            f"Hon'ble Mr. Justice {judge_full_name}",
        ):
            session.add(JudgeAlias(
                id=str(uuid4()), judge_id=judge.id,
                alias_text=alias, alias_normalised=normalise(alias),
                source="test_seed",
            ))
    session.commit()
    return court.id, judge.id


def test_court_sync_import_resolves_judges_inline(client: TestClient) -> None:
    """POST /court-sync/import with a known judge in bench_name should
    populate judges_json IMMEDIATELY (no periodic job required)."""
    session_factory = get_session_factory()
    with session_factory() as session:
        court_id, judge_id = _seed_court_and_judge(
            session, "Test High Court Inline", "Inline TestJudge",
        )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Inline bench resolution test",
            "matter_code": "INLINE-2026-001",
            "client_name": "TestClient Co.",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert matter_resp.status_code == 200, matter_resp.text
    matter_id = matter_resp.json()["id"]

    # MatterCreateRequest doesn't expose court_id (derived from
    # court_name in some flows; not set in others). For this test we
    # need a deterministic court_id so resolve_listing_bench has the
    # court scope it requires. Set it directly via SQL.
    with session_factory() as session:
        session.execute(
            text("UPDATE matters SET court_id = :cid WHERE id = :mid"),
            {"cid": court_id, "mid": matter_id},
        )
        session.commit()

    sync_resp = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "manual",
            "summary": "Manual listing entry for inline-resolution test.",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-01",
                    "forum_name": "Test High Court Inline",
                    "bench_name": "Justice Inline TestJudge",
                    "courtroom": "Court 1",
                    "item_number": "1",
                    "stage": "Hearing",
                }
            ],
            "orders": [],
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text

    # Verify judges_json was populated by the inline resolver.
    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT judges_json FROM matter_cause_list_entries "
                "WHERE matter_id = :mid"
            ),
            {"mid": matter_id},
        ).fetchone()
    assert row is not None
    assert row[0] is not None, "judges_json should be populated by inline resolver"
    assert "Inline TestJudge" in row[0] or judge_id in row[0]


def test_court_sync_import_resolves_judges_when_court_id_falls_back_to_forum_name(
    client: TestClient,
) -> None:
    """Bench resolver must fall back to forum_name → Court lookup when
    matter.court_id is NULL. Real lawyer flow: matter created with
    court_name only, no court_id set yet, then a listing is imported.
    Without the fallback, judges_json stays NULL and bench-strategy
    shows 'insufficient' even when the judge IS in our catalogue."""
    forum_name = "Test High Court Fallback"
    judge_full_name = "Fallback TestJudge"
    session_factory = get_session_factory()
    with session_factory() as session:
        _, judge_id = _seed_court_and_judge(session, forum_name, judge_full_name)

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Fallback bench test",
            "matter_code": "FALLBACK-2026-001",
            "client_name": "TestClient Co.",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": forum_name,
        },
    )
    assert matter_resp.status_code == 200, matter_resp.text
    matter_id = matter_resp.json()["id"]
    # NOTE: deliberately NOT setting court_id — that's the bug we test.

    sync_resp = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "manual",
            "summary": "Listing where matter has no court_id, only court_name.",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-10",
                    "forum_name": forum_name,
                    "bench_name": f"Justice {judge_full_name}",
                }
            ],
            "orders": [],
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text

    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT judges_json FROM matter_cause_list_entries "
                "WHERE matter_id = :mid"
            ),
            {"mid": matter_id},
        ).fetchone()
    assert row is not None
    assert row[0] is not None, (
        "judges_json should be populated even when matter.court_id is NULL "
        "— the resolver must fall back to forum_name → Court lookup"
    )
    assert judge_full_name in row[0] or judge_id in row[0]


def test_bench_strategy_reads_dict_shaped_judges_json_after_inline_resolution(
    client: TestClient,
) -> None:
    """End-to-end: lawyer creates matter → imports listing with known
    judge → GET /bench-strategy returns populated bench_judge_ids.

    Regression guard for the bug where _resolve_bench_judge_ids
    iterated judges_json expecting string names but the resolver
    writes dicts ({judge_id, matched_alias, confidence}). All dicts
    were skipped → bench_judge_ids stayed [] → panel showed
    'insufficient' even after the inline resolver fired.

    Skipped on SQLite — build_bench_strategy uses Postgres-only ANY()
    in the judge_decision_index count + L-B/L-C aggregate queries."""
    session_factory = get_session_factory()
    with session_factory() as session:
        if session.bind.dialect.name != "postgresql":
            import pytest
            pytest.skip("build_bench_strategy uses Postgres-only ANY() syntax")
    forum_name = "Test High Court Endto"
    judge_full_name = "Endto TestJudge"
    with session_factory() as session:
        _, judge_id = _seed_court_and_judge(session, forum_name, judge_full_name)

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "End-to-end bench strategy test",
            "matter_code": "ENDTO-2026-001",
            "client_name": "TestClient Co.",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": forum_name,
        },
    )
    assert matter_resp.status_code == 200, matter_resp.text
    matter_id = matter_resp.json()["id"]

    sync_resp = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "manual",
            "summary": "End-to-end bench-strategy probe.",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-20",
                    "forum_name": forum_name,
                    "bench_name": f"Justice {judge_full_name}",
                }
            ],
            "orders": [],
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text

    bs_resp = client.get(
        f"/api/matters/{matter_id}/bench-strategy",
        headers=auth_headers(token),
    )
    assert bs_resp.status_code == 200, bs_resp.text
    bs = bs_resp.json()
    assert judge_id in bs["bench_judge_ids"], (
        f"bench_strategy must extract judge_id from dict-shaped judges_json. "
        f"Got bench_judge_ids={bs['bench_judge_ids']!r} expected to contain {judge_id!r}"
    )


def test_court_sync_import_with_unknown_judge_does_not_break_import(
    client: TestClient,
) -> None:
    """If bench_name doesn't match any judge alias, judges_json should
    be set to "[]" (processed but no match) — and the import itself
    must still succeed."""
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Unknown bench test",
            "matter_code": "UNKNOWN-2026-001",
            "client_name": "TestClient Co.",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_resp.json()["id"]

    sync_resp = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "manual",
            "summary": "Listing with unrecognised bench.",
            "cause_list_entries": [
                {
                    "listing_date": "2026-05-02",
                    "forum_name": "Some Court",
                    "bench_name": "Justice Nobody Known",
                }
            ],
            "orders": [],
        },
    )
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] == "completed"
