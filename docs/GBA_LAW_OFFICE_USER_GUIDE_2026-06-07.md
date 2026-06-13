# GBA Law Office User Guide

Updated: 2026-06-13

This guide documents the GBA Law Office workflows implemented in CaseOps:
matter status terminology, tracked case refresh, court-order compliance
review, secure order uploads, India-ready matter billing, next-hearing
provenance, and date-wise cause-list PDFs.

This is product documentation, not tax or legal advice. Configuration should be
reviewed by the tenant's responsible lawyers and finance/accounting team.

## 2026-06-13 Status Labels

GBA Law Office workflows use the public CaseOps labels:

- `live`: Dispose/disposed matter status, manual order upload states,
  review-first compliance extraction, next-hearing provenance/manual lock,
  matter billing profiles, GST/TDS invoice fields, cause-list preview/PDF, and
  download audit.
- `review-first`: compliance extraction, draft/task activation, hearing/date
  suggestions, and connector-derived intelligence require lawyer confirmation
  before becoming active legal work.
- `provider-gated`: tracked case refresh, court adapters, Google Workspace,
  Microsoft 365, inbound email, and external notifications require lawful
  provider/source access, admin consent, webhook signing, or UAT evidence.
- `founder-only`: provider costs, margin/profitability, production signoff, and
  historical secret rotation evidence.
- `disabled until UAT`: Pine Labs production payments.
- `planned`: OIDC/SAML SSO, SCIM, private enterprise deployment, and autonomous
  scoped-agent execution.

## 1. Matter Status: Dispose / Disposed

- The user-facing action for a completed matter is **Dispose**.
- The canonical backend value is `disposed`.
- API responses emit `disposed`.
- Legacy clients may submit `closed` during the compatibility window; the API
  normalizes it to `disposed`.
- UI surfaces should not use Close/Closed for matter lifecycle status except in
  migration, compatibility tests, or explanatory comments.
- Disposed matters can be excluded from cause-list generation and operational
  reports by filter.

## 2. Tracked Case Refresh

Case tracking is intentionally opt-in by default.

- A matter with CNR or case number is eligible.
- Eligibility alone does not enroll the matter in scheduled refresh.
- A user must explicitly track/bookmark the matter-linked case.
- Tenant admins may later enable auto-tracking for eligible matters after
  reviewing source coverage and operational risk.

### Daily Window

Production defaults:

```text
CASEOPS_CASE_TRACKING_DAILY_WINDOW_START=16:00
CASEOPS_CASE_TRACKING_DAILY_WINDOW_END=18:00
CASEOPS_CASE_TRACKING_DAILY_TIMEZONE=Asia/Kolkata
```

Runtime rules:

- Scheduled production jobs should start inside the 4 PM-6 PM IST window,
  preferably around 4:30 PM IST.
- No new provider calls should start after 6 PM IST unless an explicit
  force/local override is used by an operator.
- Unfinished backlog persists and resumes on the next run.
- Batching is fair across tenants so one tenant cannot consume the full window.
- Disabled or misconfigured providers make no external calls and record safe
  skipped/blocked state.

### Operations Reporting

Admin/provider operations should show:

- attempted
- refreshed
- changed
- skipped
- blocked
- provider calls
- errors
- run window
- started/ended timestamps
- partial/backlog state
- blocked/skipped reason

Tenant admins receive deterministic in-app notification intents for failed
scheduled/provider jobs. External email/SMS/WhatsApp delivery is not sent unless
an approved provider is explicitly configured.

## 3. Secure Court-Order Intake

Court orders can enter CaseOps through:

- lawful configured adapters
- manual court-order creation
- manual file upload

Hard limits:

- CaseOps does not bypass captcha, login, or session-gated court sources.
- CaseOps does not make unapproved live provider calls.
- Manual uploads are limited to PDFs, DOC/DOCX, and images within configured
  file-size limits.
- Extraction begins only after the file-safety gate passes.
- Text/OCR states are visible: pending, failed, retryable, or complete.
- User-facing errors are redacted.

## 4. Court-Order Compliance Review

Compliance extraction is review-first by default.

Pipeline:

1. Order or upload is created.
2. Text is extracted or marked pending/failed.
3. Deterministic proceeding extraction runs first.
4. AI extraction runs only if tenant AI policy allows it.
5. AI output must pass JSON schema validation.
6. Dedupe runs before item creation.
7. Review-required compliance items are created.
8. Generated tasks/deadlines remain draft or review-linked unless tenant/admin
   settings enable auto-activation.
9. Relevant users receive durable in-app notification intents.
10. Lawyers can edit, confirm, reject, waive, complete, or retry.

Required compliance fields:

- description
- responsible party
- due_on
- timeline_text
- filing_requirement
- court_direction
- next_action
- source order or source attachment
- source snippet, page, and paragraph
- confidence label
- status
- review status
- generated task id and generated deadline id where applicable
- dedupe key

Rejected items must not appear as active compliance. Every confirm, reject,
waive, complete, retry, and AI/model-run event is audited without exposing raw
prompts, raw LLM responses, provider tokens, raw provider payloads, internal
costs, or unauthorized tenant-private data.

## 5. Deadline Calculation Rules

Deadline calculation is legally cautious by design.

- Calendar-day calculation is the default convention unless a configured court
  calendar supports another convention.
- Court holidays are not assumed unless a court calendar exists.
- Every computed date shows source snippet and confidence.
- Ambiguous phrases such as "from today", "within two weeks", "next date", or
  missing order date remain review-required.
- CaseOps never invents due dates.

## 6. Next-Hearing Provenance

`Matter.next_hearing_on` is managed with provenance/history.

History captures:

- source: manual, case_tracking, court_sync, proceeding_intelligence,
  cause_list, unknown
- source reference
- actor
- old date and new date
- reason
- timestamp
- manual lock state

Automatic update rules:

- Manual lock prevents overwrite unless a user accepts a suggestion.
- A high-confidence future provider date can update when there is no conflict.
- A conflict creates a review suggestion, not a silent overwrite.
- Past dates do not replace future dates unless final/disposed status is
  explicit.

UI surfaces:

- matter header source label
- hearings page manual add/edit
- suggestions accept/reject
- history drawer
- case tracking page matter-link/update path

## 7. Date-Wise Cause Lists

Route: `/app/cause-list`

API:

- preview endpoint
- PDF download endpoint
- optional CSV export where configured

Inputs:

- date or date range
- court
- lawyer/assignee
- practice area
- matter status
- include/exclude disposed matters
- source: hearings, cause-list entries, or both
- sort

Required output rows:

- serial number
- file number
- court name
- case number
- case title
- judge name
- court number
- item number
- lawyers appearing
- hearing date
- missing-field warnings

Missing values must show "Not available" or a professional preview warning.
Manual or derived overrides can be applied before PDF generation where
appropriate.

PDF requirements:

- A4 portrait
- black-and-white printable court-style table
- firm header/logo where configured
- date and generated timestamp
- applied filters
- repeated table header
- pagination
- page number footer
- no internal IDs unless intentionally used as file number

Every download is audited with filters, row count, actor, timestamp, checksum,
and file name.

## 8. Matter Billing and Invoice PDFs

Matter/client billing is separate from CaseOps SaaS subscription billing.

Admin route: `/app/admin/matter-billing`

Billing profile fields:

- default currency, INR unless tenant config says otherwise
- firm legal name
- firm address
- firm GSTIN
- firm PAN
- invoice prefix and sequence
- default payment terms/due days
- default SAC/HSN or service classification
- GST applicability and tax split configuration
- invoice footer/note/template
- firm logo/header where existing branding storage supports it

Rate and arrangement support:

- hourly rates by user
- hourly rates by role
- hourly rates by practice area
- default hourly rate
- fixed-fee matter arrangements
- milestone billing templates
- retainers/advance adjustments where supported by existing model
- expense/reimbursement categories
- manual line items

Invoice data:

- client billing name/address/GSTIN where available
- place of supply
- invoice number
- invoice date
- due date
- taxable value
- CGST/SGST/IGST split
- tax totals
- grand total
- amount paid
- outstanding amount
- TDS deduction/payment adjustment fields where recorded

Operational rules:

- Tax calculations happen server-side from stored invoice data.
- Downloadable PDFs render from server-side invoice data.
- Time entries already attached to an invoice cannot be double billed.
- Billing profile changes, rate changes, invoice creation, JSON/PDF export, and
  invoice downloads are audited.
- No UI copy should present tax or legal advice.
- External payment links are used only when an approved provider is explicitly
  configured.

## 9. Notifications

Recipients are deterministic:

- matter owner or lead lawyer
- assigned lawyer/team members/watchers where present
- tenant admins for failed scheduled/provider/extraction jobs

Repeated notifications for the same source update are deduped. Durable in-app
notification intents are the default safe delivery mechanism.

## 10. Security and Tenant Boundaries

- Every route/query/write must preserve strict tenant isolation.
- Every material user/admin/system action must be auditable.
- Provider tokens, raw provider payloads, raw prompts, raw LLM responses,
  internal costs, and tenant-private data must not be exposed to unauthorized
  users.
- Customer matter data is not used for cross-tenant training by default.
- Matter-level ethical walls override broad role access.

## 11. Public Documentation Surfaces

The following public surfaces should describe these workflows consistently:

- `/guide` in the web app
- root `README.md`
- `/llms.txt`
- `/llms-full.txt`
- landing page feature, workflow, trust, and FAQ sections
