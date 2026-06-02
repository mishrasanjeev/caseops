# Future Workplan - 2026-05-14

Scope: live remaining work only. This file must not duplicate closed release,
product, or enterprise evidence from the strict ledgers.

## Carry-Forward Caveats

- Staging proof is still missing. The staging deploy path remains a
  credential-gated no-op until staging GCP Workload Identity and secrets are
  configured and runtime proof is captured.
- The production release signoff for SHA
  `05b3025d63a10a86eb30a1637f4bc9625bb33a65` stays in
  `docs/RELEASE_SIGNOFF_2026-05-14.md`; preserve it when doing future work.
- Do not run corpus ingest, backfill, or embedding jobs as part of these
  milestones unless a later prompt explicitly authorizes that scope.
- Billing/pricing/platform-admin code is deployed. Manual production billing
  signoff remains pending, and Pine Labs production payments must remain
  disabled until UAT and founder go/no-go pass.

## Ordered Milestones

1. **Staging proof**
   - Configure staging Workload Identity and required staging secrets.
   - Run the staging deploy path and capture runtime proof for API and Web.
   - Leave production release evidence untouched except for an explicit new
     signoff task.

2. **`G-116` inbound email ingest**
   - manual inbound email import foundation is in progress for matter
     communications: explicit matter selection, tenant/matter access gates,
     provider-message idempotency, redacted audit, and attachment storage via
     the existing matter attachment pipeline.
   - Remaining before closing `WTD-12.3b` / `PG-106`: provider/webhook or
     admin-triggered mailbox connector, thread grouping, intake routing, and
     end-to-end runtime proof.

3. **`WTD-7.2` tasks/deadlines**
   - The matter-cockpit Tasks/Deadlines foundation is implemented: users can
     create, list, complete, and reopen matter-scoped tasks/deadlines, with
     generated proceeding-intelligence lineage preserved.
   - Remaining before full closure: admin task templates per practice area
     remain missing.

4. **Durable notifications / Temporal**
   - `WTD-5.1a` durable workflow foundation is implemented for notifications:
     disabled-by-default config health, a safe worker check entrypoint, and a
     no-op notification-intent probe with redacted audit metadata.
   - `WTD-5.1b` Temporal runtime foundation is implemented for notifications:
     the real Python Temporal SDK dependency is declared, client and worker
     construction is redacted, a no-op runtime-proof workflow/activity exists,
     and retry policy, timeouts, task queue, and version metadata are explicit.
   - `WTD-5.1c` operator runtime proof is complete against the
     operator-owned Mumbai Temporal backend.
   - `WTD-5.3` durable notification delivery/retry foundation is implemented:
     in-app delivery uses durable intents with idempotency, retry, and
     dead-letter metadata; email/SMS/WhatsApp remain fail-closed with no
     provider calls. ADP-20 durable Outlook sync foundation is implemented for
     readiness-gated CaseOps-to-Outlook hearing sync only, with retry,
     dead-letter, and tenant-scoped admin replay. Task/deadline, mailbox,
     webhook, Outlook-to-CaseOps, and Google Drive sync remain future work.
   - ADP-24 provider operations foundation is implemented: tenant admins can
     list failed/blocked/dead-letter provider jobs, see redacted errors, and
     request audited replay/ignore/resolve actions without immediate provider
     calls.
   - ADP-21 Google Drive durable sync, ADP-22 durable mailbox ingestion, and
     ADP-23 external digest delivery remain pending. Current readiness status
     is names-only under `/app/admin/provider-operations`.

5. **AI eval harness**
   - `WTD-11.4` now has a deterministic offline fixture foundation for
     source grounding, refusal behavior, prompt-injection handling, and
     unsafe wording detection.
   - Complete `WTD-11.4` with broader per-workflow goldens and CI gating for
     model or prompt changes.
   - Cover citation validity, statute confusion, fact fabrication, required
     section coverage, formatting compliance, and adverse-treatment detection.
