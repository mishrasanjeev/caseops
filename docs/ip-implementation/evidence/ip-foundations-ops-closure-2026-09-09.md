# IP Foundations And Operations: September 09 Implementation

## Boundary

Partial implementation, not programme closure or release certification. No manifest
`implementation_status`, canonical status ledger, production data, provider,
deployment, branch publication, or source-D file was changed by this track.

- Branch: `codex/ip-foundations-ops-closure-20260909`.
- Worktree: `C:/Projects/CaseOps/caseops/.worktrees/codex-ip-foundations-ops-closure-20260909`.
- Base: `5145fb3a4b51b26af116220ff10a7389bde6324d`.
- Inherited candidate: `C:/Projects/CaseOps/caseops/.worktrees/codex-sep08-acceptance-repair-20260908`.
- At isolation, copied 67 modified/untracked nonignored files enumerated by
  `git ls-files -m -o --exclude-standard -z`. PowerShell `Copy-Item` destinations
  were resolved beneath this worktree and source/destination SHA-256 compared.
- Migration reservation: `20260909_0003`, initially following `20260908_0001`.
  Parent must linearize its predecessor after integrating other reserved revisions.
- Sources reviewed: current AGENTS/CODEX, bug-fixing, caseops-prd-execution,
  enterprise-hardening and strict-quality-review skills, unified IP PRD,
  PROGRAM_MANIFEST, ownership and data-governance contracts, prior completion
  inventory, and existing preservation/disposition/access implementations.

## Implemented

DATA-GOV-04/05 and the preservation portion of UJ-64 now have actual authenticated
commands over the existing `LegalHold`/`LegalHoldItem` owner. This is not the whole
UJ-64 journey and does not admit additional data classes for disposition.

1. Owner creates an idempotent, authority-referenced draft after mandatory
   `legal_hold_change` MFA step-up. Scope is explicitly company or reviewed data
   classes; class identifiers resolve through the existing server projection.
2. A different, currently authorized owner/admin actually signs in and approves
   activation after step-up. A requester cannot nominate another person's ID or
   act twice through another membership. Existing owner-only audit/export access
   remains unchanged. `legal_holds:manage` is separate and non-delegable through
   custom roles; normal public user administration can create the second admin.
3. Owner requests release against a completed same-tenant dry run covering all
   scoped classes, produced after activation and at most 30 minutes old. An
   immutable proposal records the identities, reason, dry-run identity, hashes,
   scope and active-hold versions. The 30-minute proposal expiry is a technical
   reauthorization window, not a legal retention duration.
4. A different signed-in approver steps up. The command rechecks the requester
   and approver's current memberships/users/capabilities, parent version, expiry,
   immutable request hash, dry-run scope, and current preservation inventory.
   Hold release retains original activation identity and all evidence. It never
   calls a data executor or deletes records. Whole-company release fails closed
   because the six metadata classes cannot certify a complete workspace inventory.
5. Tenant-first locking now also precedes the existing private-disposition
   operation lock and its hold check. There is no new disposition job owner.
6. The UI supports scoped identity verification, drafts, independent approval,
   retained authority/scope inspection, release proposals and outcomes. Owner
   request actions are separate from administrator review. Returned mutations
   cancel stale exact list reads, update the cache, and refetch authoritative state.
7. Additional migration guard now rejects scope INSERTs once a hold is no longer
   draft. PostgreSQL uses the same tenant-first lock order as activation; admitted
   draft scope additions advance the existing version timestamp so an old approval
   token cannot silently approve different scope. SQLite has corresponding state
   and version triggers. Existing UPDATE/DELETE immutability guards stay unchanged.
   Replacement verification for this addition is still running at this checkpoint.

These are technical preservation identity controls. The track has not implemented
or certified the tenant-configured preparer/legal/data/executor approval policy,
and an entered authority reference is not verification of a legal instrument.

The previous nomination-based activation helper delegates to the one current
authenticated writer. Its old release signature is permanently refused: it cannot
manufacture an independent release approval. Non-executable data-operation dry
runs still have no approval workflow; the new approval is for an effectful hold
transition, not authorization to execute a diagnostic manifest.

## Owned Integration Files

Paths below are relative to this worktree. Do not copy the dirty worktree wholesale.

| File | Exact owned change |
| --- | --- |
| `apps/api/alembic/versions/20260909_0003_legal_hold_release_requests.py` | New additive table, composite tenant FKs, supporting indexes, immutable proposals, draft-only scope INSERT/version triggers, populated downgrade refusal |
| `apps/api/src/caseops_api/db/models.py` | Only new `LegalHoldReleaseRequest` class immediately before `LegalHoldItem`; do not copy tracking/provider/patent blocks |
| `apps/api/src/caseops_api/schemas/legal_holds.py` | New strict command and response DTOs |
| `apps/api/src/caseops_api/services/legal_hold_workflow.py` | New commands delegating preservation state to existing LegalHold owner |
| `apps/api/src/caseops_api/api/routes/data_governance.py` | Imports, `LegalHoldOperator`, six hold routes; existing diagnostic authorization unchanged |
| `apps/api/src/caseops_api/services/data_governance.py` | Retire nominated actor approval, delegate activation, refuse legacy release; remove now-unused local helper/import |
| `apps/api/src/caseops_api/services/data_disposition.py` | Company import and tenant-first lock/reload in `_approved_private_operation` only |
| `apps/api/src/caseops_api/services/capability_catalog.py` | One `legal_holds:manage` owner/admin capability |
| `apps/api/src/caseops_api/services/capabilities.py` | Add that capability to non-delegable custom-role set |
| `apps/api/src/caseops_api/governance/generated_data_class_projection.py` | Local ORM fingerprint refresh only; regenerate from integrated source instead of copying |
| `apps/web/lib/capabilities.ts` | Capability union and GOVERNANCE array entry only |
| `apps/web/lib/capabilities.test.ts` | Preservation role parity and audit-export isolation regression |
| `apps/web/lib/api/legal-holds.ts` | Six typed client wrappers and complete nested proposal/hold validators |
| `apps/web/app/app/admin/data-governance/holds/page.tsx` | New preservation work area |
| `apps/web/app/app/admin/data-governance/holds/page.test.tsx` | Focused success/error/access/discovery/independent-review component tests |
| `apps/web/app/app/admin/data-governance/page.tsx` | One legal-holds link after PageHeader |
| `apps/web/app/app/admin/page.tsx` | One capability read and matching Legal holds link |
| `apps/api/tests/test_20260909_legal_hold_workflow.py` | API workflow, current-access and no-deletion invariants |
| `apps/api/tests/test_20260909_legal_hold_postgres.py` | Real PG HTTP, immutable evidence and deterministic tenant-lock races |
| `apps/api/tests/test_20260909_legal_hold_migration.py` | Independently fresh SQLite and PostgreSQL migration rehearsals |
| `apps/api/tests/test_datagov05_hold_step_up_and_dual_approval.py` | Replace nominated-reviewer fixtures with real independent authenticated workflow; retain and strengthen semantic cases |
| `apps/api/tests/test_data_governance_service.py` | One summary fixture records draft scope before activation; outcome assertions unchanged |
| `apps/api/tests/test_datagov04_hold_scope_resolver.py` | Scoped fixtures insert while draft, then explicitly activate; all coverage/isolation assertions retained |
| `apps/api/tests/test_datagov17_integrity_scan.py` | Scoped integrity fixtures use draft -> scoped -> active -> released ordering; no integrity finding/gate weakened |
| `tests/e2e/iplf-028b-legal-holds-2026-09-09.spec.ts` | Dated two-browser/public-admin/MFA/persisted-reload/responsive journey, local synthetic bootstrap only |
| `scripts/tests/run-ip-foundations-offline.sh` | Frozen source snapshot, executable scratch and pinned offline Temporal, retained pytest journal/JUnit |
| `scripts/tests/run-ip-foundations-web.sh` | Exact lockfile-matched offline web tool image and retained JUnit |
| `scripts/tests/check-ip-foundations-web.sh` | Complete web TypeScript check and dated Playwright collection |
| `scripts/tests/summarize-ip-foundations-evidence.py` | Reconciles exact unchanged manifest requirements with retained setup/call/teardown and web results |
| `scripts/tests/Dockerfile.ip-foundations-browser` | Own offline browser tools assembled from existing cached tool images; not an application release image |
| `scripts/tests/run-ip-foundations-browser.sh` | Fresh source archive/build, direct dependency lock verification, isolated synthetic browser acceptance |
| `playwright.ip-foundations.config.ts` | Own dated journey selector, local Chromium, fresh servers, inherited timeouts and no-paid guard |
| `docs/ip-implementation/evidence/ip-foundations-ops-requirements-2026-09-09.json` | Initial full 15-slice/167-requirement and journey inventory plus retained test identities; no closure claims |
| `docs/ip-implementation/evidence/ip-foundations-ops-closure-2026-09-09.md` | This dedicated integration and gap handoff |

No edits to `domain_outbox`, `document_processor`, summary event contracts,
provider-spend/transport/lease ownership, or patent/other-domain code.

## Shared Map And Contract Integration

Parent-owned coordination is required before this candidate can pass all gates.
No canonical map or manifest was edited for this new table. Register
`legal_hold_release_requests` with policy profile `security_identity_control`,
the existing `registry_fail_closed` disposition handler, and explicit categories:

- `company_id`, `legal_hold_id`, `dry_run_id`, `requester_user_id`,
  `requester_membership_id`: `tenant_or_access_identifier`.
- `requester_label_snapshot`: `personal_or_contact_data`.
- `reason_reference`, `request_json`: `privileged_or_raw_content`.
- `request_hash`, `idempotency_key`: `lifecycle_or_audit_evidence`.
- `created_at`, `expires_at`: `temporal_or_version_metadata`.

No approved retention duration, export, purge or provider transmission is implied.
Preserve these records; a populated downgrade must roll forward. Keep this table
outside the six-class runtime disposition admission registry until independently
reviewed. Refresh the aggregate map/index inventory and its renderer, the generated
data-class projection, and OpenAPI types from the integrated source. Only then add
the required data-governance migration change-gate marker. Register/verify audit
actions `legal_hold.created`, `legal_hold.activated`, `legal_hold.release_requested`
and `legal_hold.released` against the parent's canonical audit catalogue.
The migration also adds PostgreSQL function `caseops_guard_hold_scope_insert` and
trigger `trg_legal_hold_items_draft_insert`; SQLite additionally has
`trg_legal_hold_items_scope_version`. Include those in the aggregate trigger
inventory without removing the pre-existing UPDATE/DELETE guards.

## Assigned Inventory

Statuses below are the unchanged manifest `implementation_status`, not claims of
completion. Empty requirement/journey arrays on an A slice inherit the parent epic.
The machine-readable companion `ip-foundations-ops-requirements-2026-09-09.json`
contains all 167 distinct source requirements and their exact source text/hash,
every effective journey path, original blockers, existing implementation references,
the actual owned implementation scope, and exact executed test identities. A
passing ownership/contract test is never promoted to full runtime acceptance.

| Slice | Manifest state | Code/evidence and exact remaining work |
| --- | --- | --- |
| IPLF-027B | in_progress | Existing default-off A0 and deadline writers retained. ARCH-OPS-01..26/UJ-67 exceptions remain open. Manifest expressly forbids A1 implementation before fresh exact old-revision deletion, T_FENCE, unchanged fingerprints and second drain. No A1/A2 code or cloud action performed. |
| IPLF-028A | in_progress | Existing six-class registry/projection remains canonical. New immutable hold-release evidence and fresh migration proof are additive only. Client/content/object/provider/backup admission, authority-backed retention policy, current export and combined application/object restore remain missing. Historical PITR-disabled/RPO finding was not re-probed in production. |
| IPLF-028B | in_progress | Concrete preservation commands/UI implement part of DATA-GOV-04/05/UJ-64. DATA-GOV-01..18/RES-01..14, UJ-28/UJ-65 normal and exceptions are not closed. General export/purge/offboarding/restore and worker-resume executors remain absent. |
| IPLF-029A | in_progress | Existing `ip_m2_ownership_audit.py` remains the repository owner; no duplicate audit service. Open M2/provider/A0/data/recovery rows cannot be certified by reference validation. Runtime one-writer/reconciliation evidence still required. |
| IPLF-029B | in_progress | Existing ownership ledger/ARCH_OPS_CONTRACT and manifest validators retained. Exact integrated deployed M2 reconciliation/rollback/ownership acceptance remains absent. |
| IPLF-039G | not_started | No new trademark state owner or duplicate 039A-F behavior added. Remaining integrated normal workflows need requirement-by-requirement runtime reconciliation and concrete gap implementation; not completed by this preservation change. |
| IPLF-039H | not_started | CAL-OPS, COMM, IP-CLR/FILE/INC/OPS/POST and TM-DATA exception integration remains open across UJ-03,31,32,49..55,57..59,61,62. Existing partial cost evidence must not substitute for all these paths. |
| IPLF-070A | not_started | Existing feedback/assistant references are not GA readiness. Pilot migration, security/accessibility/performance/support/DR/billing/readiness integration remains open. Cold-start/provider work belongs to parent/other assigned track. |
| IPLF-070B | not_started | COMP-01..08 acceptance, 30-day SLO evidence, independent release/security gates and current full-stack production proof not executed here. |
| IPLF-071A | in_progress | Existing `data_disposition.py` and 20260831_0001 remain the private-index subsystem owner. Added tenant-first preservation fence only. Full SQL/object/index/cache/queue/log/provider/backup/client/tenant executors, signed receipts and expiring exports are missing. |
| IPLF-071B | not_started | UJ-28/UJ-64 normal and all exceptions still need complete inventory, source-licence exclusion, durable provider/backup exceptions, isolated full-tenant purge/restore anti-resurrection proof. No production purge enabled. |
| IPLF-072A | not_started | No full restore coordinator/worker-resume implementation added. Must reuse existing effect owners and prove cross-region/process fences, tombstone reapplication and exact-image recovery; no second dispatcher or invented recovery certificate. |
| IPLF-072B | not_started | RES-01..14/UJ-65 normal and five exceptions need independently fresh database+object restore, missing-key/corrupt-index/provider failures, old-region fencing, no duplicate effects and measured RPO/RTO. No such full-stack claim here. |
| IPLF-073A | not_started | Existing target-aware `matter_access.py` explicitly excludes review campaigns and emergency sessions. Those remain absent; preservation approval is not emergency access or access-review implementation. |
| IPLF-073B | not_started | IP-ACCESS-01..08/SEC-GOV-01..16/UJ-63 normal and four exceptions remain open: exact scoped temporary capability, short expiry/revocation, no inherited grants, current ACL/search/cache/count boundaries, safe notifications and independent retrospective review. |

## Verification

All runs use owned labelled containers, no external network/provider calls, and
synthetic tenants. The old `f0a13e53` acceptance stack is not used as evidence.
Structured reports and failed attempts remain under `.tmp/ip-foundations-evidence`.

- `holds-01`: 6 passed, 3 failed. Individually inspected failures: two assertions
  read an incorrect nested ProblemDetails location; one unauthenticated probe
  retained its bootstrap cookie. Corrected setup/assertion shape, not product gates.
- `holds-02`: selection failed before collection because a test filename was
  incorrect. Zero collection is incomplete evidence; retained unchanged.
- `holds-03`: 67 passed, 5 failed. Every failure inspected: release requester ORM
  object had been discarded from the weak identity map, losing its fence marker.
  Fixed by retaining all locked participants through the command, not bypassing
  the canonical capability fence.
- `holds-04`: 72 passed, 33 warnings, 213.47 seconds. Full replacement inventory
  for the above backend failures passed. This preceded the owner/admin refinement.
- `holds-pg-01`: 6 passed, 2 failed. Fresh SQLite/PG migration and deterministic
  activation/access races passed; HTTP actor cookies incorrectly overrode explicit
  reviewer Bearer identities. Both structured failures inspected. Actor fixtures
  now clear bootstrap cookies and create the reviewer via the public admin API.
- `holds-pg-02`: 104 passed, 65 warnings, 308.43 seconds. Complete replacement
  mixed SQLite/PostgreSQL gate, with actual public owner/admin identities.
- `holds-pg-03`: 108 passed, 65 warnings, 457.65 seconds. Final backend gate adds
  stale generated-projection rejection for create/activate/release and a current
  Company-disablement race. Every collected node has passing setup/call/teardown
  and a successful session completion event. Includes six PostgreSQL hold tests,
  independently fresh SQLite/PG migrations and private-disposition regressions.
- `foundations-control-01`: 35 passed, 33 warnings, 129.00 seconds. Existing M2
  ownership audit, ownership ledger, A0 quiescence and fingerprint controls on the
  same frozen candidate as `holds-pg-03`. This does not certify the external A0
  revision-deletion/drain prerequisite or deployed M2 reconciliation.
- `holds-web`: 10 passed, 1 failed. Accessible button name joined title/status
  spans without expected spacing. Added an explicit accessible name.
- `holds-web-02`: 19 passed across three files in 16.41 seconds. Includes new hold
  UI success/error/admin-review/release flows, existing data-governance page and
  capability parity. Expected negative-path error logging is retained.
- Web tools lockfile equality verified: image and source SHA-256
  `fd10115d54e45819da64d7388bd673d390f3c45197bda3ca48830cecd387563c`.
- Complete web TypeScript check passed with `tsc --noEmit --incremental false`.
  Dated Playwright collection passed with one intended node, not browser execution.
- Scoped Ruff and `git diff --check` passed. Web tool image has no Prettier binary;
  no formatter claim is made. Full parent integrated gates remain unexecuted.
- `holds-browser-01`: fresh production build succeeded; one dated test failed after
  successful MFA because its broad alert selector matched Next's empty
  `__next-route-announcer__`. Initial screenshot-only suspicion of the offline
  banner was corrected by inspecting the exact trace DOM target.
- `holds-browser-02`: another fresh build succeeded; the same route-announcer
  assertion failed. Trace and screenshot retained. The attempted browser online
  emulation was unnecessary and has been removed. Only the framework route
  announcer is excluded now; all application error alerts must still be absent.
  Non-loopback browser requests and all OS external networking remain blocked.
- Initial browser tool-image assembly referenced the wrong hoisted Nodemailer
  directory; corrected to the observed workspace dependency path before execution.
- `holds-scope-red-01`: two genuine PostgreSQL call failures, 42.75 seconds, with
  valid fixtures and complete structured results. Active scope insertion raised
  no database error; a stale draft token activated changed scope with HTTP 200
  instead of the required 409. Both details were inspected before implementing
  the draft-only/version guard. This failed evidence remains unchanged.
- `holds-pg-04`: expanded replacement gate running on an independently fresh owned
  PostgreSQL base, including old database-guard and integrity-scan regressions.

All backend passing counts above are selected gates, not a complete repository
PostgreSQL gate. Raw failed journals/JUnit and the successful replacement inventory
are retained. Test tools image is
`caseops-offline-test-tools:20260908-statute-compiler-isolated` at
`sha256:09d833f4e368065b410628495562e0bb96d83e8610393a127eee5e235069fc20`.
Temporal stayed pinned outside executable scratch at
`/opt/caseops-test-tools/temporal-test-server`, hash
`daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce`.
The owned PostgreSQL service and runner together are limited to 2 CPU/4 GiB and
share a network-disabled namespace. Source archive hashes accompany each gate.

## Residual Product Gaps

This narrow UI lists at most 100 holds and 25 unexpired proposals; there is no
continuation navigation yet. Existing non-data-class retained holds fail closed
instead of being misrepresented as company-wide. Client/record/custodian/date
scoping, draft cancellation, active/future object preservation propagation and
whole-company release remain unfinished. Direct database scope INSERT/version
fences have now been implemented but are not yet replacement-test-certified at
this checkpoint. There is no full operation approval/executor,
backup restoration, signed export, independent production review, or deployed
closure. No assigned manifest slice is ready to be relabelled completed solely
from this evidence.
