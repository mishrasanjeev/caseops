# Renewal Response Integrity

Status: Inconclusive; release NO-GO until fresh complete gates and production
replay. Scope: UJ-02/04/26, IPLF-037 and their existing source-date/notification
contracts. No legal source, entitlement, provider or lifecycle policy changes.

## Evidence

- R21 `f4fa6dcd7182bf18276a30cca0faffc280681c1e`, main CI39465871860:
  605 browser passes, 17 explicit skips, one failure, no retries. The failure
  is `ram-2026-10-13-ip-portfolio.spec.ts`, the 393px source-tolerant import
  journey, renewal-date correction assertion754.
- Its originating database exception was not retained. Local original-source
  diagnostics05 reproduced after_commit, after_begin, SQLite SQLITE_ERROR1
  and circular/reference evidence. The safe SQL graph repeats anonymous
  `anon_4` declarations at four nested depths. This is not SQLITE_BUSY and
  does not justify an automatic mutation retry.
- Diagnostic06 only hoisted anonymous stages and returned500; it is failed
  evidence, not an accepted fix. Diagnostic07 assigned five explicit stage
  names, retained all nesting/materialization/predicates and completed all
  three date corrections with HTTP200. Its complete journey then failed at
  assertion798: the notification's offsetless SQLite timestamp was interpreted
  in the Windows client's timezone, producing the wrong alert-day expectation.
- All original artifacts remain under
  `outputs/bugs-l-20261019/r21-renewal-sqlite-diagnostic-01`; external AST
  diagnostics are not canonical acceptance or evidence for production.

## Correction And Regression Scope

Give the scoped, provenance, raw-date, validated-date and stopped-source CTEs
distinct stable identities. Keep the existing nested scope, PostgreSQL
MATERIALIZED prefix, tenant/ACL boundaries, exact current-version joins,
malformed-date protection and source eligibility. Exercise warm tracker,
portfolio list/count/category queries and the complete dated browser journey.
Do not merely remove the legacy writer's unused tracker response.

Normalize known UTC notification persistence fields at the response boundary,
including reminders, delivery intents and suppression receipts. Require
explicit offsets, preserve nulls and the exact instant for non-UTC aware
values, and test alert dates around local midnight. Keep the existing exact
browser assertion; do not make it accept either date.

The unrelated CodeQL595 mixed-return note is addressed only by annotating the
unconditional HTTP400 helper as NoReturn, with direct MIME/extension controls.
Its body is unchanged; a fresh hosted scan must establish resolution.

## Scoped Local Results

- `test_ip_tracker_cte_identity_20261021.py` deterministically reuses the
  anonymous CTE seed: the original source failed four calls, including three
  HTTP503s. The replacement and all three adjacent modules pass 63 cases and
  189 phases, without skips or retries. All 21 PostgreSQL-marked cases were
  deselected, not executed; the three new native cases are discoverable and
  still require the Docker gate. Repeated tracker/portfolio queries retain real
  compiled-cache hits and independent all-row versus 90-day category counts.
- The first replacement run's 61 passes/two failures remain retained. Its new
  test incorrectly counted a May16 fixture inside the Jan1-to-Mar31 horizon;
  the corrected independent expectation leaves the product horizon unchanged.
- `test_notification_response_utc_20261021.py` plus the existing notification
  self-test pass 18 cases/54 phases. The original response boundary failed 11
  explicit-offset assertions, including real SQLite reload-to-HTTP output.
  All 11 persisted timestamp fields are covered; three DTO JSON Schemas are
  byte-equivalent as structured documents before and after the correction.
- `test_matter_import_mime_contract.py` and `test_matter_imports.py` pass
  52 cases/156 phases. The original annotation failed its dedicated contract;
  all prior rejection behavior remains unchanged.

Retained local proof roots are `r21-renewal-503-diagnosis-01`,
`notification-dto-utc-01` and `codeql595-noreturn-01` beneath the existing
BUG008 output directory. These scoped results are not summed into a distinct
whole-suite count and are not Docker, hosted CI or production certification.

## Release Boundary

C22 `30d9ba70b3212df60b72416fca149ba6294a9eae` completed a fresh standard-config
build and all four dated IP portfolio browser cases at 1280px/393px, with zero
skips, retries or global errors. Native collection, JSON, JUnit, progress and
all 3,058 source hashes reconcile. This is focused C22 proof, not acceptance
for a later dependency revision or the whole release.

C22 Security39490391664 subsequently failed on critical
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
published October20. Its frozen certifi2026.2.25 includes the affected trust
root; the first patched release is
[2026.10.19](https://pypi.org/project/certifi/2026.10.19/).
Patch that dependency and rebuild images without disabling TLS verification
or changing the audit policy. Preserve the original scan and require fresh
complete gates on the actual replacement commit.

The local follow-up updates only certifi's lock entry and official artifacts;
both hashes match PyPI. All 137 other installed third-party versions remain
unchanged, and the normal 139-distribution environment includes the restored
editable application. Two offline trust-bundle regressions pass six phases:
the compromised G3 root is absent and certificate/hostname verification remains
required. The hash-pinned old bundle fails the root exclusion control without
downgrading the active environment. Strict OSV audit passes for the same 138
non-editable dependencies selected by the canonical CI workflow. This is
scoped local security evidence, not replacement hosted or image acceptance.

Docker12 stopped before application tests because the operator selected
Windows PowerShell5 rather than Docker11's actual accepted bundled PowerShell7
host. An isolated control reproduces stderr from a native exit0 becoming
NativeCommandError on5, while7 accepts exit0 and rejects exit17 explicitly.
Docker13 used the accepted host, but was deliberately superseded after the
critical dependency finding. Its owned native child was stopped, canonical
cleanup ran and its parent was reaped. Neither run provides native PostgreSQL
or browser acceptance; retain both and start the replacement from fresh images.

C21's accepted Docker11 and candidate CI do not override R21's failed main
replay and cannot certify changed source. Require fresh combined Docker/CI,
normal main merge, exact-tree confirmation, current-main release guards and
the exact-serving production journey. Production remains `9cf76f2b` at this
checkpoint. Preserve independent legal-source, Calendar cleanup, unknown
historical incident and initial manager setup qualifications in all workbooks.
