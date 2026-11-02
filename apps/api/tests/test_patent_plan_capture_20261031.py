"""Offline execution-capture regressions; no application imports or database."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import pytest
from sqlalchemy import Integer, String, TupleType, bindparam, column, select, table, tuple_
from sqlalchemy.dialects.postgresql.psycopg import dialect
from sqlalchemy.types import TypeDecorator


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _processed_expansion(compiled, expanded):
    processors = dict(expanded.processors)
    for bind, name in compiled.bind_names.items():
        if name in expanded.parameters:
            processor = bind.type.dialect_impl(compiled.dialect).bind_processor(compiled.dialect)
            if processor is not None:
                processors[name] = processor
    values = {
        name: processors[name](value) if name in processors else value
        for name, value in expanded.parameters.items()
    }
    if expanded.positiontup is not None:
        return tuple(values[name] for name in expanded.positiontup)
    return {compiled.escaped_bind_names.get(name, name): value for name, value in values.items()}


@dataclass(frozen=True)
class _PatentExecution:
    compiled: Any
    statement: Any
    raw_sql: str
    driver_parameters: Any
    compiled_parameters: tuple
    parameter_expansion: Any
    executemany: bool


def _freeze_patent_execution(
    compiled, raw_sql, driver_parameters, compiled_parameters, many=False,
    *, parameter_expansion=None,
):
    return _PatentExecution(
        compiled=compiled,
        statement=compiled.statement,
        raw_sql=raw_sql,
        driver_parameters=_freeze(driver_parameters),
        compiled_parameters=_freeze(compiled_parameters),
        parameter_expansion=_freeze(parameter_expansion),
        executemany=many,
    )


def _unexpanded_patent_parameters(captured):
    assert not captured.executemany
    assert len(captured.compiled_parameters) == 1
    compiled = captured.compiled
    assert not compiled.literal_execute_params, "literal_execute parameters are unsupported"
    assert isinstance(captured.compiled_parameters[0], Mapping)
    parameters = dict(captured.compiled_parameters[0])
    expanding = {
        compiled.bind_names[bind]: bind for bind in compiled.post_compile_params
    }
    assert all(bind.expanding for bind in expanding.values()), "unsupported postcompile bind"
    expansion = captured.parameter_expansion
    if expansion is None:
        assert not expanding, "missing parameter expansion map"
        expansion = {}
    assert isinstance(expansion, Mapping), "invalid parameter expansion map"
    assert set(expansion) == set(expanding), "parameter expansion roots do not match"
    consumed = set()
    for name, bind in expanding.items():
        children = expansion[name]
        assert isinstance(children, (list, tuple)), "invalid expansion child sequence"
        assert all(isinstance(child, str) for child in children), "invalid expansion child name"
        assert name not in parameters, "execution parameters were not expanded"
        assert len(children) == len(set(children)), "duplicate expansion child"
        assert not consumed.intersection(children), "expansion children overlap"
        consumed.update(children)
        assert all(child in parameters for child in children), "missing expanded parameter"
        values = [parameters.pop(child) for child in children]
        if isinstance(bind.type, TupleType):
            width = len(bind.type.types)
            assert width > 0 and len(values) % width == 0, "invalid tuple expansion width"
            parameters[name] = tuple(
                tuple(values[offset:offset + width]) for offset in range(0, len(values), width)
            )
        else:
            parameters[name] = tuple(values)
    assert set(parameters) == set(compiled.bind_names.values()), "execution bind coverage mismatch"
    return parameters


def _validate_patent_execution(captured):
    parameters = _unexpanded_patent_parameters(captured)
    # Public API takes `params` in the pinned SQLAlchemy, so use its positional form.
    expanded = captured.compiled.construct_expanded_state(parameters, escape_names=False)
    expansion = {} if captured.parameter_expansion is None else captured.parameter_expansion
    assert _freeze(expanded.parameter_expansion) == expansion
    assert _freeze(expanded.parameters) == captured.compiled_parameters[0]
    processed = _processed_expansion(captured.compiled, expanded)
    assert expanded.statement == captured.raw_sql
    assert _freeze(processed) == captured.driver_parameters
    return expanded


def _numeric_patent_execution(captured, *, limit=None):
    _validate_patent_execution(captured)
    compiled = captured.statement.compile(dialect=dialect(paramstyle="numeric_dollar"))
    parameters = _unexpanded_patent_parameters(captured)
    assert set(compiled.bind_names.values()) == set(parameters)
    if limit is not None:
        # Keep the original AST and all execution values; change only this probe's limit.
        limit_name = compiled.bind_names[captured.statement._limit_clause]
        parameters[limit_name] = limit
    expanded = compiled.construct_expanded_state(parameters, escape_names=False)
    return expanded.statement, _processed_expansion(compiled, expanded)


def _offline_capture(compiled, parameters):
    assert set(parameters) == set(compiled.bind_names.values())
    expanded = compiled.construct_expanded_state(parameters, escape_names=False)
    return _freeze_patent_execution(
        compiled,
        expanded.statement,
        _processed_expansion(compiled, expanded),
        [expanded.parameters],
        parameter_expansion=expanded.parameter_expansion,
    )


def test_patent_capture_expanding_in_uses_execution_not_cached_first_page():
    family = table("family", column("id", Integer))
    statement = select(family).where(family.c.id.in_(bindparam("ids", [1, 2], expanding=True)))
    compiled = statement.compile(dialect=dialect())
    captured = _offline_capture(compiled, {"ids": [101, 102, 103]})
    sql_text, parameters = _numeric_patent_execution(captured)
    assert parameters == (101, 102, 103)
    assert "$3" in sql_text
    assert compiled.params == {"ids": [1, 2]}


def test_patent_capture_tuple_in_expands_current_pairs():
    version = table("version", column("family_id", Integer), column("version", Integer))
    statement = select(version).where(
        tuple_(version.c.family_id, version.c.version).in_(
            bindparam("pairs", [(1, 1)], expanding=True)
        )
    )
    compiled = statement.compile(dialect=dialect())
    captured = _offline_capture(compiled, {"pairs": [(101, 2), (102, 3)]})
    sql_text, parameters = _numeric_patent_execution(captured)
    assert parameters == (101, 2, 102, 3)
    assert "(($1, $2), ($3, $4))" in sql_text


def test_patent_capture_preserves_current_cursor_and_overrides_only_probe_limit():
    family = table("family", column("id", Integer))
    statement = (
        select(family)
        .where(family.c.id > bindparam("cursor", 1))
        .order_by(family.c.id)
        .limit(bindparam("take", 2))
    )
    compiled = statement.compile(dialect=dialect())
    captured = _offline_capture(compiled, {"cursor": 900, "take": 101})
    _, actual = _numeric_patent_execution(captured)
    _, small = _numeric_patent_execution(captured, limit=1)
    assert actual == (900, 101)
    assert small == (900, 1)
    assert captured.compiled_parameters[0]["take"] == 101


def test_patent_capture_continuations_are_immutable_per_execution():
    family = table("family", column("id", Integer))
    compiled = (
        select(family)
        .where(family.c.id.in_(bindparam("ids", [1], expanding=True)))
        .compile(dialect=dialect())
    )
    parameters = {"ids": [101, 102]}
    expanded = compiled.construct_expanded_state(parameters, escape_names=False)
    driver = _processed_expansion(compiled, expanded)
    first = _freeze_patent_execution(
        compiled, expanded.statement, driver, [expanded.parameters],
        parameter_expansion=expanded.parameter_expansion,
    )
    expanded.parameters["ids_1"] = 999
    expanded.parameter_expansion["ids"].reverse()
    driver["ids_1"] = 999
    parameters["ids"][:] = [201, 202, 203]
    second = _offline_capture(compiled, parameters)
    parameters["ids"].clear()
    first_sql, first_values = _numeric_patent_execution(first)
    second_sql, second_values = _numeric_patent_execution(second)
    assert first_values == (101, 102)
    assert second_values == (201, 202, 203)
    assert first_sql != second_sql
    assert first.parameter_expansion["ids"] == ("ids_1", "ids_2")
    with pytest.raises(TypeError):
        first.compiled_parameters[0]["ids_1"] = 999
    with pytest.raises(TypeError):
        first.driver_parameters["ids_1"] = 999
    with pytest.raises(TypeError):
        first.parameter_expansion["ids"] = ()


@pytest.mark.parametrize("mismatch", ["sql", "binds"])
def test_patent_capture_rejects_mismatched_driver_execution(mismatch):
    family = table("family", column("id", Integer))
    compiled = (
        select(family)
        .where(family.c.id.in_(bindparam("ids", [1], expanding=True)))
        .compile(dialect=dialect())
    )
    expanded = compiled.construct_expanded_state({"ids": [101, 102]})
    raw_sql = expanded.statement + (" /* mismatch */" if mismatch == "sql" else "")
    driver = dict(expanded.parameters)
    if mismatch == "binds":
        driver["ids_2"] = 999
    captured = _freeze_patent_execution(
        compiled, raw_sql, driver, [expanded.parameters],
        parameter_expansion=expanded.parameter_expansion,
    )
    with pytest.raises(AssertionError):
        _numeric_patent_execution(captured)


def test_patent_capture_applies_public_scalar_and_expanding_bind_processors():
    class Upper(TypeDecorator):
        impl = String
        cache_ok = True

        def process_bind_param(self, value, _dialect):
            return value.upper()

    family = table("family", column("id", Upper()))
    compiled = (
        select(family)
        .where(
            family.c.id.in_(
                bindparam("ids", ["old"], expanding=True, type_=family.c.id.type)
            ),
            family.c.id != bindparam("excluded", "old", type_=family.c.id.type),
        )
        .compile(dialect=dialect())
    )
    captured = _offline_capture(compiled, {"ids": ["a", "b"], "excluded": "c"})
    _, parameters = _numeric_patent_execution(captured)
    assert parameters == ("C", "A", "B")
    assert captured.driver_parameters == {"excluded": "C", "ids_1": "A", "ids_2": "B"}


def test_patent_capture_rejects_reordered_positional_driver_parameters():
    family = table("family", column("id", Integer))
    compiled = (
        select(family)
        .where(family.c.id.in_(bindparam("ids", [1], expanding=True)))
        .compile(dialect=dialect(paramstyle="numeric_dollar"))
    )
    expanded = compiled.construct_expanded_state({"ids": [101, 102]})
    captured = _freeze_patent_execution(
        compiled, expanded.statement, (102, 101), [expanded.parameters],
        parameter_expansion=expanded.parameter_expansion,
    )
    with pytest.raises(AssertionError):
        _validate_patent_execution(captured)


@pytest.mark.parametrize(
    "shape,current",
    [
        pytest.param("scalar", [101, 102, 103], id="scalar-long"),
        pytest.param("scalar", [201], id="scalar-short"),
        pytest.param("scalar", [], id="scalar-empty"),
        pytest.param("tuple", [(101, 7), (102, 8), (103, 9)], id="tuple-long"),
        pytest.param("tuple", [(201, 10)], id="tuple-short"),
        pytest.param("tuple", [], id="tuple-empty"),
    ],
)
def test_patent_capture_actual_expansion_overrides_cached_lengths(shape, current):
    family = table("family", column("id", Integer), column("version", Integer))
    if shape == "tuple":
        predicate = tuple_(family.c.id, family.c.version).in_(
            bindparam("ids", [(1, 1), (2, 1)], expanding=True)
        )
    else:
        predicate = family.c.id.in_(bindparam("ids", [1, 2], expanding=True))
    statement = (
        select(family)
        .where(family.c.id > bindparam("cursor", 1), predicate)
        .limit(bindparam("take", 2))
    )
    compiled = statement.compile(dialect=dialect())
    parameters = {"ids": current, "cursor": 900, "take": 101}
    captured = _offline_capture(compiled, parameters)
    recovered = _unexpanded_patent_parameters(captured)
    numeric_sql, numeric_parameters = _numeric_patent_execution(captured)
    expected_compiled = statement.compile(dialect=dialect(paramstyle="numeric_dollar"))
    expected = expected_compiled.construct_expanded_state(parameters, escape_names=False)
    assert _freeze(recovered) == _freeze(parameters)
    assert "ids" not in captured.compiled_parameters[0]
    assert numeric_sql == expected.statement
    assert numeric_parameters == expected.positional_parameters
    assert recovered["cursor"] == 900
    assert recovered["take"] == 101
    if not current:
        assert captured.parameter_expansion["ids"] == ()


@pytest.mark.parametrize(
    "damage", ["missing_map", "missing_child", "duplicate_child", "unknown_root", "tuple_width"]
)
def test_patent_capture_rejects_invalid_execution_expansion_map(damage):
    version = table("version", column("family_id", Integer), column("version", Integer))
    compiled = (
        select(version)
        .where(tuple_(version.c.family_id, version.c.version).in_(
            bindparam("pairs", [(1, 1)], expanding=True)
        ))
        .compile(dialect=dialect())
    )
    expanded = compiled.construct_expanded_state(
        {"pairs": [(101, 7), (102, 9)]}, escape_names=False
    )
    parameters = dict(expanded.parameters)
    expansion = {name: list(children) for name, children in expanded.parameter_expansion.items()}
    if damage == "missing_map":
        expansion = None
    elif damage == "missing_child":
        parameters.pop(expansion["pairs"][-1])
    elif damage == "duplicate_child":
        expansion["pairs"][1] = expansion["pairs"][0]
    elif damage == "unknown_root":
        expansion["unknown"] = expansion.pop("pairs")
    else:
        parameters.pop(expansion["pairs"].pop())
    captured = _freeze_patent_execution(
        compiled, expanded.statement, _processed_expansion(compiled, expanded), [parameters],
        parameter_expansion=expansion,
    )
    with pytest.raises(AssertionError):
        _numeric_patent_execution(captured)


def test_patent_capture_rejects_unrecoverable_literal_execute_parameters():
    family = table("family", column("id", Integer))
    compiled = (
        select(family)
        .where(family.c.id > bindparam("floor", 1, literal_execute=True))
        .compile(dialect=dialect())
    )
    captured = _offline_capture(compiled, {"floor": 900})
    with pytest.raises(AssertionError, match="literal_execute parameters are unsupported"):
        _numeric_patent_execution(captured)
