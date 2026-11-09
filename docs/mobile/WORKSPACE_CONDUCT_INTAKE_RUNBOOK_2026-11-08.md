# CaseOps workspace conduct intake

A native report returns a receipt with `status: received`. Receiving a report
does not notify the target, copy Matter records, send email, or change access.

- The authenticated workspace owner can inspect their tenant's ordinary reports
  at `GET /api/admin/workspace-conduct/reports`. The MFA-gated publisher can
  inspect escalations at `GET /api/platform-admin/workspace-conduct-reports`.
  Both accept `limit` (1–50) and the prior response's `next_cursor` as `after`.
- Reports about owners or administrators route to the publisher. An operator
  cannot see a report targeting their own user identity. Reports targeting the
  sole publisher operator require an independent operator path before the
  reporting process can promise a response in that case.
- Treat the receipt and reason as confidential. Use only the permissions you
  already hold to investigate. An intake response has no source record link and
  grants no Matter access. Preserve legal holds and retention obligations.
- If authorized and appropriate, deactivate a non-owner through the existing
  workspace user control. If assignments block direct deactivation, preview
  offboarding and use its approved reassignment process. The receipt remains
  an intake record; successful action is recorded through the existing
  workspace audit mechanism. The report itself never deactivates a user.

Before declaring store readiness, exercise the deployed intake and designate
the responsible operators and response process. Restore-forward both receipt
migrations on schema problems. Destructive downgrade is refused.
