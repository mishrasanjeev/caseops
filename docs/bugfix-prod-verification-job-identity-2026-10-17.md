# Production Verification Job Identity

## Scope And Current Truth

Operational acceptance: ARCH-OPS-23/QG-SEC-004, J04/M03, J08/M08 and UJ-18.
Serving release29d35f8f5662be08fc0b64846ab02bfeb964b6f4 has tree
7135528d383fcebd10ac72b45381ffbd9c2be678. Production38942699099 completed
all11 required jobs and396 cases:378 pass,18 explicit skip,zero failure/retry,
including all42 mandatory dated cases. Skips remain skips, not verified passes.

Canonical guarded resume65074 nevertheless exited1 before mutation:
`prod-verify did not complete every required QA job`. Private cadence remains
PAUSED. This is **Partially fixed / NO-GO**, not deployed closure or a rollback
of the successful QA seal.

## Reproduction And Root Cause

GitHub's retained terminal job payload contains these actual names:

- `Prod Playwright (tester-index) (tester-index)`
- `Prod Playwright (test-legal-write-oct13) (test-legal-write-oct13)`

Both jobs used literal display names plus a one-value matrix. GitHub appended
the matrix value. The guard expected undoubled names, while its regression
fixture synthesized those intended names instead of replaying actual metadata.
The original required-job set also ignored duplicate roles and did not require
completed job status or unique positive integer IDs for every evidence row.

The committed fixture projects only public job metadata from the retained
terminal REST payload into the existing `gh run view` field names. It preserves
all12 rows:11 successful required jobs and one trigger-inapplicable scheduled
job. Names, IDs, outcomes and timestamps are retained, not invented. The
captured-name positive and workflow-name assertion both failed before the fix.

## Correction And Adjacent Guards

- Map each required role to its exact canonical name. Only the two literal
  historical doubled forms above are additional reviewed forms. No suffix
  stripping, whitespace normalization, prefix matching or generic aliasing.
- Require exactly one completed/successful row for every required role. A
  second form or duplicate row rejects the entire evidence, even if it failed.
- Require unique positive integer IDs, excluding Boolean/float/string values,
  across all rows; reject unknown display names and duplicate optional rows.
- Validate timezone-bearing start/completion timestamps and their order, reject
  future completion, and retain exact resolver log SHA/revision checks and the
  authoritative recheck immediately before mutation.
- Derive the two future display names from `${{ matrix.suite }}`, like the
  existing matrix job. Preserve all11 required roles, dependencies, bodies,
  native-artifact union, serial execution,38-minute budgets and retries0.

Every earlier active-QA, exact release/image/traffic, maintenance accounting,
SLO, serial timing and second-run-no-rebuild fence remains in force.

## Maintenance Evidence Preserved

Immutable container reference:
`asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:fbcb094a33883ca13f9262a1a9687cc4cb41104dd2fbc57bf56ebdddb602f07e`.

- tctjr:19:33:00.902673Z to19:37:39.189952Z,7 candidates,3 rebuilds.
- wdnj9:19:38:12.904832Z to19:39:33.420403Z,7 candidates,0 rebuilds.

Both records are execution-scoped, statusok/releaseblockedfalse and free of
blockers, pending/failed events, deferrals, truncation and SLO breaches. The
300-second SLO is unchanged. Nullable lag fields remain null, not zero. QA's
last required job ended19:29:46Z, before both serial runs. These historical
records do not authorize a direct resume or substitute for a new release's
required QA/maintenance evidence.

## Verification And Honest Limits

External evidence: `outputs/calendar-ip-20261013/prodverify-job-identity-20261017-01`
in the primary evidence checkout. Initial host wrapper admission failed before
collection on a drive-letter argument; it is preserved separately. Corrected
RED has2 actual failures. Four whole host contract modules pass589 tests.

The network-disabled scoped Docker replay collects589 identities and passes
588, with one explicit Windows CMD-shim skip covered by the host run. It proves
executable isolated storage and cloud-CLI sentinels. An earlier scoped Docker
attempt retained587 passes/one skip/one reporter scratch-storage failure; the
unchanged regression passed after isolated writable scratch mounts were supplied.
Source was stable during the replay, and the owned container/process was reaped.

This is not a new full-standard Docker pass. Application/build-input and dated
browser-body equivalence to accepted29d is separately recorded. Its earlier
whole standard3036 native passes and583 browser passes/10 skips remain historical
evidence, not relabeled candidate execution. CODEX.md requires functional and
security verification but contains no ops-only full-standard mandate or scoped
risk-map exception; no separate risk map was found in committed29d. The release
owner explicitly authorized this focused ops-contract gate. Fresh PR/main
CI/Security/CodeQL and all396 production cases after canonical deployment remain
mandatory. No application, DB, UI, dependency, provider, grant or cloud change
is part of this correction.
