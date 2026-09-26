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
   decision, and a strictness change landed in one of them.
5. **Reproductions that silently tested the fix.** On 2026-09-26, the first
   attempt to rerun the new tests against the old commit passed. pytest's
   `pythonpath = ["src"]` had imported the candidate's source. A real
   reproduction runs inside a checkout of the old commit. There, the six
   identity tests and both cause-list layout tests failed for the reported
   reasons: a missing link token for the CNR-identical case, glyphs crossing
   column borders, and `UnicodeEncodeError`.

Permanent rules added to `AGENTS.md` on 2026-09-26 cover each of these.

## Verification

To be completed with exact commits, runs and results. A row stays open until the
dated spec passes against the deployed release in the production tester suite.
