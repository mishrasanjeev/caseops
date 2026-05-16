# CaseOps performance review — 2026-05-15

Triggered by user report — "Login looks slower, Home never loads and moves
to today." Brutal scan of the login + Home path plus a broader P0–P2 sweep.

**Status legend:** ✅ shipped & merged · ⏳ planned (not started) · ⚠️ correctness caveat.

This doc lands as a docs-only follow-up PR *after* P0-1 / P1-2 / P1-2b
already shipped. It is corrected from the original draft on four points
(P1-1 session.commit, P0 test surface, P1-5 deferral, P1-3/P1-4
matter-access scoping) — see each section.

---

## Headline (TL;DR)

1. **✅ Home → /today was a bug, not a perf issue.** `apps/web/app/app/page.tsx`
   had a `useEffect` that unconditionally redirected to `/app/today` for
   any user with ≥1 active matter. Added → reverted → re-added in one week
   (`a2601b5` → `db0fdc2` → `2bdea6d`). **Fixed in P0-1 (PR #38, main
   `6c4c093`)**, prod-Playwright verified.
2. **✅ "Login feels slow" was largely that redirect's cascade** —
   `POST /api/auth/login → /app (fetch matters + corpus stats) → useEffect
   → /app/today (fetch today view)`, three serial round-trips after
   sign-in returned. Collapsed by P0-1.
3. **⏳ Backend login does an extra audit insert + `commit()` on the hot
   path** (`record_employee_login`). Deferrable — but **only** via
   BackgroundTasks + a fresh DB session (corrected; see P1-1).
4. **✅ No `--min-instances` on either Cloud Run service** → cold start on
   first login after idle. **Fixed in P1-2 (api) + P1-2b (web)**, PR #39,
   main `9e7111a`; live `minScale=1` on both verified.
5. **⏳⚠️ Today endpoints (`build_matter_next_action`, the five
   `_hearings/_tasks/_drafts_in_review/_overdue_invoices/_deadlines`
   aggregators) are unbounded AND only company-scoped** — they skip the
   matter-access visibility predicate, so this is a tenant/matter-isolation
   correctness gap, not only a scale trap (corrected; see P1-3/P1-4).

---

## P0-1 — Home redirected to /today, hiding the dashboard ✅ SHIPPED

**Symptom:** "Home never loads and moves to today."

**Root cause** — the removed block in `apps/web/app/app/page.tsx`:

```tsx
useEffect(() => {
  if (mattersQuery.isSuccess && activeCount > 0) {
    router.replace("/app/today");
  }
}, [activeCount, mattersQuery.isSuccess, router]);
```

The effect waited for the matters list, then unconditionally sent every
user with ≥1 active matter to `/app/today`. `/app/today` is already its
own Sidebar nav item (`apps/web/components/app/Sidebar.tsx:50`), so the
redirect didn't aid discovery — it stranded anyone who clicked "Home".

History (`git log apps/web/app/app/page.tsx`):

| Date | Commit | What |
|------|--------|------|
| 2026-05-01 | `a2601b5` | added the redirect |
| 2026-05-02 | `db0fdc2` | **reverted** with a product rationale |
| 2026-05-05 | `2bdea6d` | re-added, gated on `activeCount > 0` |
| 2026-05-15 | `6c4c093` (#38) | removed again — this fix |

### Fix shipped

`apps/web/app/app/page.tsx`: removed the `useEffect` redirect + the
now-unused `useRouter`/`useEffect` imports and the `router` binding. The
dashboard render path (loading/empty/error states) is otherwise unchanged.

### P0 test surface (corrected — all three updated together)

All three were updated so the no-redirect behaviour is the regression
guard, not just the unit test:

- **`apps/web/app/app/page.test.tsx`** — the old "redirects active
  workspaces to Today" test inverted to "renders the dashboard for active
  workspaces and does not redirect" (asserts the heading renders +
  `router.replace` never called).
- **`tests/e2e/pg-004-today-cockpit-2026-05-01-prod.spec.ts`** — the
  redirect test inverted to "/app renders the portfolio dashboard and
  does NOT redirect", with a wait window so a re-introduced redirect
  *fails* (not passes). Header comment updated.
- **`tests/e2e/app-spine.spec.ts`** — the spine flow now asserts `/app`
  stays on `/app` and shows the dashboard heading, then reaches Today
  via the Sidebar link instead of via a redirect.

### Verification (done)

- `typecheck:web` ✓, web vitest 333/333 ✓, `next build` ✓.
- Canonical prod-Playwright proof:
  `pg-004-today-cockpit-2026-05-01-prod.spec.ts:127` PASSED on deployed
  `f75a9c4` / `caseops.ai` / QA-Bot active workspace (6/6 green).
- Local `e2e:app` app-spine failures were a pre-existing local
  cookie-seam (3100↔8000 cross-origin bounce to /sign-in), not P0-1 —
  prod single-domain confirmed the fix.

---

## P1-2 — `caseops-api` `--min-instances=1` ✅ SHIPPED

`caseops-api` had no `minScale` annotation (scaled to 0). The first login
after any idle window paid a 3–8 s cold start (Python + SQLAlchemy model
graph + Cloud SQL connect + clamav sidecar) — the dominant component of
"login is slow".

Shipped in `scripts/deploy-prod.sh` (PR #39, main `9e7111a`) as
`API_MIN_INSTANCES="${API_MIN_INSTANCES:-1}"` + `--min-instances` placed
in the **service-level** flag group (a gotcha: with multi-container
`gcloud run deploy --container api`, service-level flags must precede the
first `--container` or gcloud rejects them as container-scoped). Live
`caseops-api` `autoscaling.knative.dev/minScale=1` verified.

## P1-2b — `caseops-web` `--min-instances=1` ✅ SHIPPED

`/sign-in` is `dynamic = "force-dynamic"` (SSR per request, no CDN
cache), so with web `minScale=0` the first hit after idle cold-started
the Next.js node server (~1–3 s) before the login form was even usable —
the leading cold-path latency once the API is warm. `caseops-web` is
stateless (no DB / sidecar); ≈ $10–18/mo. Shipped same PR as
`WEB_MIN_INSTANCES="${WEB_MIN_INSTANCES:-1}"` + `--min-instances`. Live
`caseops-web` `minScale=1` verified.

---

## P1-1 — Defer the login audit-write off the hot path ⏳ PLANNED

**File:** `apps/api/src/caseops_api/services/employees.py` —
`record_employee_login` writes an `audit_events` INSERT + an
`employee_profiles` UPDATE + a `session.commit()`, called inside
`authenticate_user`
(`apps/api/src/caseops_api/services/identity.py:182`) *before* the login
response is built. ~30–80 ms of Cloud SQL round-trips on the user's
critical path, on top of bcrypt. The audit row + last-login stamp are not
user-facing and their write failing should not fail the login.

### Fix shape (corrected — single sanctioned approach)

Move the audit/last-login write off the request path with FastAPI
`BackgroundTasks`, opening a **fresh DB session inside the task**:

```python
# apps/api/src/caseops_api/api/routes/auth.py
@router.post("/login", ...)
async def login(request, response, payload, session, background: BackgroundTasks):
    auth = authenticate_user(session, ...)            # no audit write here
    background.add_task(record_employee_login_bg, membership_id)  # opens its own session
    issue_session_cookies(...)
    return auth
```

`record_employee_login_bg` must construct its **own** session
(`get_db_session`-equivalent factory) — the request-scoped session is
closed once the response is sent and cannot be reused in the background
task.

> **Corrected — do NOT drop `session.commit()`.** An earlier draft
> floated "Option B: skip the second `session.commit()` and let request
> teardown commit." That is unsafe and has been removed entirely:
> `get_db_session` in this repo **only closes** the session on teardown —
> it does not auto-commit. Dropping the explicit commit silently loses
> the audit + last-login writes. BackgroundTasks + a fresh session is the
> only recommended shape.

### Verification (planned)

- `pytest apps/api/tests/test_auth*.py -k login` green.
- New test: login completes; the audit row is visible shortly after
  (assert via a fresh session, not the request session).
- Prod-Playwright login timing before/after.

---

## P1-3 — `build_matter_next_action` does whole-tenant work per matter ⏳ PLANNED ⚠️

**File:** `apps/api/src/caseops_api/services/today_view.py:352-399`.
`build_matter_next_action` calls all five
`_hearings/_tasks/_drafts_in_review/_overdue_invoices/_deadlines`
helpers, each scanning the **entire tenant**, then filters in Python by
`matter_id`. With N matters this is O(N) tenant scans to render one
matter's next-action card.

### Fix shape

Add an optional `matter_id` parameter to each helper; when set, push the
filter into SQL `WHERE` (every `Matter*` table already has `matter_id`
indexed via FK). `build_matter_next_action` passes `matter_id=matter_id`;
`build_today_view` passes `matter_id=None` (unchanged query).

## P1-4 — Today aggregators unbounded **and matter-access-blind** ⏳ PLANNED ⚠️

**File:** `apps/api/src/caseops_api/services/today_view.py` —
`_tasks` (191), `_drafts_in_review` (236), `_overdue_invoices` (261),
`_deadlines` (293), `_hearings` (164).

Two distinct problems:

**(a) Unbounded.** None apply `.limit()`. A heavy tenant returns
thousands of rows per stream and bloats `/api/me/today`. Add a
`MAX_PER_STREAM` cap (≈100) + a `truncated` flag; the UI links out to the
full list view per stream.

**(b) ⚠️ Matter-access-blind (correctness, corrected).** Every aggregator
filters on `Matter.company_id == company_id` **only**. It does **not**
apply the matter-access visibility predicate that `list_matters` uses
(`visible_matters_filter(session, context=context)` in
`apps/api/src/caseops_api/services/matters.py:1117`). Result: a user
whose access is scoped by `MatterAccessGrant` / an ethical wall can see
hearings, tasks, drafts-in-review, overdue invoices, and deadlines for
matters they are **not** entitled to. This is a tenant/matter-isolation
defect (CLAUDE.md: "Matter-level permissions and ethical walls must
override broad role access"), not merely a scale concern — treat it as
the higher-priority half of this item.

### Fix shape

Thread `context` (not just `company_id`) into `build_today_view` and each
aggregator, and add the **same** `visible_matters_filter(session,
context=context)` predicate to every query's `WHERE` (joined on
`Matter`), exactly as `list_matters` does. Then apply the `MAX_PER_STREAM`
bound. `build_matter_next_action` (P1-3) inherits the predicate for free
once the helpers take `context`.

### Verification (planned)

- Multi-matter, restricted-access tenant test: a user with a grant to
  matter A only must see **zero** today-stream rows for matter B
  (hearings/tasks/drafts/invoices/deadlines) — assert per stream.
- SQLAlchemy statement-count test proving `build_matter_next_action`
  touches one matter, not the whole tenant.
- `MAX_PER_STREAM` cap test.

---

## P1-5 / P0-2 — `useSession` synchronous initializer ⏳ DEFERRED (corrected)

**File:** `apps/web/lib/use-session.ts:25-49` + consumed by
`apps/web/components/app/RequireAuth.tsx:24-32`.

`useSession` starts at `status: "loading"` and only flips to
`authenticated`/`anonymous` inside a `useEffect` that reads
`localStorage`. On every full navigation the app shell shows
"Loading your workspace…" for one paint frame even when the cookie +
context are already present.

> **Corrected — NOT an immediate safe one-liner; deferred.** The original
> draft proposed reading `getStoredContext()` directly in the `useState`
> initializer as a trivial change. Under React 19 + Next 16 RSC,
> initializing client state from `localStorage` risks an SSR/CSR
> hydration mismatch (server render has no `localStorage`; a mismatched
> first client render can throw or silently desync auth state). This is
> **deferred pending hydration/browser verification** — it requires a
> real-browser check (and likely a mounted-guard or
> `useSyncExternalStore` pattern), not a blind initializer swap. Do not
> ship as a quick diff.

### Path when picked up

Prototype with `useSyncExternalStore` (server snapshot = anonymous,
client snapshot = stored context) so SSR and first client paint agree;
verify in a prod-like browser that RequireAuth no longer flashes and
there is no hydration warning, before shipping.

---

## P2-1 — `force-dynamic` on three pages ⏳ PLANNED

`apps/web/app/sign-in/page.tsx`, `apps/web/app/account/setup/page.tsx`,
`apps/web/app/account/reset-password/page.tsx` declare
`export const dynamic = "force-dynamic"`, opting out of static/ISR. Audit
whether `searchParams`-in-Suspense is the only "dynamic" reason (Next 16
handles that without the directive); drop where safe, confirm via
`npm run build` route report. Note this interacts with P1-2b — even
static the first cold request still pays a server boot, so P1-2b remains
the primary login-page latency fix.

## P2-3 — `optimizePackageImports` ⏳ PLANNED

`apps/web/next.config.ts` has no
`experimental.optimizePackageImports`. Adding `lucide-react`,
`@radix-ui/react-*`, `@tanstack/react-table` shaves ~20–80 KB off the
dashboard route. Verify per-route bundle deltas via `npm run build`.

## P2-2 — Parallelize the five Today queries ⏳ LOW PRIORITY

`build_today_view` issues five sequential SQLAlchemy queries (~25–75 ms
serial). Parallelizing saves ~50 ms; only worth it if Today p95 is slow
under real load. Note: must be done *after* P1-4 so the parallelized
queries already carry the matter-access predicate.

---

## Rollout status

| Item | Status |
|------|--------|
| P0-1 Home redirect removal | ✅ shipped, PR #38, main `6c4c093`, prod-verified |
| P1-2 api min-instances | ✅ shipped, PR #39, main `9e7111a`, live minScale=1 |
| P1-2b web min-instances | ✅ shipped, PR #39, main `9e7111a`, live minScale=1 |
| P1-1 defer login audit (BackgroundTasks + fresh session) | ⏳ planned |
| P1-3 next-action per-matter scoping | ⏳ planned |
| P1-4 Today bound + **matter-access predicate** | ⏳ planned ⚠️ correctness |
| P1-5 useSession initializer | ⏳ deferred (hydration verification) |
| P2-1 / P2-2 / P2-3 | ⏳ planned / low priority |

Each remaining item is independently shippable and revertable; none
changes a public API contract. P1-4's matter-access predicate is the
only remaining item with a correctness (not just performance)
dimension and should be sequenced first among the P1 remainder.
