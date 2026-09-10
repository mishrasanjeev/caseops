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


def test_hold_release_evidence_is_registered_without_disposition_admission() -> None:
    data = _map()
    proposal = next(
        row for row in data["sql_tables"] if row["table_name"] == "legal_hold_release_requests"
    )
    assert proposal["policy_profile_id"] == "security_identity_control"
    assert proposal["disposition_handler_id"] == "registry_fail_closed"
    assert "legal_hold_release_requests" not in data["table_disposition_handler_overrides"]
    columns = proposal["columns"]
    for name in ("request_json", "reason_reference"):
        assert columns[name]["category_id"] == "privileged_or_raw_content"
    assert columns["requester_label_snapshot"]["category_id"] == "personal_or_contact_data"
    for name in ("request_hash", "idempotency_key"):
        assert columns[name]["category_id"] == "lifecycle_or_audit_evidence"
    for name in (
        "company_id",
        "legal_hold_id",
        "dry_run_id",
        "requester_membership_id",
        "requester_user_id",
    ):
        assert columns[name]["category_id"] == "tenant_or_access_identifier"


def test_private_projection_is_the_only_runtime_disposition_override() -> None:
    data = _map()
    assert data["table_disposition_handler_overrides"] == {
        "private_index_projections": "private_retrieval_disposition"
    }
    private_projection = next(
        row for row in data["sql_tables"] if row["table_name"] == "private_index_projections"
    )
    checkpoint = next(
        row
        for row in data["sql_tables"]
        if row["table_name"] == "tenant_data_disposition_checkpoints"
    )
    assert private_projection["disposition_handler_id"] == ("private_retrieval_disposition")
    assert checkpoint["disposition_handler_id"] == "registry_fail_closed"

    data["table_disposition_handler_overrides"]["private_index_projections"] = "invented_handler"
    errors = ip_data_governance_map.validate(data, check_generated_view=False)
    assert any("unknown handler" in error for error in errors)


def test_patent_work_product_is_registered_without_export_or_purge_admission() -> None:
    data = _map()
    tables = {row["table_name"]: row for row in data["sql_tables"]}
    for name in (
        "ip_patent_evidence_versions", "ip_patent_evidence_documents",
        "ip_patent_prosecution_events", "ip_patent_proceeding_details",
        "ip_patent_proceeding_events",
    ):
        assert tables[name]["policy_profile_id"] == "tenant_restricted_legal_content"
        assert tables[name]["disposition_handler_id"] == "registry_fail_closed"
        assert name not in data["table_disposition_handler_overrides"]
    for name in ("ip_patent_prosecution_events", "ip_patent_proceeding_events"):
        for column in ("reason", "impact_json", "exceptional_transition_reason"):
            assert tables[name]["columns"][column]["category_id"] == "privileged_or_raw_content"
    assert tables["ip_patent_proceeding_details"]["columns"]["counterparty"]["category_id"] == (
        "personal_or_contact_data"
    )


def test_map_rejects_missing_or_unregistered_sql_table_and_column() -> None:
    data = _map()
    removed = data["sql_tables"].pop()
    schema = ip_data_governance_map.current_sql_schema()
    schema["unregistered_data_store"] = {"new_payload": {"sql_type": "TEXT", "nullable": True}}

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
        "stale or independently edited generated data-governance map" in error for error in errors
    )


def test_map_rejects_a_missing_generated_view(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    errors = ip_data_governance_map.validate(_map())

    assert any("missing generated data-governance map" in error for error in errors)


def test_map_rejects_crlf_bytes_for_the_lf_projection(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    expected = ip_data_governance_map._render_markdown(_map()).encode("utf-8")
    target.write_bytes(expected.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    errors = ip_data_governance_map.validate(_map())

    assert any(
        "stale or independently edited generated data-governance map" in error for error in errors
    )


def test_render_repairs_a_stale_view_without_recursive_validation(
    tmp_path: Path, monkeypatch
) -> None:
    data = _map()
    target = tmp_path / "DATA_GOVERNANCE_MAP.md"
    target.write_bytes(b"stale\n")
    monkeypatch.setattr(ip_data_governance_map, "GENERATED_VIEW_PATH", target)

    assert ip_data_governance_map.render(data) == target
    assert target.read_bytes() == ip_data_governance_map._render_markdown(data).encode("utf-8")
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

    errors = ip_data_governance_map.change_gate_errors([path], source_by_path={path: source})
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

    errors = ip_data_governance_map.change_gate_errors([path], source_by_path={path: source})
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

    errors = ip_data_governance_map.change_gate_errors([path], source_by_path={path: source})
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

    assert ip_data_governance_map.change_gate_errors([path], source_by_path={path: source}) == []


def test_change_gate_ignores_provider_words_in_program_documentation() -> None:
    path = "docs/ip-implementation/PROGRAM_MANIFEST.yaml"

    assert (
        ip_data_governance_map.change_gate_errors(
            [path],
            source_by_path={path: "Provider quota: OpenAI remains externally blocked."},
        )
        == []
    )


def test_committed_change_gate_ignores_binary_evidence_but_checks_governed_source(
    tmp_path: Path, monkeypatch
) -> None:
    evidence = "tests/fixtures/statutes/official/source.pdf"
    migration = "apps/api/alembic/versions/new_data.py"
    provider = "apps/api/src/caseops_api/services/new_provider.py"
    for name, content in (
        (evidence, b"%PDF-1.7\n%\xb5\xb5\xb5\xb5\n"),
        (migration, b"def upgrade(): pass\n"),
        (provider, b"from google.cloud import storage\n"),
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    monkeypatch.setattr(ip_data_governance_map, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        ip_data_governance_map, "MAP_PATH",
        tmp_path / "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml",
    )
    monkeypatch.setattr(
        ip_data_governance_map, "_git_output", lambda *args: "\n".join(
            (evidence, migration, provider)
        )
    )

    errors = ip_data_governance_map.check_change("origin/main")
    assert len(errors) == 2
    assert "DATA_GOVERNANCE_MAP.yaml update" in errors[0]
    assert migration in errors[0] and provider in errors[0]
    assert "missing required marker" in errors[1]

    (tmp_path / migration).write_text(
        f"# {ip_data_governance_map.MIGRATION_MARKER}\ndef upgrade(): pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ip_data_governance_map, "_git_output", lambda *args: "\n".join(
            (evidence, migration, provider, "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml")
        )
    )
    assert ip_data_governance_map.check_change("origin/main") == []


def test_committed_change_gate_rejects_unreadable_governed_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = "apps/api/src/caseops_api/services/new_provider.py"
    target = tmp_path / source
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff")
    monkeypatch.setattr(ip_data_governance_map, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        ip_data_governance_map, "MAP_PATH",
        tmp_path / "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml",
    )
    monkeypatch.setattr(ip_data_governance_map, "_git_output", lambda *args: source)

    errors = ip_data_governance_map.check_change("origin/main")
    assert errors == [f"cannot read governed source {source}: UnicodeDecodeError"]
