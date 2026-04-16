# CaseOps PRD

**Document Version:** 1.0.0  
**Date:** 2026-04-15  
**Product:** `CaseOps`  
**Primary Domain:** `caseops.ai`  
**Status:** Draft for Founder Review  
**Classification:** Internal - Confidential  

---

## Table of Contents

1. Executive Summary
2. Product Vision and Positioning
3. Assumptions and Product Decisions
4. Target Users and Personas
5. Jobs to Be Done and Core Problems
6. Product Goals, Non-Goals, and Success Criteria
7. End-to-End Functional Scope
8. Information Architecture
9. Detailed User Flows
10. Module Specifications
11. Recommendation Engine and AI System Design
12. Model, Training, and Evaluation Strategy
13. Multi-Tenancy, Identity, and Authorization
14. System Architecture and Tech Stack
15. Data Model and Storage Design
16. Integrations and Connectors
17. Security, Privacy, Compliance, and Governance
18. Observability, Reliability, and Operations
19. Full Test Strategy
20. Delivery Plan and Rollout
21. Risks and Mitigations
22. Open Questions and Founder Decisions
23. Appendices

---

## 1. Executive Summary

### 1.1 One-Line Pitch

CaseOps is an India-first, globally extensible legal operating system for law firms, solo lawyers, and corporate legal teams that unifies matter management, legal research, AI-assisted drafting, hearing preparation, court intelligence, contract and legal operations workflows, and explainable recommendations in one platform.

### 1.2 Product Thesis

The product is not a chatbot. It is a `system of work` for legal teams.

CaseOps should become the primary interface where legal work is:

- created
- reviewed
- tracked
- cited
- recommended
- approved
- audited
- learned from

### 1.3 Primary Market Wedge

Primary launch markets from day one:

- mid-sized and litigation-heavy Indian law firms with 20-200 lawyers
- corporate legal teams and general counsels with active litigation, contract, and outside counsel needs

Expansion markets:

- larger law firms requiring private deployments
- solo and small firms through a lighter self-serve product tier

### 1.4 Product Promise

CaseOps should let a legal team:

- manage every matter from one workspace
- get cited answers from legal sources and internal work product
- generate first drafts and hearing packs faster
- receive explainable recommendations for forum, remedy, arguments, next steps, and outside counsel
- maintain strict tenant and matter isolation
- safely use AI agents with scoped permissions, approvals, and audit trails

### 1.5 Strategic Differentiator

CaseOps wins by combining:

- `matter graph`: connected data model across courts, judges, parties, documents, deadlines, issues, recommendations, and outcomes
- `legal RAG`: grounded retrieval across statutes, judgments, orders, contracts, and internal precedents
- `workflow OS`: intake, drafting, hearing prep, contract review, legal ops, and outside counsel management
- `trust plane`: Grantex-backed scoped agent permissions, revocation, consent, and audit
- `HITL learning`: lawyer corrections, approvals, and final outputs become structured feedback

---

## 2. Product Vision and Positioning

### 2.1 Vision

Build the operating system for legal work in India, with architecture and workflows extensible to other common law markets over time.

### 2.2 Positioning

CaseOps sits at the intersection of:

- legal practice management
- legal research
- drafting copilot
- litigation operations
- legal operations and contract workflows
- recommendation systems
- AI governance and agent security

### 2.3 Category Statement

CaseOps is a `Legal Work Operating System`.

It is broader than:

- practice management tools
- legal research platforms
- contract lifecycle tools
- generic LLM wrappers
- single-purpose litigation analytics tools

### 2.4 Geographic Strategy

CaseOps is:

- `India-first in content, workflows, and product design`
- `global-ready in architecture, naming, and deployment posture`

This means:

- India-specific court, statute, and procedure support is a launch priority
- product branding, multi-tenancy, and technical architecture should still allow eventual international expansion

---

## 3. Assumptions and Product Decisions

### 3.1 Assumptions

- Launch geography is India.
- Initial product value is highest for litigation-heavy firms and legal departments with active matter portfolios.
- Product must support both law firm and corporate legal department workflows from the first release.
- Product must support contract workflows from the first release.
- Product must support billing, timekeeping, spend tracking, and fee collection from the first release.
- Product must support Indian lower courts, High Courts, and the Supreme Court from the first release.
- Product must remain commercially clean for enterprise adoption, using open source components with MIT, Apache-2.0, PostgreSQL, BSD, or similarly permissive licenses by default.
- Product should support future shared SaaS, private VPC, and on-prem/air-gapped deployments.
- Customer data must be tenant-isolated by default and cannot be used for cross-tenant model training without explicit opt-in.

### 3.2 Naming Decisions

- Company and product name: `CaseOps`
- Primary domain: `caseops.ai`

### 3.3 Infra Decisions

Launch infrastructure choice:

- `middle path`
- `Cloud Run + Cloud SQL + GCS + managed services`
- no Kubernetes cluster in founder stage
- no self-hosted always-on LLM infrastructure in shared founder-stage SaaS before first customer
- product and architecture must still support optional private/self-hosted inference from v1 for qualifying tenants and enterprise deployments

Enterprise inference offering from first enterprise release:

- fully packaged `CaseOps-managed private inference stack`
- deployable in dedicated tenant environments
- compatible with private VPC and later on-prem patterns

Future enterprise path:

- `GKE + private networking + dedicated inference + stronger HA`

### 3.4 AI Agent Framework Decision

CaseOps will not be built on a third-party agent framework as the core runtime.

Chosen pattern:

- `Temporal` for workflow orchestration
- `FastAPI` services for runtime components
- `Grantex` for agent identity, scoped auth, revocation, budgets, and audit
- small internal agent SDK for tool calling, execution context, retrieval hooks, and review gates

### 3.5 LLM Decisions

Planned model portfolio:

- `Gemma 4 31B IT` as a first-class multimodal reasoning model candidate
- `gpt-oss-20b` as a strong self-hostable reasoning and tool-use model
- `Gemma 4 E4B` or similar lightweight model for edge / cheap inference tiers
- smaller task models like `Qwen2.5 7B/14B` for specialized extraction or adapters

Design principle:

- do not train a foundation model from scratch
- keep law in retrieval and source systems
- fine-tune only for behavior and workflow outputs

### 3.6 Multi-Tenancy Decision

CaseOps will be multi-tenant from day one.

Tenant isolation will exist across:

- application data
- object storage
- vector and search scopes
- audit logs
- model memory
- prompts, playbooks, and policies

Separation model:

- shared control plane
- isolated data plane
- shared base models
- optional tenant-specific adapters

### 3.7 Launch Coverage Decision

Mandatory court coverage from the first release:

- lower courts
- High Courts
- Supreme Court

Coverage strategy:

- deeper, more reliable lower-court coverage for selected states and court systems first
- broad architecture support for eventual nationwide expansion

Priority rollout jurisdictions for deeper court coverage:

- `Delhi / NCR`
- `Maharashtra`
- `Karnataka`
- `Telangana`

Secondary rollout jurisdictions after the initial four:

- `Tamil Nadu`
- `Gujarat`

Mandatory business coverage from the first release:

- law firms
- corporate legal / GC teams

Mandatory workflow coverage from the first release:

- litigation matter management
- legal research
- drafting
- hearing preparation
- recommendation engine
- contract workflows
- outside counsel management
- billing, timekeeping, spend tracking, and fee collection

### 3.8 Dependency and Versioning Policy

CaseOps must use the latest stable production-ready version of every selected:

- framework
- SDK
- library
- runtime
- database
- search engine
- infrastructure component
- deployment tool

Versioning rules:

- no intentional pinning to older major versions unless a blocking incompatibility is documented
- every dependency choice must record the selected version at implementation time
- all greenfield modules must start on the latest stable version rather than legacy-compatible versions
- beta, preview, RC, nightly, or experimental releases must not be used in production by default
- where enterprise stability is a concern, select the latest stable LTS-style release if the ecosystem provides one

Rationale:

- avoid repeated upgrade work immediately after launch
- reduce migration debt
- keep the platform aligned with current security patches and ecosystem support

---

## 4. Target Users and Personas

### 4.1 Primary User Segments

#### A. Mid-Sized and Large Law Firms

Needs:

- litigation matter management
- knowledge reuse
- drafting leverage
- hearing readiness
- partner oversight
- profitability visibility

#### B. Corporate Legal Departments and General Counsels

Needs:

- intake triage
- contract and policy workflows
- litigation oversight
- outside counsel management
- legal spend control
- board and risk reporting

#### C. Solo and Small Lawyers

Needs:

- one lightweight system for case diary, drafting, deadlines, client communication, and billing

### 4.2 Key Personas

#### Managing Partner / Head of Litigation

Success means:

- more matters handled without chaos
- faster output from associates
- stronger hearing readiness
- better profitability and visibility

#### Senior Associate

Success means:

- faster research
- better first drafts
- cleaner hearing prep
- fewer repetitive tasks

#### Junior Associate / Paralegal / Clerk

Success means:

- fewer manual chronologies
- fewer missed dates
- easier drafting and bundling
- quicker access to precedent

#### General Counsel

Success means:

- better control over legal portfolio
- lower outside counsel spend
- better internal turnaround
- defensible reporting and approvals

#### Legal Ops Manager

Success means:

- structured intake
- standardized workflows
- better visibility into workload and spend
- easier reporting and governance

#### Solo Advocate

Success means:

- operating like a larger practice
- doing more work with less support staff
- staying on top of court dates and drafts

#### Firm Admin / IT Admin

Success means:

- secure onboarding
- tenant controls
- user access management
- auditability
- low admin overhead

---

## 5. Jobs to Be Done and Core Problems

### 5.1 Law Firm Jobs to Be Done

- Help me manage all litigation matters in one place.
- Help me find the best authorities and internal precedents quickly.
- Help me generate a reliable first draft that I can trust and edit.
- Help me prepare for tomorrow’s hearing without manually reading everything again.
- Help me know what the team is missing, what is due, and which matters need escalation.

### 5.2 Corporate Legal Jobs to Be Done

- Help me triage incoming legal requests from the business.
- Help me control contracts, disputes, outside counsel, and legal spend in one system.
- Help me know whether to litigate, settle, appeal, or escalate.
- Help me respond quickly with cited, auditable, reviewable outputs.

### 5.3 Solo Lawyer Jobs to Be Done

- Help me track cases, drafts, deadlines, and clients from a single app.
- Help me produce work faster without hiring additional support staff.

### 5.4 Core Product Problems

- fragmented workflows across multiple tools
- poor knowledge reuse
- slow drafting and hearing prep
- weak portfolio visibility
- no trustworthy recommendation layer
- poor AI governance in legal workflows
- no safe agent execution boundary

---

## 6. Product Goals, Non-Goals, and Success Criteria

### 6.1 Primary Goals

- unify legal work into a matter-centric operating system
- reduce research, drafting, and hearing prep time
- provide explainable recommendations grounded in law and internal knowledge
- support strict multi-tenant isolation and enterprise trust
- establish a HITL learning loop that improves over time

### 6.2 Secondary Goals

- support GC legal ops and outside counsel management
- support contract review and policy workflows
- support private and on-prem deployment paths

### 6.3 Non-Goals

- autonomous final legal advice without review
- black-box judge favorability scoring
- fully autonomous filing in courts at launch
- training a proprietary foundation model from scratch

### 6.4 Product Success Criteria

- users can run day-to-day legal work from CaseOps
- outputs are grounded and reviewable
- agents operate with safe permissions and audit
- enterprise prospects can see a clear path to production readiness

---

## 7. End-to-End Functional Scope

CaseOps v1-v2 scope includes:

1. Tenant, company, and workspace creation
2. User and role management
3. Matter intake and matter cockpit
4. Legal research and citation engine
5. Drafting studio
6. Hearing preparation engine
7. Judge and court intelligence
8. Recommendation engine
9. Contract and legal ops workflows
10. Outside counsel management
11. Billing, timekeeping, spend tracking, and fee collection
12. Audit, security, and governance
13. AI learning and evaluation controls

---

## 8. Information Architecture

### 8.1 Top-Level Navigation

- Home
- Matters
- Hearings
- Research
- Drafting
- Recommendations
- Contracts
- Outside Counsel
- Portfolio
- Admin

### 8.2 Core Workspaces

- `Matter Cockpit`
- `Research Workspace`
- `Drafting Workspace`
- `Hearing Pack Workspace`
- `Contract Review Workspace`
- `Portfolio / Board View`
- `Admin / Security / Billing`

### 8.3 Home Dashboard Variants

#### Law Firm Home

- upcoming hearings
- urgent deadlines
- matters needing review
- recent drafts
- recommendation queue
- firm performance metrics

#### GC Home

- incoming requests
- active disputes
- contracts due / obligations
- outside counsel spend
- escalations requiring approval

#### Solo Home

- today’s cause list and court dates
- pending drafts
- client reminders
- billing reminders

---

## 9. Detailed User Flows

## 9.1 Company / Tenant Creation and Management Flow

### Purpose

Support self-serve, assisted sales, or enterprise onboarding for new customers.

### Actors

- founder / internal ops
- company admin
- invited users
- billing owner
- IT / security admin

### Flow: Self-Serve Company Creation

1. User visits `caseops.ai`.
2. User clicks `Start Workspace`.
3. User enters:
   - company name
   - work email
   - country
   - company type: law firm / corporate legal / solo
   - number of users
4. System validates email domain.
5. System creates:
   - tenant record
   - company record
   - primary admin user
   - default workspace settings
   - starter roles and permissions
6. User verifies email.
7. User sets password or signs in with SSO if enabled.
8. System launches onboarding wizard.

### Flow: Assisted Enterprise Company Creation

1. Internal team creates provisional tenant.
2. Tenant is tagged with plan, deployment type, and security tier.
3. Primary contact receives activation link.
4. Admin completes setup:
   - domain verification
   - SSO setup or local auth confirmation
   - logo and branding
   - timezone
   - user invite policy
   - data region
5. Optional private deployment and networking fields are set.

### Flow: Onboarding Wizard

Steps:

1. Select organization type
2. Confirm jurisdictions and practice areas
3. Invite users
4. Set roles
5. Upload starter templates or documents
6. Configure matter statuses and teams
7. Configure approval policy
8. Configure AI policy and data-sharing policy
9. Finish workspace bootstrap

### Flow: Company Management

Admin can:

- edit company profile
- manage branding and domain
- manage plan and billing
- manage teams and departments
- manage security policy
- manage model policy
- manage data retention
- export audit and billing reports

### Acceptance Criteria

- tenant creation is idempotent
- company admin exists exactly once at creation
- email verification is required unless enterprise SSO pre-provisioning is used
- tenant isolation is enforced immediately after creation
- workspace bootstrap creates default roles and settings

## 9.2 User Invite, Role, and Access Management Flow

### Roles

Default roles:

- Company Admin
- Partner / Practice Head
- Senior Lawyer
- Junior Lawyer
- Paralegal / Clerk
- GC / Legal Head
- Legal Ops Manager
- Outside Counsel Viewer
- Auditor / Compliance
- Billing Admin

### Flow

1. Admin invites user by email.
2. Admin selects role, team, and optional matter scope.
3. Invitee receives activation email.
4. Invitee signs in and confirms profile.
5. Access is provisioned according to role and team.
6. Admin may later:
   - suspend
   - remove
   - change role
   - add matter-specific access
   - apply ethical wall restrictions

### Acceptance Criteria

- no cross-tenant invite leakage
- role changes are audited
- suspension revokes sessions and downstream grants
- ethical wall restrictions override broad role access

## 9.3 Matter Creation and Intake Flow

### Entry Points

- manual new matter
- document upload
- eCourts-linked import
- contract or notice import
- legal intake form

### Flow

1. User clicks `Create Matter`.
2. User selects matter type:
   - litigation
   - advisory
   - contract
   - investigation
   - compliance
3. User enters or uploads source materials.
4. System extracts:
   - parties
   - court / forum candidates
   - acts and sections
   - dates
   - reliefs
   - matter stage
   - deadlines
5. System proposes matter summary and tags.
6. User confirms or edits.
7. Matter cockpit is created.

### Acceptance Criteria

- extraction confidence is shown where relevant
- user can override extracted values
- matter is not marked finalized until user confirms profile
- source documents preserve lineage

## 9.4 Research Flow

### Flow

1. User opens Research Workspace from a matter or standalone.
2. User enters a question or issue.
3. System performs:
   - lexical retrieval
   - semantic retrieval
   - filters by court, date, statute, judge, and source type
   - reranking
4. System returns:
   - answer draft
   - citations
   - authority cards
   - contrary authorities
   - internal precedent matches
5. User saves research note to matter or private notebook.

### Acceptance Criteria

- all substantive answers include citations or explicit uncertainty
- authorities are clickable and traceable to source
- retrieval respects tenant and matter boundaries

## 9.5 Drafting Flow

### Flow

1. User opens a matter.
2. User clicks `New Draft`.
3. User selects draft type.
4. System gathers:
   - matter facts
   - prior orders
   - applicable sections
   - internal templates
   - retrieved authorities
5. Drafting agent produces first draft.
6. User edits in drafting editor.
7. User saves version or submits for review.
8. Reviewer approves or requests changes.
9. Final approved draft is locked, versioned, and available for export.

### Acceptance Criteria

- all generated drafts carry draft status until approved
- citations and authorities used in the draft are inspectable
- edit history is preserved
- final approved draft can be used as tenant memory

## 9.6 Hearing Preparation Flow

### Flow

1. System detects upcoming hearing based on matter schedule or imported court updates.
2. It generates a hearing prep checklist.
3. User clicks `Prepare Hearing Pack`.
4. System compiles:
   - chronology
   - last order
   - pending compliance items
   - issues for hearing
   - likely opposition points
   - key authorities
   - bench brief
   - oral submission outline
5. User reviews and exports.
6. After hearing, user uploads notes or outcome.
7. System updates next steps and client update draft.

### Acceptance Criteria

- hearing pack reflects latest matter state
- last order and pending obligations are visible
- post-hearing update creates tasks and next date suggestions

## 9.7 Recommendation Flow

### Flow

1. User requests recommendation in context of a matter or intake.
2. System determines recommendation type:
   - forum
   - remedy
   - authority
   - next-best action
   - outside counsel
   - settlement / escalation
3. Rules engine, retrieval engine, and rankers run.
4. Explanation layer formats output.
5. User accepts, edits, or rejects recommendation.
6. System captures feedback as structured training data.

### Acceptance Criteria

- recommendation includes explanation, assumptions, and confidence
- recommendation shows supporting sources
- user action is captured

## 9.8 Contract Review Flow

### Flow

1. User uploads contract or opens existing contract.
2. System extracts:
   - parties
   - dates
   - clauses
   - obligations
   - renewal and termination triggers
3. System compares against playbook.
4. System proposes redlines and fallback language.
5. User reviews and approves.
6. Final redline package is exported or saved.

### Acceptance Criteria

- clause extraction is visible and editable
- playbook rule hits are inspectable
- redline suggestions are tracked by version

## 9.9 Outside Counsel Management Flow

### Flow

1. Corporate legal user opens Outside Counsel workspace.
2. User assigns or evaluates counsel for a matter.
3. System surfaces:
   - prior matter fit
   - spend profile
   - responsiveness
   - outcome history
4. User approves selection.
5. Matter budget and billing trail are linked to that counsel.

### Acceptance Criteria

- counsel recommendations are review-only
- internal metrics and notes remain tenant-private
- spend is linked to matter and counsel records

## 9.10 Billing, Timekeeping, and Fee Collection Flow

### Flow: Law Firm Billing

1. User records time against matter, task, hearing, or document.
2. System applies rate card, user role, and matter billing terms.
3. User reviews draft invoice entries.
4. Partner or billing admin approves invoice.
5. Invoice is issued to client.
6. Payment link or collection instructions are attached.
7. Payment status is tracked.
8. Collections reminders can be triggered.

### Fee Collection Rail

Primary online payment gateway for v1:

- `Pine Labs`

### Flow: Corporate Legal Spend

1. GC user records or imports outside counsel invoice.
2. System maps invoice to matter, counsel, budget, and stage.
3. Reviewer approves, disputes, or partially approves.
4. Spend dashboard updates.

### Acceptance Criteria

- time entries can be role-restricted
- invoices are versioned and auditable
- collections status is linked to invoice and matter
- corporate spend approval workflows support partial approval and dispute states

---

## 10. Module Specifications

## 10.1 Matter OS

### Description

Central workspace and source of truth for all legal work items.

### Key Capabilities

- matter creation and classification
- matter status and stage tracking
- timeline and chronology
- document repository
- tasks, deadlines, and hearing calendar
- linked research, drafts, recommendations, and outcomes

### Key Screens

- matter list
- matter details / cockpit
- timeline tab
- documents tab
- tasks tab
- recommendations tab
- audit tab

## 10.2 Research and Citation Engine

### Description

Grounded legal retrieval across public legal sources and tenant work product.

### Capabilities

- semantic + lexical search
- filter by source type, court, date, judge, statute, matter
- answer generation with citations
- authority bundles
- similar-case discovery
- contrary-authority surfacing

### Data Sources

- public statutes and notifications
- judgments and orders
- tenant documents and precedents
- approved work product

## 10.3 Drafting Studio

### Description

AI-assisted drafting environment for pleadings, notices, submissions, opinions, and contracts.

### Capabilities

- template selection
- context-aware draft generation
- redline mode
- version control
- reviewer workflow
- export to docx/pdf

## 10.4 Hearing Preparation Engine

### Description

Workflow for converting matter context into a ready-to-use hearing pack.

### Capabilities

- chronology builder
- pending compliance tracker
- last order summary
- bench brief
- oral points
- issue checklist
- post-hearing next actions

## 10.5 Recommendation Engine

### Description

Explainable decision-support layer for legal teams.

### Capabilities

- ranked options
- supporting authorities
- assumptions and missing facts
- user feedback capture
- risk and action suggestions

## 10.6 Judge and Court Intelligence

### Description

Public and tenant-enriched intelligence about courts, benches, and judges.

### Capabilities

- judge profile
- court profile
- roster context
- issue clusters
- authored orders and citation trends
- internal notes overlay

### Guardrails

- no black-box favorability scoring
- no manipulation-oriented recommendations

## 10.7 Contract and Legal Ops Suite

### Capabilities

- intake requests
- contract repository
- clause extraction
- redlining with playbooks
- policy retrieval
- approvals and routing
- obligations and deadline tracking

## 10.8 Billing, Spend, and Profitability

### Capabilities

- law firm timekeeping
- matter-level and client-level rate cards
- invoice generation and approvals
- fee collection tracking
- Pine Labs payment gateway integration for online collections
- law firm matter profitability
- outside counsel budget tracking
- invoice and spend reporting for GC teams
- aging, collections, and realization views
- trust/accounting integrations later where needed

## 10.9 Admin and Governance Console

### Capabilities

- tenant settings
- role and access management
- SSO and auth config
- AI policy controls
- prompt and model policy
- audit exports
- billing and plan management

---

## 11. Recommendation Engine and AI System Design

## 11.1 Design Principles

- explainable over opaque
- assistive over autonomous
- source-grounded over memorized
- human-reviewed for critical decisions

## 11.2 Recommendation Types

- forum recommendation
- remedy recommendation
- authority recommendation
- next-best action
- settlement or escalation recommendation
- outside counsel recommendation
- draft template recommendation

## 11.3 Pipeline

1. matter understanding
2. extraction and feature building
3. rules evaluation
4. retrieval and reranking
5. ranking model
6. explanation model
7. human feedback capture

## 11.4 Required Output Structure

Each recommendation must include:

- title
- ranked options
- why
- supporting authorities or documents
- assumptions
- missing facts
- confidence level
- recommended next action

## 11.5 Guardrails

- no recommendation without evidence
- no unsupported judge favoritism outputs
- no client-facing recommendation marked final without review
- all outputs audited

---

## 12. Model, Training, and Evaluation Strategy

## 12.1 LLM Roles

### Primary Reasoning / Drafting Tier

- `Gemma 4 31B IT`
- `gpt-oss-20b`

### Lightweight / Edge Tier

- `Gemma 4 E4B`

### Task-Specific Models

- smaller open models such as `Qwen2.5 7B/14B`
- classifier and reranker models

## 12.2 Training Strategy

### Not Done

- no full foundation-model training from scratch
- no memorization-only legal tuning

### Done

- RAG for legal knowledge
- LoRA / QLoRA for workflow behavior
- supervised task models for extraction and reranking
- recommendation models trained on structured labels

## 12.3 Training Data Classes

1. Public legal corpora
2. Synthetic task datasets built from official sources
3. Tenant-approved work product
4. HITL edit and approval pairs

## 12.4 Public and Open Data

Examples:

- official statutes and notifications
- court judgments and orders
- OpenNyAI datasets
- public legal benchmarks

## 12.5 Tenant Data

Used only within policy:

- approved drafts
- precedents
- hearing notes
- contracts
- playbooks
- internal policies

## 12.6 Training Cadence

- daily retrieval corpus refresh
- weekly reranker refresh when justified
- monthly task-model retraining
- quarterly drafting adapter retraining

## 12.7 Evaluation

Measure:

- citation accuracy
- extraction accuracy
- draft acceptance rate
- edit distance
- recommendation usefulness
- hallucination rate
- latency and cost

---

## 13. Multi-Tenancy, Identity, and Authorization

## 13.1 Tenancy Model

CaseOps will use:

- shared control plane
- isolated tenant data
- shared base models
- tenant-specific memory and policies
- optional tenant-specific adapters

## 13.2 Tenant Isolation Boundaries

- database rows and schemas as designed
- object storage prefixes/buckets
- search indexes or filters
- vector namespaces
- audit logs
- billing data
- training feedback

## 13.3 Human Identity

For users:

- email/password for early self-serve
- OIDC/SAML SSO for enterprise
- MFA support

## 13.4 Authorization Model

Use:

- role-based access control
- matter-level access control
- ethical walls
- team-based scopes

## 13.5 Agent Authorization

Use `Grantex` for:

- per-agent identity
- scoped grant tokens
- expiration
- revocation
- action budgets
- audit trail

### Example Agent Scopes

- `matter.read`
- `document.read`
- `draft.write`
- `recommendation.generate`
- `external.share`
- `email.send`

### Policy Rule

Agents may never exceed:

- tenant scope
- matter scope
- role-implied user permissions

## 13.6 Deployment Tiers

- shared SaaS
- dedicated tenant / private VPC
- on-prem / air-gapped

---

## 14. System Architecture and Tech Stack

## 14.1 Foundational Principles

- use permissive open-source licenses by default
- separate stateless services from stateful services
- keep app architecture enterprise-shaped even in founder-stage infra
- support future migration from lightweight managed services to full enterprise infrastructure without product rewrite
- use latest stable production-ready versions of all approved tools and components

## 14.2 Launch Infrastructure Pattern

Chosen launch pattern:

- `Cloud Run + Cloud SQL + GCS + managed secrets/networking`

Reasons:

- lower ops burden
- autoscaling for stateless services
- cleaner path to first customer under controlled cost
- easier upgrade path to GKE

## 14.3 Target Enterprise Pattern

- `GKE + Cloud SQL/managed Postgres or private equivalent + object storage + private networking + dedicated inference`

## 14.4 Core Technology Decisions

### Frontend

- `Next.js`
- `React`
- `TypeScript`
- `Tailwind CSS`
- `TanStack Query/Table`

### Backend

- `Python 3.12+`
- `FastAPI`
- `Pydantic`
- `SQLAlchemy`
- `Alembic`

### Workflow and Async

- `Temporal` for orchestrated long-running workflows
- `NATS` or managed queue/event infrastructure depending stage

### Data Layer

- `PostgreSQL`
- `pgvector`
- `GCS` for documents
- `OpenSearch` in later phases if search requirements exceed Postgres capabilities
- `Valkey` for cache and ephemeral state if needed

### Identity and Auth

- enterprise SSO using OIDC/SAML
- `Grantex` for agent identity and delegated tool auth

### Document Intelligence

- `Docling`
- `Apache Tika`
- `Tesseract`
- optional `PaddleOCR`

### Model Serving and AI

- hosted model providers initially
- later: self-hostable open models with `vLLM`
- local / edge possibility with `llama.cpp`

### Observability

- `OpenTelemetry`
- managed logs/metrics initially
- future: `Prometheus` and `Jaeger`

## 14.5 Version Management Policy

Implementation teams must:

- record exact versions in architecture and deployment docs at build time
- prefer the latest stable version available at project initialization
- avoid older compatibility branches unless explicitly approved and documented
- review critical dependencies regularly for security and compatibility

Production release policy:

- stable GA releases only by default
- preview or beta services may be used only in isolated non-production experiments

## 14.6 Service Boundaries

### Service List

1. `web-app`
2. `api-gateway`
3. `auth-service`
4. `tenant-service`
5. `matter-service`
6. `document-service`
7. `research-service`
8. `drafting-service`
9. `hearing-service`
10. `recommendation-service`
11. `contract-service`
12. `outside-counsel-service`
13. `notification-service`
14. `billing-service`
15. `audit-service`
16. `agent-runtime-service`
17. `integration-service`
18. `evaluation-service`

### Founder-Stage Consolidation

In founder stage, some services may be deployed as modules within fewer runtime containers:

- core API
- async worker
- web frontend
- Grantex

### Enterprise-Stage Separation

Split into independent services with isolated scaling and deployment.

## 14.7 Autoscaling Expectations

Cloud Run can autoscale:

- API instances
- worker jobs
- ingestion jobs
- recommendation jobs

Autoscaling does not automatically solve:

- database bottlenecks
- heavy search bottlenecks
- model inference saturation
- bad multi-tenant design

## 14.8 Upgrade Path

CaseOps must be built so the move from middle-path infrastructure to full enterprise infrastructure is an infrastructure migration, not an application rewrite.

Requirements to preserve that path:

- stateless app services
- containerized components
- externalized storage
- externalized sessions and secrets
- migration-safe database schema
- asynchronous workflow boundaries

---

## 15. Data Model and Storage Design

## 15.1 Core Entities

- Tenant
- Company
- Workspace
- User
- Team
- Role
- Permission
- Matter
- MatterParty
- Court
- Bench
- Judge
- Proceeding
- Hearing
- Deadline
- Task
- Document
- DocumentVersion
- Order
- Judgment
- Statute
- Section
- Issue
- Relief
- Recommendation
- RecommendationDecision
- Contract
- Clause
- Obligation
- OutsideCounsel
- SpendRecord
- AuditEvent
- AgentGrant
- ModelRun
- EvaluationRun

## 15.2 Storage Mapping

### PostgreSQL

System of record for:

- tenants
- users
- roles
- matters
- hearings
- deadlines
- tasks
- recommendations
- approvals
- audit metadata

### GCS

Stores:

- uploaded documents
- exports
- model artifacts when needed
- backups and reports

### pgvector / Search Layer

Stores:

- embeddings for document chunks
- embeddings for notes and approved work product
- retrieval metadata

### Optional OpenSearch

Used when needed for:

- high-scale hybrid search
- complex legal filtering
- advanced relevance ranking

## 15.3 Data Isolation Rules

- every core record must contain `tenant_id`
- access to records must be filtered by `tenant_id`
- matter-level sensitive records require additional scope checks
- internal notes must be separately typed and protected

## 15.4 Audit Data

Every critical action must store:

- actor type: human or agent
- actor id
- tenant id
- matter id if relevant
- action type
- tool/action target
- timestamp
- result
- approval chain if any

---

## 16. Integrations and Connectors

## 16.1 Initial Integration Priorities

- official legal and court data sources
- email systems
- cloud document stores
- user identity providers
- billing/spend sources for corporate legal teams
- payment collection providers for law firms

## 16.2 External Source Categories

- public statutes and notifications
- court portals and public legal data
- lower court data sources
- High Court data sources
- Supreme Court data sources
- document repositories
- email/calendar
- contract repositories
- external counsel billing systems where relevant
- payment rails and collection systems where relevant

### Payment and Collection Partner

v1 collection partner:

- `Pine Labs`

## 16.3 Connector Requirements

- retry-safe ingestion
- connector health state
- per-tenant credentials
- audit logging
- rate limiting
- source lineage

### Payment Connector Requirements

- invoice-to-payment-link generation
- webhook reconciliation
- payment success, failure, refund, and dispute event handling
- invoice status synchronization
- secure signature verification for inbound webhooks

## 16.4 Connector Security

- secrets never exposed in UI
- connector actions scoped by tenant
- outbound integrations mediated by policy and grants

---

## 17. Security, Privacy, Compliance, and Governance

## 17.1 Security Principles

- least privilege
- explicit trust boundaries
- tenant isolation
- audit by default
- human review for critical outputs and actions

## 17.2 Required Security Controls

- TLS everywhere
- encryption at rest
- RBAC and matter-level access
- ethical walls
- secret rotation
- session revocation
- event audit logs
- secure document downloads
- malware scanning or validation pipeline for uploads later

## 17.3 Privacy and Data Governance

- customer data not used for cross-tenant model training by default
- retention policies configurable by tenant
- export and deletion workflows available to admins
- private notes clearly separated from shareable notes

## 17.4 AI Governance

- model policy per tenant
- allowlist of providers/models
- audit of prompts and tool invocations
- approval workflow before external sharing
- evaluation gates before enabling new model versions

## 17.5 Legal and Compliance Readiness

Design should be compatible with:

- contractual confidentiality obligations
- Indian privacy requirements
- client privilege handling
- enterprise vendor security reviews

---

## 18. Observability, Reliability, and Operations

## 18.1 Reliability Targets

### Founder / Pilot

- single-region
- no formal HA SLA
- strong backups and restartability

### Enterprise

- higher availability target
- stronger backup and restore guarantees
- private networking options

## 18.2 Operational Signals

Track:

- API latency
- queue depth
- failed workflows
- retrieval latency
- model latency
- token usage / cost
- document parsing failures
- auth failures
- grant issuance and revocation events

## 18.3 Backup and Restore

Must support:

- daily database backups
- object storage durability
- restore testing
- tenant-scoped export

## 18.4 Upgrade Strategy

From middle-path infra to enterprise infra:

- preserve stateless services
- use blue/green or phased cutover later
- design for minimal or no downtime migrations

---

## 19. Full Test Strategy

## 19.1 Test Philosophy

CaseOps must be tested at:

- unit level
- integration level
- workflow level
- end-to-end level
- security level
- performance and resilience level
- AI evaluation level

No feature is complete without:

- functional coverage
- permission coverage
- audit coverage
- failure-mode coverage

## 19.2 Functional Test Matrix

### A. Tenant / Company / Workspace Management

1. Create company via self-serve signup
2. Create company via assisted enterprise setup
3. Verify email and activate admin
4. Domain verification succeeds
5. Duplicate domain conflict handled correctly
6. Invite user with valid role
7. Invite user with invalid email rejected
8. User accepts invite and gains correct access
9. Admin changes user role
10. Suspended user loses access immediately
11. Deleted user sessions are revoked
12. Company settings update persists and audits correctly
13. Plan change updates entitlements
14. Tenant deletion/export workflow handles data correctly

### B. Authentication and Identity

1. Local password login
2. Password reset
3. MFA setup and login
4. OIDC SSO login
5. SAML SSO login
6. Session expiry
7. Session revocation after suspension
8. Invite token expiry
9. Replay of old invite token denied

### C. Matter Management

1. Create matter manually
2. Create matter from uploaded documents
3. Create matter from intake form
4. Edit matter metadata
5. Link connected matters
6. Add and edit parties
7. Add and edit counsel
8. Update matter stage
9. Add deadline
10. Deadline reminder triggers
11. Task assignment and completion
12. Timeline generation
13. Matter archive and restore

### D. Document Management

1. Upload supported file types
2. Reject unsupported file types
3. Version document
4. OCR pipeline executes when required
5. Document extraction stores entities
6. Access-controlled download
7. Private note upload remains private
8. Export bundle by matter

### E. Research Engine

1. Keyword search returns legal sources
2. Semantic search returns relevant authorities
3. Search filters by court/date/statute
4. Search filters by tenant corpus
5. Answer generation includes citations
6. Contradictory authorities surfaced
7. Internal precedents appear when available
8. Query with insufficient context returns uncertainty

### F. Drafting Studio

1. Generate new draft from matter
2. Template selection by document type
3. Citation-backed draft generation
4. Save draft as version
5. Compare versions
6. Submit for review
7. Reviewer approves
8. Reviewer requests changes
9. Final approved draft locks correctly
10. Export approved draft

### G. Hearing Preparation

1. Upcoming hearing detected
2. Hearing pack generation
3. Chronology includes latest events
4. Last order attached
5. Pending compliance shown
6. Bench brief generated
7. Hearing notes entered after hearing
8. Next steps created from post-hearing update

### H. Recommendation Engine

1. Forum recommendation generated
2. Remedy recommendation generated
3. Authority recommendation generated
4. Next-best action recommendation generated
5. Missing facts shown
6. Confidence shown
7. User accepts recommendation
8. User rejects recommendation
9. Recommendation decision is audited

### I. Judge and Court Intelligence

1. Judge profile page loads
2. Court profile page loads
3. Public source lineage shown
4. Internal notes visible only to allowed users
5. Restricted matters do not leak into broader views

### J. Contract and Legal Ops

1. Contract upload and parse
2. Clause extraction
3. Playbook comparison
4. Redline suggestion generation
5. Obligation extraction
6. Legal intake request routing
7. Advice note linked to request

### K. Outside Counsel Management

1. Add outside counsel profile
2. Link counsel to matter
3. Capture spend entry
4. Recommendation view shows ranking with evidence
5. Internal performance notes remain private

### L. Billing / Spend / Profitability

1. Plan billing page loads
2. Entitlement enforcement works
3. Spend records linked to matter
4. Profitability dashboard computes correctly
5. Time entries create billable records correctly
6. Invoice approval workflow executes correctly
7. Fee collection status updates on payment events
8. Overdue reminder logic works correctly
9. Pine Labs payment link generation succeeds
10. Pine Labs webhook signature validation succeeds
11. Payment failure and retry state handled correctly
12. Refund and dispute states handled correctly

## 19.3 Authorization and Multi-Tenancy Tests

1. User from tenant A cannot access tenant B data
2. Search results never contain tenant B documents
3. Shared model outputs do not include tenant B memory
4. Object storage access is tenant-scoped
5. Vector retrieval is tenant-scoped
6. Audit export is tenant-scoped
7. Matter wall denies access even for broad roles
8. Outside counsel view sees only explicitly shared items

## 19.4 Grantex and Agent Tests

1. Agent grant issued with correct scopes
2. Agent grant expiry enforced
3. Revoked grant cannot be used
4. Agent cannot access matter outside grant
5. Agent cannot call unauthorized tool
6. Human approval required action is blocked until approved
7. Audit record created for every agent tool call
8. Budget or action limits enforced

## 19.5 Security Test Matrix

### Authentication and Session Security

1. Brute-force login protection
2. Rate limiting on auth endpoints
3. CSRF protection where applicable
4. JWT/session tampering rejected
5. Password policy enforcement

### Authorization Security

1. Horizontal privilege escalation blocked
2. Vertical privilege escalation blocked
3. Role tampering blocked
4. Suspended user token rejected

### Data Security

1. Encryption at rest verified
2. Encryption in transit enforced
3. Secret exposure checks
4. Signed URL expiry enforced
5. Audit logs cannot be modified by regular users

### App Security

1. SQL injection tests
2. XSS tests
3. SSRF tests
4. path traversal tests
5. malicious file upload tests
6. template injection tests
7. prompt injection resistance tests for retrieval workflows
8. data exfiltration prompt tests

### Multi-Tenant Security

1. Tenant id tampering in API requests
2. Search filter bypass attempts
3. object path guessing blocked
4. vector namespace bypass blocked

### Agent Security

1. unauthorized tool call blocked
2. forged grant rejected
3. replayed grant rejected
4. expired grant rejected
5. approval-bypass attempt rejected

## 19.6 AI Evaluation and Safety Tests

1. citation accuracy benchmark
2. hallucination under low-context input
3. refusal when evidence is weak
4. current-law accuracy for post-2024 criminal statutes
5. recommendation explanation quality
6. contract clause extraction accuracy
7. hearing-pack completeness
8. prompt injection robustness
9. tenant data leakage red-team tests

### Private / Self-Hosted Inference Tests

1. enterprise tenant can route to private inference deployment
2. shared SaaS tenants cannot access private inference endpoints of other tenants
3. model routing policy honors tenant inference preference
4. private inference outage fails gracefully according to tenant policy
5. audit trail records private inference usage separately

## 19.7 Non-Functional Test Matrix

### Performance

1. matter cockpit load under target SLA
2. research query latency under expected load
3. draft generation latency under expected load
4. hearing pack generation latency
5. large document upload throughput

### Scalability

1. Cloud Run autoscaling for API burst
2. worker autoscaling under ingestion burst
3. DB connection pool saturation behavior
4. large tenant with many matters

### Reliability

1. worker crash mid-workflow and recovery
2. document parser retry logic
3. graceful degradation when search is slow
4. model provider outage fallback
5. queue backlog handling

### Backup and Restore

1. restore database backup
2. restore document pointers
3. tenant-scoped export and import checks

### Disaster Recovery

1. simulate region outage plan
2. recovery runbook dry run

### Accessibility

1. keyboard navigation
2. screen reader compatibility on major workflows
3. contrast checks
4. form error clarity

### Browser and Device Compatibility

1. Chrome
2. Edge
3. Safari
4. Firefox
5. mobile responsive layouts for key workflows

### Jurisdiction Coverage Validation

1. Delhi / NCR lower-court and High Court workflows validated
2. Maharashtra lower-court and High Court workflows validated
3. Karnataka lower-court and High Court workflows validated
4. Telangana lower-court and High Court workflows validated
5. Supreme Court workflows validated
6. secondary rollout jurisdictions remain feature-flagged or clearly marked until fully supported

## 19.8 UAT Scenarios

### Law Firm UAT

- create workspace
- invite team
- import matter
- research issue
- generate bail draft
- create hearing pack
- review recommendation
- export final draft

### GC UAT

- create workspace
- configure legal intake
- upload contract
- generate redline
- assign outside counsel
- review spend dashboard

### Solo UAT

- create workspace
- create matter
- upload notice/order
- generate draft
- track next hearing
- send client summary

---

## 20. Delivery Plan and Rollout

## 20.1 Phase 0: Foundation

- repository setup
- design system
- auth and tenant model
- data schema
- document ingestion baseline
- Grantex integration skeleton

## 20.2 Phase 1: Core Litigation OS

- company onboarding
- user management
- matter cockpit
- document management
- research engine
- drafting studio
- hearing preparation
- contract workflows
- GC legal intake baseline
- outside counsel management baseline
- billing, timekeeping, spend tracking, and fee collection baseline

## 20.3 Phase 2: Recommendation and Intelligence

- forum/remedy/authority recommendations
- judge and court intelligence
- recommendation feedback loops

## 20.4 Phase 3: Hardening and Expansion

- deeper GC workflows
- stronger billing and profitability analytics
- enterprise policy controls
- dedicated/private inference options and packaged enterprise deployment
- broader connector coverage

## 20.5 Phase 4: Enterprise Hardening

- private deployment support
- advanced SSO
- dedicated adapters
- stronger observability
- enterprise policy controls

---

## 21. Risks and Mitigations

### Risk: Product too broad

Mitigation:

- launch with litigation-heavy law firm wedge while keeping architecture broad

### Risk: Search and recommendation quality weak at launch

Mitigation:

- source-grounding
- narrow launch workflows
- lawyer feedback loop

### Risk: Multi-tenant leakage

Mitigation:

- explicit tenant scoping at every storage and service layer
- red-team tests
- audit-by-default

### Risk: Infra cost grows before revenue

Mitigation:

- middle-path managed infra
- hosted LLMs first
- no always-on GPU before justified

### Risk: Legal customers distrust AI

Mitigation:

- approvals
- citations
- audit logs
- explainable recommendations
- tenant-specific controls

---

## 22. Founder-Locked Decisions and Remaining Open Questions

### 22.1 Founder-Locked Decisions

1. Launch customer profile: law firms and GCs from day one
2. Contract and legal ops workflows: included in first release
3. Billing, timekeeping, fee collection, and spend workflows: included in first release
4. Inference posture: shared hosted inference allowed, with private/self-hosted inference option supported from v1
5. Court coverage: lower courts, High Courts, and Supreme Court must all be covered
6. Fee collection gateway for v1: Pine Labs
7. Enterprise inference offering: fully packaged CaseOps-managed private inference stack from first enterprise offering
8. Lower-court rollout strategy: deeper and more reliable coverage for selected states/court systems first
9. Priority rollout jurisdictions: Delhi / NCR, Maharashtra, Karnataka, Telangana
10. Secondary rollout jurisdictions: Tamil Nadu, Gujarat

### 22.2 Remaining Open Questions

1. Which exact court and legal data connectors should be implemented first where coverage overlaps inside the priority jurisdictions
2. What should the first commercial packaging be:
   - per-seat
   - per-matter
   - hybrid enterprise contract
3. Whether solo/self-serve should be held for post-launch or released with restricted scope

---

## 23. Appendices

## 23.1 Example Recommendation Output Schema

- `type`
- `title`
- `options[]`
- `primary_recommendation`
- `rationale`
- `citations[]`
- `assumptions[]`
- `missing_facts[]`
- `confidence`
- `next_action`
- `review_required`

## 23.2 Example Agent Execution Schema

- `agent_id`
- `grant_id`
- `tenant_id`
- `matter_id`
- `requested_action`
- `allowed_scopes[]`
- `tool_calls[]`
- `result_status`
- `approval_required`
- `audit_event_id`

## 23.3 Founder-Stage Infrastructure Notes

Launch on:

- Cloud Run
- Cloud SQL
- GCS
- managed secrets and networking

Upgrade later to:

- GKE
- stronger private networking
- dedicated inference clusters

The product must preserve a no-rewrite migration path.
