# IPLF-039F — the four unimplemented UJ-52 paths, closed

**Slice:** `IPLF-039F`
**Date:** 2026-08-20
**Supersedes the "not implemented" half of:**
`docs/ip-implementation/evidence/m3/IPLF-039F/per-path-2026-08-15.md`
**Lane:** assigned to Claude as `assigned_not_started` in the Codex
`parallel_work_allocation` block, branch `feat/iplf039f-cost-items-20260820`.

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

## Migration note for the integrator

`20260821_0002` chains from `20260820_0002` (the merged invoice-immutability
migration). The Codex calendar lane reserved `20260821_0001` and chains from
the same parent, so if both land there will be **two alembic heads** and the
integration needs a merge revision. This is a known cost of the two-lane split
recorded in `parallel_work_allocation`, not an error in either migration.

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
