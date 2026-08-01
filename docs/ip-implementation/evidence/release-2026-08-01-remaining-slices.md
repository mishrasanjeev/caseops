# IP Law Firm PRD remaining-slice implementation and release record

**Evidence date:** 1 August 2026
**Scope:** `IPLF-003A/B`, `IPLF-005A`, `IPLF-006A/B`, `IPLF-007A/B`, and `IPLF-039A/F`
**Product direction:** remove the fixed “seven consecutive days” scheduler-health release blocker and execute all independently safe work in one continuous delivery run
**Canonical control:** `docs/ip-implementation/PROGRAM_MANIFEST.yaml`

## Executive result

This release implements the trust-recovery source contract, privacy-preserving research outcomes, fail-closed statute verification, notification-intent evidence/fallback convergence, and the first operational trademark docket spanning existing Matter, CompanyNotice, deadline, calendar, billing, access, and lifecycle owners.

This is **not evidence that the complete M1-M10 PRD is delivered**. The master prompt is a multi-year program containing 436 requirements and 68 journeys. This release closes the currently implemented technical slices listed below; pilot UAT, legal/provider approvals, full external notification cutover, and the broader M2-M10 roadmap remain governed by the manifest.

## Approved release-gate change

The product owner explicitly removed the fixed requirement to wait for seven consecutive natural scheduler-health days. The replacement gate is immediate and evidence based:

1. verify the exact deployed scheduler/job image and revision;
2. verify Scheduler target, identity, IAM Invoker binding, timezone, and drift;
3. run bounded scheduler-to-job canaries for every required job;
4. retain natural runs as ongoing health/SLO evidence without imposing a fixed release-duration wait.

The PRD, manifest, generated views, and earlier IPLF-001B release evidence were updated consistently. This change does not weaken source, tenant, lifecycle, provider, legal, UAT, or deployed-revision gates.

## Delivered slices

### IPLF-003A — shared source action contract

- Added one typed `available | missing | unverified | blocked | quarantined` contract.
- Added authenticated open routing with a no-store/no-referrer redirect.
- Allows only CaseOps `/api/` paths or HTTPS official hosts; credentials, non-standard ports, insecure URLs, loopback targets, and unknown hosts fail closed.
- Does not server-fetch user URLs, avoiding SSRF and credential forwarding.

### IPLF-003B — source actions on user surfaces

- Research authority results serialize and render the shared action.
- Uploaded Matter File Q&A sources use authenticated Matter attachment downloads.
- Litigation-intelligence review sources show typed source state/action.
- Judge career and authority analytics use the same contract.
- Statute sections use the same contract and quarantine state.

### IPLF-005A — typed research outcomes and golden queries

- Added typed search outcomes and diagnostics to the authority search response.
- Added tenant-scoped search observations with result counts, latency, mode, filter presence, and unreadable-result omission counts.
- Stores only a normalized SHA-256 query fingerprint; raw legal queries are not persisted in telemetry.
- Added three deterministic IP golden-query fixtures and a standalone validator.

### IPLF-006A/B — fail-closed statute trust

- Added `unverified`, `verified_official`, `verified_licensed`, `quarantined`, and `retired` states.
- Added publisher, retrieval time, source hash, version, curator, verification time, quarantine time, and reason.
- Existing AI-generated (`haiku_generated`) statutory text is quarantined by migration without deleting audit evidence.
- Statutory text is returned/rendered only for verified official/licensed records with required provenance; unverified, quarantined, and retired text is withheld.
- Added an optimistic curator command and audit endpoint; stale source-version decisions return conflict.
- No replacement legal text was fetched or fabricated in this release.

### IPLF-007A — notification linkage and evidence

- Extended the existing `notification_delivery_intents` owner; no third dispatcher/table family was created.
- Added schedule-source linkage, redacted recipient snapshot, provider event identity, dispatch owner, comparison status, suppression reason, and fallback link.
- Added append-only delivery events and idempotent provider-event uniqueness.
- Provider Operations exposes dispatch/fallback/suppression evidence.

### IPLF-007B — safe convergence portion

- Durable intent is the canonical owner for the implemented path.
- Suppressed or disabled external delivery creates exactly one visible in-app fallback through the same intent service.
- The implementation prohibits dual send and records canonical/fallback comparison state.
- External provider dispatch remains disabled under the repository’s existing approval gate. Direct legacy hearing-reminder SendGrid cutover and an enabled production provider switch are therefore still open; the manifest correctly leaves `IPLF-007B` in progress.

### IPLF-039A — trademark particulars and readiness

- Added company-scoped IP docket anchors and immutable trademark-particular versions.
- Captures form/version, mark kind/representation, Nice class scope/specification, use/priority, parties, agent, filing manifest, and readiness errors.
- Version appends use optimistic concurrency; stale versions conflict.
- The responsive `/app/ip` experience supports validated trademark creation and a permission-scoped portfolio/workspace.

### IPLF-039B — shared notice/evidence integration portion

- Links permission-scoped IP records to existing `CompanyNotice`; `/app/notices` remains the accepted-notice owner.
- Tenant matching and duplicate notice/docket links are database/service enforced.
- Link kind separates correspondence, service, instruction, and official-notice projections; accepted effect remains explicit.
- Full mailbox/Drive candidate automation, dedupe/attachment processing, and instruction-state orchestration remain open, so the slice stays in progress.

### IPLF-039C — deadline coverage/calendar/control portion

- Links IP docket coverage to existing `MatterDeadline`; there is no `ip_deadlines` duplicate.
- Requires active responsible/backup memberships and supports optimistic reassignment with a recorded reason.
- Coverage acceptance queues the existing `CalendarEventSync` owner for connected responsible/backup calendars; the client cannot claim a projection succeeded.
- Docket-control reporting exposes uncovered deadlines, unprojected calendars, inactive owners, open incidents, readiness, and currency totals.
- Automated leave/deactivation bulk reassignment and signed daily control remain open, so the slice stays in progress.

### IPLF-039D — restricted deadline incidents

- Adds restricted incident evidence with severity, impact, containment, linked ordinary deadline correction, corrective action, verifier, and verification time.
- Verification is blocked until containment exists.
- Matter access and IP review capability remain mandatory.

### IPLF-039E — effective-dated title portion

- Adds effective-dated ownership/assignment/licence/encumbrance/security evidence and recordal status.
- Detects overlapping different-party interests and preserves conflict flags.
- Supports related docket references through permission-checked service logic.
- Complete related-right family projections and transaction obligations remain open, so the slice stays in progress.

### IPLF-039F — immutable cost/accounting portion

- Adds non-negative original-currency IP cost facts with immutable evidence and optional billing link.
- Requires an existing Matter billing owner; time, invoices, payments, and spend are not duplicated.
- Control reporting sums the one IP cost amount owner by currency.
- Full export reconciliation/double-count prevention across every billing export remains open, so the slice stays in progress.

## Lifecycle and access controls

- IP records are company filtered and capability gated (`ip:view`, `ip:write`, `ip:review`, `ip:finance`).
- Restricted IP records require a Matter policy anchor and use existing Matter access checks.
- Disposing a Matter atomically archives linked IP dockets under the parent lifecycle lock.
- Disposed records disappear from operational lists/details and reject writes with non-disclosing 404 responses.
- Controlled `Disposed -> Intake` reopening does not resurrect archived IP child state.
- The regression reloads the final Matter and database rows to prove persisted state.

## Database changes

Five ordered, independently reversible Alembic revisions were added rather than combining unrelated schema changes:

1. `20260801_0001_ip_source_trust.py`
2. `20260801_0002_research_outcomes.py`
3. `20260801_0003_ip_foundation.py`
4. `20260801_0004_ip_operations.py`
5. `20260801_0005_notification_convergence.py`

The chain upgrades successfully from an empty SQLite database during every focused API test startup. Named foreign keys are used for SQLite batch portability; composite company-matched foreign keys protect shared-owner links.

## Verification evidence before production deployment

| Gate | Command | Result |
|---|---|---|
| API lint | `uv run ruff check src tests` | Passed |
| Focused integrated API | `uv run pytest tests/test_ip_prd_slices.py -q` | 5 passed |
| Statute routes/schema | `uv run pytest tests/test_ip_prd_slices.py tests/test_statutes_routes.py tests/test_statutes_schema.py -q` | 27 passed |
| Golden research fixtures | `python scripts/run_ip_golden_queries.py` | Passed; 3 fixtures |
| Manifest integrity | `python scripts/ip_program_manifest.py validate` | Passed; 436 requirements, 50 families, 68 journeys, 317 atomic paths |
| Web type check | `npm run typecheck` in `apps/web` | Passed |
| Web unit/component suite | `npm test` in `apps/web` | 118 files, 550 tests passed |
| Production web build | `npm run build` in `apps/web` | Passed; `/app/ip` included in 65 generated routes |
| Dated narrow E2E | `npx playwright test tests/e2e/ram-2026-08-01-bugs.spec.ts --config=playwright.app.config.ts --project=app-chromium` | Passed; real create/readiness round trip at 360px |
| Unsharded API suite | `uv run pytest -q --durations=25 --durations-min=1.0` | Reached the 30-minute local cap with no buffered result; not counted as a pass. Exact CI shards remain required. |

## Production verification contract

Production is not verified by the source-tree results above. Release closure additionally requires:

- merge/fast-forward the validated commit onto canonical `main` and push it;
- all GitHub CI, Security, CodeQL, and Postgres validation checks green for that exact commit;
- execute all five migrations against production through the canonical migration job;
- build fresh API and web images from that commit and route production traffic to their exact revisions;
- verify health and release metadata;
- rerun `ram-2026-08-01-prod.spec.ts` against the deployed production surface at desktop and 360px;
- verify local `main`, `origin/main`, deployed source labels, and serving revisions agree.

## Rollback

- Application rollback: route Cloud Run traffic to the prior known-good API/web revisions.
- Provider safety: external durable dispatch remains disabled; no provider switch is required to roll back this release.
- Data rollback: the migrations are additive. Do not downgrade after tenant IP data is created; prefer application rollback and a forward repair. Before data exists, downgrade in reverse revision order is supported.
- Scheduler rollback: the earlier IPLF-001B pause/resume and image/IAM rollback remain unchanged.

## Truthful completion statement

The fixed seven-day scheduler blocker is removed. The implemented trust, statute, search, lifecycle, IP docket, incident, and notification-fallback behaviors are release candidates with automated evidence. `IPLF-007B`, `IPLF-039B`, `IPLF-039C`, `IPLF-039E`, and `IPLF-039F` remain in progress for the explicitly listed provider/automation/reconciliation breadth, and the complete M1-M10 program is not fully delivered by this release.
