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

## 2. Empty `recommended_drafts` on sparse-retrieval matters — **CLOSED by PR #8**

**Symptom:** Prod probe on matter `310b7c38-... (State v. Rahul Verma —
Bail application under BNSS s.483)` got HTTP 200 strategy with
`forum_sequence` populated but `recommended_drafts: []`. UX consequence:
Strategy tab renders without any "Generate draft" buttons.

**Original suspected causes** (kept for archival; the actual root
cause turned out to be #2 below — `_extract_template_slugs` returning
empty / all-unknown):

1. The citation verifier dropping every recommended-draft entry the
   LLM emits because none of them tie to a verified authority in the
   retrieval window.
2. The template-recommender's matrix not surfacing anything for
   single-step HC-bail matters.
3. The strategy service post-filter dropping uncited drafts.

**Original diagnostics planned** (not run — the code-side fix
landed first, retiring the need to investigate prod state):

- `model_runs` row for the raw LLM `recommended_drafts` array.
- `template_recommender.recommend(matter)` output.
- Frontend empty-drafts copy.

**Resolution (PR #8):** `_build_recommended_drafts` now filters
LLM-derived slugs to registry-known templates BEFORE the `[:12]` panel
slice; when zero are known it falls back to
`recommend_templates(forum_level, practice_area)`. Three review
iterations on this single function (initial fix → append-vs-replace
bug → mixed-case slice bug) are all locked down by regression tests:
`test_recommended_drafts_fallback_when_llm_emits_no_slugs`,
`test_recommended_drafts_keeps_llm_slugs_when_emitted`,
`test_recommended_drafts_fallback_replaces_when_llm_emits_only_unknown_slugs`,
`test_recommended_drafts_filters_unknowns_before_slicing_in_mixed_case`.

---

## 3. Code-level reasoning-token budget handling in `services/llm.py` — **CLOSED by PR #8**

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

**Longer-term ideal fix (not adopted; the floor below is the accepted close):**
the OpenAI provider could split the reasoning budget from the visible-
content budget — pass `max_completion_tokens` AND `reasoning.effort`
(or `reasoning.max_tokens` once the SDK exposes it) so the visible
content isn't starved when reasoning expands. This wasn't pursued
because the SDK doesn't yet expose a clean reasoning-budget knob and
the 8192-floor approach already prevents the trap with much less
code-surface risk.

**Resolution (PR #8):** adds `_REASONING_PREFIXES` (`gpt-5`, `o1`, `o3`) and `_REASONING_MIN_COMPLETION_TOKENS=8192` to `OpenAIProvider`, plus an `_effective_max_completion_tokens(requested)` helper that floors the cap and emits a `logger.warning` when the operator's setting is below the floor. Operator can still set max_tokens above the floor; the floor only catches under-configured caps so a future cutover of any new purpose to a reasoning model can't re-trigger the empty-content trap. Regression tests cover gpt-5-mini / gpt-4o-mini pass-through / no-lower-on-16K / o3-mini in `tests/test_llm_provider.py`.

**Note:** the env override `CASEOPS_LLM_MAX_OUTPUT_TOKENS_RECOMMENDATIONS=16384` on `caseops-api` becomes redundant for the floor case (the code now enforces 8192 minimum). The override can stay for the more-generous 16384 budget if you want headroom; either is correct.

---

## Memory entry

Captured at
`~/.claude/projects/C--Users-mishr-caseops/memory/feedback_reasoning_model_max_tokens.md`
so future agents touching the LLM provider stack are aware.
