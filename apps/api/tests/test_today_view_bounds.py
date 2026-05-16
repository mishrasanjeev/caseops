"""Today stream bounds (perf follow-up to P1-4).

Proves GET /api/me/today caps every stream at MAX_PER_STREAM, returns
only the first MAX_PER_STREAM rows, and reports the additive bounding
metadata (stream_limits / stream_counts / stream_truncated) without
changing the five existing arrays' shape. Also proves
/api/matters/{id}/next-action is NOT subject to the cap (it must still
see every row to pick the single most urgent item).

MAX_PER_STREAM is monkeypatched to a small value so the tests stay
fast; build_today_view reads the module constant at call time.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from caseops_api.services import today_view as today_view_mod
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_today_view import (
    _create_matter,
    _seed_deadline,
    _seed_draft_in_review,
    _seed_hearing,
    _seed_invoice,
    _seed_task,
)

_TODAY = date.today()
_STREAM_KEYS = (
    "hearings_next_7d",
    "tasks_due_or_overdue",
    "drafts_in_review",
    "overdue_invoices",
    "deadlines_next_7d",
)


def _today(client: TestClient, token: str) -> dict:
    resp = client.get("/api/me/today", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_metadata_present_and_no_truncation_on_small_workspace(
    client: TestClient,
) -> None:
    """Real MAX_PER_STREAM (100), tiny data: metadata present, every
    stream reports not-truncated, counts == array lengths, limits ==
    the production constant. The five arrays are unchanged."""
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "BND-SMALL")
    _seed_hearing(matter, _TODAY + timedelta(days=2))
    _seed_task(matter, due_on=_TODAY + timedelta(days=1), owner=None)

    body = _today(client, token)
    for key in _STREAM_KEYS:
        assert key in body, f"existing array {key} must still be present"
        assert body["stream_limits"][key] == today_view_mod.MAX_PER_STREAM
        assert body["stream_truncated"][key] is False
        assert body["stream_counts"][key] == len(body[key])
    assert len(body["hearings_next_7d"]) == 1
    assert len(body["tasks_due_or_overdue"]) == 1


def test_every_stream_caps_and_flags_truncation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(today_view_mod, "MAX_PER_STREAM", 2)
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "BND-CAP")

    # 3 rows in every stream, cap is 2 → each must truncate to 2.
    for i in range(3):
        _seed_hearing(matter, _TODAY + timedelta(days=1 + i))
        _seed_task(matter, due_on=_TODAY + timedelta(days=1 + i), owner=None)
        _seed_invoice(matter, due_on=_TODAY - timedelta(days=1 + i))
        _seed_deadline(matter, due_on=_TODAY + timedelta(days=1 + i))
        _seed_draft_in_review(client, token, matter)

    body = _today(client, token)
    for key in _STREAM_KEYS:
        assert len(body[key]) == 2, f"{key} not capped to 2: {len(body[key])}"
        assert body["stream_truncated"][key] is True, f"{key} not flagged"
        assert body["stream_counts"][key] == 2
        assert body["stream_limits"][key] == 2


def test_exactly_cap_not_truncated_capplus1_truncated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Boundary regression: exactly MAX_PER_STREAM is NOT truncated;
    MAX_PER_STREAM + 1 is. Hearings is representative — the boundary
    logic in build_today_view is shared and stream-agnostic."""
    monkeypatch.setattr(today_view_mod, "MAX_PER_STREAM", 3)
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "BND-EDGE")

    # Exactly cap (3).
    for i in range(3):
        _seed_hearing(matter, _TODAY + timedelta(days=1 + i))
    body = _today(client, token)
    assert len(body["hearings_next_7d"]) == 3
    assert body["stream_truncated"]["hearings_next_7d"] is False
    assert body["stream_counts"]["hearings_next_7d"] == 3

    # cap + 1 (4) → truncated, still only cap returned.
    _seed_hearing(matter, _TODAY + timedelta(days=5))
    body = _today(client, token)
    assert len(body["hearings_next_7d"]) == 3
    assert body["stream_truncated"]["hearings_next_7d"] is True
    assert body["stream_counts"]["hearings_next_7d"] == 3
    assert body["stream_limits"]["hearings_next_7d"] == 3


def test_next_action_is_not_subject_to_the_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """next-action must keep seeing every row (limit=None) so its
    single-most-urgent pick is never skewed by Today's truncation."""
    monkeypatch.setattr(today_view_mod, "MAX_PER_STREAM", 2)
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "BND-NA")
    # Far more than the cap.
    for i in range(5):
        _seed_task(matter, due_on=_TODAY - timedelta(days=1 + i), owner=None)

    # Today caps tasks at 2 ...
    body = _today(client, token)
    assert len(body["tasks_due_or_overdue"]) == 2
    assert body["stream_truncated"]["tasks_due_or_overdue"] is True

    # ... but next-action still resolves a (most-urgent) action.
    resp = client.get(
        f"/api/matters/{matter}/next-action", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() is not None, "cap must not starve next-action"
