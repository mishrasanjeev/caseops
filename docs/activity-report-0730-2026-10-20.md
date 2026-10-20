# Activity Report: Four Private Recipients at 07:30 IST

## Combined Candidate Checkpoint

The implementation snapshot below records the separate branch at05:01 UTC.
After parent review of all12 source hashes and the exact105-case/315-phase
collection/JUnit results, it was brought into the upcoming combined C16. C15
Docker08 was deliberately stopped for the new scope and its source/resource
hold released after closure; no native or browser result is carried. Fresh
complete Docker09, hosted CI, main merge and exact-release production acceptance
are still required. The original implementation branch was locally committed
as `b85e2b55`; it was not pushed or independently deployed.

The owner-authorized Gmail-only global suppression removal was separately
confirmed at04:47:51 UTC (DELETE204, then GET200 with an empty object). This
does not establish a delivered catch-up or change the other recipients' consent.

## Scope And Status

Ownership: J14/M14, US-040 (operational oversight) and US-042 (audit/secret
hygiene). This is a separate feature branch based on C15
`5ab8a35e25c9e071deba3d9a57654254f0ff649e`, not part of its frozen release
acceptance. No commit, push, merge, deployment or provider operation is admitted
by this document. Production-delivery verdict: **Inconclusive**.

Parent reports that the former sole Gmail recipient was globally unsubscribed
on October 18-20. That provider condition is separate from application HTTP
acceptance. The parent owns the authorized removal of only that Gmail global
unsubscribe; no other suppression or recipient state may be changed here.

## Contract

- Preserve `CASEOPS_ACTIVITY_REPORT_RECIPIENT_EMAIL` and its legacy single Gmail
  default. Accept a maximum of 1024 input characters and one to four unique
  semicolon-separated bare addresses. Trim whitespace, normalize using the
  existing email-validator dependency without DNS, and deduplicate
  case-insensitively in first-seen order.
- Reject empty segments, malformed addresses, display names, angle addresses,
  controls, Unicode line separators and over-limit input before transport.
  Revalidate at send time even if cached settings were mutated directly.
- Make exactly one POST with one `to` address per personalization, no shared
  To/CC/BCC, unchanged content and a 30-second timeout. Keep the existing `sent`
  caller contract: it means provider HTTP acceptance, never confirmed delivery.
- Keep scheduler `caseops-activity-report-0800-ist` and run job
  `caseops-activity-report`. Its historical name is an identity, not the new
  time: use cron `30 7 * * *`, timezone `Asia/Kolkata`, with task `max_retries=0`.
  No additional scheduler, job, retry loop or provider SDK is introduced.
- The inventory's sole activity-report recipient value is exactly
  `mishra.sanjeev@gmail.com;sanjeev@orchestrum.in;ram.gupta@edumatica.io;uday.chauhan@edumatica.io`.
  Database/auth/SendGrid secrets remain Secret Manager references.

## Test Mapping

| Requirement | Existing regression module and cases |
| --- | --- |
| US-040 exact private recipients and legacy compatibility | `test_activity_reports.py`: one-post four-personalization contract, legacy default, ordered normalization/deduplication and no-DNS control |
| US-042 fail-closed bounded configuration | Same module: settings and send-time negatives for malformed/empty/display/header/control/over-limit input, disabled and missing-credential paths |
| No uncertain-send replay | Same module: provider 400/429/500 and timeout/connection failures retain one attempt and real errors |
| Existing content/privacy | Same module's complete rendering/account-period/excluded-test-account cases; complete `test_send_activity_report_script.py`, including dry-run/no-send and no false sent log after failure |
| Exact cadence and no resource duplication | Complete `test_scheduler_inventory.py`: same scheduler/run-job, 07:30 IST, exact four recipients, semicolon argument preservation, zero task retries and unchanged eleven-job inventory |
| Secret hygiene | Complete `test_cloudrun_manifest_secrets.py`, including inventory and canonical manifest checks |

## Verification

The retained pre-change regression ran two exact cases against C15 production
source with the new tests: both failed at the intended private-payload and
08:00-vs-07:30 assertions. No mail or cloud call was made.

The complete host run passed 105 tests and all 315 setup/call/teardown phases,
with no failures, errors or skips: activity reports 34, report command 3,
scheduler inventory 58, manifest secrets 10. Retained collection and JUnit
identities match exactly; runtime/test pins were unchanged during execution and
the child exited naturally with code zero and was reaped. Ruff reported zero
findings across the five changed Python files, `git diff --check` passed, and
the isolated environment's 138 installed packages passed `uv pip check`.

Evidence is retained under
`outputs/bugs-l-20261019/activity-report-0730-implementation-01` outside this
worktree. This is host-only, not Docker, release or delivery acceptance. The initial isolated
offline environment setup hit a Windows cached-jsonpatch hardlink error; that
failed setup is retained. Copy-mode frozen/offline installation repaired only
this new worktree's environment without changing the lock or another checkout.

Parent plans a combined C16 after source/resource closure and review. C15
Docker08 was operator-stopped without a failed assertion; its incomplete result
is not feature or replacement acceptance. No Docker resources were launched or
changed here. Fresh combined-candidate Docker09, deployment, actual 07:30 cadence,
provider delivery evidence and recipient inbox receipt remain open. No local
green substitutes for those outcomes. No commit or push has been made here.
