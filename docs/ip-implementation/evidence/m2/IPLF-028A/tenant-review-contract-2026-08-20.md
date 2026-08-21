# IPLF-028A — is the tenant-facing review contract now present?

**Slice:** `IPLF-028A`
**Blocker:** `IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION`
**Date:** 2026-08-20
**Method:** observation of merged code only. No route, schema, generated client
or UI file in the Codex half of IPLF-028B was edited, and no API test was added
to it.

## Question

The blocker records four named artefacts. Two are implemented, one is mechanism
without content, and the fourth is recorded as **MISSING: the tenant-facing
review contract**. Codex has since merged five IPLF-028B pull requests (#274,
#275, #276, #277, #278) that add tenant-facing data-governance routes and a
review UI. Does that close the fourth artefact?

## Answer: no. It is still missing, and now it is characterised rather than asserted.

What merged is a tenant-facing **visibility and dry-run-creation** surface. What
the blocker means by a *review contract* — a workflow in which a tenant requests,
approves or rejects a data operation under dual approval and step-up — has no
route at all.

### What exists (`apps/api/src/caseops_api/api/routes/data_governance.py`)

| Route | What it does |
|---|---|
| `POST /operations/dry-runs` | Create a non-executable dry-run manifest |
| `GET /operations/dry-runs` | List reviewable dry runs |
| `GET /operations/dry-runs/{id}` | Read one dry run |
| `GET /integrity` | Tenant data-governance integrity report |
| `GET /holds/summary` | Aggregate legal-hold preservation state |
| `POST /operations/{id}/execute` | Refuses unconditionally (typed 503) |

Every one is gated on `require_capability("audit:export")`.

### What is unreachable

Both approval services exist and neither is routed. Counting references from
`apps/api/src/caseops_api/api/`:

| Function | Service | Route references |
|---|---|---|
| `request_execution` | `data_operation_approval.py` (PR #267) | 0 |
| `reject_execution` | `data_operation_approval.py` | 0 |
| `approve_execution` | `data_operation_approval.py` | 0 |
| `propose_version` | `retention_authorization.py` (PR #273) | 0 |
| `approve_version` | `retention_authorization.py` | 0 |
| `activate_version` | `retention_authorization.py` | 0 |
| `retire_version` | `retention_authorization.py` | 0 |

Their only callers anywhere in the repository are
`apps/api/tests/test_data_operation_approval.py` and
`apps/api/tests/test_datagov02_retention_authorization.py`.

So the four-eyes execution decision and the retention-policy lifecycle are
reachable from tests and from nothing else. A tenant can see what an operation
*would* do and see that execution is refused; a tenant cannot request, approve,
or reject anything.

The blocker's `evidence_needed` asks for "named dual-approval and step-up
controls, jurisdiction/tenant exceptions, and reviewed user workflow tests".
There is no user workflow for those tests to review.

## A forward risk that should be settled before the approval routes land

The entire surface is gated on `audit:export`, which
`services/capability_catalog.py` maps to `_OWNER_ONLY`. The review UI mirrors it
(`useCapability("audit:export")` in `apps/web/app/app/admin/data-governance/page.tsx`).

If the four-eyes approval is later exposed behind that same capability, a tenant
whose company has a single owner cannot satisfy four eyes at all: the only role
that can reach the surface is the role that already made the request. The control
would be unsatisfiable by construction for exactly the tenants most likely to
have one owner.

This is not a defect in what merged — those six routes are reads, a dry-run
create, and a refusal, and owner-only is defensible for all of them. It is a
constraint on the capability design of the routes that do not exist yet, and it
is cheaper to decide now than to discover after a tenant is blocked. Recording
it here rather than acting on it: the data-governance route and capability
surface is the Codex half of IPLF-028B.

## Effect on the blocker

`IPLF-028A-POLICY-AND-HOLD-AUTHORIZATION` stays open, and its fourth artefact
stays MISSING. What changes is that "MISSING" is now backed by an inventory of
what exists and what is unreachable, instead of standing as an unexamined
assertion. Nothing here bears on the third artefact: the retention schedule's
**content** — which classes are kept, for how long, on what legal basis — remains
a legal decision, and no amount of merged routing produces it.
