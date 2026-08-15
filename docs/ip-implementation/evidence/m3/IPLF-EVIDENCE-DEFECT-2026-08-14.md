# Evidence defect: rows verified by tests that were never written

**Date:** 2026-08-14
**Trigger:** the traceability audit's finding that `IPLF-039A/B/C/D/E/F` cite a
single integration test for dozens of exception paths.
**Scope found:** program-wide, not limited to `IPLF-039`.

## The defect

A `planned:` test reference names a test that **does not exist yet**. It is a
legitimate placeholder on a row still being built. It can never be evidence
that behaviour was verified.

**80 rows claimed `verification_status: passed` or
`release_status: deployment_verified` while their cited tests were `planned:`
placeholders.** In the worst cases the placeholders were the row's *only*
evidence.

The clearest examples, all previously `implemented / passed / deployment_verified`:

| Slice | Journey paths owned | Test references |
|---|---|---|
| `IPLF-039C` | 22 | one integration test + one offboarding test + **22 `planned:` placeholders** |
| `IPLF-039B` | 16 | one integration test + one e2e spec + **16 `planned:` placeholders** |
| `IPLF-039A` | 8 | one test file + **8 `planned:` placeholders** |
| `IPLF-039D` | 6 | one test file + **6 `planned:` placeholders** |
| `IPLF-039F` | 7 | one integration test + **7 `planned:` placeholders** |

`deployment_verified` is the strongest status the manifest offers. These rows
asserted it while simultaneously recording that the tests for their paths had
not been written.

## Why the validator did not catch it

The validator had **no reference to `planned:` anywhere**. Its rules checked
evidence *presence* and *shape* — that `evidence_metadata` names a revision,
environment, fixtures, assertions and result — but never whether a cited test
actually exists. A row could therefore satisfy every existing rule while citing
nothing real.

## The rule added

```python
# A `planned:` reference names a test that does not exist yet. A row may
# cite one while it is still being built, but it can never be evidence
# for a passed or deployment-verified claim.
if row.verification_status == "passed" or row.release_status == "deployment_verified":
    unwritten = [r for r in row.test_refs if r.startswith("planned:")]
    if unwritten:
        error(f"{row}: passed/deployment_verified row cites unwritten tests {unwritten}")
```

Both a positive and a negative test accompany it, as PRD Section 0.3 requires:

- `test_validator_rejects_passed_row_citing_unwritten_planned_test`
- `test_validator_allows_planned_test_reference_on_an_unverified_row` — the rule
  must not punish honest work in progress.

## The correction applied

Slices and gates citing unwritten tests were reset to
`verification_status: not_run`, and `deployment_verified` fell to `blocked`
because the manifest defines deployment verification as requiring passed
verification. Every dependent requirement, path, journey, epic and milestone
then **derived** its new status; none was edited directly.

| Collection | `passed` before → after | `deployment_verified` before → after |
|---|---|---|
| Slices | 53 → **38** | 35 → **21** |
| Requirements | 52 → **33** | 14 → **10** |
| Journey paths | 50 → **30** | 16 → **4** |
| Journeys | 10 → **5** | 4 → **1** |
| Epics | 16 → **11** | 11 → **8** |
| Milestones | 2 → **1** | — |

Slices downgraded: `IPLF-001A`, `001B`, `003A`, `003B`, `005A`, `006A`, `006B`,
`007A`, `007B`, `039A`, `039B`, `039C`, `039D`, `039E`, `039F`.

## What did **not** change

- **No `implementation_status` was downgraded.** The code exists and is shipped.
- **No production deployment evidence was deleted or altered.** The release
  evidence packs — commit SHAs, image digests, Cloud Run revisions, migration
  jobs, scheduler bindings — remain exactly as recorded. Those slices really
  were deployed.
- **No test was deleted or weakened**, and no `planned:` placeholder was
  silently removed to make a row pass.

What is corrected is a single claim: that the behaviour those rows own had been
**verified**. It had not, because the verifying tests were never written.

## Honest reading of the result

This makes the program look materially worse than it did this morning. That is
the point. The previous numbers counted deployment as verification, and counted
a placeholder as a test.

The affected M1 slices in particular were deployed with genuine production
evidence, and nothing here disputes that. The gap is between *"we shipped it and
watched it serve traffic"* and *"we proved each journey path behaves correctly"*.
Those are different claims, and only the first was ever true for these rows.

## Reversal

The correction is one commit and is fully reversible. Restoring the previous
numbers, however, would restore the false claim.

## Next actions

1. **Write the missing per-path tests.** The `IPLF-039` family alone owns 62
   journey paths with no path-level evidence. That is the largest single block
   of unproven behaviour in the program.
2. Re-verify each downgraded slice and restore its status **only** with a real
   test, per path.
3. The 18 `implemented` paths still carrying `planned:` references — the second
   item on the audit backlog — are now caught by this rule wherever they also
   claim verification.

## Commands

```
python scripts/ip_program_manifest.py validate     -> valid (0 errors)
bash scripts/verify-backend.sh tests/test_ip_program_manifest.py -> 10 passed
```
