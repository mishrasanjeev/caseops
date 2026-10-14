# IP And Calendar Release Recovery

## Status

**NO-GO / Partially fixed.** This checkpoint supersedes historical statements
that PR535 is unmerged or production remains3dbf. PR535 merged as
`09d7952758a198e908e591498363f2ee222773e7`, with the same tree as Docker-accepted
db6cd235. API00489-gdl and web00466-8kl route100% to that release. Production
certification and the approved manual-IP grant have not completed.

Existing ownership remains J08/M08/MOD-TS-006, UJ-02/04/26,
IPLF-030/032/037, ARCH-OPS-23 and QG-SEC-004. There is no new provider,
entitlement policy, scheduler, lifecycle owner or legal claim.

## Confirmed Failures And Corrections

- Main CI38598544709 has3005 passing native identities and9015 passing phases,
  but its fifth shard exceeded the unchanged12-minute job budget. The GitHub
  check annotation positively establishes budget exhaustion. Its aggregate
  correctly failed and browser/staging never ran. A passing PR run with only
  nine seconds of minimum margin was not robust evidence for main.
- Sixteen native CI shards split each prior eight-way partition in two using
  the existing deterministic modulo selector. Peak concurrency remains four;
  job deadlines, database waits, native assertions and Docker's independent
  eight-process whole-file partition remain unchanged. Matrix, reconciliation
  and inventory consumers change together. Timing simulations are estimates,
  not new-source acceptance.
- Main CodeQL has four open unreachable-statement warnings560..563 in
  adversarial finalizer tests. Explicit expected-type exception capture retains
  the original pool body, raise point, exception identity and every cleanup
  assertion. Source-exact tests and fresh actual CodeQL results remain required;
  a successful scan job is not an empty finding inventory.
- The guarded release reached both serving surfaces, then failed closed at
  manual-IP preflight. Original evidence records `execute_attempted:false`
  and only generic `cloud_command_failed`; it discarded the exact stage.
  No dedicated grant job/execution or retained admin mutation was found by
  bounded read-only reconciliation. Historical command causation is unknown.
- Separately, an isolated native Windows CMD probe proves caret/pipe-separated
  arguments truncate the cloud CLI argv, even with exitzero. Default comma
  transport round-trips the full fixed comma-free arguments. This proves a
  transport defect, not the exact cause of the discarded historical command.
  Grant transport and sanitized durable stage diagnostics need fresh proof.

## Authorization And Release Boundaries

Retain the owner's original one-time operation
`dc979781-2c36-46a4-9a7e-17932dab15dc` and approved before-state hash. Only
the existing non-billable `test-legal` subscription may gain manual IP. GBA,
paid plans, provider automation, accounts and other configuration stay unchanged.
Do not retry an uncertain execution, choose a new operation identity or inject
unreviewed helper code into the old serving image.

The failed release's output is retained unchanged. Private-projection cadence
remains paused; later release-owned worker activation/resume was not reached.
New-source local Docker, complete hosted CI, canonical merge and a guarded
exact-SHA deployment are required before the grant and production replay.
Certification must include the six dated IP/Calendar browser identities,
recipient-visible current-source reminder content, exact API/web release,
and automated no-paid-provider isolation. Then require two later serial
quiescent private-maintenance executions and guarded cadence resume.

The unknown historical Matter reopening remains **Inconclusive**. No audit
identity was supplied; lifecycle protections must not be weakened to infer a
cause. Owner-kept provider consent gaps also remain open.

## Retained Evidence

Evidence is under `outputs/calendar-ip-20261013/` in the shared primary
workspace, not uploaded as production application data:

- `docker-db6cd235-r7-01/final-reconciliation-01`: prior exact-tree local
  acceptance3005 native passes and546 browser passes/10 explicit skips.
- `main-09d79527-reconciliation-01/diagnostic-cancel-warnings-01`:
  cancellation annotation, all shard timing and complete partition simulations.
- `guarded-release-09d79527-01`: original guarded deploy exitone and logs.
- `testlegal-manual-ip-09d79527-release-01.json`: original failed-closed grant.
- `manual-ip-09d79527-failure-readonly-01`: bounded no-execution reconciliation.
- `windows-cmd-grant-transport-20261014-01`: isolated full-argv counterproof.

No historical pass transfers automatically to the new recovery candidate.
Daily SEO stays active but release-gated until certification; afterward verify
the actual GSC identity `sanjeev@orchestrum.in` and exact-serving public browser
inventory. No synthetic leads, paid probes or unsupported conversion claims.
