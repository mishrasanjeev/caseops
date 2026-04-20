"""Sprint M.1 — runtime enforcement of ``TenantAIPolicy`` on LLM calls.

Policy model + ``resolve_tenant_policy`` + ``is_model_allowed`` were
scaffolded earlier. This test battery verifies the wiring:

- No policy row → DEFAULT_POLICY with empty allow-lists → all models allowed.
- Policy row with allow-list that INCLUDES the model → call goes through.
- Policy row with allow-list that EXCLUDES the model → HTTP 403, no LLM call.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from caseops_api.db.models import Company, CompanyType, TenantAIPolicy, utcnow
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache, get_session_factory
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    generate_structured,
)


@pytest.fixture
def ephemeral_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point CASEOPS_DATABASE_URL at a fresh SQLite file in tmp_path.

    Mirrors the env overrides from ``conftest.py::client`` but without
    spinning up the FastAPI app — these tests exercise the policy layer
    directly against a Session, not via HTTP.
    """
    database_path = tmp_path / "caseops-policy-test.db"
    monkeypatch.setenv(
        "CASEOPS_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}"
    )
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "caseops-mock-1")
    monkeypatch.delenv("CASEOPS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_EMBEDDING_MODEL", "caseops-mock-embed")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    # Both caches must be invalidated — settings is @lru_cache'd, and the
    # engine factory memoises by settings identity. Without this, tests
    # inherit the parent shell's CASEOPS_DATABASE_URL (prod Cloud SQL).
    get_settings.cache_clear()
    clear_engine_cache()
    # Run migrations against the new SQLite file so the policy / company
    # tables exist.
    from caseops_api.db.base import Base
    from caseops_api.db.session import get_engine

    Base.metadata.create_all(get_engine())


class _ToyPayload(BaseModel):
    ok: bool


class _AlwaysOKProvider:
    """Toy provider that returns a JSON object matching ``_ToyPayload``."""

    name = "toy"
    model = "toy-model-1"

    def generate(self, *, messages, temperature, max_tokens):  # noqa: ANN001
        return LLMCompletion(
            provider=self.name,
            model=self.model,
            text='{"ok": true}',
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=0,
            raw=None,
        )


def _fresh_session_and_company(slug: str):
    """Create a throw-away company on a fresh SQLite session.

    Mirrors the pattern used elsewhere (test_eval_hnsw_recall, etc.):
    inline session construction, explicit disposal for Windows file-handle
    cleanup. Each test gets its own tenant so rows don't collide.
    """
    Session = get_session_factory()
    session = Session()
    company = Company(
        slug=slug,
        name=f"Test Co {slug}",
        company_type=CompanyType.LAW_FIRM,
        tenant_key=slug,
        created_at=utcnow(),
    )
    session.add(company)
    session.flush()
    return session, company


def _dispose(session) -> None:
    session.close()
    if session.bind is not None:
        session.bind.dispose()


def _make_policy(
    session,
    *,
    company_id: str,
    allowed_drafting: list[str] | None = None,
    allowed_recommendations: list[str] | None = None,
) -> TenantAIPolicy:
    row = TenantAIPolicy(
        company_id=company_id,
        allowed_models_drafting_json=(
            json.dumps(allowed_drafting) if allowed_drafting is not None else None
        ),
        allowed_models_recommendations_json=(
            json.dumps(allowed_recommendations)
            if allowed_recommendations is not None
            else None
        ),
        allowed_models_hearing_pack_json=None,
        max_tokens_per_session=16384,
        external_share_requires_approval=True,
        training_opt_in=False,
    )
    session.add(row)
    session.flush()
    return row


def test_no_policy_row_allows_any_model(ephemeral_db) -> None:
    """Absence of a row = default permissive policy."""
    session, company = _fresh_session_and_company("aip-none")
    try:
        provider: LLMProvider = _AlwaysOKProvider()  # type: ignore[assignment]
        payload, completion = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="hi")],
            context=LLMCallContext(tenant_id=company.id, purpose="drafting"),
            session=session,
        )
        assert payload.ok is True
        assert completion.model == "toy-model-1"
    finally:
        _dispose(session)


def test_allowed_model_in_policy_is_permitted(ephemeral_db) -> None:
    session, company = _fresh_session_and_company("aip-allow")
    try:
        _make_policy(
            session,
            company_id=company.id,
            allowed_drafting=["toy-model-1"],
        )
        provider: LLMProvider = _AlwaysOKProvider()  # type: ignore[assignment]
        payload, _ = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="hi")],
            context=LLMCallContext(tenant_id=company.id, purpose="drafting"),
            session=session,
        )
        assert payload.ok is True
    finally:
        _dispose(session)


def test_blocked_model_raises_403_before_llm_call(ephemeral_db) -> None:
    session, company = _fresh_session_and_company("aip-block")
    try:
        _make_policy(
            session,
            company_id=company.id,
            allowed_drafting=["claude-opus-4-7"],  # deliberately different
        )
        call_count = {"n": 0}

        class _Counting(_AlwaysOKProvider):
            def generate(self, **kwargs):
                call_count["n"] += 1
                return super().generate(**kwargs)

        with pytest.raises(HTTPException) as exc:
            generate_structured(
                _Counting(),  # type: ignore[arg-type]
                schema=_ToyPayload,
                messages=[LLMMessage(role="user", content="hi")],
                context=LLMCallContext(tenant_id=company.id, purpose="drafting"),
                session=session,
            )
        assert exc.value.status_code == 403
        assert "tenant ai policy" in str(exc.value.detail).lower()
        # Critical: the LLM must NOT have been called — policy gates *before*
        # tokens are spent.
        assert call_count["n"] == 0
    finally:
        _dispose(session)


def test_purpose_scoping_isolates_allow_lists(ephemeral_db) -> None:
    """Drafting allow-list doesn't constrain recommendations and vice versa."""
    session, company = _fresh_session_and_company("aip-scope")
    try:
        _make_policy(
            session,
            company_id=company.id,
            allowed_drafting=["claude-opus-4-7"],  # excludes toy-model-1
            allowed_recommendations=["toy-model-1"],
        )
        provider: LLMProvider = _AlwaysOKProvider()  # type: ignore[assignment]

        # Drafting with toy-model-1 → blocked.
        with pytest.raises(HTTPException) as exc:
            generate_structured(
                provider,
                schema=_ToyPayload,
                messages=[LLMMessage(role="user", content="hi")],
                context=LLMCallContext(tenant_id=company.id, purpose="drafting"),
                session=session,
            )
        assert exc.value.status_code == 403

        # Recommendations with toy-model-1 → allowed.
        payload, _ = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="hi")],
            context=LLMCallContext(tenant_id=company.id, purpose="recommendations"),
            session=session,
        )
        assert payload.ok is True
    finally:
        _dispose(session)


def test_no_session_skips_enforcement(ephemeral_db) -> None:
    """Callers that don't pass ``session`` (CLI, tests, legacy) bypass
    the policy gate entirely — DEFAULT_POLICY behaviour."""
    session, company = _fresh_session_and_company("aip-nosess")
    try:
        _make_policy(
            session,
            company_id=company.id,
            allowed_drafting=["nothing-matches"],
        )
        provider: LLMProvider = _AlwaysOKProvider()  # type: ignore[assignment]
        payload, _ = generate_structured(
            provider,
            schema=_ToyPayload,
            messages=[LLMMessage(role="user", content="hi")],
            context=LLMCallContext(tenant_id=company.id, purpose="drafting"),
            # session omitted intentionally
        )
        assert payload.ok is True
    finally:
        _dispose(session)
