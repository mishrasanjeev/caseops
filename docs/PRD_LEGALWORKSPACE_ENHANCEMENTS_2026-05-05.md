# CaseOps LegalWorkspace Enhancement PRD

Status: Draft execution PRD addendum
Date: 2026-05-05
Audience: Codex CLI and CaseOps engineering
Primary repository: `C:\Users\mishr\caseops`
Canonical PRD anchor: `docs/PRD_CLAUDE_CODE_2026-04-23.md`

## 1. Purpose

This document converts the two LegalWorkspace feedback documents into a development-ready CaseOps enhancement plan. It is meant to be handed to Codex CLI as an implementation brief.

The goal is not to create a generic legal CRM. The goal is to extend CaseOps as a matter-native legal operating system with stronger case lifecycle structure, forum/court mapping, document sequencing, contracts metadata, employee administration, and permission governance.

## 2. Source Inputs

This PRD reconciles four classes of evidence:

1. User feedback documents from `C:\Users\mishr\Downloads`:
   - `LegalWorkspace - Detailed Functional Flow (Based on Feedback).docx`
   - `LegalWorkspace - Employee Management & RBAC Module.docx`
2. Canonical product source:
   - `docs/PRD_CLAUDE_CODE_2026-04-23.md`
3. Current gap and hardening ledgers:
   - `docs/WORK_TO_BE_DONE.md`
   - `docs/PRD_COVERAGE_MOD_TS_2026-04-20.md`
   - `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`
   - `docs/PRODUCT_GAP_ANALYSIS_2026-05-01.md`
   - `docs/STRICT_PRODUCT_GAPS_2026-04-30.md`
   - `docs/RELEASE_NOTES_2026-05-01.md`
4. Current repo code scan of API routes, database models, web app pages, and tests.

## 3. How Codex CLI Should Use This PRD

Before implementation, Codex CLI must read:

1. `AGENTS.md`
2. `.agents/skills/caseops-prd-execution/SKILL.md`
3. `docs/PRD_CLAUDE_CODE_2026-04-23.md`
4. This document
5. Any target module files listed in the relevant implementation slice

For frontend work, Codex CLI must also read:

1. `.impeccable.md`
2. `.Codex/skills/impeccable/SKILL.md`, or the local vendored equivalent if the repo has moved it

For bug triage discovered during implementation, Codex CLI must read `.Codex/skills/bug-fixing/SKILL.md` before closing any defect.

## 4. Product Intent

The LegalWorkspace feedback asks for three broad upgrades:

1. Matter lifecycle clarity:
   - Case timeline
   - Hearing history
   - Order sheets
   - Legal document sequence
   - Interim order and stay tracking
   - Forum hierarchy
   - Claim amount tracking
   - Rich search and tagging
2. Enterprise operations:
   - Employee directory
   - Manual and bulk onboarding
   - Role and permission administration
   - Employee lifecycle and offboarding
   - Auditability of people and permission changes
3. Contract operations:
   - Contract type normalization
   - Legal classification by acts, sections, and clauses
   - Contract term extraction
   - Ancillary document linking

These upgrades should feel native to CaseOps, not bolted on. They must preserve:

- Strict multi-tenant isolation
- Matter-level permissions and ethical walls
- Auditable sensitive actions
- Citation and source-grounded legal intelligence
- Fail-closed authorization
- Migration readiness from Cloud Run to GKE
- Temporal as the required durable orchestration path for critical workflows
- Grantex as the future trust plane for delegated agent identity, revocation, budgets, and audit

## 5. Non-Goals

This PRD does not authorize:

- Black-box judge favorability scoring
- Unsupported legal risk scores
- Autonomous filing or external legal action without human review
- Cross-tenant training on customer data
- Emailing raw passwords in production
- Replacing matter permissions with broad role access
- Rebuilding existing modules from scratch
- Adding speculative framework layers beyond the concrete requirements here
- Moving to beta, preview, nightly, experimental, AGPL, SSPL, BSL, BUSL, or similarly restrictive production dependencies without explicit approval

## 6. Current Repo Truth

This section records the current implementation state as of the 2026-05-05 code scan.

### 6.1 Existing API Surface

Relevant API routes exist under `apps/api/src/caseops_api/api/routes`:

- `matters.py`
- `contracts.py`
- `calendar.py`
- `clients.py`
- `communications.py`
- `companies.py`
- `teams.py`
- `notifications.py`
- `email_templates.py`
- `courts.py`
- `drafting.py`
- `recommendations.py`
- `portal.py`
- `admin.py`

### 6.2 Existing Web Surface

Relevant web pages exist under `apps/web/app`:

- `/app/matters`
- `/app/matters/[id]`
- `/app/matters/[id]/documents`
- `/app/matters/[id]/documents/[attachmentId]`
- `/app/matters/[id]/drafts`
- `/app/matters/[id]/hearings`
- `/app/matters/[id]/recommendations`
- `/app/matters/[id]/strategy`
- `/app/matters/[id]/statutes`
- `/app/matters/[id]/communications`
- `/app/matters/[id]/billing`
- `/app/matters/[id]/audit`
- `/app/calendar`
- `/app/hearings`
- `/app/contracts`
- `/app/contracts/[id]`
- `/app/clients`
- `/app/clients/[id]`
- `/app/admin`
- `/app/admin/teams`
- `/app/admin/notifications`
- `/app/admin/email-templates`
- `/app/today`
- portal pages

### 6.3 Existing Models

Relevant existing models in `apps/api/src/caseops_api/db/models.py` include:

- `CompanyMembership`
- `Matter`
- `MatterTask`
- `MatterHearing`
- `MatterCourtOrder`
- `MatterAttachment`
- `MatterInvoice`
- `Client`
- `OutsideCounsel`
- `Contract`
- `ContractAttachment`
- `AuditEvent`
- `MatterAccessGrant`
- `EthicalWall`
- `MatterDeadline`
- `Team`
- `TeamMembership`
- `EmailTemplate`
- `PortalUser`
- `MatterPortalGrant`

Important current gaps:

- `Matter` does not have claim amount fields.
- `Matter` uses `client_name` and `opposing_party`, not distinct plaintiff and defendant fields.
- There is no tenant-scoped matter tag model.
- `MatterAttachment` does not store legal document type, lifecycle stage, sequence index, stay/interim flags, or linked order metadata.
- `MatterCourtOrder` stores order date, title, summary, text, source, and source reference, but not judge/bench metadata, attachment linkage, order kind, interim/stay flags, or stay status.
- `CompanyMembership` stores company/user/role/active/session fields, but not mobile, designation, department, employee code, manager, or employee lifecycle metadata.
- RBAC is currently based on fixed roles and server capability maps, not tenant-defined custom roles.
- `Contract.contract_type` is freeform text, not a controlled type.
- Contract attachments are not categorized as amendments, annexures, approvals, purchase orders, or other ancillary documents.

### 6.4 Existing Permission Model

The current static membership roles are:

- `owner`
- `admin`
- `partner`
- `member`
- `paralegal`
- `viewer`

Server-side capability rules live in `api/dependencies.py` and the web mirror lives in `apps/web/lib/capabilities.ts`.

This is a good foundation. It is not yet the custom RBAC module requested in the employee/RBAC feedback document.

### 6.5 Existing Calendar and Alerts

Current calendar support includes:

- `/api/calendar/events`
- `/api/calendar/events.ics`
- Aggregation of hearings, tasks, and deadlines
- Calendar UI with month/week/day views
- ICS export/subscription support
- Hearing reminder rows and provider-gated sending through email/SMS/WhatsApp/in-app channel fields

Current gaps:

- No Microsoft Graph OAuth Outlook connection.
- No true push sync into Outlook calendars.
- No full in-app notification center for all notification types.
- Hearing reminders use custom scheduling/worker logic, not Temporal. New durable reminder and calendar sync work should not expand this ad hoc path.

### 6.6 Existing Matters Navigation

The current matter cockpit nav includes:

- Overview
- Documents
- Drafts
- Hearings
- Recommendations
- Strategy
- Statutes
- Communications
- Billing
- Audit

Current gaps against the canonical PRD and LegalWorkspace feedback:

- No dedicated Timeline tab.
- No dedicated Orders tab.
- No Calendar and Deadlines tab inside matter cockpit.
- No Tasks tab inside matter cockpit.
- No Access tab inside matter cockpit.
- Recommendations and Strategy both exist, but need clearer product distinction.

## 7. Enhancement Map

Statuses use the CaseOps roadmap vocabulary:

- `Implemented`
- `Partially implemented`
- `Missing`
- `Stale-doc`

| ID | Feedback item | Canonical PRD mapping | Current repo status | Required action |
| --- | --- | --- | --- | --- |
| LW-001 | Case timeline with hearings in chronological order | Matters, Hearings, Calendar; US-004, US-005, US-022, FT-004, FT-037 | Implemented in LW-S2 | Matter timeline API and Timeline tab compose hearings, orders, documents, deadlines, tasks, and activity with access checks, bounded source queries, and deterministic ordering. |
| LW-002 | Hearing entries include date, forum, stage, remarks, completed/upcoming | Matters and Hearings; US-005, US-022, FT-037, FT-038 | Implemented in LW-S2 | Hearings are split into completed/upcoming sections with date, forum/stage/status, and remarks while preserving existing hearing status semantics. |
| LW-003 | Legal document lifecycle sequencing | Documents/OCR; US-007, US-008, FT-009 through FT-015 | Implemented in LW-S3 | Attachment metadata covers document type, lifecycle stage, document date, sequence index, and linked court order; upload/edit UI handles legacy unclassified documents and lifecycle grouping. |
| LW-004 | Interim order and stay tracking | Matters, Hearings, Audit; US-005, US-022, US-041, FT-037, FT-063 | Implemented in LW-S2 | Court orders carry order kind, interim, and stay metadata; matter list/header/timeline/order surfaces show stay/interim badges and audit stay/interim changes. |
| LW-005 | Hierarchical forum selector | Courts/Judge Intelligence; US-014, US-015, FT-023, FT-024 | Implemented in LW-S4 | Forum catalog supports Supreme Court, High Court, District Court, and Consumer Forum hierarchy with legacy court_name fallback and spoof-resistant court_id validation. |
| LW-006 | Order sheet management with date, judge/bench, summary, attachment, sort toggle | Hearings and Courts; US-005, US-014, FT-037, FT-023 | Implemented in LW-S2 | Hearings page order section supports bench/judge, order kind, linked viewer attachment, interim/stay metadata, and latest/oldest sorting; a separate Orders tab remains intentionally deferred. |
| LW-007 | Party-based search and auto-tagging | Matter search, Clients, Recommendations; US-004, US-006, US-026, FT-004, FT-034 | Implemented in LW-S1 with deterministic suggestions | Server filters and tenant-scoped tags support party/client/opponent search, tag CRUD, access-scoped tag listing, suggestions, and visible-row bulk assignment; no LLM auto-tagging is used in v1. |
| LW-008 | Outlook calendar sync | Calendar and Notifications; US-022, US-023, FT-037 through FT-043 | Implemented with manual sync; durable automation blocked pending Temporal | ICS remains available; Outlook connection state, token-safe OAuth API, and idempotent manual hearing sync are implemented in LW-S10. |
| LW-009 | Hearing and order alerts | Calendar and Notifications; US-023, US-024, FT-040 through FT-043 | Implemented for tenant-scoped rules and in-app new-order notifications; external durable delivery blocked pending Temporal | Notification rules, scope validation, transactional in-app notification creation for linked order uploads, and admin controls are implemented; Temporal-backed email/SMS/WhatsApp retry remains blocked. |
| LW-010 | Matter audit filters and export | Admin and Audit; US-041, FT-059 through FT-063 | Implemented in LW-S11 | Per-matter `AuditEvent` list supports date, actor, action, keyword filters, safe pagination, and scoped JSONL/CSV export. |
| LW-011 | Recommendation and Strategy tab overlap | Recommendations and Strategy; US-026, US-027, US-028, FT-034 through FT-036 | Implemented in LW-S11 | AI Recommendations remain system decision support; Strategy Plan uses separate lawyer-owned strategy entries with CRUD and audit. |
| LW-012 | Enhanced matter filters | Matters; US-004, US-006, FT-004, FT-005 | Implemented in LW-S1 | Matter API/list filters cover party/client/opponent, forum, court, status, created range, next-hearing range, tags, stay, and claim amount while preserving pagination. |
| LW-013 | Claim amount tracking | Matters, Billing, Portfolio; US-004, US-032, US-033 | Implemented in LW-S1 | Claim amount, currency, and notes persist, validate, display, filter, and audit; frontend formatting has a safe fallback for legacy/invalid display values. |
| LW-014 | Contract legal classification by acts/sections/clauses | Contracts, Research/Statutes; US-011, US-029, US-030, FT-050 through FT-054 | Implemented | Source-grounded legal references have APIs, UI review state, audit, and AI suggestions cannot bypass review into accepted. |
| LW-015 | Contract type dropdown | Contracts; US-029, FT-050 | Implemented | Controlled type keys are supported with known legacy-value mapping and safe unknown/freeform notes preservation. |
| LW-016 | Contract term extraction | Contracts; US-029, US-030, FT-050, FT-052 | Implemented | Reviewable term suggestions require source evidence before acceptance and use terminal accepted/rejected states. |
| LW-017 | Ancillary contract documents | Contracts; US-029, FT-050, FT-051 | Implemented | Attachment role, parent link, date, and notes metadata categorize grouped ancillary contract documents with cycle protection. |
| LW-018 | Manual employee creation | Admin/Teams; US-040, US-041, FT-059 through FT-063 | Implemented in LW-S5 | EmployeeProfile storage, manual employee create/read/update APIs, manager validation, setup/reset token flow, safe delivery status, and local/test-only debug tokens are implemented. |
| LW-019 | Bulk employee upload | Admin/Teams; US-040, US-041, FT-059 through FT-063 | Implemented in LW-S6 | CSV/XLSX templates, preview jobs/rows, row validation, formula rejection, tenant-scoped duplicate checks, expiry, commit/cancel, secure setup-token creation, and audit are implemented. |
| LW-020 | Employee directory | Admin/Teams; US-040, FT-059 | Implemented in LW-S5 | `/app/admin/employees` provides directory filters, add/edit flows, status/role display, setup/reset actions, and later-slice bulk/offboarding entry points against tenant-scoped APIs. |
| LW-021 | Default roles and permissions | Admin/Teams; US-040, FT-059, SEC route guards | Implemented with LW-S7 capability catalog | Existing fixed roles are preserved and server-resolved capability summaries are exposed; custom role templates cover tenant-defined overrides without introducing a separate LegalWorkspace role-name taxonomy. |
| LW-022 | Custom roles | Admin/Teams; US-040, US-041, FT-059, SEC-authorization tests | Implemented in LW-S7 repair | Revoked/inactive/missing custom roles fail closed; same-second session invalidation and delegable-capability guards are covered by targeted tests. |
| LW-023 | Permission enforcement in API and UI | Admin/Teams; US-040, US-041, FT-059 through FT-063 | Implemented in LW-S7 repair | Server-resolved capabilities drive route guards and sidebar navigation; owner-only, non-delegable, self-assignment, and self-unassignment escalation paths remain blocked. |
| LW-024 | Employee lifecycle/offboarding | Admin/Teams/Audit; US-040, US-041, FT-059 through FT-063 | Implemented in LW-S8 | Offboarding preview/commit covers supported reassignment, inactive/session revocation, last-owner guard, tenant-only active replacement, ethical-wall blockers, and audit. |
| LW-025 | Password reset, first-login setup, onboarding notifications | Admin/Email templates; US-040, US-041, FT-059, FT-062 | Implemented with LW-S5 delivery caveat | Single-use hashed setup/reset tokens, first-login setup completion, reset completion, resend/reset admin actions, safe delivery status, and mailer hooks are implemented; actual outbound delivery depends on configured mail provider/templates. |
| LW-026 | Employee audit and login activity | Admin/Audit; US-041, FT-059 through FT-063 | Implemented in LW-S8 | Employee admin history reads audit events for create/update/setup/reset/role/custom-role/login/deactivate/offboard where rows exist. |

## 8. Additive Story and Test IDs

The canonical PRD remains the source of truth. The following IDs are proposed addenda for this LegalWorkspace enhancement track. If implementation begins, update the canonical PRD in the same branch or explicitly link this addendum from it.

### 8.1 New User Stories

| Story ID | User story |
| --- | --- |
| US-LW-001 | As a lawyer, I can see a matter timeline that combines hearings, court orders, uploaded documents, deadlines, tasks, and material activity in one chronological view. |
| US-LW-002 | As a lawyer, I can distinguish completed and upcoming hearings, with date, forum, stage, status, and remarks visible without opening multiple tabs. |
| US-LW-003 | As a paralegal, I can upload documents with legal lifecycle type so the repository reflects complaint, pleadings, evidence, orders, and judgments in the expected sequence. |
| US-LW-004 | As a lawyer, I can flag interim orders and stays so urgent status is visible on the matter list, matter header, order sheet, and timeline. |
| US-LW-005 | As a legal ops user, I can select the correct forum through a hierarchy for Supreme Court, High Courts, District Courts, and Consumer Forums. |
| US-LW-006 | As a legal ops user, I can search and filter matters by party, forum, status, date range, tags, stay status, and claim amount. |
| US-LW-007 | As a legal ops user, I can track claim amount on matters for financial prioritization and portfolio reporting. |
| US-LW-008 | As a lawyer, I can sync hearings to Outlook when my calendar is connected, while still having ICS export as a fallback. |
| US-LW-009 | As an admin, I can create employees manually with role, department, designation, mobile number, and secure account setup flow. |
| US-LW-010 | As an admin, I can bulk upload employees from CSV/XLSX, preview validation errors, and commit only valid rows. |
| US-LW-011 | As an admin, I can create custom role templates from approved CaseOps capabilities without granting unsafe owner-only privileges. |
| US-LW-012 | As an admin, I can deactivate an employee, revoke active sessions, and reassign matters, contracts, tasks, drafts, approvals, and notifications. |
| US-LW-013 | As an admin, I can audit employee creation, role changes, login activity, password resets, deactivation, and reassignment. |
| US-LW-014 | As a contracts user, I can classify a contract by type, legal acts/sections, clauses, term dates, and related ancillary documents. |
| US-LW-015 | As a reviewing lawyer, I can approve or edit AI-suggested contract legal classification and term extraction before it changes canonical metadata. |
| US-LW-016 | As a lawyer, I can distinguish AI recommendations from lawyer-owned strategy planning so I do not confuse generated options with approved legal strategy. |

### 8.2 New Functional Test IDs

| Test ID | Verification |
| --- | --- |
| FT-LW-001 | Matter timeline returns normalized event types sorted ascending and descending. |
| FT-LW-002 | Timeline enforces tenant isolation and matter access restrictions. |
| FT-LW-003 | Hearings split into completed/upcoming based on status and date. |
| FT-LW-004 | Document upload requires or defaults lifecycle type and persists sequence metadata. |
| FT-LW-005 | Order upload/update supports interim and stay flags and displays badges. |
| FT-LW-006 | Forum selector supports Supreme Court, High Court by state, District Court by state/district, and Consumer Forum hierarchy. |
| FT-LW-007 | Matter search filters by party, forum, status, date range, tags, stay status, and claim amount. |
| FT-LW-008 | Matter tag suggestion and bulk assignment are tenant-scoped and auditable. |
| FT-LW-009 | Claim amount persists, displays, filters, and audits changes. |
| FT-LW-010 | Outlook sync creates or updates an external event only for authorized users with connected accounts. |
| FT-LW-011 | New order upload triggers notification rules and in-app notification state. |
| FT-LW-012 | Matter audit tab filters by date, actor, action, and exports scoped events. |
| FT-LW-013 | Employee manual creation validates fields, role, email uniqueness, and emits setup token. |
| FT-LW-014 | Employee bulk import validates all rows, previews errors, and commits only confirmed rows. |
| FT-LW-015 | Employee directory filters by role, status, department, name, and email. |
| FT-LW-016 | Custom role creation cannot grant owner-only capabilities without owner authority. |
| FT-LW-017 | Custom role assignment changes server-resolved capabilities and revokes stale sessions where needed. |
| FT-LW-018 | Offboarding preview lists owned/assigned objects and commit reassigns them transactionally. |
| FT-LW-019 | Deactivated employees cannot log in or use existing sessions. |
| FT-LW-020 | Employee audit captures create, update, role change, reset, deactivate, login, and offboard events. |
| FT-LW-021 | Contract type dropdown persists controlled values and supports other with notes. |
| FT-LW-022 | Contract legal references link acts/sections/clauses to source evidence and remain reviewable. |
| FT-LW-023 | Contract term extraction creates suggestions and does not overwrite approved fields without confirmation. |
| FT-LW-024 | Contract ancillary documents display by role and link to the primary contract or amendment. |
| FT-LW-025 | Recommendations and Strategy display distinct data models and labels. |

### 8.3 New Security and Nonfunctional Test IDs

| Test ID | Verification |
| --- | --- |
| SEC-LW-001 | Every new employee, custom role, tag, calendar connection, import job, and contract metadata object is tenant-scoped. |
| SEC-LW-002 | Matter access grants and ethical walls override broad role capabilities. |
| SEC-LW-003 | Custom roles fail closed when permissions are unknown, revoked, inactive, or malformed. |
| SEC-LW-004 | Bulk import rejects formula injection, oversized files, unsupported MIME types, duplicate emails, and cross-tenant references. |
| SEC-LW-005 | Setup and reset tokens are single-use, hashed at rest, time-limited, and audited. |
| SEC-LW-006 | Calendar OAuth tokens are encrypted or stored through the approved secret mechanism and never exposed to the client. |
| SEC-LW-007 | AI contract classification includes source lineage and does not become canonical without human acceptance. |
| NFT-LW-001 | Matter list filters preserve keyset pagination and do not regress p95 latency on seeded data. |
| NFT-LW-002 | Employee bulk preview handles at least 1,000 rows without timing out locally. |
| NFT-LW-003 | Timeline endpoint handles at least 500 events for one matter without N+1 query behavior. |
| NFT-LW-004 | Admin role and employee pages meet accessibility checks for keyboard navigation and labels. |
| NFT-LW-005 | Notification delivery is retryable, observable, and durable once Temporal is introduced. |

## 9. Global Acceptance Criteria

Every implementation slice must satisfy:

1. All new persistent business objects include `company_id` or are otherwise provably tenant-scoped.
2. Every sensitive action emits an `AuditEvent`.
3. Matter-level access and ethical walls override broad role access.
4. UI gating is backed by server authorization, not only client capability checks.
5. New APIs use explicit typed request/response schemas.
6. Validation errors are precise and user-actionable.
7. Migrations include downgrade paths if the repo convention requires them.
8. Existing tests remain green.
9. Targeted tests for the changed slice are added before closure.
10. Backend verification uses `scripts/verify-backend.sh` or the PowerShell equivalent.
11. Frontend verification includes typecheck and relevant component/page tests.
12. No workflow that must be durable is implemented as a new ad hoc background loop.

## 10. Epic A: Matter Timeline and Hearing Flow

### 10.1 Problem

The feedback asks for a chronological case timeline and hearing flow. Current CaseOps has matter hearings, court sync, court orders, documents, activity, tasks, and deadlines, but these are spread across multiple screens and not normalized into one end-user timeline.

### 10.2 Required Behavior

Users must be able to open a matter and see:

- Upcoming hearings
- Completed hearings
- Court orders
- Uploaded documents
- Important deadlines
- Matter tasks
- Material audit/activity events

The default sort for the legal timeline should be ascending by event date, because lawyers often need to understand procedural history. The UI should also allow latest-first sorting for operational review.

### 10.3 Data Model

Prefer a composed read model for v1, not a new duplicated timeline table.

Add or normalize fields only where source models lack required semantics:

`MatterHearing`:

- Keep existing `hearing_on`, `forum_name`, `purpose`, `status`, and `outcome_note` if present.
- Ensure response schema exposes:
  - `hearing_date`
  - `forum`
  - `stage`
  - `status`
  - `remarks`
  - `is_completed`
  - `is_upcoming`

`MatterCourtOrder` additions:

- `bench_name`: nullable string
- `judge_names_json`: nullable JSON array of strings
- `order_attachment_id`: nullable FK to `MatterAttachment`
- `order_kind`: enum
  - `daily_order`
  - `interim_order`
  - `stay_order`
  - `final_judgment`
  - `other`
- `stay_status`: enum
  - `none`
  - `granted`
  - `continued`
  - `modified`
  - `vacated`
  - `unknown`
- `stay_effective_until`: nullable date

Do not add a generic event table in v1 unless performance testing proves composition is too slow.

### 10.4 API

Add:

`GET /api/matters/{matter_id}/timeline`

Query parameters:

- `from`: optional ISO date
- `to`: optional ISO date
- `types`: optional comma-separated event types
- `sort`: `asc` or `desc`, default `asc`
- `limit`: default 100, max 500
- `cursor`: optional keyset cursor

Response shape:

```json
{
  "matter_id": "uuid",
  "sort": "asc",
  "items": [
    {
      "id": "hearing:uuid",
      "event_type": "hearing",
      "event_date": "2026-05-10",
      "title": "Arguments",
      "status": "upcoming",
      "summary": "Listed for arguments",
      "source_type": "matter_hearing",
      "source_id": "uuid",
      "badges": ["upcoming"],
      "links": {
        "matter": "/app/matters/...",
        "document": null
      }
    }
  ],
  "next_cursor": null
}
```

Allowed `event_type` values:

- `hearing`
- `court_order`
- `document`
- `deadline`
- `task`
- `activity`

Authorization:

- Require matter read access.
- Apply team restrictions, restricted access, matter grants, and ethical walls.
- Do not leak event counts for inaccessible matters.

### 10.5 Frontend

Add a `Timeline` tab to the matter cockpit.

The tab must support:

- Upcoming/completed hearing sections
- Full chronological timeline
- Event type filters
- Ascending/latest-first sort toggle
- Compact legal metadata:
  - Date
  - Forum/court
  - Stage
  - Order kind
  - Stay status
  - Document type
  - Actor for activity events
- Deep links to source records when available

Do not make the page decorative. It should feel like a dense legal operations screen.

### 10.6 Acceptance Criteria

- A matter with hearings, documents, orders, deadlines, tasks, and activity displays a single timeline.
- Hearing dates sort ascending by default.
- Completed hearings are visually distinct from upcoming hearings.
- Stay/interim badges appear when an order has relevant flags.
- Timeline filters do not expose inaccessible data.
- Empty state explains that no timeline events exist yet and offers the next relevant action if the user has permission.

### 10.7 Suggested Files

Backend:

- `apps/api/src/caseops_api/api/routes/matters.py`
- `apps/api/src/caseops_api/schemas/matters.py`
- `apps/api/src/caseops_api/db/models.py`
- `apps/api/src/caseops_api/services/matter_access.py`
- new service if needed: `apps/api/src/caseops_api/services/matter_timeline.py`

Frontend:

- `apps/web/app/app/matters/[id]/page.tsx`
- `apps/web/app/app/matters/[id]/timeline/page.tsx`
- `apps/web/components/matters/MatterCockpitNav.tsx`
- new component: `apps/web/components/matters/MatterTimeline.tsx`

Tests:

- `apps/api/tests/test_legalworkspace_matter_timeline.py`
- `apps/web/tests/matters-timeline.test.tsx`
- `tests/e2e/legalworkspace-matter-timeline.spec.ts`

## 11. Epic B: Document Lifecycle Sequencing

### 11.1 Problem

The feedback requires legal documents to be organized by procedural sequence: complaint/petition, pleadings/reply, evidence, orders/judgment. Current uploads process documents, extract text, and index content, but do not capture legal lifecycle metadata.

### 11.2 Required Behavior

During upload, users must choose or confirm a document type. The document repository and timeline must display documents in a legally meaningful sequence.

### 11.3 Document Type Taxonomy

Use a controlled enum with room for `other`.

Initial values:

- `complaint_petition`
- `notice`
- `vakalatnama`
- `pleading_reply`
- `affidavit`
- `evidence`
- `written_submission`
- `interim_application`
- `order_judgment`
- `correspondence`
- `research`
- `billing`
- `other`

Lifecycle groups:

- `initiation`
- `pleadings`
- `interim_applications`
- `evidence`
- `arguments`
- `orders`
- `post_order`
- `administrative`
- `other`

### 11.4 Data Model

Add to `MatterAttachment`:

- `document_type`: nullable enum/string
- `lifecycle_stage`: nullable enum/string
- `document_date`: nullable date
- `sequence_index`: nullable integer
- `linked_court_order_id`: nullable FK to `MatterCourtOrder`
- `metadata_json`: JSON object if an existing metadata field is not already available

If `metadata_json` already exists in the repo under a different name, reuse it instead of creating another JSON field.

### 11.5 API

Update upload request handling to accept metadata:

- `document_type`
- `lifecycle_stage`
- `document_date`
- `linked_court_order_id`
- `is_interim_order`
- `stay_status`

Add:

`PATCH /api/matters/{matter_id}/attachments/{attachment_id}/metadata`

The endpoint must:

- Require document management permission for edits.
- Preserve existing text extraction and embedding behavior.
- Audit metadata changes.
- Reject invalid order linkage across tenants or matters.

### 11.6 Frontend

Update the document upload dialog:

- Add document type select.
- Add lifecycle stage derived from document type but editable by users with permission.
- If `order_judgment`, show optional order metadata:
  - Order date
  - Bench/judge
  - Interim order checkbox
  - Stay status select
- Show repository groups by lifecycle sequence.
- Show badges in document list and viewer.

### 11.7 Acceptance Criteria

- Uploading a document with type persists the type and lifecycle stage.
- Existing documents without type continue to work and display as unclassified.
- Users can edit metadata after upload if authorized.
- Documents appear in the correct lifecycle group.
- Order documents can link to order sheet entries.
- Audit logs capture metadata edits.

## 12. Epic C: Interim Orders, Stay Tracking, and Order Sheets

### 12.1 Problem

Interim orders and stays are urgent legal facts. They need to be visible in matter lists, headers, timelines, and order sheets. Current `MatterCourtOrder` does not model these fields.

### 12.2 Required Behavior

Users must be able to:

- Mark an order as interim.
- Mark a stay as granted, continued, modified, vacated, unknown, or none.
- Attach an order document.
- See stay/interim indicators on:
  - Matter list
  - Matter header
  - Timeline
  - Hearings/orders page
  - Order details

### 12.3 API

Add or extend:

`GET /api/matters/{matter_id}/orders`

Query parameters:

- `sort`: `latest` or `oldest`
- `kind`
- `stay_status`

`POST /api/matters/{matter_id}/orders`

`PATCH /api/matters/{matter_id}/orders/{order_id}`

`DELETE /api/matters/{matter_id}/orders/{order_id}`

Deletion should be soft delete if the repo convention supports it. If not, require strong authorization and audit hard deletes.

### 12.4 Frontend

Update existing Hearings page or add an Orders tab. The conservative v1 path is:

- Keep `Hearings` tab.
- Add a first-class `Orders` section inside it.
- Add `Timeline` tab for unified chronology.
- Consider splitting `Orders` into its own tab later if usage justifies it.

Orders list must show:

- Order date
- Judge/bench if known
- Summary
- Attachment link
- Order kind
- Stay status
- Source
- Latest/oldest toggle

### 12.5 Acceptance Criteria

- A stay order appears as a clear badge on the matter list and header.
- Sorting works both latest-first and oldest-first.
- Order attachment opens in the document viewer.
- Updating stay status creates an audit event.
- Unauthorized users cannot edit order metadata.

## 13. Epic D: Hierarchical Forum Selection

### 13.1 Problem

The feedback requires hierarchical forum selection:

- Supreme Court directly selectable
- High Court by state
- District Court by state and district/city
- Consumer forums by national/state/district hierarchy

Current CaseOps has a court catalog and forum levels, but the matter creation UI uses a simple forum level enum and free-text court fields.

### 13.2 Required Behavior

The create/edit matter flow must guide users to the correct forum and court.

Hierarchies:

1. Supreme Court
   - Supreme Court of India
2. High Court
   - State or union territory
   - High Court for that state or jurisdiction
3. District Court
   - State
   - District or city
   - District court
4. Consumer Forum
   - National: NCDRC
   - State: SCDRC by state
   - District: DCDRC by state and district/city

### 13.3 Data Model

Prefer extending the existing `Court` model if it can cleanly support the hierarchy.

Add fields if absent:

- `parent_court_id`: nullable FK to `Court`
- `forum_subtype`: enum/string
  - `supreme_court`
  - `high_court`
  - `district_court`
  - `consumer_national`
  - `consumer_state`
  - `consumer_district`
  - `tribunal`
  - `arbitration`
  - `advisory`
- `state_code`: nullable string
- `state_name`: nullable string
- `district_name`: nullable string
- `city_name`: nullable string
- `external_source`: nullable string, for eCourts/NCDRC lineage
- `external_id`: nullable string
- `active`: existing or new boolean

If extending `Court` creates risk, create a public catalog table:

- `ForumCatalogNode`
- `Court` remains the canonical operational court table
- Matter stores `court_id` plus catalog path metadata

### 13.4 API

Add:

`GET /api/courts/forum-catalog`

Query parameters:

- `forum_type`
- `state`
- `district`
- `parent_id`

Response:

```json
{
  "items": [
    {
      "id": "uuid",
      "label": "Delhi High Court",
      "forum_type": "high_court",
      "state": "Delhi",
      "district": null,
      "court_id": "uuid",
      "children_available": false
    }
  ]
}
```

Update matter create/update schemas:

- Accept `court_id`.
- Accept forum catalog selection metadata.
- Preserve existing `court_name` fallback for imports and legacy records.

### 13.5 Frontend

Build reusable `ForumSelector`.

The component should:

- Use segmented/select controls for forum type.
- Dynamically reveal state and district selects.
- Fetch data from the catalog endpoint.
- Populate `forum_level`, `court_id`, and `court_name`.
- Work in `NewMatterDialog` and matter edit flow.
- Degrade gracefully when catalog is empty.

### 13.6 Acceptance Criteria

- Supreme Court selection requires no state.
- High Court selection requires state.
- District Court selection requires state and district/city.
- Consumer Forum selection supports national, state, and district levels.
- Matter creation stores a valid `court_id` when selected.
- Old matters with only `court_name` still render.
- Tenant data never leaks through public catalog lookup.

## 14. Epic E: Matter Search, Tags, and Claim Amount

### 14.1 Problem

The feedback asks for party-based search, enhanced filters, organization tagging, and claim amount tracking. Current matter list search is mostly client-side and the `Matter` model lacks claim amount and tags.

### 14.2 Required Behavior

Users must be able to search/filter matters by:

- Plaintiff/client name
- Defendant/opposing party name
- Forum level
- Court
- Case status
- Date range
- Tag
- Stay status
- Claim amount range

Users must be able to tag cases manually and receive deterministic tag suggestions for obvious organization names.

### 14.3 Data Model

Add to `Matter`:

- `claim_amount_minor`: nullable bigint
- `claim_currency`: string default `INR`
- `claim_amount_notes`: nullable string

Add:

`MatterTag`

- `id`
- `company_id`
- `name`
- `slug`
- `color_key`: nullable string, use controlled palette tokens in UI
- `created_by_membership_id`
- `created_at`
- unique `(company_id, slug)`

`MatterTagAssignment`

- `id`
- `company_id`
- `matter_id`
- `tag_id`
- `source`: enum/string
  - `manual`
  - `suggested`
  - `bulk`
  - `import`
- `created_by_membership_id`
- `created_at`
- unique `(matter_id, tag_id)`

### 14.4 Tag Suggestions

V1 should be deterministic:

- Suggest tags from `client_name`.
- Suggest tags from `opposing_party`.
- Suggest tags from known `Client` names.
- Suggest tags from explicit user-entered organization names.

Do not use LLM tagging in v1 unless source lineage and human review are included. Do not tag across tenants.

### 14.5 API

Update:

`GET /api/matters`

Add filters:

- `q`
- `client_name`
- `opposing_party`
- `forum_level`
- `court_id`
- `status`
- `created_from`
- `created_to`
- `next_hearing_from`
- `next_hearing_to`
- `tag`
- `has_stay`
- `min_claim_amount_minor`
- `max_claim_amount_minor`

Add:

- `GET /api/matter-tags`
- `POST /api/matter-tags`
- `PATCH /api/matter-tags/{tag_id}`
- `DELETE /api/matter-tags/{tag_id}`
- `POST /api/matters/{matter_id}/tags`
- `DELETE /api/matters/{matter_id}/tags/{tag_id}`
- `POST /api/matters/bulk-tags`
- `GET /api/matters/{matter_id}/tag-suggestions`

### 14.6 Frontend

Matter list:

- Add filter bar or filter drawer.
- Add claim amount column.
- Add tags column.
- Add stay/interim indicator column.
- Keep table dense and scannable.
- Preserve pagination.

Matter detail:

- Add claim amount to header/overview.
- Add tags editor where appropriate.
- Audit all edits.

### 14.7 Acceptance Criteria

- Filtering works server-side and respects pagination.
- Claim amount displays in list and detail.
- Claim amount updates are audited.
- Tags are tenant-scoped.
- Bulk tag action cannot include inaccessible matters.
- Tag suggestions never auto-apply without user action.

## 15. Epic F: Calendar, Alerts, and Outlook Sync

### 15.1 Problem

The feedback asks for hearing sync to Outlook and alerts for upcoming hearings/new orders. CaseOps already has calendar aggregation, ICS export, and hearing reminder infrastructure, but not true Outlook sync and not durable Temporal-backed workflow orchestration.

### 15.2 Required Behavior

Users must be able to:

- Export or subscribe to hearings using ICS.
- Connect Outlook using Microsoft Graph OAuth.
- Push selected hearing events to Outlook.
- See sync status.
- Configure hearing reminders.
- Receive in-app/email alerts for new orders when rules are enabled.

### 15.3 Temporal Requirement

CaseOps architecture requires Temporal for durable workflow orchestration. Therefore:

- Do not expand critical notification delivery as another ad hoc background loop.
- Implement Temporal foundation first if this slice needs durable delivery.
- If Temporal is not yet available, scope v1 to explicit manual sync actions and ICS fallback, and mark automated delivery as blocked.

This directly relates to enterprise hardening item `WTD-5.1`.

### 15.4 Data Model

Add:

`UserCalendarConnection`

- `id`
- `company_id`
- `user_id`
- `provider`: `outlook`
- `provider_account_id`
- `display_email`
- `status`: `connected`, `revoked`, `error`
- `encrypted_token_ref` or approved secret reference
- `scopes_json`
- `connected_at`
- `last_sync_at`
- `created_at`
- `updated_at`

`CalendarEventSync`

- `id`
- `company_id`
- `calendar_connection_id`
- `source_type`: `matter_hearing`, `matter_deadline`, `matter_task`
- `source_id`
- `provider_event_id`
- `sync_status`: `pending`, `synced`, `failed`, `deleted`
- `last_error`
- `last_synced_at`
- unique source mapping per connection

`NotificationRule`

- `id`
- `company_id`
- `scope_type`: `matter`, `company`, `user`
- `scope_id`
- `event_type`: `hearing_upcoming`, `new_order_uploaded`, `stay_status_changed`
- `channels_json`
- `offset_minutes`
- `enabled`
- `created_by_membership_id`

### 15.5 API

Add:

- `GET /api/calendar/connections`
- `POST /api/calendar/connections/outlook/start`
- `GET /api/calendar/connections/outlook/callback`
- `DELETE /api/calendar/connections/{connection_id}`
- `POST /api/calendar/sync/hearings/{hearing_id}`
- `GET /api/calendar/sync-status`
- `GET /api/notification-rules`
- `POST /api/notification-rules`
- `PATCH /api/notification-rules/{rule_id}`
- `DELETE /api/notification-rules/{rule_id}`

### 15.6 Frontend

Calendar and hearing screens:

- Keep ICS export visible.
- Add Outlook connection state.
- Add `Sync to Outlook` action for users with permission.
- Display last synced/error state.
- Add reminder controls in hearing detail or matter hearing row.

Notification UX:

- Add in-app notification state for new orders.
- Add admin notification configuration if the user has permission.

### 15.7 Acceptance Criteria

- ICS export remains functional.
- Outlook tokens are never exposed to the browser after OAuth callback.
- Manual sync creates/updates exactly one external event per source event/connection.
- Users cannot sync inaccessible matters.
- Automated reminders are durable or explicitly blocked until Temporal is in place.
- New order notification emits an audit-visible event and in-app notification.

## 16. Epic G: Matter Audit Filters and Export

### 16.1 Problem

The feedback asks for a case audit tab with user actions, document uploads, filters, and export. Current matter audit/activity exists, and admin audit export exists, but matter-level filtering/export is not first-class.

### 16.2 Required Behavior

Matter audit tab must support:

- Date filter
- Actor filter
- Action filter
- Object type filter
- Export CSV/JSON
- Clear distinction between legal timeline events and audit/security events

### 16.3 Source of Truth

Use `AuditEvent` as the source of truth for audit/security exports. UI activity streams can remain composed/read-optimized, but exports must use audit events.

### 16.4 API

Add:

`GET /api/matters/{matter_id}/audit-events`

Query parameters:

- `from`
- `to`
- `actor_membership_id`
- `action`
- `object_type`
- `limit`
- `cursor`

Add:

`POST /api/matters/{matter_id}/audit-events/export`

Response:

- Either sync CSV for small exports, or async job if existing admin export pattern supports it.

### 16.5 Acceptance Criteria

- Matter audit filters work.
- Export includes only the current matter and current tenant.
- Export action is itself audited.
- Unauthorized users cannot export audit data.
- Existing admin audit export remains intact.

## 17. Epic H: Recommendations vs Strategy

### 17.1 Problem

The feedback says Recommendation and Strategy tabs overlap. Current CaseOps has both tabs. The right product decision is not to delete one blindly. They should represent different ownership and trust states.

### 17.2 Product Distinction

Recommendations:

- AI-generated or system-generated options
- Citation-grounded where legal substance is involved
- Accept/reject/defer/edit workflow
- Risk/uncertainty stated explicitly
- Not automatically treated as approved strategy

Strategy:

- Lawyer-owned plan
- Human-approved path
- Strategic notes
- Escalation planner
- Owners and dates
- Links to recommendations that informed the plan

### 17.3 Required Behavior

Rename or label tabs to make the distinction obvious:

- `AI Recommendations`
- `Strategy Plan`

Do not duplicate the same cards across both tabs.

### 17.4 Acceptance Criteria

- A user can tell which surface is generated insight and which is approved planning.
- Strategy can link to accepted recommendations.
- Legal recommendations remain citation-grounded.
- No recommendation becomes external action without human review.

## 18. Epic I: Contract Metadata Enhancements

### 18.1 Problem

The feedback asks for contract type dropdown, legal classification by acts/sections/clauses, contract term extraction, and ancillary documents. Current contracts have useful foundations, including clauses, obligations, attachments, effective/expiry/renewal fields, and redline tools, but the requested metadata is not complete.

### 18.2 Contract Type

Replace freeform-only `contract_type` UX with controlled options:

- `agreement`
- `nda`
- `addendum`
- `purchase_order`
- `master_services_agreement`
- `statement_of_work`
- `lease`
- `employment`
- `settlement`
- `amendment`
- `other`

Backend should preserve existing string values. Migration should map known strings where possible and display unmapped values as `other` with legacy label.

### 18.3 Legal Classification

Add:

`ContractLegalReference`

- `id`
- `company_id`
- `contract_id`
- `act_name`
- `section_label`
- `clause_label`
- `authority_id`: nullable if linked to internal authority corpus
- `statute_id`: nullable if statute model exists
- `source`: `manual`, `ai_suggested`, `imported`
- `confidence`: nullable numeric
- `evidence_attachment_id`: nullable
- `evidence_quote`: short excerpt only, within copyright and product policy limits
- `status`: `suggested`, `accepted`, `rejected`
- `created_by_membership_id`
- `reviewed_by_membership_id`
- `reviewed_at`

For substantive legal classification, AI output must be reviewable and source-grounded.

### 18.4 Contract Term Extraction

Existing `effective_on`, `expires_on`, and `renewal_on` fields should remain canonical.

Add a suggestion workflow:

`ContractTermSuggestion`

- `id`
- `company_id`
- `contract_id`
- `source_attachment_id`
- `suggested_effective_on`
- `suggested_expires_on`
- `suggested_renewal_on`
- `suggested_duration_months`
- `evidence_json`
- `status`: `suggested`, `accepted`, `rejected`
- `created_at`
- `reviewed_by_membership_id`
- `reviewed_at`

Do not overwrite canonical dates without human acceptance.

### 18.5 Ancillary Documents

Add to `ContractAttachment`:

- `attachment_role`: enum/string
  - `primary_contract`
  - `amendment`
  - `addendum`
  - `annexure`
  - `email_approval`
  - `board_resolution`
  - `purchase_order`
  - `statement_of_work`
  - `supporting_document`
  - `other`
- `parent_attachment_id`: nullable FK for amendments/addenda linked to primary contract
- `document_date`: nullable date
- `notes`: nullable string

### 18.6 API

Add or update:

- `PATCH /api/contracts/{contract_id}/metadata`
- `GET /api/contracts/{contract_id}/legal-references`
- `POST /api/contracts/{contract_id}/legal-references`
- `PATCH /api/contracts/{contract_id}/legal-references/{reference_id}`
- `POST /api/contracts/{contract_id}/term-suggestions`
- `POST /api/contracts/{contract_id}/term-suggestions/{suggestion_id}/accept`
- `POST /api/contracts/{contract_id}/term-suggestions/{suggestion_id}/reject`
- `PATCH /api/contracts/{contract_id}/attachments/{attachment_id}/metadata`

### 18.7 Frontend

Contract detail:

- Metadata panel with controlled contract type.
- Term panel with start/end/renewal/duration.
- AI suggestions panel for term extraction if enabled.
- Legal references panel with acts/sections/clauses.
- Attachments grouped by role.
- Review controls for suggested legal refs and term fields.

### 18.8 Acceptance Criteria

- Controlled type options display and persist.
- Legacy freeform values do not break existing contracts.
- AI suggestions remain suggestions until accepted.
- Accepted term suggestion updates canonical date fields and audits the change.
- Contract legal references include source and review status.
- Ancillary documents display by role and parent link.

## 19. Epic J: Employee Directory and Manual Onboarding

### 19.1 Problem

The feedback asks for employee creation with full name, email, mobile, designation, department, role, status, and credentials/setup flow. Current company user APIs support creating users with email, full name, password, and fixed role, but lack a full employee profile and secure setup-link onboarding flow.

### 19.2 Required Behavior

Admins must be able to:

- Create an employee manually.
- Assign role during creation.
- Store mobile, designation, department, employee status.
- Send a secure setup link.
- Filter and manage employees in a dedicated directory.

### 19.3 Data Model

Option A: extend `CompanyMembership`.

Add fields:

- `mobile`
- `designation`
- `department`
- `employee_code`
- `manager_membership_id`
- `joined_on`
- `employment_status`: `active`, `inactive`, `offboarding`, `invited`
- `last_login_at`
- `force_password_change`

Option B: create `EmployeeProfile`.

Prefer Option B if `CompanyMembership` is already overloaded or shared with non-employee portal/member semantics.

`EmployeeProfile`:

- `id`
- `company_id`
- `membership_id`
- `mobile`
- `designation`
- `department`
- `employee_code`
- `manager_membership_id`
- `joined_on`
- `employment_status`
- `created_at`
- `updated_at`

### 19.4 Account Setup Token

Add:

`AccountSetupToken`

- `id`
- `company_id`
- `user_id`
- `membership_id`
- `token_hash`
- `purpose`: `account_setup`, `password_reset`
- `expires_at`
- `used_at`
- `created_by_membership_id`
- `created_at`

Rules:

- Tokens must be single-use.
- Store only hash at rest.
- Short TTL, recommended 24 hours for account setup and 30 to 60 minutes for password reset unless product decides otherwise.
- Do not email raw passwords in production.

### 19.5 API

Add or update:

- `GET /api/company/employees`
- `POST /api/company/employees`
- `GET /api/company/employees/{membership_id}`
- `PATCH /api/company/employees/{membership_id}`
- `POST /api/company/employees/{membership_id}/resend-setup`
- `POST /api/company/employees/{membership_id}/reset-password`
- `POST /api/auth/account-setup/complete`
- `POST /api/auth/password-reset/start`
- `POST /api/auth/password-reset/complete`

If existing `companies.py` user endpoints are reused, keep backward compatibility and add employee-specific schemas.

### 19.6 Frontend

Add:

- `/app/admin/employees`
- Employee directory table
- Add Employee dialog
- Employee detail/edit drawer
- Role selector
- Status selector
- Reset password action
- Resend setup action
- Deactivate/offboard action

Directory filters:

- Role
- Status
- Department
- Name/email search

### 19.7 Acceptance Criteria

- Admin can create an employee without setting a raw password.
- Setup link is generated and email trigger is recorded.
- Duplicate email is rejected.
- Non-admin users cannot create employees.
- Employee directory filters work.
- All sensitive actions are audited.

## 20. Epic K: Bulk Employee Upload

### 20.1 Problem

The feedback asks for CSV/XLSX bulk onboarding with template download, preview, row errors, duplicate email validation, and onboarding emails.

### 20.2 Required Behavior

Admins must be able to:

1. Download a template.
2. Upload CSV/XLSX.
3. Preview parsed rows.
4. See row-level errors.
5. Confirm import.
6. Create users/employees for valid rows.
7. Send setup emails.
8. Audit the import.

### 20.3 Template Columns

Required:

- `Name`
- `Email`
- `Role`

Optional:

- `Mobile`
- `Designation`
- `Department`
- `EmployeeCode`
- `ManagerEmail`

### 20.4 Data Model

Add:

`EmployeeBulkImportJob`

- `id`
- `company_id`
- `created_by_membership_id`
- `filename`
- `status`: `draft`, `validated`, `committed`, `failed`, `cancelled`
- `total_rows`
- `valid_rows`
- `invalid_rows`
- `error_summary_json`
- `created_at`
- `committed_at`

`EmployeeBulkImportRow`

- `id`
- `company_id`
- `job_id`
- `row_number`
- `raw_json`
- `normalized_json`
- `status`: `valid`, `invalid`, `committed`, `skipped`
- `errors_json`
- `created_membership_id`

### 20.5 API

Add:

- `GET /api/company/employees/import-template.csv`
- `POST /api/company/employees/imports/preview`
- `GET /api/company/employees/imports/{job_id}`
- `POST /api/company/employees/imports/{job_id}/commit`
- `POST /api/company/employees/imports/{job_id}/cancel`

Rules:

- Enforce file size limit.
- Enforce row count limit, v1 target 1,000 rows.
- Reject formula injection in preview/export fields.
- Validate duplicate emails within file and existing tenant.
- Validate role names.
- Validate manager email if supplied.
- Do not commit invalid rows unless UI explicitly offers and confirms `commit_valid_rows_only`.

### 20.6 Frontend

Bulk upload wizard:

1. Download template
2. Upload file
3. Preview rows
4. Resolve errors
5. Confirm
6. Results summary

The preview table must be dense, stable, and keyboard accessible.

### 20.7 Acceptance Criteria

- Template downloads.
- Invalid rows are highlighted with actionable messages.
- Duplicate emails are caught before commit.
- Commit creates employees and setup tokens.
- Audit records job creation and commit.
- Import cannot create users in another tenant.

## 21. Epic L: Custom RBAC and Permission Administration

### 21.1 Problem

The feedback asks for role creation and module/action-level permissions. Current CaseOps has fixed server capabilities and fixed roles, which is safer than no RBAC but not custom tenant-admin role management.

### 21.2 Principles

1. Server is source of truth.
2. Unknown permission means deny.
3. Custom roles cannot grant capabilities outside the safe assignable set.
4. Owner-only capabilities stay owner-only unless explicitly allowed by owner-authenticated flow.
5. Matter access and ethical walls override role permissions.
6. Frontend receives resolved capabilities from server.
7. Role changes revoke stale sessions where needed.

### 21.3 Permission Shape

Expose permissions by module/action:

Case:

- `matters:view`
- `matters:create`
- `matters:edit`
- `matters:archive`
- `matters:documents_upload`
- `matters:documents_manage`
- `matters:orders_view`
- `matters:orders_manage`
- `matters:access_manage`

Contract:

- `contracts:view`
- `contracts:create`
- `contracts:edit`
- `contracts:attachments_manage`
- `contracts:legal_refs_manage`

Audit:

- `audit:view`
- `audit:export`

Employee:

- `employees:view`
- `employees:create`
- `employees:edit`
- `employees:deactivate`
- `employees:bulk_import`
- `roles:manage`

Calendar and Alerts:

- `calendar:view`
- `calendar:sync`
- `notifications:manage`

Map these to existing `CAPABILITY_ROLES` names wherever possible. Do not invent a second permission universe if existing capabilities already cover the action.

### 21.4 Data Model

Add:

`CustomRole`

- `id`
- `company_id`
- `name`
- `slug`
- `description`
- `base_role`: nullable existing membership role
- `permissions_json`
- `is_system`
- `is_active`
- `created_by_membership_id`
- `updated_by_membership_id`
- `created_at`
- `updated_at`

Add to `CompanyMembership` or separate assignment table:

- `custom_role_id`: nullable FK to `CustomRole`

If multiple roles per user are needed later, defer it. V1 should allow one effective custom role per membership to avoid permission ambiguity.

### 21.5 Capability Resolution

Implement service:

`apps/api/src/caseops_api/services/capabilities.py`

Functions:

- `resolve_membership_capabilities(session, membership) -> set[str]`
- `can_assign_capabilities(actor_membership, capabilities) -> bool`
- `validate_custom_role_permissions(actor_membership, permissions) -> None`

Resolution order:

1. If membership inactive, deny all.
2. Start with static default capabilities for membership role.
3. If `custom_role_id` present and active, use custom role permissions according to final product decision:
   - Safer v1: custom role replaces non-owner static role permissions.
   - Owner role cannot be replaced by custom role.
4. Apply hard deny conditions:
   - inactive role
   - malformed permission
   - unknown capability
   - owner-only capability not allowed
5. Matter-specific checks still run after capability check.

### 21.6 API

Add:

- `GET /api/company/capabilities`
- `GET /api/company/roles`
- `POST /api/company/roles`
- `GET /api/company/roles/{role_id}`
- `PATCH /api/company/roles/{role_id}`
- `DELETE /api/company/roles/{role_id}`
- `POST /api/company/employees/{membership_id}/role`

### 21.7 Frontend

Add:

- `/app/admin/roles`
- Role list
- Create/edit role screen
- Permission matrix
- Employee role assignment flow

Permission matrix should use grouped checkboxes, not raw JSON.

### 21.8 Acceptance Criteria

- Existing fixed-role behavior remains unchanged for users without custom roles.
- Custom role can grant allowed capabilities.
- Custom role cannot grant owner-only capabilities through admin escalation.
- Unknown capability denies access.
- Server and frontend capability lists stay aligned through server-provided capabilities.
- Role update revokes or invalidates sessions according to existing session revocation pattern.

## 22. Epic M: Employee Lifecycle, Offboarding, and Audit

### 22.1 Problem

The feedback requires activation/deactivation, reset password, deletion restrictions, offboarding, reassignment, and employee audit. Current user update APIs can mark membership inactive and revoke sessions, but there is no full offboarding workflow.

### 22.2 Required Behavior

Admin or owner can:

- View employee lifecycle state.
- Preview offboarding impact.
- Reassign owned/assigned work.
- Deactivate employee.
- Revoke active sessions.
- Record audit trail.
- Optionally notify affected stakeholders.

Deletion should be restricted. Prefer deactivation over hard delete.

### 22.3 Offboarding Preview

Preview should include:

- Matters owned or assigned
- Restricted-access matter grants
- Team memberships
- Contracts owned
- Contract obligations assigned
- Matter tasks assigned
- Drafts owned
- Approvals pending
- Calendar reminders owned
- Portal grants or invites created
- Email templates owned if applicable

### 22.4 API

Add:

- `POST /api/company/employees/{membership_id}/offboarding/preview`
- `POST /api/company/employees/{membership_id}/offboarding/commit`

Commit request:

```json
{
  "reassign_to_membership_id": "uuid",
  "deactivate": true,
  "revoke_sessions": true,
  "notify": true,
  "notes": "Leaving team"
}
```

Rules:

- Cannot offboard the last active owner.
- Cannot reassign to inactive membership.
- Cannot reassign across tenants.
- Ethical wall restrictions must be preserved.
- Entire commit should be transactional where practical.

### 22.5 Audit Events

Add audit events for:

- employee created
- employee updated
- setup link resent
- password reset requested
- role changed
- custom role changed
- employee deactivated
- offboarding preview generated
- offboarding committed
- session revoked
- login success/failure if existing auth system supports it

### 22.6 Acceptance Criteria

- Inactive users cannot login.
- Existing sessions are invalidated after deactivation.
- Offboarding preview is accurate enough to be trusted.
- Commit reassigns supported objects and reports unsupported objects.
- Last owner cannot be deactivated.
- All actions are audited.

## 23. Data Migration Plan

Implement migrations in small, reversible slices.

### 23.1 Suggested Migration Order

1. Matter metadata:
   - claim amount fields
   - court order fields
   - attachment lifecycle metadata
2. Matter tags:
   - `MatterTag`
   - `MatterTagAssignment`
3. Forum catalog:
   - hierarchy fields or new catalog table
   - seed baseline forum nodes
4. Employee profiles and setup tokens:
   - `EmployeeProfile` or membership fields
   - `AccountSetupToken`
5. Bulk import:
   - `EmployeeBulkImportJob`
   - `EmployeeBulkImportRow`
6. Custom roles:
   - `CustomRole`
   - membership role assignment field
7. Contracts metadata:
   - contract legal references
   - term suggestions
   - contract attachment role fields
8. Calendar connections and notification rules:
   - `UserCalendarConnection`
   - `CalendarEventSync`
   - `NotificationRule`

### 23.2 Backfill Rules

- Existing matters get null claim amount.
- Existing attachments get null document type and display as unclassified.
- Existing court orders get `order_kind = daily_order` or null depending migration safety.
- Existing contract type strings are preserved.
- Existing users get employee profile records only if they are company memberships.
- Existing fixed roles remain valid.

### 23.3 Rollout Flags

Use existing feature flag patterns if available.

Suggested flags:

- `legalworkspace.timeline.enabled`
- `legalworkspace.document_lifecycle.enabled`
- `legalworkspace.forum_selector.enabled`
- `legalworkspace.employee_directory.enabled`
- `legalworkspace.bulk_employee_import.enabled`
- `legalworkspace.custom_roles.enabled`
- `legalworkspace.outlook_sync.enabled`
- `legalworkspace.contract_metadata.enabled`

Do not leave security controls behind disabled flags if routes are exposed. Routes must still fail closed.

## 24. API Summary

Matter:

- `GET /api/matters` with enhanced filters
- `GET /api/matters/{matter_id}/timeline`
- `PATCH /api/matters/{matter_id}`
- `GET /api/matters/{matter_id}/orders`
- `POST /api/matters/{matter_id}/orders`
- `PATCH /api/matters/{matter_id}/orders/{order_id}`
- `PATCH /api/matters/{matter_id}/attachments/{attachment_id}/metadata`
- `GET /api/matters/{matter_id}/audit-events`
- `POST /api/matters/{matter_id}/audit-events/export`

Tags:

- `GET /api/matter-tags`
- `POST /api/matter-tags`
- `PATCH /api/matter-tags/{tag_id}`
- `DELETE /api/matter-tags/{tag_id}`
- `POST /api/matters/{matter_id}/tags`
- `DELETE /api/matters/{matter_id}/tags/{tag_id}`
- `POST /api/matters/bulk-tags`
- `GET /api/matters/{matter_id}/tag-suggestions`

Forum catalog:

- `GET /api/courts/forum-catalog`

Calendar/notifications:

- `GET /api/calendar/connections`
- `POST /api/calendar/connections/outlook/start`
- `GET /api/calendar/connections/outlook/callback`
- `DELETE /api/calendar/connections/{connection_id}`
- `POST /api/calendar/sync/hearings/{hearing_id}`
- `GET /api/calendar/sync-status`
- `GET /api/notification-rules`
- `POST /api/notification-rules`
- `PATCH /api/notification-rules/{rule_id}`
- `DELETE /api/notification-rules/{rule_id}`

Employees:

- `GET /api/company/employees`
- `POST /api/company/employees`
- `GET /api/company/employees/{membership_id}`
- `PATCH /api/company/employees/{membership_id}`
- `POST /api/company/employees/{membership_id}/resend-setup`
- `POST /api/company/employees/{membership_id}/reset-password`
- `POST /api/company/employees/{membership_id}/offboarding/preview`
- `POST /api/company/employees/{membership_id}/offboarding/commit`
- `GET /api/company/employees/import-template.csv`
- `POST /api/company/employees/imports/preview`
- `GET /api/company/employees/imports/{job_id}`
- `POST /api/company/employees/imports/{job_id}/commit`
- `POST /api/company/employees/imports/{job_id}/cancel`

Roles:

- `GET /api/company/capabilities`
- `GET /api/company/roles`
- `POST /api/company/roles`
- `GET /api/company/roles/{role_id}`
- `PATCH /api/company/roles/{role_id}`
- `DELETE /api/company/roles/{role_id}`
- `POST /api/company/employees/{membership_id}/role`

Contracts:

- `PATCH /api/contracts/{contract_id}/metadata`
- `GET /api/contracts/{contract_id}/legal-references`
- `POST /api/contracts/{contract_id}/legal-references`
- `PATCH /api/contracts/{contract_id}/legal-references/{reference_id}`
- `POST /api/contracts/{contract_id}/term-suggestions`
- `POST /api/contracts/{contract_id}/term-suggestions/{suggestion_id}/accept`
- `POST /api/contracts/{contract_id}/term-suggestions/{suggestion_id}/reject`
- `PATCH /api/contracts/{contract_id}/attachments/{attachment_id}/metadata`

Auth:

- `POST /api/auth/account-setup/complete`
- `POST /api/auth/password-reset/start`
- `POST /api/auth/password-reset/complete`

## 25. Frontend Information Architecture

### 25.1 Matter List

Add:

- Claim amount column
- Tags column
- Stay/interim indicator
- Forum/court filter
- Status filter
- Date range filter
- Party search
- Claim amount range filter
- Bulk tag action

### 25.2 Matter Cockpit

Recommended v1 tabs:

- Overview
- Timeline
- Documents
- Drafts
- Hearings
- AI Recommendations
- Strategy Plan
- Statutes
- Communications
- Billing
- Audit

Future parity with canonical PRD should also add:

- Calendar and Deadlines
- Tasks
- Access

Do not attempt all tab restructuring in the first slice unless requested. Add `Timeline` and relabel recommendations/strategy first.

### 25.3 Matter Documents

Add:

- Document lifecycle upload metadata
- Grouped repository
- Metadata edit action
- Order/stay metadata for order documents

### 25.4 Hearings and Orders

Add:

- Completed/upcoming sections
- Orders list with sort toggle
- Stay/interim badges
- Manual order metadata edit

### 25.5 Calendar

Add:

- Outlook connection state
- Manual sync action
- Sync status
- Reminder controls
- Keep ICS export

### 25.6 Admin

Add:

- `/app/admin/employees`
- `/app/admin/roles`

Employee directory:

- Search
- Role filter
- Status filter
- Department filter
- Add employee
- Bulk upload
- Reset password
- Deactivate/offboard

Roles:

- Role list
- Permission matrix
- Create/edit custom role
- Assign role to employee

### 25.7 Contracts

Add:

- Controlled type select
- Term panel
- Legal references panel
- Ancillary documents grouping
- Reviewable AI suggestions

## 26. Security and Audit Requirements

### 26.1 Tenant Isolation

Every new table must include `company_id` unless it is a public catalog table. Public catalog tables must not include tenant-specific data.

New tenant-scoped tables:

- `MatterTag`
- `MatterTagAssignment`
- `EmployeeProfile`
- `EmployeeBulkImportJob`
- `EmployeeBulkImportRow`
- `CustomRole`
- `ContractLegalReference`
- `ContractTermSuggestion`
- `UserCalendarConnection`
- `CalendarEventSync`
- `NotificationRule`

### 26.2 Matter Access

All matter-related endpoints must enforce:

- Company membership
- Active membership
- Required capability
- Team restrictions
- Restricted access grants
- Ethical walls

Matter access checks must run even for owner/admin roles where ethical wall logic requires it.

### 26.3 Audit Events

Audit at minimum:

- Matter claim amount changes
- Matter tags created/updated/deleted
- Matter tag assignment and bulk assignment
- Court/forum changes
- Order created/updated/deleted
- Stay status changed
- Attachment lifecycle metadata changed
- Calendar connection created/revoked
- Calendar sync executed/failed
- Notification rule created/updated/deleted
- Employee created/updated
- Employee import preview and commit
- Role created/updated/deleted
- Role assignment changed
- Password reset/setup link generated
- Employee deactivated/offboarded
- Contract legal reference suggested/accepted/rejected
- Contract term suggestion accepted/rejected
- Contract attachment metadata changed

### 26.4 Password and Onboarding Safety

- Do not email raw passwords.
- Use setup links.
- Hash setup/reset tokens at rest.
- Expire tokens.
- Invalidate token on use.
- Rate-limit reset flows if the auth stack supports it.
- Audit token creation and use without logging token values.

### 26.5 Bulk Import Safety

- Reject unsupported MIME types.
- Limit file size and row count.
- Sanitize formula-like cells beginning with `=`, `+`, `-`, or `@` when exporting or previewing.
- Validate all rows before commit.
- Never commit rows into another tenant.
- Keep original import data only as long as product policy permits.

### 26.6 Calendar Token Safety

- Store OAuth tokens through the approved encrypted secret mechanism.
- Never send refresh tokens to browser clients.
- Audit connect, revoke, sync, and failures.
- Allow user/admin revocation.

## 27. Dependencies and Architectural Constraints

### 27.1 Temporal

Automated calendar sync, reminder delivery, and notification retries should be Temporal workflows or activities once Temporal is available. If the implementation slice comes before Temporal, build only non-durable/manual paths and clearly mark durable automation as blocked.

### 27.2 Grantex

This PRD does not require Grantex implementation, but RBAC and audit design must not make Grantex harder. Keep permission decisions explicit and auditable so future scoped delegation can plug in.

### 27.3 Existing Capabilities

Do not fork authorization into disconnected UI-only permissions. Extend server capability resolution and have UI consume resolved capabilities from the server.

### 27.4 Existing Court Catalog

Use the existing courts/judges model where practical. Do not import large external court datasets without source, lineage, and update plan.

### 27.5 AI Use

AI may suggest contract terms or legal classifications only when:

- Source evidence is captured.
- User can review before acceptance.
- Uncertainty is visible.
- No unsupported legal risk score is created.

## 28. Implementation Slices

This is the recommended development order. Each slice should be independently reviewable.

### Slice LW-S0: PRD Linkage and Baseline Tests

Scope:

- Link this addendum from canonical PRD or add a short canonical PRD section pointing here.
- Add route/test matrix placeholders if repo convention requires it.
- No product behavior change.

Definition of done:

- PRD linkage exists.
- No code behavior changes.

### Slice LW-S1: Claim Amount, Matter Filters, and Tags

Why first:

- High user value.
- Minimal dependency on Temporal or custom RBAC.
- Creates useful list-level scaffolding for later stay indicators.

Backend:

- Add matter claim fields.
- Add matter tag models and schemas.
- Extend `GET /api/matters` filters.
- Add tag CRUD and assignment endpoints.
- Add audit events.

Frontend:

- Add matter list filters.
- Add claim amount display.
- Add tags display and edit.
- Add bulk tag action.

Tests:

- FT-LW-007
- FT-LW-008
- FT-LW-009
- SEC-LW-001
- NFT-LW-001

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_matter_search_tags.py
```

### Slice LW-S2: Timeline, Hearings, Orders, and Stay Flags

Backend:

- Add order metadata fields.
- Add timeline service and endpoint.
- Add order list/update endpoints if missing.
- Add audit events.

Frontend:

- Add Timeline tab.
- Add completed/upcoming hearing sections.
- Add order sort toggle.
- Add stay/interim badges.

Tests:

- FT-LW-001 through FT-LW-005
- SEC-LW-002
- NFT-LW-003

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_matter_timeline.py
```

### Slice LW-S3: Document Lifecycle Metadata

Backend:

- Add attachment metadata fields.
- Update upload schemas.
- Add attachment metadata patch endpoint.
- Link order documents to orders.

Frontend:

- Update upload dialog.
- Add document type select.
- Group repository by lifecycle.
- Add metadata edit.

Tests:

- FT-LW-004
- FT-LW-005
- SEC-LW-002

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_document_lifecycle.py
```

### Slice LW-S4: Forum Hierarchy

Backend:

- Extend court catalog or add forum catalog.
- Seed baseline hierarchy.
- Add forum catalog endpoint.
- Update matter create/update schemas.

Frontend:

- Build `ForumSelector`.
- Replace simple create-matter forum controls.
- Preserve legacy free-text display.

Tests:

- FT-LW-006
- SEC-LW-001

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_forum_selector.py
```

### Slice LW-S5: Employee Directory and Manual Setup

Backend:

- Add employee profile fields/table.
- Add setup/reset token model.
- Add employee APIs.
- Add email template triggers if provider is configured.
- Audit all actions.

Frontend:

- Add `/app/admin/employees`.
- Add directory, filters, create dialog, edit drawer.
- Add setup/reset actions.

Tests:

- FT-LW-013
- FT-LW-015
- FT-LW-020
- SEC-LW-001
- SEC-LW-005

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_employee_admin.py
```

### Slice LW-S6: Bulk Employee Upload

Backend:

- Add import job/row models.
- Add template, preview, commit, cancel APIs.
- Validate CSV/XLSX.
- Sanitize preview/export.
- Audit preview/commit.

Frontend:

- Add bulk upload wizard.
- Add preview table with row errors.
- Add commit summary.

Tests:

- FT-LW-014
- SEC-LW-004
- NFT-LW-002

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_bulk_employee_upload.py
```

### Slice LW-S7: Custom Role Templates

Backend:

- Add custom role model.
- Add capability resolver service.
- Add role APIs.
- Update authorization dependencies to use resolver.
- Update session invalidation on role change.

Frontend:

- Add `/app/admin/roles`.
- Add role matrix.
- Update auth context to use server-resolved capabilities.

Tests:

- FT-LW-016
- FT-LW-017
- SEC-LW-003
- existing role guard tests

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_custom_roles.py apps/api/tests/test_role_guards.py
```

### Slice LW-S8: Offboarding and Employee Audit

Backend:

- Add offboarding preview/commit.
- Reassign supported objects.
- Revoke sessions.
- Add employee audit query if needed.

Frontend:

- Add offboarding flow.
- Add employee audit tab or drawer section.

Tests:

- FT-LW-018
- FT-LW-019
- FT-LW-020
- SEC-LW-002

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_offboarding.py apps/api/tests/test_session_revocation.py
```

### Slice LW-S9: Contract Metadata

Backend:

- Controlled contract type schemas.
- Legal reference model and APIs.
- Term suggestion model and APIs.
- Attachment role metadata.
- Audit events.

Frontend:

- Metadata panel.
- Legal references panel.
- Term suggestion review.
- Ancillary document grouping.

Tests:

- FT-LW-021 through FT-LW-024
- SEC-LW-007

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_contract_metadata.py apps/api/tests/test_contracts.py
```

### Slice LW-S10: Calendar Sync and Notifications

Status after implementation (2026-05-07): implemented as a bounded v1 with
manual Outlook sync and transactional in-app notifications. Durable automated
calendar/notification delivery remains blocked pending Temporal.

Backend:

- Add Outlook connection model/API.
- Add manual sync.
- Add notification rule model/API.
- Integrate with Temporal if available.
- If Temporal is unavailable, limit delivery to existing safe mechanisms and clearly document blocked durable automation.

Frontend:

- Add connection state.
- Add sync action.
- Add reminder and notification rule controls.

Tests:

- FT-LW-010
- FT-LW-011
- SEC-LW-006
- NFT-LW-005

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_calendar_sync.py apps/api/tests/test_hearing_reminders.py
```

### Slice LW-S11: Audit Polish and Recommendation/Strategy Distinction

Backend:

- Add matter audit filters/export.
- Add accepted recommendation link if needed for strategy.

Frontend:

- Add audit filters/export UI.
- Rename/clarify Recommendations and Strategy tabs.
- Remove duplicated cards or copy.

Tests:

- FT-LW-012
- FT-LW-025

Verification:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_matter_audit.py apps/api/tests/test_recommendations.py
```

## 29. Test Plan

### 29.1 Backend Tests

Add targeted backend tests:

- `apps/api/tests/test_legalworkspace_matter_timeline.py`
- `apps/api/tests/test_legalworkspace_document_lifecycle.py`
- `apps/api/tests/test_legalworkspace_matter_search_tags.py`
- `apps/api/tests/test_legalworkspace_forum_selector.py`
- `apps/api/tests/test_legalworkspace_employee_admin.py`
- `apps/api/tests/test_legalworkspace_bulk_employee_upload.py`
- `apps/api/tests/test_legalworkspace_custom_roles.py`
- `apps/api/tests/test_legalworkspace_offboarding.py`
- `apps/api/tests/test_legalworkspace_contract_metadata.py`
- `apps/api/tests/test_legalworkspace_calendar_sync.py`
- `apps/api/tests/test_legalworkspace_matter_audit.py`

Update existing tests where behavior changes:

- `apps/api/tests/test_role_guards.py`
- `apps/api/tests/test_session_revocation.py`
- `apps/api/tests/test_teams.py`
- `apps/api/tests/test_calendar.py`
- `apps/api/tests/test_hearing_reminders.py`
- `apps/api/tests/test_contracts.py`
- `apps/api/tests/test_contract_intelligence.py`
- `apps/api/tests/test_audit_events.py`
- `apps/api/tests/test_tenant_isolation.py`

### 29.2 Web Tests

Add or update:

- Matter list filters and tags
- Matter timeline page
- Document upload lifecycle metadata
- Hearings/orders stay badges
- Forum selector
- Employee directory
- Bulk employee import wizard
- Roles permission matrix
- Offboarding flow
- Contract metadata panels
- Calendar Outlook connection state
- Audit filters/export

### 29.3 E2E Tests

Add:

- `tests/e2e/legalworkspace-matter-flow.spec.ts`
- `tests/e2e/legalworkspace-rbac.spec.ts`
- `tests/e2e/legalworkspace-contracts.spec.ts`

Matter flow should cover:

1. Create matter with forum hierarchy and claim amount.
2. Upload complaint/petition.
3. Add hearing.
4. Upload interim stay order.
5. Confirm matter list indicator.
6. Confirm timeline chronology.
7. Filter matter by tag/status/forum/stay.

RBAC flow should cover:

1. Admin creates employee.
2. Setup link path succeeds in test harness.
3. Admin creates custom viewer-like role.
4. Employee can view but not edit matter.
5. Employee is offboarded.
6. Existing session no longer works.

Contract flow should cover:

1. Create contract with controlled type.
2. Upload primary contract and ancillary annexure.
3. Add legal reference.
4. Generate term suggestion.
5. Accept suggestion.
6. Confirm audit event.

### 29.4 Canonical Verification Commands

Backend:

```bash
scripts/verify-backend.sh
```

Targeted backend:

```bash
scripts/verify-backend.sh apps/api/tests/test_legalworkspace_matter_timeline.py
scripts/verify-backend.sh -k "legalworkspace or role_guards or tenant_isolation"
```

Frontend commands should follow current package scripts. If present, run:

```bash
npm run typecheck:web --workspace @caseops/web
npm run test:web --workspace @caseops/web
```

E2E command should follow current repo convention for Playwright. If present, run the targeted LegalWorkspace specs after starting the app through the repo's documented test harness.

## 30. Open Decisions

These decisions should be resolved before or during the first affected slice.

| Decision | Options | Recommendation |
| --- | --- | --- |
| Timeline persistence | Composed read model vs event table | Start composed. Add event table only if performance demands it. |
| Order tab | Separate Orders tab vs section inside Hearings | Keep section inside Hearings in v1 and add Timeline tab. Split later if needed. |
| Forum catalog source | Extend `Court` vs new catalog table | Extend `Court` if simple; use catalog table if district/consumer hierarchy muddies court model. |
| Employee profile storage | Extend `CompanyMembership` vs `EmployeeProfile` | Prefer `EmployeeProfile` to avoid overloading membership. |
| Custom role semantics | Replace default role permissions vs merge with default role | Prefer replace for non-owner roles to make role behavior predictable. |
| Raw password setup | Admin-set password vs setup link | Use setup link in production. Avoid raw passwords. |
| Outlook automation | Full auto-sync vs manual sync | Manual sync first unless Temporal is available. |
| Contract AI extraction | Auto-write vs reviewable suggestion | Reviewable suggestion only. |

## 31. Development Guardrails for Codex CLI

1. Keep each slice surgical.
2. Read the existing module before editing.
3. Reuse existing schemas, auth helpers, audit helpers, services, and test factories.
4. Do not refactor unrelated code.
5. Preserve backwards compatibility for existing data.
6. Use typed request/response schemas.
7. Add migrations and tests in the same slice.
8. Fail closed on permissions.
9. Never rely on frontend gating as the authorization boundary.
10. Do not invent a second audit system.
11. Do not expand ad hoc background scheduling for durable workflows.
12. Prefer deterministic tagging and reviewable AI suggestions.
13. For legal outputs, require citation/source lineage and uncertainty.
14. If a stronger verification command is blocked, record the exact command and exact failure.

## 32. Initial Codex CLI Prompt

Use a prompt like this for the first implementation slice:

```text
Read AGENTS.md, .agents/skills/caseops-prd-execution/SKILL.md, docs/PRD_CLAUDE_CODE_2026-04-23.md, and docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md.

Implement Slice LW-S1 only: claim amount, server-side matter filters, matter tags, and bulk tag assignment.

Keep the change surgical. Preserve existing matter list behavior. Add tenant-scoped models/migrations/schemas/routes, frontend matter list filters/tags/claim amount display, audit events, and targeted tests. Use scripts/verify-backend.sh for backend verification.

Do not implement later slices. If you discover schema or permission drift that blocks LW-S1, stop and report the exact blocker before broadening scope.
```

## 33. Release Readiness Criteria

The LegalWorkspace enhancement track is not release-ready until:

- All implemented slices have targeted backend tests.
- New frontend surfaces have typecheck and page/component tests.
- E2E flows cover matter lifecycle, RBAC, and contract metadata.
- Tenant isolation tests cover new tables.
- Route guards cover new APIs.
- Audit coverage includes new sensitive actions.
- Outlook sync is either proven with provider-backed test/manual evidence or explicitly shipped as disabled/manual-only.
- Durable reminders/automation are either Temporal-backed or documented as caveated.
- Accessibility checks run for new admin and matter surfaces.
- Canonical PRD and this addendum are aligned.

## 34. Final Scope Summary

The highest-value first wave is:

1. Matter filters, tags, and claim amount
2. Timeline, order sheet, and stay/interim indicators
3. Document lifecycle metadata
4. Hierarchical forum selector
5. Employee directory and secure onboarding
6. Bulk employee upload
7. Custom role templates
8. Offboarding and employee audit
9. Contract metadata enhancements
10. Outlook sync and notification rules, gated by Temporal readiness for durable automation

This order keeps early work useful, limits rework, and respects the existing CaseOps architecture.
