# Durable Document Execution And Production Certification - 2026-10-10

## Current Verdict

**NO-GO.** #527 is **Not fixed** on the serving production release
`3dbf364d9834316d181d4a52b2e9b4c7bee431b4`. PR528 and PR522 are merged;
API `caseops-api-00488-5sd` and web `caseops-web-00465-sk6` serve that exact
revision with one untagged latest-only 100% traffic entry each. PR529's
security-only repair is now merged onto canonical main
`dfda0eb3ee3d109f86092962a08d125878b24932`; it is not a newly deployed API/web
release. Fresh October 10 GitHub main-ref readback finds no open code-scanning
alerts. Draft license PR531's file-read-race finding is also fixed without
dismissal, but 19 actual license-policy rejections still prevent its merge.
The earlier "not deployed" checkpoints are history, not current serving truth.

This scope maps to existing US-001/M02/M03/M08/M13/M14/UJ36/UJ61 release
journeys and J19/M21/US-063/SEC-031 public discovery and evidence controls.
It adds no legal-source approval, consent or commercial commitment.

## Draft PR532 Checkpoint

[PR532](https://github.com/mishrasanjeev/caseops/pull/532) remains draft,
unmerged and not deployed. The initial checkpoint at `0fd0b74e` and its first
[CI run](https://github.com/mishrasanjeev/caseops/actions/runs/38058946001)
fails. The initial partial readback examined seven PostgreSQL failures and
reported shards two and three as cancelled/incomplete from job metadata.
That coverage claim is retained as an incomplete checkpoint, not current
native truth; the complete readback below supersedes it. The generated runtime
projection has now been refreshed locally without changing the reviewed
admission policy; replacement native/hosted proof remains pending.

The checkpoint's governance diff gate rejects migration 0002's absent purpose
marker before Ruff runs. A separate exact-base migration preflight identifies
four blocking index builds and two destructive no-paid-column downgrades in
0001/0002. These require real concurrent-index recovery and a reviewed
restore-forward policy, not blanket risk acknowledgements.

The PR-ref CodeQL report contains five new test-code findings (535-539): one
possibly uninitialized local, three cyclic imports and one mutation inside an
assertion. Local edits move the unchanged legacy receipt setup to a shared
test helper, initialize the savepoint variable explicitly and move `pop`
before its unchanged assertion. All four consuming test modules collect
264 identities and scoped Ruff passes. Collection is not execution; fresh
native and actual SARIF results are still required. Main-ref open alerts
remain a separate inventory, not proof that this PR is clean.

Agent broad replacements are still red: document r9 completes 331 identities
with 314 passes and 17 failures; court r4 completes 253 identities with 251
passes and two failures. No assertion, wait/lock budget or provider fence is
waived. Original reports remain retained while every failure is diagnosed.

### Complete Native CI Readback And Reindex Reproduction

All 13 API and four PostgreSQL artifacts from checkpoint `0fd0b74e` are now
retained and reconciled case-sensitively, including full failure details.
API: **8,815 identities, 6,326 passes, 2,409 unverified skips, 80 failures**,
24,036 phases. PostgreSQL: **2,407 identities, 2,392 passes, 15 failures**,
7,221 phases, zero skips. No duplicate, missing or extra identities/phases
remain; native finished events and JUnit agree. PostgreSQL shards two and
three have complete failing native evidence despite cancelled GitHub job
metadata. The shard plan sorts selection, whereas pytest preserves collection
order; exact selected multisets agree, not ordered plan/execution sequences.
Readback SHA256:
`f8348eb7d460b3556a36341fa01e18006bfb9ea7f9479424b61b1396d55f999c`.

The fifteen PostgreSQL failures include eleven stale-governance legal-hold
failures, three court-worker recovery/race assertions and one migration test
whose moving `head` expectation predates migration 0003. API failures include
governance-dependent paths, the new document/workflow import cycle, absent
Playwright dependencies in the Python-only shard, two historical actor checks,
dated gate-contract drift and an actual Contract reindex defect. These remain
open until complete replacement evidence, not merely a matching diagnosis.

Local checkpoint `fa300d36` refreshes the compiled governance projection without
weakening admission, extracts shared IP upload-target helpers to remove the
workflow/worker cycle, and installs the root Playwright dependency only for
the API shard whose exact selected inventory needs its offline CLI test.
Whole-module Main r16 reconciles **223 identities / 669 phases: 222 passes,
one failure**, no skips/errors, exact ordered collection/JUnit and unchanged
before/after source pins. Evidence SHA256:
`eb5d6a4d9d0bec9f47c7c8c747db2328a83b11e579f57a67af9711d7cd284b20`.
This scoped result is not final-image or production certification.

The remaining r16 Contract failure reproduces a real retained
`(attachment_id, chunk_index)` uniqueness collision. Detached preparation
replaced the ORM relationship, but orphan deletion followed new inserts.
The same Matter path requires correction. The proposed replacement deletes
the unchanged prior chunks only after the fresh Company/attempt/source/parent
fences, before new inserts, in the same finalization transaction. New native
controls cover consecutive reindex, parser failure, competing source changes
and post-deletion rollback. The new dated browser spec covers Matter's actual
Reindex control and Contract's public reindex API with its visible workspace,
at desktop/mobile widths, original byte preservation and exact release checks.
It is discovered by standard Docker and production configs. Typecheck and
four-case Docker collection pass; no browser execution, PostgreSQL replacement
or deployed-fix claim is made yet. Contract currently has no browser reindex
button; this evidence must not claim one was exercised.

Committed chunk correction `a91acd92` then completes Main r17: all **19 cases
/ 57 phases** in the complete Contract and document-worker API modules pass,
including the originally failing reindex. Ordered collection, JUnit and the
unchanged full-source pins reconcile. Receipt SHA256:
`f2750d59cc03ef9b5c39d41e56e2bda0759a7ebec602020536621552282df646`.
This is API replacement evidence only; the new retained-chunk PostgreSQL
interleavings and four browser journeys remain required.

Agent migration commit `7e723f67` is integrated as `06bb7850`: its separately
frozen controls reconcile **47 unit/SQLite passes and 29 native PostgreSQL
passes**, 76 identities / 228 phases, zero skips/failures. Four real index-build
cancellations preserve legacy TRUE and captured human FALSE, allow ordinary
insertion, recover matching invalid remnants and pass second upgrade plus
idempotent replay. Independent migration databases are removed. Populated
restore-forward refusal is proved; historical moving-head descent callers and
a fresh empty full-head rehearsal still require separate integration work.
No production mutation or provider entitlement is inferred from this slice.

The locked court-import actor correction `1e82ef95` is integrated as `42a34cb4`.
Compliance tail commit `f48f4774` is integrated as `b89cd0db`. Main r18 on clean
`e0fc0044` completes **120 passes / 360 phases**, zero skips/errors: all 34
historical Matter-team cases, five new actor-order cases, 58 compliance-protocol
unit cases, 15 data-class projection cases and eight IP projection-gate cases.
The initial estimated total of 121 is not the actual inventory. Exact ordered
collection, execution, JUnit and full before/after source pins reconcile;
receipt SHA256:
`da704cbbf27e12a36e3dae3741fbf90e3769baa4959e3d5a9bf981866932e59d`.
The 69-case agent PostgreSQL gate is still running. Three historical-tail
fixture failures currently mix a pinned old module with a current imported
helper; they are retained failures, not successful database-fence reproductions.
Require complete original results, exact dependency correction and complete
replacement. No assertion, lock budget or production fence is relaxed.
The governance map and compiled runtime projection are regenerated together
for **335 tables / 5,332 columns**, with the nullable execution marker reviewed
as configuration/state metadata. No retention, legal approval or general
disposition authority is added. Complete control-plane r2 passes **12/12**
commands during the r18 source-frozen window: program, ownership, architecture,
data-class/governance registries, governance-map validation/change review,
compiled projection, product guide, migration validation/change review and M2
ownership. All four changed migrations pass the canonical-base preflight.
The individually hashed command logs remain under `.tmp/control-plane-r2`;
the earlier 10-pass/two-failure r1 is retained. These scoped results are not a
fresh image, current hosted CI/SARIF or exact production proof.

### Complete Replacement CI Readback At 1d5eb65b

The later draft head `1d5eb65b` is still **NO-GO**.
[CI 38066864544](https://github.com/mishrasanjeev/caseops/actions/runs/38066864544)
completes all 13 API native inventories: **8,988 identities, 6,468 passes,
2,513 unverified skips and seven failures**, 24,451 phases. Ordered collection,
JUnit, selected files and completion agree without missing/extra identities.
The four PostgreSQL plans reconcile the complete **2,511** canonical identities,
but each hits the unchanged 12-minute job deadline. Their 6,182 retained phases
contain **2,044 passes, 16 failures, two partial tests and 449 not started**.
No final PostgreSQL XML or session-finished event exists: the full PostgreSQL
gate is **INCOMPLETE**, not a successful run or complete failure inventory.
Readback receipt SHA256:
`9a85aa60ee7bfa0d4cf35eb3ce7df600926e776e2978f50923a9fa47be46fd3f`.
Eight retained-chunk PostgreSQL interleavings pass all 24 phases inside that
interrupted run; this is scoped evidence, not full acceptance.

Every actual API failure is retained. Six historical migration journeys attempt
to descend from the new moving head through a restore-forward fence; their
fixtures need explicit pre-feature revisions and independent fresh full-head
rehearsals, not bypass flags. The seventh is the real offline Playwright CLI:
its shard selects the required file, but `rg` is absent on the hosted runner.
The shell conditional silently skips Node/Playwright installation, and one of
32 native Node controls fails without its required result file. Root npm
dependencies must be selected through required Python, with an exact validated
nonempty inventory and explicit true/false output.

The local dependency/partition replacement retains the 12-minute deadline,
expands native PostgreSQL CI from four to eight disjoint shards, and verifies
all eight real toy pytest launches plus aggregate rejection controls. Complete
Main r20 passes **76 identities / 228 phases**, zero skips/errors, unchanged
before/after full-source pins. Receipt SHA256:
`160a40cf523eaaa002821a6a37d46e330e39c88e7b92464f8bfe3b6fd36aaf95`.
This includes all 18 new execution-fence downgrade unit controls. Their earlier
complete r19 receipt is retained:
`b454951517084b3ea88c5e272c0a385afc678b0a6afab4f53936a3f0e47b9125`.
New native downgrade fixtures cover legacy queued/processing/completed/failed
receipts with both provider-policy values, a retained root with no document
job, and a separately fresh explicit empty rehearsal. These later native
fixtures and the corrected rolling-reader interruption/recovery race are
**not yet executed**; r20 must not be cited as PostgreSQL proof.

Fresh actual CodeQL at `1d5eb65b` clears findings 535-539 without dismissal,
but adds open note 540, a redundant snapshot assignment in the compliance
PostgreSQL test. Python SARIF has one result; JS/actions have zero results,
and all three have zero analysis errors/warnings. Receipt SHA256:
`6fdbb187de16c534dfd94460ce720acfc96d04020b14b225c540fa0f31c224cf`.
A successful CodeQL job is not a zero-result candidate. Replacement remains
required. The four new dated reindex browser cases are independently discovered
by both Docker and production configs with distinct native identities, receipt
`391cf415ba51647c8c6c9c535e619ea422dbebe2788057564c4d6de8923ffd7b`;
collection is not execution. No new production deployment, closure or private
cadence resume has occurred.

Complete Main r21 then replays all five deployment/evidence/planner/partition/
downgrade unit files, including the existing deployment assertions updated to
the exact eight-shard manifest. **408 identities / 1,223 phases: 407 pass,
one unverified Windows POSIX-mount-policy skip**, no failures/errors. Ordered
independent discovery, incremental results, native JUnit and full before/after
source pins agree on committed `2b960bbe` plus the captured deployment-test
diff. Node **22.23.3** runs the actual offline reporter/Playwright CLI contracts:
all **32** native TAP controls pass with zero skips/cancellations. Its real
two intentionally failing synthetic API responses are retained by the reporter;
they are offline negative controls, not production failures or paid calls.
Receipt SHA256:
`6352b3420942e2b40b052ff98cccc3426992c463090b0bfb4b811bb571c9ce62`.
This is scoped replacement, not Docker/native migration/live certification.

Sidecar test-only follow-ups are ready: the expanded historical fixture audit
passes all **28** unit/SQLite identities (84 phases), including all six dated
API failures, with independently fresh named-revision rehearsals and separate
head health. Its original 14-file/20-call claim was not exhaustive; computed
head callers and helper-return targets are now explicitly inventoried. The
compliance helper-closure replacement passes **63** unit identities (189
phases); the original complete PG69 is retained as **65 pass/four failures**,
not a successful counterproof. Main independently rehashes **71** sealed files
across these follow-ups, zero mismatches, receipt
`34be7db0bcf5a6e7beb7a7c912a6f4acb5fa33a78c1971840e98a9b5b6dc74eb`.
Those test-only commits are now integrated into clean checkpoint `9b524ab6`.
Main r22 replays all ten complete changed unit/SQLite modules: **109 passes /
327 phases**, zero skips/errors. Independent ordered collection, native JUnit,
incremental phase journal and full before/after source pins agree. PostgreSQL
selections are excluded from this unit verdict, not certified or silently
counted as skips. Receipt SHA256:
`75f5bb080c435499ece39199780339a567eb04bd011c43764f60988e8c0e5e6e`.
All twelve refreshed control-plane commands and scoped Ruff pass on that
checkpoint; these are not full-image or serving-release evidence.

Fresh [CodeQL 38071812898](https://github.com/mishrasanjeev/caseops/actions/runs/38071812898)
completes all three actual SARIF analyses with **zero findings, errors or
warnings**. Python analysis 1929235691, JavaScript/TypeScript 1929229642 and
Actions 1929225736 belong to hosted merge `2dee84bd`; its exact tree matches
`9b524ab6`. PR-ref open alerts are zero and alert540 is fixed without
dismissal. Receipt SHA256:
`6ff4344ef18dada3f7f309243a354ef621c0cfc22fd0d7c68a83abbefdb5a36b`.
This resolves that static finding, not the inherited license-policy decisions
or production certification.

[CI 38071812851](https://github.com/mishrasanjeev/caseops/actions/runs/38071812851)
still has an incomplete API readback. Web typecheck/unit/build passes.
All eight PostgreSQL shards have complete native evidence: **2,514 identities /
7,542 phases: 2,508 pass, six call failures**, zero skips/partial/not-started.
All eight full canonical collections and exact partitions agree; native JUnit
and completion events agree. Main independently rehashes 91 sealed evidence
files with zero mismatches, receipt SHA256:
`050ab575961c973518ef20a10bd41034bbddab2222f304959f9bd65484581916`.
All 55 document-protocol cases, both real rolling overlap variants and four
retained/empty/root-only rollback controls pass. Those scoped positives do
not waive the complete failing run.

All six failures stop before their intended guarded operation: three positive
legacy tails lack a staged deadline, and three historical replay fixtures
violate access-review insertion order, omit semantic patent application
parents, or misclassify an initial `root_id=id` as a cycle. Full original
tracebacks and native sections are retained. Keep the production guards;
these are not successful guard or migration reproductions.

Legacy parser correction `8ead8e2a`, integrated as `82f382e1`, uses an explicit
dated source and matching retained hash. It asserts exact item/task/deadline
dates and links before expecting SQLSTATE55000, and separately keeps the
actual old parser's ambiguous-source undated behavior under regression.
No production parser or execution fence changes; complete native replacement
remains required.

API shard eight has a separate complete failing workflow-contract assertion
that still expects the removed optional `rg` selector. The correction requires
the actual Python CLI, exact selected-files/output arguments and unchanged
Node/install ordering. All seven complete result-journal module cases then
pass in Main r23: **21 phases**, zero skips/errors, independent discovery,
JUnit and unchanged source pins. Receipt SHA256:
`356f7196e8b473e7d9089b2f19f774c855e85c5160bf2c3ac8f4cad9762d7890`.
This is a scoped correction, not full API or Docker/live acceptance. The fresh
hosted shard eleven actually selects the offline evidence file, installs Node
and Playwright, and passes; the unrelated singleton shard thirteen correctly
does not select those dependencies.

The complete Court/participant replacement r5 independently reaches
**263 identities / 789 phases: 262 pass/one failure**, zero skips/errors.
The new `[text-mutation-retry]` failure is an actual Company `55P03`, separate
from the original no-source update failure. A four-case measured diagnostic
passed with unchanged budgets, and the five-case isolated recovery/counterproof
passed, but neither closes this broader failed run. Exact retry-holder timing
and a complete replacement are required; do not assert CPU contention or
raise budgets. No new deployment or production closure follows these results.

The complete measured r6 replacement on owned `f1c91fff` and schema
`20261010_0002` then passes **263 identities /789 phases**, zero skips/errors.
All original ordered identities and 186 native journals reconcile, and all
fourteen owned databases are verified absent. Main independently verifies
its 199-file seal with zero mismatches, receipt SHA256:
`8fd63382cfa09e88d758e978866133b6b801081e0b95f749cfb97d14e3e16bab`.
The 20/500-recipient all-SQL budgets remain 394/400 and 7114/7600 with no
diagnostic observer SQL in those performance cases. The exact retry's measured
release-to-holder-commit is 0.548915 seconds under unchanged two-second lock
and ten-second statement budgets. Five other cases have incomplete sampler
coverage because the diagnostic observer rejects their valid owned clone
names; retain the full warnings. Functional results are complete, but this
instrumented older-schema slice is not Main0004 or serving-release proof.
R5's uninstrumented 2.170158-second interval remains causally Inconclusive;
do not infer CPU causality or relabel its genuine 55P03 as fixture drift.

### October 11 Packaging And Final-Candidate Checkpoint

The complete API readback of CI38071812851 reconciles **9,053 identities /
24,643 phases: 6,536 passes, 2,516 unverified skips and one call failure**
across all thirteen whole-file partitions. No identity or phase is missing,
duplicated or extra; completion and JUnit agree. The sole failure is the old
selector-contract assertion corrected above. Receipt SHA256:
`cc91b507f40f16bac6fec1510c5a32526fa4c4af726ad5049622a11feed95d2c`.
The skips are not verified coverage. Native TAP from the hosted wrapper is
not independently downloaded; the separate local TAP remains retained.

Reviewed replay corrections `09b3635e`/`e594267b` are integrated as
`8a5315cc`/`5f4e70a8`: reconstruct the captured open campaign, insert its real
decisions and execute actual guarded finalization; seed both semantic patent
application parents; exempt only the declared initial self-root. All replay
stages share pre-insert capacity. The old helper's two retained counterproofs
observe 65 and 68 INSERTs; the replacement rejects before excess admission and
keeps a 63-row positive finalization. Its complete two-module unit evidence is
35 passes/105 phases, with no skips. Main independently verifies 17 sealed
artifact/source hashes; agent seal SHA256:
`a35fd6f45d10c0e9ccd8866ae1ce9b1f39fa28f700a7b7ecde686a0bcafdd8bb`.
Independent read-only review finds no weakened guard or assertion.

Main r24 on source-stable `5f4e70a8` reconciles all sixteen selected modules:
**529 identities /1,586 phases: 528 passes, one unverified POSIX-mount-policy
skip**, zero failures/errors; local Node22 TAP contains 32 passes, zero skips
or cancellations. Receipt SHA256:
`9467d741d6053610072e9424178574f3d205decc9cd73b4002acdac642591f36`.
Docker's host dependency synchronization removed optional packages from the
borrowed Python environment during that run. Source remained stable, but this
is not frozen-runtime final certification; the replacement uses its own
frozen environment. Preserve the failed first hardlink-based environment
setup and use the established copy-mode installation rather than deleting
another run's environment.

Fresh [CodeQL38075836594](https://github.com/mishrasanjeev/caseops/actions/runs/38075836594)
on exact `5f4e70a8` has three actual SARIF analyses, zero findings/errors/
warnings and zero open PR-ref alerts. Its hosted merge and head trees agree;
receipt SHA256:
`6cb2154b25abec0f3f99b6cd9eebbc110f3aeb82ab86e60e51623940d0b8c40e`.
Main-ref open alerts also remain zero. This is exact-tree scanning proof,
not production or license-policy certification.

The first exact-source Docker attempt fails before PostgreSQL or browser
execution. Next's actual container type check cannot resolve the shared
`bounded-network-evidence` and `prod-api-response-evidence` helpers imported by
colocated web tests. The latter also imports `cost-controls`. The source-tree
CI web build passes because those files exist there; its success does not
certify the narrow Docker/Cloud Build context. Retain the original build error,
API build cancellation and failed wrapper completion. Repair explicit
builder-only copies and both ignore policies, regress the dependency closure,
and require a real web-builder build in standard CI without suppressing types.
Fresh CI38075836642 is not yet a complete reconciled release result.

Production remains `3dbf364d`, private cadence paused, with no new independent
Docs/Court jobs or triggers. No merge/deploy/issue closure follows the scoped
results. Full fresh candidate Docker, complete native CI and exact-production
browser/cadence certification remain required; license policy, Google-reported
noindex exclusion and owner-kept consent/provider gaps remain open.

### Reviewed Packaging Replacement And Isolated Replay

Packaging repair `26e4d89a` is integrated as `19f12ec8`: explicit direct and
transitive helper copies, matching narrow Docker/Cloud Build admission, and a
required real web-builder CI step after the source-tree build. Strict Next
type checking and runner copies are unchanged. Independent review finds no
actionable defect; Main rehashes 33 sealed artifacts/source files with zero
mismatches. The complete deployment-contract module has 230 passes/one known
unverified POSIX-only skip, 231 identities/692 phases. All twenty packaging
controls pass, with three pre-fix failures retained. Agent seal SHA256:
`cab985aaf77dbf01af2f883f72e495c5231199bf8162d042eac1fdc14025d869`.
The literal-import inventory is supplemental; actual compiler/context proof
and fit within the unchanged fifteen-minute CI web-job budget remain required.

Main r25 on clean `19f12ec8` uses its own frozen Python environment. All
seventeen selected modules reconcile **558 identities /1,673 phases: 557
passes, one unverified POSIX-only skip**, zero failures/errors. Full source
pins and installed distribution versions plus METADATA/RECORD hashes agree
before/after; actual local Node22 TAP has 32 passes, zero skips/cancellations.
Receipt SHA256:
`98afc45533da3a843629ab0c79c2a8ecaaebbcf8dc43789c5d15b6cc9ebe470d`.
This replaces r24's shared-environment limitation, not final-image/live proof.

The earlier exact `5f4e70a8` hosted backend replacement is now complete:
**9,076 API identities /24,712 phases: 6,560 passes and 2,516 skips**, zero
failures, thirteen exact whole-file partitions. All eight PostgreSQL shards
have **2,514 passes /7,542 phases**, zero failures/skips, including the six
original failures, all69 compliance cases and all18 dated migration cases.
Main independently rehashes 89 PG artifacts and 307 immutable source blobs
with zero mismatches. API receipt SHA256:
`cfc2317e38233cf1b9362220de0637f33422fa9c00b545cc993d8a30facc43be`;
PG readback SHA256:
`cc17ac367fc5e1cf7c5c7c3305d43c017a595bac57956edf47e93f7a92683670`.
Its initial auditor ordering error remains retained and incomplete.

Exact identity reconciliation proves every one of the2,514 API PG exclusions
has a native PG pass in that same head. Combined unique passes are9,074;
the remaining two skips are opt-in native fastembed-model acceptance and the
Windows gcloud command-shim case on Linux, still unverified by that hosted
cohort. Combined receipt SHA256:
`2cfdc23a6e05f8a792233a98c9b6cbbcd9ac5f7a5ade6195505dafed7350ec4c`.
The earlier complete failed runs are not overwritten. This earlier backend
proof and clean SARIF do not certify the packaging-corrected candidate or its
still-required full Docker/CI/browser and serving-production release gates.

### Complete Hosted Browser Failure And Contract Repair

CI38075836642 on head `5f4e70a8`, actual checkout `6fe50e8f` with the same
tree, finishes **512 identities: 490 pass, 17 unverified skip, five fail**.
Native collection, JSON/XML, incremental journal and completion hashes agree;
there are no omissions, duplicates, retries, interruptions or global errors.
Execution order differs from canonical report order and is retained separately,
not silently rewritten. Every skip has its actual runtime reason and source.
Original artifact11680440610 SHA256:
`d452aee55d5790b077cf93bc493f8bd3519366dce48cd4d8f4a7579167b6833d`.

All five complete error contexts establish contract drift, not five proven
product failures. Four Matter/Contract desktop/mobile journeys complete the
initial durable index but fail at the exact capitalized `Indexed` locator;
the shared badge lowercases DOM text even when CSS capitalizes it visually.
Neither reindex nor final original-byte download was reached. The diagnostic
case expects a body-derived problem type, but both bounded collectors
intentionally avoid decoded-body allocation and return explicit null. Typed
sanitizer unit positives do not prove runtime body capture. Its later timing,
transport and privacy assertions were not completed either.

Agent `ce8d79c0`, integrated as `91486e85`, changes only those two specs:
exact lowercase badge checks at both locations and explicit null diagnostic
expectation. All original source hashes, job identities, two reindexes,
responsive visibility, byte equality, timeouts, retries and privacy controls
remain unchanged. Independent actual-patch review finds no weakening. Agent
E2E typecheck passes on Node24; browser replay remains **Inconclusive**.
Main independently verifies586 sealed files and229 immutable source blobs,
zero mismatches. Receipt SHA256:
`1e2bb82c9db54aa02230af3e02d429b53e6211cfa2650135de7baacbf81a7c97`.
The first ordinary Windows long-path reader failure remains retained; the
complete replacement uses extended-length paths without rewriting inputs.

Docker307 R2 stops before building because the retained R1 subnet overlaps;
it is a setup failure, not a PG/browser result. R3 uses a fresh isolated pair,
builds both real images, proves exact API/web identity and internal origin,
and passes current0004 schema/index checks including the production memory
ceiling. It collects2514 PG cases before Main supersedes it for the browser
correction:623 passed calls, zero recorded failed phases, no completion event
or final JUnit. This is **incomplete**, never full acceptance. The original
journal SHA256 is
`b2e610e60682034a6ae9d320bf4458a6ead2ccb2577e9cd6968ff9ba76f740c1`.
All seven owned containers, two volumes and two networks are removed by exact
project labels, with empty post-cleanup inventories; unrelated workloads and
earlier failed evidence remain untouched.

Require the complete fresh corrected-head Docker/CI/SARIF and exact serving
production replay. No merge/deploy follows this correction. Parent Search
Console access remains available despite the reviewer's empty browser context:
one authorized read-only refresh still reports /sign-in indexed, with its
September22 crawl blocked by robots. No crawl/submission is repeated; #521,
license policy and owner-kept consent/privacy/provider dependencies stay open.

## Exact Failed Evidence

[Production verification 38036444501](https://github.com/mishrasanjeev/caseops/actions/runs/38036444501)
attempt 1 completed all six serial shards: **341 identities, 320 pass,
18 unverified skips and three failures**, without retries, missing identities,
native mismatches or global errors. The readback retains original JSON/XML,
ordered collections, incremental attempts, progress and all 64 native digests.
Main independently rehashed all **2,936** sealed files with zero mismatches.
Evidence seal SHA256:
`7aa7e4013ba81817c81e67aba0f28aec1009924a67aca8c01de57fe00c385b8f`.

| Journey | Actual response on API 00488-5sd | Corroborating SQL |
| --- | --- | --- |
| Notice sent attachment, spec line 173 | POST attachment 503 at 08:46:53 UTC, 5.047 seconds | Company NO KEY UPDATE lock timeout at 08:46:58 UTC |
| Patent parties, spec line 59 | POST patent application 503 at 08:56:27 UTC, 5.066 seconds | Company NO KEY UPDATE lock timeout at 08:56:32 UTC |
| Patent priorities, spec line 57 | POST patent application 503 at 08:58:14 UTC, 5.048 seconds | Company NO KEY UPDATE lock timeout at 08:58:19 UTC |

The temporal/route/revision evidence strongly corroborates one shared lock
mechanism. Historical holders, request IDs, problem bodies and a direct
HTTP-to-SQL-process linkage were not captured; do not invent those identities
or attribute the historical lock to a particular uncaptured worker.

A fresh unchanged Notice diagnostic passes **2/2** on 3dbf, not a waiver of
the failed full dispatch. A read-only observer subsequently captures document
private-projection finalization idle in transaction after the browser journey,
up to **5.786345 seconds**, while Cloud Run uses request-based CPU throttling.
This establishes an unsafe execution boundary; attribution of the original
historical holder remains an inference. All 90 observer samples are read-only,
bounded and complete; receipt SHA256:
`bb55c9455b0ddab60ea105034fb62b86e3bd4a535e3b169422c61335cf557d53`.

Read-only queue inspection at 10:03 UTC finds **11 processing jobs** whose
oldest enqueue age is approximately 154 days and **three queued jobs** whose
oldest age is approximately 92 days. No Contract/IP pending group is returned.
This is actual missing crash-recovery evidence, not a fabricated incident.
Receipt SHA256:
`fd75e16b1968dd70d9853a00533f4fa6dc717b40f32799d781af50a53434e19a`.

## Repair In Progress

**Partially implemented; candidate verification is Inconclusive.** Relocate
execution of the existing durable DocumentProcessingJob queue from production
Starlette after-response tasks to an independent, exact-image document worker.
Do not introduce a second domain workflow or an ad hoc in-memory queue.
Production never falls back inline after a denied/timed-out wake-up. Admission
is committed before the bounded no-override job wake; the API owns no database
transaction during external transport. A minute cadence recovers missed wakes.

Atomic claims, bounded stale recovery and attempt-fenced finalization must
prevent overlapping workers or a reclaimed old attempt from persisting output.
Release the database transaction before parsing/provider I/O, then reacquire
current parent lifecycle, membership/access, source provenance and Company-first
private-generation authority before final persistence. Retain every existing
security fence and the 5,000-ms lock budget. Unknown legacy jobs are no-paid;
new jobs persist and restore the authoritative automated-request marker.

The documents-only worker must not poll courts, generate case summaries,
automatically replay failed jobs, run migrations or call billable providers for
automated work. Scheduler/IAM/image/readback and release draining require native
regressions. Preserve request-based API billing, capacity, scanner and deadlines.

The Notice browser contract now requires all three exact uploaded attachments
to finish indexing, have completed jobs and extracted content, and survive a
page reload. Mutation retries remain forbidden. Bounded sanitized network/API
diagnostics must retain decisive failed writes instead of navigation floods,
without raw response bodies, URLs, record IDs, credentials or personal data.

Provisional Main targeted replay r3 completes **246 pass/one unverified
POSIX-only skip** among 247 identities, with 740 setup/call/teardown records and
a session-finished receipt. Source formatting overlapped that run, so it is
provisional, not frozen release proof. Earlier r1/r2 failures remain preserved.
Fresh final-source collection, migration/claims PostgreSQL races, full Docker,
browser, build and hosted CI gates still precede a normal PR merge and guarded
exact-main deployment. Full production replay and two later clean private
maintenance executions precede certification and private cadence resume.

Fresh full Main r10 completes **392 passes and one unverified POSIX-only
skip**, with 393 ordered identities, 1,178 incremental phases and a matching
session-finished/JUnit receipt. The Windows skip is not coverage of an
exec-disabled POSIX filesystem. The document and court
dispatchers release read-only transactions before bounded Google Jobs wakes;
missing wakes never fall back to production after-response execution. The
complete deployment-script suite is included in this scoped result. A later
runtime-bound replacement r11 completes **196 passes / 588 phases**, zero
skips/errors, with exact collection and native result agreement.
Agent PostgreSQL evidence is scoped to its exact committed inputs, not yet
proof of the integrated final image. Database rolling-writer fences and the
legacy-to-independent-worker handoff remain under implementation/review.

Main r13 completes **415 passes / one unverified POSIX-only skip**, with
416 ordered identities, 1,247 incremental phases and matching final JUnit.
The later r14 runtime-control replacement completes **221 passes / 663 phases**,
zero skips/failures, identical collection/execution identities and unchanged
before/after source pins. It rejects both desired and resolved traffic drift
and service-level manual scaling. These results do not replace broad
PostgreSQL, final-image Docker or production acceptance.

The actual frozen 3dbf worker commits indexing before a separate compliance
transaction. Fencing its document-job receipt alone cannot reject that tail.
An explicit root-run persistence protocol is required across manual, current
worker and court callers; no legacy auto-stamp, physical-stop claim or provider
cancellation is implied. Its migration/counterproof remains pending.

The first all-historical native stop probe is **Inconclusive**: 8,624 read-only
Monitoring requests, zero mutations, then a bounded timeout. Its failed
receipt and unchanged before/after source hashes are retained under
`.tmp/worker-stop-native-r1`. Cloud Run metrics expire after six weeks; missing
old series are not zero instances. Requiring every retained historical
revision's expired telemetry cannot produce a usable release gate. A bounded,
primary-source-backed read-only r2 classification now reconciles all 487
retired revisions with **106 native measured zero results** and **381 explicit
platform-contract inferences**, using 106 Monitoring requests and zero writes.
Receipt SHA256:
`f927fabd4ac4284f1bbe496aa482ad085d779bca82911905ff0a0eaa63db3bef`.
Expired history is not assigned fabricated zeros. The inference requires
stable untagged/unreferenced retirement, no effective minimum allocation,
automatic scaling and request-based CPU. The retained r2 receipt used an
unsupported timeout/idle/shutdown arithmetic premise and is **not final proof**.
The corrected source records historical autoscale retirement as an operational
inference only, not a physical execution deadline or missing-metric zero.
It cannot release earlier locks or cancel already-issued provider work; the
independent compliance-tail barrier is required before legacy persistence is
fenced. A fresh corrected native preflight is still required. The captured
currently serving prior revision must always have
positive native active/idle zero evidence after routing, even on a resumed
rollout. No revision deletion, credential rotation or admission enablement
has been performed as a waiver.

Corrected read-only r3 completes with **105 native measured zeros and 382
explicit operational-retirement inferences** among all 487 retired revisions,
105 Monitoring requests and zero writes. The moving six-week retention boundary
accounts for the cohort change; missing series still never become zeros.
Its receipt explicitly denies physical-stop proof for expired history and
records the compliance-tail barrier as unverified. Source pins match before
and after; receipt SHA256:
`c1d0091b8d03af46d615648114d3a65b0d4d4bd267e98d0585e79767d45867c5`.

## Security And External Boundaries

All 28 original code-scanning alerts are actually fixed, not dismissed.
PR529's actual hosted CI, Security and CodeQL attempts are successful; all three
fresh PR SARIF reports have zero results, errors and warnings. Main independently
rehashed 3,260 sealed evidence files with zero mismatches. The earlier 25 Python
note findings belong to retained historical evidence, not these new reports.
This is exact-tree scanner evidence, not a blanket security certificate.

The old secret scan examined zero commits/bytes. Its merged replacement retains
the unchanged reviewed exception policy and passes all 38 native controls,
including real offline Gitleaks fixtures. Hosted scanning actually examines
2,680 tracked files and all four changed commits, including merge resolutions.
The accepted hosted merge tree `9837fcabf8e8a4d89b399bc79e50193444b783cb`
matches canonical main's merge tree. No worker repair is certified by this
security-only result.

The inherited license artifact is still `{}`: four bytes and zero packages.
The original draft at `6cb037ab` exposed 20 rejections. Its replacement
`3616820e` corrects SPDX OR evaluation and descriptor-bound JSON reading,
passing **140/140 native and hosted controls**, zero skips. It reconciles
200 runtime locations / 166 package-version identities with **19 actual policy
rejections and zero inventory errors**. Local inventory includes 42 optional
lock-only locations; hosted inventory includes 37. OFL, LGPL, MIT-0 and Zlib
remain unapproved under the unchanged allowlist, not vulnerabilities or green
license certification. All three fresh CodeQL SARIF reports have zero results;
alert 534 is fixed, not dismissed. Main independently rehashed all 95 sealed
license evidence files with zero mismatches; manifest SHA256:
`6e2cba1ca476e8901f351395613974e4dcc1f215ee1af713a9c6b4edc858f748`.
Hosted Security fails on the real policy rejections. PR531 remains draft,
unmerged and not production-certified; #530 stays open.

#515 has 40/40 exact-release public-content passes, with closure deferred to
the replacement certified release. Stronger mobile/desktop persona/pilot
assertions additionally complete a **23/23** native local public-content
diagnostic, without retries or missing identities. It reads the retained
Docker image `a968c614` whose public source tree matches serving `3dbf364d`;
it is not new-image acceptance or a fresh 40-case production result.
Reconciliation receipt: `.tmp/public-pilot-docker-diagnostic-r1-reconciliation.json`.
#513's privacy-first lead admission keeps
GA4/client telemetry disabled; sender/privacy/retention consent is still open.
#521's crawl-policy correction is deployed, but Google-reported noindex
exclusion is not proved. Fresh owner-authorized Search Console readback on
October 10 still reports `/sign-in` indexed though blocked by robots, with the
last crawl September 22 at 02:08:14. No crawl, sitemap or validation submission
was repeated. Calendar's automatic candidate passes; actual human
Google consent remains unverified. Previously owner-kept provider/legal identity,
Workspace, sender, merchant and license dependencies stay open. Never count
synthetic production leads, paid automated probes or skipped consent as proof.

## Permanent Learning

A green deploy, zero open alerts or one successful replay cannot certify a
failed full production inventory. Request-based Cloud Run must not do database
finalization after its response; a durable admission alone also needs atomic
claims, bounded expiry and stale-attempt rejection. Persist automated no-paid
policy across execution boundaries. Preserve failed evidence and identify
uncaptured causality as unknown. A green scanner that examined zero bytes is a
coverage failure, and bounded diagnostics must prioritize failed mutations.
An empty license inventory is equally incomplete; report actual policy
rejections rather than silently electing new terms. Expired monitoring evidence
cannot certify a stopped process and must not turn into an unbounded polling
loop or an impossible historical release requirement.

Official runtime basis: [Cloud Run general tips](https://docs.cloud.google.com/run/docs/tips/general),
[billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings),
and [Jobs run API](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run).
