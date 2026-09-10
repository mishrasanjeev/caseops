"""Bounded, fail-closed readiness before Uvicorn opens the serving socket."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from threading import Thread
from time import perf_counter

from caseops_api.services.virus_scan import _config_from_env

logger = logging.getLogger(__name__)
SCANNER_STARTUP_BUDGET_SECONDS = 60.0
SCANNER_ATTEMPT_SECONDS = 2.0
SCANNER_POLL_SECONDS = 0.25
READINESS_BUDGET_SECONDS = 60.0


def warm_database_mappers() -> None:
    """Resolve the in-memory ORM graph before the first authenticated query."""
    from caseops_api.db.models import Base

    started = perf_counter()
    Base.registry.configure()
    logger.info("Startup ORM ready duration_seconds=%.3f", perf_counter() - started)


async def wait_for_native_warmup(warmup: Callable[[], object]) -> None:
    """A wedged native initializer must neither serve nor hold process exit open."""
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    started = perf_counter()

    def finish(result: object, error: BaseException | None) -> None:
        if completed.done():
            return
        if error is not None:
            completed.set_exception(error)
        else:
            completed.set_result(result)

    def initialize() -> None:
        error = None
        result = None
        try:
            result = warmup()
        except BaseException as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(finish, result, error)
        except RuntimeError:
            # The failed startup has already closed its event loop.
            pass

    Thread(target=initialize, name="caseops-native-warmup", daemon=True).start()
    result = await completed
    provider = getattr(result, "name", "unknown")
    if provider not in {"fastembed", "mock", "llm-judge"}:
        provider = "unknown"
    logger.info(
        "Startup native ready duration_seconds=%.3f provider=%s",
        perf_counter() - started,
        provider,
    )


async def wait_for_readiness(warmup: Callable[[], object]) -> None:
    """One deadline covers both concurrent checks, including native warm-up."""
    try:
        async with asyncio.timeout(READINESS_BUDGET_SECONDS):
            async with asyncio.TaskGroup() as readiness:
                readiness.create_task(wait_for_required_scanner())
                readiness.create_task(wait_for_native_warmup(warmup))
    except TimeoutError:
        raise RuntimeError("Application readiness did not complete in time") from None


async def _ping_scanner(host: str, port: int) -> None:
    writer = None
    try:
        async with asyncio.timeout(SCANNER_ATTEMPT_SECONDS):
            reader, writer = await asyncio.open_connection(host, port, limit=32)
            writer.write(b"zPING\0")
            await writer.drain()
            if await reader.readuntil(b"\0") != b"PONG\0":
                raise ValueError("Unexpected scanner readiness response")
    finally:
        if writer is not None:
            writer.close()


async def wait_for_required_scanner() -> None:
    """Allow parallel container initialization, never unscanned serving.

    The entire connect/write/read/poll sequence has one deadline. Every upload
    still performs its normal scan; a startup PONG is not cached scan approval.
    """
    host, port, _scan_timeout, required = _config_from_env()
    if not required:
        return
    if not host:
        raise RuntimeError("Required malware scanner is not configured")
    started = perf_counter()
    attempts = 0
    try:
        async with asyncio.timeout(SCANNER_STARTUP_BUDGET_SECONDS):
            while True:
                attempts += 1
                try:
                    await _ping_scanner(host, port)
                    break
                except (
                    OSError,
                    TimeoutError,
                    ValueError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                ):
                    await asyncio.sleep(SCANNER_POLL_SECONDS)
    except TimeoutError:
        raise RuntimeError("Required malware scanner did not become ready in time") from None
    logger.info(
        "Startup scanner ready duration_seconds=%.3f attempts=%d",
        perf_counter() - started,
        attempts,
    )
