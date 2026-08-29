# AI Safety Eval Harness Runbook

Status: WTD-11.4 implemented; exact deployed acceptance remains a release gate.

The harness evaluates checked-in JSON fixtures and already-generated outputs.
It is deterministic and offline: it does not call an LLM provider, open a
production connection, read production data, run a corpus job, send a
notification, or require Temporal.

## Release Gate

From the repository root:

```powershell
uv run --project apps/api python -m caseops_api.scripts.eval_ai_safety --release-gate --pretty
```

CI runs the same `--release-gate` command. The command exits non-zero unless
every case passes and the release fixture covers all required surfaces and
rules.

Required surfaces:

- drafting;
- citation validation;
- Matter File Q&A;
- recommendations;
- Litigation Strategy;
- hearing packs;
- Ask this Workspace; and
- intelligent review.

Required rules:

- citation entailment and supported claims;
- source access and verification;
- authority relevance;
- contrary-authority treatment;
- insufficient-evidence abstention with a suggested verified-source search;
- permission boundaries;
- prompt-injection resistance;
- prohibited legal advice, prediction, reputation, and sensitive scoring;
- statute confusion;
- fact fabrication; and
- data exfiltration.

The release fixture is
`apps/api/tests/fixtures/ai_safety_eval/iplf065_release_pass.json`. Do not
replace a required surface or rule with a synthetic coverage label: the case
must exercise the corresponding detector and safe output shape.

## Detector Review

The checked-in detector-failure fixture intentionally returns a failing exit
code:

```powershell
uv run --project apps/api python -m caseops_api.scripts.eval_ai_safety `
  --fixtures apps/api/tests/fixtures/ai_safety_eval/iplf065_detector_failures.json `
  --pretty
```

Use it when changing detector behavior. Unit tests assert each failure class,
so CI can distinguish a safe fixture from a detector that silently stopped
working.

The legacy WTD-11.4 fixtures remain readable for backwards compatibility.
Schema-v1 input does not satisfy the release gate because it lacks explicit
complete surface/rule coverage.

## Output And Persistence

To write the redacted machine artifact:

```powershell
uv run --project apps/api python -m caseops_api.scripts.eval_ai_safety `
  --release-gate `
  --output docs/eval_artifacts/ai_safety_release.json
```

Schema-v2 output contains the harness and mode, aggregate summary, release-gate
summary, covered and missing surfaces/rules, and bounded per-case findings and
integer metrics. It omits raw model output, full source snippets, document or
OCR text, source payloads, credentials, tenant content, and database details.

An approved caller may persist the redacted result through the existing
`EvaluationRun`/`EvaluationCase` owner. The harness does not create a second
evaluation store, feedback analytics store, or provider benchmark record.

## Adding Fixtures

Add bounded fixtures under `apps/api/tests/fixtures/ai_safety_eval/`. Each case
must declare a unique `case_id`, supported `surface`, applicable `rules`,
bounded permitted sources, already-generated output, and `expected_result`.

Never put full document text, OCR text, tenant data, provider payloads, secrets,
or API keys in a fixture. A new AI surface cannot ship merely by adding its name
to the required set: add safe and negative cases, detector assertions, and CI
coverage in the same change.

## Operational Boundary

This release gate proves deterministic repository safety behavior. It does not
claim model quality in production, legal acceptance, provider certification,
or human UAT. Any future live-provider benchmark requires separate approval,
isolated non-production data, cost controls, and its own evidence record.
