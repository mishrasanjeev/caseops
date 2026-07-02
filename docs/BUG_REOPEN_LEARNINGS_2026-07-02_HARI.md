# Bug Reopen Learnings - Hari 2026-07-02

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari02Jul2026.xlsx`.

## Reported Items

- `BUG-001` - High - Research / Context Search - contextual search returns corrupted or unreadable judgment content for the query `Cheque bounced due to insufficient funds and notice was sent after 35 days`.
- `BUG-00X` - High - Matter Management / Matter Details - Matter cockpit has no Notice section for viewing and managing notices.

## Validity

- `BUG-001`: Valid. The product rendered an authority card whose title, summary, and snippet could contain screenshot-shaped OCR corruption. A relevance score on unreadable text is not a useful legal result.
- `BUG-00X`: Valid enhancement/bug. The data model and upload API already supported `document_type: "notice"`, but the matter cockpit had no first-class Notices tab, so users had to infer notice handling from the generic Documents page.

## Brutal Root Cause

1. The June OCR fixes were still shallow. They penalized or hid some damaged OCR, but preserved a "garbled as last resort" path. That is wrong for legal research: unreadable authority text must not be displayed as a result card.
2. I let a clean query-matching snippet hide a corrupted summary/title. The first patch checked the snippet and a combined preview, which diluted corruption when the snippet was clean. The fixed rule checks title, summary, snippet, and combined preview independently.
3. The regression data was not close enough to Hari's screenshot. Prior tests covered `$O ?J` style mojibake but not the exact `[2003] 3 -- f.t 'II'. 178` / mixed ASCII OCR fragments that reopened the bug.
4. The Playwright proof had to seed the authority corpus directly and use the real Research page/API flow. Mock-only UI tests would not catch ranking, preview construction, or backend filtering failures.
5. The Notice gap existed because the capability was buried as document metadata. A product section promised by matter management must be visible in the matter cockpit navigation, not only available through a generic upload classifier.

## Permanent Rules

- Corrupted legal authority previews are never acceptable "last resort" results. If the only matching records are unreadable, omit them and show an explicit omitted-record notice.
- OCR quality gates must evaluate every rendered field independently: title, summary, snippet, and any combined preview.
- Reopened OCR bugs must add the exact reported text shape to backend, frontend, and browser regressions.
- Research regressions must seed the corpus and test the real `/app/research` route against the real API, not only mocked components.
- Matter cockpit module requests must be audited against both the navigation surface and the backing data model. If a document type exists as metadata but users cannot reach it as a workflow, the feature is incomplete.

## Regression Anchors Added

- `apps/api/src/caseops_api/services/retrieval.py` detects screenshot-shaped ASCII OCR fragments and low-quality legal previews.
- `apps/api/src/caseops_api/services/authorities.py` suppresses unreadable authority cards across authority consumers and returns an explicit contextual coverage notice when matches were omitted for unreadable extraction.
- `apps/api/tests/test_authorities.py` seeds the screenshot-shaped cheque dishonour authority and proves the API omits it when no readable preview exists.
- `apps/web/app/app/research/page.tsx` filters unreadable authority cards client-side as a defense-in-depth guard.
- `apps/web/app/app/research/page.test.tsx` and `apps/web/app/app/research/isGarbledSnippet.test.ts` cover the exact July 2 OCR shape.
- `apps/web/components/app/MatterCockpitNav.tsx` adds the Notices tab.
- `apps/web/app/app/matters/[id]/notices/page.tsx` adds the Notices workflow, notice-only listing, and notice-classified upload.
- `apps/web/app/app/matters/[id]/notices/page.test.tsx` verifies notice-only rendering and upload metadata.
- `tests/e2e/hari-2026-07-02-bugs.spec.ts` drives both reported workflows in the browser with local user/data setup.
- `playwright.app.config.ts` registers the July 2 Playwright regression in the normal app suite.

## Product-Wide Sweep

- Authority search catalog consumers now get readable-only results by default, with filtering applied before the final limit slice so readable candidates below unreadable rows can backfill the result set. The Research API intentionally fetches raw candidates first so it can report how many were omitted for unreadable extraction.
- The Research UI keeps a defense-in-depth readable-only filter so stale or external API responses cannot render a corrupted card.
- Matter attachment upload already accepts `document_type: "notice"`; the new Notices page uses that existing contract instead of creating a separate notice store.
- The generic Documents tab remains the metadata management surface; Notices is the matter workflow surface for notice-classified attachments.

## Current Verdict

`BUG-001` and `BUG-00X` are locally fixed with API, web unit, build, and Playwright browser regressions. Formal production verdict remains `Inconclusive` until the commit is merged, deployed, and production Playwright passes on the shipped build.

## Local Verification - 2026-07-02

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/retrieval.py apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_omits_corrupted_authority_when_no_readable_preview_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/research/isGarbledSnippet.test.ts "app/app/matters/[id]/notices/page.test.tsx"` - PASS, 13 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-07-02-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- Note: the normal `playwright.app.config.ts` run also passed both browser tests, but the command hit a Windows web-server teardown timeout after success. The no-webserver replay above is the clean exit-code evidence.
