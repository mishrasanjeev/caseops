# ADP-20 Outlook Provider Readiness Gate

Status: **NO-GO** as of 2026-05-26.

This is a provider-readiness checklist for ADP-20 durable Outlook sync. It does
not approve provider use, does not authorize implementation, and must not carry
credential values, tenant identifiers, OAuth tokens, redirect URI values,
Temporal endpoint values, DB URLs, private keys, or local env values.

## Baseline

- WTD-5.1c live Temporal operator proof: complete.
- WTD-5.3 durable notification delivery/retry foundation: merged in
  `6c892171bf4df6d0aa67306941d0380d38a62b1b`.
- ADP-20 durable Outlook sync: not started.
- Current safe sync behavior: bounded manual Outlook sync only.

## Explicit Non-Goals For This Gate

- Do not implement durable Outlook sync.
- Do not add schedulers, polling, mailbox sync, provider webhooks, Google Drive
  sync, corpus jobs, OCR/document-processing jobs, or feature workers.
- Do not change external notification delivery behavior.

## Config Names And Current Status

The active inspected configuration reported names/status only:

| Requirement | Status |
| --- | --- |
| `OUTLOOK_CLIENT_ID` | Missing in active inspected config |
| `OUTLOOK_CLIENT_SECRET` | Missing in active inspected config |
| `OUTLOOK_REDIRECT_URI` | Missing in active inspected config |
| `OUTLOOK_TENANT_ID` or approved tenant mode | Tenant mode exists in code, approval evidence missing |
| Approved OAuth consent model | Missing |
| Approved scopes | Missing approval evidence |
| Operator runbook for durable sync/retry/dead-letter/replay | Missing |
| Rollback/disable procedure | Missing |
| Provider error redaction rules for ADP-20 | Missing approval evidence |

The bounded manual Outlook flow currently requests these scope names:

- `offline_access`
- `User.Read`
- `Calendars.ReadWrite`

These scope names are not approval evidence. Security/compliance approval must
explicitly accept the consent model and scope set before ADP-20 can begin.

## Required Approval Evidence Before GO

ADP-20 remains blocked until all items below have an approved evidence record:

| Item | Required evidence | Current status |
| --- | --- | --- |
| Outlook app registration | Operator-owned registration recorded outside the repo | Missing |
| Consent model | Tenant-admin consent or per-user OAuth explicitly selected | Missing |
| OAuth scopes | Approved scope list and justification | Missing |
| Runtime config | Approved secret/config wiring for required names | Missing |
| Token storage policy | Encryption, retention, revocation, and audit policy approved | Missing |
| Durable workflow operation | Retry, dead-letter, replay, and monitoring runbook approved | Missing |
| Disable/rollback | Operator procedure for stopping durable sync safely | Missing |
| Provider error redaction | Redaction rules for Graph/OAuth errors approved | Missing |

## Runbook Draft Requirements

The final ADP-20 runbook must include:

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

## GO Criteria

The ADP-20 implementation prompt may be used only after:

- every row in the approval evidence table is marked approved;
- required config names are present in the target operator environment;
- scope and consent decisions are approved;
- the durable sync/retry/dead-letter/replay runbook is approved;
- rollback/disable steps are rehearsed or explicitly accepted by operations;
- no credential values are committed or exposed in logs, docs, PR bodies, tests,
  or audit metadata.

Until then, the readiness verdict is **NO-GO** and bounded manual Outlook sync
remains the only Outlook sync path.
