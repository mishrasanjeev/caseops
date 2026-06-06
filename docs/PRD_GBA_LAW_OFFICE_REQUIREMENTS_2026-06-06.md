# PRD: GBA Law Office Requirements And Functional Flow

Status: Implementation-ready PRD  
Source document: `C:\Users\mishr\Downloads\GBA Law Office - Requirement Analysis & Functional Flow Document (1).docx`  
Source filename note: the original Word filename uses a special dash after
`GBA Law Office`; this PRD uses an ASCII-normalized path label for portability.  
Prepared: 2026-06-06  
Audience: Codex CLI implementation agent, product reviewer, engineering reviewer

## 1. Purpose

This PRD converts the GBA Law Office requirement analysis document into a complete
implementation plan for CaseOps.

The source document asks for six product changes:

1. Replace the matter status terminology "Close" with "Dispose".
2. Refresh case tracking automatically every day between 4:00 PM and 6:00 PM.
3. Extract compliance obligations from court orders using AI, for both
   auto-fetched orders and manually uploaded orders.
4. Manage billing and invoices through admin-defined billing configurations,
   with downloadable invoices.
5. Support next-hearing-date management through both automatic court updates and
   manual user entry.
6. Generate date-wise cause lists and allow PDF download in a court-style layout.

The implementation must preserve existing CaseOps safety rules:

- Tenant isolation must remain strict.
- Provider/court calls must be gated by approved configuration.
- No captcha/session-gated scraping is allowed.
- AI output must be source-backed, reviewable, auditable, and not treated as
  final legal advice.
- External email/SMS/WhatsApp delivery remains provider-gated and fail-closed.
- Existing billing, matter, court-sync, and notification foundations must be
  reused where practical.

## 2. Source Document Extraction Notes

The DOCX was inspected through its OOXML structure.

Findings:

- The document contains paragraphs only; no tables were present.
- No tracked changes were present.
- No reviewer comments were present.
- No embedded media was present.
- The title contained a dash character that may render differently by system
  encoding, but content extraction was otherwise complete.

The extracted source sections were:

- Matter Status Update
- Automated Case Tracking Refresh
- AI-Based Compliance Extraction from Court Orders
- Billing & Invoice Management
- Next Hearing Date Management
- Date-wise Cause List Generation & PDF Download
- Summary of Requirements

## 3. Current Repo Alignment

This section records the current CaseOps foundations that the implementation
should reuse rather than rebuild.

### 3.1 Matter Status

Current backend:

- `MatterStatus` is defined in `apps/api/src/caseops_api/db/models.py`.
- Current values are `intake`, `active`, `on_hold`, and `closed`.
- `MatterCreateRequest` and `MatterUpdateRequest` expose those values through
  `apps/api/src/caseops_api/schemas/matters.py`.

Current frontend:

- `apps/web/components/app/NewMatterDialog.tsx` shows `Closed`.
- `apps/web/app/app/matters/page.tsx` filters by `Closed`.
- `apps/web/components/ui/StatusBadge.tsx` renders the `closed` badge.
- Generated API types currently include `"closed"`.

Gap:

- GBA wants the legal label/value to be "Dispose", not "Close" or "Closed".

### 3.2 Case Tracking

Current backend:

- Case tracking route is mounted at `/api/case-tracking`.
- Provider-gated tracking exists through:
  - `apps/api/src/caseops_api/services/case_tracking.py`
  - `apps/api/src/caseops_api/services/case_tracking_providers.py`
  - `apps/api/src/caseops_api/scripts/poll_tracked_cases.py`
- Console script exists:
  - `caseops-poll-tracked-cases`
- Cloud Run job manifest exists:
  - `infra/cloudrun/case-tracking-poll-job.yaml`
- Provider settings exist:
  - `case_tracking_enabled`
  - `case_tracking_provider`
  - provider base URL/token settings
  - poll limit and poll interval settings

Current behavior:

- Bookmarked/tracked cases can be refreshed/polled.
- Polling detects updates and creates durable in-app notification intents.
- Provider-disabled state is safe.

Gap:

- The GBA requirement specifically requires an automatic daily refresh window
  between 4:00 PM and 6:00 PM.
- The deployment/scheduler configuration must prove this window, not merely that
  a script exists.

### 3.3 Court Orders, Compliance, And Proceeding Intelligence

Current backend:

- `MatterCourtOrder` stores court orders.
- `MatterCauseListEntry` stores matter-level cause-list entries.
- `MatterCourtSyncRun` and `MatterCourtSyncJob` store import/sync activity.
- `MatterTask` and `MatterDeadline` store generated work items.
- `services/proceeding_intelligence.py` already performs deterministic
  extraction for:
  - next hearing dates
  - relative deadlines
  - filing defects
  - reply/affidavit deadlines
  - compliance directions
  - action-required items
  - order-kind and stay/interim signals
- The deterministic extraction can create/update tasks and deadlines.
- Manual court order create exists through the matters route.
- Attachments and OCR/document processing already exist.

Current frontend:

- Matter hearings page shows court orders, cause-list entries, proceeding
  intelligence, pending compliance items, and order badges.
- Matter tasks page shows generated tasks and deadlines.
- Add court order dialog exists.

Gap:

- GBA specifically asks for AI-based compliance extraction from court orders,
  not only deterministic proceeding extraction.
- It must run automatically regardless of order source:
  - auto-fetched through case tracking/court sync
  - manually uploaded/attached by a user
- Extracted obligations must be reviewable/editable/confirmable before final
  reliance, while still creating useful draft tasks/deadlines.

### 3.4 Billing And Invoices

Current matter billing:

- Matter time entries and matter invoices exist:
  - `MatterTimeEntry`
  - `MatterInvoice`
  - `MatterInvoiceLineItem`
  - `MatterInvoicePaymentAttempt`
- Matter billing UI exists at `/app/matters/{id}/billing`.
- Users can add time entries and create invoices.
- Pine Labs payment links exist for matter invoices when configured.

Current SaaS billing:

- SaaS subscription billing is separate from law-firm matter billing.
- SaaS invoices/statement downloads exist under `/api/billing`.

Gap:

- GBA asks for admin-defined billing configurations/rates driving invoice
  generation.
- Matter invoice PDF download is not a complete first-class requirement surface
  in the existing matter billing flow.
- This PRD must keep law-firm matter billing separate from CaseOps SaaS
  subscription billing.

### 3.5 Next Hearing Date

Current backend:

- `Matter.next_hearing_on` exists.
- `MatterHearing` exists.
- Manual hearing create/update exists.
- Proceeding intelligence can update `matter.next_hearing_on` from order text
  when high-confidence next-hearing signals are found.
- Court sync can import cause-list entries and update next listing information.
- Case tracking can detect hearing updates at tracked-case level.

Gap:

- GBA wants a clearly designed next-hearing-date management flow with:
  - automatic updates from court/case tracking
  - manual updates by authorized users
  - audit history
  - clear precedence and provenance

### 3.6 Date-Wise Cause List PDF

Current backend:

- Matter-level cause-list entries exist.
- Hearing records exist.
- PDF generation patterns exist in:
  - `services/draft_pdf_export.py`
  - `services/matter_summary_export.py`
  - `services/saas_billing.py`

Current frontend:

- Matter hearings page lists a matter's cause-list entries.
- Calendar page exposes hearing/date information.

Gap:

- There is no dedicated date-wise consolidated cause-list module across all
  scheduled matters.
- There is no court-style cause-list PDF export matching the GBA requirement.

## 4. Product Goals

1. Make CaseOps terminology match legal office workflow language used by GBA.
2. Ensure users see court updates without manual daily refresh.
3. Reduce manual reading of court orders by extracting compliance obligations
   into structured, actionable, reviewable work.
4. Make law-firm matter billing configurable by admin-defined rates/rules.
5. Ensure next hearing dates are reliable, auditable, and manually correctable.
6. Let GBA generate date-wise cause-list PDFs for internal advocates and client
   sharing.

## 5. Non-Goals

- Do not bypass captcha/session-gated court sources.
- Do not enable any unapproved external provider calls.
- Do not send external email/SMS/WhatsApp notifications unless that provider is
  configured and approved.
- Do not mix CaseOps SaaS subscription invoices with law-firm client invoices.
- Do not generate legal advice or represent AI compliance extraction as final
  lawyer-reviewed work.
- Do not remove historical audit records that used the old `closed` status.
- Do not make outcome-prediction or judge-shopping recommendations.

## 6. Success Metrics

- Matter status UI no longer displays "Close" or "Closed" for matter lifecycle
  completion.
- Existing `closed` matters are migrated or compatibly displayed as `Dispose`.
- Daily case-tracking refresh runs within the 4:00 PM to 6:00 PM Asia/Kolkata
  window.
- At least 95 percent of successful auto-fetched order imports enqueue or run
  compliance extraction.
- At least 95 percent of manual court-order uploads enqueue or run compliance
  extraction after text/OCR is available.
- Duplicate compliance tasks are not created on repeated extraction of the same
  order.
- Invoice PDFs download from matter billing.
- Admin-defined billing rates are used when generating billing entries.
- Manual next-hearing updates are preserved with audit history.
- Cause-list PDF generation works for a selected date and for a date range.

## 7. Epic A: Matter Status Terminology - Dispose

### A1. User Story

As a GBA user, I want completed matters to be marked as "Dispose" instead of
"Close", so the matter status terminology matches legal-office usage.

### A2. Product Decision

Use `disposed` as the canonical backend value going forward, with display label
`Dispose`.

Rationale:

- The source document asks to replace the status value, not just the display
  label.
- Existing code uses `closed`, not `close`; this PRD treats `closed` as legacy.
- The display label should remain exactly `Dispose` to match the source
  document.

Backward compatibility:

- Existing rows with `status = 'closed'` must be migrated to `disposed`.
- API request parsing may accept `closed` as a legacy alias for one release,
  converting it to `disposed`.
- API responses should emit `disposed` after migration.
- UI must not present `closed` as an option.

### A3. Backend Requirements

Update:

- `MatterStatus` enum:
  - remove or deprecate `CLOSED = "closed"`
  - add `DISPOSED = "disposed"`
- Matter schema literals:
  - include `disposed`
  - optionally accept legacy `closed` on input and normalize to `disposed`
- Filters:
  - matter list status filter supports `disposed`
  - legacy query `status=closed` normalizes to `disposed` for compatibility
- Migration:
  - update existing `matters.status = 'closed'` to `disposed`
  - ensure downgrade maps `disposed` back to `closed` if needed
- Audit:
  - status transitions must record old and new values
  - migration should not create per-row user audit events unless an existing
    migration-audit pattern exists

### A4. Frontend Requirements

Update:

- New Matter dialog status options:
  - Intake
  - Active
  - On hold
  - Dispose
- Matter list status filter:
  - show `Dispose`
  - no `Closed`
- Status badge:
  - support `disposed`
  - display `Dispose`
- Matter header, portfolio, dashboard, client matter lists, generated API
  schemas/types:
  - use `disposed`
  - do not crash on legacy `closed` if stale local data appears

### A5. Acceptance Criteria

- Creating a matter can select `Dispose`.
- Editing/filtering by `Dispose` works.
- Existing matters previously marked `closed` appear as `Dispose`.
- No visible user-facing matter status option says `Close` or `Closed`.
- Tests cover migration, API input compatibility, UI display, and filtering.

## 8. Epic B: Automated Daily Case Tracking Refresh

### B1. User Story

As a GBA user, I want tracked cases refreshed automatically every day between
4:00 PM and 6:00 PM, so latest court updates are available without manual
refresh.

### B2. Scheduling Requirements

Time zone:

- Asia/Kolkata.

Refresh window:

- Start no earlier than 4:00 PM.
- End no later than 6:00 PM for scheduled job start/active polling window.

Recommended implementation:

- Configure Cloud Scheduler to invoke the case-tracking poll job at 4:30 PM
  Asia/Kolkata daily.
- Add settings to make the window explicit:
  - `CASEOPS_CASE_TRACKING_DAILY_WINDOW_START=16:00`
  - `CASEOPS_CASE_TRACKING_DAILY_WINDOW_END=18:00`
  - `CASEOPS_CASE_TRACKING_DAILY_TIMEZONE=Asia/Kolkata`
- The script should log the configured window and current local time.
- If run outside the window by scheduler/manual mistake, behavior should be
  configurable:
  - default production behavior: refuse scheduled run unless `--force`
  - local/test behavior: allow with test override

Runtime rules:

- Cloud Scheduler/Cloud Run should start the job inside the configured window,
  preferably at 4:30 PM Asia/Kolkata.
- Scheduled production runs must not start any new provider call after
  6:00 PM Asia/Kolkata unless `--force` or an explicit local/test override is
  supplied.
- Unfinished work must remain durable and resume on the next run; the job must
  record whether backlog remains.
- Batching must be fair across tenants so one tenant cannot consume the entire
  window.
- Provider operations/admin reporting must show tracked count, skipped count,
  blocked reason, partial/backlog state, and last run.

### B3. Functional Flow

1. Cloud Scheduler triggers the Cloud Run job between 4:00 PM and 6:00 PM.
2. `caseops-poll-tracked-cases` loads eligible tracked/bookmarked cases.
   Safest default: only explicitly tracked/bookmarked cases refresh
   automatically. Tenant-admin auto-enrollment of eligible matters can be added
   later as a separate opt-in setting.
3. Provider configuration is checked.
4. If provider is disabled/misconfigured:
   - no external provider call is made
   - run is recorded as skipped/blocked
   - admin/provider-operations state remains visible
5. If provider is configured:
   - cases are refreshed in batches
   - provider bulk refresh is used where available
   - new hearing dates, orders, judgments, and status changes are detected
6. Updates are persisted.
7. Durable in-app notification intents are created for relevant users.
8. Poll-run metrics and audit events are stored.

### B4. Provider Safety

- Do not scrape captcha/session-gated eCourts pages.
- Do not call provider unless `case_tracking_enabled=true` and provider
  configuration is complete.
- Do not log full provider payloads, party-sensitive payloads, provider tokens,
  or raw responses.
- Continue after per-case provider failure.
- Back off or stop if provider failure rate exceeds a configured threshold.

### B5. Admin/Operations Requirements

Expose in admin/provider operations or a case tracking operations view:

- last scheduled run time
- last successful run time
- last skipped/blocked reason
- attempted cases
- refreshed cases
- changed cases
- skipped cases
- blocked cases and redacted blocked reason
- provider calls
- provider-billed units if known
- estimated refresh cost if configured
- error count
- run window start/end/time zone
- backlog/partial state

### B6. Acceptance Criteria

- Scheduler manifest reflects a 4:00 PM to 6:00 PM IST run window.
- Manual script output reports whether the run is inside the configured window.
- Provider-disabled run does not call provider and records safe blocked/skipped
  status.
- Provider-fixture run detects hearing/order/status changes.
- Duplicate notifications are not created for the same update.
- Tests cover scheduler config parsing, window gating, provider-disabled state,
  update detection, idempotency, and audit.

## 9. Epic C: AI-Based Compliance Extraction From Court Orders

### C1. User Story

As a lawyer, I want CaseOps to automatically identify compliance obligations
from court orders, whether the order was fetched automatically or uploaded
manually, so I do not need to read lengthy orders manually to find deadlines and
actions.

### C2. Scope

Compliance extraction must work for:

- Auto-fetched court orders from case tracking/court sync.
- Manually created court orders.
- Manually uploaded court order documents attached to a matter.
- PDFs, DOC/DOCX files, and images where text/OCR extraction succeeds.

### C3. Product Behavior

The system should extract:

- compliance description
- responsible person or party
- due date
- timeline text, such as "within 7 days", "15 days", "30 days"
- filing requirements
- court directions
- next action required
- source order and source snippet
- confidence
- review status

Example:

Source order text:

```text
Respondent is directed to file a written reply within 15 days from the date of this order.
```

Expected structured output:

```json
{
  "compliance_description": "File written reply",
  "responsible_party": "Respondent/Advocate",
  "due_date": "order_date + 15 days",
  "timeline_text": "within 15 days from the date of this order",
  "filing_requirement": "Written reply",
  "court_direction": "Respondent is directed to file",
  "next_action": "Prepare and file written reply",
  "status": "pending",
  "review_status": "review_required"
}
```

### C4. Existing Foundation To Reuse

Reuse and extend:

- `MatterCourtOrder`
- `MatterTask`
- `MatterDeadline`
- `MatterProceedingSignal`
- `services/proceeding_intelligence.py`
- `ModelRun`
- existing tenant AI policy and rate limit patterns
- existing notification delivery intent foundation
- existing attachment OCR/document processing path

### C5. Recommended Data Model

Add dedicated compliance records so the UI can manage compliance obligations as
first-class items while still generating tasks/deadlines.

New table: `matter_compliance_extraction_runs`

Fields:

- `id`
- `company_id`
- `matter_id`
- `court_order_id`
- `attachment_id`
- `source_type`: `auto_fetched_order`, `manual_order`, `manual_upload`
- `trigger`: `case_tracking`, `court_sync`, `manual_order_create`,
  `attachment_processed`, `manual_retry`
- `status`: `queued`, `processing`, `completed`, `failed`, `skipped`
- `skip_reason`
- `model_run_id`
- `parser_version`
- `started_at`
- `completed_at`
- `error_message_redacted`
- `created_by_membership_id`
- timestamps

New table: `matter_compliance_items`

Fields:

- `id`
- `company_id`
- `matter_id`
- `court_order_id`
- `attachment_id`
- `extraction_run_id`
- `description`
- `responsible_party`
- `due_on`
- `timeline_text`
- `filing_requirement`
- `court_direction`
- `next_action`
- `source_snippet`
- `source_page`
- `source_paragraph`
- `confidence_label`: `high`, `medium`, `low`
- `status`: `pending`, `in_progress`, `completed`, `waived`, `not_applicable`
- `review_status`: `review_required`, `confirmed`, `edited`, `rejected`
- `generated_task_id`
- `generated_deadline_id`
- `dedupe_key`
- timestamps

Constraints:

- unique `(matter_id, court_order_id, dedupe_key)` where `court_order_id` is not
  null
- unique `(matter_id, attachment_id, dedupe_key)` where `attachment_id` is not
  null and no court order exists
- indexes on company, matter, due date, status, review status

### C6. Extraction Pipeline

For auto-fetched court orders:

1. Case tracking or court sync creates/updates `MatterCourtOrder`.
2. System checks whether the order has usable text or linked attachment text.
3. System creates an extraction run.
4. Deterministic proceeding extraction runs first as fallback and for cheap
   signals.
5. AI extraction runs if tenant AI policy allows it and text is sufficient.
6. JSON response is schema-validated.
7. Items are deduplicated against existing compliance items.
8. Draft tasks/deadlines are created or updated.
9. In-app notification intent is created for relevant users.
10. User reviews, edits, confirms, or rejects items.

For manual upload:

1. User uploads a court order attachment or creates a manual court order.
2. Attachment is accepted only if it passes the existing file-safety gate:
   allowed MIME/extension/signature checks, configured file-size limits, and
   malware scan where configured.
3. Attachment is processed/OCRed if needed.
4. If document type is `order_judgment` or user marks it as court order, the
   system links/creates `MatterCourtOrder`.
5. Extraction run starts after text is available.
6. If OCR/text extraction is pending, UI shows "waiting for document text".
7. If OCR/text extraction fails, UI shows a redacted failure state and retry
   action without exposing raw parser/provider errors.
8. Results flow into the same compliance review surface.

Safe review default:

- Compliance items must be created first with `review_status=review_required`.
- Generated tasks/deadlines are draft or review-linked by default; they become
  active only after lawyer/user confirmation unless a tenant-admin setting
  explicitly enables auto-activation.
- Rejected compliance items must not appear as active compliance and must not
  keep active generated tasks/deadlines.
- Every confirm, edit, reject, waive, complete, retry, and generated work-item
  transition must be audited.

### C7. AI Prompt Requirements

The prompt must:

- identify only obligations supported by the provided order text
- never invent due dates
- calculate relative dates only from explicit anchors such as order date
- preserve uncertainty
- return JSON only
- include source snippet for every item
- mark low-confidence fields for review
- not produce legal advice
- not expose raw prompt text to frontend

Deadline calculation rules:

- Default relative-date convention is calendar days from the explicit anchor
  date.
- Do not assume court holidays or business-day adjustments unless a trusted
  court calendar exists for that forum and date range.
- Ambiguous phrases such as "from today", "within two weeks", "next date", or
  missing order date must be flagged `review_required`; the system must not
  invent a computed due date.
- Every computed date must show source snippet and confidence.

Required output schema:

```json
{
  "items": [
    {
      "description": "string",
      "responsible_party": "string|null",
      "due_date": "YYYY-MM-DD|null",
      "timeline_text": "string|null",
      "filing_requirement": "string|null",
      "court_direction": "string|null",
      "next_action": "string|null",
      "source_snippet": "string",
      "source_page": "integer|null",
      "source_paragraph": "string|null",
      "confidence_label": "high|medium|low"
    }
  ],
  "warnings": ["string"],
  "unsupported_gaps": ["string"]
}
```

### C8. Review UX

Matter-level compliance panel:

- pending review count
- upcoming due dates
- overdue items
- item source order/document
- source snippet
- generated task/deadline links
- edit fields
- confirm
- reject
- mark completed
- mark waived/not applicable with reason

Matter hearings/order page:

- show compliance extraction status on each court order
- "Run extraction again" action for authorized users
- show deterministic/AI source label

Matter tasks page:

- generated tasks/deadlines should show source "Court order compliance"
- link back to compliance item and order

### C9. Notifications

Create durable in-app notification intents for:

- new compliance item pending review
- compliance due soon
- compliance overdue
- extraction failed and requires user action

External delivery:

- must remain fail-closed unless provider-specific delivery is configured.

### C10. Acceptance Criteria

- Auto-fetched order fixture creates compliance extraction run.
- Manual court order upload fixture creates compliance extraction run after text
  processing.
- Relative due date "within 15 days from the date of this order" is calculated
  correctly.
- Duplicate extraction does not create duplicate tasks/deadlines.
- User can edit and confirm extracted compliance.
- Rejected item does not appear as active compliance.
- All items are tenant-scoped.
- ModelRun/audit records are present for AI extraction.
- Provider/LLM failure creates a safe failed state without blocking matter use.

## 10. Epic D: Admin-Controlled Billing And Invoice PDF

### D1. User Story

As a law-firm admin, I want to define billing rates and rules so invoices can be
generated consistently and downloaded as PDFs.

### D2. Product Boundary

This epic concerns GBA's billing to its clients for legal matters.

It is separate from:

- CaseOps SaaS subscription billing
- CaseOps platform invoices
- Pine Labs subscription/top-up checkout

### D3. Billing Configuration Requirements

Admin can configure:

- default currency, INR unless the tenant already has a different configured
  currency
- firm legal name, billing address, GSTIN, and PAN
- place of supply defaults and GST split rules
- default SAC/HSN or service classification
- default tax/GST rate where applicable
- invoice numbering prefix and sequence
- default payment terms
- default due days
- matter billing mode:
  - hourly
  - fixed fee
  - milestone
  - mixed
- role/user-level hourly rates
- default hourly rate
- fixed-fee matter arrangements
- milestone billing templates
- retainers/advance adjustment fields where supported by the existing model,
  otherwise additive fields that do not change existing invoice semantics
- practice-area default rates
- expense/reimbursement line item categories
- manual line item categories
- invoice footer/note text
- firm logo/header if configured

### D4. Data Model

New table: `matter_billing_profiles`

Fields:

- `id`
- `company_id`
- `name`
- `is_default`
- `currency`
- `firm_legal_name`
- `firm_address`
- `firm_gstin`
- `firm_pan`
- `default_place_of_supply`
- `default_sac_hsn`
- `gst_applicable`
- `gstin_state_code`
- `cgst_rate_bps`
- `sgst_rate_bps`
- `igst_rate_bps`
- `tax_rate_bps`
- `invoice_prefix`
- `next_invoice_sequence`
- `payment_terms_days`
- `billing_mode`
- `notes_template`
- `footer_text`
- timestamps

New table: `matter_billing_rates`

Fields:

- `id`
- `company_id`
- `billing_profile_id`
- `rate_scope`: `user`, `role`, `practice_area`, `default`
- `membership_id`
- `role`
- `practice_area`
- `currency`
- `amount_minor_per_hour`
- `effective_from`
- `effective_to`
- `is_active`
- timestamps

Optional table: `matter_invoice_exports`

Fields:

- `id`
- `company_id`
- `matter_id`
- `invoice_id`
- `format`: `pdf`
- `generated_by_membership_id`
- `generated_at`
- `template_version`
- `file_name`
- `checksum`

### D5. Invoice Generation Rules

- When creating a time entry, default rate should resolve from:
  1. user-specific active rate
  2. role rate
  3. practice-area rate
  4. billing profile default rate
  5. no default, user must enter rate
- Invoice number should be generated if not manually supplied.
- Time entries already attached to an invoice cannot be double-billed.
- Tax calculation must be server-side and based on persisted invoice/profile
  data, including place of supply and CGST/SGST/IGST split where GST applies.
- Fixed-fee/milestone line items should be supported as manual line items.
- Invoice data must capture invoice date, due date, taxable value, tax totals,
  grand total, amount paid, outstanding amount, and TDS deduction/payment
  adjustment fields where applicable.
- Invoice PDF must render from server-side invoice data, not client-side HTML.
- UI must not include tax/legal advice copy.

### D6. APIs

Tenant admin billing config:

- `GET /api/admin/matter-billing/profiles`
- `POST /api/admin/matter-billing/profiles`
- `PATCH /api/admin/matter-billing/profiles/{profile_id}`
- `POST /api/admin/matter-billing/profiles/{profile_id}/make-default`
- `GET /api/admin/matter-billing/rates`
- `POST /api/admin/matter-billing/rates`
- `PATCH /api/admin/matter-billing/rates/{rate_id}`

Matter invoice:

- extend existing invoice create to support profile/default numbering
- `GET /api/matters/{matter_id}/invoices/{invoice_id}/download?format=pdf`
- optional `GET /api/matters/{matter_id}/invoices/{invoice_id}/download?format=json`

### D7. Frontend

Admin page:

- route: `/app/admin/matter-billing`
- profile list
- create/edit default profile
- rate table
- user/role/practice-area rate configuration
- invoice numbering preview

Matter billing page:

- show applied billing profile
- show default rate when creating time entry
- generate invoice from unbilled time entries
- download invoice PDF
- show invoice PDF download state

### D8. Acceptance Criteria

- Admin can create default billing profile.
- Admin can create role/user/practice-area rates.
- New time entry can auto-populate rate from configuration.
- Invoice can be generated with server-side invoice number.
- Invoice PDF can be downloaded.
- Time entries cannot be billed twice.
- Tenant A cannot access Tenant B rates/invoices.
- Invoice export writes audit event.

## 11. Epic E: Next Hearing Date Management

### E1. User Story

As a user, I want next hearing dates to update automatically from court records
while still allowing authorized manual correction with audit history.

### E2. Data/Provenance Requirements

Add or expose provenance for `Matter.next_hearing_on`.

Recommended fields on `Matter` or a dedicated history table:

- `next_hearing_source`: `manual`, `case_tracking`, `court_sync`,
  `proceeding_intelligence`, `cause_list`, `unknown`
- `next_hearing_source_ref_type`
- `next_hearing_source_ref_id`
- `next_hearing_updated_by_membership_id`
- `next_hearing_updated_at`
- `next_hearing_manual_lock`: boolean, default false

New history table: `matter_next_hearing_history`

Fields:

- `id`
- `company_id`
- `matter_id`
- `old_date`
- `new_date`
- `source`
- `source_ref_type`
- `source_ref_id`
- `changed_by_membership_id`
- `change_reason`
- `created_at`

### E3. Automatic Update Sources

Automatic hearing date updates may come from:

- case tracking provider snapshot
- tracked case update event
- court sync cause-list entry
- court order/proceeding intelligence

Precedence:

1. Manual lock prevents automatic overwrite unless user unlocks or explicitly
   accepts suggestion.
2. High-confidence future provider date can update the matter if no manual lock.
3. If automatic source conflicts with existing future manual date, create a
   review suggestion instead of overwriting.
4. Past dates should not replace a future hearing date unless the matter/order
   indicates disposal/final status.

### E4. Manual Update Flow

1. User opens matter or case details.
2. User selects Add/Edit Hearing Date.
3. User enters date, purpose, notes, and optional reason.
4. System updates `Matter.next_hearing_on`.
5. System creates/updates `MatterHearing`.
6. System records history and audit event.

### E5. UI Requirements

Matter header:

- show next hearing date
- show source label: Manual, Case tracking, Court sync, Court order extraction
- show last updated timestamp

Hearings page:

- manual add/edit hearing date
- automatic update suggestions
- accept/reject suggestion
- history drawer

Case tracking page:

- when an update includes a new hearing date, allow link/update to matter if the
  tracked case is linked to a matter

### E6. Acceptance Criteria

- Manual hearing date update records history.
- Automatic provider fixture updates hearing date when no conflict exists.
- Automatic provider fixture creates review suggestion when manual lock/conflict
  exists.
- History shows old date, new date, source, actor, timestamp.
- Tenant isolation and matter access rules are enforced.

## 12. Epic F: Date-Wise Cause List Generation And PDF Download

### F1. User Story

As a GBA user, I want to generate a date-wise cause list for scheduled matters
and download it in PDF format, so daily court schedules can be shared with
advocates and clients.

### F2. Scope

Supported inputs:

- `MatterHearing` records for selected date/date range
- `MatterCauseListEntry` records for selected date/date range
- matter metadata such as matter code, court name, title, client/opposing party
- assignee/advocate information where available

Supported output:

- in-app preview
- PDF download
- A4 portrait format
- court-style tabular layout

### F3. Required Fields

The generated cause-list PDF must include:

- serial number
- file number
- court name
- case number
- case title
- judge name
- court number
- item number
- lawyer(s) appearing
- hearing date

Field mapping:

- Serial Number: row number in generated list
- File Number: `Matter.matter_code`
- Court Name: `Matter.court_name` or `Court.name`
- Case Number: use explicit case-number field if available; otherwise display
  matter code or source reference with label
- Case Title: `Matter.title`
- Judge Name: hearing judge, cause-list resolved bench, or matter judge
- Court Number: `MatterCauseListEntry.courtroom`
- Item Number: `MatterCauseListEntry.item_number`
- Lawyer(s) Appearing: matter assignee and/or configured advocates
- Hearing Date: selected listing/hearing date

Missing-field behavior:

- Preview and PDF must not silently omit required fields.
- If a required field cannot be resolved, display `Not available` or a
  professional missing-field warning in preview.
- Users may apply manual or derived overrides before PDF generation where the
  source data allows it.

Open implementation note:

- Current `Matter` does not expose a dedicated case-number field in the inspected
  model. Implementation should either reuse existing source reference where
  appropriate or add a dedicated `case_number`/`cnr_number` field if not already
  present elsewhere.

### F4. Sorting

Default sort:

1. hearing/listing date
2. court name
3. court number
4. item number numeric where possible
5. case title

User-selectable sort options:

- court-wise
- lawyer-wise
- matter-code-wise
- item-number-wise

### F5. Filtering

Preview filters:

- date
- date range
- court
- lawyer/assignee
- practice area
- matter status
- include/exclude disposed matters
- source: hearings, cause-list entries, or both

### F6. PDF Requirements

- A4 portrait.
- Organization logo/header if configured.
- Date displayed at top.
- Generated-at timestamp.
- Firm name.
- Applied filters.
- Court-style table.
- Repeated header on every page.
- Proper pagination.
- Page number footer.
- Printable black-and-white friendly design.
- ASCII-safe fallback for unsupported glyphs.
- No tenant-private internal IDs unless explicitly useful as file number.

### F7. Backend APIs

New router: `/api/cause-lists`

Endpoints:

- `GET /api/cause-lists/preview`
  - query: `date`, `from_date`, `to_date`, `court_id`, `court_name`,
    `assignee_id`, `source`, `include_disposed`, `sort`
  - returns structured rows and summary counts
- `GET /api/cause-lists/download`
  - same filters
  - `format=pdf`
  - returns PDF
- optional `GET /api/cause-lists/download?format=csv`
  - not required by GBA source, but useful for back-office workflows

### F8. Data Model

Optional table: `cause_list_exports`

Fields:

- `id`
- `company_id`
- `generated_by_membership_id`
- `date_from`
- `date_to`
- `filters_json`
- `row_count`
- `format`
- `status`
- `generated_at`
- `file_name`
- `checksum`

Every download audit/export record must include applied filters, row count,
actor, timestamp, generated file name, and checksum.

This table is for audit/history only. It should not store the full PDF unless
the app already has a secure export storage pattern for generated artifacts.

### F9. Frontend

New page:

- route: `/app/cause-list`
- sidebar entry near Calendar/Hearings
- date picker
- date range picker
- filters
- preview table
- PDF download button
- empty state
- loading state
- error state
- disabled state if no scheduled matters

Preview table columns:

- S. No.
- File No.
- Court
- Case No.
- Case Title
- Judge/Bench
- Court No.
- Item No.
- Lawyers
- Hearing Date

### F10. Acceptance Criteria

- User can generate preview for a single date.
- User can generate preview for a date range.
- User can download PDF.
- PDF includes all required fields.
- PDF paginates correctly for more than one page.
- Empty date shows professional empty state.
- Tenant access is enforced.
- Download writes audit event.
- Disposed matters are excluded by default unless user includes them.

## 13. Cross-Cutting Security And Governance

### 13.1 Tenant Isolation

Every new query must filter by `company_id` or matter access through existing
matter loading helpers.

Forbidden:

- cross-tenant matter access
- cross-tenant invoice access
- cross-tenant cause-list export
- linking an attachment from one matter to another matter's compliance item

### 13.2 Capabilities

Recommended capability mapping:

- Matter status update: existing matter write capability
- Case tracking schedule/admin visibility: admin/provider operations capability
- Compliance extraction run/retry: fee-earner or admin with matter access
- Compliance confirm/reject/edit: matter write or compliance manage capability
- Billing profile/rate admin: tenant admin/owner
- Invoice create/download: existing invoice capabilities
- Cause-list preview/download: matter read across accessible matters; admin can
  generate all-firm list

### 13.3 Audit

Audit all:

- status changes
- case tracking scheduled runs
- compliance extraction run status changes
- compliance item edits/confirm/reject/complete/waive
- generated task/deadline creation from compliance item
- billing profile/rate changes
- invoice PDF downloads
- manual next-hearing changes
- automatic next-hearing changes
- cause-list PDF downloads

### 13.4 AI Safety

- Compliance extraction must be source-backed.
- Every extracted item must show its source order/snippet.
- Review status defaults to `review_required`.
- Low-confidence values must not silently generate external communications.
- Failed AI calls must fail safely and preserve deterministic fallback where
  available.
- ModelRun must record provider/model/tokens/status without exposing raw secrets.

### 13.5 Notifications

Use durable in-app notification intents for:

- new compliance items
- due-soon/overdue compliance
- case tracking updates
- extraction failures requiring attention

External delivery remains disabled unless separately approved.

Recipient rules:

- Matter update/compliance notifications go to the matter owner/lead lawyer,
  assigned lawyer/team members/watchers where present, and only recipients who
  pass matter access checks.
- Tenant admins receive failed scheduled/provider/extraction job notifications.
- Repeated notifications for the same source update must be deduplicated with a
  stable idempotency key.

## 14. Implementation Order

### Phase 0: PRD Baseline

- Add this PRD.
- Confirm no missing requirements from source document.
- Create implementation branch.

### Phase 1: Matter Status Dispose

- Add `disposed` status.
- Migrate `closed` rows.
- Update backend schemas/types.
- Update frontend status options/badges/filters.
- Update tests.

### Phase 2: Daily Case Tracking Refresh Window

- Add scheduling/window settings.
- Update script to report/enforce window.
- Update Cloud Run job/scheduler manifests/deploy helper.
- Add provider-disabled and window tests.

### Phase 3: Compliance Extraction Data Model

- Add compliance extraction run and item tables.
- Add schemas and service layer.
- Add deterministic bridge from existing proceeding intelligence.
- Add audit.

### Phase 4: AI Compliance Extraction

- Add LLM prompt/schema validation.
- Persist ModelRun.
- Add dedupe and task/deadline generation.
- Add notification intents.
- Add retry/failure behavior.

### Phase 5: Manual Upload And Auto-Fetch Triggers

- Trigger extraction on auto-fetched orders.
- Trigger extraction on manual order creation.
- Trigger extraction after attachment processing for court-order uploads.
- Add UI status.

### Phase 6: Billing Configuration And Invoice PDF

- Add billing profiles/rates.
- Add admin UI.
- Add rate resolution in time entries.
- Add matter invoice PDF endpoint and UI download.

### Phase 7: Next Hearing Provenance And Review

- Add provenance/history.
- Implement automatic update rules.
- Add manual lock/conflict suggestion behavior.
- Update UI.

### Phase 8: Cause List Module And PDF

- Add preview/download APIs.
- Add PDF renderer.
- Add `/app/cause-list`.
- Add tests for pagination and required fields.

### Phase 9: Final Review And Release

- Run targeted backend tests.
- Run frontend tests/typecheck/build.
- Run migrations upgrade/downgrade on throwaway DB.
- Run local smoke.
- Update user guide/runbooks if needed.

## 15. Verification Requirements

Backend:

- ruff on touched backend files
- py_compile on new scripts/migrations
- migration order tests
- migration upgrade/downgrade on SQLite and Postgres if available
- tests for matter status migration/API
- tests for case tracking window/scheduler behavior
- tests for compliance extraction deterministic fallback
- tests for AI schema validation with fake provider
- tests for duplicate compliance idempotency
- tests for manual upload trigger
- tests for billing rate resolution and invoice PDF
- tests for next-hearing provenance/history
- tests for cause-list preview/PDF
- tenant isolation tests for every new route

Frontend:

- status dropdown/filter tests
- compliance panel tests
- billing settings tests
- invoice PDF download control tests
- next-hearing source/history tests
- cause-list preview/download tests
- typecheck
- build

Static safety:

- `git diff --check`
- secret scan on touched files
- no raw provider payload exposure
- no tenant-facing internal cost/profit leakage
- no visible `Closed`/`Close` matter status labels after Phase 1, except in
  migration/backward-compatibility comments/tests

Local smoke:

- create matter with Dispose status
- run case-tracking script in test/window override
- import or create court order and see compliance extraction result
- upload court order attachment and see queued extraction
- create billing profile/rate and invoice PDF
- manually update next hearing and inspect history
- generate cause-list PDF for a date with sample hearings

## 16. Release And Rollout

Feature flags/settings:

- `CASEOPS_CASE_TRACKING_DAILY_WINDOW_START`
- `CASEOPS_CASE_TRACKING_DAILY_WINDOW_END`
- `CASEOPS_CASE_TRACKING_DAILY_TIMEZONE`
- `CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED`
- `CASEOPS_COMPLIANCE_AI_EXTRACTION_AUTO_RUN_ENABLED`
- `CASEOPS_MATTER_BILLING_CONFIG_ENABLED`
- `CASEOPS_CAUSE_LIST_EXPORT_ENABLED`

Rollout sequence:

1. Deploy status terminology migration and UI.
2. Deploy scheduling changes in disabled/provider-safe state.
3. Deploy compliance extraction with auto-run disabled, test manual runs.
4. Enable auto-run for one smoke tenant.
5. Deploy billing config/invoice PDF.
6. Deploy next-hearing provenance.
7. Deploy cause-list export.
8. Run GBA UAT with representative matters/orders.

Rollback notes:

- `disposed` downgrade maps back to `closed`.
- Compliance extraction tables are additive and can be disabled by feature flag.
- Billing config is additive; existing invoice creation remains usable.
- Cause-list export is additive and can be disabled without data loss.

## 17. Open Inputs Needed From GBA

To exactly match GBA expectations, collect:

1. Sample cause-list PDF referenced in the source document.
2. GBA logo/header assets and preferred firm name/address for PDF header.
3. Whether the display label must be exactly `Dispose` or whether `Disposed`
   is acceptable in badges/reports.
4. Required matter case-number/CNR fields for cause-list output.
5. Billing rate rules:
   - hourly rates
   - fixed-fee rules
   - tax/GST applicability
   - invoice numbering format
   - payment terms
6. Who should appear under "Lawyer(s) Appearing":
   - matter assignee
   - all assigned team members
   - advocate field
   - manually selected lawyers
7. Whether compliance extraction should auto-create tasks immediately or create
   review-only draft items first.
8. Whether automatic next-hearing updates should ever overwrite manual dates.
9. Which courts/providers GBA expects for the 4:00 PM to 6:00 PM daily refresh.
10. Whether cause-list PDFs should include disposed matters when they still have
    a future date by mistake.

## 18. Definition Of Done

This PRD is done when:

- All six source requirements are implemented or explicitly feature-gated.
- Every new data write is tenant-scoped and audited.
- Provider-disabled behavior is safe.
- AI compliance extraction is source-backed and reviewable.
- Matter invoice PDFs are downloadable.
- Date-wise cause-list PDFs are downloadable and printable.
- Existing tests pass.
- New backend/frontend tests cover the GBA flows.
- A GBA UAT checklist is created and run against representative data.

## 19. Codex CLI Starter Prompt

```text
You are in C:\Users\mishr\caseops.

Read docs/PRD_GBA_LAW_OFFICE_REQUIREMENTS_2026-06-06.md end to end. Implement it in phases without skipping safety gates.

Hard rules:
- Do not bypass captcha/session-gated court sources.
- Do not enable unapproved external provider calls.
- Do not send external email/SMS/WhatsApp notifications.
- Preserve tenant isolation and audit.
- Keep law-firm matter billing separate from CaseOps SaaS billing.
- AI compliance extraction must be source-backed, schema-validated, reviewable, and auditable.
- Do not expose provider tokens, raw payloads, raw prompts, or tenant-private data.

Implementation order:
1. Matter status `disposed` migration and UI terminology.
2. Daily case-tracking refresh window between 4 PM and 6 PM Asia/Kolkata.
3. Compliance extraction data model and deterministic bridge.
4. AI compliance extraction with ModelRun, dedupe, tasks/deadlines, notifications.
5. Auto-fetched and manual-upload order triggers.
6. Admin matter-billing profiles/rates and matter invoice PDF download.
7. Next-hearing provenance/history/manual lock/conflict behavior.
8. Date-wise cause-list preview and PDF download.
9. Tests, local smoke, docs updates, and release-readiness report.

Run focused tests after each phase. Finish with backend lint/tests, frontend tests/typecheck/build, migration checks, git diff checks, and a concise implementation report.
```
