# IP18 Export Acceptance Contract

Status: partially implemented. No replacement Docker, CI, deployment or bug
closure is claimed by the component results below.

## Scope And Evidence

Existing IP15-018/IPLF-030/037, J08/M08 and UJ-02/04/26 own this dated tracker
journey. No new product module or legal-source behavior is introduced.

Exact serving API/web875f424c576e1568094b6f910c3e6a81b477d8b4 failed production
verification39915271013 with414 actual cases:395 passed,18 explicit skips and
one failure. The51-case writer completed50 passes and one failure, without
skips/retries/global errors. Notes22 passed at1280px/393px; the three following
Batch3 cases did not run. Preserve the original native JSON/JUnit/progress and
sealed failure proof under outputs/bugs-3-20261022/prod-review-03.

The sole failed case was the1280px IP18 current-source tracker journey at its
CSV job-completion assertion. Its exact-revision request-log window contains
nine HTTP200 reads of jobdc9a59b7-437c-4f52-a97a-e2bd1c902079. Authenticated,
no-paid-provider metadata readback found it completed with51 rows and3409bytes:
started09:06:46.656620UTC, completed09:06:57.146040UTC. The mobile job completed
in4.091519seconds. No retry, re-enqueue, export download, seed, lifecycle change
or provider call was performed during this diagnosis.

The public job DTO does not expose filters. The diagnostic's empty-object filter
hash is not evidence of filter identity. Correlation uses the exact job URL in
the failed test window, serving revision, actor-scoped record and timestamps.

## Root Cause

The dated spec inherited two different defaults: local Playwright15seconds and
production10seconds. A10.489420-second asynchronous completion therefore failed
only in production. A worker failure, corrupt CSV or an abandoned job is not
established. Existing application performance and worker durability are not
certified or repaired by correcting this acceptance contract.

## Repair And Regression

- Preserve the existing15-second operation budget explicitly, without changing
  either global UI timeout or the240-second whole-journey deadline.
- Bound status reads to16, one in flight, one-second spacing and no request
  beyond the remaining deadline or five seconds. Status transport failure is
  not retried and terminal failure does not consume the rest of the budget.
- Require the exact returned job identity and a completed, downloadable,
  nonnegative integral row count. Never retry the original enqueue.
- Keep51-row preview, continuation, saved-view, exact CSV records, private
  no-store download and responsive controls. Add a one-enqueue assertion.
- Test10.49-second success, late/never completion, nonadvancing clock, failed,
  unknown/wrong-job/undownloadable evidence and transport failure deterministically.
- Classify export HTTP paths without retaining job IDs, queries, tokens or
  response bodies. Foreign origins and unrelated suffixes stay excluded.

Focused component acceptance:40 cases passed across the helper and existing
failure-diagnostic module. This is not current full frontend, Docker or deployed
acceptance. Reconcile the complete intended inventory before any closure.

## Release Gates

Keep production875 healthy but uncertified. Preserve all18 skipped paths as
unverified. Do not resume maintenance by bypassing its guard. Require the
appropriate fresh Docker/frontend/contract gates, green candidate/main checks,
protected canonical merge, guarded exact-SHA release and complete production
replay, including actual Notes and all three Batch3 positives. Then obtain two
consecutive later clean same-image maintenance outcomes, second without rebuild,
and use the canonical scheduler resume guard. Update the workbook only from the
actual results. Do not turn this isolated wait correction into a broader claim
that all exports, legal records, paid providers or owner MFA are certified.
