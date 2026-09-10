# Other IP Resume: September 10 Checkpoint

Owner: other-IP track. IPLF-090A, 090B, 091A and 091B remain **PARTIAL**.
Full-domain closure and activation: **NO-GO**. This is not ten-domain completion.
The earlier September 09 report is historical; this checkpoint supersedes its
three-table inventory and intake-only descriptions for DES/COPY/LIC, but does not
inherit its PostgreSQL results as proof for the current eight-table workflow code.

## Ownership

Only `C:/Projects/CaseOps/caseops/.worktrees/codex-other-ip-domains-closure-20260909`
was edited. Branch `codex/other-ip-domains-closure-20260909`, unchanged HEAD
`5145fb3a4b51b26af116220ff10a7389bde6324d`. Inherited dirty files remain in place.
No parent snapshot copy, parent edits, commit, push, production action, paid test,
global cleanup, Docker container or shared database mutation occurred in this
resume. The parent provider/September 10 changes are not present in this candidate
and must not be overwritten from it. This worktree is not a serving revision.

`baseline-owned-files.json` records the initial selected file hashes;
`pre-final-owned-files.json` records the source before the final backend and initial
UI runs. Backend bytes are unchanged since that snapshot. Two later UI-only
reference-paging regressions are covered by `web-reference-04`, not `web-final-02`.
`owned-files-final.json` records exact owned files, separately marked shared hunks,
the untouched patent-owned catalog, and every retained JSONL/XML/log artifact.
Full-file hashes of shared paths are comparison aids, NOT permission to replace
the parent files. `.other-ip-test/deps` is local openpyxl test tooling only and is
excluded from integration. The parent virtualenv interpreter was reused read-only
with bytecode generation disabled; no package was installed into that virtualenv.

## Product Delta

The inherited unfinished source-reported workflow implementation was resumed,
not represented as a fresh full-domain implementation. New `.2` child PRDs cover
DES/COPY/LIC only. Their exact bytes are pinned by service contracts; retained
`.1` record versions remain readable. Admission requires the current per-domain
contract, not the older intake-only registration. Seven other domains retain `.1`.

| Scope | Current functional surface | Actual normal/exception evidence |
| --- | --- | --- |
| DES-01 / UJ-41 | Versioned representation sets; source-reported application stages, publication instruction and supplied renewal facts; distinct variant, rights-claim and cancellation records | `test_design_representation_versions_application_and_separate_cancellation`: retained set revisions, variant jurisdiction/root checks, filing/registration, publication gate and separate cancellation; shared stale source/tenant/replay test |
| COPY-01 / UJ-42 | Deposit versions; optional source-reported application/registration; separately reviewed rights claims and platform/court/registry proceedings | `test_copyright_rights_claims_are_independent_from_registration_and_platform`: ownership claim review, registration independence and platform-vs-court rejection; shared stale source/tenant/replay test |
| LIC-01 / UJ-43, UJ-30-EXC-02 | Reviewed instrument and issues; effective periods, recordal and termination; supplied-date contractual obligations with canonical task/deadline; persisted performance and confidential nonbillable cost evidence | Licence workflow test plus ten performance cases: completion/cancellation/notice replay and reload, retired/current instrument checks, atomic rollback, same-day close/reopen/second-close without child resurrection, voided cost replacement and finance reauthorization |
| IP-SCOPE-08 / all ten types | Restricted history/access; every specialist document link prevents general AI, portal, export and notification eligibility even alongside an ordinary trademark link | Ten populated mixed-link disclosure cases, retained byte read, private-builder exclusion, positive trademark sibling, plus intake/current-access/lifecycle and inherited boundary tests |

The resume repaired obligation-link/event migration columns and composite
tenant/docket FKs; actual SQL diagnostics exposed the missing `docket_id` column.
It added current-instrument and original-clause revalidation at obligation creation
and performance. Current active cost lineage and confidential-finance permission
are rechecked at every dependent command. Cost creation and voiding adapt the
existing canonical cost owner: category `other`, confidential, nonbillable,
actual/estimate evidence only. This is NOT royalty calculation, invoicing,
payment reconciliation or a generic specialist finance subsystem.

The UI now has paginated persisted obligations/performance, source and canonical
active-cost choices, cost evidence creation/voiding, retained rejected inputs and
read-only terminal history. Successful mutations update the cache and invalidate
authoritative lists. Seven focused workflow UI tests cover success without error
feedback, rejected input retention, discovery loading/failure, terminal read-only
history, sourced cost creation and independent reference paging. The reference
page reuses already loaded authoritative list data, fetches at most ten records
per deliberate page action, retains unsaved fields and selected cross-page pins,
and distinguishes an old selected source revision from its newer current revision.
Failed reference discovery prevents save but still permits cancellation. Vitest
DOM checks are not responsive visual QA.

## Verification

All new pytest journals are incremental setup/call/teardown evidence, not progress
character interpretation. Each attempted result remains in its own file. No failed
report was overwritten. SQLite results do not certify PostgreSQL locks or triggers.

| Attempt | Actual result | Classification / reconciliation |
| --- | --- | --- |
| baseline-01 | Import failed before journal initialization: openpyxl unavailable | Tool output only; incomplete test attempt, no product test result. Worktree-local dependency target supplied the missing library. |
| baseline-02 | 4 failures | Each structured failure inspected: Windows long-path fixture upload errors, not four product reproductions. |
| baseline-03 | 2 passed, 2 failed | Individual failures: workflow database 503 and invalid `.test` email fixture. |
| red-04 | 6 failed | Five paths blocked by missing migrated `docket_id`; SQL evidence retained in journal. Those failures did NOT reproduce their intended stale-source assertions. One old-contract admission test returned 201 and reproduced the contract gate defect. |
| workflow-05 | 8 passed, 2 failed | Individual fixture/assertion defects: canonical task starts `todo`, not `open`; duplicate upload bytes reused the source identity. |
| backend-06 | 60 passed | Complete journal; superseded by larger final selection after cost/performance changes. |
| performance-07 | 7 passed, 2 failed | Individual failures: closed-parent guard returns 404; generic cost routes correctly reject non-trademark records. No generic domain allowlist was weakened. |
| performance-08 | 8 passed, 1 failed | New adapter used an unsupported canonical cost category; corrected to existing `other`. |
| backend-final-09 | **64 passed**, 0 failed/skipped, 163.45 seconds | Exactly 64 setup, 64 call, 64 teardown passes, one exit-0 completion. Every earlier selected backend identity is in this replacement inventory. |
| web-01 | 10 passed | Intermediate UI result before the final cost surface. |
| web-final-02 | **11 passed in 3 files**, 0 failed/skipped | 5 workflow UI, 4 workspace UI, 2 strict API-schema tests; retained XML and log. |
| web-reference-03 | 12 passed, 1 failed | Full structured failure inspected: success callback returned the expected record plus TanStack Query context arguments; test incorrectly expected exactly one argument. No product guard was relaxed. |
| web-reference-04 | **13 passed in 3 files**, 0 failed/skipped | Complete replacement inventory: 7 workflow UI, 4 workspace UI, 2 strict API-schema tests. Includes reference paging, exact source-version selection, retained edits, bounded request count and failed-discovery cancellation. |

Final backend inventory, reconciled by exact collected node identity:

| File | Collected |
| --- | ---: |
| `tests/test_ip_specialist.py` | 29 |
| `tests/test_ip_specialist_workflows.py` | 4 |
| `tests/test_ip_specialist_performance.py` | 10 |
| `tests/test_ip_specialist_schema.py` | 1 |
| `tests/test_ip_specialist_disclosure.py` | 10 |
| `tests/test_ip_domain_boundaries.py` | 10 |

Run with `scripts/tests/run-other-ip-local.ps1`, explicit six-file selection,
Python 3.13.14, pytest 9.0.3, mock LLM/embedding providers, HF offline,
`PYTHONDONTWRITEBYTECODE=1`, and dedicated short `C:/tmp/oip-resume-0910-*` storage.
The HTTP fixture sends `X-CaseOps-Automated-Test: no-paid-providers`.
`static-reference-04.jsonl` records the final full web/E2E typechecks, owned-backend Ruff,
scoped whitespace checks and Playwright discovery with explicit command exits.
Discovery lists six tests in two dated specs at 393/768/1280. **Neither browser
spec has executed in this resume; no screenshots, browser timings or production
outcomes are claimed.** Dependency installation was tooling setup, not a security
audit. An extra npm invocation with no workspace lock failed before testing.

Prior-agent workflow failures in `C:/tmp/caseops-other-ip-20260909` also remain:
workflow-unit06 (four lifecycle-token minimum failures), workflow-unit07
(three passes, one duplicate-tenant fixture failure), workflow-web08 (wrong
`apiRequest` import). Each failure was inspected. The four original workflow test
identities and corrected frontend import are covered by the current replacement
inventory; old intake PostgreSQL passes do not certify these new workflow paths.

## Integration Boundary

Patent agent retains exclusive final ownership of `services/ip_domain_catalog.py`.
No edit was made to it during this resume. Its hash must equal the baseline.
Register `contract_version(domain)`, `contract_path(domain)` and
`CHILD_PRD_HASHES[domain]` for DES/COPY/LIC `.2`; do not keep using one global `.1`
version. Preserve the existing required-journey union, including LIC UJ-60/UJ-61.
Seven other registrations remain intake-only. No authoritative office support,
beta/GA status, disclosure channel or production acceptance is granted here.
Default isolated catalog admission remains denied until coordinated integration.

Migration **20260909_0005 remains reserved**. Parent must linearize its predecessor
against the newer candidate, then run independently fresh PostgreSQL upgrade,
downgrade/re-upgrade, retained-data refusal and workflow race tests. The eight
specialist tables are record, version, observation, workflow, workflow-version,
workflow-source, obligation-link and obligation-event owners. SQLite schema tests
check every migrated column/nullability/index/FK. PostgreSQL acceptance now expects
all eight tables and six immutable-history triggers, but has NOT been executed.
The new canonical obligation-scope unique index must be assessed against parent
data and deployment lock budgets.

Reviewed shared hunks only: specialist model registration plus canonical
obligation-scope index; router registration; domain-discriminator mapping;
explicit read-only historical documents; restricted-ACL guard; shared-work
optional commit control for atomic obligation/task/deadline changes; specialist
navigation link; additive September 10 ledger notes. Regenerate parent OpenAPI,
frontend contracts and governance artifacts for all eight tables after integration.
Inherited generated files in this worktree are not current integration outputs.

No accessible parent coordination channel was established. Therefore no Docker
test was started. A later coordinated run must stay within the user's **1 CPU /
2 GiB** limit; the prior report's larger container limits are historical only.
No browser/server was started against an unintegrated disabled catalog.

## Explicitly Open

- **090A/B remain partial:** current source-reported DES/COPY/LIC workflows are
  substantial but not the full parent normal/exception matrix. Independent bounded
  workflow-reference paging is now implemented and unit tested; document-inventory
  scale, full client workflow breadth and useful responsive bounds still require
  production-scale and browser acceptance.
- **DES:** official jurisdiction/rules, registry snapshots, calculated deadlines,
  infringement/Matter links, client reports and complete legal renewal/cancellation
  operations are absent or unverified. Supplied event facts are not legal findings.
- **COPY:** cross-record licence/assignment chains, enforcement/Matter links,
  external notice delivery/recovery and client chain-vs-registration reporting
  remain incomplete.
- **LIC:** affected-right links, official recordal integration, royalty calculation,
  financial reconciliation, external notice/reminder recovery and full UJ-60/UJ-61
  acceptance remain incomplete. Recording a notice is not delivering it.
- **091A/B and DOMAIN/ENF remain unfinished:** domain name, enforcement, GI,
  plant variety, semiconductor layout, trade secret and customs retain restricted
  intake/evidence only. The September 09 requirement and journey gap map still
  applies to those seven domains, including every UJ-44/UJ-45 exception.
- **Cross-domain:** general disclosure is denied, not delivered. The ten populated
  mixed-link cases do not certify every saved-output/delivery race, legacy private
  projection or portal artifact. PostgreSQL current-access/lifecycle races,
  integrated migration/governance, complete browser normal/exception journeys,
  release-owned source packs and exact-serving-image acceptance remain open.

No four-slice COMPLETE claim, full-domain activation, deployed fix or full-coverage
claim is supported by this checkpoint.
