# Patent Closure Track, 2026-09-09

Status: Partially implemented. Release verdict: NO-GO pending integrated proof.
No commit, push, deployment or production mutation is authorized in this track.

## Ownership And Source

- Worktree: `C:/Projects/CaseOps/caseops/.worktrees/codex-patent-closure-20260909`.
- Branch: `codex/patent-closure-20260909`.
- Baseline: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- Candidate D: `codex-sep08-acceptance-repair-20260908`; copied all 67 paths
  returned by `git ls-files -m -o --exclude-standard -z`. Every source/destination
  SHA-256 matched and every absolute destination was inside this worktree.
- Reserved migration: `20260909_0004`; parent owns final linear integration.
- Own IPLF-079A/B, IPLF-080A/B, patent child PRD and `ip_domain_catalog.py`.
  Do not copy shared files wholesale; integrate only track-owned hunks.
- Parent retains all five canonical status ledgers, program manifest, release
  configuration, catalogue-source acquisition and production certification.

## Contract And Dependencies

Read current patent child PRD, exact PROGRAM_MANIFEST entries and existing
family/application/party/priority/source/lifecycle implementations. Preserve those
owners. Mapping: PAT-01..04, IP-SCOPE-01..10; UJ-29/39/40 and shared UJ-60/61;
M02/M08/M13/M14. New typed evidence extends canonical IpDocumentVersion and
IpPatentApplication rather than introducing trademark particulars or statuses.

Implemented here: immutable document editions and filing manifests,
source-pinned manual prosecution and a bounded impact preview. Separate
proceeding, obligation, cost, acceptance and title adapters remain product work,
not merely missing catalogue data.
Closed records retain authorized historical reads; ordinary writes and creation
replays must recheck operational targets and current source access.

Catalogue track dependency: operative India patent Act/Rules/amendment sources,
exact official bytes/text hashes, publisher/issuing authority, version and
effective dates, plus active patent IpRuleVersion records and executable legal
fixtures covering examination, response, annuity, working statement and
restoration boundary dates. No foreign automation, guessed periods or fees.
The patent beta/GA and authoritative-automation gates remain fail-closed.

## Exact Implementation

- `apps/api/src/caseops_api/db/patent_prosecution_models.py`: three new
  company-composite owners, `IpPatentEvidenceVersion`,
  `IpPatentEvidenceDocument`, `IpPatentProsecutionEvent`. They pin existing
  application and document versions, not a second document or application store.
- `apps/api/src/caseops_api/services/ip_patent_prosecution.py`:
  `create_patent_evidence`, `get_patent_evidence`, `list_patent_evidence`,
  `preview_patent_prosecution`, `create_patent_prosecution`,
  `get_patent_prosecution_event`, `list_patent_prosecution`.
- `apps/api/src/caseops_api/schemas/ip_patent_prosecution.py`: strict typed
  contracts, 20-document manifests, fixed patent event kinds and explicit
  acknowledgement codes. No patent duration, fee, provider identifier or
  official text has been invented.
- `apps/api/src/caseops_api/api/routes/ip_patents.py`: authenticated GET/POST
  `/applications/{application_id}/evidence`, GET evidence by ID, GET/POST
  `/applications/{application_id}/prosecution`, GET event by ID and POST
  `/applications/{application_id}/prosecution/preview`, within `/api/ip/patents`.
- `apps/web/lib/api/ip-patent-prosecution.ts`: strict nested Zod response
  validators and typed client commands. The central generated OpenAPI file is
  not regenerated here; the parent must regenerate from the integrated API.
- `apps/web/components/ip/PatentProsecutionWorkspace.tsx`: bounded work-product
  and prosecution pages, source-version selection/download, new edition,
  immutable receipt history, explicit impact review, retained rejected input,
  initial-read admission and stale-read cancellation after save.
- `apps/api/alembic/versions/20260909_0004_patent_prosecution_evidence.py`:
  additive application work sequence, immutable/sealed evidence tables, FK
  indexes, PostgreSQL/SQLite guards and restore-forward downgrade refusal.

## Requirement Matrix

The exact manifest has no direct requirement/path IDs on foundation rows 079A
and 080A; those inherit their parent epic. Workflow rows 079B and 080B carry the
following IDs. No row below is an assertion that its entire slice is complete.
Source: the parsed `requirements` and `journey_paths` arrays in the current
`PROGRAM_MANIFEST.yaml`, plus patent child-PRD Sections 1-7.

Test references in this matrix are exact test function names in
`apps/api/tests/test_ip_patent_prosecution.py` (B),
`apps/api/tests/test_ip_patent_prosecution_postgres.py` (P), and
`apps/api/tests/test_ip_domain_catalog.py` (C):

| Ref | Exact test | Observed outcome |
| --- | --- | --- |
| B1 | `test_patent_manifest_filing_and_new_edition_retain_exact_receipt_history` | SQLite and PostgreSQL passed |
| B2 | `test_patent_work_idempotency_stale_commands_and_source_hash_fail_closed` | SQLite and PostgreSQL passed |
| B3 | `test_patent_backdated_and_exceptional_preview_must_be_acknowledged_and_current` | SQLite and PostgreSQL passed |
| B4 | `test_patent_work_closure_reopen_stale_replay_and_second_closure` | SQLite and PostgreSQL passed |
| B5 | `test_patent_manifest_and_event_direct_mutation_rejected` | SQLite and PostgreSQL passed |
| B6 | `test_patent_work_current_source_access_and_other_application_scope` | SQLite and PostgreSQL passed |
| B7 | `test_patent_work_pages_and_manifest_contracts_are_bounded` | SQLite and PostgreSQL passed |
| B8 | `test_patent_event_replay_reopen_and_current_access_revocation` | Added separate prosecution replay/close/reopen/revocation journey; final replay pending |
| P1 | `test_different_actor_closure_wins_waiting_patent_manifest[False/True]` | Both deterministic PostgreSQL races passed |
| P2 | `test_patent_500_retained_editions_query_budget_and_hard_history_limit` | PostgreSQL passed: 500 editions, <=30 SQL statements, successful 501st save/replay, refusal at 1,000, sealed manifest |
| P3 | `test_patent_work_fresh_migration_roundtrip_and_retained_downgrade` | Independently fresh PostgreSQL passed: empty downgrade/upgrade, identical columns/constraints/indexes/triggers, two retained refusals |
| C1 | `test_patent_intake_and_coarse_passes_cannot_claim_full_workflow[beta/ga]` | Both passed; missing implementation and five patent-source checks remain blockers |
| C2 | `test_iplf079_changed_or_stale_evidence_never_activates` | All selected parameter cases passed |
| C3 | `test_iplf079_machine_owner_is_the_only_activation_path_and_tampering_revokes` | Passed, including public catalogue observation |
| C4 | `test_iplf079_unknown_and_authoritative_operations_fail_closed` | Passed |
| C5 | `test_iplf079_intake_flag_cannot_replace_child_prd_or_implementation` | Passed |
| C6 | `test_iplf079_compiled_child_contract_hash_matches_repository_source` | Passed on PG-02 archive; the later child-PRD/hash update needs final replay |
| W1 | `IPLF-080 immutable patent package and prosecution lifecycle at 393px/768px/1280px` in `tests/e2e/iplf-080b-patent-prosecution-2026-09-09.spec.ts` | All three passed in final07 on the rebuilt application; exact save/replay, filing/edition history, byte-identical terminal download, reopen/stale replay, second same-day close, cross-tenant denial and reload |

| Requirement | Actual code / tested behavior | Remaining requirement gap |
| --- | --- | --- |
| IP-SCOPE-01 | Catalogue `workflow_implemented` is independent of `intake_implemented`; C1/C5 reject a schema/intake-only promotion. | Full non-trademark qualification and launch are not implemented/certified. |
| IP-SCOPE-02 | Patent-only `PHASES`, `PatentEventKind`, document kinds and source pins; B7 rejects trademark registration and generic lifecycle events. | Complete proceeding, fee, obligation and completion semantics remain absent; no trademark rule substitution was made. |
| IP-SCOPE-03 | Existing document/source, docket/access, lifecycle, audit and idempotency owners through typed contracts; B1/B2/B4/B5/B6 and P1. | Typed patent task/deadline/instruction/cost/notification/title adapters remain product gaps. |
| IP-SCOPE-04 | Catalogue retains IN/IP India scope and checks evidence jurisdiction/office equality; C2/C4. Foreign facts remain intake, not automation. | Actual patent jurisdiction/rule execution and full unsupported-office browser proof are not provided. |
| IP-SCOPE-05 | B1-B7, P1-P3 and W1 exercise this vertical's normal, stale, source, close/reopen, revocation, race, migration, responsive browser and work bounds. | Contested, transfer, maintenance, all child journeys and consolidated release suite remain open. |
| IP-SCOPE-06 | Five distinct source-fixture check IDs plus existing source/legal gates; C1. No legal deadline is changed by prosecution. | Operative source packs, machine-executed patent fixtures and confirmed-obligation update preservation are not implemented/proved here. |
| IP-SCOPE-07 | Existing family/application/priority owners are preserved; B1 proves no family mutation and B6 rejects a sibling manifest. | Cross-right title/territory/encumbrance reconciliation and consolidated client reporting remain product gaps. |
| IP-SCOPE-08 | Existing restricted-source and domain-disclosure owners remain in use; each retained record reauthorizes all source pins; B6 and P1. | This track has not rerun every saved AI/portal/export/delivery projection boundary or a browser grant-revocation journey. |
| IP-SCOPE-09 | Server catalogue remains authoritative, intake-only, release-bound and tamper-resistant; C1-C5. | Configured/unconfigured, public-page, reporting/packaging and catalogue-outage browser acceptance is not complete. |
| IP-SCOPE-10 | Current child PRD/hash, explicit implementation gate and existing machine release checks; C1-C6; manual work does not unlock automation. | Full implementation, source fixtures, support, integrated security/performance and exact-release certification remain open. Source absence is not an excuse for the product gaps above. |
| PAT-01 | Existing family/application/party/priority/PCT-national-phase facts preserved. New exact claims/manifests and sourced events implemented; B1-B7. | Annuity, assignments, complete patent family reports and complete UJ-29/39/40 are not delivered. |
| PAT-02 | New code never invokes trademark calculation and always returns `authoritative_calculation_available=false`, `changes_deadlines=false`; B1/B3/B7, C1/C4. | An active patent `IpRuleVersion` selection/calculation adapter and legal boundary fixtures remain absent. This is a safety fence, not deadline implementation. |
| PAT-03 | Source-pinned filing/publication/examination-request/office-action/response/hearing/amendment/grant/restoration event contracts; B1/B3 prove filing and exceptional/backdated office action. | Not every admitted event kind has a complete journey. Refusal/appeal lineage, pre/post-grant opposition, revocation, compulsory licence, working/annuity, assignment/recordal and litigation adapters remain product gaps. |
| PAT-04 | Immutable predecessor/root/application/source relationships, hashed/sealed manifest, filed event pins retained after edition replacement; B1/B2/B5/B7/P2/P3/W1. | Positive journeys for every document kind and explicit prepared/filed/granted role comparisons remain unverified; 500 retained editions is not 500 distinct IpDocumentVersion bytes. |

## Atomic Journey Matrix

This separates the exact 19 manifest path IDs assigned to these workflow slices.
Earlier P1 evidence is historical evidence, not this track's fresh full proof.

| Atomic path | Actual code and proof | Verdict / missing outcome |
| --- | --- | --- |
| UJ-29-NORMAL | Existing `ip_patent_families`, `ip_patent_applications`, `ip_patent_parties`, `ip_patent_priorities`; new B1 checks family unchanged. | Partial. Full family report and combined intake-to-prosecution journey not certified here. |
| UJ-29-EXC-01 | Existing sourced parties/priority exceptions. | Product gap: dedicated inventorship/title-conflict legal-review outcome not established by this track. |
| UJ-29-EXC-02 | Existing independent application identities; B1/B6 preserve and scope work. | Scoped regression passed; existing complete relationship suite not freshly rerun here. |
| UJ-29-EXC-03 | Catalogue scope and disabled automation C2/C4. | Safety fence passed; patent rule-engine execution remains missing. |
| UJ-39-NORMAL | `create_patent_evidence`, preview/record prosecution, new two-tab UI; B1/B3/W1. | Partial. No complete instruction/deadline/office-acceptance chain or opposition. Manual sourced filing browser journey passed at all three widths. |
| UJ-39-EXC-01 | Application-scoped event FK/writer; B1 family unchanged and B6 wrong-application manifest rejected. | Partial. Need a full event-history unchanged assertion on an independently active sibling. |
| UJ-39-EXC-02 | Append-only evidence/doc/event tables and exact manifest pin; B1/B5/P2/P3/W1. | Filed-package case passed through PostgreSQL and browser. Separate granted-set semantic journey remains unverified. |
| UJ-39-EXC-03 | No new proceeding owner created and no trademark opposition reused. | Product gap: separate patent proceeding IDs/stages/side/forum/source/audit. |
| UJ-39-EXC-04 | Missing/inaccessible/hash-mismatched sources reject under B2/B6. | Product gap: source ambiguity pending-confirmation workflow. Rejection is not that workflow. |
| UJ-40-NORMAL | No patent obligation/period chain implemented in this track. | Product gap: annuity/working proposal through instruction/funding/filing/acceptance and next-period idempotence. |
| UJ-40-EXC-01 | Existing shared cost owner untouched. | Product gap: patent quote/rule/entity invalidation and active cost revalidation. |
| UJ-40-EXC-02 | Manual filing event explicitly does not assert registry acceptance. | Product gap: paid/filed versus accepted obligation state and exact receipt reconciliation. |
| UJ-40-EXC-03 | Restoration event requires an explicit reopened lifecycle and source; B4 proves epoch fencing, not restoration law. | Product gap: separate lapse/grace/restoration obligation review and its legal fixtures. |
| UJ-40-EXC-04 | No working-form logic substituted. | Product gap plus source dependency: not-applicable/no-working declaration and applicable operative form rules. |
| UJ-60-NORMAL | `evaluate_domain` checks release/contract/jurisdiction/check completeness. | Partial foundation only. No non-trademark launch/qualification certified. |
| UJ-60-EXC-01 | C1/C4 block unsupported legal automation while manual evidence remains usable. | Scoped backend passed. Full source-unavailable browser/recovery path remains open. |
| UJ-60-EXC-02 | C1/C5 distinguish intake from workflow support. | Scoped backend passed. No intake-only record is called complete patent management. |
| UJ-60-EXC-03 | C2 evidence-office/jurisdiction mismatch and C4 authoritative-operation denial. | Scoped backend passed. Complete unsupported-jurisdiction browser path remains open. |
| UJ-60-EXC-04 | C2/C3 revoke stale/changed/tampered machine evidence without deleting records. | Scoped backend passed. Live capability downgrade with retained patent work needs integrated browser/production proof. |

Shared UJ-61 title and licensing obligations are additional child-PRD requirements,
not assigned atomic 079/080 manifest paths. They remain explicit product gaps.
Original-source patent import preview/commit/recovery, export/reporting, complete
10,000-application/1,000-family/500-document byte-version performance, unrelated
writer responsiveness and every legacy trademark/Madrid regression remain
integration or implementation work, not inferred from P2's local pass count.

## Integration Hunks

Do not copy shared files wholesale from this deliberately dirty worktree.

- `db/models.py`: only `IpPatentApplication.work_sequence` after `family_id`,
  and the bottom import of the three new model classes before
  `ensure_foreign_key_indexes(Base.metadata)`. The Matter/backfill/tracking
  changes in this file were inherited from D and are not patent hunks.
- `api/routes/ip_patents.py`: imports of the prosecution schema/service and
  seven added handlers. No changes to the central router or tracking routes.
- `services/ip_domain_catalog.py`: definition fields `workflow_implemented`
  and `required_source_checks`; trademark's existing full-workflow flag;
  patent child-PRD SHA plus five required source checks; gate evaluation hunks.
  Adding these definition fields changes every contract hash. Parent must
  regenerate exact-release machine evidence, not carry an older certificate.
- `PatentApplicationWorkspace.tsx`: import, two tab triggers and two tab panels.
- Parent must integrate migration `20260909_0004` into the linear chain, update
  the focused migration test's predecessor target if needed, and regenerate
  integrated OpenAPI/data-map/schema-governance/release fingerprints. These
  common artefacts and the five status ledgers were intentionally not edited.
- New model/service/schema/component/client/tests and dedicated evidence files
  are patent-owned. Existing family/application/party/priority services were
  not rewritten. No 090/091 or parent provider-spend blocks were touched.
- `C:/tmp/caseops-patent-closure-20260909/integration-inventory-checkpoint.json`
  records 25 owned paths/hashes. `patent-shared-hunks-checkpoint.patch` in that
  directory contains only six owned existing-file diffs, with exactly the two
  model hunks above. `git apply --check --reverse` passed in this worktree.
  Neither command applies a patch to D. Later changes to this evidence ledger
  must be copied separately; the product-code snapshot is unchanged.

## Verification Ledger

All automated execution uses owned containers labelled
`caseops.track=patent-closure-20260909`. Backend tests use
`caseops-offline-test-tools:20260908-statute-compiler-isolated`, explicit bash,
network none (or the network-none owned PostgreSQL namespace), executable disk
scratch >=2 GiB and the pre-pinned Temporal binary outside `/tmp`.
The old 29590/29592/29593 stack has not been used or mutated.

Artifacts are under `C:/tmp/caseops-patent-closure-20260909`:

- `patent-focused-01.jsonl`, `api-patent-focused-01.xml`: 28 pass, two failed
  fixture assumptions, both fully inspected. Reopen must use existing `ready`,
  not `draft`; sibling setup reuses the exact existing source rather than
  expecting a duplicate upload to create another source. Failures retained.
- `patent-pg-01.jsonl`, `api-patent-pg-01.xml`: 41 passed including nine PG
  calls, seven SQLite journeys and 25 catalogue cases; session finished exit 0.
- `patent-pg-02.jsonl`, `api-patent-pg-02.xml`: 43 passed including the two
  additional PG history/migration tests above, zero skips/failures, complete
  setup/call/teardown records and session-finished exit 0. No failed phase rows.
- `web-patent-web-02.xml`: 15 passed across application workspace, prosecution
  workspace and nested client schema files. Web TypeScript passed. The first
  web runner's unsupported BusyBox `tar --null` was an infrastructure failure;
  corrected with a validated NUL inventory conversion, not a test waiver.
- `web-patent-draft-fail01.xml`: six passed, but the newly added background-read
  regression asserted before error feedback rendered. Not accepted as proof.
- `web-patent-draft-fail02.xml`: five passed, one reproduced failure. Waiting
  for the actual query-error heading proves that the open form was unmounted.
  Product fix preserves a previously hydrated form while keeping initial
  admission fail-closed. Corrected outcome is `web-patent-final02.xml` below.
- `web-patent-final02.xml`: all 16 cases passed on the rebuilt source (eight
  application, six prosecution-workspace, two strict nested client schemas),
  zero failures/errors/skips. The reproduced draft-preservation case passed.
- Ruff focused check and `git diff --check` passed. Ruff earlier line-length
  and read-only-cache attempts were corrected; no lint gate was removed.
- `patent-final01.tar` SHA-256
  `c759fe4f435e4ec84b3c5f9bdfe2aa0511335e7105de37fb62ae75a99fa6ab85`
  contains all 2,320 selected source/fixture paths. Fresh Next production build
  passed, and a separately fresh `patent_browser` PostgreSQL database migrated
  through 0004. This archive precedes the final draft-preservation UI change.
- Browser setup attempt 01 stopped at missing root `tsconfig.json`; attempt 02
  typechecked but selected zero tests because the filename lacked the standard
  slice suffix. Both were incomplete setup attempts, never passing journeys.
  Runner now uses `tsconfig.e2e.json` and the `iplf-080b-...` file discovered by
  the existing general suite selector. No selector or timeout was weakened.
- `patent-final02.tar` SHA-256
  `28e737f9321e1159ec3c17ebe2cc508eac2071d1325913a1ecbe9217bb21b42b`
  contains all 2,321 selected source/fixture paths and the draft-preservation
  correction. Both current API/web processes record this same archive hash.
  Fresh Next production build and TypeScript passed; BUILD_ID SHA-256 is
  `7aba9ed4caf36ad7e8595deda82c9b428921d2637ac435dfd4f33d0ae2774e80`.
  The separately migrated browser database is owned by this track. It retains
  earlier failed fixtures; every rerun bootstraps independent new tenants.
- `browser-patent-final03.xml`: three failed after successful package saves.
  All three structured failures were the status locator also matching the
  offline banner. Scoped the success locator to the patent work-product area.
- `browser-patent-final04.xml`: three failed at a global empty framework alert.
  All failures inspected. A first attempted nonempty-alert predicate proved
  insufficient because Next's route announcer sometimes contains the title.
- `browser-patent-final05.xml`: 393px and 1280px complete journeys passed;
  768px failed at that route-announcer title, not a product error. XML, trace,
  screenshot and error context retained and inspected. Error assertions now
  target all alerts inside the main application content; success, exact saved
  response, byte hash, lifecycle and persisted-reload assertions are unchanged.
- Browser runner records the immutable application archive plus the separately
  hashed latest dated spec. Only test-locator corrections were overlaid after
  the final02 application build. All runs use one worker, zero retries and the
  existing deadline budgets.
- `browser-patent-final06.xml`: three 120-second whole-journey timeouts, with
  all structured failures inspected. They expired at different late operations:
  post-reopen replay (393px), post-close replay (768px), and retained event read
  after edition replacement (1280px). The 393px trace recorded 43.272 seconds
  closing its browser context and multi-second ordinary actions while writing
  artifacts to the Windows mount. This was not classified as one failing API
  boundary. A subsequent `/api/health` probe returned 200 in 107 ms.
- `browser-patent-final07.xml`: all three identical journeys passed (69.190s,
  63.841s, 92.605s), zero failures/errors/skips. Only artifact storage changed:
  captures remain on container-local disk during execution and an EXIT trap
  copies their complete output to the owned host directory. The original
  failed evidence remains intact. The 120-second test budget, assertions,
  one-worker execution and zero retries are unchanged. Screenshots at mobile,
  tablet and desktop were visually inspected; the spec also asserts all
  controls at 639/640/641, 767/768/769 and 1023/1024/1025px boundaries.
  Spec SHA-256:
  `7aa6112aa872cd457deada073396901e7a62eb1655fd42d2192bcd8a8dc5d623`.
  Runner SHA-256:
  `a6c30bdf4d566f7f6e28fab1bc78370e7a7416168dfcc284500a03a473ee2add`.
- Broader `patent-pg-03` replay selects all 11 patent modules plus
  `test_ip_domain_catalog.py`, including the newly added B8 journey in SQLite
  and PostgreSQL. Source archive SHA-256:
  `f99c74538d4b78a2ea445ee4dc2ada5eeab432b23876a37f61158b0cc3a9a886`.
  The owned API/web servers are stopped during this run; PostgreSQL plus the
  test container are capped at a combined two CPUs/four GiB. Outcome pending.

No commit, push, deployment, production mutation, unsafe GA activation or
complete-slice status claim has been made. All four assigned slices remain open.
