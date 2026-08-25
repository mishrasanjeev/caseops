# IPLF-056B exact-production verification attempt

**Date:** 2026-08-25

**Merged and deployed revision:** `fdbfe8af459ddfabf6cd32f6d01e81a2902a58d2`

**Production workflow:** `32814217518`

## Exact release

The workflow verified that both production services served the exact merged
revision before running acceptance. Production remained healthy on API revision
`caseops-api-00348-b64` and web revision `caseops-web-00326-f2v`; deployment had
already reconciled all recurring jobs to the exact API digest and latest-only
traffic.

## Result

The broad production batch executed 84 tests: 82 passed and two failed. The A0
quiescence acceptance and notice-module acceptance then passed. This attempt is
not a deployment-verification pass and does not promote IPLF-056B.

The IPLF-056B provider test failed because its credential-leak regex treated the
visible phrase `API token` as a leaked credential without requiring a value. The
page had already passed the provider readiness, default-off, and shared-control-
plane assertions. Candidate `c846287f` now rejects the exact session token and
only treats token-labelled values of credential length as a leak.

The older IPLF-026B access test reached the revoke-preview command but did not
capture its API response before asserting the replacement UI. Candidate
`c846287f` now waits for that exact response and reports its body/status, making
any server defect distinguishable from timing or UI state.

## Boundary

IPLF-056B remains `ready_for_review` until a candidate containing these verifier
repairs is merged, deployed exactly, and passes the dated production workflow.
Live IP India and Indian Kanoon calls remain separately fail-closed pending the
already documented external approvals.
