from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_web_gcloudignore_blocks_local_build_artifacts() -> None:
    """Regression for the 2026-06-26 Windows deploy archive failure.

    Docker's .dockerignore is applied after gcloud has already staged
    the source archive. The web Cloud Build context needs its own
    .gcloudignore so local node_modules/.next never get uploaded.
    """
    ignore_text = _read_repo_text("apps/web/.gcloudignore")

    required_patterns = {
        "node_modules/",
        ".next/",
        ".env.local",
        ".env*.local",
        "tsconfig.tsbuildinfo",
        "test-results/",
        "playwright-report/",
    }
    for pattern in required_patterns:
        assert pattern in ignore_text


def test_deploy_prod_uses_web_gcloudignore_explicitly() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "WEB_GCLOUDIGNORE_FILE=.gcloudignore" in script
    assert 'WEB_GCLOUDIGNORE_PATH="${WEB_SOURCE_DIR}/${WEB_GCLOUDIGNORE_FILE}"' in script
    assert '--ignore-file "${WEB_GCLOUDIGNORE_FILE}"' in script
    assert '[[ ! -f "${WEB_GCLOUDIGNORE_PATH}" ]]' in script
