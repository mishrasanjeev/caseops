# CaseOps Founder Execution Plan

**Date:** 2026-04-18  
**Source backlog:** `docs/GOAL_BACKLOG_2026-04-18.md`  
**Planning goal:** reach a complete, resilient, zero-`/legacy`, quality-proven, enterprise-ready product.

## Planning Assumptions

- Sprint length: 2 weeks
- Estimate model: one focused founder-stage team, not a large organization
- Baseline staffing for this plan to be realistic:
  - 1 strong full-stack lead
  - 1 frontend/product engineer
  - 1 backend/infra engineer
  - founder/legal reviewer available continuously for acceptance and benchmark review
- If you have fewer people than this, sequence stays valid but calendar expands.
- If you have more people, some sprints below can be parallelized, but the dependency order should not be broken.

## Delivery Strategy

This plan has four hard milestones:

1. **M1 - Single-shell product**
   - no customer-facing dependency on `/legacy`
2. **M2 - Complete v1 product**
   - all top-level navigation is real
   - no preview-only product spine
3. **M3 - Quality-proven legal engine**
   - benchmarked against expert-lawyer baselines
4. **M4 - Enterprise pilot readiness**
   - identity, governance, observability, backups, deployment, and admin controls are credible

## Critical Path

The order that must not be violated:

1. Fix trust defects first.
2. Replace `/legacy` workflows before removing `/legacy`.
3. Complete real product surfaces before claiming completeness.
4. Finish retrieval, corpus, and evaluation before claiming better-than-expert quality.
5. Finish identity, governance, observability, backup/restore, and deployment hardening before calling it enterprise-ready.

## Calendar Summary

- **Baseline duration:** 16 sprints = 32 weeks
- **Aggressive duration with parallel work:** 10-12 sprints = 20-24 weeks
- **Do not compress by skipping milestone gates.**

## Sprint Plan

### Sprint 1 - Trust Patch Pack

- **Backlog IDs:** BG-001, BG-002, BG-003, BG-004, BG-005
- **Objective:** remove the highest-risk shipped defects in AI trust, reviewer workflow, audit correctness, and legal dates
- **Dependencies:** none
- **Deliverables:**
  - recommendation refusal fixed for empty retrieval
  - shared-citation bug fixed
  - draft validator findings visible in UI
  - audit export date semantics fixed
  - audit export policy/copy aligned
  - shared legal-date formatter applied across product
- **Gate:** there is no known shipped path where legal AI output can quietly surface without evidence or where a legal date can render one day wrong

### Sprint 2 - New Bootstrap And Document Controls

- **Backlog IDs:** BG-006, BG-007, BG-010, BG-013
- **Objective:** remove the most visible product-integrity leakage and stop forcing new users into `/legacy`
- **Dependencies:** Sprint 1
- **Deliverables:**
  - new company bootstrap and onboarding in the new app
  - sign-in no longer routes new firms to `/legacy`
  - `solo` becomes a first-class company type
  - matter document upload, retry, reindex, and download all work in the new cockpit
  - internal roadmap and placeholder leakage removed from user-facing copy
- **Gate:** a new customer can create a workspace and upload matter documents without touching `/legacy`

### Sprint 3 - Billing And Timekeeping Parity

- **Backlog IDs:** BG-014, BG-015
- **Objective:** remove the billing/timekeeping dependency on `/legacy`
- **Dependencies:** Sprint 2
- **Deliverables:**
  - invoice create flow in the new app
  - Pine Labs payment-link issue flow in the new app
  - invoice state and collection state visible in the new app
  - time entry create/edit/filter/linkage in the new app
- **Gate:** matter billing tab is operational, not read-only

### Sprint 4 - Hearings Sync And Outside Counsel Parity

- **Backlog IDs:** BG-012, BG-016
- **Objective:** remove two more operational `/legacy` handoffs
- **Dependencies:** Sprint 2
- **Deliverables:**
  - outside counsel create/edit/profile flow in the new app
  - assignment and spend logging in the new app
  - court-sync run action from hearing page
  - sync status, last run result, and imported cause-list/orders visible in the new app
- **Gate:** matters can be synced and counsel can be managed without `/legacy`

### Sprint 5 - Contracts Parity

- **Backlog IDs:** BG-011
- **Objective:** replace the last major `/legacy` workflow
- **Dependencies:** Sprint 2
- **Deliverables:**
  - contract create/upload
  - clause extraction
  - playbook comparison
  - redline/review surface
  - obligation tracking
- **Gate:** contracts page is operational, not a list plus redirect

### Sprint 6 - `/legacy` Removal And Parity Proof

- **Backlog IDs:** BG-017, BG-018
- **Objective:** remove `/legacy` without product regression
- **Dependencies:** Sprints 2-5
- **Deliverables:**
  - parity E2E suite for all replaced flows
  - no CTA, empty state, nav, sign-in, or docs route points to `/legacy`
  - `/legacy` removed from product docs and smoke tests
- **Gate:** **M1 reached**
  - no customer-facing dependency on `/legacy`

### Sprint 7 - Research Workspace And Real Dashboard

- **Backlog IDs:** BG-020, BG-021
- **Objective:** move from shell-plus-cockpit to real day-to-day legal work
- **Dependencies:** Sprint 6
- **Deliverables:**
  - research query surface
  - filters
  - source-linked authority cards
  - contrary authorities
  - save-to-matter/notebook flow
  - dashboard metrics all live and meaningful
- **Gate:** research is a real product surface, not a placeholder

### Sprint 8 - Complete Core Navigation

- **Backlog IDs:** BG-022, BG-025, BG-026
- **Objective:** remove preview-only authenticated surfaces and fill out core role and intake model
- **Dependencies:** Sprint 7
- **Deliverables:**
  - remaining top-level nav sections become real
  - GC intake and legal-ops baseline shipped
  - roles expanded beyond owner/admin/member
  - teams/departments wired through policy and UI
- **Gate:** top-level nav no longer contains product stubs

### Sprint 9 - Full Recommendation And Court Intelligence

- **Backlog IDs:** BG-023, BG-024
- **Objective:** align decision-support breadth with PRD and product claims
- **Dependencies:** Sprint 8
- **Deliverables:**
  - remedy recommendations
  - next-best-action recommendations
  - outside-counsel recommendations
  - judge and court profile surfaces
- **Gate:** **M2 reached**
  - complete v1 product spine exists in one coherent application

### Sprint 10 - Corpus Depth And Retrieval Lift

- **Backlog IDs:** BG-030, BG-031, BG-032
- **Objective:** materially improve legal recall, ranking quality, and tenant relevance
- **Dependencies:** Sprint 9
- **Deliverables:**
  - priority court corpus expansion completed to target level
  - matter-attachment embeddings integrated into retrieval
  - per-tenant overlays active
  - cross-encoder reranking active
- **Gate:** retrieval quality has measurable offline lift over the current baseline

### Sprint 11 - Document Intelligence And Eval Harness

- **Backlog IDs:** BG-033, BG-034
- **Objective:** stop relying on heuristic document understanding and establish evaluation infrastructure
- **Dependencies:** Sprint 10
- **Deliverables:**
  - Docling/Tika/PaddleOCR live
  - structural extraction improved
  - evaluation runner exists outside mock mode
  - gold datasets created for target workflows
- **Gate:** quality can now be measured, not just discussed

### Sprint 12 - Expert Benchmark And Quality Gates

- **Backlog IDs:** BG-035, BG-036
- **Objective:** prove or disprove the "better than expert lawyer" claim
- **Dependencies:** Sprint 11
- **Deliverables:**
  - expert-lawyer baseline collection
  - blind review protocol
  - benchmark report across research, drafting, hearing prep, recommendations, and contract review
  - release gates tied to legal-quality thresholds
- **Gate:** **M3 reached**
  - product either has evidence for superiority in defined tasks or it does not; in either case, the claim becomes evidence-based

### Sprint 13 - Workflow Orchestration And Generic Task System

- **Backlog IDs:** BG-040, BG-041
- **Objective:** replace founder-stage workflow plumbing with durable execution
- **Dependencies:** Sprint 12
- **Deliverables:**
  - Temporal-based workflow orchestration
  - generic task/deadline/reminder model across drafts, hearings, intake, and contracts
- **Gate:** long-running workflows are durable and cross-domain tasks are first-class

### Sprint 14 - Observability, Backup/Restore, CI/CD, Secrets

- **Backlog IDs:** BG-042, BG-043, BG-044
- **Objective:** make the system operable and recoverable
- **Dependencies:** Sprint 13
- **Deliverables:**
  - OTEL traces
  - structured logs with tenant and matter context
  - backup policy and restore drill
  - production CI/CD
  - managed secret wiring
- **Gate:** the platform is diagnosable, deployable, and recoverable

### Sprint 15 - Identity, Governance, Admin, Entitlements

- **Backlog IDs:** BG-045, BG-046, BG-047
- **Objective:** make enterprise identity and governance credible
- **Dependencies:** Sprint 14
- **Deliverables:**
  - MFA
  - OIDC
  - SAML
  - role mapping
  - tenant AI policy controls
  - admin console
  - entitlements
- **Gate:** enterprise buyer can evaluate identity and governance seriously

### Sprint 16 - Malware Controls And Connector Operations

- **Backlog IDs:** BG-048, BG-049
- **Objective:** complete the founder enterprise baseline
- **Dependencies:** Sprint 15
- **Deliverables:**
  - malware scanning and quarantine
  - connector health UI
  - retry/operator workflows for sync surfaces
- **Gate:** **M4 reached**
  - enterprise pilot readiness

## Milestone Gates

### M1 - Single-shell product

Reached after Sprint 6 only if:

- no `/legacy` product dependency remains
- parity tests cover replaced workflows
- new customer onboarding works in the new app

### M2 - Complete v1 product

Reached after Sprint 9 only if:

- no preview-only top-level surface remains
- research, recommendations, drafting, hearings, portfolio, and admin are all real
- decision-support breadth matches product claims

### M3 - Quality-proven legal engine

Reached after Sprint 12 only if:

- benchmark harness is live
- expert baseline exists
- release gating uses legal-quality metrics

### M4 - Enterprise pilot readiness

Reached after Sprint 16 only if:

- identity, governance, observability, backup/restore, deployment, and admin controls are live
- malware and connector operations are covered

## Recommended Parallelization

If you have enough people, parallelize like this without breaking the critical path:

- **Track A - Product trust and UI parity**
  - Sprints 1-6
- **Track B - Retrieval and quality**
  - early corpus work from Sprint 10 can begin in background after Sprint 6
- **Track C - Platform hardening**
  - infra design for Sprints 13-16 can begin during Sprint 10, but should not delay product completion or benchmark proof

## What Not To Do

- Do not remove `/legacy` before BG-017 parity tests pass.
- Do not claim "better than expert lawyer" before Sprint 12 gates pass.
- Do not claim enterprise-grade before Sprint 16 gates pass.
- Do not widen product claims faster than shipped product breadth.

## Founder Readout

If you want the shortest correct path:

- **First target:** Sprint 6
  - gives you one coherent product
- **Second target:** Sprint 12
  - gives you evidence-based quality claims
- **Third target:** Sprint 16
  - gives you enterprise pilot readiness

If you force a single answer to "when is this truly aligned with the goal?", the answer in this plan is:

- **Sprint 16 in baseline mode**
- **Sprint 10-12 only in accelerated mode, and only if quality proof and enterprise controls are not faked**

