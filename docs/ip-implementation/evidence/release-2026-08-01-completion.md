# IP Law Firm PRD implementation-tail completion record

> **Governance supersession (30 August 2026):** Historical references below to generic human/pilot/UAT acceptance are not active implementation or release gates. Machine-validated contracts, exact-release checks, and dated production E2E close repository work. Human authority remains scoped only to an exact legally, financially, externally, or destructively effectful product action.

**Evidence date:** 1 August 2026  
**Repository:** CaseOps  
**Canonical control:** `docs/ip-implementation/PROGRAM_MANIFEST.yaml`  
**Scope:** the five implementation tails previously recorded for `IPLF-007B`, `IPLF-039B`, `IPLF-039C`, `IPLF-039E`, and `IPLF-039F`

## Result

All repository-controlled implementation work explicitly left open in the 1 August remaining-slices release has now been implemented. The result includes persistence, constraints, tenant and capability enforcement, service commands, API contracts, regenerated OpenAPI types, responsive user controls, audit evidence, migrations, focused regressions, and a dated browser journey.

This record does not claim that the complete 436-requirement, 68-journey M0-M10 program is finished. The canonical manifest still contains undecomposed and `not_started` epics requiring legal/source fixtures, provider capability facts, retention/export/recovery controls, machine-validated domain contracts, implementation, tests, and exact-release evidence. Those are program dependencies, not hidden code TODOs inside the five slices closed here.

The fixed “seven consecutive natural scheduler days” release wait remains removed by the product-owner instruction of 1 August 2026. Exact revision, configuration/IAM verification, bounded canaries, health checks, and dated production E2E are the release evidence. Natural scheduler executions remain ongoing SLO evidence, not an artificial time gate.

## Delivered behavior

### IPLF-007B — one durable notification dispatcher

- `notification_delivery_intents` is the single delivery owner for the converged hearing-reminder path.
- The scheduler creates durable intents and the same worker invocation drains eligible intents; direct legacy provider delivery is no longer the scheduled path.
- Email delivery is queued only when the server-side rollback flag, provider configuration, destination checks, permission checks, and suppression checks all permit it.
- Provider submission is idempotent and records the CaseOps intent correlation in SendGrid custom arguments.
- Provider-accepted and recipient-delivered are separate states. Existing signature-verified/idempotent SendGrid webhook handling now updates durable intent state and append-only delivery events.
- Bounce, drop, spam, unsubscribe, suppression, terminal retry exhaustion, or a disabled provider path creates exactly one in-app fallback.
- Dual-read comparison records canonical/fallback state; there is never a dual-send mode.
- Rollback is immediate through `CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`; queued evidence is retained and the in-app fallback path remains operational.
- Production provider enablement remains an action-scoped operational approval because it sends real external messages. The implementation is complete while the safe production default stays disabled.

### IPLF-039B — review-gated evidence intake over existing owners

- Added company-scoped `ip_evidence_candidates` with stable source identity, content/source fingerprint, evidence type, suggested link effect, review state, duplicate relationship, safe display metadata, reviewer, and timestamps.
- Discovery composes existing Matter-linked `CompanyNotice`, `Communication`, `MatterAttachment`, and Google Drive candidate records. It does not copy email bodies, document bytes, OAuth credentials, provider envelopes, or notice workflow state.
- Same-scan and previously stored duplicates are detected by fingerprint and presented as reviewable duplicates; they never auto-link or disappear silently.
- Every candidate is re-authorized and revalidated against the canonical source link at review time.
- Accepting a legal-notice candidate reuses the existing `CompanyNotice` and creates the company-matched IP link. `/app/notices` remains the sole accepted notice and reply-workflow owner.
- Rejecting or accepting writes an IP audit event. No inbound item can confirm a deadline, filing, payment, service, instruction, or other legal state by itself.
- The responsive `/app/ip` workspace exposes discovery, evidence source/status, and Accept/Reject controls.

### IPLF-039C — deadline continuity, leave and deactivation

- `ip_deadline_coverages` now has a monotonic `reassignment_version` and `updated_at` concurrency evidence.
- Bulk reassignment locks all affected coverage rows, validates optional expected versions, validates the active same-company replacement, transfers both primary and backup occurrences, queues the existing calendar projection for the replacement where configured, and records an audit event in one transaction.
- Explicit bulk transfer supports approved leave/team-change workflows without deactivating the source membership.
- Employee offboarding preview includes IP deadline coverage. Commit transfers the coverage in the same transaction before account deactivation and refuses the existing access/ethical-wall/policy blockers.
- Existing Matter deadlines and `CalendarEventSync` remain authoritative; no `ip_deadlines` or second external-calendar record was introduced by this slice.
- The docket-control service remains the reproducible operational report, including uncovered deadlines, calendar-projection gaps, inactive owners, readiness, open incidents, and currency totals.
- `/app/ip` displays coverage state/version and exposes version-aware bulk transfer controls that wrap and remain visible at 360px.

### IPLF-039E — title conflicts and related-right obligations

- Effective-dated title records retain ownership, assignment, licence, encumbrance, security, evidence, related docket, and recordal state.
- Conflict output distinguishes overlapping parties, competing title, and licence/encumbrance conflicts. A docket cannot relate a title entry to itself, and the related docket is permission checked.
- Added `ip_related_right_obligations` for renewal, royalty, recordal, consent, quality-control, termination, and other obligations.
- Each obligation has an evidence reference, active same-company owner, optional due date and existing Matter deadline, status, completion evidence, completion actor/time, and audit history.
- Completion requires an expected open state and evidence. It cannot be inferred from a task, invoice, registry candidate, or uploaded document.
- `/app/ip` supports creation and evidence-backed completion without adding a second task, deadline, contract, or billing lifecycle.

### IPLF-039F — one accounting owner and deterministic reconciliation

- `ip_cost_items` retains the immutable operational cost fact in original minor units/currency and can link uniquely to an existing Matter invoice, invoice line, or time entry.
- Link type and ID are an all-or-none validated pair. Cross-Matter and missing billing links fail closed.
- Reconciliation reads the canonical existing Matter billing amount and persists `matched`, `mismatch`, `missing`, or `unlinked`, the canonical amount, difference, reviewer, and time.
- The reconciliation report contains every IP cost item, per-row evidence/canonical amounts, status counts, `accounting_owner=matter_billing`, and a deterministic SHA-256 checksum suitable for export comparison.
- No invoice, time-entry, payment, write-off, or outside-counsel-spend lifecycle was duplicated.
- `/app/ip` exposes optional billing linkage, reconciliation status, and a reconciliation action. Grouped buttons are full-width on narrow screens and wrap on larger screens.

## Schema and migration

Migration `20260801_0006_ip_operations_completion.py` is an additive expand migration from `20260801_0005`.

It creates:

- `ip_evidence_candidates`;
- `ip_related_right_obligations`.

It extends:

- `ip_deadline_coverages` with reassignment version/update time;
- `ip_cost_items` with reconciliation status, canonical amount, difference, reviewer, and time.

Company-matched composite foreign keys are used for IP docket and reviewer/owner relationships where the repository model supports them. Leading indexes cover the new foreign-key and operational query paths. Downgrade is structurally supported before tenant data exists; after legal evidence exists, rollback must disable behavior and use a forward repair rather than destructively dropping evidence.

## Data-class registration for this release

| Data class | Purpose and owner | Sensitivity | Retention / hold / export / purge | Restore and projections |
| --- | --- | --- | --- | --- |
| `ip_evidence_candidates` | Review projection over existing Matter notice, communication, attachment, and Drive owners | Confidential legal metadata; safe labels only, no copied body/bytes/secrets | Inherits tenant legal-record policy; company/client/record/custodian holds cover the row and canonical source; export contains IDs, hashes, decision and safe metadata; governed tenant purge deletes with the company after hold checks | Database restore; canonical source must still exist and access is rechecked; no search copy introduced |
| `ip_related_right_obligations` | IP-specific obligation fact linked to existing owner/deadline/title | Confidential legal and commercial metadata | Inherits legal-record/contract-term policy; hold and export follow docket/client scope; purge only through governed company/record operation | Database restore; Matter deadline/calendar remain separate projections and cannot recreate completion |
| `ip_deadline_coverages.reassignment_*` | Concurrency and reassignment evidence on operational coverage | Confidential staffing metadata | Same disposition as coverage; actor history is also retained in audit; export includes old/new/version evidence; purge follows governed company operation | Database restore; calendar sync is rebuildable from canonical coverage but cannot change legal state |
| `ip_cost_items.reconciliation_*` | Comparison to canonical Matter billing | Confidential financial metadata | Same retention/hold/export scope as the IP cost and linked Matter billing evidence; purge follows both owners’ governed rules | Database restore; report is recomputable and checksum detects drift; it never recreates invoice/payment state |
| notification intent provider events/status | Durable external-delivery evidence | Restricted destination/provider metadata, redacted in operator surfaces | Existing notification evidence policy and webhook-event retention; held Matter/docket evidence blocks destructive cleanup; export is permission scoped | Database restore before dispatcher enablement; old workers are fenced and pending effects previewed to prevent duplicate sends |

The broader automated data-map/hold/export/purge and recovery program remains governed by `IPLF-028`/M2 and must pass before M2 exit. This table registers the newly introduced classes for the current additive release; it is not a false claim that M2 data governance is complete.

## Security and ownership invariants

- Every route requires an IP capability (`ip:view`, `ip:write`, `ip:review`, or `ip:finance`) and uses the current company session context.
- Linked Matter access is checked before exposing or mutating an IP docket.
- Candidate review rechecks that the source remains linked; stale or removed evidence cannot be accepted.
- Replacement memberships and obligation owners must be active and belong to the same company.
- Bulk reassignment uses parent-row locks and optimistic versions; an offboarding transaction does not deactivate first and repair ownership later.
- Cost reconciliation never trusts a client-supplied canonical amount.
- Webhook signature, replay, provider/account binding, and event idempotency continue to be enforced by the existing notification route.
- No secret, message body, attachment content, destination address, or provider credential is written to audit metadata by these changes.

## Verification evidence

### Focused backend and static gates

```text
uv run ruff check src tests
PASS

uv run pytest tests/test_legalworkspace_offboarding.py tests/test_ip_prd_slices.py tests/test_durable_workflows.py -q --tb=short
27 passed

uv run python -m compileall -q src
PASS

uv run alembic heads
20260801_0006 (head)
```

The end-to-end backend test proves, in one tenant-scoped journey: versioned coverage transfer, notice/Communication/attachment discovery, same-hash duplicate handling, accepted notice linkage, evidence-backed obligation creation/completion, canonical time-entry cost reconciliation, deterministic report checksum, and persisted final state. The durable-notification test proves one provider call, provider-accepted state, webhook-delivered state, and no fallback or duplicate in-app effect on success. Existing tests prove the disabled/suppressed fallback path.

### Frontend and generated contract

```text
npm --prefix apps/web test -- app/app/ip/page.test.tsx
3 passed

npm --prefix apps/web run typecheck
PASS

npm --prefix apps/web run build
PASS (production build, /app/ip emitted)

scripts/dump_openapi.py + openapi-typescript 7.13.0
PASS; apps/web/lib/api/openapi-types.ts regenerated
```

The component regression sets a 360px viewport and asserts that Discover, Accept, Reject, Transfer, Add obligation, and Reconcile controls are user-visible.

### Dated browser journey

```text
npx playwright test --config playwright.app.config.ts tests/e2e/ram-2026-08-01-bugs.spec.ts --project app-chromium
2 passed
```

The second dated journey bootstraps a clean tenant, creates an existing Matter, Communication and Matter deadline, creates a linked IP docket and coverage through public APIs, signs in through the browser, and at 360px discovers/accepts evidence, creates a related-right obligation, creates/reconciles a cost item, and checks every grouped action remains inside the viewport.

### Exact release evidence

The release gates completed on 2 August 2026:

| Gate | Exact evidence | Result |
| --- | --- | --- |
| Canonical application commit | `686256796422507ccbc195428faf5d02f0e190d2` on `main` | Passed |
| Full CI and staging | GitHub Actions run `30712004305`: four API coverage shards, aggregate per-area coverage, Ruff, PostgreSQL/pgvector, web typecheck/Vitest/build, Playwright app suite, and staging deploy | Passed |
| Security | GitHub Actions run `30712004299` | Passed |
| CodeQL | GitHub Actions run `30712004306` | Passed |
| API image build | Cloud Build `66799663-55d5-456e-9bf8-a61fb4b16dce`; tag `6862567`; immutable digest `sha256:d49d8891b5b40a3fda0114fe8845937223e929ab6c2f5c52ee5077e986c6fb8e` | Passed |
| Web image build | Cloud Build `8af65037-9ff9-43ba-b3d6-a329fbdbfa1f`; tag `6862567` | Passed |
| Migration | Execution `caseops-migrate-job-svl9h`; Alembic head `20260801_0006` | Passed |
| Scheduler/job convergence | Six required jobs pinned to the immutable API digest; targets, cadence, time zones, OAuth identity, enabled state, and invoker configuration verified; superseded midnight poll paused | Passed |
| API production | Revision `caseops-api-00221-sf6`, 100% traffic | Passed |
| Web production | Revision `caseops-web-00201-n5x`, 100% traffic | Passed |
| Health and malware guard | `https://api.caseops.ai/api/health` returned `{"status":"ok"}`; ClamAV sidecar present | Passed |
| Authenticated production E2E | GitHub Actions run `30725589982` from acceptance-spec commit `0b8f9aa61eef0b0c5ee6de0806ae81f1b13e4f5b`: 55-test ram batch, dated IP desktop/360px journey, and notice-module suite | Passed |

The first hosted CI attempt correctly found two conflicting disabled-provider fallback expectations. The implementation was reconciled so blocked external rows stay content-free, rule-owned external-only fallbacks remain generic, and direct durable IP fallbacks retain caller-supplied in-app copy. All three paths pass together. The first post-deploy IP proof also correctly found that the dedicated QA tenant had no IP docket; the dated spec now creates one through the real UI only when empty and then validates the operational workspace. Neither failure was waived or converted into a skip.

With these machine gates complete, `IPLF-007B`, `IPLF-039B`, `IPLF-039C`, `IPLF-039E`, and `IPLF-039F` are `deployment_verified`; no additional implementation signoff is pending.

## Rollback

- External notification dispatch: turn off `CASEOPS_NOTIFICATION_EXTERNAL_DELIVERY_ENABLED`; intents and provider evidence remain, and fallback remains available.
- Web/API behavior: return traffic to the previous compatible revision. The migration is expand-only, so the old application ignores new tables/columns.
- Evidence/coverage/title/cost behavior: hide actions by server capability/rollback deployment; do not delete accepted evidence, obligation completion, reassignment history, or reconciliation results.
- Workers: run only one revision/dispatcher owner; fence the replaced worker before replaying queued intents.
- Database: prefer forward repair after any tenant data is written. Do not downgrade away legal or delivery evidence.

## Completion boundary

There are no deferred repository TODOs for the five implementation tails named in this record. External-provider production activation is deliberately disabled until the separately authorized real-message switch; that exact external communication boundary does not create a generic pilot/legal/UAT signoff. The final documentation commit is released through the same exact-revision pipeline; it does not alter the application behavior proven above.

The rest of the master PRD is not silently waived. The manifest remains the truthful source for the undecomposed M0/M2-M10 epics and all 436 atomic requirement rows. A future program claim must map those rows and journeys to verified evidence; this release does not inflate five completed slices into a claim that the multi-year full-IP platform is complete.
