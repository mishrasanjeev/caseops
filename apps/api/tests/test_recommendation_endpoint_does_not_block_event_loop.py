"""Recommendation generation must not pin the async API event loop.

Production runs one request per Cloud Run instance. Ram 2026-09-02 BUG-004
proved that the strict-schema recommendation provider can consume the full
platform request deadline. The endpoint still needs a bounded provider call,
but that slow synchronous work must also be isolated so health and unrelated
reads on the process event loop remain responsive.
"""

from __future__ import annotations

import asyncio
import inspect
import time

import pytest
from fastapi import HTTPException

from caseops_api.api.routes import recommendations
from caseops_api.schemas.recommendations import RecommendationGenerateRequest


def test_recommendation_generation_is_offloaded_as_one_synchronous_unit() -> None:
    source = inspect.getsource(recommendations.create_recommendation)

    assert "await run_in_threadpool(" in source
    assert "run_in_threadpool(\n        generate_recommendation," in source
    assert "recommendation = generate_recommendation(" not in source


def test_slow_recommendation_provider_leaves_event_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_delay_seconds = 0.35

    def slow_provider(*_args: object, **_kwargs: object) -> None:
        time.sleep(provider_delay_seconds)
        raise HTTPException(status_code=503, detail="controlled provider delay")

    monkeypatch.setattr(recommendations, "generate_recommendation", slow_provider)
    route_implementation = inspect.unwrap(recommendations.create_recommendation)

    async def exercise() -> float:
        started_at = time.perf_counter()
        request_task = asyncio.create_task(
            route_implementation(
                request=None,  # type: ignore[arg-type]
                matter_id="matter-under-test",
                payload=RecommendationGenerateRequest(type="authority"),
                context=None,  # type: ignore[arg-type]
                session=None,  # type: ignore[arg-type]
            )
        )
        await asyncio.sleep(0.03)
        event_loop_tick_seconds = time.perf_counter() - started_at
        with pytest.raises(HTTPException, match="controlled provider delay"):
            await request_task
        return event_loop_tick_seconds

    # A direct synchronous provider call in the async route delays this tick
    # by the full provider sleep. Thread-pool isolation lets unrelated async
    # work proceed immediately.
    assert asyncio.run(exercise()) < provider_delay_seconds / 2
