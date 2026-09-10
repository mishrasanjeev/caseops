# IP Foundations: September 10 Resume

## Boundary

Resumed the existing isolated worktree, retaining inherited dirty work and all
September 09 failure evidence. No commit, push, deployment, paid API call,
parent-candidate edit, shared event-catalog edit, or manifest completion change.
The 15 assigned slices and 167 distinct requirements are still not complete.
September 10 hearing/provider repairs remain parent/other-track owned.

Authoritative requirements: unified PRD `docs/PRD_CODEX_2026-04-23.md`, IP PRD
sections 13.23-13.25 and UJ-63/64/65/67, and unchanged `PROGRAM_MANIFEST.yaml`.
The September 09 handoff remains the inventory of inherited owned changes;
this document adds the resume delta and replacement evidence.

## Concrete Delta

- Both the preservation register and active release proposals now have indexed,
  bounded keyset pages instead of inaccessible rows after 100/25 entries.
  `(created_at, id)` ordering handles tied timestamps; cursors resolve under the
  current tenant and, for proposals, the exact hold. Expiring a cursor proposal
  does not prevent continuation. No browser-supplied tenant identity is accepted.
- Each register page batches its scope read. An individual hold with more than
  100 scope rows fails closed even when the page-wide allowance is larger.
- The UI has previous/next controls, continuation error recovery, cursor reset
  when selecting another hold, and first-page selection after creating a hold
  from an older page. API responses and nested frontend validators agree.
- The fresh browser run reproduced double JSON encoding in all four inherited
  mutation wrappers. `apiRequest` owns encoding; the wrappers now pass objects.
  New tests use the real HTTP client (mocking only fetch) to assert exact request
  bodies and one attempt on rejected mutations. No shared client behavior changed.
- The dated browser journey now covers older hold/proposal discovery alongside
  authenticated two-person MFA, activation, release, retained reload, absence of
  application errors and responsive control bounds. It is local synthetic proof,
  never production certification.
- Test wrappers require unique evidence names, preserve source archive hashes,
  and explicitly load `-p tests.retained_results` with
  `CASEOPS_TEST_RESULT_JOURNAL`. Web/type/collection reports no longer overwrite
  the September 09 filenames.

## Parent Integration

Do not copy this dirty worktree wholesale. Apply only the owned paths/regions
from the September 09 handoff plus the following September 10 additions:

| Path | Owned delta |
| --- | --- |
| `schemas/legal_holds.py`, `services/legal_hold_workflow.py` | Hold/proposal page DTOs, bounded tenant/hold cursor reads and individual scope bound |
| `api/routes/data_governance.py` | `before_id`/`limit` read parameters and paged proposal response only |
| `db/models.py` | `ix_legal_holds_register_page` in `LegalHold`; `ix_hold_release_request_page` in the owned `LegalHoldReleaseRequest` class |
| `alembic/versions/20260909_0003_legal_hold_release_requests.py` | Both page indexes and empty-downgrade cleanup; retain all earlier guards |
| `tests/test_20260910_legal_hold_pagination.py` | New SQLite/PostgreSQL page, access, raw-scope and expiry regressions |
| `tests/test_20260909_legal_hold_migration.py` | Fresh upgrade/downgrade page-index assertions |
| `apps/web/lib/api/legal-holds.ts`, adjacent `.test.ts` | Typed complete page contracts and encoded cursor/cancellation regressions |
| `apps/web/lib/api/legal-holds.transport.test.ts` | Actual HTTP-client body and rejection regressions for all four mutations |
| `apps/web/app/app/admin/data-governance/holds/page.tsx`, adjacent `.test.tsx` | Bounded register/proposal navigation and mutation/error-state regressions |
| `tests/e2e/iplf-028b-legal-holds-2026-09-09.spec.ts` | Extended same dated journey, not a replacement excluding its former failure |
| `scripts/tests/*ip-foundations*` | Evidence preservation, selected tests, current structured handoff generator |

API paths above are relative to `apps/api/src/caseops_api` except `alembic` and
`tests`, which are relative to `apps/api`. Full-file SHA-256 values identify
candidate bytes, not authority to overwrite other owners' hunks. The machine
report includes the exact owned model-class source/hash and index insertion.

Migration `20260909_0003` remains reserved. Parent must linearize its predecessor
with the other reserved revisions; fresh migration rehearsals must be rerun
after integration. Never upgrade an existing database stamped with the old
unreleased version as a substitute for a freshly migrated candidate.

Shared catalogue/summary ownership remains with the summary agent; parent
integrates. No new audit action or outbox writer was introduced on September 10.
Register the four existing actions `legal_hold.created`, `legal_hold.activated`,
`legal_hold.release_requested`, `legal_hold.released` through that owner. Do not
introduce tenant-content-bearing summary events or duplicate canonical writers.

Parent must register `legal_hold_release_requests` in `DATA_GOVERNANCE_MAP.yaml`
under `security_identity_control` / `registry_fail_closed`, using the exact
field classifications in the September 09 handoff. Include the retained immutable
proposal/scope triggers and the two new indexes in the generated inventory,
regenerate the data-class projection and OpenAPI, and add the required migration
change-gate marker. The table remains outside runtime export/purge admission.
The unmodified integrity test currently reports this missing registration;
that failure is an unresolved integration gate, not a waived test.

## Verification

Fresh September 10 runs use owned containers, no external networking, source
archives, executable scratch volumes and the pinned real Temporal test server.
PostgreSQL plus its runner are limited to 0.2 + 0.8 CPU and 384 + 1664 MiB.
Web/browser runs are sequential with owned backend runs, capped at 1 CPU/2 GiB.
No other owner's container, volume or evidence is stopped or removed.

Results are reconciled in the machine-readable companion. The interrupted
`holds-pg-04` has only 14 complete test observations and no session finish; it
remains incomplete. `holds-sep10-pg-01` completed 66 passes/1 missing-map failure.
`holds-sep10-pg-02` completed 71 passes/2 failures: the same missing-map gate and
a cross-tenant test fixture that reused `aster-legal`. The latter fixture now
creates a separately named tenant. Both complete failure details are retained.
`holds-sep10-pg-03` passed 67 tests, including the entire corrected pagination
module, PostgreSQL cursor tests, ownership/A0 controls, FK indexes, capabilities
and private-disposition boundaries. `holds-sep10-api-04` passed the 29 remaining
projection, review-contract and purge-plan tests from the earlier inventory.
`holds-sep10-web01` passed 24 component/contract tests plus full TypeScript and
one-node standard Playwright collection, before the transport defect was found.
`holds-sep10-browser01` built successfully but failed its first draft mutation:
trace request resource `0790d3da0ead417d8534dec23ffb8886afd8eff9.json` is a JSON
string body and the API returned 422. This is a product defect, not an offline
banner problem or a reason to relax API validation. The original failed browser
report and trace are retained for replacement reconciliation.
`holds-sep10-web02` passed all 32 tests, TypeScript and collection after the
transport fix. `holds-sep10-browser02` passed the actual UI mutations through
release-request creation, then failed a new pagination fixture POST with
`Missing CSRF token` (trace resource
`2de964a9d75a73087d87c667a45ede882d88a49a.dat`). The fixture now sends the
double-submit header from its issued cookie; no CSRF exemption was added.

Final local result: `holds-sep10-browser03` passed the complete dated journey,
38.5 seconds of test execution / 70.34 seconds including setup, with zero skips,
retries or unexpected errors after a new successful build. Retained JSON contains
all four original screenshot attachments; byte-identical PNG extractions are in
`.tmp/ip-foundations-evidence/holds-sep10-browser03-visuals`. All four screenshots
were visually inspected: usable input widths, wrapping controls and reachable
page navigation at 360px and 1280px, with breakpoint checks in the same journey.
The offline banner is expected in the deliberately network-disabled Chromium
environment; all loopback mutations and reload outcomes passed.

The composed current backend inventory has **162 distinct fully passing nodes**,
including all 108 nodes from `holds-pg-03`, and **one still-failing integration
node**: `test_every_live_table_is_registered_in_the_map`. This is not a green
complete repository gate. Source tree/full integrated Docker/production release
certification remains parent-owned and unexecuted. Scoped Ruff and
`git diff --check` pass. No owned test process or database is left running.

Artifacts in this directory:

- `ip-foundations-ops-requirements-2026-09-10.json`: all 15 slices, 167 source
  requirements, journey inventory, exact passing identities, complete failure
  details and replacement links, current browser/web results and source hashes.
- `ip-foundations-owned-files-2026-09-10.json`: exact file SHA-256/byte lengths,
  merge-only region descriptions, owned model class text/hash, reserved migration
  note and first-resume-snapshot preservation comparison. Never use its full-file
  hashes as permission to replace a parent's shared source wholesale.

## Per-Slice Gaps

| Slice | Requirement/acceptance remaining |
| --- | --- |
| IPLF-027B | ARCH-OPS-01..26/UJ-67: retain default-off A0. Fresh exact old-revision deletion, T_FENCE, unchanged fingerprints and second drain remain prerequisites for A1. No A1/A2 activation. |
| IPLF-028A | DATA-GOV registry foundation: shared-map integration; authority-backed retention; client/content/object/provider/backup admission; current exports; combined database/object recovery. |
| IPLF-028B | DATA-GOV-04/05/UJ-64 preservation is partial. Client/record/custodian/date scopes, draft cancellation, all-current/future-object propagation, configured multi-role approval and whole-company release remain absent; UJ-28/65 executors remain open. |
| IPLF-029A | M2 ownership references retained; deployed one-writer, A0/provider/data/recovery reconciliation is not certified by repository contract tests. |
| IPLF-029B | Integrated exact-release ownership, rollback, reconciliation and deployed M2 acceptance remain unexecuted. |
| IPLF-039G | Full trademark normal-path reconciliation across existing 039A-F owners remains open. This hold change does not implement an additional trademark state owner. |
| IPLF-039H | CAL-OPS, COMM, IP-CLR/FILE/INC/OPS/POST, TM-DATA exception integration across UJ-03/31/32/49..55/57..59/61/62 remains open. |
| IPLF-070A | Pilot migration, security/accessibility/performance, support, DR, billing and GA-readiness integration remain open. Parent owns cold-start/provider repair. |
| IPLF-070B | COMP-01..08, 30-day SLO history, independent security/release gates and full current production proof remain open. |
| IPLF-071A | Existing private-disposition owner retained. General SQL/object/index/cache/queue/log/provider/backup/client/tenant executors, signed receipts and expiring exports remain absent. |
| IPLF-071B | Full UJ-28/64 inventory, licence exclusions, provider/backup exceptions, isolated purge/restore and anti-resurrection acceptance remain open. No production purge enabled. |
| IPLF-072A | Full restore coordinator and worker-resume integration absent. Reuse canonical effect owners; do not create a second dispatcher. |
| IPLF-072B | RES-01..14/UJ-65: independent database/object restore, missing-key/corrupt-index/provider exceptions, old-region fence, no duplicate effects and measured RPO/RTO remain open. |
| IPLF-073A | Access-review campaigns and scoped emergency sessions remain absent. Preservation approval is not an access-review implementation. |
| IPLF-073B | IP-ACCESS-01..08/SEC-GOV-01..16/UJ-63: temporary exact-scope access, expiry/revocation, no inherited grants, ACL/search/cache/count boundaries, safe notifications and independent retrospective review remain open. |

The machine companion retains every exact source requirement and journey text,
manifest status, source hash, existing code reference, selected passing test,
failed/incomplete run and remaining gap. No slice is relabelled completed.
