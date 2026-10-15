# QA Queue Coordination And Notice Filter Repair

## Observed Production State

API/web serve `0c82fbb008b524cd8ad75df0a445edaeabc1199d` after guarded release
of PR537. The same accepted tree passed 3,005 native Docker tests and 546 browser
cases with 10 explicit skips, plus fresh main CI and scanning. Four October10
production document/contract indexing cases now pass at desktop/mobile widths.
The original manual-IP grant was consumed once for test-legal only. Do not grant
again or modify GBA, paid plans, consent or provider automation.

Production run38693611994 remains NO-GO. Its tester journal has 121 collected
identities and 120 terminal results:106 passed,13 skipped,1 failed. One October12
mobile case is unended and all six mandatory October13 cases were unstarted.
Notice has one separate genuine failure after its three-document indexing
assertion passed. Preserve the complete failed and interrupted evidence.

## Root Causes And Scope

Intelligent Review failed detail visibility after a saved-source epoch changed.
Bounded read-only Cloud Logging and PostgreSQL evidence proves an unrelated IP
document job was queued01:43:22Z under the previous release, then completed
06:42:26Z during the new QA. That event advanced the same active generation from
tombstone9572 to9573. The selected review's source and parent were unchanged,
but the existing same-generation epoch fence correctly refused its saved read.
Neither the private ACL/source/tombstone fence nor its 300-second repair SLO is
changed by this repair.

The guarded deploy resumes normal document execution, then runs one exact-image
read-only queue observation before the final once-per-generation QA bootstrap
and private-index rebuild, followed by mutation-capable QA. The previous ordering
could rebuild before the legacy document queue drained; waiting only after that
rebuild would not establish a current generation. The bootstrap is not replayed
to repair an uncertain outcome. It resolves
the three fixed active QA slugs on the server, rejects missing/replaced tenants,
and requires two consecutive snapshots without queued or processing jobs. The
wait is capped at300 seconds. Each read-only PostgreSQL transaction has a5-second
statement limit and2-second lock limit, rolls back and closes before sleeping.
It never claims, retries, reclassifies, cancels or processes a document, never
fetches content, and never invokes a provider. Failed terminal records do not
become pending work. Ordinary workers remain available for the later positive
upload/reindex browser journeys.

The release helper verifies enabled admission, immutable API/worker equivalence,
exact per-execution command/arguments/environment/secret references, successful
single-task zero-retry completion and timing, then rechecks the serving revision.
Unknown execution outcome stops QA dispatch. Job defaults and the reserved grant
job are not changed. Canonical main is rechecked before and after the gate.

Independent review found that an already misbound worker could otherwise observe
the wrong database, and a deploy-time observation cannot cover later async work.
The helper now binds the canonical database secret identity, enabled resolved
version, namespace and Cloud SQL instance to the actual API revision before and
after the observer. It validates the execution's top-level Cloud SQL annotation
and exact copied container/environment/secret contract. Secret values are never
requested. Real v1 metadata confirms current API and worker both use latest,
resolving now to version2, with equal normal job/execution containers. This is
configuration/shape proof, not proof of a new override execution.

The existing capability-gated tenant integrity API also reports one bounded
document_processing_pending Boolean from its actual request database session
and authenticated tenant. It adds no record IDs, names, counts or new route.
Before each Review creation, the dated browser journey requires two idle API
observations within300 seconds and its original420-second testcase budget.
Direct manual dispatch and earlier test phases therefore cannot rely only on an
old release-time receipt. Two observations are not a lease: later relevant work
can still change an epoch, and the original source/access fence remains intact.

Notice has two independent conditions. Shared search legitimately retains GST,
which excludes the unrelated Payment recovery notice in the original test.
Separately, a disabled received-only reply filter incorrectly also excluded Sent
rows. Both local and linked-global Matter notices now ignore that reply filter
only on Sent while preserving its value for Received. Shared search and other
filters retain their existing meaning. The dated production test proves the
retained search exclusion, clears search visibly, and leaves the reply filter
selected to exercise the actual fix. Its90-second indexing assertion is intact.

## Verification And Limits

PR538's initial frozen candidate is a5f53f9a, tree a4c75db8. Its eight Security
jobs and three CodeQL jobs pass, but PR-scoped high-severity alert577 remains
open for the verification workflow's dynamic release checkout. This is a release
blocker, not evidence of an exploit or a new production deployment. A trusted
canonical-main ancestry admission and cache isolation amendment is being tested.
Do not dismiss the alert or predict its closure; require fresh exact-source
CodeQL/SARIF, complete CI and Docker proof after the amended source freezes.
The initial a5f Docker acceptance is retained separately, not transferred to a
different tree. Serving production remains0c82fbb0 and uncertified.

The first security amendment5fdf2f45 fixes577 without dismissal: Actions analysis
1958400371 has zero findings. The later Python analysis, however, opens high
alert578 on the new helper's input-derived receipt logging. The early zero-alert
snapshot is not final all-language clearance. Remove the unnecessary CLI payload,
preserve internal metadata and separate exact identity checks, then require all
current language analyses plus the final open-alert list before final expensive
acceptance. The staged workbook checkpoint25 was not published after this new
finding was discovered. This is candidate logging minimization, not evidence of
an actual credential leak or a deployed change.

Five complete local worker/operator modules pass259 identities/777 phases with
zero skips or retries. The new native PostgreSQL module passes4 identities/12
phases against an isolated local Docker PostgreSQL17. It proves2,000 retained
legacy failed receipts cannot hide current queue state, only two bounded SELECTs
are required, non-QA queues remain untouched, missing/inactive QA tenants fail,
and an actual claimed worker can finish while every observer transaction is
closed. The first four-failure fixture run violated the real execution trigger;
the second retained one fixture failure because completion omitted its required
timestamp. Both are preserved as fixture failures, not product reproductions.
The replacement uses the canonical legacy fixture and a real claim/attempt token.

Notice component coverage retains11 RED failures and25 GREEN passes plus web
and E2E type-checks. Fresh combined Docker/browser acceptance, CI, canonical main
merge, guarded deployment, full exact-release production replay, then two clean
post-QA private maintenance reports remain required. This document is a candidate
checkpoint, not a production certificate. LIFE13-01 remains Inconclusive.

The separate database-authority repair retains54 RED failures and178/178 final
passes across its two complete operator modules,534 phases, with no actual
cloud or secret-value calls. The new API tests and complete private workflow
module pass36 cases. A full frontend run passes1,337 tests across all204 intended
files with no skips/failures, and a fresh build plus E2E type-check pass. These
scoped pre-commit results do not replace the frozen combined gates below.
The complete combined eleven-module backend run subsequently passes679 cases
with2,037 ordered setup/call/teardown results, no skips and terminal exit0;
its collection and JUnit inventory reconcile exactly. New release-ordering
controls subsequently pass390 cases in their complete offline Docker modules,
after all six new RED failures were retained. The observer's explicit integer
single-task template is now checked before execution and again afterward;
19 new negative controls failed before that fix. Its two complete operator
modules pass199 cases/597 phases, preserving all178 previous identities.
These later scoped results still do not replace frozen joined Docker/CI or live
production acceptance. The governance map and both derived views validate;
the first stale-projection validation is retained as a repaired generation step.

Existing ownership remains J04/M03/US-007..009/FT-011..015 for document execution,
J07/M06 for notices, UJ-18 for Intelligent Review and ARCH-OPS-23/QG-SEC-004 for
release evidence. No new product entitlement, legal-source or provider policy is
introduced. Capacity partition details are in
`docs/bugfix-prod-acceptance-capacity-2026-10-15.md`.
