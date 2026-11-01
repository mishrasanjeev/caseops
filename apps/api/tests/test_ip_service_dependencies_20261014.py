"""Read-only IP source ownership and the Ops/Renewals/Delivery dependency DAG."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib.util import resolve_name
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PREFIX = "caseops_api.services."
SOURCE = PREFIX + "ip_portfolio_source"
VISIBILITY = PREFIX + "portal_publication_visibility"
WORKFLOWS = ("ip_operations", "ip_renewals", "notification_delivery")
# Function ASTs from ed856074f525b9f48a2cc7e15810e69eb14e378f before extraction.
EXTRACTED_AST = {
    "_portfolio_source": "9603ee29e8372c8fb955b480b434d3a54a5860b7b4e398be868cf3953add03ef",
    "_imported_source_row": "ec2a3e95fdf8a630733862ae61806a388ef9a2ffda903e068e65bd5771194dc3",
    "imported_renewal_reminder_is_current": (
        "2723aae4ddbe849ffe3163ded276be96cfbb8421259b1eb2aba42378588fb1d3"
    ),
}


def _graph(sources: dict[str, str], packages: set[str] | None = None) -> dict[str, set[str]]:
    graph = {}
    packages = packages or set()
    for module, source in sources.items():
        parts = module.split(".")
        imports = {".".join(parts[:length]) for length in range(1, len(parts))} & packages
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                owner = node.module or ""
                if node.level:
                    package = module if module in packages else module.rsplit(".", 1)[0]
                    owner = resolve_name("." * node.level + owner, package)
                imports.add(owner)
                imports.update(f"{owner}.{alias.name}" for alias in node.names)
        graph[module] = imports & sources.keys()
    return graph


def _route(graph: dict[str, set[str]], source: str, target: str) -> list[str] | None:
    remaining = [(source, [source])]
    visited = set()
    while remaining:
        current, path = remaining.pop()
        if current == target:
            return path
        if current in visited:
            continue
        visited.add(current)
        remaining.extend((child, [*path, child]) for child in sorted(graph.get(current, ())))
    return None


@pytest.fixture(scope="module")
def dependency_graph() -> dict[str, set[str]]:
    sources = {}
    packages = set()
    for path in (SRC / "caseops_api").rglob("*.py"):
        parts = path.relative_to(SRC).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
            packages.add(".".join(parts))
        sources[".".join(parts)] = path.read_text(encoding="utf-8-sig")
    return _graph(sources, packages)


@pytest.mark.parametrize(
    "source,target",
    [
        ("ip_operations", "ip_renewals"),
        ("ip_renewals", "notification_delivery"),
        ("ip_operations", "notification_delivery"),
        ("ip_operations", "ip_portfolio_dates_writer"),
    ],
)
def test_ip_workflow_dependencies_do_not_form_cycles(dependency_graph, source, target):
    forward = _route(dependency_graph, PREFIX + source, PREFIX + target)
    reverse = _route(dependency_graph, PREFIX + target, PREFIX + source)
    assert not (forward and reverse), (forward, reverse)


def test_portfolio_date_writer_has_one_way_dependency_on_canonical_operations(dependency_graph):
    writer = PREFIX + "ip_portfolio_dates_writer"
    operations = PREFIX + "ip_operations"
    assert operations in dependency_graph[writer]
    assert _route(dependency_graph, operations, writer) is None


def test_legacy_portfolio_date_route_uses_the_owned_writer():
    tree = ast.parse((SRC / "caseops_api/api/routes/ip_operations.py").read_text())
    owners = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "update_imported_renewal_date" for alias in node.names)
    }
    assert owners == {PREFIX + "ip_portfolio_dates_writer"}
    route = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "patch_portfolio_renewal_date"
    )
    assert ast.unparse(route.returns) == "IpDocketRecordResponse"
    payload = next(argument for argument in route.args.args if argument.arg == "payload")
    assert ast.unparse(payload.annotation) == "IpPortfolioRenewalDateUpdateRequest"
    assert any(
        isinstance(node, ast.Constant)
        and node.value == "/dockets/{docket_id}/portfolio-renewal-date"
        for node in ast.walk(route.decorator_list[0])
    )
    calls = [
        node
        for node in ast.walk(route)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_in_threadpool"
    ]
    assert len(calls) == 1
    assert ast.unparse(calls[0].args[0]) == "update_imported_renewal_date"


@pytest.mark.parametrize("first", ["ip_operations", "ip_portfolio_dates_writer"])
def test_portfolio_date_services_import_cleanly_in_both_orders(first):
    import os
    import subprocess
    import sys

    second = "ip_portfolio_dates_writer" if first == "ip_operations" else "ip_operations"
    env = os.environ.copy()
    env.update(
        CASEOPS_ENV="local",
        CASEOPS_DATABASE_URL="sqlite+pysqlite:///:memory:",
        CASEOPS_AUTO_MIGRATE="false",
        CASEOPS_LLM_PROVIDER="mock",
        CASEOPS_EMBEDDING_PROVIDER="mock",
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            f"import importlib; importlib.import_module('{PREFIX}{first}'); "
            f"importlib.import_module('{PREFIX}{second}'); "
            f"writer = importlib.import_module('{PREFIX}ip_portfolio_dates_writer'); "
            "assert writer.update_imported_renewal_date.__module__ == "
            f"'{PREFIX}ip_portfolio_dates_writer'",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_source_leaf_cannot_reach_workflows(dependency_graph, workflow):
    assert _route(dependency_graph, SOURCE, PREFIX + workflow) is None


@pytest.mark.parametrize(
    "statement",
    [
        "from caseops_api.services.ip_operations import create_ip_docket",
        "from caseops_api.services import ip_operations as writer",
        "from . import ip_operations as writer",
        "import caseops_api.services.ip_operations as writer",
    ],
)
def test_dependency_graph_detects_local_alias_and_relative_back_edges(statement):
    sources = {
        SOURCE: "def probe():\n    " + statement,
        PREFIX + "ip_operations": "from .ip_portfolio_source import probe",
    }
    graph = _graph(sources)
    assert _route(graph, SOURCE, PREFIX + "ip_operations") == [SOURCE, PREFIX + "ip_operations"]
    assert _route(graph, PREFIX + "ip_operations", SOURCE) == [PREFIX + "ip_operations", SOURCE]


def test_dependency_graph_keeps_package_initializer_imports():
    package = PREFIX.rstrip(".")
    sources = {
        package: "from . import ip_operations",
        SOURCE: "pass",
        PREFIX + "ip_operations": "pass",
    }
    graph = _graph(sources, {package})
    assert _route(graph, SOURCE, PREFIX + "ip_operations") == [
        SOURCE,
        package,
        PREFIX + "ip_operations",
    ]


def test_source_leaf_has_only_model_and_sqlalchemy_dependencies():
    tree = ast.parse((SRC / "caseops_api/services/ip_portfolio_source.py").read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports == {"__future__", "sqlalchemy", "sqlalchemy.orm", "caseops_api.db.models"}


@pytest.mark.parametrize("name", EXTRACTED_AST)
def test_extracted_source_function_is_ast_identical(name):
    tree = ast.parse((SRC / "caseops_api/services/ip_portfolio_source.py").read_text())
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(functions) == 1
    assert (
        sha256(ast.dump(functions[0], include_attributes=False).encode()).hexdigest()
        == EXTRACTED_AST[name]
    )


@pytest.mark.parametrize("name", EXTRACTED_AST)
def test_renewals_compatibility_alias_is_the_same_source_function(name):
    from caseops_api.services import ip_portfolio_source, ip_renewals

    function = getattr(ip_portfolio_source, name)
    assert function.__module__ == SOURCE
    assert getattr(ip_renewals, name) is function


def test_notification_delivery_imports_the_neutral_predicate():
    tree = ast.parse((SRC / "caseops_api/services/notification_delivery.py").read_text())
    owners = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "imported_renewal_reminder_is_current" for alias in node.names)
    }
    assert owners == {SOURCE}
    from caseops_api.services import ip_portfolio_source

    assert ip_portfolio_source.__all__ == ["imported_renewal_reminder_is_current"]


def test_renewals_declares_its_public_workflow_and_compatibility_exports():
    from caseops_api.services import ip_portfolio_source, ip_renewals

    tree = ast.parse((SRC / "caseops_api/services/ip_renewals.py").read_text())
    declarations = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(declarations) == 1 and isinstance(declarations[0], ast.List)
    names = ast.literal_eval(declarations[0])
    public_functions = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert len(names) == len(set(names)) == 14
    assert set(names) == public_functions | {"imported_renewal_reminder_is_current"}
    assert ip_renewals.__all__ == names
    assert all(callable(getattr(ip_renewals, name)) for name in names)
    assert (
        ip_renewals.imported_renewal_reminder_is_current
        is ip_portfolio_source.imported_renewal_reminder_is_current
    )


class _ReadSession:
    def __init__(self, *, version=None, row=None):
        self.version = version
        self.row = row
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: self.version)

    def scalar(self, statement):
        self.statements.append(statement)
        return self.row


def _source_intent():
    return SimpleNamespace(
        company_id="company",
        ip_docket_id="docket",
        source_id="version",
        source_type="ip_trademark_particular_version",
        event_type="renewal_source_date_1month",
        metadata_json={"source_due_on": "2028-03-31"},
        schedule_source_type="ip_portfolio_renewal",
        schedule_source_id="docket",
    )


@pytest.mark.parametrize("value", [None, "wrong", [], False])
def test_non_mapping_portfolio_source_is_empty(value):
    from caseops_api.services.ip_portfolio_source import _portfolio_source

    assert _portfolio_source({"portfolio_import": value}) == {}


def test_portfolio_source_preserves_the_original_mapping():
    from caseops_api.services.ip_portfolio_source import _portfolio_source

    source = {"source_row_id": "a" * 36, "renewal_due_date": "2028-03-31"}
    assert _portfolio_source({"portfolio_import": source}) is source
    assert _portfolio_source({}) == {}


@pytest.mark.parametrize("row_id", [None, "", "short", 36])
def test_invalid_import_row_identity_does_not_query(row_id):
    from caseops_api.services.ip_portfolio_source import _imported_source_row

    session = _ReadSession()
    assert (
        _imported_source_row(
            session, company_id="company", docket_id="docket", source={"source_row_id": row_id}
        )
        is None
    )
    assert session.statements == []


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("source_type", "other"),
        ("event_type", "other"),
        ("metadata_json", {"source_due_on": "2028-04-30"}),
        ("metadata_json", None),
        ("schedule_source_type", "other"),
        ("schedule_source_id", "other"),
    ],
)
def test_current_source_predicate_rejects_changed_identity_or_date(attribute, value):
    from caseops_api.services.ip_portfolio_source import imported_renewal_reminder_is_current

    source = {"source_row_id": "a" * 36, "renewal_due_date": "2028-03-31"}
    session = _ReadSession(
        version=SimpleNamespace(representation_json={"portfolio_import": source}), row=object()
    )
    intent = _source_intent()
    setattr(intent, attribute, value)
    assert not imported_renewal_reminder_is_current(session, intent=intent)


@pytest.mark.parametrize(
    "version,row", [(None, object()), (SimpleNamespace(representation_json={}), object())]
)
def test_current_source_predicate_rejects_missing_version_or_source(version, row):
    from caseops_api.services.ip_portfolio_source import imported_renewal_reminder_is_current

    assert not imported_renewal_reminder_is_current(
        _ReadSession(version=version, row=row), intent=_source_intent()
    )


@pytest.mark.parametrize("provenance", [False, True])
def test_current_source_predicate_delegates_to_owned_provenance_helper(monkeypatch, provenance):
    from caseops_api.services import ip_portfolio_source

    source = {"source_row_id": "a" * 36, "renewal_due_date": "2028-03-31"}
    session = _ReadSession(
        version=SimpleNamespace(representation_json={"portfolio_import": source})
    )
    calls = []

    def resolve(session_arg, *, company_id, docket_id, source):
        calls.append((session_arg, company_id, docket_id, source))
        return object() if provenance else None

    monkeypatch.setattr(ip_portfolio_source, "_imported_source_row", resolve)
    assert (
        ip_portfolio_source.imported_renewal_reminder_is_current(session, intent=_source_intent())
        is provenance
    )
    assert calls == [(session, "company", "docket", source)]
    assert len(session.statements) == 1


@pytest.mark.parametrize("workflow", (*WORKFLOWS, "portal_ip", "ip_reports"))
def test_publication_visibility_cannot_reach_workflows(dependency_graph, workflow):
    assert _route(dependency_graph, VISIBILITY, PREFIX + workflow) is None


def test_portal_and_delivery_use_the_canonical_visibility_policy():
    from caseops_api.services import portal_ip, portal_publication_visibility

    for name in (
        "load_publication_visibility",
        "publication_access_state",
        "publication_is_available",
        "publication_target_is_current",
        "publication_grant_is_active",
    ):
        assert getattr(portal_ip, name) is getattr(portal_publication_visibility, name)
    tree = ast.parse((SRC / "caseops_api/services/notification_delivery.py").read_text())
    imported = {
        alias.name: node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name
        in {
            "load_publication_visibility",
            "publication_is_available",
            "publication_target_is_current",
        }
    }
    assert imported == {
        "load_publication_visibility": VISIBILITY,
        "publication_is_available": VISIBILITY,
        "publication_target_is_current": VISIBILITY,
    }


PUBLICATION_CASES = [
    ("available", "available"),
    ("report", "available"),
    ("scheduled-future", "scheduled"),
    ("scheduled-now", "available"),
    ("revoked", "revoked"),
    ("grant-revoked", "review_required"),
    ("grant-expired", "review_required"),
    ("grant-expired-naive", "review_required"),
    ("inactive", "review_required"),
    ("archived", "review_required"),
    ("docket-version", "review_required"),
    ("lifecycle-version", "review_required"),
    ("access-policy-version", "review_required"),
    ("restricted-domain", "review_required"),
    ("missing-targets", "review_required"),
    ("missing-version", "review_required"),
    ("missing-document", "review_required"),
    ("document-tenant", "review_required"),
    ("version-tenant", "review_required"),
    ("document-identity", "review_required"),
    ("document-version", "review_required"),
    ("privileged", "review_required"),
    ("confidentiality", "review_required"),
    ("non-disclosable", "review_required"),
    ("draft", "review_required"),
    ("filed", "available"),
    ("served", "available"),
    ("accepted", "available"),
]
TARGET_DENIALS = {
    "grant-revoked",
    "grant-expired",
    "grant-expired-naive",
    "inactive",
    "archived",
    "docket-version",
    "lifecycle-version",
    "access-policy-version",
    "restricted-domain",
}


def _publication_case(change):
    now = datetime(2028, 3, 31, 9, tzinfo=UTC)
    user = SimpleNamespace(
        id="portal-user", company_id="company", email="portal@example.invalid", is_active=True
    )
    publication = SimpleNamespace(
        id="publication",
        company_id="company",
        portal_user_id=user.id,
        status="published",
        scheduled_for=None,
        published_at=now - timedelta(hours=1),
        title="Reviewed publication",
        document_version_id="version",
        report_artifact_id=None,
        delivery_intent_id="intent",
        access_count=0,
        last_accessed_at=None,
    )
    target = SimpleNamespace(docket_version=3, lifecycle_version=7, access_policy_version=11)
    grant = SimpleNamespace(id="grant", revoked_at=None, expires_at=now + timedelta(days=1))
    docket = SimpleNamespace(
        id="docket",
        company_id="company",
        title="Reviewed docket",
        record_type="trademark",
        is_active=True,
        archived_by_matter_disposal=False,
        current_version=3,
        lifecycle_version=7,
        access_policy_version=11,
        matter_id=None,
    )
    document = SimpleNamespace(
        id="document",
        company_id="company",
        current_version=2,
        is_privileged=False,
        confidentiality="internal",
    )
    version = SimpleNamespace(
        document_id="document",
        company_id="company",
        version=2,
        state="approved",
        display_name="reviewed.pdf",
    )
    case = SimpleNamespace(
        now=now,
        user=user,
        publication=publication,
        grant=grant,
        docket=docket,
        target=target,
        version=version,
        document=document,
        targets=[(target, grant, docket)],
        disclosable={"document"},
        artifact=None,
        intent=SimpleNamespace(status="queued", dead_letter_reason=None),
    )
    mutations = {
        "grant-revoked": (grant, "revoked_at", now),
        "grant-expired": (grant, "expires_at", now),
        "grant-expired-naive": (grant, "expires_at", now.replace(tzinfo=None)),
        "inactive": (docket, "is_active", False),
        "archived": (docket, "archived_by_matter_disposal", True),
        "docket-version": (docket, "current_version", 4),
        "lifecycle-version": (docket, "lifecycle_version", 8),
        "access-policy-version": (docket, "access_policy_version", 12),
        "restricted-domain": (docket, "record_type", "patent_family"),
        "document-tenant": (document, "company_id", "other"),
        "version-tenant": (version, "company_id", "other"),
        "document-identity": (version, "document_id", "other"),
        "document-version": (document, "current_version", 3),
        "privileged": (document, "is_privileged", True),
        "confidentiality": (document, "confidentiality", "restricted"),
        "draft": (version, "state", "draft"),
        "filed": (version, "state", "filed"),
        "served": (version, "state", "served"),
        "accepted": (version, "state", "accepted"),
        "revoked": (publication, "status", "revoked"),
    }
    if change in mutations:
        subject, attribute, value = mutations[change]
        setattr(subject, attribute, value)
    elif change.startswith("scheduled-"):
        publication.status = "scheduled"
        publication.scheduled_for = now if change == "scheduled-now" else now + timedelta(hours=1)
        publication.published_at = None
    elif change == "missing-targets":
        case.targets = []
    elif change == "missing-version":
        case.version = None
    elif change == "missing-document":
        case.document = None
    elif change == "non-disclosable":
        case.disclosable = set()
    elif change == "report":
        publication.document_version_id = None
        publication.report_artifact_id = "artifact"
        case.version = case.document = None
        case.artifact = SimpleNamespace(
            report_kind="portfolio_register",
            schema_version="v1",
            generated_at=now,
            freshness_json={"source": "current"},
            summary_json={"count": 1},
            rows_json=[{"docket_title": "Reviewed docket"}],
        )
    else:
        assert change == "available"
    return case


class _PublicationSession:
    def __init__(self, case):
        self.case = case
        self.statements = []
        self.gets = []

    def scalar(self, statement):
        from caseops_api.db.models import MatterPortalGrant, PortalPublication

        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        if entity is MatterPortalGrant:
            return self.case.grant.id
        assert entity is PortalPublication
        return self.case.publication

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: self.case.targets)

    def scalars(self, statement):
        self.statements.append(statement)
        return iter(self.case.disclosable)

    def get(self, model, identity):
        from caseops_api.db.models import (
            Company,
            IpDocketRecord,
            IpDocument,
            IpDocumentVersion,
            NotificationDeliveryIntent,
            PortalUser,
            ReportArtifact,
        )

        self.gets.append((model, identity))
        return {
            Company: SimpleNamespace(is_active=True),
            IpDocketRecord: self.case.docket,
            IpDocument: self.case.document,
            IpDocumentVersion: self.case.version,
            PortalUser: self.case.user,
            ReportArtifact: self.case.artifact,
            NotificationDeliveryIntent: self.case.intent,
        }[model]


def _expected_publication_dto(case, change, state):
    def timestamp(value):
        return value.isoformat().replace("+00:00", "Z") if value is not None else None

    visible = state == "available"
    artifact = case.artifact if visible else None
    version = case.version if visible else None
    return {
        "id": "publication",
        "publication_kind": "report" if case.artifact else "document",
        "title": "Reviewed publication",
        "status": case.publication.status,
        "access_state": state,
        "scheduled_for": timestamp(case.publication.scheduled_for),
        "published_at": timestamp(
            case.publication.published_at
            or (case.publication.scheduled_for if state != "scheduled" else None)
        ),
        "delivery_status": "queued",
        "delivery_error": None,
        "report_kind": artifact.report_kind if artifact else None,
        "schema_version": artifact.schema_version if artifact else None,
        "generated_at": timestamp(artifact.generated_at) if artifact else None,
        "freshness": artifact.freshness_json if artifact else None,
        "summary": artifact.summary_json if artifact else None,
        "rows": artifact.rows_json if artifact else None,
        "document_id": version.document_id if version else None,
        "document_version": version.version if version else None,
        "document_filename": version.display_name if version else None,
        "targets": []
        if change == "missing-targets"
        else [
            {
                "ip_docket_record_id": "docket",
                "docket_title": "Restricted IP record"
                if change == "restricted-domain"
                else "Reviewed docket",
                "current": change not in TARGET_DENIALS,
            }
        ],
        "accessed_at": None,
    }


@pytest.mark.parametrize("change,state", PUBLICATION_CASES)
def test_publication_portal_delivery_and_loaded_dto_parity(monkeypatch, change, state):
    from caseops_api.schemas.portal_ip import PortalPublicationTargetRecord
    from caseops_api.services import notification_delivery, portal_ip, portal_publication_visibility

    case = _publication_case(change)
    monkeypatch.setattr(portal_ip, "_now", lambda: case.now)
    monkeypatch.setattr(notification_delivery, "_now", lambda: case.now)
    expected = _expected_publication_dto(case, change, state)
    session = _PublicationSession(case)
    record = portal_ip._publication_record(
        session, publication=case.publication, portal_user=case.user
    )
    assert record.model_dump(mode="json") == expected
    assert record.model_dump_json() == json.dumps(expected, separators=(",", ":"))
    loaded_session = _PublicationSession(case)
    loaded = portal_ip._publication_record(
        loaded_session,
        publication=case.publication,
        portal_user=case.user,
        dependencies_loaded=True,
        loaded_targets=[PortalPublicationTargetRecord(**target) for target in expected["targets"]],
        loaded_artifact=case.artifact,
        loaded_version=case.version,
        loaded_document=case.document,
        loaded_disclosable_document_ids=case.disclosable,
        loaded_intent=case.intent,
    )
    assert loaded.model_dump_json() == record.model_dump_json()
    assert loaded_session.statements == [] and loaded_session.gets == []
    assert portal_ip.portal_publication_is_available(
        _PublicationSession(case),
        portal_user=case.user,
        publication_id=case.publication.id,
    ) is (state == "available")
    inputs_session = _PublicationSession(case)
    visibility = portal_publication_visibility.load_publication_visibility(
        inputs_session,
        portal_user=case.user,
        publication_id=case.publication.id,
    )
    assert portal_publication_visibility.publication_is_available(
        visibility,
        portal_user=case.user,
        now=case.now,
    ) is (state == "available")
    from caseops_api.db.models import NotificationDeliveryIntent, ReportArtifact

    assert not {model for model, _identity in inputs_session.gets} & {
        NotificationDeliveryIntent,
        ReportArtifact,
    }
    intent = SimpleNamespace(
        company_id="company",
        recipient_membership_id=None,
        recipient_portal_user_id=case.user.id,
        matter_id=None,
        ip_docket_id="docket",
        source_type="portal_publication",
        source_id=case.publication.id,
        schedule_source_type="portal_publication",
    )
    assert notification_delivery._recipient_still_permitted(_PublicationSession(case), intent) is (
        state == "available"
    )


def test_visibility_loader_preserves_tenant_user_and_target_query_scope():
    from sqlalchemy import select

    from caseops_api.db.models import (
        IpDocketRecord,
        MatterPortalGrant,
        PortalPublication,
        PortalPublicationTarget,
    )
    from caseops_api.services.portal_publication_visibility import load_publication_visibility

    case = _publication_case("available")
    session = _PublicationSession(case)
    assert (
        load_publication_visibility(
            session,
            portal_user=case.user,
            publication_id=case.publication.id,
        )
        is not None
    )
    publication = select(PortalPublication).where(
        PortalPublication.id == case.publication.id,
        PortalPublication.company_id == case.user.company_id,
        PortalPublication.portal_user_id == case.user.id,
    )
    targets = (
        select(PortalPublicationTarget, MatterPortalGrant, IpDocketRecord)
        .join(MatterPortalGrant, MatterPortalGrant.id == PortalPublicationTarget.portal_grant_id)
        .join(IpDocketRecord, IpDocketRecord.id == PortalPublicationTarget.ip_docket_record_id)
        .where(
            PortalPublicationTarget.company_id == case.publication.company_id,
            PortalPublicationTarget.publication_id == case.publication.id,
        )
        .order_by(IpDocketRecord.title, IpDocketRecord.id)
    )
    assert session.statements[0].compare(publication)
    assert session.statements[1].compare(targets)


def test_missing_publication_is_unavailable_without_loading_targets(monkeypatch):
    from caseops_api.services import portal_ip, portal_publication_visibility

    case = _publication_case("available")
    case.publication = None
    session = _PublicationSession(case)
    assert (
        portal_publication_visibility.load_publication_visibility(
            session,
            portal_user=case.user,
            publication_id="missing",
        )
        is None
    )
    assert len(session.statements) == 1 and session.gets == []

    def unexpected_clock():
        pytest.fail("Missing publications do not need the original portal clock")

    monkeypatch.setattr(portal_ip, "_now", unexpected_clock)
    assert not portal_ip.portal_publication_is_available(
        _PublicationSession(case),
        portal_user=case.user,
        publication_id="missing",
    )


@pytest.mark.parametrize("available", [False, True])
def test_publication_record_preserves_access_audit_contract(monkeypatch, available):
    from caseops_api.db.models import AuditActorType, AuditResult
    from caseops_api.services import portal_ip

    case = _publication_case("available" if available else "grant-revoked")
    monkeypatch.setattr(portal_ip, "_now", lambda: case.now)
    audits = []

    def record(session, **values):
        audits.append((session, values))

    monkeypatch.setattr(portal_ip, "record_audit", record)
    session = _PublicationSession(case)
    result = portal_ip._publication_record(
        session,
        publication=case.publication,
        portal_user=case.user,
        record_access=True,
    )
    assert case.publication.access_count == int(available)
    assert case.publication.last_accessed_at == (case.now if available else None)
    assert result.accessed_at == (case.now if available else None)
    assert audits == (
        [
            (
                session,
                {
                    "company_id": case.user.company_id,
                    "actor_type": AuditActorType.SYSTEM,
                    "actor_label": f"portal:{case.user.email}",
                    "action": "portal.publication.opened",
                    "target_type": "portal_publication",
                    "target_id": case.publication.id,
                    "result": AuditResult.SUCCESS,
                    "metadata": {"portal_user_id": case.user.id},
                    "commit": True,
                },
            )
        ]
        if available
        else []
    )


def test_boolean_availability_uses_each_callers_clock_after_dependency_reads(monkeypatch):
    from caseops_api.db.models import IpDocument
    from caseops_api.services import notification_delivery, portal_ip

    case = _publication_case("available")
    current = [case.now]
    monkeypatch.setattr(portal_ip, "_now", lambda: current[0])
    monkeypatch.setattr(notification_delivery, "_now", lambda: current[0])

    class AdvancingSession(_PublicationSession):
        def get(self, model, identity):
            value = super().get(model, identity)
            if model is IpDocument:
                current[0] = case.now + timedelta(days=2)
            return value

    assert not portal_ip.portal_publication_is_available(
        AdvancingSession(case),
        portal_user=case.user,
        publication_id=case.publication.id,
    )
    current[0] = case.now
    intent = SimpleNamespace(
        company_id="company",
        recipient_membership_id=None,
        recipient_portal_user_id=case.user.id,
        matter_id=None,
        ip_docket_id="docket",
        source_type="portal_publication",
        source_id=case.publication.id,
        schedule_source_type="portal_publication",
    )
    assert not notification_delivery._recipient_still_permitted(AdvancingSession(case), intent)
