from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "scripts" / "product_guide_catalog.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("product_guide_catalog", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gate() -> ModuleType:
    return _load_gate()


def test_committed_product_guide_projection_is_valid(gate: ModuleType) -> None:
    assert gate.validate() == []


def test_gate_accepts_crlf_projection_from_windows_checkout(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "catalog.json"
    api_projection = tmp_path / "api.json"
    web_projection = tmp_path / "web.json"
    document = gate._load()
    canonical = gate._canonical_bytes(document)
    source.write_bytes(canonical)
    api_projection.write_bytes(canonical.replace(b"\n", b"\r\n"))
    web_projection.write_bytes(canonical.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(gate, "SOURCE_PATH", source)
    monkeypatch.setattr(gate, "API_PROJECTION_PATH", api_projection)
    monkeypatch.setattr(gate, "WEB_PROJECTION_PATH", web_projection)

    assert gate.validate() == []


def test_gate_rejects_a_duplicate_section_id(gate: ModuleType) -> None:
    document = gate._load()
    document["sections"][1]["id"] = document["sections"][0]["id"]

    errors = gate.validate_document(document)

    assert any("duplicate section IDs" in error for error in errors)


def test_gate_rejects_an_invented_capability(gate: ModuleType) -> None:
    document = gate._load()
    document["commands"][0]["required_capabilities"] = ["records:teleport"]

    errors = gate.validate_document(document)

    assert any("unknown capabilities" in error for error in errors)


def test_gate_rejects_a_command_without_a_real_page(gate: ModuleType) -> None:
    document = gate._load()
    document["commands"][0]["href"] = "/app/not-a-real-caseops-page"

    errors = gate.validate_document(document)

    assert any("has no page owner" in error for error in errors)


def test_gate_rejects_a_hand_edited_runtime_projection(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "catalog.json"
    api_projection = tmp_path / "api.json"
    web_projection = tmp_path / "web.json"
    document = gate._load()
    canonical = gate._canonical_bytes(document)
    source.write_text(json.dumps(document), encoding="utf-8")
    api_projection.write_bytes(canonical + b" ")
    web_projection.write_bytes(canonical)
    monkeypatch.setattr(gate, "SOURCE_PATH", source)
    monkeypatch.setattr(gate, "API_PROJECTION_PATH", api_projection)
    monkeypatch.setattr(gate, "WEB_PROJECTION_PATH", web_projection)

    errors = gate.validate()

    assert any("stale or hand-edited projection" in error for error in errors)
