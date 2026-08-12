from __future__ import annotations

import pytest

from caseops_api.core.settings import Settings
from caseops_api.services.security import STEP_UP_PURPOSES


def test_iplf027a_runtime_surfaces_default_fail_closed() -> None:
    settings = Settings()

    assert settings.domain_outbox_consumers_enabled is False
    assert settings.domain_outbox_consumers_rollout_expires_at is None
    assert settings.ip_workflow_commands_enabled is False
    assert settings.ip_workflow_commands_rollout_expires_at is None


def test_iplf027a_switches_are_independent_from_temporal_and_workspace() -> None:
    settings = Settings(
        durable_workflows_enabled=True,
        ip_workspace_enabled=True,
    )

    assert settings.domain_outbox_consumers_enabled is False
    assert settings.ip_workflow_commands_enabled is False


def test_empty_optional_rollout_expiries_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_DOMAIN_OUTBOX_CONSUMERS_ROLLOUT_EXPIRES_AT", "")
    monkeypatch.setenv("CASEOPS_IP_WORKFLOW_COMMANDS_ROLLOUT_EXPIRES_AT", "")

    settings = Settings(_env_file=None)

    assert settings.domain_outbox_consumers_rollout_expires_at is None
    assert settings.ip_workflow_commands_rollout_expires_at is None


def test_iplf027a_high_risk_step_up_purposes_are_stable() -> None:
    assert {
        "ip_lifecycle_transition",
        "ip_workflow_activation",
        "ip_rule_activation",
    } <= STEP_UP_PURPOSES
