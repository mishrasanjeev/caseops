"""PG-005 Sprint 7 (2026-05-01) — bench-aware drafting expansion tests.

Verifies that the bench-strategy context injection + the PG-107
predictive-mode workspace addendum, both previously gated to
``appeal_memorandum`` only, now fire for every template in the
expanded ``_BENCH_AWARE_TEMPLATES`` set, AND DO NOT fire for
templates that are intentionally outside the set
(``vakalatnama``, ``caveat_petition``, ``affidavit``, etc.).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from caseops_api.db.models import Draft, Matter
from caseops_api.schemas.drafting_templates import DraftTemplateType
from caseops_api.services.drafting import (
    _BENCH_AWARE_TEMPLATES,
    _build_messages,
)


def _matter() -> Matter:
    return Matter(
        id="m-bench",
        company_id="c-bench",
        matter_code="BENCH-1",
        title="State v. Sample",
        practice_area="criminal",
        forum_level="high_court",
        court_name="Delhi High Court",
        judge_name="Hon'ble Mr Justice X",
        client_name="Sample",
        opposing_party="State",
        description="Sample matter for bench-aware drafting tests.",
    )


def _fake_bench_context(*, ctx_quality: str = "high") -> SimpleNamespace:
    """Duck-typed bench-strategy context. The drafting service uses
    getattr/duck-typing so it doesn't import the real dataclass —
    SimpleNamespace is enough for these tests."""
    return SimpleNamespace(
        context_quality=ctx_quality,
        structured_match_coverage_percent=42,
        recurring_tests=[
            SimpleNamespace(
                phrase="triple test for bail",
                occurrences=4,
                sample_authority_ids=("auth-1", "auth-2", "auth-3"),
            ),
        ],
        practice_area_patterns=[
            SimpleNamespace(
                area="criminal",
                authority_count=11,
                sample_authority_ids=("auth-1", "auth-2", "auth-3"),
            ),
        ],
        drafting_cautions=[],
        unsupported_gaps=[],
    )


_BENCH_AWARE_LITIGATION_TEMPLATES = sorted(_BENCH_AWARE_TEMPLATES)

# Templates intentionally OUTSIDE the bench-aware set — pre-litigation
# notices + procedural-only filings. Bench tendencies don't help these
# drafts; injecting them would just be noise.
_NON_BENCH_AWARE_TEMPLATES = sorted(
    {t.value for t in DraftTemplateType} - _BENCH_AWARE_TEMPLATES
)


# ---------------------------------------------------------------
# Predictive-mode workspace addendum gating.
# ---------------------------------------------------------------


@pytest.mark.parametrize("template_type", _BENCH_AWARE_LITIGATION_TEMPLATES)
def test_predictive_addendum_fires_for_every_bench_aware_template(
    template_type: str,
) -> None:
    """The WORKSPACE POLICY OVERRIDE addendum used to gate on
    appeal_memorandum only. Sprint 7 expanded it; verify it now fires
    for each litigation template."""
    matter = _matter()
    draft = Draft(id="d-test", matter_id=matter.id, template_type=template_type)
    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        predictive_bench_enabled=True,
    )
    system = messages[0].content
    assert "WORKSPACE POLICY OVERRIDE" in system, (
        f"{template_type}: predictive addendum was NOT injected — "
        f"Sprint 7 gate is broken for this template."
    )
    assert "Predictive analytics" in system


@pytest.mark.parametrize("template_type", _NON_BENCH_AWARE_TEMPLATES)
def test_predictive_addendum_does_not_fire_for_non_bench_templates(
    template_type: str,
) -> None:
    """Pre-litigation notices + procedural-only filings (vakalat,
    caveat) must NEVER receive the predictive addendum, even with the
    workspace flag on — bench tendencies are not relevant."""
    matter = _matter()
    draft = Draft(id="d-test", matter_id=matter.id, template_type=template_type)
    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        predictive_bench_enabled=True,
    )
    system = messages[0].content
    assert "WORKSPACE POLICY OVERRIDE" not in system, (
        f"{template_type}: predictive addendum LEAKED into a non-bench-"
        f"aware template — Sprint 7 gate is too permissive."
    )


# ---------------------------------------------------------------
# BENCH HISTORY CONTEXT block gating.
# ---------------------------------------------------------------


@pytest.mark.parametrize("template_type", _BENCH_AWARE_LITIGATION_TEMPLATES)
def test_bench_history_block_injects_for_bench_aware_template(
    template_type: str,
) -> None:
    matter = _matter()
    draft = Draft(id="d-test", matter_id=matter.id, template_type=template_type)
    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        bench_context=_fake_bench_context(ctx_quality="high"),
    )
    # Bench-history block is injected into the USER message (the
    # matter-record + retrieved-authorities body), not the system
    # prompt. messages[1] is the user role.
    user_body = messages[1].content
    assert "BENCH HISTORY CONTEXT" in user_body, (
        f"{template_type}: bench-history context block was NOT injected"
    )
    # The fake context's recurring test should appear verbatim.
    assert "triple test for bail" in user_body


@pytest.mark.parametrize("template_type", _NON_BENCH_AWARE_TEMPLATES)
def test_bench_history_block_skipped_for_non_bench_template(
    template_type: str,
) -> None:
    """Even when bench_context is supplied, the prompt MUST NOT inject
    the BENCH HISTORY CONTEXT block for templates outside the set —
    drafting a vakalat with bench analytics would be obviously wrong."""
    matter = _matter()
    draft = Draft(id="d-test", matter_id=matter.id, template_type=template_type)
    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        bench_context=_fake_bench_context(ctx_quality="high"),
    )
    user_body = messages[1].content
    assert "BENCH HISTORY CONTEXT" not in user_body, (
        f"{template_type}: bench-history block leaked into a non-bench-"
        f"aware template"
    )


def test_bench_history_low_context_emits_limitation_note() -> None:
    """When ctx_quality is low/none, the prompt must surface a
    limitation note rather than silently inferring tendencies."""
    matter = _matter()
    draft = Draft(
        id="d-test",
        matter_id=matter.id,
        template_type=DraftTemplateType.WRIT_PETITION.value,
    )
    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        bench_context=_fake_bench_context(ctx_quality="low"),
    )
    user_body = messages[1].content
    assert "BENCH HISTORY CONTEXT" in user_body
    assert "BENCH CONTEXT IS LOW/NONE" in user_body
    # And the limitation note must use 'general legal principles', not
    # the appeal-only 'general appellate principles'.
    assert "general legal principles" in user_body


def test_bench_aware_templates_set_membership() -> None:
    """Sanity check the explicit set against expected canonical
    membership — this guards against accidental edits."""
    # 15 of 20 templates are bench-aware (5 excluded:
    # property_dispute_notice, cheque_bounce_notice, affidavit,
    # vakalatnama, caveat_petition).
    assert len(_BENCH_AWARE_TEMPLATES) == 15
    expected = {
        "bail",
        "anticipatory_bail",
        "writ_petition",
        "quashing_petition",
        "dv_quashing_petition",
        "civil_suit",
        "written_statement",
        "reply_counter_affidavit",
        "appeal_memorandum",
        "arbitration_section_9",
        "criminal_complaint",
        "amendment_of_pleadings",
        "divorce_petition",
        "compromise_petition",
        "probate_petition",
    }
    assert _BENCH_AWARE_TEMPLATES == frozenset(expected)
    # And every key must round-trip through the enum (catches typos).
    for tt in _BENCH_AWARE_TEMPLATES:
        DraftTemplateType(tt)
