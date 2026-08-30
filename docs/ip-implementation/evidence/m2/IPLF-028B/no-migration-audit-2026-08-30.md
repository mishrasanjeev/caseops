# IPLF-028B no-migration execution-boundary audit

**Slice:** `IPLF-028B`

**Date:** 2026-08-30

**Audited revision:** `820e34bbf71750d9513ba0efbae6ab614963e916`

**Result:** repository diagnostics are executable; export, purge, offboarding,
restore and worker-resume effects remain deliberately unavailable.

## Verdict

`IPLF-028B` is no longer truthfully `not_started`. The authenticated API can
list the reviewed data-class catalog; create, list and read tenant-scoped,
point-in-time dry-run manifests; document source-licence exclusions; classify
held items; expose a content-minimized hold summary; and report incomplete
integrity checks without a reassuring false green.

The slice is not complete. Every data-operation execute request returns the
typed `data_operation_execution_unavailable` refusal. There is no encrypted
export artifact/download/retry path, no purge or offboarding executor, and no
restore/failover/worker-resume control plane. This audit therefore advances
only the slice implementation status to `in_progress`; verification remains
`not_run` and release remains `blocked`.

## Journey-path reconciliation

| Path | Executable repository behavior | Missing effectful behavior | Honest status |
| --- | --- | --- | --- |
| `UJ-28-NORMAL` | Tenant-scoped catalog, point-in-time dry-run, hashed scope/manifest, bounded tenant history | Encrypted background export, included object checksums, expiring download, audited download and separate retention/deletion execution | blocked; not complete |
| `UJ-28-EXC-01` | Dry-run manifest explicitly excludes non-redistributable source payloads and preserves reference metadata | An executing exporter that applies the same exclusion policy | diagnostic half executable; path not complete |
| `UJ-28-EXC-02` | Active scoped holds mark matching dry-run items `held`; safe aggregate hold state is readable | A differentiated deletion attempt that is refused specifically because of that hold | diagnostic half executable; path not complete |
| `UJ-28-EXC-03` | Dry-run records remain readable | No partial export artifact, checkpoint or retry manifest exists | blocked |
| `UJ-65-NORMAL` | Integrity diagnostics identify unavailable checks | No isolated restore, exact-image boot, application cutover, smoke, worker fence or resume operation exists | blocked |
| `UJ-65-EXC-01` | Integrity checks fail visibly as `unavailable` where prerequisites do not exist | No restore validator disables a capability based on missing objects, keys, corrupt indexes or unsafe sends | blocked |
| `UJ-65-EXC-02` | None specific to recovery fencing | No old-region/process fence or single-dispatcher ownership proof | blocked |
| `UJ-65-EXC-03` | Purge propagation can be planned and unresolved targets are reported | No restore-time tombstone/hold reapplication or resurrection test | blocked |
| `UJ-65-EXC-04` | A kill-switch assertion helper and manual-fallback catalog tests exist | The helper has no production service caller and no restore/provider degraded-mode path invokes it | blocked |
| `UJ-65-EXC-05` | None specific to recovery timing | No measured RPO/RTO record, corrective action or disclosure-review workflow | blocked |

No journey path is promoted to `implemented`: the executable portions are
diagnostic boundaries inside larger effectful paths.

## Requirement reconciliation

The repository contains partial controls for:

- `DATA-GOV-01/03`: reviewed data-class projection and change validation, with
  incomplete estate coverage reported rather than hidden;
- `DATA-GOV-04`: scoped hold resolution and a tenant-safe hold summary;
- `DATA-GOV-06/07`: point-in-time dry runs and documented export exclusions;
- `DATA-GOV-08/09`: purge dependency and propagation plans only;
- `DATA-GOV-11/15`: audit and log-sink minimization/redaction;
- `DATA-GOV-12`: an offboarding revocation/preservation plan only;
- `DATA-GOV-17`: an integrity scan that marks unimplemented checks
  `unavailable`.

These are not effectful completion claims. `DATA-GOV-02/05/10/13/14/16/18`
remain materially incomplete, and `DATA-GOV-18` expressly forbids claiming
readiness from dry-run/runbook evidence without automated execute paths.
`RES-01` through `RES-14` remain unproven as recovery requirements; in
particular, source-only helpers are not credited as deployed recovery controls.

Manual review/approval routes are not a completion dependency. They remain
absent. Any future executor must be authorized by machine-enforced scope,
retention, hold, licence, idempotency and recovery boundaries without reopening
a generic human approval workflow.

## Validation

From `apps/api` on the audited revision:

```text
uv run --no-sync pytest -q \
  tests/test_data_governance_service.py \
  tests/test_datagov04_hold_scope_resolver.py \
  tests/test_datagov0607_export_dry_run.py \
  tests/test_datagov08_purge_dependency_plan.py \
  tests/test_datagov09_purge_propagation.py \
  tests/test_datagov11_audit_tombstone_minimisation.py \
  tests/test_datagov12_tenant_offboarding.py \
  tests/test_datagov15_telemetry_redaction.py \
  tests/test_datagov17_integrity_scan.py \
  tests/test_res08_kill_switches.py

110 passed, 33 warnings in 172.74s
```

This is local repository evidence only. No deployment, production restore,
data export, deletion, purge, offboarding or external effect was performed.
