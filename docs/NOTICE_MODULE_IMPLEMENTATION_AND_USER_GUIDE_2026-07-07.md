# Notice Module Implementation And End-User Usage Guide

Date: 2026-07-07
Status: Implemented and deployed
Primary app location: `/app/matters/{matter_id}/notices`
Related production verification: `.github/workflows/prod-verify.yml`

## 1. Purpose

The Notice module gives each matter a first-class workflow for notices received
from external parties and notices sent by the firm or company. It captures the
notice document and the operational metadata needed to track response ownership,
reply deadlines, reply status, amounts, departments, counsel, and supporting
documents.

The module is matter-scoped. Users work inside a specific matter and see only
the notices attached to that matter.

## 2. Where To Find It

Open any matter and select the `Notices` tab in the matter cockpit.

Typical path:

1. Sign in to CaseOps.
2. Open `Matters`.
3. Select a matter.
4. Select `Notices` from the matter navigation.

Direct URL pattern:

```text
/app/matters/{matter_id}/notices
```

The Notices page also links back to the matter `Documents` page. Notice files
are still normal matter documents, so they are visible from both places.

## 3. Permissions

The module uses the existing document permissions.

| Capability | What it allows in the Notice module |
|---|---|
| `documents:upload` | Upload received notices, sent notices, reply documents, and supporting documents. |
| `documents:manage` | Open the management surface for the document metadata through the Documents page. |
| Matter access | View notices only for matters the user can access. |

If a user can view a matter but does not have `documents:upload`, the Notices
page remains visible but upload controls are hidden.

## 4. Key Concepts

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

### 5.1 Notice Dashboard

At the top of the Notices page, users see four counters:

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

Users with `documents:manage` see a `Manage` action that links to the Documents
page. Use the Documents page for broader document metadata management.

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

The Notice module uses `matter_attachments` as the source of truth. A notice is
not stored in a separate notice table. This keeps Notices, Documents, workspace
APIs, storage governance, document processing, downloads, and audit activity on
one shared document model.

### 8.2 Main Code Locations

| Area | File |
|---|---|
| Notice UI | `apps/web/app/app/matters/[id]/notices/page.tsx` |
| Matter cockpit navigation | `apps/web/components/app/MatterCockpitNav.tsx` |
| Web API endpoint wrapper | `apps/web/lib/api/endpoints.ts` |
| Web workspace types | `apps/web/lib/api/workspace-types.ts` |
| Generated OpenAPI client types | `apps/web/lib/api/openapi-types.ts` |
| API routes | `apps/api/src/caseops_api/api/routes/matters.py` |
| API service logic | `apps/api/src/caseops_api/services/matters.py` |
| DB model | `apps/api/src/caseops_api/db/models.py` |
| API schemas | `apps/api/src/caseops_api/schemas/matters.py` |
| Initial notice metadata migration | `apps/api/alembic/versions/20260703_0001_notice_metadata_and_bulk_download.py` |
| Expanded notice workflow migration | `apps/api/alembic/versions/20260706_0001_notice_workflows.py` |
| Local E2E | `tests/e2e/notice-module.spec.ts` |
| Production E2E | `tests/e2e/notice-module-prod.spec.ts` |
| Production Playwright config | `playwright.notice-prod.config.ts` |
| Production verification workflow | `.github/workflows/prod-verify.yml` |

### 8.3 Data Model

Notice fields live on `matter_attachments`.

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

The React page:

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

Latest verified production run:

```text
https://github.com/mishrasanjeev/caseops/actions/runs/28834193540
```

### 8.11 Known Boundaries

- The module is matter-scoped. It does not currently provide a global notice
  dashboard across all matters.
- Reply reminders are stored and displayed as offsets, but notification delivery
  depends on the broader deadline/reminder infrastructure.
- The Notices page is optimized for capture and monitoring; advanced metadata
  management remains on the Documents page.
- Sent notices do not currently create reply deadlines.
- Status values are free text; teams should agree on internal conventions.

## 9. Quick Reference

| Need | Use |
|---|---|
| Log a notice received from an authority or party | `Notice Received` tab |
| Track a reply deadline | `Reply required` plus `Reply due date` |
| Upload the actual reply | `Reply document` on the received notice row |
| Mark a reply sent without a file | `Reply sent date` plus `Mark reply sent` |
| Add annexures or proof | `Add document` |
| Log an outgoing notice | `Notice Sent` tab |
| Open the file | `View` |
| Manage broader document metadata | `Documents` or `Manage` |
| Find overdue responses | Dashboard `Overdue replies` or reply status filter |

