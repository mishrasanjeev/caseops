"""The projection gate has to REJECT things, or it is decoration.

``scripts/ip_data_class_projection.py validate`` is the entire control keeping
the compiled projection equal to the reviewed registries. A test that only
asserts the committed tree is valid would pass with every assertion in the
validator deleted, so each test here mutates something and requires a specific
refusal.

The one happy-path test is labelled a canary and is not counted as evidence.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = REPO_ROOT / "scripts" / "ip_data_class_projection.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ip_data_class_projection", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gate() -> ModuleType:
    return _load_gate()


def _errors_contain(errors: list[str], needle: str) -> bool:
    return any(needle in error for error in errors)


class TestTheGateAccepts:
    def test_the_committed_projection_is_valid(self, gate: ModuleType) -> None:
        # CANARY ONLY. This would pass with every assertion removed; it exists
        # to catch the gate becoming impossible to satisfy, nothing more.
        assert gate.validate() == []


class TestTheGateRejects:
    def test_a_hand_edited_projection(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Control: byte equality. Without it the compiled module is just another
        # copy that can drift - the exact defect being fixed.
        tampered = tmp_path / "generated.py"
        tampered.write_text(
            gate.render_module() + "\nADMITTED_DATA_CLASSES['matters'] = None\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "GENERATED_PATH", tampered)

        assert _errors_contain(gate.validate(), "stale or hand-edited")

    def test_a_missing_projection(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(gate, "GENERATED_PATH", tmp_path / "absent.py")

        assert _errors_contain(gate.validate(), "missing generated projection")

    def test_a_registry_row_the_projection_does_not_carry(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Control: set equality against the reviewed registry. Adding a reviewed
        # class without regenerating must not leave the runtime admitting the
        # old set while the registry claims the new one.
        registry = yaml.safe_load(
            gate.REGISTRY_028A_PATH.read_text(encoding="utf-8")
        )
        extra = dict(registry["data_classes"][0])
        extra["id"] = "matters"
        extra["table_name"] = "matters"
        registry["data_classes"].append(extra)
        forged = tmp_path / "registry.yaml"
        forged.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        monkeypatch.setattr(gate, "REGISTRY_028A_PATH", forged)

        errors = gate.validate()

        assert errors, "a registry row absent from the projection must be rejected"

    def test_a_mutated_reviewed_field(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Control: per-FIELD equality. Id-set equality alone passes this, and
        # the fields are what the runtime reads.
        registry = yaml.safe_load(
            gate.REGISTRY_028A_PATH.read_text(encoding="utf-8")
        )
        registry["data_classes"][0]["confidentiality"] = "internal"
        forged = tmp_path / "registry.yaml"
        forged.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        monkeypatch.setattr(gate, "REGISTRY_028A_PATH", forged)

        assert gate.validate(), "a changed reviewed field must be rejected"

    def test_a_schema_change_without_regenerating(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Control: the live ORM fingerprint. This is what catches a migration
        # landing without the projection being re-rendered, which is the routine
        # way a compiled artifact goes stale.
        monkeypatch.setattr(gate, "_orm_schema_fingerprint", lambda: "0" * 64)

        assert _errors_contain(
            gate.validate(), "different ORM schema"
        ), "a moved schema must be rejected"

    def test_a_reintroduced_hard_coded_constant(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Control: the retired-constant assertion. If FOUNDATION_DATA_CLASS_IDS
        # comes back, the runtime has a second, ungated source of admitted
        # classes and everything above it is decoration.
        forged = tmp_path / "data_governance.py"
        forged.write_text(
            gate.HANDLER_PATH.read_text(encoding="utf-8")
            + '\nFOUNDATION_DATA_CLASS_IDS = frozenset({"legal_holds"})\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "HANDLER_PATH", forged)

        assert _errors_contain(gate.validate(), "has reappeared")

    def test_a_shrunken_inventory(
        self, gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Control: inventory domain equality. Drop a table from the map without
        # regenerating and "inventoried but unreviewed" silently downgrades to
        # "no such data class" for it - a weaker, wronger answer.
        document = json.loads(gate.MAP_PATH.read_text(encoding="utf-8"))
        document["sql_tables"] = [
            row for row in document["sql_tables"] if row["table_name"] != "matters"
        ]
        forged = tmp_path / "map.yaml"
        forged.write_text(json.dumps(document, indent=2), encoding="utf-8")
        monkeypatch.setattr(gate, "MAP_PATH", forged)

        assert gate.validate(), "a shrunken inventory must be rejected"
