from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ip_data_governance_map.py"
SPEC = importlib.util.spec_from_file_location("ip_data_governance_map", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
ip_data_governance_map = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip_data_governance_map)


def _map() -> dict:
    return copy.deepcopy(ip_data_governance_map._load(ip_data_governance_map.MAP_PATH))


def test_committed_data_governance_map_covers_current_repository_inventory() -> None:
    assert ip_data_governance_map.validate(_map()) == []


def test_map_rejects_missing_or_unregistered_sql_table_and_column() -> None:
    data = _map()
    removed = data["sql_tables"].pop()
    schema = ip_data_governance_map.current_sql_schema()
    schema["unregistered_data_store"] = {
        "new_payload": {"sql_type": "TEXT", "nullable": True}
    }

    errors = ip_data_governance_map.validate(data, sql_schema=schema)

    assert removed["table_name"] in " ".join(errors)
    assert any("sql-table inventory must exactly match" in error for error in errors)
    assert any("unregistered_data_store" in error for error in errors)


def test_map_rejects_missing_policy_and_runtime_overclaim() -> None:
    data = _map()
    data["completion_boundary"] = "This is complete."
    data["policy_profiles"]["tenant_operational_record"]["default_retention"] = ""
    data["disposition_handlers"][0]["status"] = "live_execute_handler"
    data["non_sql_data_classes"][0]["status"] = "policy_approved"

    errors = ip_data_governance_map.validate(data)

    assert any("explicit incomplete boundary" in error for error in errors)
    assert any("default_retention must be explicit" in error for error in errors)
    assert any("must not overclaim runtime execution" in error for error in errors)
    assert any("must not overclaim runtime policy approval" in error for error in errors)


def test_map_rejects_stale_view_after_non_projected_semantic_change(
    tmp_path: Path, monkeypatch
) -> None:
    data = _map()
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    target.write_bytes(ip_data_governance_map._render_markdown(data).encode("utf-8"))
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)
    data["non_sql_data_classes"][0]["purpose"] += " Reviewed semantic change."

    errors = ip_data_governance_map.validate(data)

    assert any(
        "stale or independently edited generated data-governance map" in error
        for error in errors
    )


def test_map_rejects_a_missing_generated_view(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    errors = ip_data_governance_map.validate(_map())

    assert any("missing generated data-governance map" in error for error in errors)


def test_map_rejects_crlf_bytes_for_the_lf_projection(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    expected = ip_data_governance_map._render_markdown(_map()).encode("utf-8")
    target.write_bytes(expected.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    errors = ip_data_governance_map.validate(_map())

    assert any(
        "stale or independently edited generated data-governance map" in error
        for error in errors
    )


def test_render_repairs_a_stale_view_without_recursive_validation(
    tmp_path: Path, monkeypatch
) -> None:
    data = _map()
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    target.write_bytes(b"stale\n")
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    assert ip_data_governance_map.render(data) == target
    assert target.read_bytes() == ip_data_governance_map._render_markdown(data).encode(
        "utf-8"
    )
    assert ip_data_governance_map.validate(data) == []


def test_change_gate_requires_map_update_and_migration_marker() -> None:
    migration = "apps/api/alembic/versions/20260814_0001_new_data.py"
    errors = ip_data_governance_map.change_gate_errors(
        [migration], source_by_path={migration: "def upgrade(): pass"}
    )

    assert any("DATA_GOVERNANCE_MAP.yaml update" in error for error in errors)
    assert any("missing required marker" in error for error in errors)

    passed = ip_data_governance_map.change_gate_errors(
        [migration, "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml"],
        source_by_path={
            migration: f"# {ip_data_governance_map.MIGRATION_MARKER}\ndef upgrade(): pass"
        },
    )
    assert passed == []


def test_change_gate_requires_map_update_for_new_provider_or_storage_boundary() -> None:
    path = "apps/api/src/caseops_api/services/new_provider.py"
    source = "from google.cloud import storage\nclient = storage.Client()\n"

    errors = ip_data_governance_map.change_gate_errors(
        [path], source_by_path={path: source}
    )
    assert any("DATA_GOVERNANCE_MAP.yaml update" in error for error in errors)

    assert (
        ip_data_governance_map.change_gate_errors(
            [path, "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml"],
            source_by_path={path: source},
        )
        == []
    )


def test_change_gate_requires_map_update_for_a_boundary_in_a_deploy_manifest() -> None:
    # A deploy manifest contains no import statements and no attribute calls, so
    # a pattern anchored on code syntax matches nothing in one. `infra/` is a
    # RISKY_SOURCE_ROOT, and a root that is listed but unwatched is worse than a
    # root that was never listed: the gate reports success either way, so the
    # absence of an error reads as proof that nothing data-bearing changed.
    path = "infra/cloudrun/new-worker-job.yaml"
    source = (
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - image: gcr.io/caseops/worker\n"
        "          env:\n"
        "            - name: CACHE_BACKEND\n"
        "              value: redis\n"
    )

    errors = ip_data_governance_map.change_gate_errors(
        [path], source_by_path={path: source}
    )
    assert any("DATA_GOVERNANCE_MAP.yaml update" in error for error in errors)

    assert (
        ip_data_governance_map.change_gate_errors(
            [path, "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml"],
            source_by_path={path: source},
        )
        == []
    )


def test_change_gate_matches_a_scoped_npm_provider_package() -> None:
    # Provider SDKs are scoped on npm, so the import a frontend actually writes
    # is `@opentelemetry/api`, not `opentelemetry`. Anchoring the bare module
    # name to the opening quote matched none of them.
    path = "apps/web/lib/telemetry/otel.ts"
    source = 'import { trace } from "@opentelemetry/api";\n'

    errors = ip_data_governance_map.change_gate_errors(
        [path], source_by_path={path: source}
    )
    assert any("DATA_GOVERNANCE_MAP.yaml update" in error for error in errors)


def test_change_gate_still_ignores_provider_words_in_prose_inside_source_files() -> None:
    # The manifest rule above must not undo the noise fix it sits beside: bare
    # provider words in comments and route paths are why code files are matched
    # on syntax rather than on the word alone.
    path = "apps/api/src/caseops_api/api/routes/intake.py"
    source = (
        "# Inbound legal requests from business units are triaged here.\n"
        '@router.get("/api/intake/requests")\n'
        "def list_requests() -> list[str]:\n"
        "    return []\n"
    )

    assert (
        ip_data_governance_map.change_gate_errors([path], source_by_path={path: source})
        == []
    )


def test_change_gate_ignores_provider_words_in_program_documentation() -> None:
    path = "docs/ip-implementation/PROGRAM_MANIFEST.yaml"

    assert (
        ip_data_governance_map.change_gate_errors(
            [path],
            source_by_path={path: "Provider quota: OpenAI remains externally blocked."},
        )
        == []
    )
