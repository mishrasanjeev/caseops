# Governed IP legal-deadline workflow

**Slice:** `IPLF-023B`  
**Implementation revision:** `e021bb1fb509448f3282be11da3cb2ae3fbb9b39`  
**Program status:** `PROGRAM INCOMPLETE`

## Purpose

This slice turns the neutral IPLF-023A evidence foundation into an
authenticated, tenant-scoped legal-deadline workflow. It does not create a
second operational calendar. `ip_deadlines` retains the authoritative legal
calculation and evidence chain; the existing `matter_deadlines` writer receives
an atomic, one-way operational projection only after explicit confirmation.

The workflow covers the IPLF-023B facets of `CAL-OPS-01..14`, `IP-DL-01..08`,
and `RULE-GOV-01..08`, plus the allocated normal and exception paths for UJ-08,
UJ-09, UJ-47, and UJ-56. Reciprocal later slices still own daily docket,
calendar-feed, form/fee, broad automation, and portfolio-level facets, so the
requirement families and overall program remain incomplete.

## Authoritative ownership

| Concern | Canonical owner | IPLF-023B behavior |
|---|---|---|
| Legal calculation and history | `ip_deadlines` and immutable rule/calendar versions | stores exact inputs, intermediate calendar operations, explanation, citation, engine/source versions, overrides, supersession, and completion evidence |
| Operational work | existing `matter_deadlines` service | creates or updates projections through the shared writer inside the legal transaction |
| Coverage and responsibility | `ip_responsibility_assignments` plus existing `ip_deadline_coverages` | requires acknowledged primary and backup/escalation coverage for critical dates |
| Reminder delivery | existing notification-delivery intent owner | creates durable `in_app` intents only; no external message is sent by this workflow |
| Matter access | existing Matter access and ethical-wall owner | every legal-deadline read/write resolves the docket and linked Matter fail-closed |
| Rule governance | immutable `ip_rule_versions` plus company selection policy | separates proposer, fixture reviewer, and legal activator, preserving tenant governance boundaries |

No generic task, import, provider, child update, or calendar copy can complete or
rewrite the legal deadline.

## State and command model

### Rule versions

1. An owner/admin with `ip:rules_propose` submits a candidate with legal scope,
   exact source identity/hash/effective range, engine compatibility, definition,
   and fixtures.
2. Server-side activation re-evaluates every fixture. The proposer, fixture
   reviewer, and legal activator must be distinct active company memberships.
3. Activation retires a prior active version, records immutable actor snapshots,
   and optionally selects the version in the company policy. Auto-confirm stays
   disabled unless separately and explicitly selected.
4. Retirement or emergency disable requires a fresh impact token. Existing
   confirmed evidence is preserved; disablement blocks new calculations and
   appears in the exception workspace.
5. A tenant can govern only versions proposed by its memberships. A company sees
   active rules in its workspace only when its own policy selected them.

### Working calendars

1. A candidate records jurisdiction/office scope, timezone, weekend days,
   holidays, exceptional working days, source priority, source reference/hash,
   and effective range.
2. The proposer cannot self-approve. Replacing an active calendar requires an
   explicit conflict review.
3. Calculation snapshots the exact selected calendar version, so later calendar
   changes cannot silently rewrite historical results.

### Legal deadlines

| State | Meaning | Allowed next action |
|---|---|---|
| `provisional` | source date is unknown, uncertain, or conflicting; no precision is manufactured | provide sourced correction during confirmation, or propose a new calculation |
| `candidate` | deterministic calculation exists but has no legal/operational effect yet | explicit confirmation, recalculation, or retained review |
| `confirmed` / `overdue` | authoritative legal date with atomic operational projection, coverage, and reminders | impact-aware override, reviewable recalculation candidate, or legal-evidence completion |
| `superseded` | immutable predecessor retained after accepted correction or override | read-only evidence |
| `completed` | legal completion evidence/attestation accepted through the dedicated command | read-only evidence |
| `cancelled` | terminal retained history | read-only evidence |

Every mutation locks the parent evidence row and checks `expected_version`.
Impact-changing commands also require a fresh SHA-256 impact token derived from
the exact dependent operational deadline, reminder-intent, and responsibility
identifiers.

## Calculation and confirmation

- Supported foundation semantics include calendar days, business days,
  month/year anniversaries, before/after direction, base-date inclusion,
  extensions, weekend/holiday/exceptional-working-day rules, and
  next-working-day adjustment.
- The API returns the plain-language explanation and governing source citation
  beside the result.
- Unknown/conflicting triggers produce a visible provisional record with no
  fabricated due date.
- Confirmation of a critical deadline requires exactly one acknowledged primary
  owner and acknowledged backup or escalation coverage. Each responsible member
  must be active, in the same company, and able to access the Matter.
- Confirmation atomically creates the shared operational legal deadline,
  optional internal target, responsibility evidence, coverage row, and durable
  in-app reminder intents. Any exception rolls back the entire transaction.
- Reminder offsets are deterministic and idempotent. This slice does not send
  email, SMS, WhatsApp, registry messages, filings, payments, or other external
  effects.

## Recalculation, override, and completion

- A changed trigger creates a reviewable successor candidate; the confirmed
  predecessor remains active until the successor is explicitly confirmed with
  the predecessor's fresh impact token.
- An override requires a new date, reason, evidence reference, exact expected
  version, fresh impact token, and complete replacement coverage. It cancels
  only dependencies whose source lineage points at the superseded legal
  deadline; unrelated Matter work remains untouched.
- Generic `MatterDeadline.status=done` cannot complete the legal evidence row.
  Only `/api/ip/deadlines/{id}/complete` can do so, with evidence and an
  authorized attestation. That command completes the projection and suppresses
  pending reminders in the same transaction.

## Exception and incident behavior

The docket workspace always returns visible exception rows for applicable
`overdue`, `unacknowledged`, `unowned`, `conflicting`, `uncertain`,
`source_stale`, and `rule_disabled` conditions. The UI does not provide bulk
dismissal or filtering that hides them. Existing IPLF deadline-incident commands
remain the canonical suspected-missed/incorrect deadline workflow and retain
ordinary corrective docket-event capability and audit evidence.

## API surface

| Method/path | Capability | Purpose |
|---|---|---|
| `GET /api/ip/dockets/{id}/deadline-workspace` | `ip:read` | scoped rules, calendars, legal deadlines, and exception queue |
| `POST /api/ip/deadline-rules` | `ip:rules_propose` | immutable candidate proposal |
| `GET /api/ip/deadline-rules/{id}/impact` | `ip:rules_activate` | fresh affected-policy/deadline counts and token |
| `POST /api/ip/deadline-rules/{id}/activate` | `ip:rules_activate` | fixture evaluation plus independent activation |
| `POST /api/ip/deadline-rules/{id}/transition` | `ip:rules_activate` | impact-aware retirement or emergency disable |
| `POST /api/ip/working-calendars` | `ip:rules_propose` | versioned calendar proposal |
| `POST /api/ip/working-calendars/{id}/activate` | `ip:rules_activate` | independent activation/conflict review |
| `POST /api/ip/dockets/{id}/deadlines` | `ip:approve` | deterministic or provisional proposal |
| `GET /api/ip/deadlines/{id}/impact` | `ip:approve` | exact dependent-record preview/token |
| `POST /api/ip/deadlines/{id}/confirm` | `ip:approve` | atomic confirmation/projection/coverage/reminders |
| `POST /api/ip/deadlines/{id}/override` | `ip:approve` | sourced immutable override |
| `POST /api/ip/deadlines/{id}/recalculate` | `ip:approve` | reviewable successor calculation |
| `POST /api/ip/deadlines/{id}/complete` | `ip:approve` | dedicated legal-evidence completion |

The generated OpenAPI TypeScript contract and handwritten client adapters are
committed with the API surface.

## User interface and responsive contract

The existing `/app/ip` docket workspace now contains two additive cards:

- **Legal deadline control** shows the explicit-confirmation warning, exception
  queue, active rule/calendar selectors, proposal form, coverage fields,
  explanation/citation, and state-appropriate actions.
- **Rule and calendar governance** exposes sourced candidate forms, fixture
  inputs, independent activation, and impact-aware emergency disablement.

Every grouped control is `min-w-0`, full-width on narrow screens, and wraps to
content width above the small breakpoint. Unit and Playwright acceptance assert
that all controls are visible and remain inside a 360-pixel viewport; DOM
presence alone is not treated as responsive proof.

## Verification and safe rollout

Primary executable evidence:

- `apps/api/tests/test_ip_deadline_workflow.py`
- `apps/api/tests/test_ip_deadline_foundation.py`
- `apps/api/tests/test_20260807_ip_deadline_foundation_migration.py`
- `apps/api/tests/test_ip_prosecution_workflow.py`
- `apps/web/app/app/ip/page.test.tsx`
- `tests/e2e/iplf-023b-deadline-workflow-2026-08-09.spec.ts`
- `tests/e2e/ram-2026-08-09-prod.spec.ts`

The local dated Playwright journey uses a synthetic, non-billable tenant and
proves independent governance, holiday calculation, visible exception,
confirmation, operational-task/non-legal completion separation, evidence-based
legal completion, and responsive action bounds. The production spec is
read-only against the existing unentitled tester tenant and proves that no
deadline/rule/calendar data request or mutation occurs behind the readiness
gate.

Production verification completed on canonical merge
`d8ac94da22f014dfa205079c9b1b049e98bd5347`: API revision
`caseops-api-00258-zv8`, web revision `caseops-web-00238-n7s`, migration
execution `caseops-migrate-job-5wj7s`, and exact-release workflow
`31298468728` all passed. The detailed immutable image, scheduler, CI, and
browser evidence is retained in
`evidence/m2/IPLF-023B/release-2026-08-09.md`.

The arbitrary requirement to wait seven natural days for scheduler health is
not a release blocker. Exact scheduler identity, immutable image, execution,
probe, and policy evidence remain required at deployment.

## Remaining program work

IPLF-024A and later M2-M10 slices remain unimplemented, and named human legal
fixture approval/UAT gates remain pending. This document is delivery evidence
for IPLF-023B only; it must never be read as full IP PRD completion.
