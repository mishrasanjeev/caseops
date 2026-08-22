# IPLF-028A — the tenant-facing review contract, implemented

**Slice:** `IPLF-028A`
**Blocker:** `IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION`
**Date:** 2026-08-22
**Follows:** `tenant-review-contract-2026-08-20.md`, which established by
inspection that the artefact was missing rather than merely unproven.

## What this closes

The 2026-08-20 audit found that `request_execution`, `reject_execution` and
`approve_execution` (PR #267) had **zero references from any route**, and that
their only callers in the repository were their own unit tests. A tenant could
see what an operation would do and see that execution was refused; a tenant
could not request, approve, or reject anything. The blocker's required
"reviewed user workflow tests" had no user workflow to review.

Three routes now expose that workflow:

| Route | Effect |
|---|---|
| `POST /operations/{id}/review/request` | Submit a completed dry-run manifest for approval |
| `POST /operations/{id}/review/reject` | Refuse it, recording the reason |
| `POST /operations/{id}/review/approve` | Authorise an execution, under step-up and four eyes |

## The capability decision, which is the substance of this change

The existing read-only data-governance routes are gated on `audit:export`, which
is `_OWNER_ONLY`. The 2026-08-20 evidence recorded this as a forward risk:

> If the four-eyes approval is later exposed behind that same capability, a
> tenant whose company has a single owner cannot satisfy four eyes at all: the
> only role that can reach the surface is the role that already made the
> request.

So the review contract is gated on a **new** capability,
`data_operations:review`, mapped to `_OWNER_ADMIN` — the narrowest role set that
can actually contain two distinct people. Reusing `audit:export` would have been
less code and would have produced a control that is unsatisfiable by
construction for exactly the tenants most likely to have one owner.

`test_datagov05_review_is_not_gated_behind_an_owner_only_capability` asserts the
*property* — that an admin can supply the second pair of eyes — rather than the
capability's name, so it keeps its meaning if the name changes. It was
falsified before being trusted: flipping the route back to `audit:export` fails
that test and the happy-path test, with the message naming the reason.

## Approving is not executing

The single most important line in the slice. `approve_execution` produces an
authorised operation in status `planned` and nothing else — no export is
written, no record is deleted — and `POST /operations/{id}/execute` still
refuses unconditionally with a typed 503.

Because a `200` from an approve route could reasonably be misread as "it ran",
the response carries `executed: false` explicitly rather than leaving the reader
to infer it. The happy-path test asserts the 503 *after* a successful approval,
so the two facts are proven together rather than separately.

## Response shape

`request` and `reject` return the dry run; `approve` returns the separate
execute row it creates. A client correlates on the manifest it submitted, so the
response always keys `id` on the manifest and reports the authorised operation
beside it as `approved_operation_id`. The dry run may never hold `approved` —
the execute row *is* the record of the outcome — so the serializer does not
invent that status.

## Commands run

Working tree: `feat/datagov-tenant-review-contract-20260822`, based on
`origin/main` at `1a1ee0ef`.

| Command | Result |
|---|---|
| `verify-backend.sh tests/test_datagov05_tenant_review_contract.py` | ruff clean; **6 passed** |
| `verify-backend.sh` × review, approval, governance-service, role-guards, capability-catalog | **63 passed** |
| falsification: route flipped to `audit:export` | **2 failed**, as designed |
| `ip_program_manifest` / `ip_data_governance_map` / `ip_data_class_projection` / `ip_m2_ownership_audit` / `migration_preflight` validate | all `OK` |
| `npx tsc --noEmit` (apps/web) | exit 0 |
| `npx vitest run lib/capabilities.test.ts` | **4 passed** |
| `dump_openapi.py` + `openapi-typescript@7.13.0` | regenerated; +205 lines, confined to the review routes and schemas |

`test_role_guards.py` passes, which is what proves the three new mutating routes
are capability-guarded rather than merely intended to be.

## What is still open on this blocker

The blocker names four artefacts. Two were already implemented; this closes the
fourth. The third remains open and **is not closeable by code**:

> the retention schedule has a propose/approve/activate/retire lifecycle under
> four eyes and step-up (PR #273), but no schedule **CONTENT** has been approved
> — which classes are kept, for how long, on what legal basis is a legal
> decision, and while none exists a retention purge cannot be authorized at all.

Nothing here changes that, and nothing here should be read as authorising a
purge. The retention-authorization check inside `approve_execution` still
refuses a retention purge that cites no active schedule version.

Also not delivered, and worth naming rather than implying:

- **No UI.** This is the API contract. A tenant-facing *screen* for the review
  queue does not exist yet, so the workflow is reachable by an integration and
  not yet by a lawyer in a browser. `data_operations:review` is mirrored in
  `apps/web/lib/capabilities.ts` so the screen can gate on it when it is built.
- **No deployed acceptance.** No build, deploy, or production probe was run for
  these routes, so `verification_status` stays `not_run` and `release_status`
  stays `blocked`.
