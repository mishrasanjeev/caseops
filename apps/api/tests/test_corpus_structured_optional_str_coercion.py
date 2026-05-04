"""Coverage for the ``_coerce_to_optional_str`` helper that gates
case_title / case_number / outcome on ``_ExtractionPayload``.

Anchor: 2026-05-04 prod log on the ingest VM showed gpt-5-mini
emitting ``case_number`` as a list of strings on consolidated SC
appeals (e.g. ``2014_10_458_478_GAR.pdf`` returned four appeal
numbers in an array). The original schema declared
``case_number: str | None`` and pydantic rejected the payload with
``Input should be a valid string``, marking the entire doc as
``format_error`` in ``model_runs`` and skipping the structured
write. ~10-15 % of SC corpus shows the same pattern.

This test file pins the coercion behaviour so the validator can't
silently regress and re-resurrect the same failure mode.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from caseops_api.services.corpus_structured import (
    _coerce_to_optional_str,
    _ExtractionPayload,
)

# ---------- pure-helper tests on _coerce_to_optional_str ----------


def test_none_input_returns_none() -> None:
    assert _coerce_to_optional_str(None) is None


def test_empty_string_returns_none() -> None:
    assert _coerce_to_optional_str("") is None


def test_whitespace_only_string_returns_none() -> None:
    assert _coerce_to_optional_str("   \n\t  ") is None


def test_plain_string_passes_through_stripped() -> None:
    assert _coerce_to_optional_str("  Crl. Appeal No. 2056 of 2014  ") == (
        "Crl. Appeal No. 2056 of 2014"
    )


def test_list_of_consolidated_appeal_numbers_joined() -> None:
    """The exact shape gpt-5-mini emitted on
    ``2014_10_458_478_GAR.pdf``."""
    raw = [
        "Crl. Appeal No. 2056 of 2014",
        "Crl. Appeal Nos. 2057-58 of 2014",
        "SLP (Crl.) No. 553/2011",
        "SLP (Crl.) Nos. 2203-2204/2011",
    ]
    assert _coerce_to_optional_str(raw) == (
        "Crl. Appeal No. 2056 of 2014; "
        "Crl. Appeal Nos. 2057-58 of 2014; "
        "SLP (Crl.) No. 553/2011; "
        "SLP (Crl.) Nos. 2203-2204/2011"
    )


def test_tuple_handled_like_list() -> None:
    assert _coerce_to_optional_str(("A", "B")) == "A; B"


def test_empty_list_returns_none() -> None:
    assert _coerce_to_optional_str([]) is None


def test_list_with_only_blanks_returns_none() -> None:
    assert _coerce_to_optional_str(["", "   ", None]) is None


def test_list_drops_blanks_and_strips_items() -> None:
    assert _coerce_to_optional_str(["  A  ", "", None, "B", "  "]) == "A; B"


def test_list_skips_nested_containers() -> None:
    """A list of dicts/lists is dropped item-by-item rather than
    flattened — flattening risks emitting ``"{'k': 'v'}"`` strings."""
    assert _coerce_to_optional_str(
        ["Crl. Appeal No. 1 of 2024", {"x": "y"}, ["nested"], "Crl. Appeal No. 2 of 2024"]
    ) == "Crl. Appeal No. 1 of 2024; Crl. Appeal No. 2 of 2024"


def test_list_with_non_string_scalars_stringified() -> None:
    assert _coerce_to_optional_str([2056, 2057, "SLP 553"]) == "2056; 2057; SLP 553"


def test_dict_returns_none() -> None:
    """A dict has no obvious single-string value to pick. We refuse
    to guess; persist None and let the doc's other fields carry the
    information."""
    assert _coerce_to_optional_str({"primary": "Crl. Appeal No. 1"}) is None


def test_int_scalar_stringified() -> None:
    assert _coerce_to_optional_str(2024) == "2024"


def test_long_consolidated_list_capped_at_field_floor() -> None:
    """Pydantic's smallest cap among the three target fields is
    ``outcome.max_length=240``. The validator must trim at item
    boundaries so a 30-item appeal list doesn't blow past 240. We
    accept some loss of trailing items rather than rejecting the
    whole payload."""
    items = [f"Crl. Appeal No. {i} of 2024" for i in range(40)]
    out = _coerce_to_optional_str(items)
    assert out is not None
    assert len(out) <= 240
    # Items survive at the front — earlier appeals first, by index.
    assert out.startswith("Crl. Appeal No. 0 of 2024")


def test_pathologically_long_single_item_hard_cut_at_240() -> None:
    items = ["x" * 1000]
    out = _coerce_to_optional_str(items)
    assert out is not None
    assert len(out) == 240


# ---------- _ExtractionPayload integration tests ------------------


def _minimal_payload(**overrides: object) -> dict:
    """Build the smallest payload that ``_ExtractionPayload`` will
    validate successfully, overriding any field for the assertion."""
    base: dict = {
        "case_title": "Foo v. Bar",
        "judges": ["Jane J."],
        "parties": {"appellants": ["Foo"], "respondents": ["Bar"]},
        "advocates": {"for_appellants": [], "for_respondents": []},
        "case_number": "C/123/2024",
        "sections_cited": [],
        "outcome": "Disposed",
        "chunks": [],
    }
    base.update(overrides)
    return base


def test_payload_accepts_list_case_number_consolidated_appeals() -> None:
    """The exact reproducer from the 2026-05-04 prod failure — the
    payload must validate, and the joined string must persist."""
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(case_number=[
            "Crl. Appeal No. 2056 of 2014",
            "Crl. Appeal Nos. 2057-58 of 2014",
            "SLP (Crl.) No. 553/2011",
        ])
    )
    assert payload.case_number == (
        "Crl. Appeal No. 2056 of 2014; "
        "Crl. Appeal Nos. 2057-58 of 2014; "
        "SLP (Crl.) No. 553/2011"
    )


def test_payload_accepts_null_case_number() -> None:
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(case_number=None)
    )
    assert payload.case_number is None


def test_payload_accepts_empty_list_case_number_as_none() -> None:
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(case_number=[])
    )
    assert payload.case_number is None


def test_payload_existing_string_case_number_unchanged() -> None:
    """No regression: a single-string case_number flows through
    untouched (modulo whitespace strip)."""
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(case_number="Crl. Appeal No. 2056 of 2014")
    )
    assert payload.case_number == "Crl. Appeal No. 2056 of 2014"


def test_payload_accepts_list_case_title_multiline_head() -> None:
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(case_title=[
            "SWADESI JAGARAN MANCH",
            "v.",
            "STATE OF ORISSA & ANR.",
        ])
    )
    assert payload.case_title == "SWADESI JAGARAN MANCH; v.; STATE OF ORISSA & ANR."


def test_payload_accepts_list_outcome_multi_clause_disposition() -> None:
    payload = _ExtractionPayload.model_validate(
        _minimal_payload(outcome=[
            "Appeal allowed",
            "Listed for hearing on 2025-08-12",
        ])
    )
    assert payload.outcome == "Appeal allowed; Listed for hearing on 2025-08-12"


def test_payload_real_world_failing_doc_now_validates() -> None:
    """End-to-end smoke: the literal JSON the prod log captured for
    ``2014_10_458_478_GAR.pdf`` (PR #11 anchor) must now validate
    cleanly. Schema strictness was the only thing rejecting it."""
    raw = json.dumps({
        "court_name": "Supreme Court of India",
        "forum_level": "supreme_court",
        "source_reference": "2014_10_458_478_GAR.pdf",
        "case_title": (
            "Criminal Appeal Nos. 2056-58 of 2014 "
            "(SLP(Crl.) Nos. 553/2011, 2203-2204/2011)"
        ),
        "judges": ["R. Banumathi", "T.S. Thakur"],
        "parties": {
            "appellants": ["Edmund S. Lyngdoh", "Deva Prasad Sharma"],
            "respondents": ["State of Meghalaya", "Central Bureau of Investigation"],
        },
        "advocates": [],
        "case_number": [
            "Crl. Appeal No. 2056 of 2014",
            "Crl. Appeal Nos. 2057-58 of 2014",
            "SLP (Crl.) No. 553/2011",
            "SLP (Crl.) Nos. 2203-2204/2011",
        ],
        "sections_cited": [
            "IPC s.420", "IPC s.120B", "PC Act s.5(2)",
            "PC Act s.5(1)(d)", "CrPC s.235(2)", "CrPC s.313",
        ],
        "outcome": None,
        "chunks": [],
    })
    payload = _ExtractionPayload.model_validate_json(raw)
    assert payload.case_number is not None
    assert "Crl. Appeal No. 2056 of 2014" in payload.case_number
    assert "SLP (Crl.) Nos. 2203-2204/2011" in payload.case_number


# ---------- regression-fence: schema caps still respected -----------


def test_payload_outcome_cap_240_still_enforced_by_pydantic() -> None:
    """Sanity: if the validator is ever broken to return a >240
    string for outcome, pydantic must reject. We pin the schema cap
    so a careless future widening is caught."""
    field = _ExtractionPayload.model_fields["outcome"]
    metadata = field.metadata
    max_lengths = [getattr(m, "max_length", None) for m in metadata]
    assert 240 in max_lengths


def test_payload_case_number_cap_480_still_enforced_by_pydantic() -> None:
    field = _ExtractionPayload.model_fields["case_number"]
    metadata = field.metadata
    max_lengths = [getattr(m, "max_length", None) for m in metadata]
    assert 480 in max_lengths


def test_payload_case_title_cap_800_still_enforced_by_pydantic() -> None:
    field = _ExtractionPayload.model_fields["case_title"]
    metadata = field.metadata
    max_lengths = [getattr(m, "max_length", None) for m in metadata]
    assert 800 in max_lengths


# ---------- pre-existing schema rejections still fire --------------


def test_payload_rejects_truly_unparseable_garbage_for_judges() -> None:
    """Sanity: the surrounding schema is still strict where it
    matters. ``judges`` declared as ``list[str]`` with a 40-item cap
    rejects a 100-item list to prove the validator is targeted, not
    a blanket loosening."""
    items = [f"J{i}" for i in range(100)]
    with pytest.raises(ValidationError):
        _ExtractionPayload.model_validate(_minimal_payload(judges=items))
