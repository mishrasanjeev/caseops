"""A partial document seed must never certify the 23-Act catalogue."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "catalogue_audit", ROOT / "scripts/audit_statute_catalogue.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogue_audit_reconciles_every_act_without_claiming_partial_completion():
    result = _audit_module().audit_catalogue()
    assert result["catalogue_act_count"] == result["inventoried_act_count"] == 23
    assert result["retained_release_document_count"] == 20
    assert len(result["missing_release_documents"]) == 3
    assert "constitution-india" in result["missing_release_documents"]
    assert "cpc-1908" in result["missing_whole_document_page_inventory"]
    assert "income-tax-2025" in result["additional_source_packs_pending"]
    assert result["complete"] is False


@pytest.mark.parametrize("defect", ["missing", "duplicate", "missing_source"])
def test_catalogue_audit_rejects_inventory_omissions(tmp_path, defect):
    audit = _audit_module()
    inventory = json.loads(audit.INVENTORY.read_text(encoding="utf-8"))
    if defect == "missing":
        inventory["catalogue"].pop()
    elif defect == "duplicate":
        inventory["catalogue"].append(inventory["catalogue"][0])
    else:
        inventory["catalogue"][0]["source_candidates"] = []
    audit.INVENTORY = tmp_path / "inventory.json"
    audit.INVENTORY.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.audit_catalogue()


def test_catalogue_closure_command_refuses_partial_coverage(monkeypatch, capsys):
    audit = _audit_module()
    monkeypatch.setattr("sys.argv", ["audit_statute_catalogue.py", "--require-complete"])
    with pytest.raises(SystemExit) as failure:
        audit.main()
    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out)["complete"] is False
