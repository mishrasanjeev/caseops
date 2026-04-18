# CaseOps Goal Backlog

**Date:** 2026-04-18  
**Purpose:** Execution backlog to reach the stated founder goal:

1. complete product
2. resilient product
3. demonstrably better-than-expert-lawyer output
4. enterprise-grade product
5. zero user-facing dependency on `/legacy`

This backlog is stricter than `docs/WORK_TO_BE_DONE.md`.

- `WORK_TO_BE_DONE.md` is the engineering gap register.
- This file is the founder execution backlog.
- Anything that still routes the user to `/legacy` is treated here as a top-priority product debt item, even if the engineering work exists in partial form elsewhere.

## Non-Negotiable Exit Criteria

The product is not "done" against the stated goal until all of these are true:

1. No customer-facing workflow depends on `/legacy`.
2. No top-level navigation item is a preview stub.
3. No core legal output can be surfaced without evidence-backed grounding or an explicit refusal.
4. There is benchmark evidence, against expert-lawyer baselines, across research, drafting, hearing prep, recommendations, and contract review.
5. Enterprise controls exist for identity, audit, model policy, secrets, observability, backup/restore, and deployment.

## Current `/legacy` Dependencies To Eliminate

These are the live product handoffs currently blocking a clean product:

| Surface | Current dependency | Source |
| --- | --- | --- |
| Workspace bootstrap | "New firm?" sends user to `/legacy` | `apps/web/app/sign-in/SignInForm.tsx` |
| Contracts | Buttons route to `/legacy` for authoring | `apps/web/app/app/contracts/page.tsx` |
| Outside counsel | Buttons route to `/legacy` for assignment and spend logging | `apps/web/app/app/outside-counsel/page.tsx` |
| Matter documents | Empty state tells user to use legacy for upload | `apps/web/app/app/matters/[id]/documents/page.tsx` |
| Matter hearings | Cause-list import depends on legacy-triggered sync | `apps/web/app/app/matters/[id]/hearings/page.tsx` |
| Matter billing | Invoice issue and time logging still depend on legacy | `apps/web/app/app/matters/[id]/billing/page.tsx` |

## Priority Model

- `P0`: trust, correctness, or product-integrity blockers
- `P1`: required to remove `/legacy` and ship a complete founder-stage product
- `P2`: required to prove quality and reach enterprise readiness
- `P3`: scale and expansion after the enterprise baseline is real

## P0 - Trust And Product Integrity

### BG-001 - Fix recommendation fail-open when retrieval is empty

- **Why:** recommendation output can still persist without verified citations when no authority is retrieved.
- **Done when:**
  - recommendation generation refuses whenever verified citation count is zero, regardless of whether retrieval was empty or non-empty
  - refusal is tested for both "retrieval returned documents but none verified" and "retrieval returned nothing"
  - refusal copy is clear in the UI

### BG-002 - Fix option-level citation attribution in recommendations

- **Why:** if two options cite the same authority, the current verifier can assign that citation only to the last option.
- **Done when:**
  - verification preserves shared citations across all qualifying options
  - tests cover duplicate-citation, mixed-citation, and contradictory-option cases

### BG-003 - Show draft validator findings to the reviewer

- **Why:** the backend appends quality findings to `DraftVersion.summary`, but the draft-detail UI never renders them.
- **Done when:**
  - draft detail renders validator findings prominently
  - findings are visually separated into blocker vs warning
  - reviewers cannot miss them during approve/finalize flow

### BG-004 - Fix audit export semantics and policy mismatch

- **Why:** current end-date semantics exclude most of the selected day; UI copy says "admin or owner" while capability enforcement is owner-only.
- **Done when:**
  - `until` semantics include the full selected day
  - UI copy, backend capability table, and tests all agree on who can export
  - async and sync export paths share the same range semantics

### BG-005 - Standardize legal date rendering

- **Why:** date-only legal fields can render one day early in some timezones.
- **Done when:**
  - all SQL `Date` fields use one shared formatter
  - no `new Date("YYYY-MM-DD")` remains on date-only legal fields
  - regression tests cover at least one U.S. timezone and one India timezone

### BG-006 - Remove internal roadmap leakage from customer-facing UX

- **Why:** product surfaces currently expose preview badges, roadmap references, section references, and placeholder links.
- **Done when:**
  - no production UI mentions `WORK_TO_BE_DONE.md`, section numbers, "legacy console", or "preview"
  - no customer-facing button points to placeholder destinations
  - marketing copy only claims shipped capability

### BG-007 - Make solo practitioner a first-class company type

- **Why:** the PRD treats solo as a first-class user segment, but the schema only supports `law_firm` and `corporate_legal`.
- **Done when:**
  - `solo` is a real company type across schema, API, onboarding, analytics, and UI
  - persona tests stop faking solo as `law_firm`

## P1 - Remove `/legacy` Without Product Compromise

### BG-010 - New-app workspace bootstrap and onboarding

- **Why:** sign-in currently sends new firms to `/legacy`.
- **Done when:**
  - new company creation, email verification, initial admin creation, and onboarding wizard all exist in the new app
  - the sign-in page no longer links to `/legacy`
  - bootstrap covers law firm, corporate legal, and solo paths

### BG-011 - Full contracts workspace in the new app

- **Why:** contracts still rely on classic authoring.
- **Done when:**
  - create contract
  - upload attachments
  - clause extraction
  - playbook comparison
  - redline/review surface
  - obligation tracking
  - no button or empty state routes to `/legacy`

### BG-012 - Full outside-counsel management in the new app

- **Why:** assignment and spend logging still require `/legacy`.
- **Done when:**
  - create/edit outside counsel profiles
  - assign counsel to matters
  - log spend
  - view matter-level and portfolio-level spend
  - recommendation evidence can rank counsel where applicable
  - no `/legacy` route remains in this flow

### BG-013 - Matter document upload and processing controls in the new app

- **Why:** matter documents view is read-only unless the user goes to legacy.
- **Done when:**
  - upload in the new cockpit
  - processing status, retry, and reindex actions in the new cockpit
  - secure download and lineage are visible in the new cockpit
  - OCR/parser failure reasons are visible

### BG-014 - Matter billing and collections in the new app

- **Why:** invoice issue and parts of collections still point to legacy.
- **Done when:**
  - create invoice
  - issue payment link
  - view collection state
  - void/cancel where policy allows
  - matter billing page is fully actionable without `/legacy`

### BG-015 - Matter timekeeping in the new app

- **Why:** time logging still depends on legacy.
- **Done when:**
  - create/edit time entries
  - billable vs non-billable handling
  - user/day/matter filters
  - invoice linkage from time entries

### BG-016 - Cause-list and court-sync actions in the new app

- **Why:** hearings surface still tells the user to run sync from legacy.
- **Done when:**
  - run court sync from the matter hearing page
  - track sync status and last run result
  - import cause-list items and orders without leaving the new app

### BG-017 - `/legacy` parity test suite

- **Why:** removing `/legacy` safely requires proof of replacement parity.
- **Done when:**
  - every replaced `/legacy` workflow has a new-app E2E test
  - parity checklist exists for bootstrap, contracts, outside counsel, documents, hearings sync, billing, and timekeeping

### BG-018 - Remove `/legacy` route from the product

- **Why:** the goal is zero user-facing dependence on `/legacy`.
- **Done when:**
  - no navigation, CTA, form, empty state, or docs route users to `/legacy`
  - `/legacy` is removed from product docs and public UX
  - product smoke tests no longer depend on `/legacy`

## P1 - Complete The Core Product

### BG-020 - Ship the research workspace

- **Done when:**
  - query input
  - filters
  - authority cards
  - contrary authorities
  - notebook/save-to-matter
  - source-linked answer surface

### BG-021 - Replace placeholder dashboard metrics with live, meaningful signals

- **Why:** current dashboard still contains placeholder cards and "coming soon" hints.
- **Done when:**
  - hearings, recommendations, and authority metrics are live
  - every dashboard card links to a real surface
  - no placeholder KPI remains

### BG-022 - Complete all top-level navigation surfaces

- **Why:** the product cannot be called complete while top-nav sections are stubs.
- **Done when:**
  - `Hearings`, `Research`, `Drafting`, `Recommendations`, `Portfolio`, and `Admin` are all real production surfaces
  - no `RoadmapStub` remains in authenticated product navigation

### BG-023 - Expand recommendation coverage to actual PRD breadth

- **Why:** shipped recommendation types are narrower than the PRD and narrower than current marketing claims.
- **Done when:**
  - recommendation types include remedy, next-best-action, and outside-counsel selection in addition to forum and authority
  - each type has evidence model, refusal logic, and review flow

### BG-024 - Ship judge and court intelligence surfaces

- **Done when:**
  - judge profile page
  - court profile page
  - lineage and source visibility
  - no favorability scoring

### BG-025 - Ship GC intake and legal-ops baseline

- **Done when:**
  - intake form
  - routing workflow
  - advice note linkage
  - GC dashboard baseline

### BG-026 - Expand roles and teams to PRD coverage

- **Done when:**
  - roles beyond owner/admin/member exist in schema and policy
  - teams/departments exist
  - UI capability gates match backend enforcement

## P2 - Make Legal Output Good Enough To Claim Superiority

### BG-030 - Finish target corpus ingestion for priority jurisdictions

- **Done when:**
  - Supreme Court plus priority High Courts reach the intended coverage window
  - ingestion quality and freshness are measurable

### BG-031 - Add matter-attachment embeddings and tenant overlays to retrieval

- **Done when:**
  - retrieval can combine public corpus, matter attachments, and tenant-private annotations
  - retrieval remains tenant-safe

### BG-032 - Add cross-encoder reranking

- **Done when:**
  - top-K authority retrieval is reranked by a higher-quality scorer
  - offline benchmark shows measurable recall/precision lift

### BG-033 - Upgrade document intelligence beyond heuristics

- **Done when:**
  - Docling/Tika/PaddleOCR live
  - contract extraction moves off regex heuristics
  - structural extraction is usable across judgments, orders, and contracts

### BG-034 - Build a real evaluation harness

- **Done when:**
  - benchmark runner exists outside mock mode
  - gold datasets exist for research, drafting, hearing prep, recommendations, and contract review
  - results are stored, comparable, and reportable

### BG-035 - Run expert-lawyer benchmark studies

- **Why:** "better than expert lawyer" is not a belief; it is a claim that needs evidence.
- **Done when:**
  - expert-lawyer baseline outputs are collected for target tasks
  - blind review protocol exists
  - model outputs are scored against expert outputs on legal correctness, citation quality, completeness, and usefulness
  - benchmark report exists and is repeatable

### BG-036 - Gate releases on legal-quality metrics

- **Done when:**
  - model/prompt changes cannot ship unless evaluation thresholds pass
  - citation precision, refusal behavior, and hallucination rates are part of release criteria

## P2 - Resilience And Enterprise Readiness

### BG-040 - Replace polling worker with Temporal workflows

- **Done when:**
  - long-running workflows use durable orchestration
  - retries, state transitions, and observability are workflow-native

### BG-041 - Generic task/deadline/reminder system

- **Done when:**
  - tasks and deadlines are first-class entities across hearings, drafts, intake, contracts, and follow-ups
  - reminders are delivered reliably

### BG-042 - OpenTelemetry and structured logging

- **Done when:**
  - traces exist for API, DB, worker, retrieval, and model calls
  - logs carry tenant, user, request, and matter context

### BG-043 - Backup/restore and disaster recovery proof

- **Done when:**
  - documented backup policy
  - restore drill passes
  - tenant-scoped export/import is verified

### BG-044 - Production CI/CD and secret management

- **Done when:**
  - image build/push
  - staged deploy
  - branch protection
  - secrets come from managed secret store, not manual env handling

### BG-045 - Identity and enterprise access controls

- **Done when:**
  - MFA
  - OIDC
  - SAML
  - JIT provisioning
  - role mapping
  - session and suspension behavior remain provable

### BG-046 - Tenant AI policy and governance controls

- **Done when:**
  - allowed models/providers
  - token budgets
  - external-share approvals
  - prompt/tool-call audit for admins

### BG-047 - Admin console and entitlements

- **Done when:**
  - tenant profile management
  - retention settings
  - deletion/export workflows
  - seat/matter/feature entitlements

### BG-048 - Malware and unsafe-upload controls

- **Done when:**
  - virus scanning is in the ingestion path
  - quarantine and audit flow exists

### BG-049 - Connector health and sync operations

- **Done when:**
  - connector status UI
  - last success/failure visibility
  - retry and operator workflow for court/email/calendar connectors

## P3 - Scale And Expansion

### BG-060 - Secondary jurisdiction rollout

- Tamil Nadu
- Gujarat
- broader lower-court depth

### BG-061 - Private inference and dedicated tenant deployments

- enterprise private inference
- dedicated adapters
- private networking patterns

### BG-062 - Additional integration coverage

- email ingest
- calendar sync
- broader billing/counsel connectors

## Recommended Execution Order

### Wave A - Product trust first

- BG-001
- BG-002
- BG-003
- BG-004
- BG-005
- BG-006
- BG-007

### Wave B - Kill `/legacy` with parity

- BG-010
- BG-011
- BG-012
- BG-013
- BG-014
- BG-015
- BG-016
- BG-017
- BG-018

### Wave C - Finish the actual product

- BG-020
- BG-021
- BG-022
- BG-023
- BG-024
- BG-025
- BG-026

### Wave D - Prove legal superiority

- BG-030
- BG-031
- BG-032
- BG-033
- BG-034
- BG-035
- BG-036

### Wave E - Enterprise grade hardening

- BG-040
- BG-041
- BG-042
- BG-043
- BG-044
- BG-045
- BG-046
- BG-047
- BG-048
- BG-049

## What I Would Do First

If the goal is aggressive but realistic, the first 10 backlog items to execute are:

1. BG-001
2. BG-002
3. BG-003
4. BG-005
5. BG-010
6. BG-013
7. BG-014
8. BG-015
9. BG-011
10. BG-017

Reason:

- They fix immediate trust defects.
- They break the biggest `/legacy` product dependencies.
- They move the product from "hybrid old/new shell" to a single coherent system.

