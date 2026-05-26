# ADP-20 Outlook Provider Readiness Gate

Status: **ADMIN-CONFIGURABLE / IMPLEMENTATION-UNBLOCKED** as of 2026-05-26.

This is the provider-readiness runbook for ADP-20 durable Outlook sync. The
law firm workspace admin now owns the Outlook setup path through
`/app/admin/outlook`: they can enter approved Microsoft Graph OAuth config,
record the approval checklist, connect an admin Outlook account, and run the
end-to-end readiness probe. This document must not carry credential values,
tenant identifiers, OAuth tokens, redirect URI values, Temporal endpoint values,
DB URLs, private keys, or local env values.

## Baseline

- WTD-5.1c live Temporal operator proof: complete.
- WTD-5.3 durable notification delivery/retry foundation: merged in
  `6c892171bf4df6d0aa67306941d0380d38a62b1b`.
- ADP-20 durable Outlook sync: not started.
- Current safe sync behavior: bounded manual Outlook sync only.
- Admin readiness UI/API: implemented for tenant-scoped Outlook configuration,
  approval capture, encrypted client-secret storage, and Graph connection probe.

## Explicit Non-Goals For This Gate

- Do not implement durable Outlook sync.
- Do not add schedulers, polling, mailbox sync, provider webhooks, Google Drive
  sync, corpus jobs, OCR/document-processing jobs, or feature workers.
- Do not change external notification delivery behavior.

## Config Names And Admin Setup Status

The admin page reports names/status only. Credential values are accepted by the
API but are never echoed back.

| Requirement | Status |
| --- | --- |
| `OUTLOOK_CLIENT_ID` | Configured by law firm admin in `/app/admin/outlook` |
| `OUTLOOK_CLIENT_SECRET` | Configured by law firm admin; stored encrypted, never displayed |
| `OUTLOOK_REDIRECT_URI` | Configured by law firm admin in `/app/admin/outlook` |
| `OUTLOOK_TENANT_ID` or approved tenant mode | Configured by law firm admin in `/app/admin/outlook` |
| Approved OAuth consent model | Captured by law firm admin checklist |
| Approved scopes | Captured by law firm admin checklist |
| Durable sync/retry/dead-letter/replay runbook | Captured by law firm admin checklist |
| Rollback/disable procedure | Captured by law firm admin checklist |
| Provider error redaction rules for ADP-20 | Captured by law firm admin checklist |

The bounded manual Outlook flow currently requests these scope names:

- `offline_access`
- `User.Read`
- `Calendars.ReadWrite`

These scope names are not approval evidence by themselves. The law firm admin
must explicitly approve the consent model and scope set on the Outlook
configuration page before a tenant reports `ready_for_adp20_implementation`.

## Required Approval Evidence Before GO

ADP-20 implementation is unblocked by the admin-controlled readiness path. A
specific tenant remains blocked until all items below are approved in
`/app/admin/outlook` and the end-to-end test passes:

| Item | Required evidence | Current status |
| --- | --- | --- |
| Outlook app registration | Law firm admin supplies approved Entra app values | Admin page available |
| Consent model | Tenant-admin consent or per-user OAuth explicitly selected | Admin checklist available |
| OAuth scopes | Approved scope list and justification | Admin checklist available |
| Runtime config | Approved secret/config wiring for required names | Admin page available |
| Token storage policy | Encryption, retention, revocation, and audit policy approved | Admin checklist available |
| Durable workflow operation | Retry, dead-letter, replay, and monitoring runbook approved | Admin checklist available |
| Disable/rollback | Operator procedure for stopping durable sync safely | Admin checklist available |
| Provider error redaction | Redaction rules for Graph/OAuth errors approved | Admin checklist available |

## Admin Setup Flow

1. Open `/app/admin/outlook` as a workspace owner or admin.
2. Enter the approved Entra application client ID, client secret, tenant mode
   or tenant ID, and redirect URI.
3. Confirm the approved scope list: `offline_access`, `User.Read`,
   `Calendars.ReadWrite`.
4. Mark the OAuth consent, scope, durable operation, rollback/disable, and
   redaction approvals.
5. Save the configuration. The response shows names/status only.
6. Connect an admin Outlook account through the OAuth flow.
7. Run the end-to-end readiness test. It must report
   `ready_for_adp20_implementation` before durable sync work is enabled for the
   tenant.

## ADP-20 Implementation Runbook Requirements

The ADP-20 implementation runbook must still include:

1. Preflight command sequence that reports config names/status only.
2. Temporal worker readiness check using redacted status output only.
3. Approved OAuth consent model and scope names.
4. Secret/config wiring inventory by config name only.
5. Token storage and revocation procedure.
6. Bounded retry and dead-letter policy.
7. Admin replay rules and audit fields.
8. Provider error redaction rules before DB/API/audit/UI persistence.
9. Disable and rollback procedure that leaves bounded manual sync available.
10. Post-deploy verification and incident escalation owner.

## GO Criteria For A Tenant

The ADP-20 implementation prompt may be used for tenants whose admin readiness
page shows:

- required config names present;
- every approval checklist item approved;
- an admin Outlook account connected;
- the end-to-end Graph readiness probe passed;
- `adp20_readiness=ready_for_adp20_implementation`;
- no credential values are committed or exposed in logs, docs, PR bodies, tests,
  or audit metadata.

Until durable Outlook sync is separately implemented, bounded manual Outlook
sync remains the only Outlook sync path.
