"""Sprint R8 — live-LLM regression eval for each DraftTemplateType.

For every fixture in ``apps/api/tests/fixtures/drafting/``, this
script hits Haiku with the per-type R2 system prompt + a "Facts: ..."
user message, then runs the R5 ``validate_draft_by_type`` validator
over the generated body and records whether it passed.

Output:

- A markdown report per-type pass rate + rule-miss histogram, written
  to ``docs/EVAL_DRAFTING_TYPES_2026-04-21.md`` and stdout.
- A JSON artifact containing the full generated drafts + findings at
  ``docs/eval_artifacts/drafting_types_2026_04_21.json``.

Model routing: we construct an ``AnthropicProvider`` directly against
the Haiku model from ``settings.llm_model_metadata_extract``. The
drafting-purpose model (Opus) is deliberately skipped — this is a
cheap regression eval, not a production draft.

Budget sizing: ~24 scenarios × ~2k output tokens × Haiku pricing
(~$1/MTok input + $5/MTok output) ≈ $5 end-to-end.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.schemas.drafting_templates import (
    DraftTemplateType,
    get_template_facts_model,
)
from caseops_api.services.draft_type_validators import (
    TypeValidationFinding,
    validate_draft_by_type,
)
from caseops_api.services.drafting_prompts import get_prompt_parts
from caseops_api.services.llm import (
    AnthropicProvider,
    LLMMessage,
    LLMProviderError,
)

# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------

# Haiku 4.5 pricing (per 1M tokens, USD) as of 2026-04.
_HAIKU_INPUT_PRICE_PER_MTOK = 1.00
_HAIKU_OUTPUT_PRICE_PER_MTOK = 5.00
_DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Fixture layout. Standalone files each carry one template_type;
# misc_templates.json contains the remaining types in a nested map.
# ``scripts/eval_drafting_types.py`` is four ``parents`` deep from
# ``apps/api/`` (scripts -> caseops_api -> src -> api).
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

# Placeholder matter_id so facts models validate. Same value the
# R7/R8 fixture harness uses in tests/test_drafting_goldens.py.
_PLACEHOLDER_MATTER_ID = "11111111-1111-1111-1111-111111111111"

# Anchor report + artifact outputs on the repo root (two levels
# above ``apps/api/``) so the script works regardless of CWD.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_REPORT_PATH = _REPO_ROOT / "docs" / "EVAL_DRAFTING_TYPES_2026-04-21.md"
_ARTIFACT_PATH = (
    _REPO_ROOT / "docs" / "eval_artifacts" / "drafting_types_2026_04_21.json"
)


# ---------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------


@dataclass
class ScenarioRun:
    template_type: str
    key: str
    facts: dict[str, Any]
    # Populated before the LLM call.
    pydantic_error: str | None = None
    # Populated after the LLM call.
    body: str = ""
    findings: list[TypeValidationFinding] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    llm_error: str | None = None

    @property
    def skipped_pre_llm(self) -> bool:
        return self.pydantic_error is not None

    @property
    def passed(self) -> bool:
        """PASS = validator found no error-level findings and no LLM error."""
        if self.skipped_pre_llm or self.llm_error:
            return False
        return not any(f.severity == "error" for f in self.findings)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


# ---------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------


def _load_fixture(name: str) -> dict[str, Any]:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _iter_scenarios() -> list[ScenarioRun]:
    """Return one ScenarioRun per fixture. Dedups on (type, key)."""
    seen: set[tuple[str, str]] = set()
    out: list[ScenarioRun] = []
    for fname in _STANDALONE_FIXTURES:
        data = _load_fixture(fname)
        tt = data["template_type"]
        for s in data["scenarios"]:
            pair = (tt, s["key"])
            if pair in seen:
                continue
            seen.add(pair)
            out.append(ScenarioRun(template_type=tt, key=s["key"], facts=s["facts"]))
    misc = _load_fixture(_MISC_FIXTURE)
    for type_key, block in misc["templates"].items():
        for s in block["scenarios"]:
            pair = (type_key, s["key"])
            if pair in seen:
                continue
            seen.add(pair)
            out.append(ScenarioRun(template_type=type_key, key=s["key"], facts=s["facts"]))
    return out


# ---------------------------------------------------------------
# Validation + LLM call
# ---------------------------------------------------------------


def _validate_facts_pydantic(run: ScenarioRun) -> None:
    """Populate ``run.pydantic_error`` if the facts don't validate."""
    try:
        tt = DraftTemplateType(run.template_type)
    except ValueError as exc:
        run.pydantic_error = f"unknown template type: {exc}"
        return
    model_cls = get_template_facts_model(tt)
    payload = {"matter_id": _PLACEHOLDER_MATTER_ID, **run.facts}
    try:
        model_cls.model_validate(payload)
    except ValidationError as exc:
        run.pydantic_error = str(exc)


def _build_user_message(facts: dict[str, Any]) -> str:
    """JSON-serialise the facts under a ``Facts:`` header."""
    return (
        "Facts:\n"
        f"{json.dumps(facts, indent=2, ensure_ascii=False)}\n\n"
        "Using the facts above, generate the complete draft body as "
        "plain text. Do not wrap the output in JSON or code fences — "
        "the downstream validator reads the raw body."
    )


def _run_scenario(
    provider: AnthropicProvider,
    run: ScenarioRun,
    *,
    max_tokens: int,
    temperature: float,
    dry_run: bool,
) -> None:
    """Mutate ``run`` with LLM output + validator findings."""
    _validate_facts_pydantic(run)
    if run.pydantic_error:
        return
    if dry_run:
        # Skip the call but keep the scenario in the report as "skipped".
        run.body = "[dry-run: no body generated]"
        return

    tt = DraftTemplateType(run.template_type)
    prompt_parts = get_prompt_parts(tt)
    messages = [
        LLMMessage(role="system", content=prompt_parts.system),
        LLMMessage(role="user", content=_build_user_message(run.facts)),
    ]
    try:
        completion = provider.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except LLMProviderError as exc:
        run.llm_error = str(exc)
        return

    run.body = completion.text or ""
    run.input_tokens = completion.prompt_tokens
    run.output_tokens = completion.completion_tokens
    run.latency_ms = completion.latency_ms

    result = validate_draft_by_type(template_type=tt, body=run.body)
    run.findings = list(result.findings)


# ---------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------


@dataclass
class AggregateStats:
    total: int = 0
    passed: int = 0
    pydantic_errors: int = 0
    llm_errors: int = 0
    warning_count: int = 0
    rule_counts: dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


def _aggregate(runs: list[ScenarioRun]) -> dict[str, AggregateStats]:
    per_type: dict[str, AggregateStats] = {}
    for run in runs:
        agg = per_type.setdefault(run.template_type, AggregateStats())
        agg.total += 1
        if run.skipped_pre_llm:
            agg.pydantic_errors += 1
            continue
        if run.llm_error:
            agg.llm_errors += 1
            continue
        if run.passed:
            agg.passed += 1
        agg.warning_count += run.warning_count
        for f in run.findings:
            # Count both error and warning rule-misses so the report
            # surfaces which validators fire most often regardless of
            # severity.
            agg.rule_counts[f.rule] = agg.rule_counts.get(f.rule, 0) + 1
        agg.input_tokens += run.input_tokens
        agg.output_tokens += run.output_tokens
    return per_type


def _format_report(
    per_type: dict[str, AggregateStats],
    *,
    model: str,
    total_cost_usd: float,
    runs: list[ScenarioRun],
) -> str:
    lines: list[str] = []
    lines.append("# Sprint R8 — per-template drafting eval (live Haiku)")
    lines.append("")
    lines.append(f"- model: `{model}`")
    lines.append(f"- total scenarios: {len(runs)}")
    total_passed = sum(a.passed for a in per_type.values())
    total_considered = sum(
        a.total - a.pydantic_errors - a.llm_errors for a in per_type.values()
    )
    overall_rate = (
        f"{(100.0 * total_passed / total_considered):.0f}%"
        if total_considered
        else "n/a"
    )
    lines.append(
        f"- **overall pass rate: {total_passed}/{total_considered} ({overall_rate})**"
    )
    lines.append(f"- estimated LLM cost: **${total_cost_usd:.4f}** USD")
    pyd_err = sum(a.pydantic_errors for a in per_type.values())
    llm_err = sum(a.llm_errors for a in per_type.values())
    if pyd_err:
        lines.append(f"- pydantic pre-flight errors: {pyd_err}")
    if llm_err:
        lines.append(f"- LLM call errors: {llm_err}")
    lines.append("")

    lines.append("## Per-type pass rate")
    lines.append("")
    lines.append("| Template type | Passed | Warnings | Skipped (pydantic) | Errored (LLM) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for tt in sorted(per_type):
        a = per_type[tt]
        considered = a.total - a.pydantic_errors - a.llm_errors
        rate = (
            f"{a.passed}/{considered} ({(100.0 * a.passed / considered):.0f}%)"
            if considered
            else f"0/{a.total} (n/a)"
        )
        lines.append(
            f"| `{tt}` | {rate} | {a.warning_count} | "
            f"{a.pydantic_errors} | {a.llm_errors} |"
        )
    lines.append("")

    lines.append("## Rule-miss histogram")
    lines.append("")
    global_counts: dict[str, int] = {}
    for a in per_type.values():
        for rule, n in a.rule_counts.items():
            global_counts[rule] = global_counts.get(rule, 0) + n
    if not global_counts:
        lines.append("_No validator findings fired — every draft passed cleanly._")
    else:
        for rule, n in sorted(global_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{rule}`: {n}")
    lines.append("")

    lines.append("## Per-scenario status")
    lines.append("")
    lines.append("| Type | Key | Status | Error findings | Warnings |")
    lines.append("| --- | --- | --- | --- | --- |")
    for run in runs:
        if run.skipped_pre_llm:
            status = "skipped (pydantic)"
        elif run.llm_error:
            status = "errored (LLM)"
        elif run.passed:
            status = "PASS"
        else:
            status = "FAIL"
        err_rules = [
            f.rule for f in run.findings if f.severity == "error"
        ]
        warn_rules = [
            f.rule for f in run.findings if f.severity == "warning"
        ]
        lines.append(
            f"| `{run.template_type}` | `{run.key}` | {status} | "
            f"{', '.join(err_rules) or '—'} | "
            f"{', '.join(warn_rules) or '—'} |"
        )
    lines.append("")
    rel_artifact = _ARTIFACT_PATH.relative_to(_REPO_ROOT).as_posix()
    lines.append(
        "Generated drafts and full findings are in "
        f"`{rel_artifact}`."
    )
    lines.append("")
    return "\n".join(lines)


def _write_artifacts(runs: list[ScenarioRun]) -> None:
    _ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenarios": [
            {
                "template_type": r.template_type,
                "key": r.key,
                "facts": r.facts,
                "pydantic_error": r.pydantic_error,
                "llm_error": r.llm_error,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "latency_ms": r.latency_ms,
                "body": r.body,
                "findings": [
                    {"severity": f.severity, "rule": f.rule, "message": f.message}
                    for f in r.findings
                ],
                "passed": r.passed,
            }
            for r in runs
        ]
    }
    with _ARTIFACT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def _write_report(report: str) -> None:
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _REPORT_PATH.open("w", encoding="utf-8") as fh:
        fh.write(report)


def _total_cost_usd(runs: list[ScenarioRun]) -> float:
    total_in = sum(r.input_tokens for r in runs)
    total_out = sum(r.output_tokens for r in runs)
    cost_in = (total_in / 1_000_000.0) * _HAIKU_INPUT_PRICE_PER_MTOK
    cost_out = (total_out / 1_000_000.0) * _HAIKU_OUTPUT_PRICE_PER_MTOK
    return cost_in + cost_out


# ---------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------


def _build_haiku_provider() -> AnthropicProvider:
    settings = get_settings()
    api_key = settings.llm_api_key
    if not api_key:
        raise SystemExit(
            "CASEOPS_LLM_API_KEY is not set. Cannot run live-LLM eval."
        )
    # Prefer the operator-configured metadata-extract model (already
    # Haiku per .env), fall back to the pinned default.
    model = (
        getattr(settings, "llm_model_metadata_extract", None)
        or _DEFAULT_HAIKU_MODEL
    )
    return AnthropicProvider(
        model=model,
        api_key=api_key,
        prompt_cache=True,
    )


def run(
    *,
    only_type: str | None,
    limit: int | None,
    dry_run: bool,
    max_tokens: int,
    temperature: float,
) -> int:
    all_runs = _iter_scenarios()
    if only_type:
        all_runs = [r for r in all_runs if r.template_type == only_type]
        if not all_runs:
            raise SystemExit(
                f"no fixtures matched --type {only_type!r}. valid: "
                f"{', '.join(sorted({r.template_type for r in _iter_scenarios()}))}"
            )
    if limit is not None and limit > 0:
        # Cap scenarios per type, preserving order.
        per_type_seen: dict[str, int] = {}
        capped: list[ScenarioRun] = []
        for r in all_runs:
            n = per_type_seen.get(r.template_type, 0)
            if n >= limit:
                continue
            per_type_seen[r.template_type] = n + 1
            capped.append(r)
        all_runs = capped

    provider = None
    if not dry_run:
        provider = _build_haiku_provider()

    for i, run_ in enumerate(all_runs, start=1):
        sys.stderr.write(
            f"[{i}/{len(all_runs)}] {run_.template_type}/{run_.key}... "
        )
        sys.stderr.flush()
        _run_scenario(
            provider,  # type: ignore[arg-type]
            run_,
            max_tokens=max_tokens,
            temperature=temperature,
            dry_run=dry_run,
        )
        if run_.skipped_pre_llm:
            sys.stderr.write("pydantic-error\n")
        elif run_.llm_error:
            sys.stderr.write(f"llm-error ({run_.llm_error[:60]})\n")
        elif run_.passed:
            sys.stderr.write("PASS\n")
        else:
            err_rules = ",".join(
                f.rule for f in run_.findings if f.severity == "error"
            )
            sys.stderr.write(f"FAIL ({err_rules or 'no-errors'})\n")

    per_type = _aggregate(all_runs)
    model_name = provider.model if provider else "(dry-run)"
    cost = _total_cost_usd(all_runs)
    report = _format_report(
        per_type, model=model_name, total_cost_usd=cost, runs=all_runs,
    )
    _write_artifacts(all_runs)
    _write_report(report)
    sys.stdout.write(report)
    sys.stdout.write("\n")
    # Non-zero exit when any scenario errored pre- or during-LLM, so
    # CI can gate on fixture sanity. Validator-level FAILs do not
    # fail the eval — they're the measurement we're taking.
    any_error = any(r.pydantic_error or r.llm_error for r in all_runs)
    return 1 if any_error else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseops-eval-drafting-types")
    parser.add_argument(
        "--type",
        dest="only_type",
        default=None,
        help="Only run this template type (e.g. 'bail'). Debug shortcut.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap scenarios per template type (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Skip the live LLM call; just validate fixture shapes and "
            "write a skeleton report."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Max output tokens per LLM call (default: 4096).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature (default: 0.1).",
    )
    args = parser.parse_args(argv)
    return run(
        only_type=args.only_type,
        limit=args.limit,
        dry_run=args.dry_run,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
