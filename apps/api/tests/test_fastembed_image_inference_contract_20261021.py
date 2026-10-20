"""The standard image build must execute real reranking, not only download weights."""

from __future__ import annotations

import ast
import shlex
from pathlib import Path


def _prewarm():
    source = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    commands = [shlex.split(line)[3] for line in source.splitlines()
                if line.startswith("RUN python -c ") and "TextCrossEncoder" in line]
    assert len(commands) == 1
    return ast.parse(commands[0])


def test_standard_image_build_executes_real_cached_cross_encoder_inference():
    tree = _prewarm()
    constructors = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "TextCrossEncoder"]
    assert len(constructors) == 1
    assert any(keyword.arg == "model_name" and ast.literal_eval(keyword.value) == (
        "jinaai/jina-reranker-v1-tiny-en"
    ) for keyword in constructors[0].keywords)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "rerank"]
    assert len(calls) == 1, "Prewarming without real inference does not enforce SDK compatibility"
    assert ast.literal_eval(calls[0].args[0]) == "regular bail triple test"
    assert ast.literal_eval(calls[0].args[1]) == [
        "A tax assessment determines taxable income.",
        "The court grants regular bail after applying the triple test.",
    ]


def test_standard_image_build_requires_two_finite_correctly_ordered_scores():
    tree = _prewarm()
    assertions = [node.test for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    conjuncts = [child for node in assertions for child in (
        node.values if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And) else [node]
    )]
    expressions = {ast.dump(node) for node in conjuncts}
    for required in (
        "len(scores) == 2",
        "all(math.isfinite(float(score)) for score in scores)",
        "scores[1] > scores[0]",
    ):
        assert ast.dump(ast.parse(required, mode="eval").body) in expressions
