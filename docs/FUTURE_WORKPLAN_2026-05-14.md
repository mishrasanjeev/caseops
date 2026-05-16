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
   - Land `WTD-5.1` Temporal durable workflows first.
   - Then move notification delivery and retry under `WTD-5.3` onto durable
     workflow execution.

5. **AI eval harness**
   - Complete `WTD-11.4` with per-workflow goldens and CI gating for model or
     prompt changes.
   - Cover citation validity, statute confusion, fact fabrication, required
     section coverage, formatting compliance, and adverse-treatment detection.
