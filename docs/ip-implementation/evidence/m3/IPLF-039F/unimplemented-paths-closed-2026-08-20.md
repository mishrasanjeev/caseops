# IPLF-039F — the four unimplemented UJ-52 paths, closed

**Slice:** `IPLF-039F`
**Date:** 2026-08-20
**Supersedes the "not implemented" half of:**
`docs/ip-implementation/evidence/m3/IPLF-039F/per-path-2026-08-15.md`
**Lane:** Codex-owned; branch `feat/iplf039f-cost-items-20260820` is retained
only as historical provenance.

## Result: 7 of 7 paths implemented and proven in the repository

The 2026-08-15 audit found three UJ-52 paths proven, three absent, and one
actively contradicted by the code. This change closes the remaining four. It
does **not** claim deployed acceptance — see *What is still open* below.

## What changed, and why each is the fix rather than a workaround

### `UJ-52-EXC-01` — nonbillable capture no longer depends on a Matter

The previous behaviour was not a missing feature but an inverted one:

```python
if not docket.matter_id:
    raise HTTPException(status_code=409, detail="IP costs require a Matter billing owner.")
```

The journey says the absence of a billing Matter blocks *billable time and
invoicing*, **not** nonbillable legal-cost capture. An official fee paid to the
registry has already left the firm's account; refusing to record it does not
prevent a cost, it destroys the evidence that one was incurred.

`ip_cost_items.matter_id` is now nullable and a `billable` column records the
decision explicitly. A billable cost on a matterless docket is still refused —
with a 409 that names the alternative instead of closing the door — and a
nonbillable one is accepted and reconciles to the terminal status
`nonbillable`, which is deliberately distinct from `unlinked`: the latter still
expects a billing link to arrive.

The `/app/ip` cost card previously replaced its entire form with the sentence
"Cost items require a linked Matter so Matter billing remains the accounting
owner" whenever the record had no Matter. The surface that exists to preserve a
paid fee offered no way to record one. It now offers **Add nonbillable cost
evidence** and explains the deferral.

### `UJ-52-EXC-02` — a conversion is preserved, and it is what reconciles

Five additive columns record the conversion: `fx_rate`, `fx_rate_source`,
`fx_converted_at`, `base_amount_minor`, `base_currency`. `amount_minor` and
`currency` keep meaning the amount **as originally incurred** — that is the fact
the firm must be able to produce years later.

The subtle half is reconciliation. The ledger was billed in the converted
currency, so the converted figure is the only one an invoice could match.
`_cost_comparison_value` therefore compares the converted amount when one is
preserved, and the reported difference is measured against it. Comparing the
original instead would report every converted cost as a mismatch — in the test
case, a discrepancy of 10,446,000 minor units that does not exist.

The five columns are all-or-nothing, and a conversion into the currency it
started in is refused: neither preserves anything.

### `UJ-52-EXC-04` — an estimate is a distinct nature, not a category

`cost_nature` is `actual` or `estimate`. The existing category enum described
what a cost was *for*, never whether it had happened. An estimate is captured
in full, reconciles to the terminal status `estimate`, and cannot carry a
billing link at all — a provider's quote has no counterpart in the ledger, and
the test proves that an estimate equal to an issued invoice **to the rupee**
still does not match it.

### `UJ-52-EXC-05` — confidential rates are permissioned on the read path

`rate_confidential` marks the row. `_serialize_docket` now takes the reading
`context` as a **required** keyword — an optional one would let a future call
site omit it and silently inherit whatever default was chosen — and withholds
the monetary fields from any caller without `ip:fees_manage`.

`ip:fees_view` is deliberately not sufficient: it is held by all staff, and the
point of the path is that a rate can be hidden from colleagues who can
otherwise see the record.

Withholding sets `amount_withheld` and nulls the amount rather than substituting
zero, so a withheld rate cannot be misread as a cost of nothing. The category,
description and evidence reference stay visible: the existence of the cost is
not the secret. The audit entry records the classification and never the
amount, so what is withheld from the read path is not recoverable from the
audit trail every reviewer can read.

## A defect this change introduced, found in review

Making `amount_minor` nullable for UJ-52-EXC-05 handed every consumer of it a
value it had never seen, and one consumer summed it:

```
TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'
  services/ip_operations.py, _ip_docket_control_report_from_listing
```

`GET /reports/docket-control` is gated on `ip:read`, which every authenticated
member holds. So one confidential cost anywhere in a tenant's visible dockets
made the docket control report a 500 for **every member below owner/admin**,
and took the control-review signoff path with it, since both build the report
from the same function. Reproduced exactly: the owner's request returns 200 with
a complete total, the partner's raises.

Raised by automated review on commit `683ec9b8`, and correct.

The null guard alone would have been the wrong fix. Excluding withheld amounts
from a total silently under-reports it, which is the same defect as rendering a
withheld rate as zero — the reader cannot tell an incomplete total from a
complete one — and it collides with the UJ-59 rule that a control report cannot
state all clear while something is hidden. So `withheld_cost_item_count` travels
with the total, and the owner and the partner get different, individually honest
answers: 1,375,000 with nothing withheld, and 900,000 with one withheld.

Adjacent-path audit: every `.amount_minor` consumer in the API was inspected.
Exactly one was affected. The others belong to invoices, notices,
outside-counsel spend and rate cards, which have their own non-nullable columns.
The web read path was already guarded by the `amount_withheld` branch.

Adding a required field to `IpDocketControlReport` broke two fixtures in
`apps/web/lib/ip/control-review-manifest.test.ts`, a file belonging to the other
lane. TypeScript caught it. The fixtures gained the field and nothing else:
leaving a shared type's consumers broken would be worse than touching adjacent
test data.

## Enforced twice, on purpose

Each rule is a Pydantic validator **and** a database CHECK constraint. The
validator gives the caller an actionable 422; the constraint is what a future
route, a bulk import, a backfill script, or a psql session must also pass. A
rule that lives only in one request schema is a rule the next writer does not
inherit.

`ck_ip_cost_item_billing_link_pair` was added alongside them because the
"together or not at all" rule for `billing_link_type`/`billing_link_id`
previously lived only in the request model, and the four new constraints test
`billing_link_type` — a row carrying only `billing_link_id` would have slipped
past all four.

`test_uj52_cost_invariants_hold_at_the_database_not_only_in_the_request_model`
inserts nine violating rows directly through the ORM, bypassing the API, and
asserts each is rejected. It inserts a valid control row first, so a failure is
the constraint firing rather than a broken fixture.

## Commands run and results

Working tree: `feat/iplf039f-cost-items-20260820`, based on `origin/main` at
`9e8d41c0`.

| Command | Result |
|---|---|
| `scripts/verify-backend.sh tests/test_ip_039f_cost_linkage.py` | ruff clean; **11 passed** |
| `scripts/verify-backend.sh tests/test_data_class_projection.py tests/test_ip_data_class_projection_gate.py tests/test_ip_data_governance_map.py` | **36 passed** |
| `scripts/verify-backend.sh -k "ip_ or ip_operations or capability_fences or postgres_validation or data_class or governance_map"` | **530 passed, 97 skipped**, 11 failed — every failure an artefact, see caveat |
| `scripts/verify-backend.sh tests/test_ip_record_workflow.py tests/test_ip_record_access_foundation.py tests/test_ip_record_access_workflow.py tests/test_ip_039f_cost_linkage.py tests/test_core_locked_capability_fences.py tests/test_ip_prd_slices.py` | ruff clean; **50 passed** — the `_serialize_docket` callers, re-run after the N+1 fix |
| `scripts/verify-backend.sh tests/test_ip_039f_cost_linkage.py tests/test_ip_control_review_signoff.py` (after the control-report fix) | **24 passed** |
| `scripts/verify-backend.sh -k "ip_ or capability_fences or data_class or governance_map"` (on the merged tree, after the control-report fix) | **553 passed, 28 skipped, 0 failed** — an uninterrupted run, nothing edited while it executed |
| all nine CI contract validators | all `OK` |
| `npx vitest run lib/ip/control-review-manifest.test.ts app/app/ip/page.test.tsx` | **24 passed** |
| `python scripts/ip_data_governance_map.py validate` | `data-governance map valid` |
| `python scripts/ip_data_class_projection.py validate` | `data-class projection valid` |
| `python scripts/ip_program_manifest.py validate` | clean |
| `npx tsc --noEmit` (apps/web) | exit 0 |
| `npx vitest run app/app/ip/page.test.tsx` | **16 passed** |
| `scripts/dump_openapi.py` + `openapi-typescript@7.13.0` | regenerated; diff confined to the cost-item schemas |

### Caveat on the broad backend selection

The broad `-k` selection reported 11 failures, all of them in
`test_data_class_projection.py`, `test_ip_data_class_projection_gate.py` and
`test_ip_data_governance_map.py`. Those failures were an artefact of the run
overlapping the work: it was still executing while the governance map and the
compiled projection were being regenerated, so it validated a tree that was
changing underneath it. All 36 tests in those three files were re-run against
the settled tree and passed.

**A second broad run was started and deliberately cancelled**, because while it
was executing I found the `list_ip_dockets` N+1 described below. Its result
would have described a tree that no longer exists, so it is not cited here.
What is cited instead is the targeted re-run of the three files that own
`_serialize_docket` and its callers, which is the surface the final change
touches. A full broad re-run on the exact committed tree has **not** been
performed locally; CI runs the complete suite on this commit.

### The N+1 this change introduced, and its fix

Resolving the confidential-rate capability inside `_serialize_docket` meant
`list_ip_dockets` resolved it once per docket. The capability depends only on
the reader, so it is now resolved once per request and passed down as an
explicit `may_read_rates` cache. The parameter defaults to `None`, which
resolves it properly — the default is "work it out", never "assume an answer".

### Verification that was not run

- **PostgreSQL.** The nine CHECK constraints are proven on SQLite, which
  enforces `CHECK`. They are declared identically in the migration and the
  model and are dialect-neutral SQL, but `CASEOPS_TEST_POSTGRES_URL` is not set
  in this environment, so `pytest -m postgres` skipped. CI's
  `postgres-validation` job runs `alembic upgrade head` against
  `pgvector/pgvector:pg17` and is the first place the migration is proven on
  the production dialect.
- **Deployed acceptance.** None. No build, deploy, or production smoke was run
  for this slice, which is why `verification_status` stays `not_run` and
  `release_status` stays `blocked` in the manifest.

## End-user proof, added 2026-08-21

The gap above was that every proof was developer-internal. API tests and CHECK
constraints show the fix compiles and the database refuses bad rows; neither
shows a lawyer that the workflow works. Two of these four defects were
*user-visible* in a way an API test cannot reach:

- **UJ-52-EXC-01** the failure was in the cost card, which replaced its entire
  form with "Cost items require a linked Matter" whenever the record had no
  billing Matter. The API would have accepted a nonbillable cost; the surface
  offered no way to send one.
- **UJ-52-EXC-05** a withheld rate has to *read* as withheld. Rendering it as
  `0.00` is indistinguishable to the reader from a cost of nothing, and only
  the rendered page can prove which one appears.

`tests/e2e/iplf-039f-cost-items-2026-08-21.spec.ts` covers both through a real
browser against a real API:

1. On a docket with no billing Matter, the card offers **Add nonbillable cost
   evidence**, explains the deferral, records the fee, and reports it as
   `Nonbillable` — a terminal status, distinct from `unlinked`.
2. An estimate renders as *Estimate — not an expense* (UJ-52-EXC-04); the owner
   sees both amounts; a **partner**, who holds `ip:fees_view` but not
   `ip:fees_manage`, sees the ordinary cost in full, sees *Amount withheld —
   requires fee-management access* for the confidential one, and sees neither
   the real figure nor a `0.00` substituted for it. The description stays
   visible, because the existence of the cost is not the secret.

**2 passed** on two consecutive runs, so this is repeatable rather than a
single lucky pass. The first run failed on an over-loose locator — `Nonbillable`
matched the card's explanatory copy and its submit button as well as the
recorded row — which is worth recording because the *product* behaved correctly
in that run and only the assertion was wrong. It now matches exactly.

The spec is committed and is selected by the default `playwright.config.ts`,
which uses a `testDir` plus a two-entry `testIgnore` denylist rather than a
`testMatch` allowlist, so it cannot be silently excluded from a normal run.

`data-testid="ip-cost-workspace"` was added to the cost card to scope the
assertions, matching the pattern the IPLF-039D spec established.

**Still not claimed:** this runs against a locally served build, not the
deployed caseops.ai surface, and no run against production with real
credentials has happened. Under the Playwright-on-prod rule that keeps the
slice's own verdict short of `Properly fixed` on the deployed surface, and
`release_status` stays `blocked`.

## Migration note for the integrator — resolved 2026-08-21

This migration is now `20260821_0003`, chained from `20260821_0002`. It was
originally `20260821_0002` from `20260820_0002`, and both parts of that had to
change when the Codex calendar lane merged as `c3dd77ec`:

- **Two heads.** The calendar lane chained `20260821_0001` from the same
  `20260820_0002`, so the two lanes were siblings and `alembic upgrade head`
  would have been ambiguous. Predicted before the merge; resolved by re-chaining
  rather than by adding a merge revision, since the two migrations touch
  unrelated tables and a linear chain is simpler to reason about.
- **A duplicate revision id, which was not predicted.** PR #282 carried *two*
  migrations, not one: the calendar lane also landed `20260821_0002`
  (`ip_control_review_evidence`). That collided with this migration's original
  id. Alembic reports a duplicate id as a warning and then resolves it silently,
  so the second copy would simply have become unreachable.

Verified after the change: `ScriptDirectory.get_heads()` returns exactly
`['20260821_0003']`, and all nine contract validators plus the slice tests pass
on the merged tree.

Both defects are the ones `scripts/migration_preflight.py` now detects on the
pull-request merge commit — `MIGRATION-MULTIPLE-HEADS` and
`MIGRATION-DUPLICATE-REVISION`, added in PR #284 and recorded as `EH-DEPLOY-01`.
That gate was written from the predicted collision; the duplicate id it also
catches turned out to be a real second defect in the same merge rather than a
hypothetical one.

The generated data-class projection changed only its fingerprints — no data
class was added or removed. The Codex calendar lane will change the same
fingerprints when its table lands; resolve by re-running
`scripts/ip_data_class_projection.py render` after the merge rather than by
hand-editing.

## What is still open

`IPLF-039F` remains `in_progress / not_run / blocked`. What this change
delivers is repository proof for seven of seven UJ-52 paths. What it does not
deliver:

- deployed acceptance on an exact candidate build;
- confirmation from the finance owner that a nonbillable matterless cost is the
  intended capture for an already-paid official fee — the journey text supports
  it, but this is a finance policy question and no named approval exists;
- `ARCH-OPS-18` and `ARCH-OPS-26`, which the retired blocker named as remaining
  open and which are not in this slice's scope.

No second invoice or payment ledger was created. `matter_billing` remains the
single accounting owner, and the reconciliation report still says so.
