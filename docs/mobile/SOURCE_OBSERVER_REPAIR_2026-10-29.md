# Native source observer repair — October 29, 2026

J20/M22 and QG-SEC-004 remain partially implemented; native release is NO-GO.
This change repairs optional source-gate instrumentation. It does not certify an
APK, Simulator app, Appium journey, store archive or production deployment.

## Reproduction and cause

The retained A8 measured Node inventory executed all 1,262 cases: 1,252 passed,
eight failed and two existing Windows-only cases skipped. Node 24.15.0's real
`--test` controller serializes 25 default startup flags into worker `execArgv`.
The observer omitted 21 exact defaults, so the declared main workers fell back
to detailed coverage. Its raw output also exceeded the unchanged 128-file /
64-MiB bound. These failures remain retained; a functional pass cannot supersede
that measured failure or establish a complete runtime envelope.

A separate native Files reporter unit inherited the optional observer's native
entry refusal. That prevented the deliberately absent fixture from reaching the
controller's own failed preflight and producing its required complete report.

## Repair and stable regressions

- OBS-CLI-01 exercises the actual Node controller and unchanged twelve evidence
  cases. Exact captured defaults select one worker witness, including its engine
  source hash, live event and successful exit marker.
- OBS-CLI-02 changes `--stack-trace-limit` from 10 to 11. All twelve cases still
  pass, while the unreviewed flag keeps detailed fallback and creates no compact
  witness. The allowlist has no wildcard and retains the exact runtime binding.
- IOS-FILES-PREFLIGHT preserves the Files controller's actual absent-fixture
  invocation, all 51 phase results and zero Appium sessions. This one unit removes
  only the optional source-observer keys from its child; the bootstrap, TLS
  policy and detailed-coverage environment remain unchanged. The observer's
  native action refusal and its separate negative controls remain intact.

The bootstrap was regenerated from its readable source with the unchanged
official embedded Acorn parser. Exact AST and output-byte equivalence pass.
All provisioning, Windows CI source-copy, iOS launcher, recorder and provenance
pins were reconciled. The bootstrap remains 6,068 bytes; its Windows option with
source maps remains 8,167 bytes under the original 8,191-byte limit. No trust
anchor, TLS verification, deadline or output cap was relaxed.

## Verification and remaining work

The isolated baseline/candidate/changed-flag reproduction passed three complete
twelve-case runs. The subsequent complete 33-module functional command passed
1,262 of 1,264 cases, with exactly the two existing Windows-only skips, zero
failures/cancellations/todos, unchanged source across execution, actual exit 0
and owned process-group closure. The two newly added cases passed.

Retained attempts include the initial diagnostic syntax error, stale trust-policy
launch refusal and the full run that exposed 28 stale-pin failures. The corrected
complete functional run supersedes those functional attempts only. Fresh measured
observer composition, raw-output reconciliation, hosted CI and final native
acceptance are still required. Do not describe the measured eight failures as
closed until their complete replacement inventory passes its original bounds.

Local immutable evidence is under the task cache's
`source-observer-defaults-candidate-01/run-02` and
`root-native-contracts-functional-23`; earlier directories remain preserved.
