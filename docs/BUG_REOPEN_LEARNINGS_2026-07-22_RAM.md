# Ram 2026-07-22 Conflict Review Policy Audit And Permanent Learnings

Source workbook: `CaseOps_Bugs_Ram22Jul2026.xlsx`

Audit date: 2026-07-22

Production baseline tenant: `legal` (tester credentials are intentionally not
stored in source or this document)

## Honest classification and verdict

| ID | Classification | Why | Formal verdict |
| --- | --- | --- | --- |
| BUG-001 | Valid workflow/product-policy enhancement | The product deliberately enforced a conflict gate for existing Intake/On-hold matters. The workbook now explicitly makes conflict checking optional and nonblocking for that transition. | `Properly fixed` on deployed commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a`. |

This is not evidence that the old code randomly regressed. It is a broader
acceptance contract than the one deployed on July 15.

## What the product did before this request

- Commit `d8056ee` introduced the existing-matter activation gate.
- The July 7 repair made that gate recoverable in the UI and fixed the real
  client-scan crash and large-tenant query cost.
- Commit `64f7688` implemented the July 15 creation-only exception: direct New
  Matter creation could be Active without a check, while an explicit
  Intake/On-hold to Active transition remained gated.
- Commit `c3df6e8` repaired the shallow default drift left behind by that first
  change by aligning the shared default, schema, ORM/database default, imports,
  documentation, and regression coverage.
- Reopened matters returned to Intake and treated pre-reopen clearance as
  stale; the July 15 contract then required a fresh check before Active.

The July 22 workbook supersedes the last two gate clauses. It does not undo the
scanner, resolution, tenancy, audit, performance, lifecycle, or concurrency
work.

## Brutal analysis: where the earlier work went wrong

1. **I closed the noun, not the whole state transition.** July 15 said New
   Matter, and I correctly changed direct creation, but I let the stronger
   product phrase conflict checks are optional coexist with a mandatory gate on
   the very next transition. The code matched the narrow row; the product story
   remained internally inconsistent.
2. **I turned an implementation decision into a permanent invariant.** Exact
   409 tests, UI recovery copy, the bug-fixing skill, lifecycle documentation,
   public copy, and fixture helpers all repeated the gate. Once duplicated, a
   policy change looked like a risky exception instead of a deliberate contract
   update.
3. **I treated adjacent-path coverage as a checklist, not a producer/consumer
   graph.** Intake promotion deliberately creates an Intake matter; generic
   status PATCH then consumed that state through the gate. Creation tests could
   stay green while the user still hit the same block one step later.
4. **I confused freshness with permission.** A pre-reopen or pre-party-change
   result should not be labelled current clearance. That does not imply the
   result must veto status. Evidence freshness and lifecycle permission are
   separate concerns and must remain separate in code and copy.
5. **I allowed tests to fossilize obsolete behavior.** Tests that assert the
   exact blocking message are useful only while the gate is the accepted
   contract. After supersession they become harmful: they pressure future work
   to reintroduce the old bug.
6. **I let current ledgers contradict release evidence.** The July 15 learning
   recorded deployed Playwright closure while the strict bug/product ledgers
   still said production verification pending. Contradictory source-of-truth
   documents make later triage slower and encourage shallow rework.
7. **I used the word reopen for two different failures.** A bug report can
   reopen because acceptance changed or proof was shallow. A Matter row can
   reopen only through the explicit Disposed-to-Intake lifecycle service. Those
   are different systems and need different evidence.

## Why cases are reopening

The July 22 report does not show disposed matters reopening by themselves.
CaseOps permits a Matter to reopen only through the dedicated lifecycle path,
which requires archive capability, a reason, expected source status, and a
timestamp/concurrency precondition. Generic metadata PATCH and background
writers must not reopen it.

When that explicit lifecycle action runs, the Matter lands in Intake. Prior
conflict clearance remains historical because it predates the new lifecycle.
Under the July 22 policy, that history is advisory: it cannot block a later move
to Active. A fresh check is needed only before someone claims the matter is
currently conflict-cleared.

## Effective product contract from 2026-07-22

- Conflict Check remains a tenant- and matter-scoped, auditable workflow.
- Permitted users can run a scan; authorized reviewers can clear, mark
  conflicted, or waive with a note.
- New Matter defaults to Active and direct Active creation is allowed.
- Intake and On hold can move to Active with no conflict check.
- Missing, pending, conflicted, cleared, waived, invalid, stale-party-scope,
  and pre-reopen results are all nonblocking.
- Material party changes and reopen make earlier clearance historical, not
  current. They do not create a status gate.
- Restricted-matter access, ethical walls, tenant isolation, terminal status,
  optimistic concurrency, and audit requirements remain independent and
  fail-closed.
- No speculative per-tenant mandatory-gate mode is part of this workbook.

## Whole-product paths changed together

- Backend status transition service and the former gate helper/import.
- Matter editor hint, 409 recovery branch, Conflict Check card instructions,
  and lifecycle dialog copy that previously described the gate.
- API tests that previously expected missing/pending/conflicted/stale checks to
  deny activation.
- React tests and dated Playwright specs that previously celebrated the 409.
- Reopen regressions that previously required a fresh check before Active.
- Public `/guide`, README, marketing FAQ, `/llms.txt`, and `/llms-full.txt`.
- `PG-001`, strict bug/enterprise ledgers, July 7/15 historical learning docs,
  and the permanent bug-fixing skill.
- Test helpers that unnecessarily manufacture a cleared check merely to create
  or activate fixture data.

## Mandatory regression contract

### API

- Parameterize Intake and On hold to Active with no check; assert success,
  final read-back, and no conflict-gate denial audit.
- Repeat with pending, conflicted, invalid, stale-party-scope, and a
  pre-reopen result. None may block.
- Prove active-to-active metadata edits and optimistic concurrency still work.
- Prove terminal-state protections still reject invalid lifecycle writes.
- Prove the scanner, candidate list, clear/conflict/waive decisions, tenancy,
  access controls, redacted audit metadata, and large-tenant prefilter remain
  functional independently.

### React and browser

- Selecting Active submits normally with no blocking hint or recovery-only CTA.
- The optional Conflict Check card remains visible and usable.
- Local Playwright creates/uses local-equivalent tester data, exercises Intake
  and On hold, and verifies persisted Active state after reload.
- The same committed production spec runs with the supplied test account, no
  mocks, no conditional skip, and records the deployed build identity.
- Reopen proof confirms Disposed to Intake, historical old clearance, then
  successful Active without a fresh check.

## Permanent repository rules added

- Policy changes must explicitly retire the old invariant from code, tests,
  fixtures, UI copy, public copy, skills, and ledgers.
- Optionality is tested across every state that could preserve hidden blocking,
  not only the no-record happy path.
- Historical records receive supersession annotations; their still-valid
  technical learnings are not erased.
- Freshness of review evidence and permission to change lifecycle status are
  separate concepts.
- A local pass is not production closure. `Properly fixed` requires the exact
  deployed build and committed production Playwright evidence.

## Current closure state

The workbook row is accepted as a valid product-policy enhancement. Repository
documentation now records the supersession and permanent rules.

Evidence captured on 2026-07-22:

- canonical backend verification passed Ruff plus all 59 tests in the four
  affected conflict, lifecycle, intake, and import files;
- 19 focused React tests across three files, TypeScript, and the 64-route
  production web build passed;
- the combined July 15 and July 22 local Chromium run passed 5/5 in 20.5s with
  the shared exact `legal` local identity. The two July 22 cases passed in
  1.3s and 2.1s: Intake activated without a check, and the controlled lifecycle
  case recorded a cleared review, activated On hold, disposed, reopened to
  Intake, rendered the old clearance as `Historical (stale)`, then activated
  and persisted after read-back and reload;
- before deployment, the extended committed production Chromium spec
  authenticated as the supplied tester and reproduced the prior build's HTTP
  409 requiring Clear/Waived. The second serial controlled-reopen case did not
  run; `afterAll` emitted no cleanup failure. This is retained as the
  pre-deploy production reproduction, not final fix evidence;
- the browser harness was made deterministic for a fresh no-install-project
  venv and build-time API/CSP origin, removing two workstation-only false-proof
  paths discovered during this replay;
- exact commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a` was deployed with
  `scripts/deploy-prod.sh`. Migration execution `caseops-migrate-job-ggqwz`
  succeeded, all four recurring jobs were pinned to API digest
  `sha256:23d2e9313cf8a99f538e3dbd5f9a9cfc0533e0559de0fc16f4b02df4a18e3b94`,
  API revision `caseops-api-00210-fnv` and web revision
  `caseops-web-00189-k9f` received 100% traffic, public health reported status
  `ok`, and the ClamAV sidecar remained present;
- the same committed production spec passed 2/2 with the supplied `legal`
  tester account in 71.6s. It proved no-check Intake activation and the full
  On hold -> Active -> Disposed -> controlled reopen -> historical-clearance
  -> Active workflow, including persistence, reload, and fail-loud cleanup;
  and
- GitHub production-verification run `29929098217` checked out the exact
  deployed SHA, passed both July 22 cases again on the independent QA tenant,
  completed the RAM batch with 46 passed and four expected conditional skips,
  and passed the notice module 2/2.

The formal production verdict is **`Properly fixed`**. The deployed-build
identity and both tester-tenant and independent-QA production evidence are
recorded in `docs/runbooks/release-signoff-2026-07-22-34f19ad.md`.
