# Notice Module Implementation And End-User Usage Guide

Date: 2026-07-07; updated 2026-07-15
Status: Matter workspace deployed; global register implemented locally and pending deployed verification
Primary app locations: `/app/notices` and `/app/matters/{matter_id}/notices`
Related production verification: `.github/workflows/prod-verify.yml`

## 1. Purpose

The Notice module has two complementary surfaces. The company-wide Notice
Management register captures received or sent notices independently of a case,
supports optional ownership and zero, one, or multiple matter links, and does
not require a file. The matter workspace retains the deeper document workflow
for replies, supporting documents, deadline synchronization, and processing.

The global register also presents existing matter notice attachments as
read-only legacy rows, subject to the caller's matter-access rules. It therefore
adds a standalone workflow without duplicating or breaking the established
matter document records.

## 2. Where To Find It

For the company-wide register, select `Notices` in the main navigation. Use it
to receive, send, search, filter, assign, and track notices before a matter is
known, or when one notice spans multiple matters.

Global URL:

```text
/app/notices
```

For the matter document workflow, open a matter and select the `Notices` tab in
the matter cockpit.

Typical path:

1. Sign in to CaseOps.
2. Open `Matters`.
3. Select a matter.
4. Select `Notices` from the matter navigation.

Direct URL pattern:

```text
/app/matters/{matter_id}/notices
```

The matter Notices page shows both matter attachment notices and reverse
references to standalone global notices linked to that matter. A standalone
file remains stored once on the company notice; linking it never creates a
second attachment or file copy. Matter attachment files remain available in
the matter `Documents` page.

## 3. Permissions

The module uses the existing document permissions.

| Capability | What it allows in the Notice module |
|---|---|
| `documents:upload` | Create standalone notices, attach an initial optional file, and upload matter notice/reply/supporting documents. |
| `documents:manage` | Update all standalone metadata, owner, and links; replace an existing standalone file; and manage matter document metadata. |
| Matter access | View linked notices only through matters the user can access; hidden matter links are never exposed. |

Users without write capabilities receive a read-only global register. A notice
with matter links is returned only when the caller can access every linked
matter. A mixed visible/restricted link set hides the whole standalone record,
including its file download, rather than applying the least-restrictive link.
Mutation likewise requires access to every current and requested link.

## 4. Key Concepts

### 4.0 Standalone Company Notice

A standalone company notice is stored independently from matter attachments.
It supports received/sent direction, status, owner, dates, amounts, authority,
summary, optional file, and up to multiple matter links. Matter links may be
empty and can be added later. File creation is a recoverable two-step flow: if
the optional upload fails, the notice remains available with an `Attach
document` action instead of being silently lost.

Existing matter notice attachments appear in the global register as
`legacy_attachment` records. They are intentionally read-only there and remain
managed from the matter workspace.

Standalone edits include an `expected_updated_at` version. If another browser
or integration changed the notice after the form was opened, the API rejects
the stale save instead of silently overwriting the newer record. Reload the
notice and re-apply the intended change. Initial attachment and replacement
uploads carry the same version token, so a stale file action cannot overwrite a
newer file or metadata version.

### 4.1 Primary Notice

A primary notice is the main notice record. It has:

- `document_type = notice`
- `notice_document_role = notice`
- no `notice_parent_attachment_id`

Primary notices appear as rows in the Notice Received or Notice Sent tab.

### 4.2 Notice Received

Use `Notice Received` when the matter team receives a notice from an authority,
opposing party, client department, counsel, regulator, or another external
source.

Received notices can have reply tracking. If a reply is required and a reply due
date is entered, CaseOps creates or updates a matter deadline linked to the
notice.

### 4.3 Notice Sent

Use `Notice Sent` when the matter team sends a notice, demand, recovery notice,
legal notice, or similar outgoing notice.

Sent notices do not use reply-due tracking in the current workflow. They track
sent date, status, counsel, dispute amount, recovered amount, department, and
other document metadata.

### 4.4 Related Documents

Related documents are additional files linked to a primary notice.

| Role | Meaning |
|---|---|
| `reply` | A reply document filed or sent in response to a received notice. |
| `supporting` | Any supporting annexure, acknowledgement, email, proof of service, ledger, or reference document. |

Related documents are stored as notice attachments with
`notice_parent_attachment_id` pointing to the primary notice.

### 4.5 Reply Status

Reply status is computed by the backend for primary received notices.

| Status | When it appears |
|---|---|
| `not_required` | Reply required is false. |
| `reply_pending` | Reply is required but no due date is set and no reply has been sent. |
| `reply_due_in_days` | Reply is required, due date is in the future, and no reply has been sent. |
| `reply_due_today` | Reply due date is today and no reply has been sent. |
| `reply_overdue` | Reply due date has passed and no reply has been sent. |
| `reply_sent` | Reply has been marked sent or a reply document has been uploaded. |

The page displays user-friendly labels such as `Reply Overdue`, `Reply Due
Today`, and `Reply Sent`.

## 5. End-User Guide

### 5.0 Create Or Manage A Company-Wide Notice

Use the main-navigation `Notices` page when the notice is not yet tied to a
matter or spans several matters.

1. Select `New notice`.
2. Choose `Received` or `Sent` and complete the structured metadata. The form
   supports type, mode, authority/source, department, owner, dates, reply
   state, summary, response, remarks, internal SPOC/remarks, counsel, currency,
   and the applicable amount fields.
3. Search the complete accessible matter directory and select zero, one, or
   several matters. The picker follows pagination; it is not limited to the
   first 100 matters.
4. Optionally select a primary file and save.

To correct metadata or matter relationships later, select `Manage details &
links` on the global row, add or remove matter checkboxes, and select `Save
changes`. A linked global notice then appears in each selected matter's
`Notices` workspace as a `Global notice` reference. Manage the source record in
the global register.

Owner assignment follows the Notice permission model. `documents:manage`
loads the active tenant member choices from the Notice-scoped owner endpoint;
it does not probe the employee-administration API or require
`company:manage_users`. An upload-only user can leave a new notice unassigned or
self-assign, but cannot assign another member. For users without
`documents:manage`, the owner filter explicitly identifies that its choices are
limited to the current user and owners present in loaded results; selecting
`All owners` still applies no owner restriction on the server.

The register is cursor paginated. Select `Load more notices` to append the next
server-filtered page; the API never returns an unbounded tenant-wide result in
one response. Status is a free-form exact-value filter with suggestions, so
workspace-specific statuses are not restricted to a hard-coded dropdown.

### 5.1 Notice Dashboards

The global register uses only server-authoritative counters:

| Counter | Meaning |
|---|---|
| Received | Total received notices visible to the user. |
| Sent | Total sent notices visible to the user. |
| Matching results | Exact server total for the active direction and filters. |
| Rows loaded | Rows appended from the current cursor chain. |

Changing direction, query, status, matter, owner, or due-date filters starts a
new cursor chain at page one. Filtering is performed in SQL, not against only
the rows already loaded in the browser.

The reverse-reference section on a matter walks every opaque notice cursor for
that `matter_id`, deduplicates records by ID, and stops safely if an API ever
repeats a cursor. It therefore does not omit linked standalone notices after
the first 100 records.

At the top of the matter Notices page, users see four workflow counters:

| Counter | Meaning |
|---|---|
| Pending replies | Received notices where a reply is still expected. |
| Overdue replies | Received notices past the reply due date with no reply sent. |
| Due today | Received notices whose reply deadline is today. |
| Due this week | Received notices due in the next seven days. |

These counters use only primary received notices. Sent notices are not counted in
reply deadline counters.

### 5.2 Upload A Notice Received

Use this workflow when a notice has been received and needs to be logged against
a matter.

1. Open the matter.
2. Select `Notices`.
3. Select the `Notice Received` tab.
4. Fill the relevant metadata fields.
5. Click `Upload received notice`.
6. Choose the notice file from your system.
7. Wait for the upload confirmation.

Recommended fields for received notices:

| Field | Purpose |
|---|---|
| Date of receipt | Date the notice was received. Used as the notice document date. |
| Type of notice | Business/legal classification, for example `GST demand`, `Legal demand`, `Recovery notice`. |
| Status | Working status, for example `Open`, `Under review`, `Disputed`, `Closed`. |
| Department / SPOC | Department responsible for the issue. |
| Subject | Short title shown as the main row heading. |
| Authority | Authority, regulator, court, department, or originating authority. |
| Internal SPOC | Person inside the team responsible for coordination. |
| Mode of receiving | Email, registered post, hand delivery, portal, courier, etc. |
| Received from | Sender or source. Also stored as the legacy notice source field for compatibility. |
| Amount | Demand or exposure amount, entered in major currency units. CaseOps stores it in minor units. |
| Reply due date | Date by which reply must be sent. Creates a linked matter deadline if reply is required. |
| Reply required | Leave checked when a reply is required. Uncheck for informational notices. |
| Reply sent | Check only when the reply has already been sent at upload time. |
| Reply sent date | Date of reply if `Reply sent` is checked. Defaults to today if not supplied when marking sent. |
| Response / reply plan | Planned response, strategy, or reply note. |
| Currency | Three-letter currency code. Defaults to `INR`. |
| Summary | Short factual summary of the notice. |
| Remarks | General notes visible on the notice row. |
| Internal remarks | Internal coordination notes. |

Expected result:

- A new row appears in the `Notice Received` list.
- The uploaded file is also visible in the matter `Documents` tab.
- If reply tracking applies, the row shows a reply status badge.
- If reply is required and due date is present, a matter deadline is created or
  updated.
- Reminder offsets display as `7, 3, 1 days before`.

### 5.3 Upload A Notice Sent

Use this workflow when the team sends a notice and wants it tracked under the
matter.

1. Open the matter.
2. Select `Notices`.
3. Select the `Notice Sent` tab.
4. Fill the metadata.
5. Click `Upload sent notice`.
6. Choose the sent notice file.
7. Wait for confirmation.

Recommended fields for sent notices:

| Field | Purpose |
|---|---|
| Notice sent date | Date the outgoing notice was sent. Used as the notice document date. |
| Type of notice | Classification, for example `Recovery notice`, `Demand notice`, `Legal notice`. |
| Status | Dispatch or workflow status, for example `Drafted`, `Dispatched`, `Delivered`, `Closed`. |
| Department / SPOC | Department responsible for sending or tracking. |
| Subject | Main title shown in the list. |
| Authority | Instruction source, recipient authority, or other relevant authority. |
| Internal SPOC | Internal owner. |
| Counsel engaged | External or internal counsel responsible for the notice. |
| Dispute amount | Amount in dispute, stored in minor units. |
| Recovered amount | Amount recovered after or because of the notice. |
| Currency | Three-letter currency code. Defaults to `INR`. |
| Summary | Short summary of why the notice was sent. |
| Remarks | General notes. |
| Internal remarks | Internal coordination notes. |

Expected result:

- A new row appears in the `Notice Sent` tab.
- The row shows `Sent`, status, counsel, sent date, amount, recovered amount,
  and processing status where available.
- The document appears in the matter `Documents` tab.

### 5.4 Add A Reply Document

Use this when a reply has been sent or filed for a received notice.

1. Open the `Notice Received` tab.
2. Find the received notice.
3. Click `Reply document`.
4. Select the reply file.
5. Wait for confirmation.

Expected result:

- The reply file is linked under `Documents and reply history`.
- The primary notice is marked `Reply Sent`.
- The reply sent date is set from the reply document date or upload date.
- The linked reply deadline is marked done.

### 5.5 Mark Reply Sent Without Uploading A Reply File

Use this if the reply was sent outside the system and there is no file ready to
upload yet.

1. Open the `Notice Received` tab.
2. Find the notice.
3. In the reply action area, enter `Reply sent date`.
4. Click `Mark reply sent`.

Expected result:

- The notice changes to `Reply Sent`.
- The linked reply deadline is marked done.
- You can still upload the reply document later as a related document.

### 5.6 Add Supporting Documents

Use `Add document` for annexures, proof of service, acknowledgement receipts,
email trails, account statements, ledger extracts, or any other supporting
material.

1. Find the primary notice row.
2. Click `Add document`.
3. Select the supporting file.
4. Wait for confirmation.

Expected result:

- The file appears under `Documents and reply history`.
- The file is labelled `Supporting`.
- The primary reply status is not automatically changed.

### 5.7 View A Notice Or Related Document

Each notice row has a `View` action. This opens the matter document viewer for
the uploaded file.

Related documents under `Documents and reply history` also have their own `View`
action.

### 5.8 Manage Metadata

For a standalone global record, users with `documents:manage` see `Manage
details & links`. This edits the complete structured record, including the
matter-link set. Status and owner also have fast inline controls, and every
PATCH carries the displayed record version.

For a legacy matter attachment, `Manage` continues to link to the matter
Documents page. Global legacy rows are read-only because the matter attachment
remains their source of truth.

The Notices page is optimized for notice workflow capture and monitoring. The
Documents page remains the general document-management surface.

### 5.9 Search And Filters

The Notices page has one filter block shared by both tabs.

| Filter | Behavior |
|---|---|
| Search | Searches filename, subject, type, authority, source, received-from, summary, response, remarks, status, department, SPOC, internal remarks, and counsel. |
| Status | Filters by notice status values already present in the matter. |
| Reply status | Filters received notices by computed reply status. Disabled for sent notices. |
| Due from / Due to | Filters by reply due date. |
| Authority | Filters by authority text. |
| Matter | Filters against the current matter code and title. Useful for consistent UX with broader matter filters. |
| Department | Filters by department text. |

If no records match, the page shows an empty state. Clear filters to return to
the full list.

## 6. Best Practices For Users

- Enter the `Subject` in a consistent format because it becomes the main list
  heading and deadline title.
- Always enter `Reply due date` for received notices that need a response.
- Keep `Reply required` checked only when a reply is genuinely expected.
- Use `Reply document` for the actual response file, not `Add document`.
- Use `Add document` for annexures, receipts, proof of dispatch, and background
  material.
- Use `Internal remarks` for coordination details that should not be treated as
  the formal reply plan.
- Use a three-letter currency code such as `INR`, `USD`, or `GBP`.
- Keep status values consistent within the team, for example `Open`, `Under
  review`, `Dispatched`, `Closed`.

## 7. Troubleshooting

| Issue | Likely reason | Action |
|---|---|---|
| Upload controls are missing | User lacks `documents:upload`. | Ask an admin to grant upload permission or use a user with the correct role. |
| Manage action is missing | User lacks `documents:manage`. | Use the Documents page with a manager/admin account. |
| Notice appears in Documents but not Notices | Document may not have `document_type = notice`. | Update metadata on the Documents page or re-upload through Notices. |
| Reply status says `No Reply Required` | `Reply required` was unchecked. | Update notice metadata and set reply required if a reply is needed. |
| Reply status is pending but should be sent | Reply was not marked sent and no reply document is linked. | Upload via `Reply document` or use `Mark reply sent`. |
| No deadline was created | Reply required is false or no reply due date was entered. | Set reply required and enter a reply due date. |
| Upload fails | File security, file type, storage quota, auth, or network validation failed. | Check the error toast, file type, and user permissions. |
| Currency is rejected | Currency must be exactly three letters. | Enter a valid code such as `INR`. |

## 8. Implementation Guide

### 8.1 Design Decision

The module intentionally has two source models:

- `company_notices` is the source of truth for standalone/global records. A
  link table provides zero-to-many matter relationships, and the optional
  primary file is stored once on the company notice.
- `matter_attachments` remains the source of truth for the established
  matter-specific primary/reply/supporting-document workflow.

The unified global API presents both models but marks matter attachments as
read-only legacy rows. The matter workspace queries linked standalone notices
by `matter_id` and renders a reverse reference alongside its native attachment
workflow; it does not copy the global record or blob.

### 8.2 Main Code Locations

| Area | File |
|---|---|
| Global notice UI | `apps/web/app/app/notices/page.tsx` |
| Global web API wrapper | `apps/web/lib/api/notices.ts` |
| Notice UI | `apps/web/app/app/matters/[id]/notices/page.tsx` |
| Matter cockpit navigation | `apps/web/components/app/MatterCockpitNav.tsx` |
| Web API endpoint wrapper | `apps/web/lib/api/endpoints.ts` |
| Web workspace types | `apps/web/lib/api/workspace-types.ts` |
| Generated OpenAPI client types | `apps/web/lib/api/openapi-types.ts` |
| API routes | `apps/api/src/caseops_api/api/routes/matters.py` |
| API service logic | `apps/api/src/caseops_api/services/matters.py` |
| DB model | `apps/api/src/caseops_api/db/models.py` |
| API schemas | `apps/api/src/caseops_api/schemas/matters.py` |
| Global API/service/schema | `apps/api/src/caseops_api/api/routes/notices.py`, `apps/api/src/caseops_api/services/notices.py`, `apps/api/src/caseops_api/schemas/notices.py` |
| Global notice migration | `apps/api/alembic/versions/20260715_0001_company_notices.py` |
| Initial notice metadata migration | `apps/api/alembic/versions/20260703_0001_notice_metadata_and_bulk_download.py` |
| Expanded notice workflow migration | `apps/api/alembic/versions/20260706_0001_notice_workflows.py` |
| Local E2E | `tests/e2e/notice-module.spec.ts` |
| Production E2E | `tests/e2e/notice-module-prod.spec.ts` |
| Production Playwright config | `playwright.notice-prod.config.ts` |
| Production verification workflow | `.github/workflows/prod-verify.yml` |

### 8.3 Data Model

Matter-workflow notice fields live on `matter_attachments`. Standalone fields
live on `company_notices`, with matter IDs represented by
`company_notice_matter_links`.

Core fields:

| Field | Purpose |
|---|---|
| `document_type` | Must be `notice` for notice workflow records. |
| `notice_direction` | `received` or `sent`. Defaults to `received` for notice uploads when omitted. |
| `notice_document_role` | `notice`, `reply`, or `supporting`. Defaults to `notice`. |
| `notice_parent_attachment_id` | Links reply/supporting documents to a primary notice. |
| `notice_subject` | Main subject/title. |
| `notice_source` | Legacy/source field used for received-from compatibility. |
| `notice_received_on` | Date a notice was received. |
| `notice_sent_on` | Date an outgoing notice was sent. |
| `notice_reply_due_on` | Reply deadline date. |
| `notice_reply_required` | Whether reply tracking applies. |
| `notice_reply_sent` | Whether the reply has been sent. |
| `notice_reply_sent_on` | Date reply was sent. |
| `notice_reply_deadline_id` | Linked matter deadline id. |
| `notice_reminder_offsets_json` | Reminder offsets, defaulting to `[7, 3, 1]`. |

Operational metadata:

| Field | Purpose |
|---|---|
| `notice_type` | Notice classification. |
| `notice_mode` | Receiving mode. |
| `notice_authority` | Authority, regulator, party, or instruction source. |
| `notice_received_from` | Sender/source for received notices. |
| `notice_summary` | Factual summary. |
| `notice_response` | Response plan or reply note. |
| `notice_remarks` | General remarks. |
| `notice_status` | User-managed workflow status. |
| `notice_department` | Owning department. |
| `notice_internal_spoc` | Internal owner/contact. |
| `notice_internal_remarks` | Internal coordination notes. |
| `notice_counsel_engaged` | Counsel for sent notices. |

Amount fields:

| Field | Purpose |
|---|---|
| `notice_amount_minor` | Demand/exposure amount for received notices, stored in minor units. |
| `notice_dispute_amount_minor` | Dispute amount for sent notices, stored in minor units. |
| `notice_recovered_amount_minor` | Recovered amount for sent notices, stored in minor units. |
| `notice_currency` | Three-letter currency code, default `INR`. |

### 8.4 API Contract

#### Upload notice attachment

Endpoint:

```text
POST /api/matters/{matter_id}/attachments
Content-Type: multipart/form-data
Capability: documents:upload
```

Required:

- `file`

Notice-specific form values are optional, but notice uploads should send:

```text
document_type=notice
notice_direction=received|sent
notice_document_role=notice|reply|supporting
```

Reply and supporting documents must include:

```text
notice_parent_attachment_id={primary_notice_attachment_id}
```

The API validates:

- notice direction is `received` or `sent`
- notice document role is `notice`, `reply`, or `supporting`
- reply/supporting documents have a valid parent primary notice in the same
  matter
- a notice cannot be linked to itself
- currency is exactly three alphabetic characters
- amount fields are non-negative integers in minor units
- uploaded file passes existing file security checks

#### Update notice metadata

Endpoint:

```text
PATCH /api/matters/{matter_id}/attachments/{attachment_id}/metadata
Capability: documents:manage
```

This endpoint updates notice metadata, re-syncs reply deadlines when notice
reply fields change, records activity, and writes an audit event when metadata
changes.

### 8.5 Reply Deadline Sync

The backend creates or updates a `MatterDeadline` when all conditions are true:

- attachment is a notice
- document role is `notice`
- direction is `received`
- `notice_reply_required` is true
- `notice_reply_due_on` is present

Deadline values:

| Deadline field | Value |
|---|---|
| `source` | `notice` |
| `kind` | `reply_due` |
| `title` | `Reply to notice: {subject or filename}` |
| `due_on` | `notice_reply_due_on` |
| `source_ref_type` | `matter_attachment` |
| `source_ref_id` | primary notice attachment id |
| `notes` | Includes reminder offsets. |

Status mapping:

| Notice state | Deadline status |
|---|---|
| Reply sent | `DONE` |
| Reply overdue | `MISSED` |
| Reply pending or due in future | `OPEN` |
| Reply no longer required or due date removed | existing non-final deadline is `CANCELLED` |

### 8.6 Reply Document Side Effect

When a notice attachment is uploaded with:

```text
notice_document_role=reply
notice_parent_attachment_id={primary_notice_id}
```

the service updates the parent primary notice:

- `notice_reply_sent = true`
- `notice_reply_sent_on = reply notice date, document date, or current date`
- linked deadline is re-synced to done

Supporting documents do not mark the reply sent.

### 8.7 Frontend Behavior

The global React page:

- loads the unified register and clearly marks legacy rows read-only
- uses one complete form for create and edit so the supported metadata does not
  diverge between workflows
- walks all matter-list cursors and provides local search in the link picker
- consumes the notice register through opaque cursor pages and exposes a
  `Load more notices` control
- accepts any exact free-form status in the server filter while retaining
  loaded/common values as suggestions
- supports link add/remove after creation
- includes `expected_updated_at` on quick and full-form PATCH requests
- keeps JSON creation and optional file upload as retryable separate steps
- downloads through the shared authenticated binary transport, including the
  same single refresh and one-retry behavior as JSON API requests
- uses the Notice-scoped owner directory for `documents:manage`, without
  requiring employee-admin permission; upload-only creation is limited to
  unassigned or self-assigned ownership, and its partial owner-filter domain is
  disclosed in the UI

The matter React page:

- loads matter workspace data through `useMatterWorkspace`
- filters attachments to `document_type === "notice"`
- shows only primary notices in the main tabs
- groups child reply/supporting documents under their parent notice
- computes dashboard counters from received notices
- displays received and sent workflows in separate tabs
- sends notice uploads through `uploadMatterAttachment`
- marks replies sent through `updateMatterAttachmentMetadata`
- hides upload controls without `documents:upload`
- hides the Manage link without `documents:manage`
- walks all global notice cursors for the current `matter_id`, guards repeated
  cursors, and shows source-record references without duplicating storage

The page resets the upload draft after successful primary upload and invalidates
the matter workspace query so the new notice state is reloaded.

### 8.8 Document Processing And Storage

Notice uploads follow the same storage and processing pipeline as other matter
attachments:

- filename sanitization
- file type and magic-byte validation
- storage quota checks
- document persistence
- virus scan when configured
- initial indexing job enqueue
- matter activity entry
- workspace API exposure

This means notice files participate in the broader document system, including
document viewing and processing status.

### 8.9 Audit And Activity

The module records:

- matter activity when documents are uploaded
- deadline creation audit events when reply deadlines are auto-created
- metadata update audit events when notice metadata is changed

Metadata audit snapshots include notice fields before and after the change.

### 8.10 Testing

Automated coverage includes:

| Test | File | Coverage |
|---|---|---|
| API notice metadata and deadline sync | `apps/api/tests/test_company_profile_and_matters.py` | Upload received notice, create deadline, upload reply, update parent, upload sent notice. |
| Component tests | `apps/web/app/app/matters/[id]/notices/page.test.tsx` | Page rendering, permissions, upload and filtering behavior. |
| Local E2E | `tests/e2e/notice-module.spec.ts` | Full browser workflow for received notice, reply document, sent notice, filters, Documents visibility. |
| Production E2E | `tests/e2e/notice-module-prod.spec.ts` | Same critical workflow on live production using QA Bot workspace. |
| Production verification workflow | `.github/workflows/prod-verify.yml` | Runs existing production suite and notice module production suite. |
| Global register API | `apps/api/tests/test_notices.py` | Unlinked and multi-matter records, filters, assignment, legacy compatibility, file security/quota, roles, tenant and restricted-matter isolation. |
| Global register components | `apps/web/app/app/notices/page.test.tsx`, `apps/web/lib/api/notices.test.ts`, and `apps/web/lib/api/client.test.ts` | Complete metadata create/edit, CAS, paginated matter loading, link correction, permissions, arbitrary exact-status filters, honest owner scope, retryable upload/download authentication, legacy rows, and API contract. |
| Matter reverse-reference component | `apps/web/app/app/matters/[id]/notices/page.test.tsx` | Linked standalone rendering across more than 100 records, repeated-cursor protection, and file action without creating a matter attachment row. |
| July 15 local E2E | `tests/e2e/ram-2026-07-15-bugs.spec.ts` | Main-nav standalone creation, assignment, multi-matter sent notice, actual file byte download, post-create link removal, matter reverse reference, search, and filters. |
| July 15 deployed E2E | `tests/e2e/ram-2026-07-15-prod.spec.ts` | No-mock deployed verification after release. |

Latest verified production run:

```text
https://github.com/mishrasanjeev/caseops/actions/runs/28834193540
```

### 8.11 Known Boundaries

- The global register complements rather than replaces the matter-specific
  reply/supporting-document workflow. Legacy matter rows remain read-only in
  the global surface.
- A standalone notice has one optional primary file. Use the matter workspace
  when reply documents, annexures, or document processing are required.
- Reply reminders are stored and displayed as offsets, but notification delivery
  depends on the broader deadline/reminder infrastructure.
- Standalone metadata and matter links are managed in the global Notice form;
  legacy attachment metadata remains managed in the matter Documents page.
- Sent notices do not currently create reply deadlines.
- Status values are free text; teams should agree on internal conventions.

## 9. Quick Reference

| Need | Use |
|---|---|
| Log a notice before a matter exists | Main navigation `Notices` -> `New notice`; leave matter links empty |
| Link one notice to several matters | Main navigation `Notices` -> select each visible matter during creation |
| Correct matter links later | Global notice row -> `Manage details & links` |
| Search, assign, or track notices company-wide | Main navigation `Notices` |
| Log a notice received from an authority or party | `Notice Received` tab |
| Track a reply deadline | `Reply required` plus `Reply due date` |
| Upload the actual reply | `Reply document` on the received notice row |
| Mark a reply sent without a file | `Reply sent date` plus `Mark reply sent` |
| Add annexures or proof | `Add document` |
| Log an outgoing notice | `Notice Sent` tab |
| Open the file | `View` |
| Manage broader document metadata | `Documents` or `Manage` |
| Find overdue responses | Dashboard `Overdue replies` or reply status filter |
