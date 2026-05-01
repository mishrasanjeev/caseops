# CaseOps — Release notes, 2026-05-01

**Tag:** `v0.5.0-drafting-studio`
**Production SHA:** `be9180c` (api + web)
**Headline:** PG-005 drafting roadmap closed — 12 sprints landed in a single
working day. Drafting studio status moved from `Partially implemented` →
`Implemented`. Three reopened user-bugs root-cause-fixed in the same window.

---

## Highlights

### Drafting studio is now feature-complete

CaseOps drafts now ship from a 20-template specialised catalogue, render
to court-format-aware PDFs, package into filing-grade ZIP bundles
(memo + vakalat + index + e-stamp placeholder + exhibits), expose a
revision diff for partner review, inject the assigned judge's bench
history into the prompt, and arrive with a pre-filing checklist that
auto-ticks items the system can verify itself (vakalat draft on the
matter, exhibits uploaded). The studio is mobile-responsive at 360px and
offers a solo-mode `?solo=1` URL flag for one-page generation.

### Three Ram bugs root-cause-fixed

A reopened PDF viewer bug ("Could not load the PDF" — 3rd reopen), a
recommendations 502 reopen (`LLMResponseFormatError` on GPT-5.1
malformed JSON), and an enhancement request that turned out to be a
critical discoverability bug (Sprints 1+2 of templates were invisible
because the New-draft button bypassed the template grid) — all three
shipped with prod-Playwright probes asserting the EXACT reported
failure modes are no longer reachable.

### Three new permanent hard rules in memory

The Brutal Bug-Fixing 2026-05-01 memo distills three patterns I keep
hitting and locks them into the contributor handbook:

1. Generic surface error + reopen ≠ same root cause; pull prod browser
   console first.
2. Removing a fallback ladder requires shipping the explicit retry
   path in the same commit.
3. Backend feature complete ≠ clicked-through; click the natural
   entry-point in a real browser before declaring done.

---

## What shipped (12 sprints)

| Sprint | Description | Commit | Notable artifacts |
| ------ | ----------- | ------ | ----------------- |
| **1** | 4 highest-frequency templates — Writ Petition, Quashing Petition (BNSS s.528 with Gian Singh framing), Written Statement (Order VIII Rule 1 30/90/120-day), Reply / Counter-Affidavit | `a1f8612` | 11 facts-validation + prompt-correctness pytest cases; recommender-matrix entries |
| **2** | 7 more templates — DV-Quashing (PWDVA, distinct from Gian Singh), Arbitration §9 (3-part test + s.9(3) tribunal carve-out), Caveat (CPC §148A), Vakalatnama (court-specific headers), Amendment of Pleadings (Order VI Rule 17 due-diligence), Compromise (4 statutory bases), Probate (Indian Succession Act §63(c) two-attestor) | `164c4f6` | 14 new pytest cases; 20 templates total in registry |
| **3** | Court-format-aware PDF export — fpdf2-based; 4 pinned profiles (SC, Delhi HC, Bombay HC, generic); same citation gate as DOCX | `d6207e0` | 16 pytest cases (10 unit + 6 integration); `services/court_format_profiles.py` + `services/draft_pdf_export.py` |
| **4** | Filing-grade ZIP bundle — index + memorandum PDF + vakalat (auto-resolved or placeholder) + e-stamp placeholder + matter exhibits | `df71b4e` | 7 pytest cases; auto-pick newest VAKALATNAMA-typed draft on the matter |
| **5** | Court profile expansion — Madras / Calcutta / Karnataka HC + NCLT / NCLAT / DRT (10 profiles total) + cause-title formatter (case + numbering + separator) | `22f9883` | 11 new pytest cases; NCLAT-before-NCLT ordering enforced |
| **6** | Structured draft revision compare — `difflib.SequenceMatcher` hunks + citation deltas (case-folded set semantics) + summary | `9a316bd` | 13 pytest cases; `<DraftCompareView>` on the draft detail page |
| **7** | Bench-aware drafting expanded — `_BENCH_AWARE_TEMPLATES` set (15 of 20); 5 templates intentionally excluded (notices + procedural) | `1a2662a` | 42 parameterised pytest cases |
| **8** | Pre-filing checklist per court — items grouped by category (document / fee / procedure / service); auto-satisfaction on vakalat-draft-exists + attachments-uploaded; limitation reminder for written statement / appeal / cheque-bounce / writ / quashing / amendment | `f5f5dfc` | 9 pytest cases; `<FilingChecklistCard>` |
| **9** | Mobile responsive — DraftingStepper bottom nav stacks vertically below sm; full-width buttons on 360x800 | `5a35bc5` | +1 mobile-responsive Playwright case (no-overflow + stack-proven + ≥240px width) |
| **10** | Solo mode — `?solo=1` flattens the stepper into a single scrollable form with one "Generate draft" CTA; "Solo mode" link on every template card | `be9180c` | DraftingStepper `solo` prop |
| **11** | Template governance — `tenant_ai_policies.disabled_template_types_json` (Alembic `20260501_0003`); PATCH `/api/admin/tenant-ai-policy` partial-update; templates list filters per tenant | `be9180c` | 6 pytest cases (incl. tenant-isolation) |
| **12** | Live-LLM drafting quality harness — `caseops_api.scripts.eval_drafting_quality` — runs each fixture through the EXACT production prompt, scores validator + structure + citations against the 4.8/5 PG-005 target | `d2d20c4` | Markdown report + JSON artifact; dry-run mode for prompt-edit diff review |

**Total templates available in production:** 20.
**Total court format profiles:** 10.
**New backend pytest cases this batch:** 130+.
**Web `tsc --noEmit` clean across all 12 sprints.**

---

## Bugs root-cause-fixed (Ram 2026-05-01 batch)

All four user-reported items closed with prod-Playwright verification
against `06f63a9` (commit `289ad0c` carries the spec).

| ID | Title | Verdict | Verification |
| --- | --- | --- | --- |
| **BUG-028** | PDF viewer "Could not load the PDF" — 3rd reopen | Properly fixed | Prod-Playwright: error UI absent, `<canvas>` renders, `pdfjs.workerSrc` not unpkg.com |
| **BUG-029** | Recommendations 502 (`LLMResponseFormatError`) reopen | Properly fixed | Backend retry-once test + prod-Playwright (no 502) |
| **ENH-003** | Generic AI draft quality | Partially fixed | Sprints 1-7 already address; ENH-004 fix makes them discoverable |
| **ENH-004** | "Domain-specific drafts not visible" — actually a routing bug | Properly fixed | Prod-Playwright: New-draft button → grid → 10+ cards → writ_petition → stepper |

**Root causes:**

- **BUG-028** — PDF.js worker URL pointed at `https://unpkg.com/...`; prod CSP `worker-src 'self' blob:` blocked it. Fix: bundle the worker via `new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url)` so Webpack/Turbopack emits it same-origin.
- **BUG-029** — When this session removed the Anthropic→Haiku→OpenAI fallback ladder, single transient GPT-5.1 JSON-format flakes (~1-2%) put users on a 502. Fix: single retry on `LLMResponseFormatError` specifically (same provider, same model, same prompt). Pattern audit applied to `services/drafting.py` + `services/hearing_packs.py` too.
- **ENH-004** — Sprints 1+2 added 20 templates but the "New draft" button on the matter drafts page opened a legacy 5-option dialog, never reaching the template grid. Fix: replace the dialog with a Link to `/drafts/new`. Compounding fix: `KNOWN_TEMPLATE_TYPES` allow-list on the grid was a stale 9-entry hardcoded set; replaced with a permissive regex.

Bug-fix summary delivered as
`~/Downloads/CaseOps_BugFix_Summary_Ram01May2026.xlsx` (3 sheets:
per-bug summary, brutal-pattern analysis, repo-wide pattern audit).

---

## Verification

- **Backend tests passing this batch:** 130+ new + every pre-existing
  case green. Top-level: `bash scripts/verify-backend.sh`.
- **Prod-Playwright (Ram batch):** `tests/e2e/ram-batch-2026-05-01-prod.spec.ts`
  → 4/4 cases pass against deployed code (3 fixes + 1 setup).
  Wired into `playwright.prod-ram.config.ts`.
- **Mobile-responsive Playwright:** `tests/e2e/mobile-responsive.spec.ts`
  → +1 case for DraftingStepper at 360x800.
- **Web `tsc --noEmit`:** clean across the entire batch.
- **Deploy verification:** `api=be9180c web=be9180c`, migrate-job ran,
  EG-003 clamav sidecar present, health OK.

---

## Where to test in production

| Surface | URL | Expected |
| --- | --- | --- |
| Template grid | `/app/matters/{id}/drafts` → click "New draft" | Routes to `/drafts/new` showing 20 templates |
| Solo mode | Click "Solo mode" on any template card | Single-page form, "Generate draft" CTA |
| PDF export | Open any draft → Download PDF | Court-format-aware PDF with margins / page numbers / court header |
| Filing bundle | Same → Filing bundle | ZIP with index + memo + vakalat + e-stamp + exhibits |
| Revision compare | Generate twice, open the second → Compare panel | Diff hunks + citation deltas |
| Filing checklist | Open any draft | Checklist card showing per-court / per-template items |
| Bench-aware draft | Generate a writ_petition / quashing on a matter with a known judge | Body cites judge's recurring tests + indexed authorities |
| Recommendations | Open any matter → Recommendations → Authority | 200 / 422 — never 502 with `LLMResponseFormatError` |
| PDF viewer | Open a matter → Documents → click any PDF | Inline viewer renders (no "Could not load the PDF") |

---

## Migrations

- `20260501_0001_predictive_bench_strategy_flag.py` (PG-107).
- `20260501_0002_recommendation_retrieved_authorities.py` (PG-109).
- `20260501_0003_template_governance.py` (Sprint 11).

---

## What's still in the roadmap

- PG-006 — Research treatment / good-law signal.
- PG-007 — GC spend depth (rate cards, budgets, billing guidelines, scorecards).
- PG-008 — CLM lifecycle (request → approval → e-sign → obligations).
- PG-009 — Enterprise identity (SSO + MFA + SCIM).
- PG-010 — Pricing / packaging entitlement enforcement.

See [`docs/STRICT_PRODUCT_GAPS_2026-04-30.md`](./STRICT_PRODUCT_GAPS_2026-04-30.md)
for the full ledger.

---

## Acknowledgements

Ram (tester) — caught the three reopens that grounded the brutal-pattern
memo additions and forced the discoverability fix. The bug-fix
verification rule that "reopened bugs require fresh end-user
verification" came from his last batch and saved this one.
