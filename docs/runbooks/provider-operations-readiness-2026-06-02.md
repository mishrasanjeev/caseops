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
```

Backend endpoints:

```text
GET /api/admin/provider-operations/readiness
GET /api/admin/provider-operations/jobs
POST /api/admin/provider-operations/jobs/{operation_id}/replay
POST /api/admin/provider-operations/jobs/{operation_id}/ignore
POST /api/admin/provider-operations/jobs/{operation_id}/mark-resolved
```

The readiness response reports config names and approval keys only. It must not
return credential values.

## ADP-21 Google Drive

Current state:

- Names-only readiness status is available.
- Manual bounded dry-run remains available through existing Drive import routes.
- Durable Drive sync, OAuth token storage, webhook ingestion, background
  polling, file-content fetches, and commit execution remain disabled.

Required before durable sync:

- Google Drive client id, client secret, and redirect URI stored as secret/env
  references.
- Tenant admin approval for durable Drive sync.
- Change detection fields approved: provider file id, version, content hash,
  modified time.
- Review queue policy approved for updated, deleted, and duplicate files.
- Retry/dead-letter/replay mapping approved before provider calls run.

## ADP-22 Mailbox Connector

Current state:

- Names-only readiness status is available.
- Manual imported-email metadata and email invitation candidates remain
  review-first.
- Durable mailbox polling/webhook ingestion and automatic matter mutation are
  disabled.

Required before durable mailbox ingestion:

- Provider type, client id, client secret, webhook signing secret, registered
  webhook URL, and scopes supplied through secret/env references.
- Message idempotency keys approved: provider message id, thread id, internet
  message id, and header ids.
- Thread grouping and matter-association candidate policy approved.
- Intake routing review queue approved.
- Redaction policy approved for errors, snippets, attachments, and audit.

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

