# Journey-path traceability audit — 2026-08-14

**Scope:** the 95 `in_progress` journey paths still carrying `planned:` test
references whose owning slice has already been implemented.
**Method:** read the candidate test body and confirm it asserts the specific
path behaviour. Test *names* were never treated as evidence.
**Outcome:** 5 paths mapped. The rest are **not** mappable, and the reason is
the important finding.

## Why this audit was run

Four consecutive slices (`IPLF-031A`, `033A`, `034A`, and all of `IPLF-036`)
turned out to be mostly or entirely built already. That suggested a large,
cheap win: shipped and tested behaviour recorded as unevidenced. The starting
counts were:

- **285 of 317** journey paths carried `planned:` test references.
- **95** of those were `in_progress` with at least one already-implemented
  owning slice — the population audited here.
- **18** were marked `implemented` while still carrying a `planned:` reference.

## Result: the cheap win mostly does not exist

The expectation was wrong, and it is worth stating plainly because it reverses
the earlier recommendation.

Most of these paths cannot be honestly mapped, because their owning slice's
evidence is a **single broad happy-path integration test** rather than
path-level assertions.

The clearest example is `apps/api/tests/test_ip_prd_slices.py::test_ip_remaining_operations_end_to_end`,
which is cited as the test reference for slices owning **UJ-51 (9 paths)**,
**UJ-52 (7 paths)** and **UJ-55 (7 paths)** — 23 paths against one test. Reading
its assertions, it covers docket creation, a deadline, coverage reassignment,
evidence discovery counts, one notice link kind, a title interest, an obligation
completion, and cost reconciliation totals.

It asserts nothing about the exception paths it is cited for, such as:

- `UJ-51-EXC-05` bounced email is not delivered instruction
- `UJ-51-EXC-07` privileged correspondence excluded from portal/general AI
- `UJ-52-EXC-02` exchange conversion preserves original amount/rate/source/time
- `UJ-52-EXC-03` filing payment is not client payment
- `UJ-55-EXC-04` malformed/encrypted attachment enters exception
- `UJ-55-EXC-05` webhook and polling duplicate one another without duplicate effects

Mapping those would manufacture evidence. The master prompt forbids exactly
this: *"No required path may be represented only by a snapshot, shallow render,
DOM-presence assertion, mocked 200… One test may cover multiple manifest paths
only with explicit path-level assertions."*

**So the `planned:` markers are largely honest.** The program's remaining work
is not overstated the way I first reported — what is overstated is the
*evidential strength* of some already-implemented slices.

## Mapped after verification (5)

Each was confirmed by reading the assertions.

| Path | Test | Verified assertion |
|---|---|---|
| `UJ-03-EXC-02` | `test_ip_core_records.py::test_filed_phase_requires_confirmed_application_number_unless_source_pending` | 409 without an identifier; permitted when `source_pending_identifier_allocation` is true; permitted with a confirmed identifier |
| `UJ-06-EXC-01` | `test_ip_prosecution_workflow.py::test_uj06_event_preview_commit_reconcile_correct_and_report` | `backdated is True` and `recalculation_required is True` |
| `UJ-06-EXC-02` | same | `reconciles_event_id == candidate["id"]` |
| `UJ-06-EXC-03` | same | `supersedes_event_id == original["id"]` |
| `UJ-08-EXC-01` | `test_ip_deadline_workflow.py::test_provisional_exception_disabled_rule_and_cross_tenant_governance_fail_closed` | state is `provisional` with `result_on` null and confirmation refused 409 |

With `UJ-06-NORMAL` already mapped by `IPLF-033A`, **UJ-06 is now fully
evidenced.** No status changed; only evidence references were corrected.

## Rejected after verification — genuine coverage gaps

These have implemented owners but **no test proving the path**. They are real
gaps, not bookkeeping:

| Path | Why rejected |
|---|---|
| ~~`UJ-09-EXC-01`~~ **CLOSED 2026-08-14** | Was: the completion test never attempted an overwrite, so the protection was assumed. A dedicated suite `apps/api/tests/test_ip_deadline_terminal_state.py` now proves it. The guarantee **holds**: completed and superseded rows refuse confirm, override, recalculate and complete, and their stored date, version and evidence reference are unchanged after every attempt. |
| `UJ-03-EXC-01` pre-filing draft without an application number | No test asserts the draft/pre-filing save as a journey outcome. Drafts are created incidentally by other fixtures, which is not path evidence. |
| 23 paths across `UJ-51`, `UJ-52`, `UJ-55` | Cited test is a broad happy-path integration test with no assertions for the exception behaviour. |
| Remaining `UJ-50`, `UJ-53`, `UJ-54`, `UJ-57`, `UJ-58`, `UJ-59`, `UJ-61`, `UJ-62`, `UJ-68`, `UJ-20`, `UJ-25` candidates | Not individually verified in this pass. They are **not** assumed mappable. |

`UJ-09-EXC-01` was acted on immediately and is now closed. The guarantee holds,
but it had been shipped unproven — which is the pattern this audit exists to
surface.

While writing it, the first version of the supersession test contained a silent
early `return` when the fixture produced no predecessor, so it passed while
asserting nothing. That is exactly the no-test-shortcut the master prompt
forbids. It was rewritten to build a real supersession through an override and
now carries nine assertions.

## Corrected recommendation

My earlier advice — that mapping existing tests would cheaply convert ~100
paths — was wrong, and this audit is the evidence. The revised position:

1. **Do not bulk-map.** The `planned:` count is not a bookkeeping backlog; for
   most paths it accurately reports missing path-level evidence.
2. **Treat the one-test-many-paths pattern as an evidence defect.** Slices
   `IPLF-039A/B/C/D/F` cite a single integration test for dozens of exception
   paths. Those slices are marked `implemented` and `passed` on evidence that
   does not reach their claimed paths.
3. **The 18 `implemented` paths still carrying `planned:` references** should be
   reconciled next — an implemented path with a planned test reference is an
   internal contradiction the validator currently tolerates.
4. Continue auditing each slice against current code before implementing, which
   remains correct and has now saved four slices' worth of duplicate work.

## Commands

```
bash scripts/verify-backend.sh tests/test_ip_prosecution_workflow.py \
     tests/test_ip_core_records.py tests/test_ip_deadline_workflow.py
python scripts/ip_program_manifest.py validate
```

## Caveats

- This audit **changed no status and no code**. Only evidence references and
  allocation rationales on five paths were corrected.
- Only the 5 mapped paths were verified to the assertion level. The remaining
  90 are recorded as unverified, not as absent.
- The mapped tests are SQLite-only, inheriting the limits recorded on their
  owning slices: no real-PostgreSQL CI, no deployment, no production evidence.
