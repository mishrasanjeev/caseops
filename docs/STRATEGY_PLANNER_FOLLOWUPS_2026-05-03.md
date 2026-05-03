# Strategy Planner — post-rollout follow-ups (2026-05-03)

PR #7 (Litigation Strategy & Escalation Planner) shipped to prod
and validated via the 6/7 prod smoke probe. The merged feature is
not blocked. These items are tracked separately so they get worked
without conflating with the rollout.

## 1. HTTPS → HTTP redirect on trailing-slash mismatch (P2)

**Symptom:** `GET https://api.caseops.ai/api/matters?limit=20` → 307 →
`http://api.caseops.ai/api/matters/?limit=20` (note scheme downgrade).
Strict clients fail with ECONNRESET because Cloud Run only serves HTTPS.
Browsers follow the redirect over HTTPS by browser quirk, so end-users
don't see this; Playwright + curl + native HTTP libs do.

**Root cause:** FastAPI's `redirect_slashes=True` (default) builds the
`Location` header from the request's perceived scheme. Behind Cloud Run's
HTTPS terminator the inner request is HTTP and `X-Forwarded-Proto: https`
is set but FastAPI's `RedirectResponse` doesn't consult it.

**Fix options (pick one):**

- **(a)** Add a `ProxyHeadersMiddleware` (uvicorn ships one) so
  `request.url.scheme` reflects `X-Forwarded-Proto` before
  `redirect_slashes` builds the `Location` header. Single-line wire-up
  in `apps/api/src/caseops_api/main.py`.
- **(b)** `app.router.redirect_slashes = False` and require clients to
  send the canonical trailing-slash form. Simpler but breaks anything
  that hits a non-canonical URL.

**Owner:** TBD. Recommend (a). Quick win.

---

## 2. Empty `recommended_drafts` on sparse-retrieval matters

**Symptom:** Prod probe on matter `310b7c38-... (State v. Rahul Verma —
Bail application under BNSS s.483)` got HTTP 200 strategy with
`forum_sequence` populated but `recommended_drafts: []`. UX consequence:
Strategy tab renders without any "Generate draft" buttons.

**Possible causes (need investigation):**

1. The citation verifier is dropping every recommended-draft entry the
   LLM emits because none of them tie to a verified authority in the
   retrieval window (the matter has limited Layer-2 metadata until the
   corpus backfill catches up).
2. The template-recommender's matrix isn't returning anything for
   single-step HC-bail matters.
3. The strategy service post-filter (Round-3 / Round-4 fixes) is
   correctly dropping uncited drafts but the result is unhelpful UX —
   the tab should at least say "no grounded drafts available; pick a
   template manually" rather than render an empty list.

**Diagnostics to run:**

- `model_runs` row for the prod call showing the raw LLM
  `recommended_drafts` array before the post-filter.
- `template_recommender.recommend(matter)` output for this matter.
- Frontend rendering: confirm the empty-drafts state has a clear copy,
  not just an empty list.

**Owner:** TBD. Not a guardrail bug — but a UX gap.

---

## 3. Code-level reasoning-token budget handling in `services/llm.py`

**Symptom:** gpt-5-mini (and any OpenAI reasoning model) bills hidden
reasoning tokens against `max_completion_tokens`. With the default
`llm_max_output_tokens_recommendations=4096` the model can spend the
entire budget on chain-of-thought reasoning before emitting any visible
JSON. The OpenAI API returns `status=ok` with `completion_tokens=3702`
and an empty content string. The downstream parser sees `raw[:500]=''`
and raises `LLMResponseFormatError`.

**Workaround applied (2026-05-03):** Cloud Run env override
`CASEOPS_LLM_MAX_OUTPUT_TOKENS_RECOMMENDATIONS=16384` on revision
`caseops-api-00119-4t6`. Strategy generation succeeds at 16K.

**Proper fix (separate PR):** in `apps/api/src/caseops_api/services/llm.py`
the OpenAI provider should split the reasoning budget from the visible-
content budget — pass `max_completion_tokens` AND `reasoning.effort`
(or `reasoning.max_tokens` once the SDK exposes it) so the visible
content isn't starved when reasoning expands.

**Test:** add a regression case in `tests/test_corpus_structured_layer2.py`
or wherever the OpenAI provider is unit-tested that asserts the call
sets a `reasoning.effort` value when the configured model is in
`{gpt-5, gpt-5-mini, gpt-5-nano, o1, o3, o3-mini}`.

**Owner:** TBD. P1 for any future purpose flipped to a reasoning model.

---

## Memory entry

Captured at
`~/.claude/projects/C--Users-mishr-caseops/memory/feedback_reasoning_model_max_tokens.md`
so future agents touching the LLM provider stack are aware.
