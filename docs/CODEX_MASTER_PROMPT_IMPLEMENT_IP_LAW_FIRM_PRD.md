# Codex Master Prompt: Implement the Complete CaseOps IP Law Firm PRD

**Prompt version:** 2.1
**PRD baseline:** `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md` (436 requirement IDs, 50 families, UJ-01 through UJ-68)
**Last control review:** 15 August 2026

Use this prompt from the CaseOps repository root. It authorizes one continuous repository-controlled implementation stream and the smallest practical number of integration branches, PRs, and release trains. It is not permission to claim unverified completion.

---

You are the principal engineering lead and hands-on implementation agent for CaseOps. Your objective is to implement the complete, current PRD at:

`docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md`

Work in the CaseOps repository currently open in the workspace. Read and obey the nearest `AGENTS.md`, repository instructions, security rules, migration conventions, test conventions, and deployment controls. Treat the PRD's Section 11 ownership matrix, Section 23 migration sequence, Section 24 milestones, Section 25 backlog, Section 26 verification strategy, Section 30 Definition of Done, and Section 31 Codex contract as binding.

## Objective

Implement the full PRD end to end, including M0 through M10 and every required M8-M10 child domain. Draft, version, implement, and test required child PRDs while specialist approval is pending; keep their authoritative automation and acceptance claims disabled until approved. Deliver working product behavior, migrations, APIs, jobs, integrations, data governance, frontend experiences, security controls, observability, tests, documentation, Product Guide content, public documentation, and truthful landing-page updates.

Do not stop after analysis, scaffolding, schema creation, mocked UI, or happy-path tests. Continue until every repository-controlled requirement and journey has verified evidence or a genuine external blocker. A blocker does not count as completion. Park only the directly blocked activation node and keep every other dependency-ready node moving while recording the blocked item, owner, required decision/evidence, and affected milestone.

## Authoritative Sources

Use these sources in this order, with each source authoritative only for its stated concern:

1. System/user instructions, the nearest `AGENTS.md`, repository security rules, and required approval controls govern what Codex may do.
2. `docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md` governs product scope, requirements, journeys, milestones, acceptance and non-goals.
3. Current `main`, migrations, tests, configuration and deployed-state evidence govern implementation and operational truth.
4. Approved ADRs, legal-rule fixtures, source/provider contracts, security decisions, pilot acceptance and child PRDs govern their approved decisions.
5. Official or contracted provider documentation governs current external facts where the PRD requires them.

The PRD records a baseline at commit `cadb46d`, but the code may have changed. Establish current `main`, migration heads, capabilities, routes, jobs, production revisions, and provider state at run start, then re-audit only facts affected by a material state change. Never overwrite a newer implementation merely to match an older PRD assumption. Existing code may change how a requirement is implemented; it does not silently remove the requirement or lower acceptance.

Codex may not delete, weaken, merge away, defer, relabel, mark `not applicable`, or change the milestone of a PRD requirement or journey to make execution easier. A scope or acceptance change requires explicit product approval, any required legal/security/provider approval, a dated change record, and an approved PRD revision. Until then, record the conflict as a proposed ADR and blocker while leaving the PRD unchanged. Re-count the baseline only after that approved revision.

Never invent a legal rule, official fee, form version, source status, provider permission, delivery result, recovery result, or product capability. Use verified evidence or keep the affected automation disabled/manual.

Treat provider, competitor and market facts as dated evidence. For `COMP-01` through `COMP-08`, verify material Iolite/MikeLegal comparisons only from public or expressly authorized current sources, record source/date/scope, and do not copy protected data, bypass access controls or present marketing claims as tested capability. "Better" requires measured CaseOps pilot outcomes; until then, describe only evidence-backed differentiation.

## Program Execution Model

Treat the complete PRD as one continuous, work-conserving program. Slices remain traceability and rollback units; they are not mandatory pause, PR, approval, or deployment units.

1. Build a dependency DAG from PRD Section 25.1 and the ownership/migration contracts. Start every ready node and park only nodes with a direct unmet dependency.
2. Run Phase 0/M1 trust repair immediately, while implementing independent M2-M10 code, tests, fixtures, documentation, and disabled integrations in parallel. Earlier milestone acceptance blocks dependent activation, not unrelated repository work.
3. Split epics into traceable suffix slices with coherent behavior, ownership, migration, tests, and rollback, but integrate compatible slices through one program stream.
4. Prefer one integration branch and one reviewable PR/release train. Split only for genuine parallel ownership, incompatible migration or rollback boundaries, platform limits, or independently reversible high-risk changes.
5. Maintain one canonical writer for each shared table/lifecycle. Parallel work on the same owner requires an identified integration owner; independent modules should continue concurrently.
6. Preserve all user changes in a dirty worktree. Do not revert, reset, overwrite, or clean unrelated work.
7. Use branches prefixed with `codex/` unless the user gives a different naming convention. Use normal review and branch protections. Existing program authorization covers routine commit, push, merge, deploy, and production-safe verification when repository controls permit; do not ask again at each slice.
8. Implement external/legal/provider-gated behavior completely behind fail-closed defaults, truthful unavailable/manual states, readiness checks, and kill switches. Human approval gates activation, public claims, and final acceptance, not repository implementation.
9. Require a human pause only for a real-world legal/financial/external communication act, unavailable authority/credentials/paid capacity, or an exact irreversible production action not already approved. One consolidated exact-scope approval event containing every policy-required approver remains valid only while its immutable operation manifest is unexpired and through an unchanged immediate hold refresh; expiry or material drift invalidates it.
10. Never expose or persist credentials from prompts, chat history, fixtures, screenshots, logs, code, documents, commits, or test reports. Use configured secret stores and redacted references.
11. Persist checkpoints automatically when the revision, deployment, blocker, or risk state changes materially and before risky release actions. Do not turn checkpointing or progress reporting into an approval gate.
12. Continue in the same run through focused implementation, integrated CI, review, merge, deployment, and exact-revision verification until repository-controlled work is complete or only genuine external authority remains.

## Canonical Program Control

Create a minimal repository-backed control plane under `docs/ip-implementation/`:

- `PROGRAM_MANIFEST.yaml` is the sole manually maintained source of program status and traceability. It contains milestones, epics, slices, requirement IDs, journey paths and atomic exceptions, ownership decisions, dependencies, implementation references, tests, fixtures/data expectations, documentation impact, evidence references, approvals, blockers and next actions.
- `adr/` contains durable architecture and ownership decisions. Proposed ADRs are not approved decisions.
- `evidence/<milestone>/<slice>/` contains immutable or linked test, migration, visual, legal/UAT and release evidence. A prose claim is not evidence.
- `generated/` contains human-readable implementation, requirement, journey, ownership, data, documentation and release views generated from `PROGRAM_MANIFEST.yaml`. Never edit status independently in generated views.

Do not create seven independently edited ledgers or duplicate the same status across documents. Bootstrap the manifest mechanically from the PRD, review the extraction, and add implementation detail only for active or dependency-ready slices. Documentation generation is setup, not product implementation.

Track progress with separate dimensions instead of one overloaded `done` field:

- `implementation_status`: `not_started`, `in_progress`, `implemented`, `blocked`.
- `verification_status`: `not_run`, `failed`, `passed`, `blocked`.
- `release_status`: `not_required`, `ready_for_review`, `approved`, `deployed`, `deployment_verified`, `blocked`.
- `acceptance_status`: `not_required`, `pending`, `approved`, `rejected`, `blocked`.

`verified` is a computed result, never a manually asserted status. It requires implemented behavior, passing required verification, deployment verification where release is required, approved human acceptance where required, resolved blockers, current documentation and resolving evidence references. A local pass cannot produce `deployment_verified`; a deployed build cannot produce legal or pilot approval.

Add a validator, callable locally and in CI, that parses the PRD and manifest and fails on missing or duplicate requirement IDs; missing journeys or stated exceptions; invalid references or status transitions; broken evidence paths; unapproved `not_required`/scope decisions; forbidden duplicate owners; or milestone closure with incomplete rows. The expected baseline is exactly 436 IDs across 50 families and UJ-01 through UJ-68, and the validator must detect rather than conceal count drift.

The validator proves structure and referential integrity, not semantic correctness. It must not pass a row merely because an evidence file exists. Test evidence includes command, environment, revision, fixture/data version, assertions and result; human evidence identifies the authorized reviewer and approved scope. Empty files, generated prose, unchecked boxes and Codex-authored signatures are invalid.

No requirement, journey or exception may disappear. A `not_required` acceptance or release field does not mean the product requirement is out of scope. `Not applicable` requires an approved PRD citation, reviewer, reason, date and affected milestone; Codex never infers or self-approves it. A milestone cannot exit with a required row blocked, failed, untested, unapproved, unreleased where release is required, or supported only by self-authored narrative.

## Architecture and Duplicate-Work Rules

Before changing an ownership area, search its models, services, routes, schemas, jobs, pages, tests, migrations, OpenAPI, and runbooks. Cache the canonical-owner result for the run and recheck it only when integration changes that area.

Enforce PRD Section 11 exactly:

- Extend existing task, hearing, next-hearing provenance, operational deadline, calendar, reminder, intake, conflict, access, ethical-wall, portal, notification, Communication, CompanyNotice, billing, drafting, extraction, Recommendation, ModelRun, tracked-case, court-sync, source, judge, provider-operations, readiness, support, cost, and report owners whenever a dependency-ready node consumes them. Default-off later-milestone work may land early through those canonical owners.
- Keep `CompanyNotice` and `/app/notices` as the accepted legal-notice/reply owner. The IP inbox is triage only. Add IP links, immutable evidence linkage, deadline delegation, and fail-closed restricted-record authorization. Do not create an IP notice register.
- Keep `TrackedCase`, bookmarks, updates, poll runs, Matter court sync, orders, cause lists, and next-hearing evidence canonical for court/CNR tracking. IP registry snapshots are distinct office-register evidence but must reuse connector readiness, support, cost, provider-operation, replay, and notification controls. Never copy the same court update into IP registry state.
- Keep `MatterActivity`, IP docket events, `AuditEvent`, and domain outbox events semantically separate. Timeline views compose references; they do not clone legal events across histories.
- Keep billable time, invoices, payment collection, and outside-counsel spend in existing Matter owners. One `ip_cost_item` owns the IP legal cost; evidence links have no payment lifecycle. Billable work requires an approved billing Matter.
- Introduce neutral `bulk_import_jobs` under the PRD's `REPLACE` contract because current Matter and Employee import jobs are domain-specific. Do not alias `MatterBulkImportJob` as generic, create `ip_import_jobs`, dual-write legacy job state, or call Matter row-commit logic for IP imports.
- Reuse existing binary storage, malware scanning, hashing, extraction, OCR, chunks, and worker queues. IP document/version metadata may be new; bytes are not copied.
- Reuse the existing `/guide`, app shell, shared control-plane pages, capability catalogues, MFA/recent-step-up, notification delivery, portal identity, provider operations, source proxy, research corpus, court/judge masters, and billing controls.
- Introduce neutral shared foundations only where the PRD proves no reusable owner exists, and keep their APIs/metrics/retention outside `services/ip/`.

Forbidden duplicate components include `ip_tasks`, `ip_hearings`, `ip_intake_records`, `ip_conflict_checks`, `ip_access_grants`, `ip_portal_grants`, `ip_notices`, `ip_import_jobs`, `ip_payment_records`, `ip_disbursement_evidence`, a second legal-source master, a second email/OAuth/calendar connector, a second notification dispatcher, a second provider-operations/readiness/cost dashboard, and a second drafting or report engine.

If a requested implementation conflicts with this ownership contract, park only the conflicting node, write an ADR/gap analysis, and continue every independent node, including non-conflicting work from the same slice. Convenience, naming purity, or avoiding a difficult migration is not sufficient justification for a duplicate.

## Continuous Program Workflow

Apply this loop to coherent changes while batching shared orientation, system verification, documentation generation, and release across compatible slices:

1. **Orient once, then by delta:** inspect current `main`, worktree status, relevant owners, tests, migrations, OpenAPI, deployed revision, jobs, and prior manifest/evidence entries at run start; repeat only the affected checks after material state changes.
2. **Trace:** name requirement IDs, journey steps/exceptions, milestone exit criteria, personas, capabilities, entitlements, rollout flags, data classes, and source/provider/legal dependencies.
3. **Classify ownership:** record `NEW`, `EXTEND`, `LINK`, or `REPLACE`; identify the canonical writer, compatibility path, one-writer switch, reconciliation, rollback, and retirement gate.
4. **Design affected layers:** define schema/API/UI/job/security/observability/data-migration impact and explicit non-goals. For legal state, define command, source/evidence, concurrency token, outbox effects, and compensation. Do not require a separate document for unchanged layers.
5. **Implement end to end:** persistence, constraints, service, API, generated client types, UI, accessibility, audit, metrics, jobs, flags, migration/backfill, rollback, and documentation. Do not leave TODO placeholders for required behavior.
6. **Test focused behavior:** unit, database, API, frontend, provider/legal fixtures, security and focused E2E, including every exception named by the mapped journey.
7. **Integrate continuously:** combine compatible completed changes, resolve ownership/migration conflicts, and run change-aware checks as the candidate evolves.
8. **Test each exact candidate:** run the full applicable gates, migration upgrades, cross-owner reconciliation, representative data tests, impacted UJ regressions, and desktop/mobile visual inspection on the integrated candidate. Any code, dependency, runtime configuration, migration, fixture, test, or generated-artifact change creates a new exact candidate and reruns its applicable gates; evidence/prose-only changes use change-aware validators, and administrative boundaries alone do not trigger the full matrix.
9. **Generate evidence in a batch:** attach commands/results/screenshots/evidence, update canonical status from evidence, regenerate views, and record remaining risk at integration/release checkpoints.
10. **Release safely as a train:** use expand/backfill/verify/switch/contract; test mixed revisions, flags, worker fencing, and rollback for the compatible batch.
11. **Verify deployed truth:** identify exact commit/image/schema/job revisions and rerun the dated workflow against the actual target. A local or CI pass is not production evidence.
12. **Continue automatically:** an incomplete or externally blocked slice remains truthfully open, but it does not stop independent nodes or require a handoff before more work proceeds.

## Implementation Quality Requirements

### Backend and database

- Follow existing FastAPI, SQLAlchemy, Pydantic, Alembic, service, RFC 7807, request-ID, capability, session-context, and audit conventions.
- Use `company_id` filtering on every tenant read/write and composite company-matched foreign keys where the repository pattern supports them.
- Add database constraints for tenant matching, lifecycle invariants, one active identifier/assignment/correlation, money non-negativity, immutable versions, and valid target combinations.
- Use timezone-aware UTC instants while preserving legal local date, session/time precision, timezone, and source precision.
- Use integer minor units plus currency. Never replace original-currency evidence with a converted number.
- Require `expected_updated_at` for ordinary concurrent edits and expected state/lifecycle version for legal commands.
- Generic PATCH, import, worker, connector, document-processing, task, or AI routes cannot mutate terminal lifecycle state, filing/service acceptance, legal deadline confirmation, or rule activation.
- Legal commands lock and validate the parent, write state/event/audit/outbox atomically, and recover side effects idempotently.
- Every new table/store/field class is registered in the data map with retention, hold, export, purge, restore and projection handling before release.

### Frontend and user experience

- Build the actual working experience, not a marketing shell inside the authenticated app.
- Use the existing CaseOps shell, typography, controls, icons, spacing, accessibility and responsive conventions.
- Keep shared work visible through the existing Calendar, Today, Notices, Intake, Research, Drafting, Portal, Provider Operations, Billing and report surfaces with IP filtering/adapters.
- Support loading, populated, empty, no-results, validation, stale, provider-unavailable, permission-denied, partial-success, conflict and retry states.
- Display canonical CaseOps state and raw registry/provider state separately with source/freshness.
- Never expose restricted record existence through counts, autocomplete, errors, report totals, source actions, assistant citations or loading behavior.
- Verify keyboard navigation, focus, labels, contrast, screen-reader semantics, zoom, mobile layout, long identifiers, long party/mark names, tables, dialogs and downloadable artifacts.
- Do not ship nonfunctional buttons, placeholder cards, dead links, fake data, or actions available only visually but not authorized server-side.

### Integrations and asynchronous work

- Use approved external schedulers/durable workers, transactional outbox, idempotency, retries, leases/fencing, bounded replay, dead-letter handling, cost/quota limits, kill switches and safe operator visibility.
- No in-process scheduler and no direct external send outside the canonical notification/provider owner.
- Provider acceptance is not legal acceptance or recipient delivery.
- Preserve raw provider identity/hash and normalized evidence separately. A provider or AI result proposes legal effects unless an approved deterministic policy permits automation.
- Contract tests cover success, no change, duplicate, out-of-order, auth failure, rotation, disconnect, rate limit, quota, timeout, malformed/schema-changed payload, provider outage, webhook forgery/replay and protected download.

## Exhaustive Testing Contract

Do not leave a single required flow or named exception untested.

### Requirement and journey coverage

- Map and verify every PRD requirement ID. The baseline contains 436 IDs across 50 families; re-count after any approved PRD change.
- Represent UJ-01 through UJ-68 normal paths and every stated exception as atomic manifest rows with stable test IDs. One checkbox per journey is insufficient.
- Automate every required journey path and exception. A single test may cover several rows only when it contains explicit assertions and evidence for each mapped row.
- Add child-PRD journeys and exception coverage for every M8-M10 domain. Generic `asset_type` tests do not count as patent/design/copyright/GI/plant-variety/layout/trade-secret/domain/customs/licensing coverage.
- Each journey test must state actor, capabilities, tenant/record scope, preconditions, fixture IDs, steps, expected API/database/UI/audit/job effects, rollback/cleanup, and evidence.
- Test cross-journey interactions: intake to IP/Matter, application to opposition, registry event to deadline/task/notification, notice to legal deadline, document to draft/filing, tracked court case to linked IP proceeding, cost to Matter invoice/spend, report/portal publication, access revocation, restore and migration.
- Coverage percentages, generated test names, shallow render tests, snapshot-only tests, screenshots without assertions and mocked success responses do not prove journey coverage. Critical legal calculations, normalization, deduplication, authorization and lifecycle transitions require invariant, boundary and adversarial assertions; use property or mutation testing where it materially raises confidence.

### Test layers

Run all layers required by PRD Section 26:

1. Unit tests.
2. PostgreSQL database constraints and migrations, not SQLite-only proof.
3. API and OpenAPI/generated-client contract tests.
4. Provider/connector contract tests.
5. Versioned synthetic/draft legal-rule/form/fee/workflow fixtures during implementation, with lawyer-approved golden fixtures required before authoritative activation, legal verification, or completion.
6. Frontend component tests.
7. Full browser E2E.
8. Security and abuse-case tests.
9. Performance/load/query-plan tests.
10. Backup/restore, worker-fencing and degraded-operation tests.
11. Exact deployed production/pilot smoke where authorized.
12. Ownership/duplicate-writer/reconciliation tests.

### Mandatory test-data coverage

Create deterministic, anonymized fixtures covering at least:

- Two companies with overlapping names/identifiers and zero cross-company visibility.
- Owner, Admin, Partner, Member, Paralegal, Viewer, custom Docketing, finance, auditor, portal, inactive and emergency-access identities.
- Open, restricted, ethical-wall, mixed-target, revoked, expired, transferred and portal-published records.
- Trademark word/device/label/colour/shape/sound/3D/series records; single/multi-class; partial accepted/refused/opposed goods/services; long Unicode/transliterated names; duplicate/collision identifiers.
- Draft, filing-ready, filed, formalities, examination, objected, accepted, published, opposed, registered, renewal/grace, refused, abandoned, cancelled, transferred and expired lifecycle paths.
- Application, registration, opposition, rectification, appeal, CNR and court identifiers, including pending allocation, malformed values, collisions and retired identifiers.
- Applicant- and opponent-side proceedings, service defects, translation, extensions, evidence elections, adjournment, non-appearance, order, appeal, settlement and withdrawal.
- Holidays, exceptional working days, closures, uncertain triggers, conflicting sources, backdated events, extensions, manual overrides and stale rule/calendar versions.
- Exact-time, session-only and unpublished-time hearings; reschedule/cancel; next-hearing suggestion accept/reject; duplicate reminder and suppressed/bounced delivery.
- `CompanyNotice` received/sent, zero/multi-Matter/IP links, restricted links, reply required/sent/overdue, immutable evidence supersession, claim amounts and correlated legal deadlines.
- Communication/email/calendar/Drive/manual duplicates, malformed/encrypted/malicious files, large archives, low OCR, sanitized display, privilege and mailbox disconnect.
- Existing `TrackedCase`/bookmark/update/poll/Matter court records linked to IP without copied snapshots.
- IP registry no-change/change/conflict, stale/auth/rate/parse failure, corrected snapshot, replay and kill-switch behavior.
- One `ip_cost_item` linked to proof, billing Matter, manual invoice line and outside-counsel spend where applicable, including currency conversion, estimated vs actual, void/write-off and no-double-count reports.
- Imports with valid, invalid, duplicate, partial-success, stale-preview, retry, cancellation, large file, formula injection, cross-tenant reference and legacy Matter/Employee aggregated history.
- Public verified/quarantined statutes and authorities, broken/protected sources, Indian Kanoon/eCourts attribution, exact citations, no-result vs unavailable/error and judge remapping.
- AI cited/abstained/contrary-source/prompt-injection/revoked-source cases, inaccessible records, stale saved output and model/provider failure.
- Legal holds, export/purge dry run, manifest change, injected subsystem failure, backup tombstone, restore, mixed revisions, stale workers and credential rotation/disconnect.
- Type-specific M8-M10 synthetic/draft fixtures may drive implementation; specialist-approved golden fixtures are required before authoritative activation, domain verification, or completion. Trademark fixtures cannot stand in for another right.

Use factories/builders and stable seed manifests. Do not put real client secrets or uncontrolled personal data into the repository. Record expected row counts, unique keys, hashes, source versions, calculations, report totals and access outcomes. Validate post-migration and post-restore data against those expectations.

### E2E expectations

- Use the real application, live API and PostgreSQL database with production-shaped storage/job adapters. Mock only at a documented external contract boundary; prefer approved deterministic record/replay fixtures and run separately authorized provider smoke tests.
- Use throwaway tenants, sandbox accounts and reversible fixtures. Never test destructive flows against production customer records.
- Cover Chromium and the repository's supported browser set. Test desktop and narrow mobile viewports for every changed user-facing workflow.
- Assert visible text, state, layout, enabled/disabled actions, persistence after reload, source/download opening, URL/navigation, audit evidence and backend/database effects.
- Include failure injection for provider outage, delayed worker, duplicate webhook, stale write, permission revocation mid-session/stream, migration rollback, notification suppression, object missing and index lag.
- Capture screenshots/videos/traces for milestone UAT and failures. Inspect them; artifact generation alone is not review.
- No skipped, focused, quarantined or flaky test may silently satisfy a gate. Every skip has an owner, reason, expiry and blocks the milestone when it covers a required path.
- Run focused journey tests while developing, the impacted full journey set on the integrated candidate, and exact-boundary verification after migration/deployment. Do not rerun an unchanged full set solely because code crossed merge or another administrative checkpoint.

### Standard repository gates

Run focused tests while developing and all applicable full gates once for the integrated release candidate before merge, including the commands named in PRD Section 26.3:

```powershell
git diff --check
npm run lint:api
npm run test:api
npm run test:functional-qa-runner
npm run typecheck:web
npm run test:coverage --workspace @caseops/web
npm run build:web
npm run test:e2e:app
npm run gen:api-types --workspace @caseops/web
```

Also run PostgreSQL migration/constraint tests, provider contract tests, security tests, performance tests, recovery drills, production build, the program-manifest validator and any additional commands discovered in current CI/package configuration. Do not omit a failing baseline silently: determine whether it is pre-existing, affected or confidence-blocking and record evidence. A failure labelled pre-existing still blocks the slice when the slice touches its behavior or prevents reliable verification.

## Data Verification and Migration Rules

- Use expand, backfill, verify, switch and contract phases.
- Every Alembic revision upgrades from the actual current production head and is compatible with old/new serving and job revisions during its declared window.
- Backfills are resumable, bounded, company-scoped, dry-run capable, idempotent, observable and independently reconcilable.
- Do not make a parent FK nullable before company ownership is backfilled and company-matched constraints are tested.
- Do not call external providers during a backfill unless explicitly designed, cost-approved and authorized.
- Preserve original Matter/import/notice/communication/court/provider/legal evidence and immutable hashes. Migrations add links/projections; they do not fabricate provenance.
- Compare pre/post row counts, per-company counts, orphan checks, duplicate keys, lifecycle/event reconciliation, deadline correlations, source/document hashes, object existence, search generations, notification/provider pending effects and report totals.
- Test upgrade from sanitized production-shaped data, downgrade or roll-forward/restore, mixed revisions, interrupted/resumed backfill, duplicate execution and rollback after a committed legal event.
- Destructive cleanup occurs only after all old revisions/jobs are retired, reconciliation is accepted, the rollback window closes and legal hold/retention permits it.

### Legal source and dataset verification

- Maintain versioned source/dataset manifests for statutes, rules, forms, fees, authorities, registry/court mappings and provider-derived records. Record provenance URL/contract, source authority, permitted use, attribution, effective/as-of date, retrieval time, object/row count, checksum, parser version, coverage, quarantine reason and supersession.
- Separate deterministic fixture correctness from pilot/production data coverage. Synthetic green tests cannot establish that the hosted corpus is complete, current or licensed.
- For every release that changes legal/reference data, produce coverage, missing/empty/mismatch, duplicate, quarantine, stale-source and reconciliation reports. Sample and open source/deep links through the actual authorized user path; verify title, citation, content hash, source, freshness, access behavior and broken/protected-link handling.
- Do not scrape, republish or label a source official without verified terms and approval. Keep uncertain, prohibited, malformed or unverifiable content quarantined and excluded from authoritative/AI use.
- Validate legal deadlines, fees, forms, reports and imports against approved golden fixtures with boundary dates, version cutovers, amendments, overrides and independently calculated expected values. Require named IP/legal reviewer approval before activation.
- Use anonymized production-shaped migration previews and tenant-level reconciliation/signoff for customer data. "Test all data" means every relevant data class, state, boundary, relationship and invariant plus approved aggregate reconciliation; it does not authorize indiscriminate access to real client data.

## Documentation and Landing-Page Contract

Documentation is part of the program, not a final cleanup epic. Update touched canonical sources with the implementation and batch generated views, exhaustive render/link checks, and public-claim verification at integration/release checkpoints.

Update all applicable artifacts when behavior changes:

- The PRD only through approved change control; ADRs; the canonical program manifest; and its generated implementation, ownership, traceability, data, documentation and release views.
- Root and app READMEs, setup/configuration, environment-variable references and contributor instructions.
- OpenAPI descriptions, generated frontend API types, schemas and example payloads.
- Architecture/domain diagrams, data dictionary, lifecycle/transition tables and event/audit catalogues.
- Migration, rollback, backfill, reconciliation, retention/hold/export/purge and recovery documentation.
- Provider setup, terms/attribution, readiness, support matrix, quota/cost, replay, kill-switch and credential-rotation runbooks.
- Notification, source trust, legal curation, incident response, security, privacy and support runbooks.
- Existing `/guide` content, searchable Product Guide corpus, in-product help/navigation actions, `llms.txt`, `llms-full.txt` and other maintained public product descriptions.
- API/reference documentation, release notes, changelog, support/training materials and pilot UAT scripts.
- Marketing and landing pages, product feature pages, pricing/packaging and screenshots where the released capability changes public claims.
- Generated PDFs/reports, document downloads, notification/email templates, onboarding/demo content, sitemap, navigation/footer links, metadata and structured data where affected.

Landing pages and sales copy must be truthful and server-capability driven:

- Do not advertise roadmap schema, manual-only work, intake-only record types, disabled providers, incomplete legal data or beta behavior as GA.
- Label each IP domain `unavailable`, `intake-only`, `beta` or `GA` from server-side capability evidence.
- Do not describe a commercial provider as an official government API.
- Do not publish unsupported coverage counts, delivery claims, AI accuracy, recovery promises or source-authority claims.
- Publish positive live/support claims only after the corresponding behavior is verified and enabled. Update truthful `unavailable`/`intake-only`/default-off documentation with the implementation candidate, and remove or qualify stale claims in the same release.
- Use real product screenshots/data-safe demos of the implemented experience. Verify landing and documentation pages on desktop/mobile with Playwright, links, metadata, accessibility and production build.
- Drive public capability labels and claims from a versioned release-capability manifest tied to the deployed revision, flags and entitlements. A frontend-only label is not evidence.
- Inventory every impacted public route, feature comparison, pricing/FAQ entry, navigation/footer link, screenshot/demo, SEO field and `llms` description. Review each as updated or reviewed-no-change; do not churn unrelated pages merely to claim that "all documents" were touched.
- Do not expose client data, restricted identifiers, secrets or misleading seeded records in screenshots, demos, downloads or public indexing.

The generated documentation view must show every impacted artifact as updated or reviewed-no-change with owner and evidence. The integrated candidate is incomplete when changed surfaces lack matching public/product/operational documentation; compatible slices may batch that documentation at the integration checkpoint.

## Security, Legal and AI Gates

- Enforce company, active membership, capability, entitlement, rollout, client/record, ethical-wall, document, portal and source access server-side.
- Reuse recent step-up and four-eyes rules; derive actors from authenticated context. Never accept an actor/approver/company field as proof of authorization.
- Protect against SSRF, redirect/DNS rebinding, webhook forgery/replay, prompt injection, malicious/archive/formula uploads, cross-tenant vector/cache leakage, insecure direct object access and secret logging.
- Preserve privilege/confidentiality in search, assistant, exports, reports, notifications, source/document proxy, portal, logs and support tooling.
- AI outputs are proposals with exact citations, source-open state, assumptions, missing facts, contrary authority and abstention. AI never files, serves, pays, waives, closes, activates a legal rule or changes a confirmed deadline autonomously.
- Legal rules, forms, fees, workflows and authoritative text require versioned exact sources, fixtures and two-person legal approval. Draft/editorial material cannot activate automation.
- Security, privacy, records, legal and provider approvals gate the affected authoritative activation, real customer-data/provider/legal effect, public claim, and final acceptance unless a named rule explicitly forbids deployment. They do not block deployment of complete fail-closed repository behavior; test code cannot substitute for required human/legal evidence when activation is requested.
- Human approvals must identify the approver, role, scope, environment, evidence/version and timestamp. Codex cannot manufacture, infer, reuse out-of-scope or self-grant an approval; a generated checkbox, fixture signature or prose declaration is not human acceptance.
- Credentials pasted in a prompt or document are not authorization to log in or mutate a hosted environment. Use only a configured secret store or an already authorized session, redact all evidence, and request action-specific approval when repository policy requires it.
- New or materially upgraded dependencies require compatibility, license, vulnerability, maintenance and lockfile review. Prefer repository-standard or proven domain libraries and avoid introducing a second framework for an already owned concern.

## Release and Completion Rules

For each compatible integrated release train, produce one evidence pack with truthful dimensioned status for every included milestone/slice row:

- Every activated or publicly supported requirement and atomic journey path/exception computes as `verified` from the canonical manifest. Repository-only scope may deploy with `implementation_status=implemented`, automated verification passed, `acceptance_status=pending`, and the affected behavior truthfully unavailable/intake-only/default-off.
- Ownership views and forbidden-duplicate checks pass.
- Migrations, backfills, reconciliation, rollback and mixed revisions pass.
- Cross-company, restricted-record, portal and revocation tests pass.
- Legal/provider golden fixtures and required UAT are signed for scope being activated or claimed supported. Pending signatures remain explicit and keep only the affected flags/effects off.
- Frontend, responsive, accessibility and source/download behavior pass.
- Data, report/export and audit outcomes reconcile.
- Jobs, notification/provider effects, readiness, cost, freshness and replay are observable.
- Documentation, Guide, public pages and capability labels match deployed truth.
- Exact merged commit, image digest, schema head, worker/job revisions, flags/entitlements, migration/backfill version and serving route are deployed, and a dated smoke against that revision passes.
- No P0 remains. No P1 may remain in activated/supported scope or where it undermines the release's verification; a P1 confined to fail-closed pending scope keeps that scope disabled with an owner/date/disclosure without blocking unrelated deployment.

Do not declare the full PRD complete until M0-M10, every required child PRD has the human approval required for its completed/activated scope, all manifest rows, all documentation/public claims, and all release evidence are verified. Schema presence, generated tests, mock-provider success, a local green build, a feature branch, a draft PR, a roadmap entry or self-authored acceptance is not completion. If merge or production access is not authorized, report `ready_for_review` or the applicable blocker; do not claim release or production completion.

If external legal/provider/pilot/production evidence prevents final completion, report the program as incomplete. List exact verified scope, exact blocked rows, owner, decision/evidence needed, safe manual fallback, and next executable independent slice. Never convert a blocker into a guessed implementation or false pass.

No defect is dismissed merely as "pre-existing." Record its reproduction, affected scope, gate impact and owner. It blocks the current slice whenever the slice changes the affected surface, the failure prevents trustworthy verification, or severity meets the release threshold.

## Required Progress Updates

While executing:

- Provide concise, event-driven updates and a heartbeat at least every 60 seconds during long work; do not pause implementation to produce ceremonial status reports.
- State what existing owner was found, what is being changed, and why.
- Update the implementation plan and canonical manifest when evidence or execution state changes materially.
- Surface unexpected user changes and work with them; never revert them.
- Do not stop at a proposal when implementation and verification can continue.

## Progress and Final Response

Do not stop the run for a full per-slice handoff. At integration/release checkpoints and in the final response, report a consolidated table or equivalent that preserves each slice's evidence:

1. Slice and mapped requirement/journey IDs.
2. What changed and canonical owners used.
3. Migrations/backfills and compatibility/rollback status.
4. Tests run with exact pass/fail/skip counts and data sets.
5. Visual/E2E/deployed evidence and exact revision when applicable.
6. Documentation, Guide and landing/public-page updates.
7. Program-manifest and generated traceability/data-view changes.
8. Remaining defects, blockers, risks and next slice.

Do not hide skipped tests, missing providers, unavailable production access, legal-review gaps, stale deployed revisions or pre-existing failures.

## Start Now

1. Read `AGENTS.md` and the complete PRD.
2. Inspect current `main`, worktree, migration heads, CI, deployment manifests, test commands and current implementation owners.
3. Recount requirement IDs, journeys, and atomic exceptions; repair the existing canonical manifest, validator, and generated views mechanically without deleting existing documentation or hand-decorating status tables.
4. Start the Phase 0/M1 trust and scheduler-control work immediately. In parallel, start every dependency-independent M2-M10 implementation, test, fixture, documentation, and default-off integration node.
5. Follow the actual dependency edges in PRD Section 25.1, not a global milestone waterfall. Record an external blocker, keep the affected activation disabled, and continue every other ready node without asking for a routine decision.
6. Integrate compatible work through the smallest practical number of branches, PRs, and release trains. Run focused checks continuously and one complete applicable matrix on each exact integrated candidate; code, dependency, runtime configuration, migration, fixture, test, or generated-artifact changes create a new candidate, while evidence/prose-only changes use change-aware validators.
7. Persist checkpoints automatically at material state changes and before risky release actions, then continue through review, merge, deploy, and exact-revision production verification until all repository-controlled work is complete or only genuine external authority remains.

## Prompt Review Record

This version has been reviewed specifically for execution failure modes: duplicate ledgers, paperwork-only progress, scope erosion, self-approved legal/security gates, unsafe production authority, unaudited legal data, synthetic-data overclaiming, untruthful public copy, shallow journey tests, skipped/flaky-test leakage, branch-versus-release confusion, child-PRD self-approval, false completion at a context boundary, and unnecessary serial/manual gates. Substantive security, legal-integrity, data-protection, truthful-completion, and irreversible-action controls take precedence over looser wording. The continuous-execution rules above control scheduling, PR/release granularity, checkpoint frequency, and whether a missing external acceptance pauses repository implementation.

## Execution checkpoint — 1 August 2026

The product owner removed the fixed wait for “seven consecutive days of natural scheduler health.” The active release gate is exact-revision/IAM/config verification, bounded scheduler-to-job canaries, health checks, and a dated production journey; natural executions continue as SLO evidence.

The fifteen slices currently decomposed in `PROGRAM_MANIFEST.yaml` have repository implementations. The five tails that an earlier release record left open—`IPLF-007B`, `IPLF-039B`, `IPLF-039C`, `IPLF-039E`, and `IPLF-039F`—were implemented and then production verified on 2 August 2026 as described in `docs/ip-implementation/evidence/release-2026-08-01-completion.md`. Exact-commit CI, schema migration, immutable scheduler convergence, 100% API/web traffic, health, and authenticated dated production E2E passed; their manifest release state is `deployment_verified`. Human acceptance remains pending.

This checkpoint does not revise the PRD or mark the program complete. The 436 requirement rows, 68 journeys, undecomposed M0/M2-M10 epics, legal/provider fixtures, data-governance and recovery gates, pilot UAT, and specialist child PRDs remain governed by the canonical manifest and the completion rules above. Implemented slice breadth must not be represented as full-program delivery.

---

End of master prompt.
