# IPLF-027A production release attempt - 2026-08-13

## Verdict

The IPLF-027A shared reliability and inert workflow foundation is merged,
deployed, and independently exercised on the exact production revision
`0ad7a43de3d136e9991191d29cc8feeb75602443`. The capacity repair needed to
make the production evidence trustworthy is also deployed: API container
concurrency remains safely at `1`, while both the service-wide and
revision-level scale ceilings are `20`.

The complete exact-release production workflow is not green. Workflow
`31661191199` completed with 65 RAM/IP tests passed, 4 failed, and 3
documented conditional skips; the independently continued Notice phase passed
2 tests. The four failures are three live-recommendation 503 responses caused
by the configured production OpenAI project's exhausted quota and one
case-tracking-provider health gate reporting HTTP 409. They are not waived or
converted into skips. IPLF-027A therefore remains
`implemented / passed / blocked / pending`, not `deployment_verified`, and
the program remains `PROGRAM INCOMPLETE`.

The two IPLF-027A runtime controls remain absent/default-false in production:
`CASEOPS_DOMAIN_OUTBOX_CONSUMERS_ENABLED=false` and
`CASEOPS_IP_WORKFLOW_COMMANDS_ENABLED=false`. No new legal workflow command,
outbox consumer, provider change, filing, payment, external delivery, or other
real-world legal effect was activated. Production verification used synthetic
QA tenants and records only.

## Released lineage and independent controls

| Control | Exact result |
|---|---|
| Foundation implementation | PR #212, head `10dac4d3bfaecfc4c5a2c021cc8a5a47c4ca6164`, merged as `f64386bdf77a7459897222b33a5a0ecc1d6100f4` |
| Continue Notice after RAM failure | PR #213, merged as `409edb497450d3d3f971b447c67394e8772d96a6` |
| Service-wide scale headroom | PR #214, merged as `2a66a56d32b4b096027a02f409d1f142dd298af1` |
| Revision-level scale headroom | PR #215, merged as `0ad7a43de3d136e9991191d29cc8feeb75602443` |
| PR #215 CI | `31658664742`, passed: API lint/coverage, PostgreSQL + pgvector, web typecheck/Vitest/build, Playwright app suite |
| PR #215 Security | `31658664725`, passed |
| PR #215 CodeQL | `31658664707`, passed |
| PR #215 automated review | `31661186206`, passed |
| Exact-main CI | `31661191219`, passed: API lint/coverage, PostgreSQL + pgvector, web typecheck/Vitest/build, and Playwright app suite |
| Exact-main Security / CodeQL | `31661191220` / `31661191204`, both passed |

PR #213 changes the production verifier so the Notice suite uses `if:
always()` and produces evidence even if RAM/IP has a real failure. PRs #214 and
#215 correct the actual deployment boundary: Cloud Run's service `maxScale`
and immutable per-revision `max-instances` must both leave headroom. The
deployment intentionally does not increase `containerConcurrency`, because
the prior synchronous API incident established `1` as the safe bound.

## Exact production deployment

| Control | Exact result |
|---|---|
| Canonical release | `0ad7a43de3d136e9991191d29cc8feeb75602443` |
| API build | Cloud Build `e2d0a7cb-0f49-470d-bc01-aae23a179f41`, tag `0ad7a43` |
| API immutable image | `sha256:9b67291a5f369f87e9c215ba9de17b5e7816241a211ce705112ff12a9dbcabce` |
| Web build | Cloud Build `627c60de-05b4-485d-8f69-7c939c74f1d0`, tag `0ad7a43` |
| Web immutable image | `sha256:f89c07415347e63c57c6da01cdb7142d7d4247eb8da3cac37f202803f3e5ea06` |
| Migration | `caseops-migrate-job-wcwlg`, `succeededCount=1`, completed 2026-08-13T02:39:14Z on the exact API digest |
| API revision | `caseops-api-00285-skg`, 100% traffic, API image/tag and `/api/build` SHA match release |
| Web revision | `caseops-web-00263-sx6`, 100% traffic, image/tag match release |
| API capacity | concurrency `1`; service max scale `20`; revision max instances `20` |
| Scheduler inventory | All six canonical scheduler bindings passed identity, target, cadence, and exact API-digest verification |
| Public identity | `/api/health` returned `{"status":"ok"}`; `/api/build` returned the full release SHA and API revision |

The canonical deploy wrapper timed out locally while the submitted Cloud Build
continued. The remaining migration, scheduler, and revision-verification steps
were resumed exactly once against the same clean source SHA; no duplicate final
build was submitted. The revisions above are the verified serving revisions.

## Exact production verification

Push workflow `31661191199` checked out the exact serving SHA and recorded the
serving API and web revisions before running production-safe Playwright. The
relevant successful assertions were:

- `tests/e2e/ram-2026-07-15-prod.spec.ts:728` passed: a terminal Matter
  rejects stale writes, suppresses operational children, and only reopens to
  Intake.
- `tests/e2e/ram-2026-08-11-bugs.spec.ts:572` passed: disposal is atomic,
  stale writes and child resurrection fail closed, and a controlled reopen
  persists only to Intake.
- `tests/e2e/ram-2026-08-11-prod.spec.ts:334` passed at 360 px: IPLF-026B
  independent IP-access preview, grant, revoke, and persistence proof.
- `tests/e2e/notice-module-prod.spec.ts:76` passed: the synthetic QA tenant
  uploads received notices, reply documents, and sent notices, then filters
  them.

This is material improvement over the earlier capacity-starved run: neither
`Rate exceeded` nor `no available instance` occurred, and both lifecycle
regressions completed successfully. It does not make the complete release gate
green.

## Open blockers, safe fallback, and next work

1. **`IPLF-027A-PROD-GATE-31661191199` -- OpenAI quota.** Three
   recommendation assertions failed with HTTP 503; one captured the typed
   `llm_quota_exhausted` response and confirmed that no output was saved. The
   production AI provider/account operator must restore usable quota or credits
   for the configured CaseOps OpenAI project and verify its configuration.
   Keep the sanitized 503 and no-output behavior; do not substitute synthetic
   output, weaken assertions, or change providers/cost ownership to obtain a
   green run.
2. **`IPLF-027A-PROD-GATE-31661191199` -- Case-tracking provider.**
   `tests/e2e/ram-2026-08-05-prod.spec.ts:358` observed a red provider health
   state (HTTP 409) and requires the authorized provider operator's review and
   replay decision. Do not invoke a real-provider replay or bypass the
   fail-closed gate without that authority.
3. **IPLF-027B activation.** An approved rollout and operator policy is still
   required before enabling either dark control or exposing legal workflow
   commands. This is independent of the infrastructure repair.

After the two external production gates are resolved, Engineering/QA must rerun
the unchanged complete RAM/IP and Notice workflow against the exact serving
release. Named legal, security, provider, pilot, and UAT acceptance -- and the
M0 human program lock -- remain outstanding and are not inferred by this
technical evidence.
