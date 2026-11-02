# Ram 2026-10-30 batch 4: why Ram's bugs keep reopening

Source: `CaseOps_Bugs (4).xlsx`, 17 populated rows (BUG-001..BUG-016,
ENH-017), reported in test-legal on Chrome desktop. Integration branch:
`codex/ram-bugs4-20261031`. Ledger: `docs/STRICT_BUG_TASKLIST_2026-04-22.md`,
October 31 Ram Batch 4.

## Verdicts

Every row is `Inconclusive - complete local proof; production verification as
the reporting tester pending`. Nothing is deployed. BUG-003..006 also need the
IPLF-027B A1 release and the A2 governance enable before Ram can reach them.
The lane-level positions that matter for the next verdict:

- The first independent reviews rated seven rows `Partially fixed`: BUG-001,
  BUG-002, BUG-003, BUG-006, BUG-007, BUG-010 and BUG-016. A fix pass closed
  the named defects locally.
- BUG-015 asks for autonomous full-application testing. The PRD maps it to
  FT-099, a control crawl of the tester tenant. That is narrower than the row.
- The docket-sweep lane is `Partially fixed`: the watch workspace still drops
  rows past 250 silently.
- Owner decisions are open on BUG-005 (dropping the pasted SHA-256 field) and on
  working calendars staying writable while governance is off.

## The pattern in one paragraph

Most of this workbook is dropdowns that show only "Select" and buttons that do
nothing. These are the defects that earlier batches "fixed". Each fix was
proven somewhere other than where Ram stands: in a fixture that built the
missing data first, in a tenant with a flag Ram does not have, in a journey
whose assertions sat behind a branch that production never takes, or in a test
that read the first page of a list. This batch repeated the pattern inside its
own lanes. The lanes reported their first implementations as fixed locally. An
independent adversarial review then found blocking or major defects in every
one of the twelve. A self-reported local green does not
predict what Ram will see.

## First-implementation review findings

| Lane | Rows | First review | Representative defect the implementer missed |
| --- | --- | --- | --- |
| matter-links | BUG-007 | 1 blocking, 3 major | Enter in the Matter search submitted the portal invite for the previously chosen Matter |
| calendar-year | ENH-017 | 4 major | Tapping Year on a phone changed nothing on screen; the spec failed whenever today+47 crossed a year |
| ip-create | BUG-001/002 | 1 blocking, 5 major | Two older specs still drove the removed form; the same bare class input remained on opposition and post-registration |
| governance-ui | BUG-003..006 | 1 blocking, 5 major | The client acknowledged the server's activation impact review on the user's behalf; person pickers offered walled members |
| foreign-associates | BUG-009/010/011/013 | 1 blocking, 5 major | "Link a Matter" opened a view without Link Matter; production acceptance asserted shared record state that the fix invites Ram to change |
| invoice-pdf | BUG-016 | 2 blocking, 5 major | Void left the total in billing KPIs; there was no way to issue a draft, so every PDF Ram could download said "not payable" |
| fixture-honesty | BUG-002(b) | 1 major | A production spec toggled test-legal's AI policy |
| watch | BUG-014 | 9 major | A new ethical-wall leak: unlinked journal entries and their notes became visible tenant-wide |
| registry | BUG-012 | 4 major | An application-less docket linked to a page that cannot add an application; five sibling pickers were still first-page only |
| recordals | BUG-008 | 2 major | The "sibling sweep" missed a hand-copied predicate in the Madrid validator that skipped document access |
| madrid-portal | BUG-015 sweep | 4 major | Grants were offered that publish rejects; renewals still asked for four raw IDs after "no change needed" |
| docket-sweep | adjacent | 6 major | The paging test never crossed a page boundary: a one-page reader passed it |

## Mechanisms, with this batch's examples

### 1. Proof in a fixture or tenant other than the tester's

- The foreign-associate local test created its docket already linked to a Matter
  through the API. The Matterless path Ram reported (BUG-010) was never walked,
  so the wrong-view link went unnoticed.
- The invoice journey ran on Ram's real reported Matter. Each run added INR
  3,58,000 to his KPIs and consumed the shared billing profile's invoice
  sequence.
- The governance journey proved activation with three local people and the flag
  on. In production Ram is alone and the flag is off.
- The portal-invite proof is local because Ram's portal:invite capability in
  test-legal is not established.
- BUG-002(b): every local tenant received its Classification entries when the
  spec enabled the workspace through the API (`support/ram-bugs4.ts`,
  `configureLocalWorkspace`). Ram's test-legal workspace was enabled before
  that code existed, so its entries can only come from migration
  `20261031_0001` (trigger `release_backfill`), which is not on main.
  `test_ip_document_taxonomy_defaults_migration_20261031.py` proves the
  backfill on tenants shaped like the pre-release state, but no browser journey
  ran against a backfilled tenant. The ip-create lane's own review named this
  dependency, and the first ledger draft dropped it.

Permanent rule: accept a tester's bug only in the reporting tester's own tenant
and role, on the exact serving release, from records the journey creates
through the UI with fresh identifiers. Read preconditions from server data,
never from the state of a shared record.

Guard now in place: the batch-4 specs sign in through
`tests/e2e/support/ram-bugs4.ts` as Ram on test-legal in the tester production
projects. `ram-2026-10-31-foreign-associates.spec.ts` creates a fresh Matterless
record and makes each prerequisite through the form's links.
`ram-2026-10-31-invoice-pdf.spec.ts` uses a stamped QA Matter and compares the
billing profile read-only before and after.

Gap: no static check stops a production spec from asserting mutable shared
state. The release workflow's required positive receipts
(`scripts/prod_playwright_evidence.py`) are still being wired for batch 4.

### 2. A conditional branch or a skip counted as a pass

- Eight batch-4 tests in seven specs are `[local-only]` and skip in
  production:
  - `invoice-pdf.spec.ts:408` and `:416` (issuing is final)
  - `governance-ui.spec.ts:357` (three approvers)
  - `matter-links.spec.ts:353` (portal invite)
  - `foreign-associates.spec.ts:407` (GBP assignment)
  - `madrid-portal.spec.ts:192` (publish)
  - `registry.spec.ts:327`
  - `fixture-honesty.spec.ts:131` (classified upload)
- `invoice-pdf.spec.ts:424` and `:432` are `[prod-only]`; they have not
  executed anywhere yet.
- The control crawl skips reported-record routes locally
  (`control-crawl.spec.ts:154`).
- The docket-sweep journey (`docket-sweep.spec.ts:84`, `:94`) branches on
  `if (body.total === 0)` (`:61`). Calendar-copy reviews cannot be created
  through the UI, so locally, and almost certainly in production, only the
  empty-state branch runs. The over-100 behaviour is proven by vitest (100 of
  137) and the pytest population tests, not by the journey. This is a known
  limitation of this batch's own spec.
- On the foreign-associate form, the crawl stopped before record selection.
  Every per-record select was legitimately disabled there, so "zero offenders"
  proved nothing.
- The 2026-04-26 anchor incident (BUG-018 skipped on Ram's tenant and called
  verified) is the same mechanism.

Permanent rule: a `test.skip`, a `[local-only]` grep exclusion, an `if` that
guards assertions, or a crawl that never reaches the control is a skip. A
verdict counts only assertions that production executed. A workflow that
production can never run stays `Inconclusive`, with that reason stated.

Guard: AGENTS.md requires an actual passed zero-retry receipt for each repaired
journey. Batch 4 lists every local-only journey in the ledger.

Gap: no lint flags assertions inside conditionals in `tests/e2e`.

### 3. A PDF accepted because a file arrived

- The hari BUG-052 and BUG-055 journeys checked only the suggested file name.
- The BUG-033 fix (d57a2547) asserted glyph positions and extracted text. Those
  checks pass when text is drawn dark on dark, and that is the regression Ram
  reported as BUG-016.

Permanent rule: a document is verified by rendering it. Rasterize every page,
measure each text run's contrast against its own background, assert the page
count with no blank trailing page, and check the required fields. File-name,
`%PDF`, checksum and text-extraction checks are not legibility proof.

Guards: the committed dark-on-dark negative control is
`apps/api/tests/test_bug016_invoice_pdf_legibility.py::test_bug016_raster_check_flags_dark_text_on_a_dark_fill`
(`:429`); the contrast measurement it exercises lives in
`apps/api/tests/pdf_legibility.py`. The same test file covers all five PDF
generators, including the stored taxable-value-0 outside-counsel state. The
hari specs now parse PDF content (bd9d8cd1). `invoice-pdf.spec.ts:424` and
`:432` download Ram's two reported invoices by server id in production.

### 4. An empty state or disabled control called a fix

- Registry told Ram to "Open this docket" for a docket that cannot take an
  application anywhere in the UI.
- Foreign associates linked to the Overview view, which has no Link Matter.
- Madrid disabled the cost select but left "Record transaction" enabled, so the
  API rejected every submission.
- The owner's 2026-10-31 PRD rule already says it: an empty, explained control
  is not acceptance when the tester expected a usable selection.

Permanent rule: an explanation is a fix only if the same journey follows it to
a usable selection, for the tester's role. A link to a view where the action
does not exist, an action the role cannot perform, or a disabled field next to
an enabled submit is still the reported dead end.

Guard: `foreign-associates.spec.ts:386` walks every empty picker to a created
and retired instruction. Registry `page.test.tsx` asserts each link's target.
The crawl's dead-select rule fails an enabled select that has no real option.

Gap: the crawl does not go past record selection on per-record forms.

### 5. A picker that offers values its validator rejects

- Portal grants on closed dockets.
- Responsible-person pickers that offered walled members.
- Free-text "UK" compared with "United Kingdom".
- Voided estimates.
- A recordal instrument bound applied before the access check.
- Partners offered Void and Draft PDF, which return 403.
- Ineligible Matters in the Operational role.

Permanent rule: serve options from the write validator's own predicate,
including state that changes after creation (docket closed, client inactive,
ethical wall), and test a record whose state changed after it was offered.

Guards:

- `test_portal_ip_shareable_documents_20261031.py`
- `test_ip_foreign_associate_create_options_20261031.py`
- `test_ip_recordal_instruments_20261031.py`
- `test_ip_madrid_document_refs_20261031.py`
- `test_ip_renewal_transition_references_20261031.py`
- `test_ip_registry_docket_eligibility_20261031.py`
- `test_ip_jurisdictions.py`, with web parity in `lib/ip/jurisdictions.test.ts`
- `test_matter_team_role_fences.py`

Gaps:

- The docket-scoped document list still disagrees with the recordal and Madrid
  validators.
- The rule-needs-calendar check is client-only.
- Portal invitation checks company only (B4-ADJ-01, Not fixed; enterprise gap
  EH-B4-01, Missing).

### 6. Lists that stop at the first page

- BUG-012 itself: the registry docket picker read the first 100 dockets.
- The recordal relationship-cycle check was found only at integration
  (2d053832).
- Notices, drafting, recommendations and portfolio Matter lists.
- The watch workspace at 250.
- `list_linked_ip_documents` capped at 100 and returned `total=len(page)`.
- Madrid designations and calendar-copy reviews.
- The Documents "Linked docket" picker on `/app/ip`, the BUG-002 upload
  surface, still lists the first 100 dockets with no search and no cap
  statement (B4-ADJ-18). `docket-dropdowns.test.ts` allowlists the whole of
  `app/app/ip/page.tsx`, so the guard cannot see it.
- The docket-sweep lane's own regression used 153 rows against a 200-row page.
  A mutation run that read only one page still passed it.

Permanent rule: every list a picker, validator, report or check reads must
either page to the end or state its cap with a server total. Prove it with a
test that crosses at least two page or chunk boundaries, with the interesting
row sorted last. Show that the test fails on a one-page reader.

Guards:

- `test_ip_docket_full_population.py`: chunk 40, 154 dockets, and an update
  mid-read
- `test_ip_detail_lists_complete_20261101.py`
- `apps/web/lib/api/ip-offset-lists.test.ts`: reread when fewer distinct rows
  arrive than the total
- `apps/web/lib/ip/docket-dropdowns.test.ts`: exact allowlist of bare docket
  list reads

Gaps: the docket-dropdown guard allowlists whole files, not individual reads;
the Documents Linked docket picker, Matter lists, watch, and non-IP
`limit=100` defaults remain (EH-B4-02).

### 7. Seeded fixtures that route around the real setup

- Sixteen e2e calls to `/api/ip/document-taxonomy/seed`, an alias import in
  `ram-2026-08-09-prod`, and an ORM-built taxonomy row in `seed_iplf037b.py`.
- `ensure_default_ip_document_taxonomy` provisions only when a tenant has zero
  entries. A seeded fixture therefore guaranteed the Classification dropdown
  was populated in every test, while Ram's real workspace depended on
  provisioning that no test exercised. That is BUG-002(b).

Permanent rule: a fixture must not create the catalogue or tenant
configuration that the journey claims to test. A production spec must not
change shared tester configuration.

Guard: `apps/web/lib/e2e-document-taxonomy-seed-guard.test.ts` scans TS and
Python e2e files for literal, assembled and ORM writes.
`ram-2026-10-31-fixture-honesty.spec.ts` asserts the
`ip_document_taxonomy.defaults_provisioned` audit event locally.

Gaps:

- A seed path assembled in a file that never names the taxonomy prefix.
- API-level pytest fixtures still call `/seed`.
- No equivalent guard exists for other catalogues.

### 8. Flag-gated features that cannot be reached in production

- IP rule governance defaults to off, and the A0 fence returns 503.
- Earlier governance acceptance ran locally with the flag on, so the pickers
  Ram saw empty (BUG-003/004) were "proven".
- Watch readiness claimed "Automated polling is available" although no journal
  provider exists.
- IP entitlements come only from a manual override, while the billing page
  pointed to a plan.

Permanent rule: before claiming a fix for a gated feature, record the gate's
production value at the serving SHA. Until production runs with that value, the
verdict is `Inconclusive`. Never present a state as available when no
production configuration can reach it.

Guard: `deploy/ip-rule-governance-state.json` is checked-in state.
`scripts/ip-rule-governance-a2.sh` and
`apps/api/tests/test_ip_rule_governance_a2_script.py` cover it. The ip-a0
production step asserts the 503 only while that state is disabled.

Gap: other entitlement and rollout gates have no equivalent checked-in state.

### 9. Lanes merged with conflicting copies of one fix

- The 422 double prefix was fixed at integration (e5262ef0) and again inside
  lanes.
- The `record_type=trademark` docket filter landed in both the registry and
  madrid-portal lanes.
- `MatterSelect` and the new `MatterPicker` overlap.
- A merge produced a duplicate TypeScript field.
- The docket-dropdown allowlist had to be pruned by hand.
- Three Nice-class parsers existed before `parseNiceClasses`.

Permanent rule: one behaviour has one owner. Before a lane starts, the
integrator names the owning lane for each shared primitive. After merging,
regenerate contracts and run the full typecheck and exact-equality guards on
the merged tree.

Guards: `test_problem_details.py`, the web typecheck, regenerated
`openapi-types.ts`, and `docket-dropdowns.test.ts` (exact equality, so a stale
pending entry fails).

Gap: nothing detects a second component for the same picker, so the
`MatterSelect`/`MatterPicker` consolidation is still open.

### 10. Lanes counted as done on the implementer's word

The twelve first reviews above found 1 to 9 serious findings per lane.
Implementers also wrote their own ledger text, and every suggested line except
the docket-sweep lane's (which proposed `Partially fixed`) said "Properly
fixed". The reviewers rated seven of those rows `Partially fixed` (BUG-001,
BUG-002, BUG-003, BUG-006, BUG-007, BUG-010, BUG-016).

Permanent rule: a lane is done only when an independent adversarial review of
its diff and specs, run from the tester's workflow, reports no blocking or
major finding. Its verdict is recorded with the corrected status.

Guard: process only.

Gap: no automated control enforces it.

## Where this batch's own process still falls short

- Production verification has not run. Nothing here is a production fix.
- No merged-tree typecheck, vitest, backend suite or batch-4 Playwright result
  is recorded on the integration HEAD after the 2026-11-01 lane merges and the
  integration fixes 2d053832 and d1a02940. Mechanism 9's guard has not yet run
  for this merge.
- The batch-4 production ip-create and recordals journeys upload an IP
  document that the product cannot retire, which breaks this batch's own
  fixture rule. Before release the owner must record a residue exception, or
  the upload half moves to `[local-only]` (B4-ADJ-07).
- These production records and residues need retirement or correction:
  - triage docket 7ece82b7
  - registry link 83b46b3c
  - probe calendar 189148f7 and its version
  - test-legal's billing profile policy
  - one document per ip-create or recordals run, because there is no retire
    path
- Local Playwright runs needed raised webServer boot windows under workstation
  load (API cold import 146-192 s). That is an environment fault, not product
  evidence, and the timeout must not be raised in the canonical config.
- The adjacent defects B4-ADJ-01..24 are recorded, not fixed. The portal
  invitation wall bypass is a security gap that predates this batch.
