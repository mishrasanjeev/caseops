# CaseOps performance review — 2026-05-15

Branch: `perf/review-2026-05-15` (off `origin/main`).
Scope: brutal scan triggered by user report — "Login looks slower, Home never
loads and moves to today." Read-only investigation; no code changed yet.

---

## Headline (TL;DR)

1. **Home → /today is a bug, not a perf issue.** `apps/web/app/app/page.tsx:45-49`
   unconditionally redirects to `/app/today` for any user with `>= 1` active
   matter. Real users never see Home. This was added → reverted → re-added in
   the same week (commits `a2601b5` → `db0fdc2` → `2bdea6d`).
2. **Login feels slow because the post-login Home page re-fetches a portfolio
   the user never gets to see** before the redirect fires. The flow today is
   `POST /api/auth/login → /app (fetch matters + corpus stats) → useEffect →
   /app/today (fetch today view)` — three sequential round-trips after the
   sign-in itself returns. Fixing #1 also collapses this perceived slowness
   for users who land on `/app/today` deliberately.
3. **Backend login adds ~one extra DB write + commit on the hot path** that
   doesn't need to be synchronous (`record_employee_login` → audit insert).
4. **No `--min-instances` on `caseops-api`** in `scripts/deploy-prod.sh` →
   every login after idle eats a Cloud Run cold start (3–8 s).
5. Two Today endpoints (`build_matter_next_action`, `_tasks`/`_drafts_in_review`/
   `_overdue_invoices`) are unbounded and / or do per-matter work in Python
   instead of in SQL. Today is fine on a small tenant; this will hurt at scale.

Below is a P0 → P2 fix plan with file:line citations and recommended shape.
**No code is changed in this commit — this is the plan.** Each fix is small,
surgical, and reversible.

---

## P0-1 — Home redirects to /today, hiding the dashboard

**Symptom:** "Home never loads and moves to today."

**Root cause** — `apps/web/app/app/page.tsx:45-49`:

```tsx
useEffect(() => {
  if (mattersQuery.isSuccess && activeCount > 0) {
    router.replace("/app/today");
  }
}, [activeCount, mattersQuery.isSuccess, router]);
```

The useEffect waits for the matters list to resolve, then unconditionally
sends every user with at least one active matter to `/app/today`. The
`/app/today` route is **already** in the Sidebar as its own nav item
(`apps/web/components/app/Sidebar.tsx:50`), so this redirect doesn't help
discovery — it strands users who clicked "Home" on a different page.

History (just `git log apps/web/app/app/page.tsx`):

| Date | Commit | What |
|------|--------|------|
| 2026-05-01 | `a2601b5` | "default route /app → /app/today" — added the redirect |
| 2026-05-02 | `db0fdc2` | "Home (/app) is the portfolio dashboard again — drop /app → /app/today redirect" — explicitly reverted with a long rationale |
| 2026-05-05 | `2bdea6d` | "Fix PG-004 app today redirect" — re-added the redirect, gated on `activeCount > 0` |

So the redirect was deliberately removed by Sanjeev on 2026-05-02 with a
clear product reason ("partners reviewing a multi-matter book need a
portfolio glance; that path was friction'd through Today") and re-introduced
three days later. The current state contradicts that decision.

### Fix shape (one PR, ~5 LoC)

**Edit:** `apps/web/app/app/page.tsx`

- Delete lines 45-49 (the `useEffect` redirect).
- Delete the now-unused `useRouter` import (line 6) and the `useRouter()`
  call (line 23). Keep the rest of the component as-is — it already has
  proper empty/loading/error states.

**Side-effects to keep working:**

- `apps/web/app/app/page.test.tsx` — likely asserts the redirect. Update test
  to assert the dashboard renders instead. Run `npm run test --filter @caseops/web`.
- `tests/e2e/pg-004-today-cockpit-2026-05-01-prod.spec.ts:23` — likely the
  prod Playwright spec that locks in the redirect. Adjust to navigate to
  `/app/today` explicitly instead of relying on `/app` to redirect.

**Verification (per the brutal-honest testing rule):**

1. Local: `npm run test --filter @caseops/web` passes.
2. Local Playwright: a fresh QA-Bot login lands on `/app`, sees the
   dashboard cards, can click the Sidebar Today link to reach `/app/today`.
3. Prod-Playwright spec line citing the post-deploy SHA.

**Risk:** very low. Sidebar's Today link still works. `/app/today` is fully
functional today. Reverting is a single-file change.

---

## P0-2 — Perceived "login slowness" is the cascaded post-auth fetch chain

**Symptom:** "Login looks slower."

**The chain** (each step is a round-trip; nothing parallelizes across them):

1. `POST /api/auth/login` — bcrypt verify + 1 user-by-email lookup + 1
   memberships eager-load + 1 audit insert + commit (see backend timings
   in P1-1).
2. `router.replace("/app")` — `apps/web/app/sign-in/SignInForm.tsx:60`.
3. `/app` mounts → `RequireAuth` waits one paint frame for `useSession` to
   read localStorage (`apps/web/components/app/RequireAuth.tsx:24-32`,
   `apps/web/lib/use-session.ts:25-49`) → renders the loader.
4. `DashboardPage` fires two queries: `listMatters({ limit: 50 })` and
   `fetchAuthorityCorpusStats()` (both `enabled: session.status ===
   "authenticated"`, so they wait on step 3).
5. `useEffect` fires when `mattersQuery.isSuccess` → `router.replace("/app/today")`.
6. `/app/today` mounts → fires `fetchTodayView({ horizonDays: 7 })`
   (`apps/web/app/app/today/page.tsx:42-45`).
7. **Now** the user sees their Today feed.

Steps 4 and 6 are in series (4 must finish before 5 fires the redirect that
triggers 6). On a Cloud Run cold start with even a 200-matter tenant,
that's easily 2–4 s after the login response itself returned.

**Step 7 is the only thing the user actually wants to see** for the
"redirect" path. So the dashboard fetches in step 4 are a tax that the
useEffect imposes on every login.

### Fix shape

**Removing the redirect (P0-1 above) is the entire fix here for users with
matters.** They land on `/app`, see the dashboard skeletons immediately,
and the two parallel queries fill in. No /today round-trip on the critical
path.

For users who clicked the Sidebar's Today link from sign-in: that's a
direct navigation to `/app/today`, single round-trip.

**Optional tightening** (separate small PR, P1):

- `apps/web/lib/use-session.ts:25-29`: read `getStoredContext()` in the
  `useState` initializer instead of starting at `status: "loading"` and
  filling in via `useEffect`. The current shape causes RequireAuth to
  flash "Loading your workspace…" for one paint frame on every full
  navigation, even when the cookie + context are already present.

  ```diff
  - const [state, setState] = useState<SessionState>({
  -   status: "loading",
  -   token: null,
  -   context: null,
  - });
  + const [state, setState] = useState<SessionState>(() => {
  +   const context = getStoredContext();
  +   return { status: context ? "authenticated" : "anonymous", token: null, context };
  + });
  ```

  Also stops the queries on the dashboard from waiting for the
  `enabled` flip.

---

## P1-1 — Login endpoint: defer the audit-insert + commit off the hot path

**File:** `apps/api/src/caseops_api/services/employees.py:1894-1917`

```python
def record_employee_login(session, *, membership):
    profile = membership.employee_profile
    if profile is None:
        return
    now = _utcnow()
    profile.last_login_at = now
    profile.updated_at = now
    record_audit(session, ..., action="employee.login", ...)
    session.commit()
```

Called inside `authenticate_user` (`apps/api/src/caseops_api/services/identity.py:182`)
**before** the response is built. On a typical Cloud Run + Cloud SQL setup,
that's:

- 1 INSERT into `audit_events`
- 1 UPDATE on `employee_profiles`
- 1 COMMIT (round-trip to Cloud SQL)

Total ~30–80 ms on top of bcrypt's 80–150 ms. Not catastrophic, but the
audit row + last-login update are not on the user's critical path — failure
to write them shouldn't fail the login.

### Fix shape

Two options, pick one:

**Option A (recommended, smallest):** keep synchronous, but make the audit
write fire-and-forget via FastAPI `BackgroundTasks`:

```python
# apps/api/src/caseops_api/api/routes/auth.py
@router.post("/login", ...)
async def login(request, response, payload, session, background: BackgroundTasks):
    auth = authenticate_user(session, ...)
    background.add_task(record_employee_login_async, session_factory, membership_id)
    issue_session_cookies(...)
    return auth
```

Pull `record_employee_login` out of `authenticate_user` and let the route
own the deferral. The function itself becomes a no-op in the sync path.
`session_factory` opens a fresh DB session (the request session is closed
when the response goes out).

**Option B:** keep synchronous but skip the second `session.commit()` —
the surrounding request will commit anyway on dispose. Saves the round-trip
without changing semantics. This is a one-line change and is the safest.

**Verification:**

- `pytest apps/api/tests/test_auth*.py -k login` — green.
- Add one test: login completes; audit row visible within 1s.
- Time the prod login round-trip before/after via the existing
  `tests/e2e/auth-*.spec.ts` perf log.

---

## P1-2 — Cloud Run `caseops-api` has no `--min-instances`

**File:** `scripts/deploy-prod.sh:67-77`

Today's deploy:

```bash
gcloud run deploy caseops-api \
  --concurrency 40 --timeout 300s --cpu 2 --memory 4Gi --image ...
```

No `--min-instances` flag → defaults to 0 → after the service idles past the
Cloud Run keepalive window, the next request boots a fresh container.
Booting Python + SQLAlchemy + the model graph + secret fetches takes
**3–8 s** on `caseops-api`. The first user-facing login of the day eats
this. The user perceives this as "login is slow."

### Fix shape

Add `--min-instances=1` to the API deploy block (only on prod). Estimated
cost: one always-on `cpu=2 / memory=4Gi` instance ≈ $35–50/month. For a
B2B legal product this is the right trade-off.

```diff
   gcloud run deploy caseops-api \
     --region "${REGION}" \
     --project "${PROJECT}" \
     --quiet \
     --concurrency "${API_CONCURRENCY}" \
+    --min-instances=1 \
     --timeout "${API_TIMEOUT}" \
     ...
```

If the user wants to avoid the cost: add `--min-instances=1` only via a
Cloud Scheduler job that warms the service Mon–Fri 09:00–20:00 IST, and
let it scale to 0 outside business hours. But the simple flag is the
cleanest first move.

**Verification:** after deploy, `gcloud run services describe caseops-api`
shows `minInstances: 1`. Hit `https://api.caseops.ai/api/health` after a
30-min idle window → response time `< 200 ms`.

**Risk:** one extra always-on instance bills slowly. Not destructive.

---

## P1-3 — `build_matter_next_action` does whole-tenant Today aggregation per matter

**File:** `apps/api/src/caseops_api/services/today_view.py:352-399`

```python
def build_matter_next_action(session, *, context, matter_id, today=None):
    ...
    hearings = [
        h for h in _hearings(session, context.company.id, today, horizon_end)
        if h.matter.id == matter_id
    ]
    tasks = [t for t in _tasks(session, context.company.id, ...) if t.matter.id == matter_id]
    drafts = [d for d in _drafts_in_review(session, context.company.id) if d.matter.id == matter_id]
    invoices = [i for i in _overdue_invoices(...) if i.matter.id == matter_id]
    deadlines = [d for d in _deadlines(...) if d.matter.id == matter_id]
```

Each `_hearings`/`_tasks`/etc. function pulls **all rows for the entire
tenant**, then this caller filters in Python. With 500 matters, fetching
the next-action card for one matter does 5 queries over the whole tenant
+ Python list comprehension on potentially thousands of rows. The
docstring even acknowledges this: "Cheaper than re-querying — we already
have these joined views" — which is wrong, since this is a separate
endpoint with no shared cache.

### Fix shape

Add a `matter_id` filter parameter to each `_hearings/_tasks/_drafts/_invoices/_deadlines`
helper (default `None`). When set, push the filter into the SQL `WHERE`.
`build_matter_next_action` passes `matter_id=matter_id`. Tenant-wide
callers (`build_today_view`) pass `matter_id=None` — same query as today.

That turns five tenant-scans into five indexed lookups by `matter_id`
(all `Matter*` tables already have `matter_id` indexed via FK).

**Verification:**

- `pytest apps/api/tests/test_today_view*.py` — extend with a "two-matter
  tenant, next-action only touches matter A" test that asserts SQL
  cardinality (use SQLAlchemy event hooks to count statements).
- Time `/api/matters/{id}/next-action` on a 200-matter tenant before/after.

**Risk:** isolated to one service module. Test coverage already exists.

---

## P1-4 — Today aggregator queries are unbounded

**File:** `apps/api/src/caseops_api/services/today_view.py`

- `_drafts_in_review` (line 236) — no `.limit()`. Returns every IN_REVIEW
  draft tenant-wide.
- `_tasks` (line 191) — no `.limit()`. Returns every uncompleted task
  with `due_on IS NULL OR due_on <= horizon_end` for the user.
- `_overdue_invoices` (line 261) — no `.limit()`.
- `_deadlines` (line 293) — no `.limit()`.

A heavy tenant could return tens of thousands of rows per response. The
JSON payload alone bloats `/api/me/today`. This isn't a today-bug; it's
a scale trap.

### Fix shape

Add a `MAX_PER_STREAM = 100` constant and apply `.limit(MAX_PER_STREAM)`
to each aggregator. Surface a `truncated: bool` flag in the schema; the
Today UI shows "and N more" links to the full list view (matters,
hearings, etc.).

**Verification:**

- Add `tests/test_today_view.py::test_streams_cap_at_max_per_stream`.
- No UI change needed for v1 — 100 rows per stream is far above what
  any single user should be triaging in one morning.

**Risk:** none — pure capacity ceiling, no behaviour change for normal
tenants.

---

## P1-5 — `RequireAuth` causes a one-frame loading flash on every navigation

**File:** `apps/web/components/app/RequireAuth.tsx:24-32` +
`apps/web/lib/use-session.ts:25-49`

`useSession` starts at `status: "loading"`, then a `useEffect` reads
localStorage and flips to `authenticated` / `anonymous`. On every full
navigation (sign-in → /app, refresh, deep link), the layout shows
`Loading your workspace…` for one paint, then renders the page. Users
perceive this as "the app is reloading on every click."

The cookie + the localStorage context are both available synchronously on
the first render — there's no reason to wait for an effect.

### Fix shape

See the diff in P0-2 above. One-line change to `useState` initializer.
Removes the loading flash for already-authenticated users while keeping
the safety guarantee for anonymous ones.

**Verification:**

- `apps/web/lib/use-session.test.ts` already covers session lifecycle —
  add an assertion that the initial render is not `loading` when
  `localStorage.caseops.session.context` is set.

**Risk:** SSR safe — `getStoredContext` already returns `null` when
`window` is undefined (`apps/web/lib/session.ts:26-28`).

---

## P2-1 — Three pages declared `dynamic = "force-dynamic"` that don't need it

**Files:**

- `apps/web/app/account/setup/page.tsx`
- `apps/web/app/account/reset-password/page.tsx`
- `apps/web/app/sign-in/page.tsx`

`dynamic = "force-dynamic"` opts the route out of Next.js's static / ISR
caching. For `/sign-in`, that means every request to the marketing-facing
sign-in route hits Node SSR. For `/account/setup` and `/reset-password`,
the route is token-gated but the page shell itself is static — only the
form mutation needs runtime.

### Fix shape

Audit each page. If the only "dynamic" reason is reading `searchParams`
inside a Suspense boundary (which `/sign-in` does), Next 16's RSC handles
that correctly without `force-dynamic`. Drop the directive; let Next pick
the right cache mode. If a page genuinely needs runtime data, leave it.

**Verification:**

- `npm run build` — confirm the routes are reported as `prerendered`
  or `static` instead of `dynamic`.
- Manual: deep link to `/account/setup?token=…` and `/sign-in?next=/app`
  still works.

**Risk:** medium-low — `force-dynamic` was probably added defensively. Drop
behind a single PR, watch the build output, revert if anything regresses.

---

## P2-2 — `_drafts_in_review`, `_overdue_invoices` issue 1 query per stream — could parallelize

`build_today_view` (`today_view.py:128-152`) issues five sequential
SQLAlchemy queries on the request thread. With Cloud SQL round-trips of
~5–15 ms each, that's 25–75 ms of unnecessary serial latency.

### Fix shape

The five aggregators are tenant-scoped reads with no inter-dependency.
Wrap them in `asyncio.gather` (would require an async session or a
`run_in_executor` shim). Lower priority; only ~50 ms saved.

**Skip unless** Today endpoint p95 is reported slow under real load.

---

## P2-3 — `next.config.ts` could bundle-report fonts more tightly

`apps/web/next.config.ts` has rich CSP + redirect logic but no
`experimental.optimizePackageImports` for `lucide-react`,
`@radix-ui/react-*`, or `@tanstack/react-table`. Next 16 supports this
flag and shaves ~20–80 KB off the dashboard route.

### Fix shape

```diff
 const nextConfig: NextConfig = {
   reactStrictMode: true,
+  experimental: {
+    optimizePackageImports: [
+      "lucide-react",
+      "@radix-ui/react-dialog",
+      "@radix-ui/react-dropdown-menu",
+      "@tanstack/react-table",
+    ],
+  },
   async headers() { ... },
```

Verify with `npm run build` and check the per-route bundle size deltas.
Low risk, easy revert.

---

## What I deliberately did NOT touch

- **Codex CLI's in-flight work** on `codex/release-signoff-2026-05-14`
  (release sign-off docs, `docs/STRICT_*` updates, `docs/FUTURE_WORKPLAN_2026-05-14.md`
  untracked file). This worktree is on a fresh branch off `origin/main`;
  Codex's branch is untouched.
- **The auth flow's `/api/auth/me` round-trip on every page** — the cookie
  cutover (EG-001) already removed this; only `useSession` reads
  localStorage now.
- **bcrypt cost factor** — staying at the configured value; lowering it
  trades away security.
- **The recommendations / bench-strategy / HNSW prefilter** — already
  fixed in `da7216a` (BUG-015 root cause), per `session_log.md`.
- **CSP**, **CORS**, **rate-limit** — all production-correct.

---

## Suggested rollout order

1. **P0-1** (one PR, ~5 LoC) — remove the Home → /today redirect. Ship
   first; this is the user's actual blocking complaint.
2. **P1-2** (one PR, +1 flag) — add `--min-instances=1` to the API
   Cloud Run deploy script. Ship same day; immediate login speedup
   for the next idle period.
3. **P1-1** (one PR, ~10 LoC) — defer the login audit-write off the
   hot path.
4. **P0-2 optional / P1-5** (one PR, ~5 LoC) — synchronous `useSession`
   initializer.
5. **P1-3** (one PR, ~30 LoC + tests) — push `matter_id` filter into
   `_hearings/_tasks/_drafts/_invoices/_deadlines`.
6. **P1-4** (one PR, ~20 LoC + tests) — bound the Today aggregator
   responses.
7. **P2-1**, **P2-3** — two small Next.js bundle/build wins. Bundle
   together.
8. **P2-2** — only if Today endpoint shows real slowness in production
   logs.

Each PR is independently revertable. None touches more than two files.
None changes a public API contract.

---

## Verification stance per the brutal-honest testing rule

Every fix above must produce a named prod-Playwright spec line + commit
SHA before being declared `Properly fixed`. Specifically:

- **P0-1** — extend `tests/e2e/pg-004-today-cockpit-2026-05-01-prod.spec.ts`
  with a "Home renders dashboard, does not redirect" assertion. Run
  against the deployed SHA after the PR ships.
- **P1-2** — `curl https://api.caseops.ai/api/health` after a 30-min idle
  window, expect `< 200 ms`. Persist as `tests/e2e/api-cold-start.spec.ts`.
- **P1-1** — backend test asserting login path emits the audit row
  asynchronously (`pytest apps/api/tests/test_auth.py::test_login_audit_async`).
- **P1-3 / P1-4** — SQLAlchemy event-hook test counting statements per
  next-action call.

Anything that ships without a green prod-Playwright line goes into the
`docs/STRICT_BUG_TASKLIST_2026-04-22.md` ledger as `Inconclusive` per
the bug-fixing skill, not `Properly fixed`.
