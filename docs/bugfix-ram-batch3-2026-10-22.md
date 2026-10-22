# Ram Batch 3: Draft Recovery And Client Editing

## Source And Classification

The supplied `CaseOps_Bugs (3).xlsx` contains two populated issues, Bug Sheet
rows2/3. The source hash is
`9343973e38a062d94de391f8c7a32a1e1bf661c82ccf09d2072cd33f0ea58c63`.
Its reported dates say October23 while acquisition is October22; retain that
discrepancy rather than altering the source. BUG001's remarks repeat client-edit
wording and are not an additional draft requirement. No credentials belong in
the summary or repository.

- B3-001 / sourceBUG001: approval with zero verified citations is a required
  legal-safety rejection, not a defect to bypass. The usable recovery workflow
  still needs acceptance: current UI offers known-ineligible approval, gives
  generic recovery copy and does not expose the existing regeneration focus
  input. Classify the safety behavior separately from the UX gap. Current
  citation verification proves catalogue existence, not proposition correctness.
- B3-002 / sourceBUG002: confirmed UI gap. The authorized update API exists,
  but the client profile has no edit control after creation or KYC. Supply a
  prefilled contact/address editor and preserve client identity, KYC evidence,
  matter associations, audit and capability/tenant fences. Changing only the
  creation-form promise is not a fix.

## Product Mapping

Drafting: J07/M06, US-017/018/021, FT-027..030, MOD-TS-008/012.
Client management: J12/M11, US-034/035/037,
FT-044..046/049, MOD-TS-009/013. No paid-provider or legal-verification policy
change is authorized. Keep current administration/enquiry release certification
on its frozen source while the independent batch is implemented.

## Required Proof

| ID | Boundary |
| --- | --- |
| B3-DRAFT-01 | Current zero-citation revision keeps approval unavailable with persistent reason and server422 defense. |
| B3-DRAFT-02 | Recovery opens current Matter source context and exposes bounded regeneration focus using the existing contract. |
| B3-DRAFT-03 | Real local deterministic regeneration makes a new version; only the latest verified count enables approval, with reload persistence. |
| B3-DRAFT-04 | Older positive versions cannot authorize a latest zero-citation version. |
| B3-DRAFT-05 | Permissions, finalized/filed/served immutability and provider failures remain fail-closed; no automated paid calls. |
| B3-DRAFT-06 | Desktop and mobile actions fit the available work area; stale/error feedback is actionable. |
| B3-CLIENT-01 | Real existing client can open a prefilled editor with clients:edit. |
| B3-CLIENT-02 | Contact/address update and explicit clearing persist after profile/list reload. |
| B3-CLIENT-03 | Verified KYC evidence, identity, relationships and audits survive contact edits unchanged. |
| B3-CLIENT-04 | Unauthorized/cross-tenant/archived paths remain unavailable or reject without mutation. |
| B3-CLIENT-05 | Validation and failure retain user input and expose the actual safe problem. |
| B3-CLIENT-06 | Desktop/mobile keyboard and visible actions work, without hidden or zero-width controls. |

## Current Verdict

Component acceptance:37 passed across the three client/draft page modules.
Complete client native acceptance:47 passed,141 setup/call/teardown phases,
including9 new PostgreSQL contact cases and9 SQLite siblings; source was stable,
with no skipped cases. Evidence is retained in `outputs/bugs-3-20261022` under
the primary workspace, not committed with confidential runtime artefacts.

Full frontend coverage01 passed1864 cases with unchanged thresholds on the
pre-browser candidate. Actual Docker preflight01 collected6 but did not execute
them because its caller had not created the native reporter directory. Preserve
it as incomplete infrastructure evidence. Replacement preflight02 executed all6:
2passed (mobile contact persistence and independent permission/tenant/archive
negatives),4failed. Desktop contact/fault tests incorrectly used the host's
touchscreen capability to select Playwright tap; select the configured project
hasTouch instead. Both drafting cases exposed the actual20px Matter-context
link target; increase its visible target, keep the24px geometry assertion and
replay the complete six-case inventory. These failures are not green acceptance
and the earlier frontend proof does not cover the subsequent class change.

Bounded read-only production metadata at API92f162b4 shows the screenshot Matter
has a differently titled current draft with5 catalogue citations at revision2
and0 at revision1. Two other retained Appeal Memoranda are accessible, one
finalized with1 citation and one draft with3. They are not the pictured draft
and were not modified. The exact screenshot's failed approval is not recreated
by those records. No automatic Matter reopening is established by that metadata.

Both outcomes remain Inconclusive for deployed acceptance. Source inspection,
fixture tests, a submitted PR and an older release do not prove production.
Record exact intended/collected browser identities, no skips/retries, local
Docker image identity, CI, merged main and the serving API/web revision before
changing the workbook verdict. No silent Matter reopening is established by
this workbook; investigate the persisted lifecycle audit rather than assuming it.
