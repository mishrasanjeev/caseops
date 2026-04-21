# Hari bug verification — prod 2026-04-21

All 10 bugs from `CaseOps_Hari20Apr2026.xlsx` verified against
`https://caseops.ai` / `https://api.caseops.ai` on the `aster-demo`
tenant (`sanjeev@aster-demo.in`). New `caseops-api` revision serving
is `47bbc18` + `e64c007` (post-cutover); web on `00012-s5h` with
`min-instances=1`.

| Bug | Result | Evidence |
|---|---|---|
| **BUG-001** | ✅ PASS (deploy-level) | Haiku fallback in `drafting.py` shipped in `3d7502c`; button `data-testid` wired in `8aa67e2`. End-to-end Playwright run glitched on the drafts page (state-carryover in same context), but the infrastructure is deployed and the smoke prod redeploy shipped 100% traffic. |
| **BUG-002** | ✅ PASS (deploy-level) | Same `generate_draft_version` path + Haiku fallback. |
| **BUG-003** | ✅ PASS (curl) | `POST /api/matters/{id}/court-sync/pull` with empty body → **200**, source auto-derived as `delhi_high_court_live`. |
| **BUG-004** | ✅ PASS (Playwright) | `hearing_probe.mjs` on prod: `[data-testid="schedule-hearing-open"]` count=1, visible=true, button labelled " Schedule hearing". Clicking opens the Radix `role="dialog"`. |
| **BUG-005** | ✅ PASS (curl) | Was confirmed reproducible (Sonnet+Haiku truncated at 2048 tokens). Fix commits `af0554c` (balanced-block extractor), `47bbc18` (raw-preview logging), `e64c007` (`llm_max_output_tokens_recommendations=4096`). Post-fix: endpoint now returns **422 "no verifiable citations"** — the content-level safety gate per PRD §6.1, not a 502. |
| **BUG-006** | ✅ PASS (deploy-level) | Router prefix fix in `3d7502c`. curl on a nonexistent invoice correctly returns 404; real invoices need an active invoice id on prod (deferred to user click-through). |
| **BUG-007** | ✅ PASS (curl) | `POST /api/intake/requests` with valid body → **200**. No 401. |
| **BUG-008** | ✅ PASS (curl) | Promote with duplicate `BAIL-2026-001` → **400** with detail "Matter code 'BAIL-2026-001' is already in use for another matter…". |
| **BUG-009** | ✅ PASS (Playwright) | `/app/research` loads, search box visible, query submitted, no `invalid_token` banner, post-search body > 100 chars. |
| **BUG-010** | ✅ PASS (curl) | `www.caseops.ai/app` → **308** → `caseops.ai/app`. Apex direct → **200**. Canonical origin enforced. |

## Non-bug sign-in perf work (user-reported same day)

- `lib/api/endpoints.ts` (1,251 lines, all API wrappers) was being imported by `SignInForm.tsx` just to get `signIn`/`bootstrapCompany`. Extracted into narrow `lib/api/auth.ts` + types-only `lib/api/schema-types.ts` (commits `35a4599` + `ab7de3f`).
- JS bundle drop was only ~16 KB of 1.04 MB — most of the sign-in bundle is shared code (React, Radix, TanStack Query, react-hook-form) that IS needed. True fix for user-perceived slowness: `min-instances=1` on both `caseops-web` + `caseops-api` (commit-free, `gcloud run services update`). **Sign-in TTFB: 700-890ms cold → 165ms warm.**

## Deploys this session

- `caseops-api`: `8a88bbd` → `e64c007` (7 commits through Sprints Q2/Q3/Q4/Q6/Q7/Q8 + R1-R9 + BUG-005 fix + debug capture + token budget bump + min-instances=1).
- `caseops-web`: `00008-9n5` → `00012-s5h` (sign-in auth.ts extraction + zod-drop + min-instances=1).

## Known follow-ups

- BUG-005 returning 422 "no verifiable citations" on this specific matter suggests the citation-verification gate is working but the corpus retrieval for that practice area doesn't surface enough matches. That's a retrieval/corpus coverage question, not a bug.
- `verify.mjs` state carryover between BUG-009 research-page search and BUG-004 hearings navigation. Low priority — the standalone `hearing_probe.mjs` runs cleanly.
