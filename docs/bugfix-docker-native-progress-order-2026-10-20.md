# Docker Native Progress Report Ordering

Source-freeze status: Inconclusive; release NO-GO pending replacement gates.
Scope: release verification for J14/M14, US-040/042 and PRA-01..08. Application
behavior, database rules, authentication and provider policy are unchanged.

## Reproduction And Root Cause

C20 `2948b3a6a417bd94a594261e96ef62ef1b0f82a3` completed candidate CI39411274703,
Security39411274648 and CodeQL39411274550. PR547 merged normally to
`445b359b3910b4b68bb44e4fa36689d6245129d2`, with tree
`f601ac83b0d4f2527ce13ca751fae9c978b9d2a4` identical to C20.

Docker10 completed eight native groups: 3,252 passing cases, 9,756 passing
setup/call/teardown phases, no failures or skips. Its first desktop group
reconciled 312 passes/5 skips. The second raw desktop report contains 296
passes/5 skips, no failures, retries or global errors, and all 301 test-end
events plus a successful session finish. The parent nevertheless exited 1 at
`verify-docker.ps1`'s positional comparison of native and built-in JSON
identities. No canonical second-group completion receipt was written and
mobile five never started. Docker10 is failed, not a complete acceptance run.

Independent joins establish 301 unique identities with no missing, extra or
duplicate case. Twenty-four positions differ across
`release-identity-transport.spec.ts` and `seo_demo_20261009.spec.ts`:
Playwright's built-in JSON reporter regroups cases by their fixture pools,
whereas native collection/final serialization retains declaration order.
Every keyed identity/outcome and full native progress record matches. Native
discovery order also matches native final order exactly. Annotation presentation
differences between the two reporter formats are retained separately; they
were never a reason to erase native progress fields.

## Correction And Regression Contract

Join final built-in JSON cases to native cases by unique stable identity.
Require exact file, line, column and project plus expected/actual status,
one attempt and zero retry. Keep duplicate rejection, nonempty cardinality,
source/config binding, final statistics and errors unchanged. Preserve the
strict native collection-order check and exact full-record progress join.

Regress a legitimate reordered nested/mixed-fixture report and reject missing,
extra, duplicate, altered-identity and altered-outcome records. Replay the
retained real 301-case failure through the corrected verifier without changing
any original bytes. Complete the standard discovered regression module and
fresh full Docker/browser inventories before release acceptance. This document
does not assert those future outcomes or authorize a native skip/carry path.

## Retained Evidence

At 14:40 UTC the narrow correction passed the complete 80-case retention
module with 240 passing phases, including two reordered-pool positives and
28 corruption negatives. Both real Windows PowerShell 5.1 and PowerShell 7
repository-root guards passed their 54 controls. The exact retained 301-case
reports reproduce RED exit1 with the original validator and GREEN exit0 with
the corrected validator; original reports and absent completion remain
unchanged. This is scoped regression proof, not new Docker or production
acceptance. See `outputs/bugs-l-20261019/docker-evidence-identity-fix-01/FINAL-PROOF.json`.

- `outputs/bugs-l-20261019/docker10-readonly-observer-01/terminal-refusal-01/PRIMARY-REFUSAL-PACKET.json`
- `outputs/bugs-l-20261019/docker10-progress-diagnosis-01/REPORT.md`
- `outputs/bugs-l-20261019/docker10-progress-independent-01/FULL-301-PERMUTATION-JOIN.json`
- `outputs/bugs-l-20261019/docker10-readonly-closure-02/FINAL-PROOF.json`

The parent reaped session97777 with exit1. The exact owned project has zero
containers/networks/volumes and no owned port/process remains; all 3,053 C20
raw source pins and 1,766 retained artifacts were verified unchanged. No failed
evidence is overwritten, no previous skip becomes a pass, and no production,
owner setup or email-delivery claim follows from this checkpoint.
