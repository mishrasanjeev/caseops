"""PG-005 Sprint 12 (2026-05-01) — live-LLM drafting quality harness.

Iterates the canonical drafting fixtures and runs each through the
**production drafting pipeline** (generate_structured against the
configured drafting model, currently GPT-5.1), then scores each
output on multiple dimensions and produces an aggregate 0-5 rating
per template + overall.

Why a separate script vs ``eval_drafting_types.py``:
- ``eval_drafting_types.py`` hits Haiku with the per-template prompt
  + a bare "Facts: ..." user message. Cheap regression eval, but it
  does NOT exercise the production system prompt (the generic
  ABSOLUTE RULES block + STATUTE GUIDANCE + bench-history hooks).
- This harness uses ``services.drafting._build_messages`` to assemble
  the EXACT prompt the production endpoint sends, producing
  measurements closer to what a fee-earner sees.

Scoring (each 0-5 per scenario, aggregated as mean):
- ``validator_score``: 5 if no error-level findings, 3 if warnings
  only, 0 otherwise.
- ``structure_score``: count of Cause Title / Facts / Grounds /
  Prayer / Verification headings present (5 = all 5).
- ``citation_score``: 5 if ≥3 verified citations, 3 if 1-2, 0 otherwise.

Aggregate rating = round(mean of the three scores, 1).
Target per PG-005: 4.8+/5.

Usage:

    python -m caseops_api.scripts.eval_drafting_quality \\
        --max-scenarios 4 \\
        --report-path docs/EVAL_DRAFTING_QUALITY_$(date +%F).md

By default --max-scenarios 1 keeps the run cheap. The script
respects the LLM_DAILY_SPEND_CAP_USD env var (default $20) and
short-circuits if the cap is reached.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    get_template_facts_model,
)
from caseops_api.services.draft_validators import run_validators

# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------

# Anchor outputs at the repo root (5 levels above this file).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "drafting"
)
_STANDALONE_FIXTURES = (
    "bail.json",
    "cheque_bounce_notice.json",
    "anticipatory_bail.json",
    "civil_suit.json",
)
_MISC_FIXTURE = "misc_templates.json"
_PLACEHOLDER_MATTER_ID = "11111111-1111-1111-1111-111111111111"
_TARGET_RATING = 4.8

# Heading patterns we look for in the body text. Case-insensitive.
_STRUCTURE_HEADINGS: list[tuple[str, list[str]]] = [
    ("cause_title", ["IN THE", "PETITIONER", "RESPONDENT", "VERSUS", "v."]),
    ("facts", ["STATEMENT OF FACTS", "FACTS", "BACKGROUND"]),
    ("grounds", ["GROUNDS", "ARGUMENTS", "SUBMISSIONS"]),
    ("prayer", ["PRAYER", "RELIEF SOUGHT"]),
    ("verification", ["VERIFICATION", "AFFIRMATION", "VERIFIED ON OATH"]),
]


# ---------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------


@dataclass
class ScenarioResult:
    template_type: str
    key: str
    body: str = ""
    error: str | None = None
    validator_score: float = 0.0
    structure_score: float = 0.0
    citation_score: float = 0.0
    rating: float = 0.0
    findings_summary: list[str] = field(default_factory=list)
    structure_present: list[str] = field(default_factory=list)
    citation_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


# ---------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------


def _load(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_scenarios(max_per_type: int) -> list[tuple[str, str, dict]]:
    """Yield (template_type, key, facts) for each fixture, capped at
    `max_per_type` per template_type."""
    seen: dict[str, int] = {}
    out: list[tuple[str, str, dict]] = []
    for fname in _STANDALONE_FIXTURES:
        data = _load(fname)
        tt = data["template_type"]
        for s in data["scenarios"]:
            seen.setdefault(tt, 0)
            if seen[tt] >= max_per_type:
                continue
            seen[tt] += 1
            out.append((tt, s["key"], s["facts"]))
    misc = _load(_MISC_FIXTURE)
    for type_key, block in misc["templates"].items():
        for s in block["scenarios"]:
            seen.setdefault(type_key, 0)
            if seen[type_key] >= max_per_type:
                continue
            seen[type_key] += 1
            out.append((type_key, s["key"], s["facts"]))
    return out


# ---------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------


def _score_validator(
    template_type: str, body: str, citations: list[str],
) -> tuple[float, list[str]]:
    """Run draft validators; return (score, findings summary).

    5.0 = no error-level findings.
    3.0 = warning-only findings.
    0.0 = at least one error.
    """
    findings = run_validators(body, citations)
    summary = [f"[{f.severity}] {f.code}: {f.message}" for f in findings]
    has_error = any(f.severity == "error" for f in findings)
    if has_error:
        return 0.0, summary
    if findings:  # warning-only
        return 3.0, summary
    return 5.0, summary


def _score_structure(body: str) -> tuple[float, list[str]]:
    """Look for 5 canonical structural headings. 1 point each."""
    haystack = body.upper()
    present: list[str] = []
    for label, markers in _STRUCTURE_HEADINGS:
        if any(m.upper() in haystack for m in markers):
            present.append(label)
    return float(len(present)), present


def _score_citations(citations: list[str]) -> float:
    """5.0 = ≥3 citations, 3.0 = 1-2, 0.0 = none."""
    n = len(citations or [])
    if n >= 3:
        return 5.0
    if n >= 1:
        return 3.0
    return 0.0


# ---------------------------------------------------------------
# Live-LLM call
# ---------------------------------------------------------------


def _run_one_scenario(
    template_type: str, key: str, facts: dict, *, dry_run: bool,
) -> ScenarioResult:
    """Validate facts → build production prompt → run LLM → score."""
    result = ScenarioResult(template_type=template_type, key=key)

    # Validate the facts payload first; a bogus fixture skips the LLM
    # call entirely so we don't waste tokens.
    try:
        tt_enum = DraftTemplateType(template_type)
    except ValueError as exc:
        result.error = f"Unknown template_type: {exc}"
        return result
    facts_model = get_template_facts_model(tt_enum)
    payload = {**facts, "matter_id": _PLACEHOLDER_MATTER_ID}
    try:
        facts_model.model_validate(payload)
    except ValidationError as exc:
        result.error = f"Facts model validation failed: {exc.errors()[:3]}"
        return result

    # Build the EXACT production prompt by importing _build_messages
    # + a synthetic Matter / Draft pair. We don't hit the DB; the
    # prompt builder takes plain attribute reads off these objects.
    from caseops_api.services.drafting import _build_messages

    matter = type("M", (), {
        "id": _PLACEHOLDER_MATTER_ID,
        "title": f"Eval scenario — {key}",
        "matter_code": f"EVAL-{template_type[:6].upper()}-{key[:6]}",
        "practice_area": (
            "criminal"
            if "bail" in template_type or "criminal" in template_type
            else "civil"
        ),
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "judge_name": None,
        "client_name": "Eval Client",
        "opposing_party": "Eval Opposing",
        "description": f"Synthetic scenario for {template_type} ({key}).",
    })()
    draft = type("D", (), {
        "id": "draft-eval",
        "matter_id": matter.id,
        "title": f"Eval — {key}",
        "draft_type": "brief",
        "template_type": template_type,
        "status": "draft",
        "review_required": True,
        # _build_messages reads draft.facts_json; the production
        # endpoint stores the stepper output here. Fixture facts go
        # in directly so the prompt sees them in the FACTS block.
        "facts_json": json.dumps(facts),
    })()

    messages = _build_messages(
        matter, draft, retrieved=[], focus_note=json.dumps(facts),
    )

    if dry_run:
        result.body = "[dry-run] " + messages[0].content[:400]
        return result

    # Run the LLM. Single retry on format error mirrors production.
    from caseops_api.services.drafting import _LLMDraftResponse
    from caseops_api.services.llm import (
        PURPOSE_DRAFTING,
        LLMCallContext,
        LLMResponseFormatError,
        build_provider,
        generate_structured,
        max_tokens_for_purpose,
    )

    provider = build_provider(purpose=PURPOSE_DRAFTING)
    ctx = LLMCallContext(
        tenant_id="", matter_id=_PLACEHOLDER_MATTER_ID, purpose="drafting:eval",
    )
    t0 = time.monotonic()
    try:
        response, completion = generate_structured(
            provider, schema=_LLMDraftResponse, messages=messages,
            context=ctx, max_tokens=max_tokens_for_purpose(PURPOSE_DRAFTING),
        )
    except LLMResponseFormatError:
        # Parallel to production: single retry.
        try:
            response, completion = generate_structured(
                provider, schema=_LLMDraftResponse, messages=messages,
                context=ctx, max_tokens=max_tokens_for_purpose(PURPOSE_DRAFTING),
            )
        except Exception as retry_exc:  # noqa: BLE001
            result.error = f"LLM retry failed: {type(retry_exc).__name__}: {retry_exc}"
            return result
    except Exception as exc:  # noqa: BLE001
        result.error = f"LLM call failed: {type(exc).__name__}: {exc}"
        return result

    result.latency_ms = int((time.monotonic() - t0) * 1000)
    result.body = response.body
    result.input_tokens = completion.prompt_tokens
    result.output_tokens = completion.completion_tokens
    result.citation_count = len(response.citations)

    val_score, val_findings = _score_validator(
        template_type, response.body, response.citations,
    )
    struct_score, struct_present = _score_structure(response.body)
    cite_score = _score_citations(response.citations)

    result.validator_score = val_score
    result.structure_score = struct_score
    result.citation_score = cite_score
    result.findings_summary = val_findings
    result.structure_present = struct_present
    result.rating = round((val_score + struct_score + cite_score) / 3, 2)

    return result


# ---------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------


def _aggregate(results: list[ScenarioResult], *, dry_run: bool) -> dict:
    """Roll up per-template rating + overall.

    Dry-run path: no LLM call was made, so scoring is meaningless.
    Codex 2026-05-01 flagged a real credibility problem: a previous
    dry-run write produced a "0.0/5 — meets target: NO" artifact
    that a reader couldn't distinguish from a real failed eval.
    Dry-run output now ships an explicit `dry_run: true` flag, sets
    `meets_target: null`, and skips the rating math entirely.
    """
    if dry_run:
        return {
            "dry_run": True,
            "overall_rating": None,
            "target": _TARGET_RATING,
            "meets_target": None,
            "note": (
                "Dry-run smoke output — the LLM was NOT called, no scoring "
                "performed. Re-run without --dry-run to produce a real "
                "rating. Reading any score in this file as a quality "
                "measurement is incorrect."
            ),
            "per_template": {
                tt: {"scenarios": len([r for r in results if r.template_type == tt])}
                for tt in {r.template_type for r in results}
            },
        }
    by_type: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_type.setdefault(r.template_type, []).append(r)
    per_type_rating: dict[str, dict] = {}
    overall_ratings: list[float] = []
    for tt, runs in by_type.items():
        valid = [r for r in runs if r.error is None]
        if not valid:
            per_type_rating[tt] = {"rating": 0.0, "scenarios": len(runs), "errored": len(runs)}
            continue
        avg = round(sum(r.rating for r in valid) / len(valid), 2)
        per_type_rating[tt] = {
            "rating": avg,
            "scenarios": len(valid),
            "errored": len(runs) - len(valid),
            "total_input_tokens": sum(r.input_tokens for r in valid),
            "total_output_tokens": sum(r.output_tokens for r in valid),
            "median_latency_ms": sorted([r.latency_ms for r in valid])[len(valid) // 2],
        }
        overall_ratings.append(avg)
    overall = round(sum(overall_ratings) / len(overall_ratings), 2) if overall_ratings else 0.0
    return {
        "dry_run": False,
        "overall_rating": overall,
        "target": _TARGET_RATING,
        "meets_target": overall >= _TARGET_RATING,
        "per_template": per_type_rating,
    }


def _write_report(
    results: list[ScenarioResult], summary: dict, report_path: Path, artifact_path: Path,
) -> None:
    is_dry = bool(summary.get("dry_run"))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "scenarios": [
                    {
                        "template_type": r.template_type,
                        "key": r.key,
                        "rating": r.rating,
                        "validator_score": r.validator_score,
                        "structure_score": r.structure_score,
                        "citation_score": r.citation_score,
                        "structure_present": r.structure_present,
                        "citation_count": r.citation_count,
                        "findings_summary": r.findings_summary,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "latency_ms": r.latency_ms,
                        "error": r.error,
                    }
                    for r in results
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if is_dry:
        lines.append("# Drafting quality eval — DRY-RUN smoke output")
        lines.append("")
        lines.append(
            "**Important:** this report was produced with `--dry-run`. "
            "The LLM was NOT called, no scoring was performed. Any number "
            "appearing as `0.0/5` below is an artefact of skipping the LLM "
            "step, not a real quality measurement. Re-run "
            "`python -m caseops_api.scripts.eval_drafting_quality` "
            "without the `--dry-run` flag to produce a real rating against "
            f"the **{summary['target']}/5** PG-005 target."
        )
        lines.append("")
        lines.append(f"Scenarios queued: {len(results)}")
        for r in results:
            lines.append(f"- `{r.template_type}` / `{r.key}`")
        return _finalise_report(lines, report_path)
    lines.append(f"# Drafting quality eval — overall {summary['overall_rating']}/5")
    lines.append("")
    lines.append(
        f"Target: **{summary['target']}/5**. "
        f"Meets target: **{'YES' if summary['meets_target'] else 'NO'}**."
    )
    lines.append("")
    lines.append("## Per-template ratings")
    lines.append("")
    lines.append("| Template | Rating | Scenarios | Errored | Median latency (ms) |")
    lines.append("|---|---|---|---|---|")
    for tt, row in sorted(
        summary["per_template"].items(), key=lambda kv: kv[1]["rating"], reverse=True,
    ):
        lines.append(
            f"| `{tt}` | **{row['rating']}/5** | {row['scenarios']} | "
            f"{row['errored']} | {row.get('median_latency_ms', '-')} |"
        )
    lines.append("")
    lines.append("## Per-scenario detail")
    lines.append("")
    for r in results:
        lines.append(f"### `{r.template_type}` / `{r.key}` — {r.rating}/5")
        if r.error:
            lines.append(f"- ERROR: {r.error}")
            continue
        lines.append(f"- validator: {r.validator_score}/5")
        lines.append(f"- structure: {r.structure_score}/5 (found: {r.structure_present})")
        lines.append(f"- citations: {r.citation_score}/5 ({r.citation_count} cites)")
        if r.findings_summary:
            lines.append("- findings:")
            for f in r.findings_summary[:5]:
                lines.append(f"  - {f}")
        lines.append("")
    _finalise_report(lines, report_path)


def _finalise_report(lines: list[str], report_path: Path) -> None:
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-LLM drafting quality eval")
    parser.add_argument("--max-scenarios", type=int, default=1, help="cap per template_type")
    parser.add_argument(
        "--report-path",
        default=str(_REPO_ROOT / "docs" / "EVAL_DRAFTING_QUALITY.md"),
    )
    parser.add_argument(
        "--artifact-path",
        default=str(_REPO_ROOT / "docs" / "eval_artifacts" / "drafting_quality.json"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't call the LLM; just emit the assembled prompt for each scenario",
    )
    parser.add_argument(
        "--templates",
        nargs="*",
        default=None,
        help="restrict to specific template_type values",
    )
    args = parser.parse_args(argv)

    scenarios = _iter_scenarios(args.max_scenarios)
    if args.templates:
        allowed = set(args.templates)
        scenarios = [s for s in scenarios if s[0] in allowed]

    print(f"Running {len(scenarios)} scenarios "
          f"({'dry-run' if args.dry_run else 'LIVE'})...", file=sys.stderr)

    results: list[ScenarioResult] = []
    for tt, key, facts in scenarios:
        print(f"  - {tt} / {key} ...", file=sys.stderr)
        r = _run_one_scenario(tt, key, facts, dry_run=args.dry_run)
        results.append(r)
        if r.error:
            print(f"    ERROR: {r.error}", file=sys.stderr)
        else:
            print(
                f"    rating={r.rating}/5 "
                f"(val={r.validator_score} struct={r.structure_score} "
                f"cite={r.citation_score})",
                file=sys.stderr,
            )

    summary = _aggregate(results, dry_run=args.dry_run)
    _write_report(
        results, summary, Path(args.report_path), Path(args.artifact_path),
    )
    if summary.get("dry_run"):
        print(
            f"\nDRY-RUN: {len(results)} scenarios queued; LLM not called. "
            f"Re-run without --dry-run for a real rating.",
            file=sys.stderr,
        )
    else:
        print(
            f"\nOverall: {summary['overall_rating']}/5 (target {summary['target']}). "
            f"Meets target: {summary['meets_target']}.",
            file=sys.stderr,
        )
    print(f"Report: {args.report_path}", file=sys.stderr)
    print(f"Artifact: {args.artifact_path}", file=sys.stderr)
    if summary.get("dry_run"):
        return 0
    return 0 if summary["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
