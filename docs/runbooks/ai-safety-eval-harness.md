# AI Safety Eval Harness Runbook

Status: WTD-11.4 foundation only.

This runbook covers the offline AI safety and quality evaluation harness added
for WTD-11.4. The harness evaluates checked-in JSON fixtures and already
generated outputs. It does not call live LLM providers, open production
connections, read production data, run corpus jobs, send notifications, or
require Temporal.

## What It Covers

Initial foundation coverage is intentionally small and deterministic:

- Matter File Q&A source grounding and insufficient-evidence refusal.
- Prompt-injection text inside a source being ignored rather than copied.
- Recommendation output with verified supporting citations.
- Litigation Strategy wording that avoids prediction and judge-reputation
  claims.
- Hearing-pack items carrying bounded source references.

The harness blocks:

- generated answers without source references;
- source IDs or source refs that are not present in the fixture input;
- copied prompt-injection text such as requests to reveal tenant data;
- directive legal-advice wording;
- guaranteed outcome, win-probability, or judge-reputation wording;
- emotion, biometric, psychological, mental-health, voice, or lie-detection
  scoring;
- oversized fixture output strings.

## How To Run

From `apps/api`:

```powershell
uv run caseops-eval-ai-safety --pretty
```

To write the machine-readable JSON artifact:

```powershell
uv run caseops-eval-ai-safety --output ../../docs/eval_artifacts/ai_safety_foundation.json
```

To exercise the checked-in negative detector cases locally:

```powershell
uv run caseops-eval-ai-safety --fixtures tests/fixtures/ai_safety_eval/wtd114_negative_cases.json --pretty
```

The default pass suite is suitable for a fast CI check. The negative suite is
for harness tests and detector review; it intentionally returns a failing exit
code because it contains unsafe generated outputs.

## Output Shape

The CLI writes JSON with:

- `schema_version`
- `harness`
- `mode`
- aggregate `summary`
- one entry per suite
- one entry per case with `case_id`, `surface`, `status`, `expected_result`,
  bounded `findings`, and integer `metrics`

The result intentionally omits raw model output, full source snippets, document
text, OCR text, source payloads, credentials, and DB connection information.

## Adding Fixtures

Add fixtures under `apps/api/tests/fixtures/ai_safety_eval/`.

Each case must include:

- `case_id`
- `surface`
- `input.sources` with bounded IDs/titles/snippets
- `output` with the already-generated response to evaluate
- `expected_result`

Use bounded snippets only. Do not paste full document text, OCR text, tenant
data, provider payloads, secrets, or API keys into fixtures.

## Foundation Limits

This milestone is not full WTD-11.4 closure. Remaining work:

- add per-workflow goldens for drafting, citations, Matter File Q&A,
  recommendations, Litigation Strategy, hearing packs, and any new AI route;
- add richer citation-validity and statute-confusion checks;
- add data-exfiltration red-team cases for every source-bearing workflow;
- decide whether the fast default suite should become a required CI gate for
  prompt/model changes;
- preserve separate live-provider evaluation approval for any future model
  benchmark run.
