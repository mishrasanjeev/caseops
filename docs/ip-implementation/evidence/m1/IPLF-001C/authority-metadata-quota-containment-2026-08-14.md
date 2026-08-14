# Authority-metadata quota containment and exact-release checkpoint - 2026-08-14

## Verdict

The quota-containment change is deployed on exact canonical release
`8d9654bbe556ad4fa24caf64578ac9cf55343a0e`. The recurring authority-metadata
scheduler is intentionally `PAUSED`, its job timeout is bounded to 43,200
seconds, and a strict one-document provider canary stopped after one OpenAI
request with typed quota exit code `3`. This is successful containment evidence,
not provider-recovery evidence. The configured OpenAI account still reports
`credit_balance_exhausted`, so neither the authority scheduler nor the complete
production suite is green.

This checkpoint does not mark the IP program complete, activate a legal or data
operation, or infer legal, security, pilot, or UAT acceptance.

## Immutable repository and CI lineage

| Gate | Exact evidence | Result |
| --- | --- | --- |
| Pull request | PR #225, validated head `973f71d283022d01ae008f1a79dd1ea5763ae074`; merge commit `8d9654bbe556ad4fa24caf64578ac9cf55343a0e` has the same tree `337e1a898d9b6b65fbe6cade155811633090cb33` | passed |
| PR-head CI | [CI 31801650057](https://github.com/mishrasanjeev/caseops/actions/runs/31801650057), [Security 31801650072](https://github.com/mishrasanjeev/caseops/actions/runs/31801650072), and [CodeQL 31801649992](https://github.com/mishrasanjeev/caseops/actions/runs/31801649992) | passed |
| Codex-review workflow | [Run 31805558827](https://github.com/mishrasanjeev/caseops/actions/runs/31805558827) completed green at the OpenAI-key guard; checkout, actual review, and feedback steps were skipped | not review evidence |
| Exact-main CI | [CI 31805582426](https://github.com/mishrasanjeev/caseops/actions/runs/31805582426), [Security 31805582335](https://github.com/mishrasanjeev/caseops/actions/runs/31805582335), and [CodeQL 31805582374](https://github.com/mishrasanjeev/caseops/actions/runs/31805582374) on exact `8d9654b` | passed |
| Canonical refs | local `main`, local `origin/main`, and remote `refs/heads/main` | all resolve to exact `8d9654b` |

The exact-main CI passed all ten API coverage shards and aggregate coverage,
Ruff and repository-control validators, PostgreSQL plus pgvector, web
typecheck/Vitest/build, and the Playwright app suite.

## Exact deployed identity

| Boundary | Exact evidence | Result |
| --- | --- | --- |
| API build | Cloud Build `c94dbf02-4418-4b1f-b15a-07e20942494c` | succeeded |
| Web build | Cloud Build `add05d4e-25bc-4d5c-abe7-e471685c88f3` | succeeded |
| Migration | `caseops-migrate-job-5zsdl`, exact API digest, `alembic upgrade head`; `2026-08-14T13:43:17.902420Z` to `13:43:36.078310Z` | succeeded in 18.17 seconds |
| API | `caseops-api-00292-sr5`, 100% traffic, release SHA `8d9654b`, digest `sha256:de2ce8390e727d7c612a21829d1a6c636f1efdb3c619e4515d5d5c194ce79629` | serving |
| Web | `caseops-web-00270-z4k`, 100% traffic, release SHA `8d9654b`, digest `sha256:b4f42ab054b98f4a99288d3d8737b39ea636cda393c08a0ff145fa4987f0b8dd` | serving |
| Public availability | `https://api.caseops.ai/api/health` returned `{"status":"ok"}`; `https://caseops.ai/` returned HTTP 200 with TLS verification result 0 | passed availability only |

`CASEOPS_AUTO_MIGRATE=false`. The production API environment does not set
`CASEOPS_IP_RULE_GOVERNANCE_ENABLED`, so that separate default-false legal-rule
rollout remains disabled. No provider switch, filing, fee, payment, external
message, retention action, export, purge, offboarding, or restore is inferred.

## Scheduler containment and audit

The pre-release execution `caseops-extract-authority-metadata-wv2b7` was
cancelled after exhausted-credit errors caused a long per-document sweep. The
scheduler was paused before the containment release. The canonical inventory
now owns the paused state and a 43,200-second timeout, while the other five
recurring schedulers remain enabled.

After deployment, the exact command below passed all six configuration rows:

```powershell
python scripts/scheduler_inventory.py audit `
  --project perfect-period-305406 `
  --region asia-south1 `
  --image asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:de2ce8390e727d7c612a21829d1a6c636f1efdb3c619e4515d5d5c194ce79629
```

The authority row reported desired/actual `PAUSED`, timeout `43200`, exact image,
and `scheduler_delivery=not_required_paused`. The five desired-enabled rows
reported matching identity, cadence, timezone, target, timeout, exact image,
and successful delivery evidence. A post-release natural reminder execution,
`caseops-reminders-job-5xv29`, succeeded at `2026-08-14T14:15:17.877027Z`.

Passing a bare digest to this command is invalid because `--image` expects the
full Artifact Registry reference; that invocation reported six apparent image
drifts even though each returned row displayed the correct digest. The
full-reference command above is the resolving audit and returned `result: pass`.

## Strict provider canary and durable error evidence

Execution `caseops-extract-authority-metadata-sh7jg` used the exact API image,
one task, `maxRetries=0`, timeout `43200`, and:

```text
python -m caseops_api.scripts.extract_authority_metadata --provider-canary
```

It selected one eligible document, submitted exactly one OpenAI request, and
received HTTP 429 with `credit_balance_exhausted` / "You have no credits
remaining." There was no SDK retry. The bounded drain line recorded
`submitted=1`, `in_flight=0`, and `unsubmitted=0`; the terminal counters were
`processed=1 submitted=1 updated=0 no_text=0 llm_err=1 quota_exhausted=1`, and
the container exited with the dedicated quota code `3`.

A later exact-image, read-only database inspection execution,
`caseops-extract-authority-metadata-pt89c`, confirmed durable `ModelRun`
`603cc662-d17f-47c6-8877-b13add0add04` with purpose `metadata_extract`, status
`error`, provider/model `openai/gpt-5-mini`, and the sanitized quota error at
`2026-08-14T13:53:46.832031Z`. That inspection's success is not a provider
success. An earlier malformed quoting attempt, execution
`caseops-extract-authority-metadata-rwhw4`, failed with a Python `SyntaxError`
before querying; neither inspection execution changes the failed-canary result.
Operators must not interpret whichever inspection appears as the latest job
execution as provider recovery.

## Exact production workflow

[Production workflow 31805582341](https://github.com/mishrasanjeev/caseops/actions/runs/31805582341)
verified the exact serving release and completed with:

- RAM/IP: `69 passed, 3 failed, 4 skipped` across 76 tests.
- Notice: `2 passed` (setup plus the full Notice workflow).
- All four dated 14 August bulk-import scenarios and the case-tracking canary
  passed.
- The only failures were the three live recommendation/citation checks that
  received the known OpenAI quota HTTP 503 behavior:
  `ram-batch-2026-04-26-prod.spec.ts:1170`,
  `recommendations-grounding-2026-04-29-prod.spec.ts:170`, and
  `recommendations-grounding-2026-04-29-prod.spec.ts:436`.

The production workflow therefore remains red. The typed no-output/fail-closed
behavior is correct containment, but it does not satisfy the complete-release
gate.

## Required next actions and safe fallback

1. Keep `caseops-extract-authority-metadata-daily` `PAUSED`; do not directly
   resume it.
2. The production AI provider/account operator must restore usable credits for
   the configured CaseOps OpenAI project. Then rerun the unchanged strict
   one-document provider canary and require an explicit provider-completed
   result plus its durable `ModelRun` evidence.
3. Only after that evidence, review a version-controlled scheduler-inventory
   change from `PAUSED` to `ENABLED`, reconcile it, and repeat the six-row audit.
4. Rerun the unchanged complete RAM/IP and Notice production workflow against
   the exact serving release. Do not hide, skip, or broaden the three quota
   assertions.
5. Continue independent repository-controlled IP work. Overall status remains
   `PROGRAM INCOMPLETE`; policy, legal/privacy/security, recovery, provider,
   pilot/UAT, and later-slice gates remain pending or blocked.
