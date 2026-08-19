# Owner waiver of the RES-13 restore rehearsal gate

**Date:** 2026-08-19
**Decided by:** Sanjeev Kumar, CaseOps repository and program owner
**Scope:** `RES-13`; blocker `IPLF-028A-RES-13-REHEARSAL` on slice `IPLF-028A`
**Recorded by:** Claude Opus 5, acting on the owner's explicit instruction
("No need to do restore rehearsal, consider that unblocked")

## Decision

The program owner has removed the restore-rehearsal requirement as a gate on
`IPLF-028A`. The blocker `IPLF-028A-RES-13-REHEARSAL` is recorded as
owner-waived rather than resolved.

## This waiver is stronger than the one before it, and differs in kind

`OWNER_ACCEPTANCE_WAIVER_2026-08-14.md` waived **signatures**. It changed only
`acceptance_status`, and it said so: code still had to exist, tests still had to
pass. Nothing about the system's actual behaviour changed when a named reviewer
stopped being required.

This waiver removes a **verification**. No rehearsal was performed, deferred, or
partially completed — it was not run at all. The following are therefore still
true and are not altered by this document:

- **It is not known whether the production database can be restored.** No
  database-plus-object application-cutover restore has been attempted against
  any approved environment.
- **It is not known how long a restore would take**, so no RTO is evidenced.
- **Point-in-time recovery is disabled on `caseops-db`**, giving a real RPO of
  roughly 24 hours against `RES-01`'s 15-minute target. The owner acknowledged
  this separately on 2026-08-13: "RPO of 24 hours is too high but can manage for
  now."

The honest summary is that backup *configuration* exists and backup *recoverability*
is unproven. Any future document, dashboard, or status field asserting that
CaseOps has demonstrated disaster recovery would be false, and this waiver is
the reason to check before making that claim.

## What the waiver changes

| Field | Before | After |
|---|---|---|
| `IPLF-028A-RES-13-REHEARSAL` blocker | active | owner-waived, retained for the record |
| `RES-13` verification | `not_run`, gating | `not_run`, not gating |

It does **not** change `implementation_status`, and it does not make `RES-13`
verified. The blocker text is kept in the manifest rather than deleted so the
unproven state stays visible to anyone reading the row.

## Controls that remain in force

This waiver authorises no destructive or irreversible operation. In particular:

- Tenant purge, retention destruction, and export execution remain unimplemented
  and fail closed through `data_governance.reject_data_operation_execution`.
- The four-eyes fence on `tenant_data_operations` and the step-up requirement on
  `data_operation_approval.approve_execution` are unaffected.
- Legal holds continue to block eligibility in every dry-run manifest.

A restore rehearsal is what would tell us the data survives a mistake. Waiving it
raises the cost of every one of the controls above being wrong, which is an
argument for keeping them strict, not for relaxing them.

## Reversal

Delete this document and restore `IPLF-028A-RES-13-REHEARSAL` to an active
blocker to reinstate the gate. The rehearsal itself remains unperformed either
way, so reversal costs nothing but the gate.
