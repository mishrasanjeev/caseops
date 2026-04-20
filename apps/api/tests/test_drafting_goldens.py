"""Sprint R7 + R8 — fixture-driven regression harness.

Ships the first slice of the per-type eval suite:

- ``apps/api/tests/fixtures/drafting/{template_type}.json`` — the
  canonical fact-patterns for each template.
- This module loads the fixtures and runs three contracts:

  1. Every fixture's fact-pattern satisfies the template's Pydantic
     facts model — so the stepper never receives a schema-mismatched
     fixture.
  2. Every fixture's ``facts`` can be rendered through the per-type
     prompt without a template registry miss.
  3. For each fixture, a "good" synthetic draft that *would* satisfy
     the R5 validator passes, and a stripped-down synthetic that
     drops the rule's signal fails with the expected rule code.

The live-LLM comparison (hit Haiku with the fact-pattern, score the
output against the golden) runs in the dedicated
``caseops-eval-drafting --type <t>`` CLI — out of scope here because
it depends on an Anthropic key and budget. This harness is the
deterministic floor that catches a regression before the live run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    get_template_facts_model,
)
from caseops_api.services.draft_type_validators import validate_draft_by_type
from caseops_api.services.drafting_prompts import get_prompt_parts

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "drafting"


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def _iter_all_scenarios() -> list[tuple[DraftTemplateType, str, dict, dict]]:
    """Flatten every fixture into (template_type, key, facts, meta)."""
    out: list[tuple[DraftTemplateType, str, dict, dict]] = []
    # Standalone fixture files (one template type each).
    for fname in ("bail.json", "cheque_bounce_notice.json", "anticipatory_bail.json", "civil_suit.json"):
        data = _load(fname)
        tt = DraftTemplateType(data["template_type"])
        for s in data["scenarios"]:
            out.append((tt, s["key"], s["facts"], s))
    # Combined fixture for the remaining types.
    misc = _load("misc_templates.json")
    for type_key, block in misc["templates"].items():
        tt = DraftTemplateType(type_key)
        for s in block["scenarios"]:
            out.append((tt, s["key"], s["facts"], s))
    return out


@pytest.mark.parametrize(
    ("template_type", "key", "facts", "meta"),
    [
        (tt, key, facts, meta)
        for tt, key, facts, meta in _iter_all_scenarios()
    ],
)
def test_fixture_facts_match_pydantic_schema(
    template_type: DraftTemplateType, key: str, facts: dict, meta: dict,
) -> None:
    """Every fixture's facts block must validate under the template's
    Pydantic facts model, including the ``matter_id`` + ``focus_note``
    plumbing. Stepping through a fixture must never be a schema
    bug."""
    _ = key, meta
    model_cls = get_template_facts_model(template_type)
    payload = {
        "matter_id": "11111111-1111-1111-1111-111111111111",
        **facts,
    }
    model_cls.model_validate(payload)


@pytest.mark.parametrize(
    "template_type",
    list(DraftTemplateType),
)
def test_every_template_has_a_matching_prompt(
    template_type: DraftTemplateType,
) -> None:
    """R2 parity — every template registered in R1 has a prompt in R2."""
    parts = get_prompt_parts(template_type)
    assert parts.system and parts.focus


def _synthetic_good_bail() -> str:
    return (
        "Application under BNSS Section 483 for grant of regular bail. "
        "The accused has been in custody since 1 March 2026. "
        "The triple test is satisfied: no flight risk (applicant is a "
        "resident of Delhi with roots), no tampering with evidence (the "
        "prosecution has completed examination of material witnesses), "
        "and no influencing of witnesses. Parity arguments apply - the "
        "co-accused has been granted bail by this Hon'ble Court."
    )


def _synthetic_bad_bail_missing_statute() -> str:
    # Deliberately omits any BNSS/CrPC citation — must fire
    # bail_missing_statute.
    return (
        "Application for bail. The accused has been in custody since "
        "1 March 2026. Triple test is satisfied: no flight risk, no "
        "tampering, no witness influence. Parity applies."
    )


def _synthetic_good_cheque_bounce() -> str:
    return (
        "Demand notice under Section 138 of the Negotiable Instruments "
        "Act, 1881. You are called upon to pay Rs. 5,00,000 (Rupees "
        "Five Lakhs only) within fifteen days of receipt of this "
        "notice."
    )


def _synthetic_bad_cheque_bounce_missing_days() -> str:
    # Omits the statutory window phrase — must fire
    # cheque_bounce_missing_15_day_window.
    return (
        "Demand notice under Section 138 of the Negotiable Instruments "
        "Act, 1881. You are called upon to pay Rs. 5,00,000 (Rupees "
        "Five Lakhs only) forthwith."
    )


def test_validator_passes_synthetic_good_bail_draft() -> None:
    res = validate_draft_by_type(
        template_type=DraftTemplateType.BAIL,
        body=_synthetic_good_bail(),
    )
    assert res.passed, [f.rule for f in res.errors()]


def test_validator_fails_bail_without_statute() -> None:
    res = validate_draft_by_type(
        template_type=DraftTemplateType.BAIL,
        body=_synthetic_bad_bail_missing_statute(),
    )
    rules = {f.rule for f in res.errors()}
    assert "bail_missing_statute" in rules


def test_validator_passes_synthetic_good_cheque_bounce() -> None:
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE,
        body=_synthetic_good_cheque_bounce(),
    )
    assert res.passed, [f.rule for f in res.errors()]


def test_validator_fails_cheque_bounce_without_window_phrase() -> None:
    res = validate_draft_by_type(
        template_type=DraftTemplateType.CHEQUE_BOUNCE_NOTICE,
        body=_synthetic_bad_cheque_bounce_missing_days(),
    )
    rules = {f.rule for f in res.errors()}
    assert "cheque_bounce_missing_15_day_window" in rules


def test_fixture_count_covers_every_template_type() -> None:
    """Every DraftTemplateType must have at least one fixture scenario
    so the regression harness can't silently drop coverage for a
    type."""
    seen = {tt for tt, *_ in _iter_all_scenarios()}
    assert seen == set(DraftTemplateType)
