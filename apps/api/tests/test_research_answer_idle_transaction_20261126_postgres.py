"""Research answer retrieval must not hold a transaction open (FT-116).

Production prod-verify 45856740774 (release e492d6472) failed the Section 138
phone run: retrieval read the corpus, then spent over a minute embedding and
reranking, and PostgreSQL's idle-in-transaction timeout (60 s) killed the
connection before the next read. The job ended ``failed/internal_error``.
This reproduces that with a one-second server timeout and a slow retrieval.
"""

from __future__ import annotations

import time

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.services import research_answers as service
from tests.test_auth_company import bootstrap_company
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_research_answers_20261124 import _ask, _seed_sources

pytestmark = pytest.mark.postgres

IDLE_TIMEOUT_MS = 1_000


def test_slow_retrieval_outlives_the_idle_transaction_timeout(
    isolated_postgres_client, monkeypatch
) -> None:
    client = isolated_postgres_client
    _seed_sources()
    token = bootstrap_company(client)["access_token"]

    monkeypatch.setenv("CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS", str(IDLE_TIMEOUT_MS))
    get_settings.cache_clear()
    clear_engine_cache()
    original = service._retrieve_judgments
    calls = []

    def slow_retrieval(session, query, **kwargs):
        judgments = original(session, query, **kwargs)
        # The reranker's CPU time after the last corpus read.
        time.sleep(IDLE_TIMEOUT_MS / 1000 * 2)
        calls.append(len(judgments))
        return judgments

    monkeypatch.setattr(service, "_retrieve_judgments", slow_retrieval)

    record = _ask(client, token)

    assert calls == [1], calls
    assert record["status"] == "answered", (record["error_code"], record["message"])
    kinds = {source["kind"] for source in record["sources"]}
    assert kinds == {"statute_section", "judgment"}
