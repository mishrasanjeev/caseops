# September 09 Completion Execution

Owner: Codex. Status: implementation in progress. Release: **NO-GO** until the
requirements below have exact local and deployed proof. No earlier partial
catalogue or intake-only domain is relabelled complete.

Canonical source baseline is `5145fb3a4b51b26af116220ff10a7389bde6324d`.
The working candidate is `codex/sep08-acceptance-repair-20260908`. September 08
Docker evidence remains historical proof for its frozen source, not proof of
September 09 edits. User approved parallel implementation agents on September 09.
Agents use isolated worktrees; central integration owns shared schema, migration
ordering, generated contracts, programme status and production release.

## Milestones

| Milestone | Owner | Concrete exit gate | State |
| --- | --- | --- | --- |
| Provider recovery | Main task | Durable bounded attempt claims before transport; total HTTP deadline; no transaction during provider/AI waits; current access/identity/lifecycle checks; expiry and uncertain-spend recovery; PostgreSQL concurrency and browser acceptance | In progress |
| Complete catalogue | Catalogue agent | All 23 existing Acts plus scoped IP packs; entire official provision/schedule inventory; exact source/hash/edition; explicit historical applicability; positive selection/attachment/source/reload for every admitted edition | In progress |
| IP foundations and operations | Foundations agent | IPLF-027B, 028A/B, 029A/B, 039G/H, 070A/B, 071A/B, 072A/B, 073A/B requirements and normal/exception journeys reconciled and implemented | In progress |
| Patent | Patent agent | IPLF-079A/B, 080A/B plus versioned patent child PRD; preserve existing foundations; complete distinct prosecution/proceeding/claim/obligation/filing/title workflows | In progress |
| Other IP domains | Domain agent | IPLF-090A/B, 091A/B separate versioned domain contracts and complete scoped journeys, without trademark substitution or unsupported legal automation | In progress |
| Cold-start stability | Performance agent | Repeated fresh 2 CPU/4 GiB runs under unchanged 30-second budget; original HTTP workflow plus real AV positive/rejection/outage/recovery; no dynamic network model assets | In progress |
| Integrated release | Main task | IPLF-100A/B, all local source/API/PostgreSQL/frontend/browser/security/migration gates, truthful guide/public claims, canonical main and green CI, exact production identities and dated E2E, quiescent private maintenance | Pending dependencies |

No production mutation, commit or push is included in an agent's scope. Routerwise
shares this workstation Docker: no global cleanup, reset or unrelated stop is
permitted. Automated suites use deterministic emulators and the authoritative
no-paid-provider marker. Any live paid verification is a separate capped action.

## Provider Findings And Contract

J08, MOD-TS-006, US-022/023/024/025/057 and FT-078-082 remain the existing owner.
Manual and scheduled transport held an application transaction; bulk scheduling
made its paid request before claiming individual cases. The repair must not
substitute a bare commit for a durable recovery protocol. Running claims expire,
each returned attempt must still own its token, and unknown paid outcomes must
continue consuming budget rather than expire into free retry capacity.

The September 09 official [eCourts pricing](https://ecourtsindia.com/api/pricing)
distinguishes search, detail and refresh prices and excludes failed requests and
empty results. An absent response cannot establish that an attempt was free.
The [HTTPX timeout contract](https://www.python-httpx.org/advanced/timeouts/)
bounds individual waits, not the overall response-body or retry duration. A
separate total deadline is therefore required.

Additional adjacent paths to accept: initial search, source download, AI update
summaries, post-disposal results, token and membership revocation, archived or
relinked bookmarks, identity convergence, same-window backlog continuation,
budget-report/API/UI parity and mixed-revision worker drain. No broad provider
closure follows from two newly passing transaction probes alone.

## September 09 Local Evidence

No commit, push or production mutation has occurred. Candidate changes continue;
each snapshot below certifies only its retained source archive, not later edits.

- `api-sep09-provider-first-01.xml`: 38 passed, one obsolete spend DTO assertion
  failed after adding `reserved_minor`; the complete failure was inspected.
- `api-sep09-provider-boundaries-02.xml`: 64 passed, exit 0, including durable
  overlap, worker loss, uncertain budget and mid-transport membership/archive
  revocation. This snapshot precedes the later search/source and async protocol.
- `api-sep09-provider-protocol-03.xml`: 68 passed, one obsolete 15-paise combined
  call-cost assertion failed. Corrected acceptance distinguishes a 165-paise
  refresh-plus-detail estimate from a held uncertain sibling; replay is pending.
- `api-sep09-provider-postgres-01.xml`: all 8 passed, exit 0, real PostgreSQL.
  Covers durable overlap, manual/scheduled transaction release, access/archive
  revocation, interrupted-worker recovery, queued-to-completed provider status,
  invalid concurrent-index recovery and two evidence-preserving downgrade refusals.
- `api-sep09-provider-boundaries-04.xml`: 128 passed, two source-download test
  assertions failed because they queried the nonexistent `feature_key` model
  attribute rather than `usage_type`; both complete failures were inspected and
  corrected. One Windows-only command-shim test is skipped on Linux, not waived.
- `api-sep09-provider-postgres-02.xml`: all 15 passed, zero skipped/failed/errors,
  141.826 seconds. Adds real concurrent disposal, initial-search/source-download
  post-I/O reauthorization, a 51-case continuation and orphan poll-run recovery.
  Both corrected source-download variants passed in this PostgreSQL run.
- `api-api-sep09-provider-boundaries-05.xml`: 249 passed, zero failures/errors,
  one explicitly Windows-only skip, 380.814 seconds in offline Docker. Includes
  the real TCP header/body deadlines, provider redirect rejection, rollout
  pause/drain/resume, prior deployment hardening and cold-start regressions.
  This snapshot precedes the later nested-invalid-status and precise-spend UI
  test additions; it is not evidence for those later changes.
- Cold-start seven-file patch integrated after incremental-diff review. Three
  sidecar cold portfolio/real-AV HTTP runs passed at 14.7709, 14.5174, 22.2118
  seconds, unchanged 30-second limit. See the dedicated evidence document for
  the failed narrow-margin run, exact image, source hashes and remaining proof.

The XML and source-archive hashes are retained under
`C:/tmp/caseops-completion-20260908/`. Current broader provider/cold tests and
fresh integrated release gates still require completion. Generated governance
now inventories all four additive lease/spend columns; no policy approval is
invented. The 18:00-20:00 scheduler window now has a five-minute continuation
cadence in candidate infrastructure; production has not been changed.

The [official provider contract](https://ecourtsindia.com/api/docs) makes refresh
submission asynchronous and refresh-status checks free. The implementation
checks that status before a second purchase, treats pending as scheduled work,
and admits details only after completion. PAYG estimates conservatively reserve
60/150/15/375 paise for search/detail/refresh/document respectively, and report
unconfirmed holds separately; these are not claims about a reconciled invoice.

## Mixed-Revision Rollout

The candidate deployment now pauses and drains the canonical tracking scheduler
before migrations, holds it through image reconciliation and synchronous release
checks, and resumes only after verifying its exact immutable image, runtime,
target and invoker contract. A failure leaves it paused and fails the release;
there is no paid execution canary or cancellation of unknown charged work.

The drain inspects an unfiltered bounded execution history, fails on truncation
or malformed identity, and requires two clean observations with the scheduler
still paused. An old worker behind a newer completed execution must be found.
The total wait is 180 seconds and each control-plane subprocess has a deadline.
A failed-task count alone is not proof that an execution ended. This follows the
official [Cloud Run execution state](https://docs.cloud.google.com/run/docs/reference/rest/v1/namespaces.executions)
and [CLI listing contract](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/executions/list).
It coordinates scheduled executions; it is not an assertion that an independent
operator cannot manually launch a job during rollout. New rollout regressions
and real-loopback stalled-header/body regressions are in the next Docker run.
