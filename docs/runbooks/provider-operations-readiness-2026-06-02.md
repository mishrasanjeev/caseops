# Provider Operations Readiness Runbook - 2026-06-02

**Scope:** ADP-21 Google Drive readiness, ADP-22 mailbox connector readiness,
ADP-23 digest delivery readiness, and ADP-24 provider retry/dead-letter/replay
operations.

**Hard rules:**

- Do not write provider credentials, webhook secrets, OAuth tokens, raw email
  bodies, raw Drive file contents, or raw provider payloads into this repo.
- Do not enable autonomous Google Drive sync, mailbox polling, provider
  webhooks, or external digest delivery without explicit tenant/provider
  readiness approval.
- Keep all external provider calls fail-closed when config/readiness is missing.

## Admin Surface

Tenant workspace admins can use:

```text
/app/admin/provider-operations
/app/admin/integrations
```

Backend endpoints:

```text
GET /api/admin/provider-operations/readiness
GET /api/admin/provider-operations/jobs
POST /api/admin/provider-operations/jobs/{operation_id}/replay
POST /api/admin/provider-operations/jobs/{operation_id}/ignore
POST /api/admin/provider-operations/jobs/{operation_id}/mark-resolved
GET /api/admin/integrations
POST /api/calendar/connections/google-calendar/start
GET /api/calendar/connections/google-calendar/callback
POST /api/calendar/sync/google-calendar/hearings/{hearing_id}
POST /api/calendar/sync/google-calendar/tasks/{task_id}
POST /api/calendar/sync/google-calendar/deadlines/{deadline_id}
POST /api/calendar/sync/google-calendar
POST /api/admin/google-calendar-sync/replay
GET /api/mailbox/gmail/status
POST /api/mailbox/gmail/start
GET /api/mailbox/gmail/callback
DELETE /api/mailbox/connections/{connection_id}
POST /api/mailbox/gmail/import
POST /api/mailbox/gmail/watch
POST /api/mailbox/gmail/webhook
GET /api/mailbox/imports
GET /api/mailbox/attachment-candidates
PATCH /api/mailbox/attachment-candidates/{candidate_id}
GET /api/case-tracking/support-matrix
GET /api/platform-admin/case-tracking/support-matrix
POST /api/platform-admin/case-tracking/support-matrix
PATCH /api/platform-admin/case-tracking/support-matrix/{row_id}
```

`/app/admin/integrations` is the tenant-safe connector registry. It shows
connector keys, names, categories, providers, status, safe config names, scopes,
webhook status, runbook links, and provider-operations links. It must not show
secrets, OAuth tokens, raw provider payloads, internal provider costs, gross
profit, gross margin, or platform-only notes.

The readiness response reports config names and approval keys only. It must not
return credential values.

Mutation endpoints require an operator reason between 8 and 500 characters.
The reason is used only to record whether a reason was supplied in audit
metadata; raw reason text is not exposed in provider-operation list responses.

## Case Tracking Provider Matrix

Founder/platform admins manage the internal support matrix at
`/app/platform-admin/paid-production` and
`GET/POST/PATCH /api/platform-admin/case-tracking/support-matrix`.

Required internal fields:

- provider
- court
- bench/jurisdiction
- lookup method
- refresh cost
- bulk refresh cost
- rate limit
- freshness SLA
- legal/ToS status
- failure-code mapping
- enabled/disabled status
- tenant visibility
- evidence/source reference

Tenant users see only the tenant-safe matrix through
`GET /api/case-tracking/support-matrix` and the case tracking page before they
track a case. Tenant responses must not include refresh cost, bulk refresh
cost, internal evidence references, margins, provider fees, or founder notes.

Manual checks:

- A disabled support-matrix row blocks new tracking/bookmark creation for that
  court/provider.
- Empty matrix remains backward-compatible for existing disabled/mock setups.
- Supported rows show tenant-safe court/provider/method/rate/freshness/status
  information only.
- Case-refresh usage remains quota/credit-gated; heavy refresh use must not
  silently bypass plan limits or top-up requirements.
- Do not add captcha/session-gated court scraping. Use only approved provider,
  API, or manual workflows.

Stable provider-operation fields:

- `job_kind`: `calendar_sync`, `notification_delivery`,
  `mailbox_message_import`, or `mailbox_webhook`
- `operator_state`: `open`, `ignored`, or `resolved`
- Calendar statuses: `failed`, `retry_scheduled`, `dead_letter`, `pending`,
  `synced`, `deleted`
- Notification statuses: `blocked`, `retry_scheduled`, `dead_letter`,
  `queued`, `delivered`
- `replay_available`, `ignore_available`, and `mark_resolved_available`
  determine which UI actions should be enabled.

## BUG-053 Google Calendar V1

Current state:

- Google Calendar is a first-class calendar provider alongside Outlook.
- Tenant users with `calendar:sync` can connect Google Calendar only when
  `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET`, and
  `GOOGLE_CALENDAR_REDIRECT_URI` are configured.
- Missing Google Calendar config shows a disabled/fail-closed connector on
  `/app/calendar` and `/app/admin/integrations`; no provider call is attempted.
- OAuth tokens are encrypted in `UserCalendarConnection.encrypted_token_ref`.
- Manual single-hearing, task, deadline, and bounded visible-range sync can
  create/update Google Calendar events for `matter_hearing`, `task`, and
  `deadline` source records.
- Manual Google event delete is available for a previously synced hearing via
  `DELETE /api/calendar/sync/google-calendar/hearings/{hearing_id}`; repeated
  delete is idempotent once the sync row is marked `deleted`.
- Cancelling a hearing clears or recomputes `Matter.next_hearing_on`, cancels
  hearing reminders, removes the hearing from upcoming calendar lists, and
  auto-deletes the synced Google Calendar event when one exists.
- `POST /api/admin/google-calendar-sync/replay` lets tenant admins replay
  tenant-scoped pending/failed Google Calendar sync rows through the same
  fail-closed provider checks.
- Short-lived Google Workspace UAT setup is documented in
  `docs/runbooks/google-workspace-gcp-uat-setup-2026-06-08.md`.
- Provider-operation rows and action audits preserve provider
  `google_calendar`.
- Google-to-CaseOps imports, Google Calendar provider webhooks, always-on
  background automation, and Drive sync remain outside BUG-053. Gmail mailbox
  V1 is tracked under ADP-22 below.

Manual smoke checklist:

- With Google config absent, `POST /api/calendar/connections/google-calendar/start`
  returns `provider_available=false`, config names only, and no auth URL.
- With a local/mock provider, OAuth start/callback returns a Google connection
  and the response text contains no `access_token`, `refresh_token`, or raw
  OAuth payload.
- `POST /api/calendar/sync/google-calendar/hearings/{hearing_id}` is
  idempotent: the second call updates the existing `CalendarEventSync` row and
  reuses the stored provider event id.
- `DELETE /api/calendar/sync/google-calendar/hearings/{hearing_id}` marks the
  sync row `deleted` and does not call the provider again on repeated delete.
- `POST /api/calendar/sync/google-calendar/tasks/{task_id}` and
  `POST /api/calendar/sync/google-calendar/deadlines/{deadline_id}` create or
  update provider events without exposing provider event payloads in responses.
- Updating a hearing to `cancelled` removes it from upcoming views, leaves it
  in cancelled history, clears/recomputes `Matter.next_hearing_on`, cancels
  reminders, and deletes any previously synced provider event idempotently.
- `POST /api/calendar/sync/google-calendar` rejects ranges over 92 days and
  filters by tenant, visible matters, and optional `matter_id`.
- `POST /api/admin/google-calendar-sync/replay` only replays rows visible to
  the tenant and keeps missing-config behavior blocked without provider calls.
- A failed Google Calendar sync appears under `/app/admin/provider-operations`
  as provider `google_calendar`; redacted output must not contain bearer tokens,
  email addresses, Google URLs, OAuth tokens, raw provider payloads, or operator
  reason text.
- `/app/calendar` must show loading, fail-closed missing-config, connected,
  sync success, revoke success, and error states without exposing secrets.

## ADP-21 Google Drive

Current state:

- Names-only readiness status is available.
- Per-user Google Drive OAuth is available behind fail-closed configuration
  checks.
- Tenant users with document upload access can start Drive OAuth, store encrypted
  token material, list recent file metadata, and revoke their own connection.
- Drive user APIs are:
  `GET /api/drive/google/status`, `POST /api/drive/google/start`,
  `GET /api/drive/google/callback`, `GET /api/drive/google/files`, and
  `DELETE /api/drive/connections/{connection_id}`.
- `/app/matters/{matter_id}/documents` shows a compact Google Drive panel for
  document uploaders. `/app/admin/integrations` shows the same tenant-safe Drive
  readiness and connection controls for workspace admins.
- Manual bounded dry-run remains available through existing Drive import routes.
- Durable Drive sync, webhook ingestion, background polling, file-content
  fetches, folder mapping, and commit execution remain disabled.

Required before durable sync:

- Google Drive client id, client secret, and redirect URI stored as secret/env
  references.
- Tenant admin approval for durable Drive sync.
- Change detection fields approved: provider file id, version, content hash,
  modified time.
- Review queue policy approved for updated, deleted, and duplicate files.
- Retry/dead-letter/replay mapping approved before provider calls run.
- Use `docs/runbooks/google-workspace-gcp-uat-setup-2026-06-08.md` for the
  shared Google Auth Platform/Pub/Sub UAT foundation; Drive commit remains
  disabled until a separate Drive product slice is approved.

Manual Google Drive smoke checklist:

- With Drive config absent, `GET /api/drive/google/status` reports
  `configured=false` and safe config names only.
- OAuth callback stores a per-user connection without returning `access_token`,
  `refresh_token`, encrypted token material, or raw provider payloads.
- `GET /api/drive/google/files` returns recent metadata only: file id, name,
  MIME type, size, modified time, and safe web URL. It must not download file
  bytes or create matter attachments.
- Tenant A cannot list or revoke Tenant B's Drive connection.
- `/app/matters/{matter_id}/documents` must show loading, blocked,
  connected/list, revoke, error, and empty-result states without exposing
  secrets or provider raw payloads.

## ADP-22 Mailbox Connector

Current state:

- Gmail mailbox V1 is available behind fail-closed configuration checks.
- Tenant users can start Gmail OAuth only when `GMAIL_CLIENT_ID`,
  `GMAIL_CLIENT_SECRET`, and `GMAIL_REDIRECT_URI` are configured.
- OAuth tokens are encrypted in `UserMailboxConnection.encrypted_token_ref`.
- `POST /api/mailbox/gmail/import` imports Gmail message metadata/snippets only.
  It stores hashed provider ids, safe headers, message timestamps, and small
  snippets; it does not store raw email bodies in product responses.
- Matter matching is review-first and based on visible matter codes. Attachment
  candidates are created for review and approval before document import.
- `POST /api/mailbox/gmail/watch` and `POST /api/mailbox/gmail/webhook` support
  Gmail Pub/Sub watch/webhook foundations with verification-token checking,
  idempotency, raw-payload hashing, and no raw payload exposure.
- Provider-operation rows support `mailbox_message_import` and
  `mailbox_webhook`, with redacted error/output fields.
- Microsoft 365 mailbox ingestion, durable autonomous polling, raw body storage,
  and automatic document mutation remain disabled.

Required before durable mailbox ingestion:

- Provider type, client id, client secret, webhook signing secret, registered
  webhook URL, and scopes supplied through secret/env references.
- Message idempotency keys approved: provider message id, thread id, internet
  message id, and header ids.
- Thread grouping and matter-association candidate policy approved.
- Intake routing review queue approved.
- Redaction policy approved for errors, snippets, attachments, and audit.

Manual Gmail smoke checklist:

- Follow `docs/runbooks/google-workspace-gcp-uat-setup-2026-06-08.md` for the
  short-lived GCP API/Pub/Sub/OAuth setup and cleanup manifest.
- With Gmail config absent, `GET /api/mailbox/gmail/status` reports
  `provider_available=false` and safe config names only.
- OAuth callback stores a connection without returning `access_token`,
  `refresh_token`, encrypted token material, or raw provider payloads.
- Recent import creates idempotent message rows and review-first attachment
  candidates without exposing raw bodies or attachment bytes.
- Tenant A cannot see Tenant B mailbox imports or attachment candidates.
- The webhook endpoint rejects a bad verification token and deduplicates repeat
  Pub/Sub events by provider message id.

## ADP-23 Digests

Current state:

- Judgment and legal-update digest previews are in-app only.
- External email/SMS/WhatsApp delivery is disabled.
- Notification delivery intents provide retry/dead-letter foundations where
  persisted delivery jobs exist.

Required before external delivery:

- Provider-specific delivery credentials stored as secret/env references.
- Sender identity, webhook verification, unsubscribe/suppression, bounce, and
  complaint handling approved.
- Digest preferences and recipient policy approved.
- UAT evidence for duplicate, failed, unsubscribed, and suppressed recipients.

## ADP-24 Provider Operations

Current state:

- Workspace admins can list tenant-scoped failed, blocked, and dead-letter
  provider jobs.
- Error display is redacted.
- Replay, ignore, and mark-resolved actions are audited.
- Replay reschedules existing idempotent rows. It does not create duplicate
  delivery intents, duplicate calendar sync records, or immediate provider
  calls.

Manual checks:

- Non-admin users receive 403 for provider operations endpoints.
- Tenant A cannot see Tenant B operations.
- Redacted errors do not contain email addresses, bearer tokens, URLs, webhook
  signatures, OAuth tokens, or raw payloads.
- External delivery replay remains blocked while provider config/approval is
  missing.
- Audit export shows provider operation actions with redacted ids only.
