"""Sprint R4 — tests for the stepper preview endpoint."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting_preview import (
    generate_step_preview,
)
from caseops_api.services.llm import LLMCompletion


class _StubProvider:
    """Minimal provider stub — returns a canned completion.

    Used in place of Anthropic so the pure-function tests don't hit
    the network.
    """

    provider = "stub"
    model = "stub-model"

    def generate(self, *, messages, temperature, max_tokens):
        _ = messages, temperature, max_tokens
        return LLMCompletion(
            provider=self.provider,
            model=self.model,
            text="PARTIAL DRAFT: placeholder content reflecting partial facts.",
            prompt_tokens=100,
            completion_tokens=30,
            latency_ms=42,
        )


def test_generate_step_preview_emits_text_with_stub_provider() -> None:
    preview = generate_step_preview(
        template_type=DraftTemplateType.BAIL,
        facts={"accused_name": "Ramesh Kumar", "fir_number": "FIR 1/2026"},
        step_group="facts",
        provider=_StubProvider(),
    )
    assert preview.template_type == "bail"
    assert "PARTIAL DRAFT" in preview.preview_text
    assert preview.step_group == "facts"
    assert preview.prompt_tokens == 100
    assert preview.completion_tokens == 30


def test_preview_route_404_on_unknown_template(client: TestClient) -> None:
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    resp = client.post(
        "/api/drafting/preview",
        headers=headers,
        json={"template_type": "does-not-exist", "facts": {}},
    )
    assert resp.status_code == 404


def test_preview_route_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/drafting/preview",
        json={"template_type": "bail", "facts": {}},
    )
    assert resp.status_code in {401, 403}


def test_preview_route_happy_path(client: TestClient) -> None:
    """With the stub provider patched into the service, the route
    round-trips the preview shape."""
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    with patch(
        "caseops_api.services.drafting_preview._default_preview_provider",
        return_value=_StubProvider(),
    ):
        resp = client.post(
            "/api/drafting/preview",
            headers=headers,
            json={
                "template_type": "bail",
                "facts": {
                    "accused_name": "Ramesh Kumar",
                    "fir_number": "FIR 1/2026",
                },
                "step_group": "grounds",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "bail"
    assert "PARTIAL DRAFT" in body["preview_text"]
    assert body["step_group"] == "grounds"
    assert body["prompt_tokens"] == 100


def test_preview_accepts_empty_facts() -> None:
    """An empty facts dict should not break the service — the prompt
    still tells the model to emit placeholders for unfilled fields.
    The preview is illustrative, not gated on completeness."""
    preview = generate_step_preview(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE,
        facts={},
        provider=_StubProvider(),
    )
    assert preview.template_type == "cheque_bounce_notice"
    assert preview.preview_text


# ---------------------------------------------------------------------------
# EG-006 (2026-04-23) — preview goes through the tenant AI policy gate,
# persists a ModelRun for audit, and never leaks raw exception text in
# the user-visible 502 detail.
# ---------------------------------------------------------------------------


def test_preview_persists_model_run_for_successful_call(
    client: TestClient,
) -> None:
    """Every preview call must leave a ModelRun audit row so AI spend
    is visible alongside drafting / recommendations / hearing-pack
    spend. Codex enterprise audit gap EG-006."""
    from sqlalchemy import select

    from caseops_api.db.models import ModelRun
    from caseops_api.db.session import get_session_factory
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    with patch(
        "caseops_api.services.drafting_preview._default_preview_provider",
        return_value=_StubProvider(),
    ):
        resp = client.post(
            "/api/drafting/preview",
            headers=headers,
            json={"template_type": "bail", "facts": {"accused_name": "X"}},
        )
    assert resp.status_code == 200, resp.text

    factory = get_session_factory()
    with factory() as session:
        runs = list(
            session.scalars(
                select(ModelRun).where(ModelRun.purpose == "drafting_preview")
            )
        )
    assert len(runs) == 1, runs
    run = runs[0]
    assert run.status == "ok"
    assert run.prompt_tokens == 100
    assert run.completion_tokens == 30
    assert run.model == "stub-model"
    # company_id + actor_membership_id must be populated so the audit
    # row joins back to the tenant + the user who triggered it.
    assert run.company_id is not None
    assert run.actor_membership_id is not None


def test_preview_502_detail_redacts_internal_exception_text(
    client: TestClient,
) -> None:
    """Codex 2026-04-19 finding #6 — user-visible 4xx/5xx detail
    must not leak internal exception strings (model name, provider
    error class, stack hints). The 502 should give the user an
    actionable, redacted message; the raw exception is logged."""
    from caseops_api.services.llm import LLMProviderError

    class _AlwaysFails:
        name = "stub"
        model = "stub-fail"

        def generate(self, *, messages, temperature, max_tokens):
            _ = messages, temperature, max_tokens
            raise LLMProviderError(
                "Anthropic call failed: SECRET_INTERNAL_TRACE_xyz"
            )

    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    with patch(
        "caseops_api.services.drafting_preview._default_preview_provider",
        return_value=_AlwaysFails(),
    ):
        resp = client.post(
            "/api/drafting/preview",
            headers=headers,
            json={"template_type": "bail", "facts": {}},
        )
    # 2026-04-30: gpt-5.1-only path. Single primary call → redacted 502.
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    # Redaction invariants stay: no raw provider error text, no internal
    # marker substring leaked back.
    assert "SECRET_INTERNAL_TRACE_xyz" not in detail
    assert "LLMProviderError" not in detail
    assert "Anthropic" not in detail
    # Actionability: must tell the user what to do next.
    lowered = detail.lower()
    assert "retry" in lowered or "support" in lowered


def test_preview_persists_error_model_run_when_provider_fails(
    client: TestClient,
) -> None:
    """A failed preview also writes a ModelRun row with status='error'
    so the audit log shows the failure rate alongside successes — the
    operator can spot a 50% failure rate in the dashboard without
    grep-ing pod logs."""
    from sqlalchemy import select

    from caseops_api.db.models import ModelRun
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.llm import LLMProviderError
    from tests.test_auth_company import auth_headers, bootstrap_company

    class _AlwaysFails:
        name = "stub"
        model = "stub-fail"

        def generate(self, *, messages, temperature, max_tokens):
            _ = messages, temperature, max_tokens
            raise LLMProviderError("anthropic 503 overloaded")

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    with patch(
        "caseops_api.services.drafting_preview._default_preview_provider",
        return_value=_AlwaysFails(),
    ):
        resp = client.post(
            "/api/drafting/preview",
            headers=headers,
            json={"template_type": "bail", "facts": {}},
        )
    assert resp.status_code == 502

    factory = get_session_factory()
    with factory() as session:
        error_runs = list(
            session.scalars(
                select(ModelRun)
                .where(ModelRun.purpose == "drafting_preview")
                .where(ModelRun.status == "error")
            )
        )
    assert len(error_runs) == 1
    run = error_runs[0]
    assert run.error == "preview_provider_failed"
    assert run.model == "stub-fail"


def test_preview_single_call_no_fallback_ladder(client: TestClient) -> None:
    """2026-04-30: gpt-5.1-only path. Replaces test_preview_402_quota_cuts_
    over_to_openai. With Anthropic retired and OpenAI as the sole primary,
    a primary failure goes straight to a redacted 502 — no cutover ladder,
    one provider call per click."""
    from caseops_api.services.llm import LLMProviderError
    from tests.test_auth_company import auth_headers, bootstrap_company

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    primary_calls: list[bool] = []

    class _SinglePrimary:
        name = "openai"
        model = "gpt-5.1"

        def generate(self, *, messages, temperature, max_tokens):
            _ = messages, temperature, max_tokens
            primary_calls.append(True)
            raise LLMProviderError("openai 503 overloaded")

    with patch(
        "caseops_api.services.drafting_preview._default_preview_provider",
        return_value=_SinglePrimary(),
    ):
        resp = client.post(
            "/api/drafting/preview",
            headers=headers,
            json={"template_type": "bail", "facts": {}},
        )

    assert resp.status_code == 502, resp.text
    # Exactly one provider call — no fallback ladder, no 3x token burn.
    assert primary_calls == [True]
