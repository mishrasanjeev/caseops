# Async Provider Summary Integration And Browser Acceptance

Date: 2026-09-10. This is scoped evidence, not a canonical closure ledger.

Target: `C:/Projects/CaseOps/caseops/.worktrees/codex-sep08-acceptance-repair-20260908`.
The integration was validated on dirty HEAD
`5145fb3a4b51b26af116220ff10a7389bde6324d`, not a released commit.
No commit, push, production mutation or generated-contract edit was performed.

## Scope And Provenance

This preserves the reviewed handoff at
`C:/tmp/caseops-summary-integration-20260910/HANDOFF.md` and extends it with
the dated browser/worker gate status. The original isolated patch handoff is
`docs/ip-implementation/evidence/provider-summary-closure-2026-09-09.md` in
the `codex-cold-start-closure-20260909` worktree. All eight original frozen
handoff hashes matched before integration.

Read workspace and target AGENTS, bug-fixing, caseops-prd-execution,
enterprise-hardening and strict-quality-review skills, canonical PRD,
coverage, backlog, strict ledgers, CODEX and program context. Product mapping:
J08/M08, MOD-TS-006/007, US-022/023/024/025/057, FT-078-082 and SEC-026.
This evidence does not close those complete journeys.

Exactly seven files changed in the prior source integration:

1. `apps/api/src/caseops_api/services/case_tracking.py`
2. `apps/api/src/caseops_api/services/case_tracking_summary.py` (new)
3. `apps/api/src/caseops_api/services/domain_outbox.py`
4. `apps/api/src/caseops_api/services/llm.py`
5. `apps/api/src/caseops_api/workers/document_processor.py`
6. `apps/api/tests/test_case_tracking_summary.py` (new)
7. `docs/ip-implementation/IP_EVENT_CATALOG.yaml` (one event)

`integration-source-verification.json` in the external evidence directory
records tested hashes for all seven files. AST comparison proved the parent's
`case_tracking.py` unchanged outside the summary helpers and obsolete imports;
structural catalog comparison proved only the one owned event was added.
Parent provider recovery, rollout, lease, precision fixture, frontend,
September 10 intake, catalogue and non-CNR changes were preserved. Parent was
notified when source became stable for its separate PostgreSQL replacement.

Subsequent parent integration intentionally supersedes the original catalog
hash: the event owner is the existing canonical `court-tracking`, not the
unrecognized `case-tracking`. Parent retained the full API failures, corrected
the owner and added an exact-owner regression. That correction is preserved.
The later parent hearing merge also supersedes the whole-file
`case_tracking.py` hash while preserving the summary integration hunks.
The old seven hashes describe the original tested snapshot, not current D.

## Safety Boundaries

- Source updates immediately persist the permitted fallback and atomically
  enqueue identifiers, hashes, actor/token and locked lifecycle identity plus
  the authoritative no-paid boolean. Snapshot writes do not invoke an LLM.
- Summary outbox and effect leases commit before preflight; expired claims
  recover with a new fence. Claims filter only the summary event.
- Before and after the model call, current tenant/actor/token, capability,
  Matter ACL/lifecycle, bookmark, tracked/source identity and model policy
  are checked. Database transactions are released during provider I/O.
- Completed usage is durably accounted before publication authorization,
  including malformed and discarded responses. Rejected text is not attached.
- Summary objects reject additional properties recursively. Verified source
  URLs are attached locally, not supplied to the model. Provider attempts are
  bounded to 45 seconds within a five-minute lease and three outbox attempts.
- Both normal and skip-maintenance document-worker paths drain summaries.

The imported finalization reproduced two PostgreSQL lock failures after
successful setup and usage accounting. The integration uses NOWAIT publication
locks and NO KEY UPDATE for authority parents. Only SQLSTATE 55P03/40P01 is
retryable; partial locks roll back and existing 30/60-second, three-attempt
outbox bounds apply. Real Company/membership contention tests prove released
Matter locks and subsequent disposal. Injected SQLSTATE tests prove error
classification, not a real 40P01 reproduction. Unknown errors propagate.

## Completed Focused Verification

`integration-focused-05`: **196 passed, zero failures/skips, exit 0**, 330.20s.
All 588 setup/call/teardown reports and the completion event are retained.
JUnit identities reconcile one-to-one with the nonempty selected inventory.

| Module | Passed |
| --- | ---: |
| test_case_tracking_summary.py | 61 |
| test_case_tracking.py | 28 |
| test_document_worker.py | 7 |
| test_llm_provider.py | 18 |
| test_shared_reliability.py | 14 |
| test_20260909_provider_recovery.py | 13 |
| test_20260909_provider_refresh_protocol.py | 8 |
| test_provider_recovery_postgres.py | 16 |
| test_provider_rollout_guard.py | 20 |
| test_20260909_provider_deadline.py | 11 |

There are 29 PostgreSQL-backed summary identities and 16 provider PostgreSQL
identities. Remaining tests use SQLite or isolated adapters/workers/contracts.
Scoped Ruff and git diff checks passed. Final inspection found zero retained
`caseops_http_%` fixture databases/templates. This was not the full PG gate.

Invocation: `python -m pytest -n 0 -q --tb=short -p no:cacheprovider
-p tests.retained_results --junitxml=/output/integration-focused-05.xml`
with the ten modules above and
`CASEOPS_TEST_RESULT_JOURNAL=/output/integration-focused-05.jsonl`.

Retained evidence root: `C:/tmp/caseops-summary-integration-20260910`.
Exact inventory: `reconciliation-integration-focused-05.json`.
Results: `integration-focused-05.jsonl`, `.xml`, `.log`, `.exit`.
Source: `source-integration-focused-05.tar`, accompanying per-file manifest,
`integration-source-verification.json`, and final empty drift report.

Tools image ID:
`sha256:09d833f4e368065b410628495562e0bb96d83e8610393a127eee5e235069fc20`.
Frozen source archive SHA256:
`9c597e6a3daec667a047c828156f8de8aff5d0c0b64211f8703fcb4760bb2488`.
PostgreSQL image:
`pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`.
The tools image ran current frozen source via pinned PYTHONPATH, not its
historical package. Runner limits were 0.75 CPU/1536 MiB and independently
initialized PostgreSQL 0.25 CPU/512 MiB, combined 1 CPU/2 GiB, no extra swap.
Both used network=none, no ports and one owned Unix socket volume. Scratch
was executable; the pinned Temporal binary was verified outside scratch.
No shared database was used or cloned. All integration containers are stopped.

### Failed Attempts Preserved

- PG launch attempts 01-03 failed in isolated socket setup; diagnostics remain.
  Attempt 04 used a new empty volume and proved readiness on the default socket.
- Baseline 01/02 failed before pytest during migration connection: not tests.
- Baseline 03 completed with exactly two call failures and successful setup/
  teardown. Both full failures were inspected; each exact node passes in 05.
- Focused 04 named a nonexistent module, selected zero tests and exited 4:
  invalid invocation, not acceptance. Focused 05 verified every path first.

No old failure evidence was overwritten or retrospectively relabeled green.

## Dated Browser/Worker Gate

Requested spec: `tests/e2e/case-tracking-summary-2026-09-10.spec.ts`.
Status: **authored, typechecked and discovered; browser execution not run**.
Parent owns the full image build and integration stack. No duplicate image
build or full PostgreSQL run was started for this follow-up.

Required assertions: immediate source fallback visible before worker claim;
actual release-image document worker consumes the event; generated text,
`ai_summary`, ModelRun and consumer-effect linkage persist; reload and source
links retain the authorized source; repeat drain does not generate or spend
again; persisted QA and explicit no-paid events remain suppressed with no
external provider call or lifecycle mutation. Expected source/model response
must be frozen, and all regular browser traffic retains the no-paid marker.

Exactly seven follow-up files were changed:

1. `tests/e2e/case-tracking-summary-2026-09-10.spec.ts`
2. `apps/api/src/caseops_api/scripts/docker_acceptance_summary.py`
3. `apps/api/src/caseops_api/scripts/docker_acceptance_case_provider.py`
4. `apps/api/tests/test_docker_acceptance_summary.py`
5. `docker-compose.yml`
6. `scripts/verify-docker.ps1`
7. This evidence note.

Parent owns discovery in `playwright.app.config.ts`; the temporary summary
entry was removed before the parent added its own dated pattern. No summary
service, shared LLM, generated contract or canonical ledger was edited in
this follow-up. Parent's source-frozen API/PG containers were not modified.

### Fixture And Worker Contract

The local-only fixture CLI requires explicit opt-in, `e2e`, the isolated
`postgres/caseops` database, the existing local emulator URL and exact dummy
token, mock LLM/model and no LLM key. Seeding is limited to newly owned
`summaryacceptance-*` and `summarypersistent-*` Intake Matters. It admits the
source through `apply_snapshot` with the canonical CNR identity; it never
calls the summary consumer or manufactures generated rows/effects.

The positive source event represents an unattended synthetic admission, not
an HTTP request with its marker removed. Marked admission retains `true` in
the outbox payload. A separate persistent tenant is explicitly added to the
one-shot worker's blocked-company configuration. Every browser/API request
still carries `X-CaseOps-Automated-Test: no-paid-providers`.

The CLI prepares the frozen replay cassette and `execve`s the installed
`caseops-document-worker --once --skip-migrations --skip-maintenance
--summary-batch-size 25` executable. It does not substitute a consumer call.
Replay misses fail closed, with no inner-provider fallback. Frozen key:
`fb977e47e7dde573278d134ae98d89580cb2b6dbbcb847ac406d13d6600e20db`.
Expected response, source text and key are literal reviewed fixture data;
they are not derived from the eventual generated result.

The dated test verifies API/worker image equality, serving revision and
consumer/worker file hashes against its frozen repository. It pauses only
the named Compose project's worker before admission, observes the immediate
fallback, and launches a same-image one-shot worker capped at 1 CPU/2 GiB.
It asserts actual outbox/effect/ModelRun linkage, exact mock token counts,
both suppression reasons, unchanged provider-operation/spend counts through
generation and replay, and unchanged Matter lifecycle throughout. Reloads
at widths 393/768/1280 retain the summary and authenticated source proxy.
API and browser-click source downloads must match the frozen bytes. Those
downloads use only the local emulator; they are not paid-provider probes.

The stage journal is append-only and records a completion event only after
all acceptance assertions pass. Screenshots, source bytes, worker stdout/
stderr and final states are retained. Finally restores the original worker
running state and stops any surviving one-shot worker without deleting
fixture tenants or failure evidence.

### Follow-Up Focused Results

`integration-browserfixture-02`: **127 passed, 29 deselected, zero failures
or skips, exit 0**, 154.66s. All 381 setup/call/teardown reports and the
completion event reconcile with JUnit. The 29 deselections are PostgreSQL
summary identities, deliberately excluded from this offline source gate;
the parent owns the merged provider/summary/hearing PostgreSQL replacement.
These 127 tests overlap the original 196 and must not be added as unique tests.

| Module | Passed |
| --- | ---: |
| test_docker_acceptance_summary.py | 19 |
| test_case_tracking_summary.py | 32 |
| test_case_tracking.py | 28 |
| test_document_worker.py | 7 |
| test_llm_cassette.py | 8 |
| test_ip_arch_ops_contract.py | 33 |

The new tests cover fail-closed runtime admission, frozen prompt drift,
strict cassette output and replay miss, installed worker executable launch,
canonical source admission, generation through the worker CLI, marked and
configured-tenant suppression before adapter construction, replay, unchanged
lifecycle, and the exact authenticated emulator source response.

This used the same tools image ID as the original integration, a new frozen
full repository snapshot and pinned PYTHONPATH, with network=none,
1 CPU/2 GiB and no PostgreSQL container/database. No shared DB was accessed.
Source archive SHA256:
`7c066de59b63cf6ef3ac543139d28c0bfccffd14afae8b1b35c5cfea666ed19d`.
Artifacts under the same external evidence root:
`integration-browserfixture-02.{jsonl,xml,log,exit}`,
`reconciliation-integration-browserfixture-02.json`, frozen source archive
and per-file manifest. This snapshot contains the parent's catalog owner
correction but precedes its later hearing merge. It is not verification of
that later combined source. Later spec logging/network changes were
typechecked separately; the browser itself remains unverified.

Attempt 01 completed with 92 passed and two call failures, both after
successful setup/teardown. Full structured details for both were inspected:
an invented fixture identity was canonically replaced during snapshot
admission, correctly causing `source_changed` suppression. The fixture was
corrected to use the canonical CNR identity; neither the source fence nor
the expected suppression reasons were weakened. Both exact failed nodes
pass in 02. Attempt 01's archive/results/reconciliation remain untouched.

Scoped Ruff passed. `tsc --project tsconfig.e2e.json` passed. Parent's Docker
Playwright config discovers exactly one summary test in `app-chromium`.
Compose configuration resolves the intended mock flags and network topology.
These are static/source checks, not a completed Docker browser journey.

### Parent Execution And Open Harness Boundaries

Parent should build the frozen candidate once with the new fixture module,
emulator endpoint and worker settings, then run the dated test in its
existing isolated stack using the environment established by
`verify-docker.ps1`:

```text
npx playwright test --config playwright.docker.config.ts --project=app-chromium case-tracking-summary-2026-09-10.spec.ts --workers=1 --retries=0
```

Do not repeat the full PG gate just to execute this command. A non-Docker
run explicitly skips and does not count as acceptance. Docker execution
without the fixture opt-in or exact local-only runtime must fail, not skip.

Acceptance sets `CASEOPS_DOCKER_INTERNAL_WORKER_NETWORK=true`; only the
worker belongs exclusively to the internal `worker-offline` network.
PostgreSQL, Valkey and the local emulator also retain their default network
for API access. API loopback publication is unchanged. If Docker's address
pools are exhausted, supply distinct free `-NetworkSubnet` and
`-WorkerNetworkSubnet` values to the parent's initial verify-docker launch.
No network pruning is authorized. Ordinary local Compose defaults remain
non-internal. The final multi-network stack has not been launched here.

A retained small network probe disproved the initial all-internal proposal:
this Docker Desktop did not publish the HTTP server's requested host port.
The probe container is stopped, its internal network retained, and full
diagnostics are in `internal-network-probe.md`. It was infrastructure
diagnostics, not a product failure or browser acceptance attempt.

The parent-owned `docker_acceptance_hearing_provider.py` initially intercepted
all `/api/partner/case/` paths before superclass delegation. Its owner was
notified to preserve/delegate the summary order-document endpoint before
the broad case branch; otherwise the download assertion will correctly fail
on case JSON. This follow-up did not modify that parent-owned file. The
source handler in the existing emulator must survive its separate adaptation.

## Gaps And Verdict

**Inconclusive for release/user-visible closure.** The 196-test result proves
focused source integration only. Full API/PG, rebuilt application/worker,
complete dated Docker browser, deployed-worker and production acceptance are
not established here. Parent owns those gates and canonical status updates.

Gemini's preexisting prompt-JSON plus validation path is not native strict
schema enforcement; it remains documented and outside this follow-up scope.
No shared Gemini/LLM change is authorized for the browser task. Quota
preflight is an estimate, not concurrent reservation. Unknown completion
usage is not invented. Authorized publication retries can generate/account
again within the three-attempt bound; no external exactly-once claim is made.
