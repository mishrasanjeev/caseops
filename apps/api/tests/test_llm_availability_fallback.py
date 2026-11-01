"""OpenAI availability fallback to managed gemini-3.8-flash (owner decision 2026-11-01).

Offline only: OpenAI and Gemini are deterministic emulators or the native SDK
behind an in-process transport. Covers the trigger rules, one attempt per
request inside the caller's deadline, the tenant AI policy, the no-paid marker,
cap refusals surfacing the primary failure, unchanged validators and recorded
provenance on drafting, contracts, recommendations and a job path (compliance
extraction run by the document-processing job).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import ModelRun
from caseops_api.db.session import get_session_factory
from caseops_api.services import gemini_spend_cap, llm
from caseops_api.services.ai_money_budget import AiMoneyBudgetError
from caseops_api.services.llm import (
    AvailabilityFallbackProvider,
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    MockProvider,
)
from caseops_api.services.llm_http import provider_failure_http_exception
from caseops_api.services.llm_types import (
    LLMDailyCapReachedError,
    LLMProviderError,
    LLMQuotaExhaustedError,
    LLMResponseFormatError,
    LLMTransientProviderError,
)
from tests import test_ai_policy_enforcement, test_gemini_flash_lite_provider

ephemeral_db = test_ai_policy_enforcement.ephemeral_db
sdk = test_gemini_flash_lite_provider.sdk
FALLBACK_MODEL = "gemini-3.8-flash"
_QUOTA = "OpenAI quota exhausted. Check the provider billing account."
_TRANSIENT = "OpenAI is temporarily unavailable or the request timed out."


class _Primary(MockProvider):
    """OpenAI stand-in: fails with ``error`` or answers like the mock."""

    name = "openai"

    def __init__(self, error: BaseException | None = None, *, on_call=None) -> None:
        super().__init__("gpt-5.1")
        self.error = error
        self.on_call = on_call
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        return super().generate(messages, **kwargs)


class _Gemini(MockProvider):
    """Managed Gemini stand-in; ``text`` overrides the mock answer."""

    name = "gemini"

    def __init__(self, *, text: str | None = None, error: BaseException | None = None) -> None:
        super().__init__(FALLBACK_MODEL)
        self.text = text
        self.error = error
        self.calls = 0
        self.deadlines: list[float | None] = []

    def generate(self, messages, **kwargs):
        self.calls += 1
        self.deadlines.append(llm._provider_deadline.get())
        if self.error is not None:
            raise self.error
        if self.text is None:
            return super().generate(messages, **kwargs)
        return LLMCompletion(
            text=self.text, provider=self.name, model=self.model,
            prompt_tokens=3, completion_tokens=5, latency_ms=1,
        )


def _wrap(primary, gemini, *, budget: float = 60.0, timeouts: list | None = None):
    def factory(*, timeout_seconds):
        if timeouts is not None:
            timeouts.append(timeout_seconds)
        return gemini

    return AvailabilityFallbackProvider(
        primary, purpose="drafting", budget_seconds=budget, fallback_factory=factory
    )


class _Toy(BaseModel):
    ok: bool


def _messages():
    return [LLMMessage(role="user", content="Offline source fixture")]


@pytest.fixture
def openai_env(monkeypatch):
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "offline-not-a-real-key")
    monkeypatch.delenv("CASEOPS_LLM_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("CASEOPS_LLM_GEMINI_PROJECT", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _enable(monkeypatch):
    monkeypatch.setenv("CASEOPS_LLM_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_LLM_GEMINI_PROJECT", "offline-caseops-project")
    get_settings.cache_clear()


# --- settings and construction ------------------------------------------------


@pytest.mark.parametrize(
    "purpose",
    [None, "drafting", "assistant", "recommendations", "hearing_pack", "metadata_extract",
     "case_tracking:update_summary"],
)
def test_disabled_by_default_builds_the_unchanged_primary(openai_env, purpose):
    settings = get_settings()
    assert settings.llm_fallback_enabled is False
    assert settings.llm_fallback_model == FALLBACK_MODEL
    provider = llm.build_provider(purpose)
    assert type(provider) is llm.OpenAIProvider


@pytest.mark.parametrize(
    ("purpose", "budget"),
    [
        ("drafting", 240.0),  # 120 s per attempt, one SDK retry
        ("assistant", 120.0),
        ("recommendations", 100.0),
        ("hearing_pack", 180.0),
        ("metadata_extract", 60.0),
        ("case_tracking:update_summary", 45.0),
        (None, 180.0),
    ],
)
def test_enabled_wraps_openai_within_the_existing_worst_case_budget(openai_env, purpose, budget):
    _enable(openai_env)
    provider = llm.build_provider(purpose)
    assert isinstance(provider, AvailabilityFallbackProvider)
    assert type(provider.primary) is llm.OpenAIProvider
    assert provider._budget_seconds == budget
    assert (provider.name, provider.model, provider.fallback_model) == (
        "openai", provider.primary.model, FALLBACK_MODEL
    )
    explicit = llm.build_provider(purpose, timeout_seconds=12.5)
    assert explicit._budget_seconds == 12.5


def test_opt_out_mock_primary_and_no_paid_marker_are_never_wrapped(openai_env):
    _enable(openai_env)
    assert type(llm.build_provider("drafting", availability_fallback=False)) is llm.OpenAIProvider
    marker = set_automated_test_request("no-paid-providers")
    try:
        assert type(llm.build_provider("drafting")) is MockProvider
    finally:
        reset_automated_test_request(marker)
    openai_env.setenv("CASEOPS_LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    assert type(llm.build_provider("drafting")) is MockProvider


def test_enabled_without_project_fails_closed(openai_env):
    openai_env.setenv("CASEOPS_LLM_FALLBACK_ENABLED", "true")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="CASEOPS_LLM_GEMINI_PROJECT"):
        get_settings()


def test_fallback_builder_is_managed_and_pinned(openai_env):
    captured = []
    openai_env.setattr(llm, "GeminiProvider", lambda **kwargs: captured.append(kwargs))
    with pytest.raises(LLMProviderError, match="not configured"):
        llm.build_gemini_fallback(timeout_seconds=10.0)
    _enable(openai_env)
    llm.build_gemini_fallback(timeout_seconds=10.0)
    assert captured == [
        {
            "model": FALLBACK_MODEL,
            "api_key": None,
            "project": "offline-caseops-project",
            "location": "global",
            "timeout_seconds": 10.0,
        }
    ]


def test_only_corpus_eval_and_best_effort_paths_opt_out():
    """New LLM call sites get the fallback unless an opt-out is reviewed here."""
    root = Path(__file__).resolve().parents[1] / "src" / "caseops_api"
    opted_out = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        # llm.py defines the switch; every other mention is a reviewed opt-out.
        if path.name != "llm.py"
        and "availability_fallback=False" in path.read_text(encoding="utf-8")
    )
    assert opted_out == [
        "scripts/eval_drafting_quality.py",
        "scripts/eval_drafting_types.py",
        "scripts/eval_hnsw_recall.py",
        "scripts/extract_authority_metadata.py",
        "scripts/reextract_placeholder_titles.py",
        "services/corpus_structured.py",
        # Recommendations own the source-revalidating fallback plan.
        "services/recommendations.py",
        "services/reranker.py",
        "services/retrieval_normalisers.py",
        "services/statute_enrichment.py",
    ]


# --- trigger rules --------------------------------------------------------------


@pytest.mark.parametrize(
    "error", [LLMQuotaExhaustedError(_QUOTA), LLMTransientProviderError(_TRANSIENT)]
)
@pytest.mark.parametrize("mode", ["text", "structured"])
def test_quota_or_transient_primary_failure_switches_once(error, mode):
    primary, gemini, timeouts = _Primary(error), _Gemini(text='{"ok": true}'), []
    provider = _wrap(primary, gemini, timeouts=timeouts)
    if mode == "structured":
        payload, completion = llm.generate_structured(
            provider, schema=_Toy, messages=_messages(), context=LLMCallContext(purpose="drafting")
        )
        assert payload.ok is True
    else:
        completion = provider.generate(_messages())
    assert (completion.provider, completion.model) == ("gemini", FALLBACK_MODEL)
    assert (provider.name, provider.model) == ("gemini", FALLBACK_MODEL)
    assert primary.calls == gemini.calls == 1
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 60.0


@pytest.mark.parametrize(
    "error",
    [
        LLMResponseFormatError("OpenAI:gpt-5.1 structured response refused."),
        LLMResponseFormatError("OpenAI:gpt-5.1 did not complete the required structured response."),
        AiMoneyBudgetError("The shared monthly AI budget is exhausted."),
        LLMDailyCapReachedError("Daily cap reached."),
        LLMProviderError("OpenAI call failed. Check provider configuration."),
        HTTPException(status_code=403, detail="Tenant policy denied."),
    ],
    ids=["refusal", "schema", "budget", "daily-cap", "configuration", "policy"],
)
def test_refusal_schema_safety_policy_and_budget_failures_never_switch(error):
    primary, gemini, timeouts = _Primary(error), _Gemini(), []
    provider = _wrap(primary, gemini, timeouts=timeouts)
    with pytest.raises(type(error)) as caught:
        provider.generate(_messages())
    assert caught.value is error
    assert timeouts == [] and gemini.calls == 0
    assert provider.fallback_attempted is False


def test_no_paid_marker_blocks_both_providers():
    markers = []
    primary = _Primary(
        LLMTransientProviderError(_TRANSIENT),
        on_call=lambda: markers.append(set_automated_test_request("no-paid-providers")),
    )
    gemini, timeouts = _Gemini(), []
    provider = _wrap(primary, gemini, timeouts=timeouts)
    try:
        with pytest.raises(AiMoneyBudgetError, match="Automated verification"):
            provider.generate(_messages())
        # The managed builder and the cap refuse independently, before any SDK.
        with pytest.raises(AiMoneyBudgetError, match="Automated verification"):
            llm.build_gemini_fallback(timeout_seconds=5.0)
        with pytest.raises(AiMoneyBudgetError, match="Automated verification"):
            gemini_spend_cap.reserve_gemini_spend(
                model=FALLBACK_MODEL, input_bytes=10, output_tokens=10
            )
    finally:
        for token in reversed(markers):
            reset_automated_test_request(token)
    assert timeouts == [] and gemini.calls == 0


def test_one_fallback_attempt_per_request():
    primary, gemini, timeouts = _Primary(LLMTransientProviderError(_TRANSIENT)), _Gemini(), []
    provider = _wrap(primary, gemini, timeouts=timeouts)
    assert provider.generate(_messages()).provider == "gemini"
    with pytest.raises(LLMTransientProviderError) as caught:
        provider.generate(_messages())
    assert str(caught.value) == _TRANSIENT
    assert primary.calls == 2 and gemini.calls == 1 and len(timeouts) == 1
    assert (provider.name, provider.model) == ("openai", "gpt-5.1")


def test_fallback_runs_inside_the_primary_deadline(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(llm.time, "perf_counter", lambda: clock[0])

    def slow():
        clock[0] += 45.0

    primary, gemini, timeouts = _Primary(LLMTransientProviderError(_TRANSIENT), on_call=slow), (
        _Gemini()
    ), []
    provider = _wrap(primary, gemini, budget=60.0, timeouts=timeouts)
    provider.generate(_messages())
    assert timeouts == [15.0]
    assert gemini.deadlines == [1060.0]

    late = _Primary(
        LLMTransientProviderError(_TRANSIENT), on_call=lambda: clock.__setitem__(0, clock[0] + 59.5)
    )
    unused, late_timeouts = _Gemini(), []
    with pytest.raises(LLMTransientProviderError):
        _wrap(late, unused, budget=60.0, timeouts=late_timeouts).generate(_messages())
    assert late_timeouts == [] and unused.calls == 0


def test_caller_deadline_bounds_the_fallback(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(llm.time, "perf_counter", lambda: clock[0])
    primary = _Primary(
        LLMTransientProviderError(_TRANSIENT), on_call=lambda: clock.__setitem__(0, 10.0)
    )
    gemini, timeouts = _Gemini(), []
    with llm.provider_deadline(30.0):
        _wrap(primary, gemini, budget=240.0, timeouts=timeouts).generate(_messages())
    assert timeouts == [20.0] and gemini.deadlines == [30.0]


@pytest.mark.parametrize(
    ("primary_error", "status_code"),
    [(LLMQuotaExhaustedError(_QUOTA), 503), (LLMTransientProviderError(_TRANSIENT), 502)],
)
def test_cap_refusal_surfaces_the_primary_failure(primary_error, status_code):
    refusal = gemini_spend_cap.GeminiAllowanceError(gemini_spend_cap.CAP_REFUSAL)
    provider = _wrap(_Primary(primary_error), _Gemini(error=refusal))
    with pytest.raises(type(primary_error)) as caught:
        provider.generate(_messages())
    assert str(caught.value) == f"{primary_error} {gemini_spend_cap.CAP_REFUSAL}"
    assert caught.value.fallback_refusal == (
        "The monthly Gemini fallback allowance is used up. No external request was sent."
    )
    response = provider_failure_http_exception(noun="draft", exc=caught.value)
    assert response.status_code == status_code
    assert gemini_spend_cap.CAP_REFUSAL in response.detail
    if status_code == 503:
        assert "provider quota is exhausted" in response.detail


def test_gemini_unavailability_reports_primary_and_format_errors_keep_their_type():
    primary_error = LLMQuotaExhaustedError(_QUOTA)
    for gemini_error in (
        LLMTransientProviderError("Gemini is temporarily unavailable or the request timed out."),
        LLMQuotaExhaustedError("Gemini quota exhausted. Check the provider billing account."),
        LLMProviderError("Gemini call failed. Check provider configuration."),
    ):
        with pytest.raises(LLMQuotaExhaustedError) as caught:
            _wrap(_Primary(primary_error), _Gemini(error=gemini_error)).generate(_messages())
        assert caught.value is primary_error
    format_error = LLMResponseFormatError("Gemini declined the supplied prompt.")
    with pytest.raises(LLMResponseFormatError) as caught:
        _wrap(_Primary(primary_error), _Gemini(error=format_error)).generate(_messages())
    assert caught.value is format_error


def test_gemini_output_meets_the_same_schema_validator():
    provider = _wrap(_Primary(LLMTransientProviderError(_TRANSIENT)), _Gemini(text='{"ok": 7}'))
    with pytest.raises(LLMResponseFormatError, match="gemini:gemini-3.8-flash"):
        llm.generate_structured(
            provider, schema=_Toy, messages=_messages(), context=LLMCallContext(purpose="x")
        )


# --- tenant AI policy -------------------------------------------------------------


@pytest.mark.usefixtures("ephemeral_db")
@pytest.mark.parametrize("allowed", [["gpt-5.1"], ["gpt-5.1", FALLBACK_MODEL], None])
def test_tenant_policy_must_allow_the_fallback_model(allowed):
    from tests.test_ai_policy_enforcement import _dispose, _fresh_session_and_company, _make_policy

    session, company = _fresh_session_and_company("fallback-policy")
    try:
        if allowed is not None:
            _make_policy(session, company_id=company.id, allowed_recommendations=allowed)
        session.commit()
        primary, gemini = _Primary(LLMTransientProviderError(_TRANSIENT)), _Gemini(
            text='{"ok": true}'
        )
        context = LLMCallContext(tenant_id=company.id, purpose="recommendation:authority")
        provider = _wrap(primary, gemini)
        if allowed == ["gpt-5.1"]:
            with pytest.raises(LLMTransientProviderError):
                llm.generate_structured(
                    provider, schema=_Toy, messages=_messages(), context=context, session=session
                )
            assert gemini.calls == 0
        else:
            _, completion = llm.generate_structured(
                provider, schema=_Toy, messages=_messages(), context=context, session=session
            )
            assert completion.model == FALLBACK_MODEL and gemini.calls == 1
    finally:
        _dispose(session)


def test_policy_context_withholds_fallback_for_direct_callers():
    primary, gemini = _Primary(LLMTransientProviderError(_TRANSIENT)), _Gemini()
    with llm.availability_fallback_policy(False), pytest.raises(LLMTransientProviderError):
        _wrap(primary, gemini).generate(_messages())
    assert gemini.calls == 0


# --- caller paths ------------------------------------------------------------------


def _drafting_versions(client, token, matter_id, monkeypatch, provider):
    from tests.test_drafting_studio import _create_draft, _generate

    monkeypatch.setattr("caseops_api.services.drafting.build_provider", lambda *a, **k: provider)
    draft = _create_draft(client, token, matter_id)
    return _generate(client, token, matter_id, draft["id"])["versions"][0]


@pytest.mark.parametrize(
    "error", [LLMQuotaExhaustedError(_QUOTA), LLMTransientProviderError(_TRANSIENT)]
)
def test_drafting_fallback_output_passes_the_same_citation_validation(client, monkeypatch, error):
    from tests.test_auth_company import bootstrap_company
    from tests.test_drafting_studio import _create_matter, _seed_authority

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FALLBACK")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 361")
    served = _drafting_versions(client, token, matter_id, monkeypatch, _wrap(_Primary(), _Gemini()))
    fallback = _drafting_versions(
        client, token, matter_id, monkeypatch, _wrap(_Primary(error), _Gemini())
    )
    for field in ("body", "citations", "verified_citation_count"):
        assert fallback[field] == served[field], field
    assert fallback["verified_citation_count"] >= 1
    with get_session_factory()() as session:
        runs = session.scalars(select(ModelRun).where(ModelRun.purpose == "draft")).all()
    assert sorted((run.provider, run.model) for run in runs) == [
        ("gemini", FALLBACK_MODEL), ("openai", "gpt-5.1")
    ]


def test_drafting_cap_refusal_explains_primary_quota(client, monkeypatch):
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_drafting_studio import _create_draft, _create_matter, _seed_authority

    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "DS-FALLBACK-CAP")
    _seed_authority(neutral_citation="2024 SCC OnLine SC 362")
    refusal = gemini_spend_cap.GeminiAllowanceError(gemini_spend_cap.CAP_REFUSAL)
    provider = _wrap(_Primary(LLMQuotaExhaustedError(_QUOTA)), _Gemini(error=refusal))
    monkeypatch.setattr("caseops_api.services.drafting.build_provider", lambda *a, **k: provider)
    draft = _create_draft(client, token, matter_id)
    response = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["type"] == "llm_quota_exhausted"
    assert "provider quota is exhausted" in body["detail"]
    assert body["detail"].endswith(gemini_spend_cap.CAP_REFUSAL)


@pytest.mark.parametrize(
    "error", [LLMQuotaExhaustedError(_QUOTA), LLMTransientProviderError(_TRANSIENT)]
)
def test_contract_clause_fallback_records_actual_provider(client, monkeypatch, error):
    from caseops_api.db.models import ContractClause
    from caseops_api.services import contract_intelligence
    from tests.test_contract_ai_money_denial import _seed_contract

    boot, contract_id = _seed_contract(client)
    results = {}
    for label, primary in (("primary", _Primary()), ("fallback", _Primary(error))):
        provider = _wrap(primary, _Gemini())
        monkeypatch.setattr(
            contract_intelligence, "build_provider", lambda _provider=provider, **_: _provider
        )
        response = client.post(
            f"/api/ai/contracts/{contract_id}/clauses/extract",
            headers={"Authorization": f"Bearer {boot['access_token']}"},
        )
        assert response.status_code == 200, response.text
        with get_session_factory()() as session:
            results[label] = sorted(
                (row.title, row.clause_type, row.clause_text)
                for row in session.scalars(
                    select(ContractClause).where(ContractClause.contract_id == contract_id)
                )
                if (row.notes or "").startswith("[auto]")
            )
            results[label + "-runs"] = sorted(
                (run.provider, run.model, run.status)
                for run in session.scalars(
                    select(ModelRun).where(ModelRun.company_id == boot["company"]["id"])
                )
            )
    assert results["primary-runs"] == [("openai", "gpt-5.1", "ok")]
    assert results["fallback-runs"] == [
        ("gemini", FALLBACK_MODEL, "ok"), ("openai", "gpt-5.1", "ok")
    ]
    # The contract validators treat the Gemini answer exactly like OpenAI's.
    assert results["fallback"] == results["primary"]


def test_contract_cap_refusal_explains_primary_quota():
    from caseops_api.services import contract_intelligence

    refusal = gemini_spend_cap.GeminiAllowanceError(gemini_spend_cap.CAP_REFUSAL)
    provider = _wrap(_Primary(LLMQuotaExhaustedError(_QUOTA)), _Gemini(error=refusal))
    with pytest.raises(HTTPException) as caught:
        contract_intelligence._structured_with_retry(
            provider,
            schema=_Toy,
            messages=[],
            context=LLMCallContext(purpose="metadata_extract"),
            temperature=0.0,
            max_tokens=512,
            session=None,
            feature="extract clauses",
        )
    assert caught.value.status_code == 503
    assert "provider quota is exhausted" in caught.value.detail
    assert caught.value.detail.endswith(gemini_spend_cap.CAP_REFUSAL)


@pytest.mark.parametrize("gemini_output", ["grounded", "invalid"])
def test_compliance_job_fallback_uses_the_same_schema_and_records_provider(
    client, monkeypatch, gemini_output
):
    from caseops_api.db.models import MatterComplianceExtractionRun
    from caseops_api.services import compliance_extraction
    from tests.test_auth_company import auth_headers, bootstrap_company
    from tests.test_matter_court_orders_create import _create_matter

    monkeypatch.setenv("CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_COMPLIANCE_AI_EXTRACTION_AUTO_RUN_ENABLED", "true")
    get_settings.cache_clear()
    item = {
        "description": "File the compliance affidavit",
        "source_snippet": "The parties shall comply within two weeks from today.",
        "confidence_label": "high" if gemini_output == "grounded" else "certain",
    }
    gemini = _Gemini(text=json.dumps({"items": [item]}))
    provider = _wrap(_Primary(LLMTransientProviderError(_TRANSIENT)), gemini)
    monkeypatch.setattr(compliance_extraction, "build_provider", lambda **_: provider)
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "FALLBACK-COMPLIANCE")
    response = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json={
            "order_date": "2026-11-01",
            "title": "Synthetic compliance direction",
            "summary": "The parties shall comply within two weeks from today.",
            "source": "manual_upload",
            "order_text": "The parties shall comply within two weeks from today.",
        },
    )
    assert response.status_code == 200, response.text
    assert gemini.calls == 1
    with get_session_factory()() as session:
        run = session.scalar(
            select(MatterComplianceExtractionRun).where(
                MatterComplianceExtractionRun.matter_id == matter["id"]
            )
        )
        if gemini_output == "grounded":
            model_run = session.get(ModelRun, run.model_run_id)
            assert (model_run.provider, model_run.model) == ("gemini", FALLBACK_MODEL)
            assert run.metadata_json["ai_item_count"] == 1
        else:
            # The schema rejects the Gemini answer exactly as it would OpenAI's.
            assert run.model_run_id is None
            assert run.metadata_json["ai_failed"] is True
    get_settings.cache_clear()


def test_case_tracking_summary_unwraps_budget_and_rechecks_actual_model(monkeypatch):
    from caseops_api.services import case_tracking_summary as summaries

    primary = object.__new__(llm.OpenAIProvider)
    primary.model = "gpt-5.1"
    provider = _wrap(primary, _Gemini())
    assert summaries._completion_budget(provider) == primary._REASONING_MIN_COMPLETION_TOKENS

    checked = []
    monkeypatch.setattr(summaries, "resolve_tenant_policy", lambda *_a, **_k: "policy")
    monkeypatch.setattr(
        summaries,
        "is_model_allowed",
        lambda policy, *, purpose, model: checked.append((purpose, model)) or model != "blocked",
    )

    class _Context:
        class company:  # noqa: N801
            id = "tenant"

    assert summaries._fallback_allowed(None, context=_Context, provider=provider) is True
    assert summaries._fallback_allowed(None, context=_Context, provider=primary) is True
    with pytest.raises(summaries.SummarySuppressed):
        summaries._allow_model(None, context=_Context, model="blocked")
    assert checked == [
        ("recommendations", FALLBACK_MODEL),
        ("recommendations", "blocked"),
    ]


def test_recommendation_plan_runs_on_the_pinned_managed_fallback(openai_env):
    from caseops_api.services import llm_recommendation_fallback as routing

    captured = []
    openai_env.setattr(llm, "GeminiProvider", lambda **kwargs: captured.append(kwargs) or "g")
    _enable(openai_env)
    assert routing.build_recommendation_fallback(timeout_seconds=40.0) == "g"
    assert captured[0]["model"] == FALLBACK_MODEL
    assert captured[0]["project"] == "offline-caseops-project"


# --- native SDK: the cap is reserved before any managed transport -----------------


@pytest.mark.parametrize("cap_state", ["open", "exhausted"])
def test_native_managed_fallback_reserves_the_cap_before_transport(sdk, monkeypatch, cap_state):
    from caseops_api.db.ai_spend_models import AiGeminiSpendAdmission, AiGeminiSpendMonth
    from tests.test_gemini_flash_lite_provider import PAYLOAD, _Answer
    from tests.test_gemini_flash_lite_provider import _messages as sdk_messages

    ledger = gemini_spend_cap.get_session_factory()
    if cap_state == "exhausted":
        with ledger() as session:
            session.add(
                AiGeminiSpendMonth(
                    month=gemini_spend_cap.ist_month(),
                    limit_minor=1_000_000,
                    admitted_minor=1_000_000,
                    created_at=gemini_spend_cap.datetime.now(gemini_spend_cap.UTC),
                )
            )
            session.commit()
    # Offline token: the SDK emulator supplies anonymous managed credentials.
    monkeypatch.setattr(llm, "_managed_credentials_before_deadline", lambda deadline: None)

    def factory(*, timeout_seconds):
        return llm.GeminiProvider(
            model=FALLBACK_MODEL,
            project="offline-caseops-project",
            location="global",
            timeout_seconds=timeout_seconds,
        )

    provider = AvailabilityFallbackProvider(
        _Primary(LLMQuotaExhaustedError(_QUOTA)),
        purpose="drafting",
        budget_seconds=60.0,
        fallback_factory=factory,
    )
    call = dict(
        schema=_Answer, messages=sdk_messages(), context=LLMCallContext(purpose="drafting"),
        max_tokens=1024,
    )
    if cap_state == "open":
        payload, completion = llm.generate_structured(provider, **call)
        assert payload.answer == PAYLOAD["answer"]
        assert (completion.provider, completion.model) == ("gemini", FALLBACK_MODEL)
        assert len(sdk.requests) == len(sdk.cap_reservations) == 1
        assert "/locations/global/" in sdk.requests[0].url.path
        assert sdk.cap_reservations[0]["output_tokens"] == 1024
        with ledger() as session:
            rows = session.scalars(select(AiGeminiSpendAdmission)).all()
            period = session.get(AiGeminiSpendMonth, gemini_spend_cap.ist_month())
            assert [(row.model, row.upper_bound_minor) for row in rows] == [
                (FALLBACK_MODEL, period.admitted_minor)
            ]
    else:
        with pytest.raises(LLMQuotaExhaustedError) as caught:
            llm.generate_structured(provider, **call)
        assert caught.value.fallback_refusal == gemini_spend_cap.CAP_REFUSAL
        assert sdk.requests == [] and sdk.reservations == []
