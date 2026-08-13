from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_prod_verification_runs_notice_suite_after_ram_failure() -> None:
    """The required Notice signal must not disappear behind another failure."""

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(
        encoding="utf-8"
    )
    notice_step = workflow.split("- name: Run prod-Playwright suite (notice module)", 1)[1]
    next_step = notice_step.split("- name: Upload Playwright report on failure", 1)[0]

    assert "if: always()" in next_step
    assert "playwright.notice-prod.config.ts" in next_step
