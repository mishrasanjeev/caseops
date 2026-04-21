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
