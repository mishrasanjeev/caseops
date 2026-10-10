"""Static recognizer and fresh-process checks for the shared fence owner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_service_dependency_boundaries import (
    SERVICE_PREFIX,  # noqa: F401
    _route,
)
from tests.test_service_dependency_boundaries import (
    dependency_graph as _dependency_graph_fixture,
)

_CALLERS = (
    "compliance_extraction", "proceeding_intelligence", "matters", "court_sync_jobs",
    "notification_rules",
)
dependency_graph = _dependency_graph_fixture


@pytest.mark.parametrize("caller", _CALLERS)
def test_participant_owner_has_no_reverse_workflow_dependency(dependency_graph, caller):
    source, owner = SERVICE_PREFIX + caller, SERVICE_PREFIX + "compliance_participants"
    assert owner in dependency_graph[source]
    assert _route(dependency_graph, owner, source) is None
    assert not _route(
        dependency_graph,
        SERVICE_PREFIX + "proceeding_intelligence",
        SERVICE_PREFIX + "compliance_extraction",
    )


@pytest.mark.parametrize("first", (*_CALLERS, "compliance_participants"))
def test_fresh_process_compliance_import_origin_and_owner(first):
    root = Path(__file__).resolve().parents[1] / "src"
    program = """
import importlib
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
prefix = 'caseops_api.services.'
importlib.import_module(prefix + sys.argv[2])
owner = importlib.import_module(prefix + 'compliance_participants')
extraction = importlib.import_module(prefix + 'compliance_extraction')
proceeding = importlib.import_module(prefix + 'proceeding_intelligence')
assert extraction.lock_compliance_participants is owner.lock_compliance_participants
assert 'lock_compliance_participants' not in vars(proceeding)
assert owner.lock_compliance_participants.__module__ == prefix + 'compliance_participants'
for module in (owner, extraction, proceeding):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(
        pathlib.Path(sys.argv[1]).resolve())
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(root), first],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
