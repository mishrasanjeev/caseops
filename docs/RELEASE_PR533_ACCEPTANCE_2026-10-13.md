# PR 533 Release Acceptance, October 13

## Current Verdict

**NO-GO; not merged or deployed.** This checkpoint covers J09/M07
(US-026..028, FT-034..036), J14/M14, UJ36/UJ61 and QG-SEC-004.
The owner requires green CI, complete exact-candidate workstation Docker
acceptance, canonical-main merge, guarded production deployment and live replay.
Scoped results below do not replace those gates.

## Preserved Candidate Evidence

Candidate `dd7c4d5030410c6b0abbc3c941e4022be164f77e` has tree
`7af7505e8662f62fca53be97f2643a1c2cea90a3`. Hosted CI used merge
`5ea5f087b133267ef98afa0c374ce3ff17f3d27c` with the identical tree.

- CI run 38311637729: 10,451 unique API identities, 7,594 passed,
  one failed and 2,856 skipped. The failure is the stale exact upload-path
  expectation in `test_postgres_sharding.py`; combined API coverage and
  hosted Playwright did not execute. All 2,853 native PostgreSQL identities
  passed separately with 8,559 phases and retained native journals.
- Security run 38311637713 passed all eight jobs. CodeQL run 38311637798
  completed its analyses but reported alert 552 (`py/empty-except`) in the
  Gemini raw-response decoder. A successful analysis job is not alert closure.
- Full local Docker run `docker-dd7c4d50-01` naturally ended at
  `2026-10-12T23:09:43.083152+00:00`: 2,853 native identities,
  8,559 phases, 2,852 passed, one failed, zero skipped and zero retries.
  All eight whole-file groups completed and source bytes stayed unchanged.
  The failed call is
  `test_native_recovery_skips_locked_claim_and_respects_batch`.
  Recovery returned one where the test expected zero while its own claim
  was locked. A bounded read-only snapshot from the owned native database
  retained two distinct rows: the earlier job `11bc0b81-8e0a-4f4d-9608-c334a731e1c6`
  was queued with the exact recovery marker at `23:04:45.539196Z`; the job
  created in the failed fixture's time window
  `35255488-e530-46e0-881a-5513e466f998` remained processing.
  Its original SQL journal omitted parameters, so the locked ID is not
  directly recorded there. The source, exact query/update timing and retained
  rows establish an invalid shared-workload zero-count assumption, not a
  demonstrated production SKIP LOCKED defect. The corrected test must use
  the existing independently migrated, connection-disabled-template child
  fixture; production recovery remains global and unchanged.
- The Docker gate correctly stopped before Playwright. Its 550 discovered
  browser identities are an inventory, not executed acceptance. Failure
  diagnostics and pending aggregate products remain preserved; there is no
  successful aggregate completion. Owned Docker resources were cleaned up.
- Candidate secret tree/history scans, all 16 control-plane gates and the
  actual musl web-image 19-package obligation bindings passed. Those results
  apply only to this candidate, not to an amended source tree.

## Prepared Corrections

The exact upload-path regression now includes the native journal directory
and per-shard environment binding without changing shard counts, deadlines,
aggregate failure guards or original artifact paths. Its complete two-module
run has 52 passes and 156 phases.

The Gemini decoder explicitly retains `body = None` on unreadable metadata,
so conservative usage accounting still precedes its typed terminal error.
There is no catch broadening, private logging or suppression. Three native
SDK response-metadata regressions already passed before the clarity edit;
they are not falsely described as behavioral RED. The full four-module
replacement has 365 passes and 1,095 phases. Fresh actual CodeQL is required.

Global recovery zero/count tests now use `isolated_court_audit`, retaining
their original lock, expiry, count and persisted-state assertions. An added
three-tenant regression keeps the oldest claim locked, recovers each of two
unlocked stale claims with `limit=1`, proves no remaining unlocked work,
then recovers the original claim after lock release. Actor/source identity
and the locked claim's state remain preserved; production recovery is unchanged.
The complete three-module PostgreSQL-marked collection has 43 passes,
129 phases and zero skips in `court-recovery-isolation-20261013-02`.
These include native races and fixture/control tests, not 43 independent
overlap races. Its initial run is retained separately: 23 setup failures
were a missing external launcher's basetemp parent (`WinError 3`), not
product reproductions. Both owned resource sets were cleaned up.

Clarification of the preceding observability checkpoint: its 127-case run
contained 103 PostgreSQL-marked cases and 24 pure controls. Within the 103,
65 exercised native audit behavior and 38 were controls. It was not 127
independent PostgreSQL overlaps; canonical native collection remains 2,853.

## Remaining Release Gates

Replay the isolated global recovery correction and the explicit locked plus
unlocked multi-job batch boundary without deleting retained claims, changing
the production recovery scope or weakening assertions.
Then freeze the final source and rerun complete CI, CodeQL and Docker
native/browser acceptance. Reconcile every selected identity and every
setup/call/teardown phase; earlier failed and interrupted runs stay retained.
Merge only the validated tree to current canonical main. Deploy through the
guarded exact-SHA script, including its completed pre-migration backup,
then run exact-live verification and two clean private-projection cadences
before guarded scheduler resume.

Production was last verified on API and web revision `3dbf364d`; this document
does not establish a newer serving revision. No cloud backup, restore, live
provider, legal-model quality or conversion claim follows from these tests.
October paid behavior, automated no-paid fences, Gemini activation consent,
financial-baseline requirements and owner-kept provider gaps remain unchanged.

Evidence is retained under
`outputs/pr-final-release-20261012/`, including
`ci-dd7c4d50-reconciliation-01`, `docker-dd7c4d50-01`,
`docker-dd7c4d50-first07-independent-reconciliation-01`,
`gemini-decoder-intent-20261013-01` and
`finalizer-observability-scope-clarification-01`. The workload snapshot and
original failed phases are in `court-recovery-dd7c4d50-diagnosis-01`;
the corrected full focused proof is in `court-recovery-isolation-20261013-02`.
