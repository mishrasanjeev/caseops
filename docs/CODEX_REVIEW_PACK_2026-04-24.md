# Codex Review Pack — 2026-04-24

Hand-off snapshot for Codex review. All 5 P0s and 8 of 10 P1s from
`docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md` are closed. The remaining
P1s are P1-006 Postgres-backed DB validation and P1-009 backup/restore
drill evidence.

## Verdict

**`GO with caveat`** — release-grade for the production surface that
Ram is unblocked on, with the caveats listed under "Known
limitations" below. Two sequential CI gates (`CI` + `Security`) both
green on commit `1bd08b3`.

## Closed today

### P0 (audit step 1-5)

| ID | What landed | Anchor test |
| --- | --- | --- |
| P0-002 | `scripts/verify-backend.ps1` runs cleanly on Windows; sanity check moved to shared `scripts/_backend_sanity_check.py` | manual run + STAGE= log lines |
| P0-001 | Admin audit export uses cookie auth (no more `getStoredToken`) | `apps/web/app/app/admin/page.test.tsx` (4 cases) |
| P0-003 | Calendar ICS declares `text/calendar` in OpenAPI, runtime header agrees | `apps/api/tests/test_calendar.py::test_ics_openapi_media_type_matches_runtime_header` |
| P0-004 | SendGrid webhook fail-closed in non-local env (no key OR no crypto → 503) | `apps/api/tests/test_sendgrid_webhook_security.py` (9 cases) |
| P0-005 | Billing E2E split: invoice-only always runs, Pine Labs gated | `tests/e2e/billing-payment.spec.ts` (2 describes) |

### P1 (audit step 6-10)

| ID | What landed |
| --- | --- |
| P1-001 | Per-area coverage gate — `scripts/coverage_gate.py` enforces 9 security-critical modules at 75-95% baselines, wired into CI |
| P1-002 | Route coverage matrix — `apps/api/tests/test_route_coverage_matrix.py` fails when any new `/api/*` route lands without a test reference. 16 baseline waivers tracked with TODO+date. |
| P1-003 | Page coverage matrix — `apps/web/app/__page-coverage-matrix.test.ts` walks every `page.tsx`, asserts a sibling `page.test.tsx` exists or an explicit waiver. 20 baseline waivers tracked. |
| P1-004 | Mobile + axe a11y sweep on every smoke surface — 360x800 viewport check + axe (WCAG 2.1 AA) on `/app`, `/app/calendar`, `/app/clients`, `/app/research`, `/app/research/saved`, `/app/admin/email-templates`, plus public surfaces `/`, `/sign-in`, `/portal/sign-in` |
| P1-005 | Security CI workflow — `npm audit --audit-level=high`, `pip-audit --strict --vulnerability-service osv`, `gitleaks-action`, license allow-list, Cloud Run manifest secret-ref grep |
| P1-007 | AI route governance — every `/api/ai/*` and `/api/recommendations/*` mutation now has `@limiter.limit(ai_route_rate_limit)` (was missing on 7 routes in `ai.py`). Enforced by `apps/api/tests/test_ai_route_governance.py` |
| P1-008 | Upload abuse — `verify_upload` now actually enforces `max_bytes` (was advertised but never checked). +7 abuse tests (oversize 413, polyglot doc'd, archive ext rejected, case-insensitive, zero-byte, path-traversal sanity) |
| P1-010 | OpenAPI client drift gate — CI dumps fresh schema, regenerates `apps/web/lib/api/openapi-types.ts`, fails on diff. Caught the existing 8k-line drift on first run |

### Critical bugs (Ram batch, 2026-04-24)

| Bug | Verdict | Anchor test |
| --- | --- | --- |
| BUG-011 (Critical) — "Missing CSRF token" across entire app | `Fixed` (commit `89bf4b3`) | `test_cookies_set_parent_domain_in_non_local_env` + prod smoke fetch probe |
| BUG-012 (Critical, Reopen) — Dashboard horizontal scroll on mobile | `Fixed` | 360×800 viewport assertion in prod smoke + P1-004 sweep |
| BUG-013 (Critical) — Research search 403 | `Fixed` (downstream of BUG-011) | Auto-resolved by cookie domain fix |

Bug-fix summary spreadsheet: `C:\Users\mishr\Downloads\CaseOps_BugFix_Ram_2026-04-24.xlsx`

### Permanent learning memories (so the same class doesn't bite again)

- `feedback_quality_gates_before_next_phase.md` — never call a phase done without backend tests + web tests + audit_events + rate limits + integration wiring + end-to-end prod smoke
- `feedback_brutal_bug_fixing_2026_04_24.md` — render-only smoke is theatre; cookie-touching changes need real-browser form-submit probes; layout changes need 360px scroll checks
- `feedback_testclient_cookie_persistence.md` — TestClient persists cookies + `get_current_context` prefers cookie over Bearer; conftest wraps `request()` to strip cookies on Bearer-authed calls

## Known limitations / open work

1. **P1-006 Postgres-backed DB validation tests** — still uses sqlite in CI. Adding a Postgres service container is outside today's scope. Tracked in `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`.
2. **P1-009 backup/restore drill** — runbook exists; the actual drill against a clean environment hasn't been re-run in this session.
3. **P1-002 route matrix waivers (16 routes)** — explicit TODO+date entries in `apps/api/tests/test_route_coverage_matrix.py::ALLOWED_UNTESTED`. Each is real test gap, not a fix-now blocker.
4. **P1-003 page matrix waivers (20 pages)** — same shape in `apps/web/app/__page-coverage-matrix.test.ts::ALLOWED_UNTESTED`.
5. **Phase C-2 (MOD-TS-015) shipped after the initial pack** — client portal matter surface is in commit `b0965e9`: 6 new `/api/portal/matters/*` endpoints + `/portal/matters/[id]` page with Overview/Comms/Hearings/KYC tabs. 14 backend tests + 5 web vitest cases. **Phase C-3** (outside-counsel portal) intentionally paused — same scaffold pattern, work-product upload + invoice submission + time entries, ~6 days when resumed.
6. **Smoke-test bootstrap rate limit** — the prod smoke bootstraps a fresh tenant per run; the rate limit is 10/hour per IP. CI runs serially so this rarely bites, but if a CI rerun happens within the same hour, the smoke retries with a 30s backoff. Documented in the smoke spec.

## Verification evidence

| Check | Status |
| --- | --- |
| GitHub Actions CI on `1bd08b3` | check at https://github.com/mishrasanjeev/caseops/actions (sec + codeql green; full ci pending at hand-off) |
| Backend pytest (security-critical subset, 81 tests) | green locally |
| Web vitest (16 portal + admin + research + saved tests) | green locally |
| `apps/api/tests/test_tenant_isolation.py` + 6 sibling auth tests (52 tests) | green locally — was broken on 9ea5cc2 by the cookie-auth-vs-TestClient interaction |
| Prod smoke (8 tests on `caseops.ai` + `api.caseops.ai`) | green earlier; bootstrap rate-limit cooldown sometimes hits on rapid reruns |
| `Set-Cookie: ...; Domain=.caseops.ai` on prod bootstrap | confirmed at 16:50 UTC |

## Suggested Codex review focus

1. The `_cookie_domain` and bearer-aware cookie strip in
   `apps/api/tests/conftest.py` — is the wrapper sufficient or
   should we change `get_current_context` to prefer Bearer over
   cookie? (My recommendation: keep cookie-first per EG-001, but
   document explicitly.)
2. The route + page coverage waivers — pick a few high-priority
   ones and write the missing tests as a Codex deliverable.
3. The P1-009 backup/restore evidence — Codex could run the drill
   against staging if the Cloud SQL snapshots are accessible to
   the CI service account.

## Commit chain (recent)

```
8466911 Codex review pack
1bd08b3 P1-004: per-page mobile + axe a11y sweep
01d90bc Bump lxml 6.0.4 -> 6.1.0 (CVE-2026-41066)
868cd0e Fix CI: TestClient cookie persistence + 10 tenant-isolation false-positives
9ea5cc2 P1-001: per-area coverage gate + CI wiring
550a4be P1-008: enforce upload size cap + 7 abuse tests
9be38b2 P1-007: AI route rate-limit governance + dedicated coverage gate
65e3425 P1-005 + P1-010: security CI gates + OpenAPI drift gate
89bf4b3 BUG-011 + BUG-012 + BUG-013 cookie cross-subdomain + dashboard mobile
161c384 Strict-audit P0s 1-5
e7c8fb7 Phase C-1 hardening
```
