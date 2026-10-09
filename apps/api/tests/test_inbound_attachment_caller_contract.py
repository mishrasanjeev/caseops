"""Keep every staging-helper caller aligned; workflow tests prove admission."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from caseops_api.services.communications import _persist_inbound_attachment

SERVICES = Path(__file__).resolve().parents[1] / "src/caseops_api/services"
HELPER = "_persist_inbound_attachment"


def _validate_call(tree: ast.AST, call: ast.Call) -> None:
    assert all(not isinstance(argument, ast.Starred) for argument in call.args)
    assert all(keyword.arg is not None for keyword in call.keywords)
    inspect.signature(_persist_inbound_attachment).bind(
        *(object() for _ in call.args),
        **{keyword.arg: object() for keyword in call.keywords},
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is call:
            assert all(isinstance(target, ast.Name) for target in node.targets), (
                "The upload helper returns one transient attachment, not a tuple."
            )


def _calls(source: str) -> tuple[ast.AST, list[ast.Call]]:
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == HELPER
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == HELPER
        )
    ]
    return tree, calls


def test_complete_production_staging_caller_inventory() -> None:
    observed = {}
    for path in SERVICES.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if HELPER not in source:
            continue
        _, calls = _calls(source)
        if calls:
            observed[path.name] = len(calls)
    assert observed == {"communications.py": 2, "gmail_sync.py": 1, "drive_sync.py": 1}


@pytest.mark.parametrize("filename", ["communications.py", "gmail_sync.py", "drive_sync.py"])
def test_every_production_staging_call_binds_current_contract(filename: str) -> None:
    tree, calls = _calls((SERVICES / filename).read_text(encoding="utf-8"))
    assert calls
    for call in calls:
        _validate_call(tree, call)


def test_contract_check_rejects_legacy_arguments() -> None:
    tree, calls = _calls(
        "attachment = _persist_inbound_attachment(session, context=context, matter=matter, "
        "filename=name, content_type=content_type, stream=stream)"
    )
    with pytest.raises(TypeError):
        _validate_call(tree, calls[0])


def test_contract_check_rejects_legacy_tuple_return() -> None:
    tree, calls = _calls(
        "attachment, job, key = _persist_inbound_attachment(session, company_id=company_id, "
        "matter_id=matter_id, actor_id=actor_id, staged_size_bytes=0, filename=name, "
        "content_type=content_type, stream=stream)"
    )
    with pytest.raises(AssertionError, match="not a tuple"):
        _validate_call(tree, calls[0])
