from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cloudrun_manifest_deploy_resolves_api_image_to_digest() -> None:
    script = (REPO_ROOT / "infra" / "cloudrun" / "deploy.ps1").read_text(encoding="utf-8")

    assert "function Resolve-ImmutableImage" in script
    assert "value(image_summary.digest)" in script
    assert 'return "$imageName@$digest"' in script
    assert "$ApiImage = Resolve-ImmutableImage" in script
    assert "Failed to replace Cloud Run job" in script


def test_production_deploy_refreshes_recurring_jobs_with_immutable_image() -> None:
    script = (REPO_ROOT / "scripts" / "deploy-prod.sh").read_text(encoding="utf-8")

    assert "API_IMMUTABLE_IMAGE=" in script
    assert "gcloud artifacts docker images describe" in script
    assert "python scripts/scheduler_inventory.py reconcile" in script
    assert '--image "${API_IMMUTABLE_IMAGE}"' in script


def test_production_deploy_only_refreshes_jobs_provisioned_in_production() -> None:
    script = (REPO_ROOT / "scripts" / "deploy-prod.sh").read_text(encoding="utf-8")

    # The document worker is optional and intentionally absent from the
    # production scheduler inventory.
    assert "caseops-document-worker" not in script
