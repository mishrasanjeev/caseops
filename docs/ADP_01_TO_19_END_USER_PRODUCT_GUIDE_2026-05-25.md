# CaseOps ADP-01 to ADP-19 End User Product Guide

Last updated: 2026-07-23

This guide explains the product capabilities delivered through ADP-19 and how
law firm and legal operations users can use them in CaseOps. It is written for
end users and administrators, not developers.

## General Safety Notes

- CaseOps helps organize legal work, documents, research, drafting, and
  operational workflows. It does not replace professional legal judgment.
- AI-assisted outputs should be reviewed by a qualified lawyer before use.
- Features that show summaries, recommendations, alerts, or extracted fields are
  review aids. They are not legal advice, outcome predictions, success
  probabilities, or judge/court recommendations.
- Calendar, judgment, law update, and email-invitation features are in-app and
  review-driven unless the product explicitly says otherwise.
- Do not upload or enter secrets, passwords, private keys, or provider tokens in
  ordinary matter notes, documents, comments, or descriptions.

## ADP-01: Storage Governance

Purpose: Track storage use and enforce safer upload behavior.

How to use:

1. Upload matter documents through the normal matter document flow.
2. Review storage or quota messages shown by the app before retrying failed
   uploads.
3. Ask an administrator to review firm-level storage settings if uploads are
   blocked by quota.

What to expect:

- The system tracks storage at the firm level.
- Uploads may be blocked when governance limits are exceeded.
- Storage governance does not expose storage keys or internal object paths to
  end users.

## ADP-02: AI Token Governance

Purpose: Keep AI usage controlled by firm and user quotas.

How to use:

1. Use AI features normally, such as Matter File Q&A, recommendations, and
   drafting assistance.
2. If an AI request is blocked, review the quota or policy message.
3. Ask an administrator to adjust approved AI budgets or policies if needed.

What to expect:

- AI requests are checked against policy and quota controls.
- Over-limit requests fail closed before provider calls.
- Audit metadata avoids storing raw prompts and answers.

## ADP-03: Objective-Based Recommendations

Purpose: Generate matter recommendations tied to an explicit objective.

How to use:

1. Open a matter and go to the recommendations area.
2. Choose or enter a clear objective, such as preparing for hearing, improving
   evidence organization, or reviewing next procedural steps.
3. Review recommendations with their supporting context.
4. Accept only the actions that fit your professional judgment.

What to expect:

- Recommendations are framed around your selected objective.
- The system should avoid unsupported legal conclusions and outcome prediction.
- Recommendations remain advisory workflow suggestions, not legal advice.

## ADP-04: Contextual Legal Research

Purpose: Search legal context using existing source-backed authority data.

How to use:

1. Open the research area.
2. Enter a natural-language legal or factual issue.
3. Review returned issues, statutes, authorities, and source references.
4. Use weak-coverage messages as a warning that more research is needed.

What to expect:

- Results should include source-backed references where available.
- The feature does not run new corpus ingest or guarantee exhaustive coverage.
- Use citations and authority links as starting points for lawyer review.

## ADP-05: Unified Communication Timeline

Purpose: View matter communications in one chronological timeline.

How to use:

1. Open a matter and select the communications page.
2. Review emails, notes, and related communication entries in chronological
   order.
3. Use filters to narrow by type, direction, or source where available.
4. Treat internal-only notes as firm-side content.

What to expect:

- Timeline entries are matter-access controlled.
- Internal notes should not appear in outside-counsel or portal views unless the
  product explicitly allows them.
- Full email bodies and attachment payloads are not exposed through the timeline
  surface.

## ADP-06: Court and Judge Context Explorer

Purpose: Explore descriptive court and judge context from existing records.

How to use:

1. Open the courts or judge profile pages.
2. Review practice-area counts, court-wise counts, statute or act trends, and
   source-backed case lists where available.
3. Pay attention to sample-size and coverage limitations.

What to expect:

- Analytics are descriptive and historical.
- Low sample sizes suppress pattern claims and show limitations.
- The feature does not recommend the best judge, best bench, best court, most
  suitable judge, or probability of success.

## ADP-07: Calendar Sync Status and Conflict Review

Purpose: Show calendar sync readiness and surface reviewable conflicts.

How to use:

1. Open the calendar page.
2. Review the sync status panel.
3. Connect Outlook only through the approved calendar connection flow.
4. Use manual visible-range sync where available.
5. Review conflict candidates before taking further action.

What to expect:

- Current Outlook sync is bounded and manual.
- Durable always-on sync remains pending until the required automation
  prerequisites are complete.
- Reminder or notification delivery is not active unless the product explicitly
  says it is.

## ADP-08: Multilingual Matter File Q&A

Purpose: Ask questions about uploaded matter documents and optionally receive a
local-language aid.

How to use:

1. Open a matter's documents page.
2. Use Matter File Q&A to ask a question grounded in uploaded matter documents.
3. Keep English selected for the default response, or choose a supported local
   language when available.
4. Review the English answer as authoritative.
5. Treat local-language output as a translation aid, not a separate legal
   analysis.

Supported foundation languages:

- English (`en`)
- Hindi (`hi`)
- Marathi (`mr`)
- Gujarati (`gu`)
- Tamil (`ta`)
- Telugu (`te`)
- Kannada (`kn`)
- Bengali (`bn`)

What to expect:

- Answers remain grounded only in uploaded matter documents.
- Source cards and snippets remain tied to original uploaded evidence.
- Unsupported languages fail closed.
- Refusals for missing, processing, or insufficient evidence remain refusals.

## ADP-09: Outside Counsel Spend Tracking

Purpose: Track matter-level outside counsel spend and payment status.

How to use:

1. Open a matter's outside counsel page.
2. Review assigned counsel, agreed fee, amount paid, amount pending, invoice
   references, and payment status.
3. Update factual spend or payment tracking fields if you have permission.
4. Use the spend summary to understand operational status.

What to expect:

- Pending amount is computed from recorded agreed and paid amounts.
- Multi-currency values should be reviewed carefully and not treated as one
  combined currency unless the UI says so.
- The feature does not process payments or score outside counsel performance.
- Outside counsel portal users should not see firm-internal spend fields unless
  explicitly configured and tested.

## ADP-10: Client Verification Workflow

Purpose: Track client or matter verification status through review states.

How to use:

1. Open the client page.
2. Review verification status and required document metadata.
3. Mark verification requested, submitted, under review, verified, rejected, or
   expired according to the matter's process.
4. Record bounded rejection or rework reasons where allowed.

Supported statuses:

- not required
- required
- requested
- submitted
- under review
- verified
- rejected
- expired

What to expect:

- Verification uses existing KYC/client metadata foundations.
- Document references are references only; the workflow does not expose identity
  document payloads or storage keys.
- There is no biometric verification or automated identity scoring.

## ADP-11: Bulk Matter Creation

Purpose: Validate the canonical 21-column CSV/XLSX template or a documented
compatible client register, create every valid matter after confirmation, and
retain a searchable audit/error history.

Release status (23 July 2026): the compatibility revision described below is
deployed from merge commit `e763584`. Full CI, security, database migration,
Cloud Run revision/digest/traffic, and public-health certification passed.
Post-deploy workflow `30019214017` passed, including the dated bulk-Matter
scenario and its lifecycle-cleanup hook. See the dated validation guide for
the exact live-production coverage boundary and cleanup-proof limits.

Who can use it:

- Workspace Owner.
- Admin.
- A custom Matter Manager role granted `matters:bulk_import` by an Owner.
- Viewer/read-only users cannot see or call the import workflow.

How to use:

1. Open **Matters** and select **Bulk upload matters**.
2. Download the XLSX template (recommended) or CSV template. The XLSX workbook
   includes Matter Import, Reference Values, and Instructions sheets.
3. Enter one matter per row. The canonical template has 21 columns. **Court**
   is the court/forum name; **Court Forum Number** is a separate optional court,
   bench, room, or forum reference.
4. Upload the completed `.xlsx` or `.csv` file. CSV may be UTF-8, BOM-marked
   UTF-16, or Windows-1252 and may use comma, semicolon, tab, or pipe
   delimiters. Enclose a field in standard CSV double quotes when it contains
   the selected delimiter.
5. Select **Validate data before import**. No matter is created at this step.
6. Review Total Records, Valid, Validation Errors, Imported, and Failed counts.
   Invalid rows appear first and show every detected problem.
7. Correct the source and upload it again, or confirm the current job to create
   all rows that are still valid. Invalid rows are skipped rather than blocking
   valid matters.
8. Download the error CSV for any invalid or commit-failed rows.
9. Use Import History to search by file name, uploader name, or uploader email,
   and filter by job status.

Required fields:

- Matter Title.
- Matter Code.
- Practice Area.
- Forum.

Client Name is optional. Matter Status is optional and defaults to Active.
Other optional fields are Matter Type/Description, client code/contact
number/email, opposing party/counsel, Court, Court Forum Number, Case Number,
Filing Number/Date, Matter Owner, Assigned Team, and Responsible Lawyer. People
are entered by their active CaseOps work email; teams may use an active team
name or slug.

Compatible values and layouts:

- Status and Forum values are case-insensitive and tolerate spaces, hyphens,
  and underscores. For example, `On Hold`, `on-hold`, and `on_hold` mean the
  same status; `HIGH COURT` and `high_court` mean the same forum.
- A required Practice Area does not have to exist in the catalog. CaseOps
  canonicalizes a known value and preserves another valid 2-120 character
  business label.
- Normal legal/business punctuation is supported in applicable text/reference
  fields. A phone main number must contain 7-20 digits and may have a trailing
  `ext`, `ext.`, or `x` followed by 1-10 digits. Without a leading `+`, it may
  use spaces, parentheses, periods, commas, `#`, hyphens, slashes, and `&`.
  With exactly one leading international `+`, the formula-safe grammar permits
  only digits, spaces, parentheses, and hyphens before the optional extension.
- Common headings such as `Matter Name`, `Matter ID`, `Area of Practice`,
  `Current Status`, `Existing Client Name`, `Court / Forum`,
  `Client Phone No.`, `Date of Filing`, and `Court / Forum No.` are recognized
  regardless of case or presentation punctuation.
- CSV/XLSX may contain report-title rows above the header. XLSX may put the
  import table on a later worksheet. CaseOps searches the first 25 non-empty
  rows of each candidate sheet and chooses the best recognized table.
- Filing Date accepts ISO/year-first dates, common Indian day-first numeric or
  English month-name dates, ISO timestamps, and fractional Excel serial dates.
  XLSX follows the workbook's 1900/1904 date system and discards any
  time-of-day fraction because the field stores a date.

What validation checks:

- Missing required fields and invalid matter code/status/forum.
- Invalid/out-of-range text, filing date, or phone; Client Email must be a
  valid address of at most 254 characters.
- Duplicate Matter Code, Case Number, or Matter Title + Client Name in the file
  and visible tenant records.
- Unknown, inactive, or cross-company people/teams.
- Team-membership consistency when team scoping is enabled.
- Unsafe spreadsheet formulas or formula-like values.

Two rules remain intentionally strict:

- Matter Code is trimmed and uppercased, must be 2-80 characters, must start
  and end with a letter or digit, and may contain only letters, digits, and
  internal hyphens. Spaces, underscores, slashes, and other punctuation are
  rejected, matching normal Matter creation.
- Actual XLSX formula nodes in the selected import header/data cells and
  formula-like selected-table text beginning with `=`, `+`, `-`, or `@` are
  rejected and sanitized. Ignored report rows and nonselected worksheets are
  not imported or evaluated. A phone may begin with `+` only in Client Contact
  Number and only under the narrower grammar above. The downloaded error CSV
  is formula-safe.

What to expect:

- Maximum 500 non-empty rows and 2 MB per import.
- XLSX coordinates must stay within Excel's A-XFD columns and rows
  1-1,048,576. Malformed/out-of-range coordinates and duplicate/out-of-order
  worksheet row references are rejected. Encrypted workbooks, more than 1,000
  ZIP entries, an uncompressed entry over 16 MiB, total uncompressed content
  over 32 MiB, or a 250:1 compression ratio on an entry of at least 1 MiB are
  rejected. XLSX ZIP entries must use stored or Deflate compression; other
  compression methods are rejected. Workbook metadata is capped at 512 KiB per required metadata file;
  shared strings are streamed and capped at 100,000 entries, 32,767 characters
  per entry, and 8,388,608 characters of aggregate text.
- Validation jobs expire after 24 hours; expired jobs must be uploaded again.
- The system revalidates at confirmation so a duplicate created after preview
  cannot silently pass.
- A mixed file can finish with partial success. For example, 95 valid rows are
  created while 5 invalid rows remain in the error report.
- Repeating confirmation for a completed job is idempotent and creates no
  duplicate matters.
- Upload, validation failure, and completion produce in-app notification
  intents. Validation, each created row, completion, cancellation, and error
  report download are audited.
- The original upload binary is not retained. CaseOps stores its SHA-256,
  metadata, sanitized row data, normalized values, errors, and outcomes.
- The former `/imports/dry-run` API remains for backward-compatible ADP-11
  planning and document-name checks. It still creates no matters or documents;
  the dedicated Bulk upload matters page is the production creation workflow.
- Release implementation/validation details are maintained in
  `docs/BULK_MATTER_VALIDATION_COMPATIBILITY_IMPLEMENTATION_AND_VALIDATION_GUIDE_2026-07-23.md`.

## ADP-12: Google Drive Bounded Manual Import

Purpose: Plan a bounded Google Drive import without autonomous sync.

How to use:

1. Open the Google Drive import area where available.
2. Review provider configuration status.
3. Validate folder or file metadata for a matter.
4. Review the import plan before any later approved execution workflow.

What to expect:

- The foundation validates metadata and fails closed when config is missing.
- It does not contact Google APIs for autonomous sync unless a later approved
  feature explicitly provides that.
- It does not store OAuth tokens, Drive payloads, or file contents through the
  planning surface.

## ADP-13: Party-Based Contract Clause Extraction

Purpose: Extract bounded party-specific contract clause metadata for review.

How to use:

1. Open the contract clause extraction or contract analysis area.
2. Select the contract or available contract text source.
3. Review extracted party names, clause categories, obligations, dates, and
   other bounded clause metadata.
4. Confirm or correct extracted values before relying on them.

What to expect:

- Extraction is a review aid and should not replace contract review.
- The feature avoids storing raw prompt or answer payloads in audit metadata.
- Extracted clause content should stay bounded and source-linked.

## ADP-14: Contract Playbook Admin and Compare

Purpose: Manage contract playbooks and compare clauses against approved
positions.

How to use:

1. Open the contract playbook administration area.
2. Create or update playbook positions for clause categories.
3. Compare a contract's clauses against the playbook.
4. Review deviations and required approvals.

What to expect:

- Playbooks are tenant-scoped.
- Comparison findings are workflow support, not legal advice.
- Users should review all deviations before negotiation or filing decisions.

## ADP-15: Drafting Data Extraction Review Queue

Purpose: Extract drafting facts from uploaded matter documents and route them
through lawyer review.

How to use:

1. Open a matter's drafting page.
2. Run the drafting data extraction review queue where available.
3. Review suggested fields such as FIR number, case number, police station,
   party names, dates, and statute sections.
4. Confirm, override, or reject each field.
5. Generate drafts knowing only confirmed or overridden reviewed fields feed the
   reviewed-facts block.

What to expect:

- Pending or rejected suggestions do not feed draft generation.
- Explicit stepper facts remain authoritative.
- Source snippets are bounded and should match existing extracted document text.
- No raw document text, OCR text, prompt, answer, or storage key is shown in the
  review queue.

## ADP-16: Court-Specific Draft Format Profiles

Purpose: Surface court-specific drafting format profiles and required-field
warnings.

How to use:

1. Open a draft detail or export view.
2. Choose or review the selected court profile.
3. Review required-field warnings before export or filing preparation.
4. Use warnings as a checklist; do not let the system fabricate missing values.

Profile categories:

- District Court
- High Court
- Supreme Court
- Tribunal
- Generic

What to expect:

- Profile rules affect export/checklist metadata where supported.
- Missing required fields are warnings or review findings, not legal sufficiency
  conclusions.
- Normal draft creation remains available.

## ADP-17: Judgment Monitoring In-App Alert Center

Purpose: Create saved in-app judgment alert rules against existing authority
records.

How to use:

1. Open the research or judgment alerts area.
2. Create an alert rule with bounded filters such as query terms, court, judge,
   practice area, statute terms, document type, and date range.
3. Run or preview matches manually.
4. Review in-app alerts and mark them read or dismissed.
5. Use digest preview as an in-app summary only.

What to expect:

- Alerts are generated from existing AuthorityDocument records only.
- Matching is deterministic and manual.
- No crawling, ingestion, LLM, provider call, scheduler, webhook, or external
  notification delivery is performed.
- Alert snippets are bounded and do not expose full judgment text or source
  payloads.

## ADP-18: Law Amendment and Regulatory Update Monitor

Purpose: Track legal updates and regulatory changes through in-app watchlists.

How to use:

1. Open the statutes or legal updates area.
2. Create a watchlist with at least one bounded filter, such as Act, section,
   jurisdiction, practice area, source category, update type, or date range.
3. Run or preview matches manually.
4. Review legal update records, source/provenance metadata, and relevance
   explanations.
5. Mark updates read or dismissed.

What to expect:

- Watchlists require source/provenance for every update record.
- Matching uses existing statute, statute section, authority, and source
  registry metadata.
- Digest preview is in-app only.
- The feature does not send external alerts or expose full statute, judgment, or
  regulatory text beyond existing statute detail behavior.

## ADP-19: Email Invitation to Calendar Candidate Extraction

Purpose: Extract reviewable calendar-event candidates from already imported
email or invite metadata.

How to use:

1. Open the calendar page.
2. Review the Email invitation candidates panel.
3. Scan for candidates from existing imported communications.
4. Review detected title, date/time, location, matter link, duplicate status,
   and bounded source preview.
5. Approve a candidate to create an internal CaseOps calendar item.
6. Reject candidates that should not become calendar items.

What to expect:

- Extraction is deterministic and uses existing imported communication metadata,
  subject, and bounded preview text only.
- Approval creates only an internal CaseOps calendar item.
- It does not create Outlook, Google, or other provider calendar events.
- Pending, rejected, duplicate, or skipped candidates do not create calendar
  items.
- Full email bodies, invite payloads, attachments, storage keys, and provider
  tokens are not shown through the candidate panel.

## Current Production-Use Boundaries

The following boundaries apply after the ADP-20 and ADP-24 foundations:

- ADP-20 implements readiness-gated CaseOps-to-Outlook hearing sync only.
  Broad two-way Outlook automation, Outlook-to-CaseOps import, task/deadline
  sync, mailbox ingestion, and provider webhooks remain out of scope.
- Connector Automation and Communication Readiness (2026-06-10) adds
  review-first Outlook Mail metadata candidates, Microsoft 365 setup/readiness,
  and calendar provider-event suggestions. These are manual review workflows,
  not autonomous Graph mailbox or calendar automation.
- ADP-24 implements an admin provider-operations surface for failed/blocked
  durable jobs, redacted errors, and audited replay/ignore/resolve actions.
  Replay reschedules existing idempotent rows; it does not bypass provider
  readiness gates or make immediate provider calls.
- Durable Google Drive sync remains pending under ADP-21, but a review-first
  Drive candidate queue now exists. Users can review metadata and explicitly
  import selected files through the existing document security/OCR pipeline when
  provider credentials and tenant policy allow it. Auto-import remains off.
- Durable email provider ingestion remains pending under ADP-22, but Gmail and
  Outlook Mail metadata review queues now support link, note/task, request
  import, and ignore actions. Raw email bodies and attachment bytes are not
  imported automatically.
- Inbound email aliases now exist as disabled-by-default readiness. Production
  inbound email remains disabled until a real provider is configured with
  signature verification and DNS/security proof.
- Judgment/legal-update external digest delivery remains pending under ADP-23.
- Background mailbox polling remains disabled.
- Provider webhooks for calendar/email ingestion remain disabled.
- External notification delivery by email, SMS, WhatsApp, push, or digest
  remains provider-gated and disabled unless explicitly configured, preferred by
  the tenant/user, and tested. User and tenant preference screens now exist for
  in-app, email, SMS, WhatsApp, digest frequency, quiet hours, categories, and
  opt-outs.
- Tenant admins can use `/app/admin/integrations` for active connector health,
  `/app/admin/microsoft365` for Graph setup/readiness, and
  `/app/admin/inbound-email` for alias readiness. Founder/platform admins can
  use `/app/platform-admin/integrations` for cross-tenant redacted health.
- Legal outcome prediction or success probability.
- Judge, bench, court, or counsel scoring.

Use the delivered ADP-01 to ADP-19 features as reviewable, source-backed,
in-app workflow foundations. Use `/app/admin/provider-operations` for the
current ADP-21/22/23 readiness ledger and ADP-24 provider retry/dead-letter
foundation.
