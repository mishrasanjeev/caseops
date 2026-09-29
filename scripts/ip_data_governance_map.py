#!/usr/bin/env python3
"""Build and enforce the repository data-governance inventory.

This is a Definition-of-Ready control, not a retention, legal-hold, export,
purge, offboarding, restore, or backup implementation.  It takes an explicit,
versioned snapshot of every SQLAlchemy table and column, plus the repository's
known non-SQL data classes.  A changed data-bearing migration or provider/
storage/telemetry boundary must change the map before CI accepts it.

The default disposition handler is deliberately fail-closed while the named
Records/Privacy/Legal/Security policy approvals remain outstanding.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, TypeGuard

REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "docs" / "ip-implementation" / "DATA_GOVERNANCE_MAP.yaml"
GENERATED_VIEW_PATH = (
    REPO_ROOT / "docs" / "ip-implementation" / "generated" / "DATA_GOVERNANCE_MAP.md"
)
MIGRATION_DIR = REPO_ROOT / "apps" / "api" / "alembic" / "versions"

MAP_STATUS = "repository_inventory_snapshot_policy_unapproved"
DEFAULT_HANDLER_ID = "registry_fail_closed"
MIGRATION_MARKER = "DATA-GOVERNANCE-MAP: updated"
REQUIRED_NON_SQL_KINDS = {
    "object_prefix_version",
    "cache",
    "sql_index_projection",
    "search_vector_index",
    "queue_outbox_dead_letter",
    "log_trace_metric",
    "export_artifact",
    "provider_held_object",
    "backup",
}
REQUIRED_POLICY_FIELDS = {
    "legal_policy_basis",
    "sensitivity",
    "default_retention",
    "tenant_configurable",
    "tenant_retention_bounds",
    "disposition",
    "hold_behavior",
    "source_licence_limits",
    "region_subprocessor",
    "owner",
}
REQUIRED_NON_SQL_FIELDS = {
    "id",
    "kind",
    "purpose",
    "legal_policy_basis",
    "sensitivity",
    "default_retention",
    "tenant_configurable",
    "tenant_retention_bounds",
    "disposition",
    "hold_behavior",
    "source_licence_limits",
    "region_subprocessor",
    "owner",
    "disposition_handler_id",
    "status",
    "implementation_refs",
}
RISKY_PATHS = {
    "apps/api/src/caseops_api/core/observability.py",
    "apps/api/src/caseops_api/core/settings.py",
    "apps/api/src/caseops_api/services/document_storage.py",
    "apps/api/src/caseops_api/services/domain_outbox.py",
    "apps/api/src/caseops_api/services/embeddings.py",
    "apps/api/src/caseops_api/services/llm.py",
    "infra/cloudrun/document-worker-job.yaml",
}
RISKY_SOURCE_ROOTS = (
    "apps/api/src/",
    "apps/web/",
    "infra/",
)
# Matches a real provider/storage/telemetry boundary, not a passing mention of
# the word. The bare-word form used to fire on ordinary prose - a comment saying
# "Inbound legal requests from business units" and the route path
# `/api/intake/requests` both tripped it - which meant every edit to models.py or
# endpoints.ts demanded a governance-map regeneration that produced no diff.
# Anchoring on an import or an attribute access keeps the detection and drops the
# noise.
_RISKY_MODULES = (
    r"google\.cloud|boto3|azure\.storage|openai|anthropic|voyageai|google\.genai|"
    r"opentelemetry|redis|pubsub|httpx|requests|aiohttp|urllib3"
)
RISKY_SOURCE_PATTERN = re.compile(
    # `import x`, `from x import ...`, `require('x')`, `from "x"`
    rf"(?:^|\n)\s*(?:import|from)\s+(?:{_RISKY_MODULES})\b"
    # The `@?` matters: provider SDKs ship scoped on npm, so the real import is
    # `from "@opentelemetry/api"`. Anchoring the bare name to the quote missed
    # every one of them.
    rf"|require\(\s*['\"]@?(?:{_RISKY_MODULES})"
    rf"|from\s+['\"]@?(?:{_RISKY_MODULES})"
    # attribute access on the module, e.g. httpx.post(, redis.Redis(
    rf"|\b(?:{_RISKY_MODULES})\s*\.\s*\w+\s*\("
    # unambiguous single-token boundaries that are never ordinary prose
    r"|\bstorage\.Client\b|\bOTLPSpanExporter\b|\bcloud.?tasks\b",
    re.IGNORECASE,
)
# Anchoring on import/attribute syntax only works in files that HAVE syntax.
# Deploy manifests are YAML and Terraform: they name a provider boundary as a
# bare word by nature - an image reference, an env var, a sidecar - so the
# pattern above matches nothing in them. `infra/` is a RISKY_SOURCE_ROOT, and
# applying the code pattern there would leave the root advertised but unwatched,
# which is worse than not listing it. Manifests also carry none of the English
# prose that made bare-word matching noisy in source files, so the original form
# is still the right one here.
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
RISKY_MANIFEST_PATTERN = re.compile(
    rf"\b(?:{_RISKY_MODULES}|storage\.Client|OTLPSpanExporter|cloud.?tasks)\b",
    re.IGNORECASE,
)


def risky_source_match(path: str, source: str) -> bool:
    """Detect a provider/storage/telemetry boundary in a changed file."""
    pattern = (
        RISKY_SOURCE_PATTERN
        if path.endswith(_CODE_SUFFIXES)
        else RISKY_MANIFEST_PATTERN
    )
    return bool(pattern.search(source))


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata() -> Any:
    # Importing models registers every SQLAlchemy table with Base.metadata.
    from caseops_api.db import models  # noqa: F401
    from caseops_api.db.base import Base

    return Base.metadata


def _column_type(column: Any) -> str:
    return str(column.type)


def current_sql_schema() -> dict[str, dict[str, dict[str, object]]]:
    """Return a deterministic table/column snapshot from the ORM metadata."""

    snapshot: dict[str, dict[str, dict[str, object]]] = {}
    for table_name, table in sorted(_metadata().tables.items()):
        snapshot[table_name] = {
            column.name: {
                "sql_type": _column_type(column),
                "nullable": bool(column.nullable),
            }
            for column in sorted(table.columns, key=lambda value: value.name)
        }
    return snapshot


def current_orm_indexes() -> list[dict[str, object]]:
    """Return all ORM-declared relational indexes as derived data classes."""

    indexes: list[dict[str, object]] = []
    for table_name, table in sorted(_metadata().tables.items()):
        for index in table.indexes:
            indexes.append(
                {
                    "table_name": table_name,
                    "index_name": str(index.name),
                    "columns": [column.name for column in index.columns],
                    "unique": bool(index.unique),
                }
            )
    return sorted(
        indexes,
        key=lambda item: (
            str(item["table_name"]),
            str(item["index_name"]),
            tuple(str(column) for column in item["columns"]),
        ),
    )


class MigrationIndexInventoryError(ValueError):
    """A migration declares an index whose name cannot be determined."""


class _Unresolvable(Exception):
    """A value that cannot be known without running the migration."""


# The name must be followed by ON, so a keyword such as IF can never be taken
# for a name when the real name is not literal text.
_CREATE_INDEX_START = re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE)
_CREATE_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>\"[^\"\x00]+\"|[A-Za-z_][A-Za-z0-9_]*|\x00)\s+ON\b",
    re.IGNORECASE,
)
_INDEX_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SQL_KEYWORDS = frozenset(
    {"CONCURRENTLY", "EXISTS", "IF", "INDEX", "NOT", "ON", "ONLY", "UNIQUE", "USING"}
)
_UNRESOLVED = "\x00"
_UNKNOWN = object()
_MAX_DEPTH = 8
_MAX_BINDINGS = 10_000
_STR_METHODS = frozenset({"join", "lower", "lstrip", "replace", "rstrip", "strip", "upper"})
_SEQUENCE_BUILTINS = frozenset({"list", "reversed", "sorted", "tuple"})
_UNDETERMINABLE_DDL = "CREATE INDEX name is not determinable statically"
_UNDETERMINABLE_CALL = "create_index name is not determinable statically"


class _ReviewedDatabaseDerivedIndexes(NamedTuple):
    # (enclosing function, whitespace-normalized source) of each reviewed
    # declaration, listed once per occurrence.
    declarations: tuple[tuple[str, str], ...]
    # Names the migration also declares through module constants.
    names: Callable[[Mapping[str, object]], list[object]]


# Migrations that read index names from the live database while they run:
# they index foreign keys found without a covering index. Those names cannot be
# known statically. Only the listed declarations are exempt, and only from an
# undeterminable name: an added, duplicated or edited declaration in the same
# migration fails closed like one anywhere else, and so does a reviewed
# declaration that is no longer present. The names the migration declares
# through module constants are still inventoried, and the release index-health
# gate proves complete foreign-key coverage.
_REVIEWED_DATABASE_DERIVED_INDEXES: dict[str, _ReviewedDatabaseDerivedIndexes] = {
    "20260827_0001_complete_foreign_key_indexes.py": _ReviewedDatabaseDerivedIndexes(
        declarations=(
            (
                "_postgres_create_indexes",
                'f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_quote(connection, name)} " '
                'f"ON {_quote(connection, table_name)} ({quoted_columns})"',
            ),
            ("upgrade", "op.create_index(name, table_name, list(columns))"),
        ),
        names=lambda env: [
            env["HOT_INDEX"],
            *(spec[0] for spec in env["IMPLICIT_INDEX_REQUIREMENTS"]),  # type: ignore[attr-defined]
        ],
    ),
    "20260909_0004_patent_prosecution_evidence.py": _ReviewedDatabaseDerivedIndexes(
        declarations=(("_support_indexes", "op.create_index(name, table, columns)"),),
        names=lambda env: [],
    ),
}


def _target_names(target: ast.AST) -> set[str]:
    return {
        node.id
        for node in ast.walk(target)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


def _bind(target: ast.AST, value: object, env: dict[str, object]) -> None:
    if isinstance(target, ast.Name):
        env[target.id] = value
        return
    if isinstance(target, ast.Tuple | ast.List):
        if not isinstance(value, tuple) or len(value) != len(target.elts):
            raise _Unresolvable
        for element, item in zip(target.elts, value, strict=True):
            _bind(element, item, env)
        return
    raise _Unresolvable


def _without(env: Mapping[str, object], names: set[str]) -> dict[str, object]:
    return {name: value for name, value in env.items() if name not in names}


def _is_prose(statement: ast.stmt) -> bool:
    """Docstrings and bare string statements are prose, never executed DDL."""

    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    return [statement for statement in function.body if not _is_prose(statement)]


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    arguments = function.args
    return [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ]


def _is_index_name(name: object) -> TypeGuard[str]:
    return (
        isinstance(name, str)
        and _INDEX_NAME.fullmatch(name) is not None
        and name.upper() not in _SQL_KEYWORDS
    )


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    """Name the function or class that lexically contains each node."""

    owners: dict[int, str] = {}
    pending: list[tuple[ast.AST, str]] = [(tree, "<module>")]
    while pending:
        node, owner = pending.pop()
        for child in ast.iter_child_nodes(node):
            scope = owner
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                scope = child.name if owner == "<module>" else f"{owner}.{child.name}"
            owners[id(child)] = scope
            pending.append((child, scope))
    return owners


class _Evaluator:
    """Evaluate migration expressions without executing any migration code."""

    def __init__(
        self,
        functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
        module_env: Mapping[str, object],
    ) -> None:
        self.functions = functions
        self.module_env = module_env

    def partial(self, node: ast.AST, env: Mapping[str, object], depth: int) -> object:
        try:
            return self.value(node, env, depth)
        except _Unresolvable:
            return _UNKNOWN

    def truth(self, node: ast.AST, env: Mapping[str, object], depth: int) -> bool:
        return bool(self.value(node, env, depth))

    def value(self, node: ast.AST, env: Mapping[str, object], depth: int = 0) -> object:
        if depth > _MAX_DEPTH:
            raise _Unresolvable
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            found = env.get(node.id, _UNKNOWN)
            if found is _UNKNOWN:
                raise _Unresolvable
            return found
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            if any(isinstance(element, ast.Starred) for element in node.elts):
                raise _Unresolvable
            return tuple(self.partial(element, env, depth) for element in node.elts)
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise _Unresolvable
            return {
                self.value(key, env, depth): self.partial(item, env, depth)
                for key, item in zip(node.keys, node.values, strict=True)
                if key is not None
            }
        if isinstance(node, ast.JoinedStr):
            return self.render(node, env, depth, strict=True)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.value(node.left, env, depth)
            right = self.value(node.right, env, depth)
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, tuple) and isinstance(right, tuple):
                return left + right
            raise _Unresolvable
        if isinstance(node, ast.IfExp):
            chosen = node.body if self.truth(node.test, env, depth) else node.orelse
            return self.value(chosen, env, depth)
        if isinstance(node, ast.BoolOp):
            results = [self.truth(item, env, depth) for item in node.values]
            return all(results) if isinstance(node.op, ast.And) else any(results)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self.truth(node.operand, env, depth)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            return self.compare(node, env, depth)
        if isinstance(node, ast.Subscript):
            container = self.value(node.value, env, depth)
            index = self.value(node.slice, env, depth)
            if not isinstance(container, str | tuple | dict):
                raise _Unresolvable
            try:
                item = container[index]  # type: ignore[index]
            except (IndexError, KeyError, TypeError) as exc:
                raise _Unresolvable from exc
            if item is _UNKNOWN:
                raise _Unresolvable
            return item
        if isinstance(node, ast.Slice):
            parts = [
                None if part is None else self.value(part, env, depth)
                for part in (node.lower, node.upper, node.step)
            ]
            if not all(part is None or isinstance(part, int) for part in parts):
                raise _Unresolvable
            return slice(*parts)
        if isinstance(node, ast.GeneratorExp | ast.ListComp | ast.SetComp):
            return self.comprehension(node, env, depth)
        if isinstance(node, ast.Call):
            return self.call(node, env, depth)
        raise _Unresolvable

    def compare(self, node: ast.Compare, env: Mapping[str, object], depth: int) -> bool:
        left = self.value(node.left, env, depth)
        right = self.value(node.comparators[0], env, depth)
        operator = node.ops[0]
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.In | ast.NotIn):
            if not isinstance(right, str | tuple | dict):
                raise _Unresolvable
            contained = left in right  # type: ignore[operator]
            return contained if isinstance(operator, ast.In) else not contained
        if isinstance(operator, ast.Is | ast.IsNot) and right is None:
            return (left is None) == isinstance(operator, ast.Is)
        raise _Unresolvable

    def comprehension(
        self,
        node: ast.GeneratorExp | ast.ListComp | ast.SetComp,
        env: Mapping[str, object],
        depth: int,
    ) -> tuple[object, ...]:
        if len(node.generators) != 1 or node.generators[0].is_async:
            raise _Unresolvable
        generator = node.generators[0]
        iterable = self.value(generator.iter, env, depth)
        if not isinstance(iterable, tuple):
            raise _Unresolvable
        results: list[object] = []
        for item in iterable:
            scope = dict(env)
            _bind(generator.target, item, scope)
            if all(self.truth(condition, scope, depth) for condition in generator.ifs):
                results.append(self.partial(node.elt, scope, depth))
        return tuple(results)

    def call(self, node: ast.Call, env: Mapping[str, object], depth: int) -> object:
        function = node.func
        if isinstance(function, ast.Name) and function.id in _SEQUENCE_BUILTINS:
            if len(node.args) != 1 or node.keywords:
                raise _Unresolvable
            sequence = self.value(node.args[0], env, depth)
            if isinstance(sequence, dict):
                sequence = tuple(sequence)
            if not isinstance(sequence, tuple):
                raise _Unresolvable
            if function.id == "reversed":
                return tuple(reversed(sequence))
            if function.id == "sorted":
                try:
                    return tuple(sorted(sequence))  # type: ignore[type-var]
                except TypeError as exc:
                    raise _Unresolvable from exc
            return sequence
        if isinstance(function, ast.Name) and function.id in self.functions:
            helper = self.functions[function.id]
            body = _body(helper)
            if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
                raise _Unresolvable
            return self.value(body[0].value, self.arguments(helper, node, env, depth), depth + 1)
        if isinstance(function, ast.Attribute):
            if function.attr == "f" and len(node.args) == 1 and not node.keywords:
                return self.value(node.args[0], env, depth)
            owner = self.value(function.value, env, depth)
            if isinstance(owner, dict) and function.attr in {"items", "keys", "values"}:
                if node.args or node.keywords:
                    raise _Unresolvable
                return tuple(getattr(owner, function.attr)())
            if isinstance(owner, str) and function.attr in _STR_METHODS and not node.keywords:
                arguments = [self.value(argument, env, depth) for argument in node.args]
                if function.attr == "join" and not (
                    len(arguments) == 1
                    and isinstance(arguments[0], tuple)
                    and all(isinstance(part, str) for part in arguments[0])
                ):
                    raise _Unresolvable
                if function.attr != "join" and not all(
                    isinstance(argument, str) for argument in arguments
                ):
                    raise _Unresolvable
                try:
                    return getattr(owner, function.attr)(*arguments)
                except (TypeError, ValueError) as exc:
                    raise _Unresolvable from exc
        raise _Unresolvable

    def arguments(
        self,
        helper: ast.FunctionDef | ast.AsyncFunctionDef,
        call: ast.Call,
        env: Mapping[str, object],
        depth: int,
    ) -> dict[str, object]:
        """Bind a helper's parameters from one call site; unknown stays unknown."""

        parameters = _parameters(helper)
        scope = _without(self.module_env, {parameter.arg for parameter in parameters})
        arguments = helper.args
        positional = [*arguments.posonlyargs, *arguments.args]
        defaulted = positional[len(positional) - len(arguments.defaults):]
        defaults = dict(
            zip(
                [parameter.arg for parameter in defaulted],
                arguments.defaults,
                strict=True,
            )
        )
        defaults.update(
            {
                parameter.arg: default
                for parameter, default in zip(
                    arguments.kwonlyargs, arguments.kw_defaults, strict=True
                )
                if default is not None
            }
        )
        for parameter, default in defaults.items():
            scope[parameter] = self.partial(default, self.module_env, depth)
        unpacked = False
        for index, argument in enumerate(call.args):
            if isinstance(argument, ast.Starred):
                # Positions after an unpacked argument are unknown.
                unpacked = True
                for parameter in positional[index:]:
                    scope.pop(parameter.arg, None)
                break
            if index < len(positional):
                scope[positional[index].arg] = self.partial(argument, env, depth)
            elif arguments.vararg is None:
                raise _Unresolvable
        if arguments.vararg is not None:
            extra = call.args[len(positional):]
            scope[arguments.vararg.arg] = (
                _UNKNOWN
                if unpacked
                else tuple(self.partial(argument, env, depth) for argument in extra)
            )
        names = {parameter.arg for parameter in [*positional, *arguments.kwonlyargs]}
        explicit: set[str] = set()
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            if keyword.arg not in names:
                if arguments.kwarg is None:
                    raise _Unresolvable
                continue
            explicit.add(keyword.arg)
            scope[keyword.arg] = self.partial(keyword.value, env, depth)
        if any(keyword.arg is None for keyword in call.keywords):
            # A **mapping may supply any parameter not passed explicitly.
            for name in names - explicit:
                scope.pop(name, None)
        return {name: value for name, value in scope.items() if value is not _UNKNOWN}

    def render(
        self, node: ast.JoinedStr, env: Mapping[str, object], depth: int, *, strict: bool
    ) -> str:
        parts: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
                continue
            try:
                if not isinstance(part, ast.FormattedValue) or part.format_spec is not None:
                    raise _Unresolvable
                if part.conversion not in (-1, ord("s")):
                    raise _Unresolvable
                value = self.value(part.value, env, depth)
                if not isinstance(value, str | int) or isinstance(value, bool):
                    raise _Unresolvable
                parts.append(str(value))
            except _Unresolvable:
                if strict:
                    raise
                parts.append(_UNRESOLVED)
        return "".join(parts)


class _MigrationIndexScanner:
    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.names: set[str] = set()
        # One entry per declaration and reason, however many bindings reach it.
        self.problems: dict[tuple[int, int, str], ast.AST] = {}
        self.functions = {
            statement.name: statement
            for statement in tree.body
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        self.module_env: dict[str, object] = {}
        self.evaluator = _Evaluator(self.functions, self.module_env)
        for statement in tree.body:
            # Replace in place: the evaluator holds this mapping, and a name
            # reassigned to an unknown value must be forgotten.
            updated = self.assign(statement, [dict(self.module_env)], 0)[0]
            self.module_env.clear()
            self.module_env.update(updated)
        self.reached: set[str] = set()

    def problem(self, node: ast.AST, reason: str) -> None:
        key = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0), reason)
        self.problems.setdefault(key, node)

    def scan(self) -> None:
        top_level = [
            statement
            for statement in self.tree.body
            if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        self.block(top_level, [dict(self.module_env)], 0)
        for entry in ("upgrade", "downgrade"):
            if entry in self.functions:
                self.reached.add(entry)
                self.block(_body(self.functions[entry]), [dict(self.module_env)], 0)
        # A helper never reached from a known call site keeps unknown parameters.
        for name, function in self.functions.items():
            if name not in self.reached:
                self.reached.add(name)
                parameters = {parameter.arg for parameter in _parameters(function)}
                self.block(_body(function), [_without(self.module_env, parameters)], 0)

    def block(self, statements: list[ast.stmt], envs: list[dict[str, object]], depth: int) -> None:
        if len(envs) > _MAX_BINDINGS:
            if statements:
                self.problem(statements[0], "too many loop bindings to resolve")
            return
        for statement in statements:
            if _is_prose(statement):
                continue
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                parameters = {parameter.arg for parameter in _parameters(statement)}
                self.block(_body(statement), [_without(env, parameters) for env in envs], depth)
                envs = [_without(env, {statement.name}) for env in envs]
                continue
            if isinstance(statement, ast.ClassDef):
                self.block(statement.body, envs, depth)
                continue
            if isinstance(statement, ast.For | ast.AsyncFor):
                self.expressions(statement.iter, envs, depth)
                names = _target_names(statement.target)
                expanded: list[dict[str, object]] = []
                for env in envs:
                    try:
                        items = self.evaluator.value(statement.iter, env, depth)
                        if isinstance(items, dict):
                            items = tuple(items)
                        if not isinstance(items, tuple):
                            raise _Unresolvable
                        for item in items:
                            bound = dict(env)
                            _bind(statement.target, item, bound)
                            expanded.append(
                                {
                                    key: value
                                    for key, value in bound.items()
                                    if value is not _UNKNOWN
                                }
                            )
                    except _Unresolvable:
                        expanded.append(_without(env, names))
                self.block(statement.body, expanded, depth)
                self.block(statement.orelse, envs, depth)
            elif isinstance(statement, ast.If | ast.While):
                self.expressions(statement.test, envs, depth)
                self.block(statement.body, envs, depth)
                self.block(statement.orelse, envs, depth)
            elif isinstance(statement, ast.With | ast.AsyncWith):
                for item in statement.items:
                    self.expressions(item.context_expr, envs, depth)
                self.block(statement.body, envs, depth)
            elif isinstance(statement, ast.Try | ast.TryStar):
                self.block(statement.body, envs, depth)
                for handler in statement.handlers:
                    self.block(handler.body, envs, depth)
                self.block(statement.orelse, envs, depth)
                self.block(statement.finalbody, envs, depth)
            else:
                self.expressions(statement, envs, depth)
                envs = self.assign(statement, envs, depth)
                continue
            # A compound statement may rebind names; forget them afterwards.
            assigned = {
                node.id
                for node in ast.walk(statement)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            }
            envs = [_without(env, assigned) for env in envs]

    def assign(
        self, statement: ast.stmt, envs: list[dict[str, object]], depth: int
    ) -> list[dict[str, object]]:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets, value = [statement.target], statement.value
        elif isinstance(statement, ast.AugAssign):
            targets = [statement.target]
        if not targets:
            return envs
        updated: list[dict[str, object]] = []
        for env in envs:
            current = dict(env)
            for target in targets:
                try:
                    if value is None:
                        raise _Unresolvable
                    _bind(target, self.evaluator.value(value, env, depth), current)
                except _Unresolvable:
                    current = _without(current, _target_names(target))
            updated.append({key: item for key, item in current.items() if item is not _UNKNOWN})
        return updated

    def expressions(self, node: ast.AST, envs: list[dict[str, object]], depth: int) -> None:
        fragments = {
            id(part)
            for joined in ast.walk(node)
            if isinstance(joined, ast.JoinedStr)
            for part in joined.values
        }
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute) and child.func.attr == "create_index":
                    self.create_index(child, envs, depth)
                if isinstance(child.func, ast.Name) and child.func.id in self.functions:
                    self.inline(child, envs, depth)
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if id(child) not in fragments:
                    self.ddl(child, [child.value])
            elif isinstance(child, ast.JoinedStr):
                self.ddl(
                    child,
                    [self.evaluator.render(child, env, depth, strict=False) for env in envs],
                )

    def inline(self, call: ast.Call, envs: list[dict[str, object]], depth: int) -> None:
        """Scan a helper's body once per call-site binding of its parameters."""

        assert isinstance(call.func, ast.Name)
        helper = self.functions[call.func.id]
        self.reached.add(call.func.id)
        if depth >= _MAX_DEPTH:
            self.problem(call, "helper calls nest too deeply to resolve")
            return
        scopes: list[dict[str, object]] = []
        for env in envs:
            try:
                scopes.append(self.evaluator.arguments(helper, call, env, depth))
            except _Unresolvable:
                parameters = {parameter.arg for parameter in _parameters(helper)}
                scopes.append(_without(self.module_env, parameters))
        self.block(_body(helper), scopes, depth + 1)

    def create_index(self, call: ast.Call, envs: list[dict[str, object]], depth: int) -> None:
        argument: ast.expr | None = call.args[0] if call.args else None
        for keyword in call.keywords:
            if keyword.arg == "index_name":
                argument = keyword.value
        if argument is None:
            self.problem(call, "create_index without an index name")
            return
        for env in envs:
            try:
                name = self.evaluator.value(argument, env, depth)
            except _Unresolvable:
                self.problem(call, _UNDETERMINABLE_CALL)
                continue
            self.record(call, name)

    def ddl(self, node: ast.AST, texts: list[str]) -> None:
        for text in texts:
            for start in _CREATE_INDEX_START.finditer(text):
                match = _CREATE_INDEX.match(text, start.start())
                if match is None:
                    self.problem(node, "CREATE INDEX statement without a parseable name")
                    continue
                name = match.group("name")
                if name == _UNRESOLVED:
                    self.problem(node, _UNDETERMINABLE_DDL)
                    continue
                self.record(node, name.strip('"'))

    def record(self, node: ast.AST, name: object) -> None:
        if not _is_index_name(name):
            self.problem(node, f"index name {name!r} is not an identifier")
            return
        self.names.add(name)


def _migration_index_names() -> list[str]:
    """Inventory index declarations that are not always represented by the ORM.

    The fingerprint intentionally includes conventional Alembic declarations and
    raw PostgreSQL search/vector DDL.  It is a release guard, not an inference
    that every index has a different retention rule: indexes inherit the source
    table/column class and the explicit derived-index classes below.

    Each migration is parsed, never executed or pattern-matched as raw text:
    comments and docstrings are not read, adjacent string literals are joined,
    and names built from literals, module constants, loops over constant
    sequences and the migration's own helper functions are resolved. A
    declaration whose name cannot be determined fails closed unless it is
    one of the reviewed database-derived declarations.
    """

    names: set[str] = set()
    problems: list[str] = []
    for path in sorted(MIGRATION_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        scanner = _MigrationIndexScanner(path, ast.parse(source, filename=str(path)))
        scanner.scan()
        reviewed = _REVIEWED_DATABASE_DERIVED_INDEXES.get(path.name)
        if reviewed is None:
            problems.extend(
                f"{path.name}:{line}: {reason}"
                for line, _column, reason in sorted(scanner.problems)
            )
        else:
            problems.extend(_reviewed_problems(path, source, scanner, reviewed))
        names.update(scanner.names)
    if problems:
        raise MigrationIndexInventoryError(
            "migration index inventory cannot name every declaration: "
            + "; ".join(dict.fromkeys(problems))
        )
    return sorted(names)


def _reviewed_problems(
    path: Path,
    source: str,
    scanner: _MigrationIndexScanner,
    reviewed: _ReviewedDatabaseDerivedIndexes,
) -> list[str]:
    """Exempt exactly the reviewed database-derived declarations; report the rest."""

    problems: list[str] = []
    try:
        declared = reviewed.names(scanner.module_env)
    except (IndexError, KeyError, TypeError):
        problems.append(f"{path.name}: reviewed module-constant index names cannot be resolved")
        declared = []
    for name in declared:
        if not _is_index_name(name):
            problems.append(
                f"{path.name}: reviewed module-constant index name {name!r} is not an identifier"
            )
            continue
        scanner.names.add(name)
    owners = _enclosing_functions(scanner.tree)
    found: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for (line, _column, reason), node in sorted(scanner.problems.items()):
        if reason not in (_UNDETERMINABLE_DDL, _UNDETERMINABLE_CALL):
            problems.append(f"{path.name}:{line}: {reason}")
            continue
        segment = ast.get_source_segment(source, node) or ""
        identity = (owners.get(id(node), "<module>"), " ".join(segment.split()))
        found.setdefault(identity, []).append((line, reason))
    expected = Counter(reviewed.declarations)
    for identity, occurrences in found.items():
        if len(occurrences) == expected[identity]:
            continue
        note = (
            f" ({len(occurrences)} identical declarations in {identity[0]}, "
            f"{expected[identity]} reviewed)"
            if expected[identity]
            else ""
        )
        problems.extend(f"{path.name}:{line}: {reason}{note}" for line, reason in occurrences)
    problems.extend(
        f"{path.name}: reviewed database-derived declaration in {function} "
        f"is no longer present: {text}"
        for function, text in expected
        if (function, text) not in found
    )
    return problems


def _policy_profiles() -> dict[str, dict[str, object]]:
    pending_basis = (
        "Pending named Records/Privacy/Legal/Security approval; this repository "
        "inventory is not an asserted legal retention basis or policy activation."
    )
    pending_retention = (
        "No approved automated retention duration. Preserve existing records under "
        "current operational controls and do not schedule expiry or destruction."
    )
    pending_bounds = (
        "No tenant override is available until an approved versioned policy defines "
        "per-tenant bounds, legal basis, and authority."
    )
    common = {
        "legal_policy_basis": pending_basis,
        "default_retention": pending_retention,
        "tenant_configurable": False,
        "tenant_retention_bounds": pending_bounds,
        "disposition": (
            "No automated retention, hold, export, purge, offboarding, restore, or "
            "provider-deletion action is authorized by this inventory."
        ),
        "hold_behavior": (
            "A future approved legal hold must block conflicting disposition; the "
            "current registry does not activate or execute a hold."
        ),
        "region_subprocessor": (
            "Pending approved deployment, residency, international-transfer, and "
            "subprocessor policy; no residency guarantee is asserted."
        ),
        "owner": "Codex",
    }
    return {
        "tenant_restricted_legal_content": {
            **common,
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Do not redistribute client, privileged, licensed, or source payload "
                "without the applicable approval and source terms."
            ),
        },
        "tenant_operational_record": {
            **common,
            "sensitivity": "confidential",
            "source_licence_limits": (
                "Record-specific source and contract limits must be checked before "
                "export or provider transmission."
            ),
        },
        "security_identity_control": {
            **common,
            "sensitivity": "restricted_security",
            "source_licence_limits": (
                "Never export authentication material, secrets, recovery codes, or "
                "provider credentials through a data operation."
            ),
        },
        "billing_provider_evidence": {
            **common,
            "sensitivity": "confidential_financial",
            "source_licence_limits": (
                "Provider, payment, and tax terms restrict disclosure; approved billing "
                "and legal review is required before export or deletion."
            ),
        },
        "public_or_licensed_legal_reference": {
            **common,
            "sensitivity": "internal_or_licensed_reference",
            "source_licence_limits": (
                "Authority, licence, attribution, retrieval, and redistribution terms "
                "must be verified; unverified material remains quarantined."
            ),
        },
        "platform_operational_reference": {
            **common,
            "sensitivity": "internal",
            "source_licence_limits": (
                "No external reuse or transfer is approved merely because a record is "
                "platform-scoped."
            ),
        },
    }


def _column_categories() -> dict[str, dict[str, object]]:
    return {
        "security_secret_or_credential": {
            "sensitivity": "restricted_security",
            "handling": "Redact from logs, exports, errors, metrics, and provider prompts.",
        },
        "privileged_or_raw_content": {
            "sensitivity": "privileged_or_confidential",
            "handling": (
                "Treat as content-bearing; retain, export, purge, and restore only "
                "through an approved handler."
            ),
        },
        "personal_or_contact_data": {
            "sensitivity": "confidential_personal_data",
            "handling": (
                "Do not expose through cross-tenant search, unaudited exports, or "
                "telemetry labels."
            ),
        },
        "financial_or_payment_data": {
            "sensitivity": "confidential_financial",
            "handling": (
                "Keep original evidence and do not expose payment data in telemetry or "
                "generic exports."
            ),
        },
        "external_or_provider_identifier": {
            "sensitivity": "confidential",
            "handling": (
                "Preserve provider terms and do not treat external identifiers as "
                "tenant-editable secrets."
            ),
        },
        "tenant_or_access_identifier": {
            "sensitivity": "confidential",
            "handling": (
                "Use only with company/access filtering; never use as an unauthenticated "
                "data-discovery key."
            ),
        },
        "derived_search_or_embedding_data": {
            "sensitivity": "confidential_derived_data",
            "handling": (
                "Reapply source access/tombstones before retrieval and before any future "
                "disposition action."
            ),
        },
        "lifecycle_or_audit_evidence": {
            "sensitivity": "confidential",
            "handling": (
                "Preserve immutable evidence through approved supersession/tombstone rules "
                "rather than generic update/delete."
            ),
        },
        "temporal_or_version_metadata": {
            "sensitivity": "internal",
            "handling": (
                "Use for lifecycle/reconciliation only; it inherits the source table "
                "retention policy."
            ),
        },
        "configuration_or_state_metadata": {
            "sensitivity": "internal_or_confidential",
            "handling": (
                "Treat configuration payloads as confidential until reviewed for embedded "
                "content or credentials."
            ),
        },
        "domain_attribute": {
            "sensitivity": "inherits_table_profile",
            "handling": (
                "Inherits the registered table profile; a more specific category may be "
                "selected through an explicit override."
            ),
        },
    }


def _table_profile(table_name: str, columns: Mapping[str, object]) -> str:
    normalized = table_name.lower()
    if any(
        token in normalized
        for token in (
            "token",
            "mfa",
            "secret",
            "security",
            "access_grant",
            "ethical_wall",
            "portal_magic",
            "identity_configuration",
        )
    ):
        return "security_identity_control"
    if any(
        token in normalized
        for token in (
            "billing",
            "payment",
            "invoice",
            "credit",
            "refund",
            "coupon",
            "pine_labs",
            "spend",
            "usage",
        )
    ):
        return "billing_provider_evidence"
    if (
        any(
            token in normalized
            for token in (
                "statute",
                "authority",
                "judge",
                "court",
                "forum",
                "legal_update_source",
            )
        )
        and "company_id" not in columns
    ):
        return "public_or_licensed_legal_reference"
    if any(
        token in normalized
        for token in (
            "attachment",
            "document",
            "communication",
            "notice",
            "matter",
            "contract",
            "draft",
            "recommendation",
            "ip_",
            "client",
            "provider_snapshot",
        )
    ):
        return "tenant_restricted_legal_content"
    if "company_id" in columns:
        return "tenant_operational_record"
    return "platform_operational_reference"


def _column_category(column_name: str) -> str:
    value = column_name.lower()
    if any(
        token in value
        for token in (
            "secret",
            "password",
            "token",
            "credential",
            "api_key",
            "private_key",
            "recovery_code",
        )
    ):
        return "security_secret_or_credential"
    if any(token in value for token in ("embedding", "vector", "chunk")):
        return "derived_search_or_embedding_data"
    if any(
        token in value
        for token in (
            "body",
            "content",
            "prompt",
            "response",
            "payload",
            "raw",
            "text",
            "html",
            "markdown",
            "transcript",
            "document",
            "file",
            "description",
            "narrative",
            "details",
        )
    ):
        return "privileged_or_raw_content"
    if any(
        token in value
        for token in ("email", "phone", "address", "name", "contact", "birth")
    ):
        return "personal_or_contact_data"
    if any(
        token in value
        for token in ("amount", "cost", "price", "fee", "payment", "currency", "tax")
    ):
        return "financial_or_payment_data"
    if any(
        token in value
        for token in ("provider", "external", "webhook", "source", "oauth")
    ):
        return "external_or_provider_identifier"
    if (
        any(
            token in value
            for token in (
                "company_id",
                "membership",
                "user_id",
                "client_id",
                "portal_user",
            )
        )
        or value == "id"
        or value.endswith("_id")
    ):
        return "tenant_or_access_identifier"
    if any(
        token in value
        for token in ("audit", "event", "lifecycle", "immutable", "hash", "checksum")
    ):
        return "lifecycle_or_audit_evidence"
    if (
        value.endswith("_at")
        or value.endswith("_on")
        or any(
            token in value
            for token in ("date", "version", "expires", "created", "updated")
        )
    ):
        return "temporal_or_version_metadata"
    if any(
        token in value
        for token in ("status", "state", "policy", "config", "setting", "mode", "type")
    ):
        return "configuration_or_state_metadata"
    return "domain_attribute"


def _non_sql_defaults() -> dict[str, object]:
    return {
        "legal_policy_basis": (
            "Pending named Records/Privacy/Legal/Security approval; this inventory is "
            "not an asserted legal retention basis or policy activation."
        ),
        "default_retention": (
            "No approved automated retention duration. Do not schedule deletion, expiry, "
            "provider deletion, or backup destruction from this registry."
        ),
        "tenant_configurable": False,
        "tenant_retention_bounds": (
            "No tenant override is available until an approved versioned policy defines "
            "per-tenant bounds and authority."
        ),
        "disposition": (
            "registry_fail_closed prevents a Definition-of-Ready pass for an unregistered "
            "class; it does not perform data I/O."
        ),
        "hold_behavior": (
            "A future approved hold must block conflicting disposition. This inventory "
            "does not activate or execute a hold."
        ),
        "region_subprocessor": (
            "Pending approved residency, international-transfer, and subprocessor policy; "
            "no guarantee is asserted."
        ),
        "owner": "Codex",
        "disposition_handler_id": DEFAULT_HANDLER_ID,
        "status": "inventory_registered_runtime_policy_unapproved",
    }


def _non_sql_data_classes() -> list[dict[str, object]]:
    defaults = _non_sql_defaults()
    return [
        {
            **defaults,
            "id": "document-object-prefix-and-version",
            "kind": "object_prefix_version",
            "purpose": (
                "Logical matter/contract attachment objects and any configured GCS object "
                "versions under the company-scoped storage-key namespace."
            ),
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Client and licensed-source bytes must not be exported, replicated, or "
                "deleted outside approved source/contract and legal-hold rules."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_storage.py",
                "apps/api/src/caseops_api/core/settings.py",
                "docs/GCP_DEPLOY.md",
            ],
        },
        {
            **defaults,
            "id": "document-materialization-cache",
            "kind": "cache",
            "purpose": (
                "Ephemeral local document materialization and process-local caches used by "
                "the API and document worker."
            ),
            "sensitivity": "confidential_or_privileged",
            "source_licence_limits": "Inherits source object and tenant access restrictions.",
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_storage.py",
                "infra/cloudrun/document-worker-job.yaml",
            ],
        },
        {
            **defaults,
            "id": "tenant-private-retrieval-candidate-cache",
            "kind": "cache",
            "purpose": (
                "Ephemeral process-local private-retrieval candidate identifiers. Keys are "
                "partitioned by tenant, membership, active index generation, access epoch, "
                "tombstone epoch, query hash, filters and locale; values contain identifiers "
                "only, and every hit is hydrated and reauthorized against current SQL state."
            ),
            "sensitivity": "confidential_access_identifiers",
            "source_licence_limits": (
                "Never cache source content, snippets, ranks, grants or authorization "
                "decisions; tenant invalidation and hydration reauthorization are mandatory."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/private_retrieval.py",
            ],
        },
        {
            **defaults,
            "id": "sql-relational-index-projections",
            "kind": "sql_index_projection",
            "purpose": (
                "All ORM and Alembic relational indexes derived from registered SQL table "
                "and column classes; index fingerprints are checked below."
            ),
            "sensitivity": "inherits_source_table_or_column",
            "source_licence_limits": "Inherits the registered source table and column limits.",
            "implementation_refs": [
                "apps/api/src/caseops_api/db/models.py",
                "apps/api/alembic/versions",
            ],
        },
        {
            **defaults,
            "id": "authority-document-pgvector-index",
            "kind": "search_vector_index",
            "purpose": "Derived vector search projection for authority-document chunks.",
            "sensitivity": "confidential_derived_data",
            "source_licence_limits": (
                "Inherits authority/source terms and must respect retrieval access."
            ),
            "implementation_refs": [
                "apps/api/alembic/versions/20260417_0003_authority_embeddings.py",
                "apps/api/src/caseops_api/services/authorities.py",
            ],
        },
        {
            **defaults,
            "id": "matter-attachment-pgvector-index",
            "kind": "search_vector_index",
            "purpose": "Derived vector search projection for Matter attachment chunks.",
            "sensitivity": "confidential_derived_data",
            "source_licence_limits": (
                "Inherits Matter/document access, privilege, and source limits."
            ),
            "implementation_refs": [
                "apps/api/alembic/versions/20260418_0004_matter_attachment_embeddings.py",
                "apps/api/src/caseops_api/services/document_processing.py",
            ],
        },
        {
            **defaults,
            "id": "database-queues-outbox-and-dead-letter",
            "kind": "queue_outbox_dead_letter",
            "purpose": (
                "Database-backed document, court, notification, mailbox, and domain-outbox "
                "queue/dead-letter records, including idempotency and consumer-effect state."
            ),
            "sensitivity": "confidential_operational_and_content_metadata",
            "source_licence_limits": "Inherits the source event/document/provider contract.",
            "implementation_refs": [
                "apps/api/src/caseops_api/services/document_jobs.py",
                "apps/api/src/caseops_api/services/domain_outbox.py",
                "apps/api/src/caseops_api/db/models.py",
            ],
        },
        {
            **defaults,
            "id": "application-logs-traces-and-metrics",
            "kind": "log_trace_metric",
            "purpose": (
                "Application logging, optional OpenTelemetry traces, and operational metrics "
                "that must minimize/redact content and identifiers."
            ),
            "sensitivity": "internal_with_confidential_identifiers",
            "source_licence_limits": (
                "Logs/traces/metrics may not become a content or secret export channel."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/core/observability.py",
                "apps/api/src/caseops_api/core/settings.py",
            ],
        },
        {
            **defaults,
            "id": "audit-export-artifacts",
            "kind": "export_artifact",
            "purpose": (
                "Existing audit-export job outputs and the reserved future tenant-data export "
                "artifact class. No tenant export dry-run or execute capability is claimed."
            ),
            "sensitivity": "confidential_or_privileged",
            "source_licence_limits": (
                "Exports must exclude secrets, cross-tenant/global data, internal cost/profit, "
                "and non-redistributable source payloads after approved policy review."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/audit_exports.py",
                "apps/api/src/caseops_api/db/models.py",
            ],
        },
        {
            **defaults,
            "id": "llm-and-embedding-provider-held-content",
            "kind": "provider_held_object",
            "purpose": (
                "Configured or optional LLM, embedding, and prompt-cache provider request/response "
                "content and derived vectors, including bounded authority-metadata extraction "
                "and its one-document provider canary."
            ),
            "sensitivity": "privileged_or_confidential",
            "source_licence_limits": (
                "Provider training, retention, residency, deletion, and permitted-use settings "
                "require approved provider and tenant policy before content transmission."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/llm.py",
                "apps/api/src/caseops_api/scripts/extract_authority_metadata.py",
                "apps/api/src/caseops_api/services/embeddings.py",
                "apps/api/src/caseops_api/core/settings.py",
            ],
        },
        {
            **defaults,
            "id": "connector-and-payment-provider-held-records",
            "kind": "provider_held_object",
            "purpose": (
                "External mailbox, calendar, Drive, court/source, and payment-provider objects "
                "referenced by connector or provider operations."
            ),
            "sensitivity": "confidential_provider_and_client_data",
            "source_licence_limits": (
                "Every provider/source contract, consent, permitted use, retention, and deletion "
                "capability must be approved before activation or data-operation execution."
            ),
            "implementation_refs": [
                "apps/api/src/caseops_api/services/integrations.py",
                "apps/api/src/caseops_api/services/case_tracking_providers.py",
                "apps/api/src/caseops_api/services/indian_kanoon.py",
                "apps/api/src/caseops_api/scripts/seed_indian_kanoon_costs.py",
                "apps/api/src/caseops_api/services/pine_labs.py",
                "scripts/deploy-prod.sh",
            ],
        },
        {
            **defaults,
            "id": "database-and-object-backups",
            "kind": "backup",
            "purpose": (
                "Production database backups/PITR and object-version recovery copies, including "
                "the required tombstone/hold reapplication before a restore serves traffic."
            ),
            "sensitivity": "inherits_all_protected_source_data",
            "source_licence_limits": (
                "Backup retention and restoration require approved SRE/security/records "
                "evidence."
            ),
            "implementation_refs": [
                "external:approved SRE backup/PITR/object-version evidence required before M2 exit",
                "docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md",
            ],
        },
    ]


def _skeleton() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "slice_id": "IPLF-028C",
        "status": MAP_STATUS,
        "policy_status": "pending_named_human_approval",
        "purpose": (
            "Versioned repository inventory for DATA-GOV-01 and DATA-GOV-03. It "
            "snapshots SQL tables/columns/indexes and known non-SQL classes so unregistered "
            "data-bearing changes fail Definition of Ready."
        ),
        "completion_boundary": (
            "This inventory does not claim approved retention bounds, legal-hold activation, "
            "tenant export, purge, offboarding, provider deletion, backup recovery/restore, "
            "residency, or data-governance/recovery milestone completion. The only current "
            "disposition behavior is fail-closed Definition-of-Ready validation."
        ),
        "requirement_refs": ["DATA-GOV-01", "DATA-GOV-03"],
        "disposition_handlers": [
            {
                "id": DEFAULT_HANDLER_ID,
                "status": "implemented_definition_of_ready_guard_no_data_operation",
                "implementation_ref": "scripts/ip_data_governance_map.py",
                "behavior": (
                    "Rejects an unregistered table, column, index snapshot, migration, or "
                    "declared provider/storage/telemetry boundary from passing CI. It performs "
                    "no retention, hold, export, purge, offboarding, restore, backup, or "
                    "provider I/O."
                ),
            }
        ],
        "policy_profiles": _policy_profiles(),
        "column_categories": _column_categories(),
        "table_policy_profile_overrides": {},
        "table_disposition_handler_overrides": {},
        "column_category_overrides": {},
        "table_purpose_overrides": {},
        "change_controls": {
            "migration_marker": MIGRATION_MARKER,
            "ci_validate_command": (
                "uv --directory apps/api run python "
                "../../scripts/ip_data_governance_map.py validate"
            ),
            "ci_change_gate_command": (
                "uv --directory apps/api run python "
                "../../scripts/ip_data_governance_map.py check-change --base origin/main"
            ),
            "rule": (
                "A changed Alembic migration or registered storage/provider/telemetry boundary "
                "must change this map and use the migration marker. A future runtime operation "
                "may replace the fail-closed handler only after the required machine policy, "
                "dry-run, and exact-release checks pass."
            ),
        },
        "non_sql_data_classes": _non_sql_data_classes(),
        "sql_tables": [],
        "schema_fingerprint": "",
        "index_inventory": {},
    }


def _generic_purpose(table_name: str) -> str:
    return (
        f"Repository SQL persistence class `{table_name}`; its exact column "
        "inventory is intentionally versioned below."
    )


def _table_rows(
    schema: Mapping[str, Mapping[str, Mapping[str, object]]],
    *,
    table_overrides: Mapping[str, object],
    disposition_overrides: Mapping[str, object],
    column_overrides: Mapping[str, object],
    purpose_overrides: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for table_name, columns in sorted(schema.items()):
        profile = str(
            table_overrides.get(table_name) or _table_profile(table_name, columns)
        )
        raw_column_overrides = column_overrides.get(table_name, {})
        overrides = (
            raw_column_overrides if isinstance(raw_column_overrides, Mapping) else {}
        )
        rendered_columns: dict[str, dict[str, object]] = {}
        for column_name, details in sorted(columns.items()):
            category = str(overrides.get(column_name) or _column_category(column_name))
            rendered_columns[column_name] = {
                "category_id": category,
                "sql_type": str(details["sql_type"]),
                "nullable": bool(details["nullable"]),
            }
        rows.append(
            {
                "id": table_name,
                "table_name": table_name,
                "purpose": str(
                    purpose_overrides.get(table_name) or _generic_purpose(table_name)
                ),
                "policy_profile_id": profile,
                "disposition_handler_id": str(
                    disposition_overrides.get(table_name) or DEFAULT_HANDLER_ID
                ),
                "columns": rendered_columns,
            }
        )
    return rows


def _schema_fingerprint_payload(
    schema: Mapping[str, Mapping[str, Mapping[str, object]]],
    orm_indexes: list[dict[str, object]],
    migration_indexes: list[str],
) -> dict[str, object]:
    return {
        "sql_schema": schema,
        "orm_indexes": orm_indexes,
        "migration_indexes": migration_indexes,
    }


def generate() -> dict[str, Any]:
    """Refresh only generated SQL inventory while preserving policy decisions.

    Reviewed table purposes are decisions too: they live in
    ``table_purpose_overrides`` and every other row gets the generated text.
    """

    data = copy.deepcopy(_load(MAP_PATH) if MAP_PATH.exists() else _skeleton())
    schema = current_sql_schema()
    orm_indexes = current_orm_indexes()
    migration_indexes = _migration_index_names()
    table_overrides = data.get("table_policy_profile_overrides", {})
    disposition_overrides = data.get("table_disposition_handler_overrides", {})
    column_overrides = data.get("column_category_overrides", {})
    purpose_overrides = data.get("table_purpose_overrides", {})
    if not isinstance(table_overrides, Mapping):
        raise ValueError("table_policy_profile_overrides must be an object")
    if not isinstance(column_overrides, Mapping):
        raise ValueError("column_category_overrides must be an object")
    if not isinstance(disposition_overrides, Mapping):
        raise ValueError("table_disposition_handler_overrides must be an object")
    if not isinstance(purpose_overrides, Mapping):
        raise ValueError("table_purpose_overrides must be an object")
    # Rows are generated output. A reviewed purpose written only into a row
    # would be replaced below, so refuse before rewriting anything.
    unrecorded = sorted(
        str(row.get("table_name"))
        for row in data.get("sql_tables", [])
        if isinstance(row, Mapping)
        and row.get("table_name") in schema
        and row.get("table_name") not in purpose_overrides
        and row.get("purpose") != _generic_purpose(str(row.get("table_name")))
    )
    if unrecorded:
        raise ValueError(
            "record reviewed table purposes in table_purpose_overrides before "
            f"regenerating sql_tables: {unrecorded}"
        )

    data["sql_tables"] = _table_rows(
        schema,
        table_overrides=table_overrides,
        disposition_overrides=disposition_overrides,
        column_overrides=column_overrides,
        purpose_overrides=purpose_overrides,
    )
    data["schema_fingerprint"] = _fingerprint(
        _schema_fingerprint_payload(schema, orm_indexes, migration_indexes)
    )
    data["index_inventory"] = {
        "orm_index_count": len(orm_indexes),
        "orm_index_fingerprint": _fingerprint(orm_indexes),
        "migration_index_count": len(migration_indexes),
        "migration_index_fingerprint": _fingerprint(migration_indexes),
        "interpretation": (
            "Relational indexes inherit registered source table/column treatment. The "
            "fingerprints deliberately force a reviewed map update for every index change; "
            "the named non-SQL classes separately identify pgvector projections."
        ),
    }
    _write(MAP_PATH, data)
    return data


def _required_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _relative(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _validate_ref(ref: object) -> bool:
    if not _required_string(ref):
        return False
    ref_text = str(ref)
    if ref_text.startswith("external:"):
        return True
    return (REPO_ROOT / ref_text).exists()


def validate(
    data: dict[str, Any] | None = None,
    *,
    sql_schema: dict[str, dict[str, dict[str, object]]] | None = None,
    orm_indexes: list[dict[str, object]] | None = None,
    migration_indexes: list[str] | None = None,
    check_generated_view: bool = True,
) -> list[str]:
    """Return all map integrity errors without mutating the registry."""

    errors: list[str] = []
    if data is None:
        if not MAP_PATH.exists():
            return [f"data-governance map is missing: {_relative(MAP_PATH)}"]
        data = _load(MAP_PATH)
    if data.get("schema_version") != 1:
        errors.append("data-governance map schema_version must be 1")
    if data.get("slice_id") != "IPLF-028C":
        errors.append("data-governance map must remain bounded to IPLF-028C")
    if data.get("status") != MAP_STATUS:
        errors.append(
            "data-governance map must preserve the policy-unapproved inventory status"
        )
    if data.get("policy_status") != "pending_named_human_approval":
        errors.append("data-governance map must preserve pending human policy approval")
    completion_boundary = str(data.get("completion_boundary", "")).lower()
    for term in ("does not claim", "export", "purge", "restore", "residency"):
        if term not in completion_boundary:
            errors.append(
                "data-governance map must state its explicit incomplete boundary"
            )
            break
    if data.get("requirement_refs") != ["DATA-GOV-01", "DATA-GOV-03"]:
        errors.append(
            "data-governance map must retain the DATA-GOV-01 and DATA-GOV-03 scope"
        )

    profiles = data.get("policy_profiles")
    if not isinstance(profiles, Mapping) or not profiles:
        errors.append("data-governance map must define policy_profiles")
        profiles = {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, Mapping):
            errors.append(f"policy-profile/{profile_id}: must be an object")
            continue
        missing = sorted(REQUIRED_POLICY_FIELDS - set(profile))
        if missing:
            errors.append(f"policy-profile/{profile_id}: missing fields {missing}")
        for field in REQUIRED_POLICY_FIELDS - {"tenant_configurable"}:
            if not _required_string(profile.get(field)):
                errors.append(f"policy-profile/{profile_id}: {field} must be explicit")
        if not isinstance(profile.get("tenant_configurable"), bool):
            errors.append(
                f"policy-profile/{profile_id}: tenant_configurable must be boolean"
            )

    categories = data.get("column_categories")
    if not isinstance(categories, Mapping) or not categories:
        errors.append("data-governance map must define column_categories")
        categories = {}
    for category_id, category in categories.items():
        if not isinstance(category, Mapping):
            errors.append(f"column-category/{category_id}: must be an object")
            continue
        for field in ("sensitivity", "handling"):
            if not _required_string(category.get(field)):
                errors.append(
                    f"column-category/{category_id}: {field} must be explicit"
                )

    handlers = data.get("disposition_handlers")
    if not isinstance(handlers, list):
        errors.append("data-governance map must define disposition_handlers")
        handlers = []
    handler_by_id = {
        str(row.get("id")): row for row in handlers if isinstance(row, Mapping)
    }
    handler = handler_by_id.get(DEFAULT_HANDLER_ID)
    if handler is None:
        errors.append("data-governance map must include registry_fail_closed handler")
    else:
        if (
            handler.get("status")
            != "implemented_definition_of_ready_guard_no_data_operation"
        ):
            errors.append(
                "registry_fail_closed handler must not overclaim runtime execution"
            )
        if handler.get("implementation_ref") != "scripts/ip_data_governance_map.py":
            errors.append("registry_fail_closed handler must reference this validator")
        if not _required_string(handler.get("behavior")):
            errors.append(
                "registry_fail_closed handler must describe fail-closed behavior"
            )

    controls = data.get("change_controls")
    if not isinstance(controls, Mapping):
        errors.append("data-governance map must define change_controls")
    elif controls.get("migration_marker") != MIGRATION_MARKER:
        errors.append("data-governance map must preserve the required migration marker")

    actual_schema = sql_schema if sql_schema is not None else current_sql_schema()
    actual_orm_indexes = (
        orm_indexes if orm_indexes is not None else current_orm_indexes()
    )
    actual_migration_indexes: list[str] | None = migration_indexes
    if actual_migration_indexes is None:
        try:
            actual_migration_indexes = _migration_index_names()
        except MigrationIndexInventoryError as exc:
            errors.append(str(exc))
    rows = data.get("sql_tables")
    if not isinstance(rows, list) or not rows:
        errors.append("data-governance map must enumerate every sql_tables row")
        rows = []
    row_by_name: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("sql-table entry must be an object")
            continue
        table_name = str(row.get("table_name", ""))
        if table_name in row_by_name:
            errors.append(f"duplicate sql-table entry: {table_name}")
        row_by_name[table_name] = row
    purpose_overrides = data.get("table_purpose_overrides", {})
    if not isinstance(purpose_overrides, Mapping):
        errors.append("table_purpose_overrides must be an object")
        purpose_overrides = {}
    actual_table_names = set(actual_schema)
    registered_table_names = set(row_by_name)
    if registered_table_names != actual_table_names:
        missing = sorted(actual_table_names - registered_table_names)
        extra = sorted(registered_table_names - actual_table_names)
        errors.append(
            "sql-table inventory must exactly match SQLAlchemy metadata "
            f"(missing={missing}, extra={extra})"
        )
    for table_name, expected_columns in sorted(actual_schema.items()):
        row = row_by_name.get(table_name)
        if row is None:
            continue
        if row.get("id") != table_name:
            errors.append(f"sql-table/{table_name}: id must equal table_name")
        if not _required_string(row.get("purpose")):
            errors.append(f"sql-table/{table_name}: purpose must be explicit")
        elif row.get("purpose") != (
            purpose_overrides.get(table_name) or _generic_purpose(table_name)
        ):
            errors.append(
                f"sql-table/{table_name}: purpose must equal its table_purpose_overrides "
                "entry or the generated text; record a reviewed purpose as an override"
            )
        profile_id = str(row.get("policy_profile_id", ""))
        if profile_id not in profiles:
            errors.append(
                f"sql-table/{table_name}: unknown policy_profile_id {profile_id!r}"
            )
        if row.get("disposition_handler_id") not in handler_by_id:
            errors.append(f"sql-table/{table_name}: unknown disposition handler")
        columns = row.get("columns")
        if not isinstance(columns, Mapping):
            errors.append(f"sql-table/{table_name}: columns must be an object")
            continue
        if set(columns) != set(expected_columns):
            missing = sorted(set(expected_columns) - set(columns))
            extra = sorted(set(columns) - set(expected_columns))
            errors.append(
                f"sql-table/{table_name}: columns must exactly match metadata "
                f"(missing={missing}, extra={extra})"
            )
        for column_name, expected in expected_columns.items():
            column = columns.get(column_name)
            if not isinstance(column, Mapping):
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: missing mapping"
                )
                continue
            category_id = str(column.get("category_id", ""))
            if category_id not in categories:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: unknown category {category_id!r}"
                )
            if column.get("sql_type") != expected["sql_type"]:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: sql_type drift "
                    "requires map update"
                )
            if column.get("nullable") != expected["nullable"]:
                errors.append(
                    f"sql-table/{table_name}/column/{column_name}: nullability drift "
                    "requires map update"
                )

    table_overrides = data.get("table_policy_profile_overrides", {})
    if not isinstance(table_overrides, Mapping):
        errors.append("table_policy_profile_overrides must be an object")
    else:
        for table_name, profile_id in table_overrides.items():
            if table_name not in actual_schema:
                errors.append(
                    f"table profile override references unknown table {table_name}"
                )
            if profile_id not in profiles:
                errors.append(
                    f"table profile override uses unknown profile {profile_id!r}"
                )
    disposition_overrides = data.get("table_disposition_handler_overrides", {})
    if not isinstance(disposition_overrides, Mapping):
        errors.append("table_disposition_handler_overrides must be an object")
    else:
        for table_name, handler_id in disposition_overrides.items():
            if table_name not in actual_schema:
                errors.append(
                    f"table disposition override references unknown table {table_name}"
                )
            if handler_id not in handler_by_id:
                errors.append(
                    f"table disposition override uses unknown handler {handler_id!r}"
                )
    for table_name, purpose in purpose_overrides.items():
        if table_name not in actual_schema:
            errors.append(f"table purpose override references unknown table {table_name}")
        if not _required_string(purpose):
            errors.append(f"table purpose override for {table_name} must be explicit")
        elif purpose == _generic_purpose(str(table_name)):
            errors.append(
                f"table purpose override for {table_name} repeats the generated text"
            )
    column_overrides = data.get("column_category_overrides", {})
    if not isinstance(column_overrides, Mapping):
        errors.append("column_category_overrides must be an object")
    else:
        for table_name, overrides in column_overrides.items():
            if table_name not in actual_schema:
                errors.append(
                    f"column category override references unknown table {table_name}"
                )
                continue
            if not isinstance(overrides, Mapping):
                errors.append(
                    f"column category override for {table_name} must be an object"
                )
                continue
            for column_name, category_id in overrides.items():
                if column_name not in actual_schema[table_name]:
                    errors.append(
                        "column category override references unknown column "
                        f"{table_name}.{column_name}"
                    )
                if category_id not in categories:
                    errors.append(
                        f"column category override uses unknown category {category_id!r}"
                    )

    expected_schema_fingerprint = (
        None
        if actual_migration_indexes is None
        else _fingerprint(
            _schema_fingerprint_payload(
                actual_schema, actual_orm_indexes, actual_migration_indexes
            )
        )
    )
    if (
        expected_schema_fingerprint is not None
        and data.get("schema_fingerprint") != expected_schema_fingerprint
    ):
        errors.append(
            "SQL schema/index fingerprint drift requires `generate` and review"
        )
    index_inventory = data.get("index_inventory")
    if not isinstance(index_inventory, Mapping):
        errors.append("data-governance map must define index_inventory")
    else:
        expected_index_values: dict[str, object] = {
            "orm_index_count": len(actual_orm_indexes),
            "orm_index_fingerprint": _fingerprint(actual_orm_indexes),
        }
        if actual_migration_indexes is not None:
            expected_index_values["migration_index_count"] = len(actual_migration_indexes)
            expected_index_values["migration_index_fingerprint"] = _fingerprint(
                actual_migration_indexes
            )
        for key, expected in expected_index_values.items():
            if index_inventory.get(key) != expected:
                errors.append(f"index_inventory/{key}: drift requires map update")
        if not _required_string(index_inventory.get("interpretation")):
            errors.append("index_inventory must state the inherited-index treatment")

    non_sql = data.get("non_sql_data_classes")
    if not isinstance(non_sql, list) or not non_sql:
        errors.append("data-governance map must define non_sql_data_classes")
        non_sql = []
    seen_non_sql: set[str] = set()
    kinds: set[str] = set()
    for row in non_sql:
        if not isinstance(row, Mapping):
            errors.append("non-SQL data class must be an object")
            continue
        class_id = str(row.get("id", ""))
        if class_id in seen_non_sql:
            errors.append(f"duplicate non-SQL data class: {class_id}")
        seen_non_sql.add(class_id)
        kinds.add(str(row.get("kind", "")))
        missing = sorted(REQUIRED_NON_SQL_FIELDS - set(row))
        if missing:
            errors.append(f"non-SQL/{class_id}: missing fields {missing}")
        for field in REQUIRED_NON_SQL_FIELDS - {
            "tenant_configurable",
            "implementation_refs",
        }:
            if field in {"id", "kind", "disposition_handler_id", "status"}:
                continue
            if not _required_string(row.get(field)):
                errors.append(f"non-SQL/{class_id}: {field} must be explicit")
        if not _required_string(class_id) or not _required_string(row.get("kind")):
            errors.append("non-SQL data class id and kind must be explicit")
        if not isinstance(row.get("tenant_configurable"), bool):
            errors.append(f"non-SQL/{class_id}: tenant_configurable must be boolean")
        if row.get("disposition_handler_id") not in handler_by_id:
            errors.append(f"non-SQL/{class_id}: unknown disposition handler")
        if row.get("status") != "inventory_registered_runtime_policy_unapproved":
            errors.append(
                f"non-SQL/{class_id}: must not overclaim runtime policy approval"
            )
        refs = row.get("implementation_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"non-SQL/{class_id}: implementation_refs must be non-empty")
        elif any(not _validate_ref(ref) for ref in refs):
            errors.append(f"non-SQL/{class_id}: implementation ref does not exist")
    missing_kinds = sorted(REQUIRED_NON_SQL_KINDS - kinds)
    if missing_kinds:
        errors.append(f"non-SQL data classes missing required kinds: {missing_kinds}")
    if check_generated_view and not errors:
        expected = _render_markdown(data).encode("utf-8")
        if not GENERATED_VIEW_PATH.is_file():
            errors.append(
                "missing generated data-governance map "
                f"{_relative(GENERATED_VIEW_PATH)}"
            )
        elif GENERATED_VIEW_PATH.read_bytes() != expected:
            errors.append(
                "stale or independently edited generated data-governance map "
                f"{_relative(GENERATED_VIEW_PATH)}; run `render`"
            )
    return errors


def _render_markdown(data: Mapping[str, Any]) -> str:
    """Build the checked-in human projection without mutating the repository."""

    rows = data["sql_tables"]
    non_sql = data["non_sql_data_classes"]
    index_inventory = data["index_inventory"]
    lines = [
        "# Repository Data-Governance Map",
        "",
        "Generated from `DATA_GOVERNANCE_MAP.yaml`; do not edit this view directly.",
        "",
        "## Status",
        "",
        f"- Status: `{data['status']}`",
        f"- Policy approval: `{data['policy_status']}`",
        f"- Canonical map SHA-256: `{_fingerprint(data)}`",
        f"- SQL tables: `{len(rows)}`",
        f"- SQL columns: `{sum(len(row['columns']) for row in rows)}`",
        f"- ORM indexes: `{index_inventory['orm_index_count']}`",
        f"- Alembic/raw index declarations: `{index_inventory['migration_index_count']}`",
        f"- Non-SQL data classes: `{len(non_sql)}`",
        "",
        "## Boundary",
        "",
        data["completion_boundary"],
        "",
        "## SQL table inventory",
        "",
        "| Table | Policy profile | Columns | Disposition handler |",
        "| --- | --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['table_name']}` | `{row['policy_profile_id']}` | "
            f"{len(row['columns'])} | `{row['disposition_handler_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Known non-SQL data classes",
            "",
            "| ID | Kind | Disposition handler |",
            "| --- | --- | --- |",
        ]
    )
    for row in non_sql:
        lines.append(
            f"| `{row['id']}` | `{row['kind']}` | `{row['disposition_handler_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Change control",
            "",
            "Any changed Alembic migration or registered storage/provider/telemetry "
            "boundary must update the machine-readable map. New migrations also require "
            f"the marker `{MIGRATION_MARKER}`. The current handler is intentionally "
            "fail-closed and performs no data operation.",
            "",
        ]
    )
    return "\n".join(lines)


def render(data: dict[str, Any] | None = None) -> Path:
    """Render a compact human view; the machine-readable map remains canonical."""

    if data is None:
        data = _load(MAP_PATH)
    errors = validate(data, check_generated_view=False)
    if errors:
        raise ValueError(
            "cannot render invalid data-governance map: " + "; ".join(errors)
        )
    GENERATED_VIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_VIEW_PATH.write_bytes(_render_markdown(data).encode("utf-8"))
    return GENERATED_VIEW_PATH


def _normalise_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def change_gate_errors(
    changed_paths: list[str], *, source_by_path: Mapping[str, str]
) -> list[str]:
    """Validate a supplied diff; exposed for deterministic unit tests."""

    normalized_paths = {_normalise_path(path) for path in changed_paths}
    map_changed = _relative(MAP_PATH) in normalized_paths
    risky_paths: list[str] = []
    migration_paths: list[str] = []
    for path in sorted(normalized_paths):
        if path.startswith("apps/api/alembic/versions/") and path.endswith(".py"):
            migration_paths.append(path)
            risky_paths.append(path)
            continue
        source = source_by_path.get(path, "")
        if path in RISKY_PATHS or (
            path.startswith(RISKY_SOURCE_ROOTS) and risky_source_match(path, source)
        ):
            risky_paths.append(path)
    errors: list[str] = []
    if risky_paths and not map_changed:
        errors.append(
            "data-bearing changes require DATA_GOVERNANCE_MAP.yaml update: "
            + ", ".join(risky_paths)
        )
    for path in migration_paths:
        source = source_by_path.get(path, "")
        if MIGRATION_MARKER not in source:
            errors.append(
                f"migration {path} is missing required marker: {MIGRATION_MARKER}"
            )
    return errors


def _git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _default_base() -> str:
    github_base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base:
        candidate = f"origin/{github_base}"
        try:
            _git_output("rev-parse", "--verify", candidate)
            return candidate
        except subprocess.CalledProcessError:
            pass
    for candidate in ("origin/main", "HEAD^"):
        try:
            _git_output("rev-parse", "--verify", candidate)
            return candidate
        except subprocess.CalledProcessError:
            continue
    return "HEAD"


def check_change(base: str | None = None) -> list[str]:
    """Run the Definition-of-Ready diff gate against a Git base revision."""

    selected_base = base or _default_base()
    try:
        diff = _git_output("diff", "--name-only", f"{selected_base}...HEAD")
    except subprocess.CalledProcessError as exc:
        return [
            f"cannot determine change set from {selected_base}: {exc.output.strip()}"
        ]
    changed_paths = [line for line in diff.splitlines() if line.strip()]
    source_by_path: dict[str, str] = {}
    read_errors: list[str] = []
    for path in changed_paths:
        normalized = _normalise_path(path)
        # Only these boundaries consume source text. Evidence PDFs and other
        # unrelated assets still belong to the diff, but are not UTF-8 source.
        if not (
            normalized in RISKY_PATHS
            or normalized.startswith(RISKY_SOURCE_ROOTS)
            or (
                normalized.startswith("apps/api/alembic/versions/")
                and normalized.endswith(".py")
            )
        ):
            continue
        candidate = REPO_ROOT / normalized
        if candidate.is_file():
            try:
                source_by_path[normalized] = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                read_errors.append(
                    f"cannot read governed source {normalized}: {type(exc).__name__}"
                )
    return read_errors + change_gate_errors(changed_paths, source_by_path=source_by_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("generate", "validate", "render", "check-change"),
        nargs="?",
        default="validate",
    )
    parser.add_argument("--base", help="Git revision used by check-change")
    args = parser.parse_args(argv)
    if args.command == "generate":
        data = generate()
        print(
            "generated data-governance map: "
            f"{len(data['sql_tables'])} SQL tables and "
            f"{sum(len(row['columns']) for row in data['sql_tables'])} columns"
        )
        return 0
    if args.command == "render":
        print(f"rendered {render()}")
        return 0
    errors = check_change(args.base) if args.command == "check-change" else validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.command == "check-change":
        print("data-governance change gate valid")
    else:
        print("data-governance map valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
