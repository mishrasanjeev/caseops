"""Regression boundaries for the production CodeQL circular dependencies."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
SERVICE_PREFIX = "caseops_api.services."
LEAVES = (
    "record_access_policy",
    "ip_document_policy",
    "calendar_projection_tombstones",
    "ip_coverage_read",
)
WORKFLOWS = (
    "private_retrieval",
    "ip_document_workflow",
    "matter_access",
    "employee_deactivation",
    "identity",
    "document_jobs",
    "ip_operations",
    "ip_coverage_projection",
    "notification_delivery",
    "storage_governance",
)
ALERT_EDGES = (
    (423, "ip_document_workflow", "document_jobs"),
    (493, "document_jobs", "private_retrieval"),
    (494, "ip_operations", "private_retrieval"),
    (495, "ip_operations", "private_retrieval"),
    (499, "document_jobs", "private_retrieval"),
    (500, "ip_document_workflow", "private_retrieval"),
    (506, "document_jobs", "matter_write_fence"),
    (507, "ip_document_workflow", "ip_operations"),
    (508, "ip_document_workflow", "storage_governance"),
    (509, "ip_document_workflow", "identity"),
    (510, "ip_operations", "private_retrieval"),
    (511, "ip_operations", "private_retrieval"),
    (512, "matter_write_fence", "private_retrieval"),
    (515, "ip_document_workflow", "matter_write_fence"),
    (525, "employee_deactivation", "ip_coverage_projection"),
    (526, "employee_deactivation", "ip_operations"),
    (527, "identity", "employee_deactivation"),
    (528, "ip_document_workflow", "matter_access"),
)


@pytest.fixture(scope="module")
def dependency_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in (SRC / "caseops_api").rglob("*.py"):
        module = ".".join(path.relative_to(SRC).with_suffix("").parts)
        imports: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
        graph[module] = imports
    return graph


def _route(graph: dict[str, set[str]], source: str, target: str) -> list[str] | None:
    remaining = [(source, [source])]
    visited: set[str] = set()
    while remaining:
        current, path = remaining.pop()
        if current == target:
            return path
        if current in visited:
            continue
        visited.add(current)
        remaining.extend((child, [*path, child]) for child in graph.get(current, ()))
    return None


@pytest.mark.parametrize("alert,source,target", ALERT_EDGES)
def test_codeql_alert_imports_do_not_form_cycles(
    dependency_graph: dict[str, set[str]], alert: int, source: str, target: str
) -> None:
    source = SERVICE_PREFIX + source
    target = SERVICE_PREFIX + target
    if target in dependency_graph[source]:
        reverse = _route(dependency_graph, target, source)
        assert reverse is None, f"CodeQL alert {alert}: {[source, *(reverse or [])]}"


@pytest.mark.parametrize("leaf", LEAVES)
def test_shared_policy_leaves_never_depend_on_workflows(
    dependency_graph: dict[str, set[str]], leaf: str
) -> None:
    for workflow in WORKFLOWS:
        route = _route(dependency_graph, SERVICE_PREFIX + leaf, SERVICE_PREFIX + workflow)
        assert route is None, route


@pytest.mark.parametrize("first", (*LEAVES, "private_retrieval", "ip_document_workflow"))
def test_fresh_process_import_order_and_public_function_identity(first: str) -> None:
    program = """
import importlib
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
prefix = 'caseops_api.services.'
first = importlib.import_module(prefix + sys.argv[2])
assert pathlib.Path(first.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
if sys.argv[2] in ('record_access_policy', 'ip_document_policy',
                   'calendar_projection_tombstones', 'ip_coverage_read'):
    forbidden = sys.argv[3:]
    assert not [name for name in forbidden if prefix + name in sys.modules]
policy = importlib.import_module(prefix + 'record_access_policy')
documents = importlib.import_module(prefix + 'ip_document_policy')
tombstones = importlib.import_module(prefix + 'calendar_projection_tombstones')
access = importlib.import_module(prefix + 'matter_access')
workflow = importlib.import_module(prefix + 'ip_document_workflow')
coverage = importlib.import_module(prefix + 'ip_coverage_projection')
private = importlib.import_module(prefix + 'private_retrieval')
assert access.visible_matters_filter is policy.visible_matters_filter
assert access.visible_ip_dockets_filter is policy.visible_ip_dockets_filter
for name in ('_active_grant_window', '_active_ip_subject_match', '_active_wall_window'):
    assert getattr(policy, name).__module__ == prefix + 'record_access_policy'
    assert name not in vars(access)
assert private.visible_matters_filter is policy.visible_matters_filter
assert private.visible_ip_dockets_filter is policy.visible_ip_dockets_filter
assert workflow.get_ip_document_policies is documents.get_ip_document_policies
assert workflow.get_accessible_ip_document_ids is documents.get_accessible_ip_document_ids
assert workflow._policy is documents._policy
assert all(callable(getattr(workflow, name)) for name in workflow.__all__)
assert private.get_ip_document_policies is documents.get_ip_document_policies
assert coverage.CalendarProjectionTombstoneResult is tombstones.CalendarProjectionTombstoneResult
assert (coverage.tombstone_membership_calendar_projections
        is tombstones.tombstone_membership_calendar_projections)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(SRC), first, *WORKFLOWS],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_extracted_document_policy_retains_fail_closed_threshold() -> None:
    from caseops_api.db.models import IpDocument, IpDocumentVersion
    from caseops_api.services.ip_document_policy import _policy

    document = IpDocument(is_privileged=False, confidentiality="internal")
    version = IpDocumentVersion(processing_status="indexed", ocr_quality_score=0.65)
    allowed = _policy(document, version, domain_disclosure_allowed=True)
    assert allowed.ai_retrieval_allowed
    for attribute, value in (
        ("is_privileged", True),
        ("confidentiality", "restricted"),
    ):
        original = getattr(document, attribute)
        setattr(document, attribute, value)
        denied = _policy(document, version, domain_disclosure_allowed=True)
        assert not denied.ai_retrieval_allowed
        assert not denied.portal_share_allowed
        assert not denied.export_allowed
        assert not denied.notification_content_allowed
        assert denied.reasons
        setattr(document, attribute, original)
    version.ocr_quality_score = 0.649
    assert not _policy(document, version, domain_disclosure_allowed=True).ai_retrieval_allowed
    version.ocr_quality_score = 0.65
    version.processing_status = "processing"
    assert not _policy(document, version, domain_disclosure_allowed=True).ai_retrieval_allowed
    version.processing_status = "indexed"
    denied = _policy(document, version, domain_disclosure_allowed=False)
    assert not denied.ai_retrieval_allowed
    assert not denied.portal_share_allowed
    assert not denied.export_allowed
    assert not denied.notification_content_allowed


def test_document_workflow_has_explicit_complete_public_exports() -> None:
    module = SERVICE_PREFIX + "ip_document_workflow"
    tree = ast.parse((SRC / "caseops_api/services/ip_document_workflow.py").read_text())
    declarations = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(declarations) == 1, "Declare the workflow's real public API explicitly"
    assert isinstance(declarations[0].value, ast.List), "Exports must be a literal, nonopaque list"
    exports = ast.literal_eval(declarations[0].value)
    assert all(isinstance(name, str) for name in exports)
    assert len(exports) == len(set(exports))
    expected = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    } | {"get_accessible_ip_document_ids", "get_ip_document_policies"}
    assert set(exports) == expected
    for path in (SRC / "caseops_api").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and node.module == module:
                assert not any(alias.name == "*" for alias in node.names), path
                assert {
                    alias.name for alias in node.names if not alias.name.startswith("_")
                } <= expected, path


def test_upload_target_helpers_have_one_owner_without_a_worker_workflow_cycle(
    dependency_graph: dict[str, set[str]],
) -> None:
    from caseops_api.services import ip_document_targets, ip_document_workflow

    assert SERVICE_PREFIX + "ip_document_workflow" not in dependency_graph[
        SERVICE_PREFIX + "document_jobs"
    ]
    assert _route(
        dependency_graph, SERVICE_PREFIX + "ip_document_targets",
        SERVICE_PREFIX + "ip_document_workflow",
    ) is None
    for name in (
        "_target_docket_id", "_upload_target_lifecycles",
        "_upload_document_targets", "_lock_upload_targets",
    ):
        function = getattr(ip_document_targets, name)
        assert function.__module__ == SERVICE_PREFIX + "ip_document_targets"
        assert getattr(ip_document_workflow, name) is function


def test_private_access_helpers_have_leaf_ownership() -> None:
    helpers = {"_active_grant_window", "_active_ip_subject_match", "_active_wall_window"}
    facade = ast.parse((SRC / "caseops_api/services/matter_access.py").read_text())
    facade_imports = {
        alias.name
        for node in ast.walk(facade)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert helpers.isdisjoint(facade_imports), "Private helpers belong to record_access_policy"
    caller = ast.parse(Path(__file__).with_name("test_ip_patent_postgres.py").read_text())
    origins = {
        node.module
        for node in ast.walk(caller)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "_active_ip_subject_match"
    }
    assert origins == {SERVICE_PREFIX + "record_access_policy"}
