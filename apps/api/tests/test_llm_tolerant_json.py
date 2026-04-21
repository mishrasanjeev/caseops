"""BUG-005 — regression tests for the LLM JSON extractor.

Both Sonnet and Haiku were prod-502-ing the recommendations endpoint
because they wrapped the structured payload in preamble / postamble
narration. The ``_tolerant_json_loads`` helper now walks through
three progressively-more-lenient parse attempts and only raises the
original error when none succeed.
"""
from __future__ import annotations

import json

import pytest

from caseops_api.services.llm import (
    _extract_first_json_block,
    _tolerant_json_loads,
)


def test_clean_json_round_trips() -> None:
    raw = '{"a": 1, "b": [1, 2, 3]}'
    assert _tolerant_json_loads(raw) == {"a": 1, "b": [1, 2, 3]}


def test_trailing_comma_tolerated() -> None:
    raw = '{"a": 1, "b": [1, 2, 3,],}'
    assert _tolerant_json_loads(raw) == {"a": 1, "b": [1, 2, 3]}


def test_preamble_narration_stripped() -> None:
    """The exact failure mode BUG-005 hit: model prepends a sentence."""
    raw = (
        "Here is the JSON you asked for:\n\n"
        '{"options": [{"title": "A"}, {"title": "B"}]}'
    )
    result = _tolerant_json_loads(raw)
    assert result == {"options": [{"title": "A"}, {"title": "B"}]}


def test_postamble_commentary_stripped() -> None:
    """Model appends 'Note: I chose X because…' after the JSON."""
    raw = (
        '{"options": [{"title": "A"}]}\n\n'
        "Note: I've recommended the Delhi HC forum because the "
        "client's principal office is in NCR."
    )
    assert _tolerant_json_loads(raw) == {"options": [{"title": "A"}]}


def test_preamble_plus_trailing_comma_both_tolerated() -> None:
    raw = (
        "Sure, here's the JSON:\n"
        '{"options": [{"title": "A",}, {"title": "B",},],}'
    )
    assert _tolerant_json_loads(raw) == {"options": [{"title": "A"}, {"title": "B"}]}


def test_braces_inside_strings_do_not_break_extractor() -> None:
    raw = 'preamble\n{"a": "text with } brace", "b": 1}\npostamble'
    assert _tolerant_json_loads(raw) == {"a": "text with } brace", "b": 1}


def test_escaped_quotes_in_strings() -> None:
    raw = '{"a": "he said \\"hi\\"", "b": 2}'
    assert _tolerant_json_loads(raw) == {"a": 'he said "hi"', "b": 2}


def test_genuine_malformation_still_raises_original_error() -> None:
    raw = "{definitely not json at all"
    with pytest.raises(json.JSONDecodeError):
        _tolerant_json_loads(raw)


def test_array_at_top_level_also_extracted() -> None:
    raw = 'Here are the items: [1, 2, 3] done.'
    assert _tolerant_json_loads(raw) == [1, 2, 3]


def test_extract_first_block_helper_is_balanced() -> None:
    """Nested braces must close the outer brace correctly."""
    raw = 'xxx {"outer": {"inner": {"deep": 1}}} yyy'
    assert _extract_first_json_block(raw) == '{"outer": {"inner": {"deep": 1}}}'


def test_extract_first_block_returns_none_when_no_structure() -> None:
    assert _extract_first_json_block("just a plain string") is None
    assert _extract_first_json_block("") is None
