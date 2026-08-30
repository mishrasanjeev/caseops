# IPLF-039F — matterless nonbillable cost finalization

**Date:** 2026-08-30

**Scope:** the remaining repository gap recorded in `PROGRAM_MANIFEST.yaml`

**Release claim:** repository implementation only; exact deployed acceptance is not claimed

## Brutal gap analysis

The earlier UJ-52 implementation correctly accepted a cost on an IP docket
with no Matter only when `billable=false`, rejected billing links, and returned
the terminal reconciliation status `nonbillable`. That was necessary, but it
was not enough to support the stronger closure statement in the manifest.

Three gaps remained:

1. The service had no update/delete route, but PostgreSQL still allowed a
   future writer, import, repair script, or direct SQL session to rewrite the
   stored `matter_id`, `billable`, amount, currency, evidence reference, or
   billing link. A matterless cost could therefore be repurposed later despite
   having been presented as immutable official-fee evidence.
2. The API regression counted only `MatterInvoice` rows. It did not prove that
   invoice lines, payment attempts, invoice totals, or collected amounts were
   unchanged, and it reconciled only once. A shallow implementation could have
   passed that test while producing an adjacent accounting effect.
3. The matterless UI called the action **Reconcile with Matter billing**, even
   though no Matter billing owner exists. It also stopped showing the evidence
   reference after capture, so the retained evidence was not inspectable from
   the operator surface.

## Durable fix

- Alembic revision `20260830_0003` installs SQLite and PostgreSQL triggers over
  `ip_cost_items`. The cost/evidence identity is immutable and deletion is
  rejected. Reconciliation status, canonical amount/difference, reviewer, and
  time remain mutable derived projections, so repeat verification still works.
- The service/API regression snapshots invoice count, invoice-line count,
  payment-attempt count, invoice total, and received amount before capture and
  after repeat reconciliation. Every value must remain identical.
- The same regression proves PATCH, PUT, and DELETE are not public cost-item
  operations, then attempts a direct ORM rewrite and verifies the original
  matterless/nonbillable amount and evidence reference persist.
- A real PostgreSQL regression proves the trigger permits reconciliation but
  rejects amount, billable-state, evidence-reference, and delete mutations.
- The UI now names the action **Verify nonbillable evidence**, states that it
  cannot create an invoice, invoice line, payment attempt, or collection, and
  keeps the evidence reference visible before and after verification.
- The dated Playwright scenario reads the canonical Matter billing/payment
  tables before capture and after UI verification, asserting the same complete
  zero-effect snapshot rather than inferring safety from a label.

## Verification completed while authoring this record

| Surface | Command | Result |
|---|---|---|
| API + SQLite migration | `uv run --project apps/api --no-sync pytest -q apps/api/tests/test_20260830_ip_cost_evidence_immutable.py apps/api/tests/test_ip_039f_cost_linkage.py` | **13 passed** |
| PostgreSQL 17 / pgvector | targeted `pytest -m postgres` migration-head and immutable-cost tests against a fresh container | **2 passed**, 105 deselected |
| API lint | targeted Ruff over migration and changed backend tests | **passed** |
| IP UI | `npm run test --workspace @caseops/web -- app/app/ip/page.test.tsx` | **28 passed** |
| Web types | `npm run typecheck --workspace @caseops/web` | **passed** |

The exact final-commit Docker/PostgreSQL Playwright result is intentionally not
self-asserted inside this source-controlled document: it is run only after the
candidate is committed and is recorded in the Draft PR/test evidence. Hosted
CI, integration into `main`, deployment, exact production identity, and dated
production Playwright remain required before `verification_status` or
`release_status` can move from `not_run / blocked`.
