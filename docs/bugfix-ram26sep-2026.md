# Ram workbook (IV), 2026-09-26: bug report and root-cause review

Source: `CaseOps_ai_Bugs(lV).xlsx` ("Bug Sheet"). Workbook IDs are local to the
file; this report namespaces them as `RAM-20260926-BUG-032..034`. Credentials in
the workbook are intentionally not reproduced here.

## Workbook reconciliation

- Three populated issue rows (BUG-032, BUG-033, BUG-034) and one header row.
- Three embedded screenshots, anchored to the header row (1) and to BUG-033's row
  (2). By content they show BUG-032 (Case Tracking), BUG-033 (the PDF) and BUG-034
  (the Tasks tab).
- BUG-034's "Steps to Reproduce" repeats BUG-032's Case Tracking steps. Its
  summary, page URL and screenshot identify the Matter Tasks & Deadlines tab; this
  report follows those.

## Verdicts

| ID | Classification | Verdict | Proof |
| --- | --- | --- | --- |
| BUG-032 | Valid bug (product-level policy contradiction) | See "Verification" | `test_20260926_case_match_policy.py`, `ram-2026-09-26-bugs.spec.ts` BUG-032 |
| BUG-033 | Valid bug (layout and latent crash) | See "Verification" | `test_20260926_pdf_table_layout.py`, `ram-2026-09-26-bugs.spec.ts` BUG-033 |
| BUG-034 | Valid bug, **reopened** regression of the 2026-09-24 change | See "Verification" | `ram-2026-09-26-bugs.spec.ts` BUG-034 and layout sweep |

## BUG-032: "Does not match this Matter" for the Matter's own case

**Symptom.** In Matter scope, a CNR search returned the Matter's own case
(`DLHC010317282019`) and labelled it "Does not match this Matter".

**Root cause.** Two different identity policies existed for one decision:

- Manual search, resolve and link used a private matcher. After CNR equality it
  still rejected a result when the free-text court name or any party name
  differed in wording. Examples: "Delhi High Court" vs "High Court of Delhi",
  and "Punjab National Bank" vs "Punjab National Bank & ORS."
- Refresh, scheduled polling and next-hearing sync used `identity_matches`, where
  the CNR decides.

The same Matter could therefore be auto-linked and refreshed on its CNR, while
the user's own search called that case unrelated. The UI also had no "already
linked" or "existing Matter" state.

**Why the tests missed it.** Every fixture used identical court and party strings
on both sides. The browser spec mocked the search response, so the server
matcher never saw real-world wording. One backend test explicitly asserted the
divergent rule: same CNR plus a different court label must give `no_match`.

**Fix.**

- Search, resolve and link call `identity_matches`.
- The search compares the provider snapshot's full published matching identity,
  including case type and court code, and the signed selection carries that
  identity for the link-time recheck.
- Without a CNR, the exact case number, its provider case type and the court are
  required (fail closed). A bare `number/year` or another case type never links.
- Results list visible Matters that record the same CNR, and say whether the
  scoped Matter already tracks the case. The page shows "Linked to this Matter"
  and an "Open matter" link.
- Review finding (P1), fixed: manual search, resolve and link require a CNR or a
  case number that carries its case type. A bare `6209/2019` returns an
  actionable 409 (`CASE_TYPE_REQUIRED`) or `insufficient_identifiers`, because
  registries reuse numbers across case types (WP(C) 6209/2019 and CRL.A.
  6209/2019 share a court). This first version kept the weaker check for
  automatic linking and the refresh of automatic links; review on 2026-09-27
  found that exception and it is removed (see "Production run 1").
- Docker acceptance finding, fixed: a search result without the optional
  `existing_matters` context (older responses, dated browser mocks) crashed the
  page into the workspace error boundary. The row treats a missing list as
  empty, the client type matches the generated contract, and a page test
  renders the older payload shape.
- Docker acceptance finding, fixed: the 2026-09-24 local court-link journey
  mints a selection through the private token helper with only the displayed
  result; the new candidate argument defaults to that result's identity.
- Review finding (P2), fixed: the SQL key that finds existing Matters by CNR
  drops every non-alphanumeric character (`regexp_replace` on PostgreSQL),
  matching `normalize_cnr`; a stored `DLHC_0103-1728.2019` is found.

**Contract change, recorded.** A result with the Matter's CNR but a different
free-text court label is now a match. A different CNR is still never a match.

**Residual (not claimed).** Without a CNR, case-type aliases are not yet
reconciled; for example, a Matter typed "WP(CIVIL)" vs the provider code "WP_C".
Refresh behaves the same way; such rows fail closed.

## BUG-033: cause list PDF columns overlap

**Symptom.** Downloaded cause list text ran into neighbouring columns.

**Root cause.**

- Fixed-width single-line `cell()` calls on portrait A4.
- The widths summed to 199 mm against 190 mm of printable width.
- fpdf2 neither clips nor wraps a `cell()`, so long text ran into the next
  columns; values were also cut at 32 characters and rows had a fixed height.
- The PDF also lacked the preview's Date column.
- A non-Latin title (for example "Rāmesh") raised `UnicodeEncodeError`, so the
  download failed with a server error.

**Why the tests missed it.** Every PDF test asserted `%PDF`, the content type and
the checksum length. No test in the product read a generated PDF's text or
layout.

**Fix.**

- New `services/pdf_layout.py`:
  - `write_wrapped_table` sizes columns from weights to the exact printable
    width, wraps every cell, grows rows and repeats headings;
  - `write_wrapped_pairs` handles side-by-side label/value text;
  - `safe_pdf_class` normalizes every string through fpdf2's `normalize_text`
    hook.
- The cause list renders on landscape A4 with a Date column, the shared table
  and "Page N of M".

**Adjacent defects found by the audit and fixed.**

- **Matter invoice, line items:** four unwrapped single-line line-item columns.
- **Matter invoice, header:** a `multi_cell` that left the cursor at the right
  margin, so the "Matter:" line was drawn off the page on every invoice that had
  a client billing address. The matter title was also cut at 80 characters.
- **All five PDF generators:** none handled non-Latin text safely. All now build
  from `safe_pdf_class`.
- **Guards:** tests fail if any module constructs a bare `FPDF`, or calls
  `multi_cell` without an explicit `new_x`.
- **Review finding (P2), fixed:** the new footer's `{nb}` alias was not
  registered, so the first version printed `Page 1 of {nb}`. The tests now read
  the footer on a single-page list and on a 90-row multi-page list.

**Residual (not claimed).** Devanagari and other non-Latin scripts render as `?`
in PDFs, because the core fonts are Latin-1; DOCX exports remain lossless.
Native rendering needs a vendored Unicode TrueType font.

## BUG-034: Tasks & Deadlines labels overlap the inputs (reopened)

**Symptom.** At desktop width the Task and Deadline title inputs collapsed, and
the Due date field covered their labels ("TaDue").

**Root cause.**

- The form used a **viewport** breakpoint:
  `lg:grid-cols-[minmax(0,1fr)_10rem_9rem_auto]`.
- At `xl` the page places the Tasks and Deadlines cards side by side. Each card
  is then only about 440 CSS px wide, so the fixed tracks and gaps took about
  420 px, and `minmax(0,1fr)` allowed the title column to shrink to about 20 px.

**Why it reopened.**

- The 2026-09-24 change (`d49cbdd3`) moved this form from `md:` to `lg:` and
  introduced `minmax(0,1fr)`, which explicitly permits the collapse.
- Its only browser proof was the 2026-09-21 spec measuring the Task input at a
  600 px viewport. Neither breakpoint applies at that width.
- The fix was verified at a width where the defect cannot occur, then closed.

**Fix.**

- Both forms are sized by their card with container queries: four columns only
  when the card is at least 42rem, two columns from 28rem, stacked below.
- The title column's minimum is 12rem.

**Product-wide prevention.**

- New `tests/e2e/support/form-layout.ts` reports, on any page:
  - squeezed controls (under 96 px);
  - overlapping sibling fields;
  - clipped field labels;
  - controls outside the viewport.
- The dated spec runs it:
  - on the Tasks page at seven widths from 390 to 1920 px;
  - in a sweep over every page in the product's own navigation plus every
    Matter tab, at 1280, 1440, 1920 and 390 px.
- The sweep inventory comes from the rendered navigation, so new pages are
  included automatically.

**Sweep findings on the 2026-09-26 candidate (58 pages per width).**

- `/app/admin` at 390 px: the portal invite form was 397 px wide. Its
  `Matter grant` select had no width constraint, and a native select never
  shrinks below its longest option, so one ordinary matter title widened the
  form past the phone. Fixed on the form, and product-wide with a base rule
  `select { max-width: 100% }` so no data-driven option can widen a form past
  its container again. It did not reproduce in a tenant without matters, which
  is exactly why the sweep runs with product data.
- `/app/research`: two 1 px `aria-hidden` native selects that a custom dropdown
  keeps for form submission. Guard refined to skip hidden fallbacks.
- `/app/admin/billing` and `/app/ip/recordals`: native selects auto-sized to
  their options, 1 px under a formula. Guard refined to compare a select with
  its browser-measured intrinsic width instead of an estimate.
- Guard defect found and fixed on the way: awaiting every animation's
  `finished` promise hung on pages with a perpetual spinner; the wait is now
  bounded to finite animations.

## Why fixes keep reopening

The three rows share one failure mode: each earlier proof measured a proxy that
could pass while the user-visible invariant was broken.

1. **Proof at a width where the bug cannot occur (BUG-034).** A layout fix was
   closed after one viewport measurement. The constraint is the container,
   which depends on the page's split layout and the sidebar.
2. **Fixtures that agree with themselves (BUG-032).** Identical strings on both
   sides of an identity comparison can never exercise the comparison. A mocked
   browser response bypassed the server rule entirely.
3. **Assertions on packaging, not content (BUG-033).** `%PDF` and a checksum
   prove a file exists, not that anyone can read it. The same blind spot hid the
   invoice's off-page Matter line.
4. **Duplicated policy (BUG-032).** Two functions made the same identity
   decision, and a strictness change landed in one of them. The first
   unification then repeated the mistake as an exception: manual paths required
   a typed case number while automatic linking and its refresh did not. A
   reproduction on that commit re-pointed a bare `6209/2019` Matter to the
   provider's only `CRL.A. 6209/2019` result and wrote that case's hearing date.
5. **Reproductions that silently tested the fix.** On 2026-09-26, the first
   attempt to rerun the new tests against the old commit passed. pytest's
   `pythonpath = ["src"]` had imported the candidate's source. A real
   reproduction runs inside a checkout of the old commit. There, the six
   identity tests and both cause-list layout tests failed for the reported
   reasons: a missing link token for the CNR-identical case, glyphs crossing
   column borders, and `UnicodeEncodeError`.

Permanent rules added to `AGENTS.md` on 2026-09-26 cover each of these.

## Production run 1 (2026-09-27, release `2febd211`): two tester failures

Production verification run 36276564868 ran the tester project against the
deployed release and failed two tests. Neither was a product regression; both
were defects in how the proof was written, and both are recorded here because
they are exactly the kind of proxy proof this report is about.

1. **`ram-2026-09-26-bugs.spec.ts` BUG-032, production branch.** The branch
   asserted the blocked-provider body as `detail.code`; the API emits RFC 7807
   bodies with `code` at the top level, which every sibling spec reads. The
   branch is production-only and had never executed before release. It now uses
   a shared `expectPaidProviderBlocked` helper, and a pytest sends the identical
   CNR-only request against the real provider host with the automation marker
   to pin that exact shape before any browser run.
2. **`ram-2026-09-24-prod.spec.ts` QA-owned matter journey.** Its fixture case
   number was `WP(C) <six random hex characters>/2026`. The public-number
   parser reads digits, so the fixture parsed only when the hex slice ended in
   a digit: the journey passed on 62.5% of runs (it passed twice before, by
   chance) and drew `6d661b` here. `public_number` was byte-identical between
   the two releases; the failure was latent flakiness, not the unified policy.
   The fixture is now registry-shaped.

The run also exposed a real usability gap: for `WP(C) 6d661b/2026` the page
said "Insufficient case identifiers" although the entry visibly carried a type,
a year and a court. Fixed product-wide:

- `hearing_matching.identity_gap` names the one reason a Matter cannot be
  matched: `invalid_cnr`, `missing_identifiers`, `unreadable_case_number` or
  `case_type_required`. Search, resolve and link all use it; the resolve
  response carries the reason and the recorded values, and the page renders
  reason-specific copy with the recorded case number.
- The parser now reads the common spellings of one case identity
  (`W.P.(C) No. 6209 of 2019`, `CWP-1234-2020`, `WP(C) No.6209/2019`) and
  rejects a compound entry that names two records (`FIR 145/2025 + Crl. M.C.
  412/2026`) instead of matching on the last number with a garbage type.
- A new dated journey creates an unreadable, an untyped and a readable Matter
  and asserts the exact message for each; it runs locally, in Docker and in
  production.

**Review finding (P1) on this follow-up, fixed.** Manual search, resolve and link
required a typed case number, but automatic linking at Matter creation, the
scheduled existing-Matter backfill and the refresh and polling of automatic links
still used the weaker `reliable_identity` check. `_number_matches` accepts any
case type for a bare number, so a provider that publishes exactly one case under
that number and court decided the Matter's case. Reproduced on `452ae52d` in a
separate checkout: the refresh returned 200, re-pointed the tracked case to
`CRL.A. 6209/2019` and wrote its hearing date on a Matter that was
`WP(C) 6209/2019`; the backfill searched the bare number.

- Every path that establishes or keeps a case from a Matter's recorded identity
  now calls `identity_gap`: auto-link at creation (skipped with the reason),
  backfill (skipped), the automatic source refresh and provider dispatch (409
  with the reason, before any spend or transport), and the tracked case's
  readiness (`manual_refresh_disabled_reason` names the gap). Publication already
  requires the dispatch-time scopes unchanged, so the same decision holds when
  results are persisted.
- A CNR still decides; a bare secondary number beside a CNR is corroboration.
  Bookmarks without a Matter keep the coarse check, because an automatic link
  stores a filing number in the tracked case's `case_number`.
- Regressions (all fail on `452ae52d`): auto-link for bare, unreadable, typed,
  filing-only and CNR Matters; a backfill where the provider publishes exactly
  one case of another type (zero searches for the bare number, no date); an
  existing automatic link whose Matter loses its type (409, readiness reason,
  zero provider calls, no date), then restored (the type selects `WP(C)` from
  two published cases). `test_20260927_case_identity_readability_postgres.py`
  repeats them on PostgreSQL, where the scheduled poll gates each tracked case
  inside a savepoint.

**Contract change, recorded.** An existing automatic link whose Matter records
only a bare `number/year` and no CNR stops refreshing, with "Add the case type to
the case number ... or record the CNR" on the bookmark, until the type or CNR is
recorded. Dates already written are retained; nothing is cleared.

## Production run 2 (2026-09-27, release `1c617a31`): two tester failures

Run 36291638337 passed BUG-034, BUG-033 and BUG-032 against the serving release,
and failed two tests, neither of them a reported row.

1. **The new identity-gap journey used fixed case numbers.** Production tenants
   keep every earlier run's Matters, and the duplicate-case rule counts disposed
   Matters, so disposing a fixture does not free its number. The tenant already
   held `6209/2019`, and the journey's own `WP(C) 6d661b/2026` would have collided
   on the next run. This repeats a rule already in `AGENTS.md` (a fresh identity
   per run on persistent tenants). BUG-033's journey drew from only 9,000 values
   and would collide as runs accumulate; the Docker-only BUG-032 journey, which
   must use the emulator's fixed CNR, also reused one case number and failed its
   second pass as the tester-supplied account. All three now use clock-plus-serial
   registry numbers (the CNR still decides the BUG-032 case), and the unreadable
   entry ends in a letter so no reading can find a number/year. Proof: the
   pre-fix journey fails with the production 409 on its second pass in one
   retained local tenant; the fixed journeys pass twice there, and twice more as
   the tester-supplied account in a Docker tenant holding every earlier run.
2. **An Intelligent Review list request queued behind a cold start.** The list
   took 32.4 s; Cloud Run logs show a new instance starting at that moment, with
   the ClamAV sidecar ready only after 8 startup-probe attempts. The API serves
   one request per instance with four warm instances, and the review page's
   concurrent requests plus CORS preflights exceeded that. The endpoint normally
   takes 1.5-4 s because it re-verifies each review's saved-source manifest with
   several queries (N+1), and it took 39 s on 2026-09-25 in the same way. This is
   a separate, pre-existing capacity defect: recorded and handed off, not hidden
   behind a retry or a longer timeout.

## Verification

Evidence to date is recorded in `docs/STRICT_BUG_TASKLIST_2026-04-22.md`
(2026-09-26 section). Production evidence, the deployed release identity and
the final verdicts are added in a follow-up entry once the dated spec passes in
the production tester suite; until then every row is **Inconclusive**.
