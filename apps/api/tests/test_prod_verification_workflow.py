from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_prod_verification_is_deploy_triggered_not_push_triggered() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")

    trigger_block = workflow.split("on:", 1)[1].split("concurrency:", 1)[0]
    assert "push:" not in trigger_block
    assert "workflow_dispatch:" in trigger_block
    assert "required: true" in trigger_block
    assert "--wait-seconds 180" in workflow
    assert "--wait-seconds 1500" not in workflow


def test_prod_verification_runs_notice_suite_after_ram_failure() -> None:
    """The required Notice signal must not disappear behind another failure."""

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(
        encoding="utf-8"
    )
    notice_step = workflow.split("- name: Run prod-Playwright suite (notice module)", 1)[1]
    next_step = notice_step.split("- name: Upload Playwright report on failure", 1)[0]

    assert "if: always()" in next_step
    assert "playwright.notice-prod.config.ts" in next_step


def test_historical_a0_acceptance_is_opt_in_not_a_recurring_release_gate() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(
        encoding="utf-8"
    )
    trigger_block = workflow.split("on:", 1)[1].split("concurrency:", 1)[0]
    a0_step = workflow.split(
        "- name: Run IPLF-027B A0 quiescence acceptance", 1
    )[1].split("- name: Check IPLF-037B renewal acceptance configuration", 1)[0]

    assert "run_historical_a0_gate:" in trigger_block
    assert "default: false" in trigger_block
    assert "type: boolean" in trigger_block
    assert "inputs.run_historical_a0_gate == true" in a0_step
    assert "CASEOPS_IP_A0_PROD_MODE: verify" in a0_step
