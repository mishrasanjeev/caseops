from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_m2_ownership_audit.py"
SPEC = importlib.util.spec_from_file_location("ip_m2_ownership_audit", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_m2_ownership_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_m2_ownership_audit)


def _manifest() -> dict:
    return copy.deepcopy(ip_m2_ownership_audit._load(ip_m2_ownership_audit.MANIFEST_PATH))


def _ledger() -> dict:
    return copy.deepcopy(ip_m2_ownership_audit._load(ip_m2_ownership_audit.LEDGER_PATH))


def _slice(manifest: dict, slice_id: str) -> dict:
    return next(row for row in manifest["slices"] if row["id"] == slice_id)


def test_committed_m2_slices_have_one_writer_reconciliation_evidence() -> None:
    assert ip_m2_ownership_audit.validate(_manifest()) == []


def test_audit_accepts_only_allowlisted_root_playwright_config_references() -> None:
    for path in ip_m2_ownership_audit.ROOT_REFERENCE_ALLOWLIST:
        assert ip_m2_ownership_audit._reference_path(path) == REPO_ROOT / path
    assert ip_m2_ownership_audit._reference_path("unreviewed-root.config.ts") is None


def test_audit_rejects_missing_writer_test_and_evidence_for_active_slice() -> None:
    manifest = _manifest()
    row = _slice(manifest, "IPLF-020A")
    row["ownership"][0].pop("canonical_writer")
    row["test_refs"] = ["planned:IPLF-UJ-UNKNOWN"]
    row["evidence_refs"] = []

    errors = ip_m2_ownership_audit.validate(manifest)

    assert any("lacks canonical_writer" in error for error in errors)
    assert any("planned or missing canonical-writer test_refs" in error for error in errors)
    assert any("requires a dated evidence artifact" in error for error in errors)


def test_audit_rejects_active_blocked_slice_without_named_blocker() -> None:
    manifest = _manifest()
    row = _slice(manifest, "IPLF-026B")
    row["blockers"] = []

    errors = ip_m2_ownership_audit.validate(manifest)

    assert any("active blocked slice requires an explicit blocker" in error for error in errors)


def test_audit_rejects_not_started_slice_with_implementation_evidence() -> None:
    manifest = _manifest()
    row = _slice(manifest, "IPLF-027B")
    row["implementation_status"] = "not_started"

    errors = ip_m2_ownership_audit.validate(manifest, check_generated_view=False)

    assert any(
        "not_started slice carries implementation or evidence records" in error
        for error in errors
    )


def test_audit_binds_completion_slice_to_arch_ops_and_ledger_control() -> None:
    manifest = _manifest()
    ledger = _ledger()
    row = _slice(manifest, "IPLF-029B")
    row["requirement_ids"].pop()
    row["ownership"][0]["canonical_writer"] = "untracked second audit writer"

    errors = ip_m2_ownership_audit.validate(
        manifest, ledger, check_generated_view=False
    )

    assert any("exactly cover the manifest ARCH-OPS controls" in error for error in errors)
    assert any("canonical_writer must match" in error for error in errors)


def test_audit_rejects_retiring_the_checked_in_completion_workflow() -> None:
    manifest = _manifest()
    row = _slice(manifest, "IPLF-029B")
    row["implementation_status"] = "not_started"
    row["implementation_refs"] = []
    row["evidence_refs"] = []
    row["evidence_metadata"] = []

    errors = ip_m2_ownership_audit.validate(
        manifest, _ledger(), check_generated_view=False
    )

    assert any("checked-in reconciliation workflow must remain active" in error for error in errors)


def test_audit_rejects_a_stale_generated_view(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "M2_OWNERSHIP_AUDIT.md"
    target.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(ip_m2_ownership_audit, "GENERATED_VIEW_PATH", target)

    errors = ip_m2_ownership_audit.validate(_manifest())

    assert any(
        "stale or independently edited generated M2 ownership audit" in error for error in errors
    )


def test_render_is_explicit_about_repository_evidence_boundary(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "M2_OWNERSHIP_AUDIT.md"
    monkeypatch.setattr(ip_m2_ownership_audit, "GENERATED_VIEW_PATH", target)

    assert ip_m2_ownership_audit.render(_manifest()) == target
    rendered = target.read_text(encoding="utf-8")

    assert "canonical-writer, test, and evidence references" in rendered
    assert "It does not run a production operation" in rendered
    assert "Rows still awaiting release closure" in rendered
    assert "repository-evidence-recorded-release-blocked" in rendered
