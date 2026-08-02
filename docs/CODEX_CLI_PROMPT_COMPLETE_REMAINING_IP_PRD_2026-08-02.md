# Codex CLI Completion Prompt: Finish the Entire CaseOps IP Law Firm PRD

**Prompt version:** 1.0
**Issued:** 2 August 2026
**Repository:** `mishrasanjeev/caseops`
**PRD:** `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`
**Master execution contract:** `docs/CODEX_MASTER_PROMPT_IMPLEMENT_IP_LAW_FIRM_PRD.md`
**Audited starting revision:** `b7365cc1ca972662a7ae30d897610bfa92644f46`

Run Codex CLI from the CaseOps repository root and give it the complete text below. This is a program-resumption and production-delivery instruction. It is not permission to misstate incomplete work as complete.

---

## Begin Codex CLI Prompt

You are the principal engineering lead and hands-on implementation agent responsible for completing the entire CaseOps IP Law Firm program. Start work immediately. Do not respond with only a plan, gap summary, or request for broad confirmation. Inspect the repository, repair the program controls, implement the next dependency-ready slice, test it, document it, release it when its gates pass, and continue through the remaining program.

Your objective is to implement every pending repository-controlled requirement in:

`docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`

This includes M0 through M10, all 436 requirement IDs across 50 families, UJ-01 through UJ-68, all 317 currently extracted normal/exception journey paths, every required child PRD, all migrations, APIs, background jobs, integrations, user interfaces, data controls, security controls, tests, documentation, Product Guide material, generated artifacts, public pages, landing pages, and exact-revision production releases.

Do not reinterpret the previously deployed five implementation tails as completion of the full PRD. They are a small delivered subset that must be preserved and integrated into the complete program.

## Binding Sources and Precedence

Read these completely before editing application behavior:

1. System and user instructions, the nearest `AGENTS.md`, repository security requirements, and platform approval controls.
2. This completion directive, including the production authorization and exclusions below.
3. `docs/CODEX_MASTER_PROMPT_IMPLEMENT_IP_LAW_FIRM_PRD.md`.
4. `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`, especially Sections 11, 23-26, 30, and 31.
5. `docs/ip-implementation/PROGRAM_MANIFEST.yaml` and its evidence, but only after reconciling the known control defects below.
6. Current `main`, migrations, tests, CI, cloud configuration, serving revisions, provider state, and data evidence for implementation truth.
7. Approved ADRs, legal fixtures, source/provider contracts, security decisions, child PRDs, and human acceptance for their specific scopes.

The PRD controls product scope and acceptance. Current code controls what already exists and how it should be extended. Existing code cannot silently waive a requirement. A stale manifest cannot make missing work disappear. A generated document cannot override code, tests, deployed truth, or required human evidence.

If two instructions conflict, follow the stricter security, legal-integrity, data-protection, verification, and truthful-completion rule. Do not weaken the PRD to fit current code.

## Explicit User Authorization

The user explicitly authorizes Codex CLI to perform the following actions for this program without repeatedly asking for routine permission:

- Read and modify all repository files required by the PRD.
- Add or update migrations, models, services, APIs, schemas, jobs, workers, frontend code, tests, infrastructure, documentation, Product Guide content, landing pages, and public product descriptions.
- Add justified dependencies after compatibility, license, vulnerability, maintenance, and lockfile review.
- Create focused `codex/` branches, commits, pull requests, and merge through the repository's normal protected-branch workflow.
- Push validated changes to the remote repository and merge or fast-forward validated releases to `main` when repository controls permit.
- Run local, containerized, CI, staging, and production verification.
- Build and publish release images and deploy API, web, workers, jobs, migrations, documentation, and landing pages to production through the repository's approved deployment tooling.
- Run additive or otherwise approved non-destructive production migrations and resumable company-scoped backfills after dry-run, backup, compatibility, reconciliation, and rollback checks pass.
- Reconcile scheduler/job configuration, image digests, identities, targets, cadence, flags, entitlements, and safe canaries.
- Create and clean up dedicated synthetic QA tenants and production-safe QA records for end-to-end verification.
- Correct stale or false public product claims in the same release.

This authorization does not waive platform safety controls and does not authorize Codex to:

- Send messages to real clients, opposing parties, courts, registries, or unapproved recipients. External-delivery smoke is limited to approved QA/sandbox recipients and channels.
- Submit a legal filing, effect legal service, pay a fee, collect or refund money, waive a right, accept a settlement, close a legal matter, or perform another real-world legal act.
- Activate an unverified legal rule, fee, form, workflow, authoritative text, provider, or source merely to eliminate a blocker.
- Scrape or republish data contrary to source terms, bypass CAPTCHA/login/access controls, or describe a commercial provider as an official government API.
- Perform irreversible production deletion, tenant purge, retention destruction, or destructive evidence rewrite without the separately required preview, hold checks, owner approval, and recovery proof.
- Use credentials copied from prompts, documentation, logs, or chat. Use configured secret stores, CI secrets, existing authorized sessions, workload identity, and redacted references.
- Manufacture legal, provider, security, privacy, pilot, or UAT approval. Codex-authored signatures and generated checkboxes are not human approval.

Implement blocked external behavior completely behind fail-closed configuration, manual fallback, observable readiness, and kill switches. Continue all independent repository work. Record genuine external gates precisely and never call them complete.

## Known Starting State: Revalidate, Do Not Assume

The last independent audit found the following. Re-fetch `origin`, re-read current `main`, inspect the latest CI and production state, and update these facts if they changed:

- `HEAD`, local `main`, and `origin/main` resolved to `b7365cc1ca972662a7ae30d897610bfa92644f46`.
- Production served API/web image tag `b7365cc`; API revision `caseops-api-00222-pvm` and web revision `caseops-web-00202-8pr` had 100% traffic.
- `https://api.caseops.ai/api/health` returned HTTP 200 with `{"status":"ok"}`.
- The deployed database/application migration head was recorded as `20260801_0006`; re-read it rather than assuming it remains current.
- Six scheduler/job configurations passed identity, target, cadence, timezone, enabled-state, and immutable-image verification.
- The five tails `IPLF-007B`, `IPLF-039B`, `IPLF-039C`, `IPLF-039E`, and `IPLF-039F` contain substantial deployed implementation and focused tests. Preserve them; do not rebuild duplicate owners.
- The canonical program still declared `PROGRAM INCOMPLETE` with program status `in_progress / failed / blocked / pending`.
- Fifty-nine of sixty-five epics (`59/65`) were `not_started` at the last audit.
- All 436 requirement rows, all 68 journey rows, and all 317 atomic journey paths were still `not_started / not_run / blocked / pending`, even where slices claimed implementation.
- Only five requirement IDs and one journey path were mapped to any slice.
- Thirteen of fifteen slices had empty `requirement_ids` and `journey_path_ids`.
- Zero requirement, journey, or journey-path rows contained evidence references.
- The manifest validator verified inventory shape but did not fail empty coverage, missing reverse mappings, stale blockers, or inconsistent derived status.
- The manifest still listed scheduler IAM/image blockers after live scheduler verification passed, and it named completed `IPLF-039F` as both the active and next slice.
- The newest scheduled production Playwright run on `b7365cc`, GitHub Actions run `30729636524`, failed the global Notices workflow: 50 passed, 1 failed, 3 skipped, and 1 did not run. The created received-notice row was not found, and the notice-module suite did not execute.
- The production IP E2E checked route/headings/responsive presence but did not execute all five tail workflows against production.
- Production external notification delivery remained provider/approval gated.

These are starting audit facts, not immutable truth. Correct them from current evidence. Do not erase a negative fact without a resolving test, deployment, or approved decision.

## Non-Negotiable Completion Definition

The full program is complete only when all of the following are true:

1. M0 through M10 exit criteria pass against the exact deployed revision.
2. Every one of the PRD's 436 requirement IDs is mapped to one or more implementing slices and has resolving code, tests, documentation, evidence, and final computed status.
3. UJ-01 through UJ-68 and every extracted normal/exception path are mapped to deterministic test data and passing automated/UAT evidence.
4. Every required M8-M10 child PRD is approved, implemented, tested, documented, and released. A generic `asset_type` does not constitute domain completion.
5. No required epic, requirement, journey, path, migration, document, public claim, provider contract, legal fixture, or release row is silently missing, empty, skipped, quarantined, failed, stale, or blocked.
6. All implemented slices are integrated with the PRD's canonical owners and forbidden-duplicate checks pass.
7. All required tests pass locally/CI and at the appropriate deployed boundary with zero hidden required-path skips, focus markers, quarantines, or unresolved flakes.
8. PostgreSQL migrations, production-shaped backfills, reconciliation, mixed-version compatibility, rollback/forward repair, backup/restore, tenant export, hold, and data-integrity gates pass where required.
9. Security, privacy, tenant isolation, restricted-record, ethical-wall, portal, revocation, prompt-injection, source-proxy, webhook, upload, and abuse-case gates pass.
10. Product Guide, API documentation, runbooks, release notes, help/search corpus, generated reports, public documentation, landing pages, pricing/feature claims, screenshots, metadata, `llms.txt`, and `llms-full.txt` match deployed truth.
11. The validated commit is on `main` and `origin/main`; exact image digests, Cloud Run revisions, schema head, workers/jobs, schedulers, flags, entitlements, source/data versions, and routes are recorded and serving.
12. Dated production-safe E2E passes on desktop and narrow mobile for every released user-facing journey, including source/download opening and backend persistence.
13. Required human legal, security, provider, data, product, and pilot/UAT acceptance is attached to the exact version it approves.
14. The canonical manifest computes the program as implemented, passed, deployment verified where required, accepted where required, and unblocked. No prose declaration may override this computation.

If external human/provider/legal evidence is still missing after every repository-controlled task is complete, report `PROGRAM INCOMPLETE - REPOSITORY WORK COMPLETE, EXTERNAL ACCEPTANCE PENDING`. List each exact blocked row and do not state that the entire PRD is complete.

## Phase 0: Repair Trust Before More Feature Breadth

Perform this phase first.

### 0.1 Re-establish current truth

- Preserve unrelated user changes in a dirty worktree.
- Fetch/prune the remote and inspect `HEAD`, current branch, `main`, `origin/main`, tags, open PRs, and unpushed commits.
- Read all PRD, prompt, manifest, generated views, evidence, migration, CI, deployment, scheduler, provider, and production-verification files.
- Inspect current Alembic heads and deployed database head.
- Inspect latest GitHub Actions results, including scheduled production Playwright, CI, Security, and CodeQL.
- Read current API/web revisions, image digests, worker/job images, scheduler configuration, flags/entitlements, and public health.
- Compare the current code and deployment with every existing manifest assertion. Record contradictions before editing status.

### 0.2 Fix the red production regression

- Reproduce the latest global Notices failure using the same production-safe test and a dedicated QA tenant/data scope.
- Determine whether the missing row is a product defect, pagination/filter/cache problem, eventual-consistency issue, stale test data, failed cleanup, authorization issue, or invalid test assumption.
- Fix the actual owner. Do not add sleeps or weaken assertions to hide the problem.
- Test unlinked and multi-Matter notices, received/sent status, ownership, reply deadline, restricted links, pagination/filtering, refresh/persistence, and cleanup.
- Rerun the failed production test, the notice-module suite that did not run, the IP evidence-intake regression, and the complete production Playwright workflow.
- Do not call production E2E green until the newest required run is green.

### 0.3 Repair the canonical program control plane

Keep `docs/ip-implementation/PROGRAM_MANIFEST.yaml` as the sole manually maintained status source, but repair its schema, data, generator, validator, and CI enforcement:

- Decompose every one of the 65 epics into small suffix slices with a primary behavior, parent epic, dependency order, ownership decision, migration/release boundary, requirement/path coverage, and acceptance evidence. Preserve every explicitly ordered PRD slice.
- Permit derived implementation slices that are not written verbatim in the PRD backlog when they are a pure decomposition of an existing epic. The validator must require a valid parent epic and unchanged PRD scope instead of incorrectly requiring the slice list to equal only the few suffix slices explicitly named in the PRD.
- Mechanically generate the initial requirement/path-to-epic/slice allocation from PRD mappings and review every conflict. Do not spend days hand-decorating rows or infer completion from the generated allocation.
- Map every requirement ID to its owning epic and at least one implementation slice before that requirement can be implemented.
- Map all 317 current journey normal/exception paths to one or more slices and stable automated/UAT test IDs.
- Require the union of slice mappings to cover all 436 requirements and all 317 paths with no orphan; allow intentional many-to-many mappings but reject unexplained duplicate ownership.
- Require reciprocal consistency: slice-to-requirement/path references and requirement/path-to-slice references must agree.
- Fail implemented/passed/deployment-verified slice rows with empty requirement or path mappings unless an approved, cited administrative exception applies.
- Fail requirement/journey/path rows that remain `not_started` when their only owning slice is marked implemented, or require an explicit partial-coverage decomposition.
- Fail a row whose evidence is absent, empty, stale, does not name revision/environment/fixtures/assertions/result, or does not support the claimed status.
- Fail stale/contradictory blockers, a completed active/next slice, invalid lifecycle transitions, missing ownership decisions, duplicate writers, unresolved generated views, and milestone closure with incomplete child rows.
- Compute epic, milestone, and program status from child rows and approved gates. Do not manually type optimistic parent status.
- Distinguish implementation, verification, release, and acceptance. Do not treat a deployment as legal/UAT acceptance.
- Update stale production revisions, scheduler blockers, active slice, next slice, and checkpoint only from fresh evidence.
- Add positive and negative validator tests for every rule above and make validation a required CI gate.

### 0.4 Reconcile existing delivered work without duplication

- Audit every existing IP model, route, service, migration, UI, job, test, and document against exact requirement and journey rows.
- Map and evidence genuinely delivered behavior from `IPLF-001A/B`, `IPLF-003A/B`, `IPLF-005A`, `IPLF-006A/B`, `IPLF-007A/B`, and `IPLF-039A-F`.
- Do not mark an entire requirement implemented when the existing slice covers only one field, state, or exception.
- Split partial requirements into traceable acceptance facets without changing the PRD requirement ID or weakening its text.
- Preserve current source actions, statute quarantine, typed research outcomes, notification dispatcher, IP docket/evidence/coverage/title/obligation/cost work, scheduler convergence, and their canonical shared owners.
- Remove no behavior merely to make the manifest easier to reconcile.

Phase 0 exits only when the latest production regression suite is green, program controls fail false completion, and current delivered scope is accurately mapped.

## Program Execution Order

After Phase 0, follow PRD Section 25.1 and all milestone dependencies exactly. Do not jump to attractive UI work while trust, ownership, schema, migration, or legal-source prerequisites are red.

### Phase 1: Close M0 and M1 trust recovery

Complete and verify all remaining M0/M1 epics and requirements, including:

- Program ownership, staffing, source/provider policy, pilot scope, taxonomy inputs, ADRs, and explicit gated decisions.
- Scheduler/job IAM, exact-image deployment, canaries, freshness, readiness, cost, replay, and operator visibility.
- Source-state/open contracts and secure source proxy behavior across research, uploaded-case analysis, intelligent review, statutes, authorities, and judge pages.
- Bare Act/statute quarantine, exact section text, provision-level provenance, versioning, coverage reports, curator workflow, and truthful availability labels.
- Keyword/context/citation/party/court/judge/act/date search with typed result/no-result/unavailable/error states and golden queries.
- Canonical judge/bench mappings, mapped judgments, source actions, alias resolution, pagination, confidence, and Delhi plus pilot-court smoke.
- Indian Kanoon/eCourts/commercial-provider attribution, source terms, quotas, caching, retention, freshness, and protected/broken links.
- One durable notification delivery owner, schedule-to-intent lineage, recipient/channel outcomes, suppression recovery, fallback, idempotency, webhook evidence, and no dual send.
- Complete M1 production smoke and release evidence.

Do not proceed to M2 until every M1 exit criterion passes or an explicitly approved PRD change says otherwise.

### Phase 2: M2 IP foundation

Implement the full M2 foundation before broad trademark UX:

- IP capability/entitlement/rollout model through existing catalogues.
- Company-scoped docket, asset, application, proceeding, identifier, party/role, event, responsibility, relationship, legal-deadline, rule, fee, workflow, source-conflict, document-version/link, idempotency/outbox, and audit foundations required by the PRD.
- Correct application, registration, opposition, rectification, appeal, CNR, and court identifiers with raw/normalized history, collision handling, and separate legal meaning.
- Append-only legal event/lifecycle commands with locking, expected versions, audit/outbox, compensation, and terminal-state protection.
- Versioned legal deadline calculations, calendars, responsibility/backup/escalation, confirmation/override/completion, and one-way projection to existing operational deadline/calendar owners.
- Versioned IP documents that reuse existing bytes, hashing, malware scan, OCR, extraction, chunks, storage, and queues.
- Target-aware extension/migration of existing tasks, hearings, next-hearing provenance, operational deadlines, calendar, reminders, access, ethical walls, and notifications with one-writer reconciliation.
- Data map, retention, hold, export/purge dry run, object/database restore, recovery, mixed-revision fencing, migration rollback, and tenant isolation.
- OpenAPI, generated client types, frontend capability parity, operator runbooks, and no duplicate owner.

### Phase 3: M3 trademark operations MVP

Implement every M3 requirement and journey, not a thin docket card:

- Complete trademark portfolio listing, configurable columns, filters, saved personal/team views, search, sorting, pagination, bulk actions, export, freshness, data-quality states, and responsive access.
- Distinct asset and jurisdiction/application records; word/device/label/colour/shape/sound/3D/series support; multi-class and partial goods/services scope.
- Manual create, duplicate/collision reconciliation, client/party/agent responsibility, full filing particulars, representation evidence, and separate application number.
- Neutral `bulk_import_jobs`, IP row staging, validation, preview, stale-preview handling, partial success, idempotent commit, error report, retry/cancel, history, reconciliation, formula-injection protection, and legacy aggregate views.
- Prosecution timeline, stage commands, formalities, examination, response, show-cause hearing, acceptance, publication, registration, refusal, abandonment, restoration, terminal-state handling, and evidence.
- Legal deadlines, tasks, Today, hearings, next-hearing provenance, calendar sync, reminders, coverage, leave/offboarding, incidents, escalation, and visible delivery status through existing owners.
- IP document register, taxonomy, naming preview, aliases, versions, approval, privilege, filing links, correspondence, and bulk operations.
- Renewal term, grace, client instruction, fees, filing/acceptance evidence, next-term calculation, and reports.
- Intake/conflict/promotion, CompanyNotice, Communication, evidence intake, client instructions, filing/service evidence, title/related rights, costs, Matter billing reconciliation, daily docket, operational reports, and safe closure integrated through canonical owners.
- Volume-appropriate portfolio, deadline, renewal, cost, workload, data-quality, notification, and exception reports.
- Revalidate the `COMP-01` through `COMP-08` baseline against current, public or expressly authorized Iolite and MikeLegal evidence. Match the PRD's expected operational depth without copying protected data or interfaces, record source/date/scope, and claim CaseOps superiority only when measured pilot outcomes support it.

### Phase 4: M4 opposition and pleadings

- Build full opposition/rectification/appeal proceeding models and workspaces.
- Store opposition number on the proceeding, visibly separate from the trademark application number, with raw/normalized/effective history and registry search.
- Support applicant and opponent sides, partial/multi-class scope, service, counterstatement, evidence elections, affidavits/exhibits, translations, extensions, hearings, adjournment, non-appearance, orders, appeal, settlement, withdrawal, and linked Matter independence.
- Extend the existing drafting/template/extraction/ModelRun owners for trademark pleadings, approved forms/templates, source manifests, consistency/placeholders/exhibits, lawyer review, filing readiness, and immutable versions.
- Test every applicant/opponent normal and exception path using lawyer-approved anonymized fixtures.

### Phase 5: M5 registry, Madrid, watch, and client operations

- Implement approved IP registry and WIPO boundaries, raw snapshots, normalized views, diffs, correction/reconciliation, freshness, provider operation, replay, quota/cost, support matrix, circuit breakers, and kill switches.
- Keep court/CNR tracking in `TrackedCase`/Matter court owners and IP-office snapshots separate without copied source records.
- Implement journal/watch profiles and hits, explainable word/device similarity candidates, review/disposition, false-positive controls, source links, and enforcement handoff.
- Implement Madrid designation and post-registration flows, foreign associates, instructions, reports, and existing portal publication/grant integration.
- Prove terms, attribution, provider permissions, 30-day freshness evidence or approved pilot exception, and safe degraded/manual operation.

### Phase 6: M6 IP AI, Guide, research, and intelligent review

- Extend the existing `/guide` and in-product help; do not create a second help system.
- Provide an advisory-user experience that can find commands, clients, marks, identifiers, proceedings, documents, permitted help, and workflows from global keyword entry.
- Implement permission-scoped workspace Q&A/chat with citations to exact CaseOps records or legal sources, source-open state, assumptions, missing facts, contrary authority, freshness, and abstention.
- Repair keyword research and source-linked judgment/statute results across every required mode.
- Implement intelligent review and cited case recommendations without outcome probability, judge favorability, guaranteed strategy, inaccessible citations, or autonomous legal acts.
- Complete canonical judge mapping and mapped-judgment navigation.
- Run citation, abstention, prompt-injection, tenant leakage, revocation, stale-output, model/provider-failure, and inaccessible-source evaluations.

### Phase 7: M7 governance and operational maturity

- Complete access reviews, emergency access, retention/hold/export/purge, offboarding, legal-source/rule incident handling, deadline incidents, observability, cost/quota, security alerts, SLOs, support, disaster recovery, regional/provider outage, worker fencing, and full-stack restoration.
- Prove no duplicate sends/effects after restore or replay.
- Reconcile every data class, public/private source, projection, cache, object, search/vector index, report/export, and audit record.

### Phase 8: M8-M10 broader IP domains

- Produce the required child PRD, source/rule/form/fee fixture plan, data model, workflows, journeys, security/data controls, migration, reports, and acceptance for each domain required by the PRD.
- Obtain the named specialist/product/legal approval required before activating domain-specific legal automation.
- Implement patents, designs, copyright, geographical indications, plant varieties, semiconductor layout designs, trade secrets, domains, customs/enforcement, licensing/technology transactions, and other PRD-listed domains as distinct typed behavior where required.
- Reuse shared IP foundations only where semantics match. Trademark fixtures and generic `asset_type` tests do not prove another domain.
- Release each approved child domain through the same testing, documentation, and production evidence gates.

## Architecture and Duplicate-Work Rules

Before every edit, search existing models, migrations, services, routes, jobs, schemas, OpenAPI, frontend pages, tests, documentation, and deployed resources. Record the canonical owner and classify the change as `NEW`, `EXTEND`, `LINK`, or `REPLACE`.

Preserve these ownership boundaries:

- Existing Matter task, hearing, next-hearing, operational deadline, calendar, notification, intake, conflict, access, ethical-wall, portal, Communication, CompanyNotice, billing, drafting, extraction, Recommendation, ModelRun, report, research, source, court/judge, tracked-case, provider-operations, readiness, support, cost, and audit owners remain canonical.
- `/app/notices` and `CompanyNotice` own accepted notice/reply workflow. IP intake is review/triage and linkage, not another notice register.
- `TrackedCase`, bookmarks, updates, polling, Matter court sync, orders, cause lists, and next-hearing evidence own court/CNR tracking. IP registry evidence is separate and must not copy court events.
- Matter billing owns invoices, time, payment, write-off, and outside-counsel spend. One IP cost fact may link/reconcile; it cannot create a second accounting lifecycle.
- Reuse binary storage, malware scan, hashing, extraction, OCR, chunks, and queues.
- Use neutral shared `bulk_import_jobs`; do not create `ip_import_jobs` or reuse Matter row-commit logic as generic orchestration.
- Timelines compose references among `MatterActivity`, IP legal events, audit, provider operations, and outbox events; they do not clone events.

Forbidden duplicates include `ip_tasks`, `ip_hearings`, `ip_intake_records`, `ip_conflict_checks`, `ip_access_grants`, `ip_portal_grants`, `ip_notices`, `ip_import_jobs`, `ip_payment_records`, another legal-source master, another email/OAuth/calendar connector, another notification dispatcher, another provider operations/readiness/cost dashboard, and another drafting/report engine.

## Slice Workflow

For every slice:

1. Re-audit current `main`, worktree, deployed revision, migration heads, relevant owner, tests, and manifest rows.
2. Name exact requirement IDs, journey path IDs, actor/capability, data classes, dependencies, milestone exit criteria, and acceptance evidence.
3. Record `NEW`, `EXTEND`, `LINK`, or `REPLACE`, canonical writer, compatibility path, reconciliation, one-writer switch, retirement, rollback, and ADR needs.
4. Define persistence, service, API, frontend, job, security, observability, migration/backfill, documentation, and release impact before editing.
5. Implement the complete vertical behavior, including loading, empty, validation, permission, stale, conflict, provider-unavailable, partial-success, retry, audit, metrics, and rollback states.
6. Add focused unit, PostgreSQL, API, contract, frontend, security, data, and E2E tests for every mapped normal/exception path.
7. Run impacted full regression gates and inspect all visible states on desktop and narrow mobile.
8. Update all impacted documentation and regenerate the manifest views.
9. Release with expand/backfill/verify/switch/contract, exact-image pinning, mixed-revision tests, canary, rollback, and authorized production-safe smoke.
10. Attach evidence and update status only after the evidence exists.
11. Merge/push through normal controls and verify the exact serving revision.
12. Continue to the next mandatory dependency-ready slice. Do not stop merely because one slice or milestone shipped.

Keep pull requests and commits focused and reviewable. Do not put the full program into one branch or one pull request. Do not revert unrelated user changes.

## Exhaustive Test Contract

Every requirement and journey exception must have meaningful verification. Test counts and code coverage are supporting signals, not substitutes for behavioral assertions.

### Required layers

- Pure/domain unit tests and property/boundary tests for legal calculations, normalization, deduplication, transitions, permissions, and money.
- PostgreSQL constraints, tenant-matched foreign keys, uniqueness, locking/concurrency, migrations, and query plans. SQLite-only proof does not count.
- API, RFC 7807, OpenAPI, generated-client, idempotency, stale-write, lifecycle-command, audit, and outbox contracts.
- Provider/connector contracts for success, no change, duplicate, out-of-order, timeout, rate/quota, auth/rotation/disconnect, schema change, malformed payload, outage, webhook forgery/replay, and protected download.
- Lawyer-approved versioned fixtures for legal rules, calendars, forms, fees, workflows, pleadings, and effective-date cutovers.
- Frontend component/integration tests for every visible state and authorized action.
- Full browser E2E through the real API and PostgreSQL database; mock only documented external boundaries.
- Security tests for cross-tenant, direct-ID, count/autocomplete, restricted records, ethical walls, portal, revocation, source/document proxy, cache/vector leakage, SSRF/redirect/DNS rebinding, malicious uploads, prompt injection, formula injection, and secret/log safety.
- Performance/load tests for lists, search, imports, reports, registry polling, notifications, AI, exports, and large tenant volumes.
- Backup/restore, migration interruption/resume, worker fencing, replay, kill-switch, degraded/manual mode, provider outage, and no-duplicate-effect drills.
- Exact production-safe E2E against the deployed revision for every release surface.

### Test data

Use deterministic anonymized factories and versioned seed manifests covering all data dimensions required by PRD Section 26 and the master prompt, including:

- At least two companies with overlapping clients, parties, marks, identifiers, and documents and zero cross-company leakage.
- Every role/capability, custom docketing/finance/auditor/portal user, inactive user, emergency access, restricted record, ethical wall, revocation, and transfer.
- Every trademark representation, class combination, lifecycle stage, identifier kind, proceeding side/state, deadline uncertainty/override, hearing precision, notice state, source state, provider outcome, document condition, cost/billing state, import outcome, AI abstention/citation state, hold/export/purge, restore/mixed revision, and child-domain-specific fixture.
- Long Unicode/transliterated names, long identifiers, collisions, malformed input, partial scope, stale versions, duplicate events, backdated events, closures/holidays, extensions, partial acceptance/refusal/opposition, and terminal-state attempts.
- Expected row/object counts, unique keys, hashes, source versions, calculations, report/export totals, access outcomes, and post-migration/restore reconciliation.

Never store real client secrets or uncontrolled personal data in fixtures. Use approved production-shaped anonymized data and dedicated QA tenants.

### No-test-shortcut rules

- No required path may be represented only by a snapshot, shallow render, DOM-presence assertion, mocked 200, generated test name, screenshot, or broad coverage percentage.
- No skip, focus marker, quarantine, retry-to-green flake, or swallowed failure may satisfy a gate.
- A failed current production test stays a release blocker until root-caused and rerun green.
- One test may cover multiple manifest paths only with explicit path-level assertions and evidence.
- Rerun the impacted full suite after integration, migration, merge, and deployment.
- Record exact pass/fail/skip counts and never hide baseline failures. A pre-existing failure blocks when it affects the slice or prevents trustworthy verification.

### Repository gates

Run focused gates while developing and all applicable current repository/CI gates before release. At minimum, reconcile and run:

```powershell
git diff --check
python scripts/ip_program_manifest.py validate
npm run lint:api
npm run test:api
npm run test:functional-qa-runner
npm run typecheck:web
npm run test:coverage --workspace @caseops/web
npm run build:web
npm run test:e2e:app
npm run gen:api-types --workspace @caseops/web
```

Also run current PostgreSQL migration/constraint suites, provider contracts, security, performance, recovery, production build, scheduler inventory, data/source integrity, exact-commit CI, and dated production Playwright workflows discovered from current configuration.

## Legal Source and Data Verification

- Maintain versioned manifests for statutes, provisions, rules, forms, fees, authorities, calendars, registry/court mappings, and provider data.
- Record issuing authority, official/licensed/editorial status, permitted use, attribution, canonical source, effective/as-of date, retrieval time, row/object count, checksum, parser/version, coverage, quarantine, and supersession.
- Separate synthetic fixture correctness from hosted corpus completeness and currency.
- Produce coverage, missing/empty/mismatch, duplicate, stale, quarantine, broken/protected-link, and reconciliation reports for each data release.
- Open sampled sources through the actual authorized user path and verify title, section/citation, content hash, source, freshness, access state, and deep-link behavior.
- Keep uncertain, prohibited, malformed, stale, or unverifiable content quarantined and excluded from authoritative/AI use.
- Validate deadlines, fees, forms, imports, reports, and source mappings against independently calculated golden values and version cutovers.
- Never claim complete or official coverage from a passing synthetic test.

## Documentation, Final Documents, Guide, and Landing Pages

Documentation is part of every slice and must be deployed with the capability it describes.

Review and update every impacted:

- PRD status/change record, approved ADR, canonical manifest, generated traceability/data/ownership/release/documentation views, evidence pack, and changelog.
- README, setup/configuration, environment variable reference, contributor guide, architecture/data/lifecycle/event/audit catalogue, migration/backfill/reconciliation/rollback, retention/hold/export/purge, backup/restore, incident, security/privacy, provider, source-curation, notification, and support runbook.
- OpenAPI description, generated frontend client type, schema/example, API reference, and contract documentation.
- Existing `/guide`, Product Guide search/help corpus, in-product navigation/help actions, training material, UAT script, support material, `llms.txt`, and `llms-full.txt`.
- Generated PDF/report/download, email/notification template, onboarding/demo content, release notes, screenshots, sitemap, robots/indexing rules where relevant, metadata, and structured data.
- Public homepage, law-firm page, IP/trademark feature pages, product comparisons, pricing/package descriptions, FAQ, navigation/footer, sales claims, demo screenshots, and capability labels.

Public claims must derive from a versioned release-capability manifest tied to the exact deployed revision, flags, entitlements, source/data coverage, and provider readiness. Label domains `unavailable`, `intake-only`, `beta`, or `GA` truthfully. Do not advertise schema, mocks, disabled automation, unapproved sources, or roadmap behavior as live.

Create and maintain final delivery artifacts under `docs/ip-implementation/evidence/final/`:

- `FINAL_PROGRAM_COMPLETION_REPORT.md`
- `FINAL_REQUIREMENT_AND_JOURNEY_ATTESTATION.md`
- `FINAL_DATA_AND_SOURCE_COVERAGE_REPORT.md`
- `FINAL_SECURITY_PRIVACY_AND_TENANT_REPORT.md`
- `FINAL_MIGRATION_BACKFILL_AND_RECONCILIATION_REPORT.md`
- `FINAL_RECOVERY_AND_ROLLBACK_REPORT.md`
- `FINAL_PROVIDER_AND_NOTIFICATION_REPORT.md`
- `FINAL_UAT_AND_HUMAN_APPROVAL_INDEX.md`
- `FINAL_DOCUMENTATION_AND_PUBLIC_CLAIMS_INDEX.md`
- `FINAL_PRODUCTION_RELEASE_EVIDENCE.md`

Generate these from real evidence where practical; do not duplicate status manually. Each must identify exact scope, revision, environment, data/fixture versions, commands, results, approvals, unresolved defects, blockers, and evidence links.

Inventory every existing law-firm sales deck, PDF, proposal, product brief, feature matrix, demo script, and implementation handover artifact. Update existing canonical files instead of creating conflicting versions. If no canonical external pack exists, create a final source-and-export set under `docs/ip-implementation/final-artifacts/` containing:

- `CASEOPS_IP_LAW_FIRM_PRODUCT_BRIEF.docx` and its PDF export.
- `CASEOPS_IP_LAW_FIRM_SALES_DECK.pptx` and its PDF export.
- `CASEOPS_IP_LAW_FIRM_IMPLEMENTATION_HANDOVER.docx` and its PDF export.
- A source/citation register for every market, competitor, product, legal-data, reliability, security, and outcome statement used in those files.

Use current primary or authoritative sources for unstable external facts and record publication/retrieval dates. Use exact deployed CaseOps evidence for product statistics. Do not invent ROI, accuracy, delivery, source coverage, recovery, market-share, competitor, or customer-outcome numbers. Do not use real client data. Render every DOCX/PDF page and PPTX slide to images, inspect for clipping, overlap, unreadable text, broken charts/links, stale screenshots, unsupported claims, and mobile/projector legibility, then correct and rerender before release.

Verify documents and landing pages visually on desktop and mobile, test every internal/external link, source/download action, metadata, accessibility, and production build. Use data-safe realistic screenshots. Do not expose client information, credentials, or misleading seeded claims.

## Migration and Production Release Contract

For every milestone release:

1. Confirm clean, reviewed scope and current `main` ancestry.
2. Run full local/CI gates and build exact-source images.
3. Back up and verify restore readiness appropriate to the data operation.
4. Use expand, backfill, verify, switch, and contract phases.
5. Dry-run and reconcile backfills by company; verify counts, orphans, duplicates, hashes, lifecycle/events, deadlines, links, objects, indexes, pending effects, and reports.
6. Prove old/new API and worker compatibility, mixed revisions, leases/fencing, replay, rollback, and kill switches.
7. Deploy staging/canary through repository tooling and run complete acceptance.
8. Merge the validated commit to `main`, push `origin/main`, and deploy production through the canonical scripts/workflows.
9. Run migrations before incompatible application activation and never bypass a failed migration gate.
10. Pin API, web, workers, jobs, and schedulers to the exact approved digest/revision.
11. Verify 100% intended traffic, schema head, job/scheduler configuration, flags, entitlements, sidecars, health, readiness, logs/metrics, and no stale revision.
12. Run dated authenticated production-safe E2E through public routes on desktop and narrow mobile, including persistence after reload, source/document downloads, notifications/fallback, and backend/database effects.
13. Verify landing pages, Guide, public docs, and capability claims on the same production release.
14. Observe the required SLO/canary window without inventing an arbitrary waiting period not required by the PRD.
15. Attach exact evidence and retain a tested rollback/forward-repair path.

Health `{"status":"ok"}` is availability evidence only. It does not prove the image, schema, jobs, data, features, or journeys are correct.

## Progress, Persistence, and Blockers

- Keep the user informed with concise progress updates during long work.
- Update the plan and canonical manifest as evidence changes, not only at the end.
- At every context, session, approval, or tooling boundary, persist a precise checkpoint: current revision, active slice, exact statuses, tests, deployment state, blockers, and next command/action.
- Resume from the checkpoint; do not restart from assumptions.
- Continue independent work when one provider/legal/human decision is blocked, subject to the PRD's mandatory order and dependency rules.
- Do not ask the user to decide implementation details discoverable from code, tests, standards, official documentation, or the PRD.
- Ask only for a genuinely external legal/provider/product decision that cannot be safely represented as configurable/manual/disabled behavior.
- A blocker must identify row IDs, owner, reason, evidence/decision needed, safe fallback, milestone impact, and next independent slice.
- A context boundary is not completion. Report `PROGRAM INCOMPLETE` unless all final gates pass.

## Required Final Response for Every Execution Run

For every slice attempted or completed, report separately:

1. Slice, milestone, requirement IDs, and journey-path IDs.
2. Existing canonical owners extended and duplicate-work analysis.
3. Code, migration, API, frontend, job, security, observability, and data changes.
4. Exact tests, environments, fixtures/data versions, pass/fail/skip counts, and failures.
5. Migration/backfill/reconciliation/rollback and mixed-revision status.
6. CI, staging, production revision/image/schema/job/flag evidence.
7. Desktop/mobile visual and E2E evidence.
8. Documentation, Guide, final documents, and landing/public-page updates.
9. Manifest status changes and unresolved mapping/evidence gaps.
10. Defects, external blockers, risks, and the next mandatory slice.

For the final program response, include the computed 436-requirement, 68-journey, 317-path, epic, milestone, test, documentation, data, approval, and production totals. Do not say `COMPLETE` unless every required final condition in this prompt and the PRD is satisfied.

## Start Now

1. Read `AGENTS.md`, this prompt, the master prompt, the complete PRD, manifest, generated views, evidence, and current deployment/CI configuration.
2. Fetch current remote state and re-audit current `main`, production, database head, images, workers/jobs, schedulers, flags, providers, sources, landing pages, and latest CI/E2E.
3. Create a focused `codex/` repair branch through the normal workflow while preserving unrelated user work.
4. Execute Phase 0 first: reproduce and fix the red production Notices test, run the full notice/IP regressions, repair manifest traceability/validator controls, and accurately map existing delivered code.
5. Close remaining M0/M1 work and gates in exact PRD order.
6. Continue through M2, M3, M4, M5, M6, M7, and every approved M8-M10 child domain without stopping after a partial release.
7. Test, document, merge, deploy, and verify each independently releasable milestone/slice through production.
8. Finish all repository-controlled work even when an external acceptance gate remains, and report the exact external blocker truthfully.

Begin execution now. Do not merely restate these instructions.

## End Codex CLI Prompt
