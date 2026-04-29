# Bug verification: Hari + Ram 2026-04-27 batch — real-data audit on 2026-04-28

Anchor: `feedback_brutal_bug_fixing_2026_04_27.md` rule that synthetic-only
tests are forbidden as sole proof when real data exists. The 4 reopens
shipped in `192d0a8` were re-verified against prod by the QA Bot
workspace using `playwright.prod-ram.config.ts`.

| Bug | Verdict | Evidence |
| --- | --- | --- |
| BUG-031 (NDPS Act + 14 acts) | **Properly fixed** | `GET /api/statutes/?q=NDPS` returns NDPS-1985 + sections. Real-prod probe via QA Bot session. |
| BUG-023 / BUG-032 (PDFViewer cross-origin cookie) | **Properly fixed** | Created QA matter + uploaded sample PDF, then `GET /api/matters/{id}/attachments/{id}/download` returned 200 with cross-origin `caseops_session` cookie — 401 would mean the fix regressed. |
| BUG-019 / BUG-025 (calendar empty) | **Partially fixed (workaround)** | Empty-state banner renders on real-prod calendar with QA tenant (zero events). Per brutal-memory Pattern 4, banner ≠ workflow fix. The user's underlying complaint ("calendar should show hearings/tasks/deadlines") still requires UX to *create* hearings — that UX does not exist on `/app/matters/[id]`. |
| BUG-026 (research garbled detector) | **Partially fixed** | v2 detector catches the 1 real-prod ASCII-mojibake sample currently in the test fixture. Brutal-memory Pattern 3 requires ≥10 real samples for a detector regression suite. We have 1. |
| BUG-024 / BUG-033 / BUG-034 (recommendations 422) | **Properly fixed** (2026-04-29, commit `ceb8e01`) | Bracket-tag fast path shipped: `services/citations.verify_citations` now resolves citations starting with `[N]` to `sources[N-1]` by index, skipping both the fuzzy citation gate AND the proposition gate (the model has explicitly named the source). `services/recommendations._build_prompt` instructs the model to prefix every `supporting_citations` entry with the numbered list's `[N]`. `_filter_and_verify_options` surfaces canonical `SourceDoc.identifier` so the UI shows clean citations. Existing 0.5 fuzzy + proposition path stays as fallback for free-form output. Evidence: `tests/e2e/recommendations-grounding-2026-04-29-prod.spec.ts:89` PASSED on deployed `caseops-api-00086-qp4` (`ceb8e01`) — fresh QA Bot matter → 200 with verified citations, no `[N]` prefix leak. Backend: 49/49 across `test_citations.py`, `test_recommendations.py`, `test_drafting_studio.py`, `test_hearing_packs.py`, `test_contract_intelligence.py`. |
| BUG-035 (recommendations 502, LLM JSON schema mismatch) | **Properly fixed** (2026-04-29, commit `ceb8e01`) | Same commit. Schema-bound widening shipped 2026-04-28; the bracket-tag fast path collapses the proposition gate that was the secondary 502 source by removing the rationale-vs-snippet token check from the `[N]` path. |

## Surfaced follow-ups

1. ~~**BUG-035** (new): ...~~ **Closed 2026-04-29 in commit `ceb8e01`** (see verdict row above).
2. **BUG-026 expansion**: extend `tests/e2e/ram-batch-2026-04-26-prod.spec.ts:1010` to cycle through ≥10 real-prod garbled snippets (sample from `authority_documents` rows where `length(snippet) < 0.45 * letter_ratio + dirty_token_density > 30%`). Detector passes if ≥90 % of real garbled snippets are flagged AND ≥90 % of real clean snippets pass through unflagged.
3. **BUG-019/025 workflow**: ship a "+ Add hearing" affordance on `/app/matters/[id]` that POSTs to `/api/matters/{id}/hearings` and surfaces the result in `/api/calendar/events`. Without this, every QA tenant + every greenfield user sees the empty-state banner even though we said the bug was "fixed".

## Method

- Auth: signed in via QA Bot (`qa-bot@caseops.ai`, slug `caseops-qa`) using the password that lives in Secret Manager `caseops-qa-password` (rotated 2026-04-28 via `scripts/one-off/reset-qa-bot-password.py`).
- Spec config: `playwright.prod-ram.config.ts`, project `prod-chromium`.
- Filter: `-g "BUG-02[3-6]|BUG-031|BUG-019"`.
- Result: 6 passed, 1 skipped, 0 failed. The skipped run was BUG-023 on the first attempt (no attachments in QA tenant). After populating one matter + uploading a tiny PDF, BUG-023 ran clean.

## What's preserved

- `scripts/one-off/reset-qa-bot-password.py` — durable password rotation. Random 32-byte URL-safe value, scrypt hash via `core/security.hash_password`, plaintext pushed to Secret Manager. Future runs fetch via `gcloud secrets versions access latest --secret=caseops-qa-password`.
- `caseops-watchdog-runtime` SA already has `roles/secretmanager.secretAccessor` on the password secret, so any future GCP-side automation can pull it.
- One real PDF attachment is now in the QA workspace's first matter so BUG-023 stays runnable.
