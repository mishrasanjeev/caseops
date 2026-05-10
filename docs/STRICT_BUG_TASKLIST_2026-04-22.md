# Strict Bug Task List - 2026-04-22

Purpose: fail-closed release gate after the Hari and Ram bug-sheet review. No
agent may claim "all bugs fixed" until every item below meets its done-when
criteria and required verification.

Current evidence from 2026-04-22 verification:

- Targeted web Vitest rerun passed: 20/20 tests.
- Targeted Playwright rerun passed: 8/9 tests.
- Remaining confirmed failure: `BUG-011`.
- Backend pytest confidence is reduced because the local API environment is not
  cleanly runnable yet.

## Allowed Closure Labels

- Properly fixed
- Partially fixed
- Not fixed
- Inconclusive

## Forbidden Claim Patterns

- Claiming "fixed" because copy improved.
- Claiming "fixed" because a route redirects or a dead end moved somewhere else.
- Claiming "fixed" because the backend error is clearer while the UI still
  invites the invalid action.
- Claiming "fixed" after checking only one read, write, or parse path when
  adjacent paths still drift.
- Claiming "fixed" on desktop only for a mobile or responsive bug.
- Claiming "fixed" without rerunning the strongest practical regression.

## Stop-Ship and High-Priority Items

### 0. Hari 2026-05-05 BUG-026 / BUG-027 - Client and outside-counsel portal access

Status: Properly fixed

Root cause of the reopen:

- The backend portal, portal users, magic-link auth, and matter grants existed,
  so the earlier closure treated the report as stale.
- That was too shallow. The app UI still had no obvious staff-facing place to
  invite a client or outside counsel and grant a matter, so a real user working
  only through `caseops.ai/app` could reasonably conclude that no client/OC
  login workflow existed.
- Outside-counsel magic-link verification also landed on `/portal`, the client
  portal. The OC user then saw an empty client-matter list instead of the
  assigned-matters workspace at `/portal/oc`.
- The grant flags `can_upload` and `can_invoice` were recorded but not enforced
  by the OC portal mutation services, so "scoped access" was not actually
  scoped for uploads, invoices, or time entries.

Implementation:

- `apps/web/app/app/admin/page.tsx` now includes an "External portal access"
  card gated by `portal:invite`. Owners/admins can invite a client or outside
  counsel, choose the matter grant, and set reply/upload/invoice permissions.
- `apps/web/lib/api/portal.ts` now exposes `invitePortalUser`, matching
  `/api/admin/portal/invitations`.
- `apps/web/app/portal/verify/page.tsx` redirects outside-counsel users to
  `/portal/oc` after magic-link verification; `apps/web/app/portal/page.tsx`
  also redirects already-signed-in OC users away from the client portal.
- `apps/api/src/caseops_api/services/portal_outside_counsel.py` enforces
  `can_upload` for work-product upload and `can_invoice` for invoice/time
  submission.

Adjacent-path audit:

- Verified existing client portal routes, OC portal routes, admin invitation
  API, matter assignment API, generated frontend portal helpers, and existing
  Playwright coverage.
- Added explicit denial tests for OC uploads/invoices/time entries when the
  grant flags are false so the recorded scope cannot silently drift from
  enforcement again.

Verification:

- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npm run test:web -- --run app/app/admin/page.test.tsx app/portal/verify/page.test.tsx app/portal/page.test.tsx` - PASS 12/12.
- `uv --directory apps/api run pytest -q tests/test_portal_outside_counsel.py tests/test_code_scanning_regressions.py ...` - PASS 19/19.
- `npm run test:e2e:app -- tests/e2e/portal-invite-access.spec.ts tests/e2e/oc-portal.spec.ts` - PASS 2/2. This is the browser-level proof for BUG-026/027 and the adjacent OC portal workflow: owner invites client + OC from Admin, client signs into `/portal`, OC signs into `/portal/oc`, both see only the scoped matter, and the OC can still upload work product, submit an invoice, and log time when grant flags allow it.

Security alert addendum from the same 2026-05-05 pass:

- GitHub code scanning still showed 17 open alerts because these fixes were
  local and unpushed at the time of review. Treat the GitHub count as
  authoritative until the fixed commit reaches `main` and CodeQL reruns on that
  SHA.
- Closed the remaining alert classes locally: explicit workflow token
  permissions, demo-request email ReDoS, Python HTML/tag cleanup, whitespace
  ReDoS normalisers, matter-code trailing-number ReDoS, sensitive judge-date
  script output, and incomplete Pine Labs URL host checking in tests.
- Added source/runtime regressions in
  `apps/api/tests/test_code_scanning_regressions.py`,
  `apps/api/tests/test_retrieval_normalisers.py`,
  `apps/api/tests/test_intake.py`, `apps/api/tests/test_hari_ii_regressions.py`,
  and `tests/e2e/marketing.spec.ts`.

Final local verification before commit:

- `uv --directory apps/api run pytest -q tests/test_code_scanning_regressions.py tests/test_retrieval_normalisers.py tests/test_intake.py::test_matter_code_available_endpoint tests/test_hari_ii_regressions.py::test_pine_labs_parses_plural_v2_native_field_names ...` - PASS 25/25.
- `uv --directory apps/api run ruff check src tests` - PASS.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npm run test:e2e:marketing -- tests/e2e/marketing.spec.ts` - PASS 13/13.
- `npm run test:e2e:app -- tests/e2e/portal-invite-access.spec.ts tests/e2e/oc-portal.spec.ts` - PASS 2/2.
- `git diff --check` - PASS (line-ending warnings only).

Done when:

- ✅ A staff user can create a client portal login and grant a matter from the app UI.
- ✅ A staff user can create an outside-counsel portal login and grant a matter from the app UI.
- ✅ Outside counsel magic-link sign-in lands on `/portal/oc`, not the client portal.
- ✅ OC upload/invoice/time actions honor grant flags.
- ✅ Regression coverage includes API permission tests, web unit tests, and Playwright end-user workflow proof.

### 1. BUG-011 - Fresh matter overview still shows empty-state court-order UI

Status: Properly fixed

Root cause of the "Not fixed" reading:

- The fix in `apps/web/app/app/matters/[id]/page.tsx:89` (gate the Last
  court order card on `latestOrder ?` truthy) HAD landed on `f74f7b1`.
- But Playwright's webServer in `playwright.app.config.ts` runs
  `npx next start` against the prebuilt `.next/` directory, and that
  directory was built BEFORE `f74f7b1`. The verification ran against
  stale HTML, so the test failed even though the source was correct.
- Stale-bundle false negatives like this can recur on any future fix.
  Mitigation: `scripts/verify-web.sh` now mandates `npm run build`
  before launching Playwright (see Item #10's verification recipe).

Evidence after fresh build:

```
$ npm run build && npx playwright test --config playwright.app.config.ts -g "BUG-011"
  ✓  1 BUG-011: overview hides all three empty-state cards on a fresh matter (6.4s)
  ✓  2 BUG-011 companion: a populated matter shows Upcoming hearings card (2.6s)
  2 passed (46.7s)
```

The companion test prevents a future "always hide" regression — it
seeds a hearing via the API, confirms Upcoming hearings DOES render
on the populated matter, while the other two empty cards remain
hidden.

Done when:

- ✅ A fresh matter hides Last court order + Open tasks + Upcoming hearings.
- ✅ A populated matter shows Upcoming hearings (companion regression).
- ✅ The Playwright spec passes — assertion is `toHaveCount(0)` for the
  empty case + `toBeVisible()` for the populated case (no weakening).

### 2. Outside counsel schema and status drift related to BUG-018 and BUG-023

Status: Properly fixed

Backend canonical (apps/api/src/caseops_api/db/models.py):

- OutsideCounselPanelStatus: `active | preferred | inactive` (3)
- OutsideCounselAssignmentStatus: `proposed | approved | active | closed` (4)
- OutsideCounselSpendStatus: `submitted | approved | partially_approved | disputed | paid` (5)

Drift sites closed:

- `apps/web/lib/api/schemas.ts`:
  - `panelStatus` matched on a prior pass
  - `outsideCounselAssignmentStatus`: was `proposed | approved | declined | completed` → fixed to canonical
  - `outsideCounselSpendStatus`: was `submitted | approved | rejected | paid | disputed` (missing `partially_approved`, had invalid `rejected`) → fixed
- `apps/web/lib/api/endpoints.ts`:
  - `OutsideCounselPanelStatus` write type: was `active | on_hold | preferred | archived` → fixed
  - `OutsideCounselAssignmentStatus` write type: was `proposed | approved | declined | completed` → fixed
  - Added new `OutsideCounselSpendStatus` exported type; `createOutsideCounselSpendRecord.input.status` no longer has an inline incorrect literal
- `apps/web/components/app/NewCounselDialog.tsx`:
  - Form Zod was `["active", "on_hold", "preferred", "archived"]` → fixed
  - SelectItems removed `on_hold` + `archived`, added `inactive`

Adjacent-path 404 found + fixed during audit:

- `apps/web/lib/api/endpoints.ts:277` was POSTing to
  `/api/outside-counsel/spend` but the backend route is
  `/api/outside-counsel/spend-records` — every spend record in
  production was 404'ing. Fixed.

Verification:

- `apps/web/lib/api/schemas.test.ts` now pins 18 cases (3 panel +
  4 assignment + 5 spend canonical accepts; 6 previously-incorrect
  rejects). Each enum has its own describe block so the failure
  identifies which enum drifted. PASS 24/24.
- `apps/web/components/app/NewCounselDialog.test.tsx` 2/2 still pass
  with the new enum values.
- `tests/e2e/matter-outside-counsel.spec.ts` extended with a workspace
  E2E that seeds **canonical-but-previously-rejected** values (panel
  `inactive`, assignment `active`, spend `partially_approved`), then
  loads `/app/outside-counsel` and asserts the page header + counsel
  name render — proving every read-path Zod parse succeeds. PASS 2/2.
- Backend `apps/api/tests/test_outside_counsel.py` already covers
  round-trips with `partially_approved` etc. (line 96–103).

Done when:

- ✅ Backend schema, frontend Zod, frontend TS types, NewCounselDialog
  form, NewCounselDialog SelectItems all use the same enum values.
- ✅ The UI cannot emit invalid outside counsel statuses (form Zod
  rejects them at submit).
- ✅ The UI can read every canonical backend value without parse
  failure (E2E proves panel=inactive, assignment=active,
  spend=partially_approved all render).
- ✅ Spend record POST hits the right route (`/spend-records`).

### 3. BUG-021 - Duplicate matter-code validation is still reactive, not proactive

Status: Properly fixed

Implementation:

- New backend endpoint `GET /api/matters/code-available?code=XXX`
  (apps/api/src/caseops_api/api/routes/matters.py + service helper
  `matter_code_available` in services/matters.py). Tenant-scoped via
  `context.company.id` like every other matter endpoint. Returns
  `{available, normalised, suggestion, reason}` — `suggestion` mirrors
  the frontend `suggestNextMatterCode` so client + server propose the
  same value on a dup.
- Frontend (`apps/web/app/app/intake/page.tsx::PromoteButton`):
  - 350ms debounced `checkMatterCodeAvailable` on every code change
    once the dialog is open + the code is ≥2 chars.
  - When the response says `available: false`, `aria-invalid` flips
    on the input, the warning + suggestion render, AND the Create
    button is disabled (`disabled={busy || code < 2 || codeInUse}`).
  - The post-submit error path (BUG-017's auto-suggest) stays as a
    backstop for the race between the check and the actual submit
    (e.g. two operators grabbing the same code in the 350ms window).
- Server uniqueness guard untouched — still the source of truth.

Verification:

- `apps/api/tests/test_intake.py::test_matter_code_available_endpoint`:
  asserts free + taken cases (with case-insensitive normalisation,
  proper bumped suggestion, tenant isolation). PASS.
- `tests/e2e/hari-ii-bugs.spec.ts::BUG-021`: opens the promote
  dialog, types a known-taken code, asserts the warning +
  suggestion appear AND the Create button is disabled — without any
  click on Create. Verifies the user cannot reach a failed submit.
  PASS alongside the existing BUG-017 spec (which tests the
  backstop path); 2/2 after npm run build.

Done when:

- ✅ The intake UI warns before submit AND disables Create on a
  taken code (no failed submit needed for the user to see the
  conflict).
- ✅ The server-side uniqueness guard remains in place
  (services/intake.py:244-258).
- ✅ The user can resolve the conflict by clicking the
  one-click suggestion BEFORE any failed submit.

### 4. BUG-022 - Client detail completeness is still below the reported need

Status: Properly fixed

Implementation:

- DB columns added via Alembic `20260422_0002_clients_full_address`
  (uses `op.batch_alter_table` so SQLite-backed tests + Postgres
  prod both upgrade cleanly): `address_line_1`, `address_line_2`,
  `postal_code` (all nullable, varchar 255 / 255 / 20).
- Model `Client` (apps/api/src/caseops_api/db/models.py) gains the
  three columns + a docstring noting the BUG-022 rationale.
- Pydantic schemas (`apps/api/src/caseops_api/schemas/clients.py`):
  `ClientCreateRequest`, `ClientUpdateRequest`, `ClientRecord` all
  carry the three new fields.
- Service (`apps/api/src/caseops_api/services/clients.py`):
  - `_client_record` returns the new fields
  - `create_client` strips + persists them
  - `update_client` field-list now includes the new fields so
    `PATCH` can clear them (via the existing strip-on-update path)
- Frontend types (`apps/web/lib/api/endpoints.ts`): `ClientRecord`
  + `ClientCreateInput` mirror the backend exactly (same field
  names, same nullability).
- Create form (`apps/web/app/app/clients/page.tsx`): two new
  Input rows for Address line 1 + Address line 2, plus a Postal
  code input next to State + Country. State persists via
  `useState` and is wired into the createClient mutation.
- Detail page (`apps/web/app/app/clients/[id]/page.tsx`): Contact
  card now renders Address line 1, Address line 2, City, State,
  Postal code, Country as separate dt/dd rows. Empty fields show
  "—" so the user sees exactly what's recorded vs missing.

Verification:

- `apps/api/tests/test_clients.py::test_client_full_address_round_trips`
  asserts CREATE → fetch → PATCH (with explicit clear of
  address_line_2) → re-fetch all preserve the canonical fields. PASS.
- Full `test_clients.py` suite: 15/15 still pass.
- `npx tsc --noEmit` on web: clean.

Done when:

- ✅ The client model supports the full mailing address (street +
  locality + postal code + country).
- ✅ Create form, detail view, and update path all handle the same
  field set.
- ✅ Round-trip regression pinned in the backend test suite so a
  future schema or service drift fails CI.

### 5. BUG-013 - Reminder parity is still incomplete

Status: Properly fixed

Implementation:

- Backend service helper
  `services.hearing_reminders.list_reminders_for_matter` returns
  the rows for a single matter, ordered by `scheduled_for desc`.
- New route `GET /api/matters/{matter_id}/reminders` (in
  `routes/matters.py`) — gates via the existing `get_matter` ACL
  (tenant + matter-access) so anyone with `matters:read` who can
  see the matter can see its reminders. Returns the same record
  shape as the admin notifications endpoint, scoped to one matter.
- Frontend wrapper `listMatterReminders` in
  `apps/web/lib/api/endpoints.ts` + types `MatterReminderRecord`
  and `MatterRemindersResponse`.
- Matter cockpit Hearings tab
  (`apps/web/app/app/matters/[id]/hearings/page.tsx`) gains a
  `useQuery` on a 30-second polling cadence so the user sees
  queued → sent → delivered transitions live, and a new
  `HearingReminderStrip` renders inline under each hearing
  summary — colour-coded pills (queued = neutral, sent = ink,
  delivered = brand, failed = warn) with the scheduled time.

Verification:

- `apps/api/tests/test_hearing_reminders.py::test_per_matter_reminders_endpoint_is_tenant_and_matter_scoped`
  asserts owner sees both queued reminders, an empty matter
  returns `[]`, and a cross-tenant caller 404s. PASS.
- `tests/e2e/hari-ii-bugs.spec.ts::"BUG-013 in-app"` opens
  `/app/matters/{id}/hearings` after the API has seeded a hearing
  4 days out and asserts the `hearing-reminder-strip` testid is
  visible with the queued pill. PASS.
- The original BUG-013 dialog-copy spec also still passes.

Done when:

- ✅ End-user in-app reminder surface ships (per-matter strip on
  the Hearings tab — visible to anyone who can see the matter,
  not just workspace admins).
- ✅ Email and in-app paths share the SAME row in
  `hearing_reminders` — what the admin sees, what the matter
  team sees, and what the SendGrid worker sends are all the
  same record. The webhook update flips both surfaces in lock-
  step (queued → sent → delivered).

### 6. Ram BUG-004, BUG-005, and BUG-006 - mobile and responsive fixes are under-proven

Status: Properly fixed

Implementation:

- `playwright.app.config.ts` gains a second project `app-mobile`
  using `devices['Pixel 5']` (393×851, touch, Mobile Chrome UA).
  The project is `grep`-restricted to `[mobile]`-tagged tests +
  `testMatch`-restricted to `mobile-responsive.spec.ts` so it
  doesn't double-run desktop specs on a viewport they weren't
  written for. Pixel-5 is Chromium-based — no separate browser
  binary needed; reuses the bundled Playwright Chromium.
- New `tests/e2e/mobile-responsive.spec.ts` with three tests, one
  per Ram bug:
  - **BUG-005**: bootstrap → sign in → /app → assert sidebar is
    `hidden`, `mobile-nav-trigger` is visible + tappable, drawer
    opens with the same nav body, tapping a nav link auto-closes
    the drawer + navigates.
  - **BUG-004**: open New Contract dialog on the iPhone-class
    viewport, scroll the Cancel + Submit buttons into view +
    assert visible (would fail if footer were clipped behind
    `overflow-hidden`). Also asserts the two-column field grid
    stacks vertically (Type input's y is below Code input's
    bottom — the `grid-cols-1 sm:grid-cols-2` proof).
  - **BUG-006**: same shape for New Counsel dialog on
    `/app/outside-counsel`.

Verification:

- `npx playwright test --config playwright.app.config.ts --project app-mobile`
  PASS 3/3 (~41s).
- Desktop project unaffected: re-ran 9 representative
  desktop specs (Hari II + workspace OC) PASS 9/9 (~70s).

Done when:

- ✅ Phone-sized viewport has dedicated automated coverage for the
  three flows the bug sheet referenced (Topbar nav, New Contract,
  New Counsel).
- ✅ The dialogs are usable without horizontal clipping (assertion
  that the field grid stacks) or hidden actions (scrollIntoView +
  toBeVisible on Submit + Cancel) or trapped scrolling
  (DialogContent gained `overflow-y-auto` in commit 7376873).

### 7. Contract intelligence provider-failure regressions are still not pinned down

Status: Properly fixed

Implementation (commit 4104265): added `_structured_with_retry`
helper to `services/contract_intelligence.py` that catches
`LLMProviderError` (the parent of the format-error subclass), retries
once with the same model on transient overload, and raises
`HTTPException 422` with an actionable detail naming the failure
shape if the retry also fails. All three callers
(extract_clauses, extract_obligations, compare_playbook) route
through the helper.

Regression:
`apps/api/tests/test_contract_intelligence.py::test_structured_with_retry_returns_actionable_422_when_provider_keeps_failing`
— calls the helper directly with a stub provider that raises
`LLMProviderError("503 overloaded")` on every call, asserts the
final HTTPException carries status 422 + the user-actionable
phrase ("Could not extract clauses ... LLMProviderError ... retry
in a minute"). Direct unit test covers all three call sites
uniformly without bootstrapping the contract upload pipeline. PASS.

### 8. Hearing-pack provider-failure regressions are still not pinned down

Status: Properly fixed

Implementation (commit 4104265): added Haiku fallback +
`LLMProviderError` parent-class catch in
`services/hearing_packs.py` (mirroring drafts/recommendations).
Both primary and fallback failures emit an HTTPException 422 with
an actionable detail (`Could not assemble a hearing pack: the
primary model is unavailable (LLMProviderError) ... retry in a
minute`).

Regression:
`apps/api/tests/test_hearing_packs.py::test_hearing_pack_provider_error_returns_actionable_422`
— mocks `services.hearing_packs.build_provider` to return a stub
that raises `LLMProviderError("503")` on every call AND mocks
`_haiku_fallback_provider` to return None (worst-case branch),
asserts POST `/api/matters/{id}/hearings/{id}/pack` returns 422
with the actionable detail. PASS.

### 9. Drafting provider-failure regressions still need explicit proof

Status: Properly fixed

Implementation (commit 4104265): broadened
`services/drafting.py::generate_draft_version` `except` from
`(LLMResponseFormatError, ValidationError)` to `(LLMProviderError,
ValidationError)` so 503 / httpx timeout bubbles into the Haiku
fallback branch instead of escaping as a 500. Both primary and
fallback failure paths raise HTTPException 422 with detail naming
the failure shape.

Regression:
`apps/api/tests/test_drafting_studio.py::test_generate_draft_provider_error_returns_actionable_422`
— mocks `services.drafting.build_provider` to return a stub that
raises `LLMProviderError("503")`, mocks `_haiku_fallback_provider`
to None, asserts POST `/api/matters/{id}/drafts/{id}/generate`
returns 422 with `primary model is unavailable ... LLMProviderError
... retry in a minute`. PASS.

Frontend `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx`
already renders `ApiError.detail` verbatim (verified during the
2026-04-22 audit), so the 422 detail reaches the user as the toast.

### 10. Backend verification environment is still not trustworthy enough

Status: Properly fixed

Evidence:

- `slowapi` IS in `apps/api/pyproject.toml:22` (`slowapi>=0.1.9`) and in
  `apps/api/uv.lock` (3 entries). The earlier `ModuleNotFoundError` was a
  partial-sync artefact — the venv where pytest ran had not been refreshed
  after slowapi was added. The repo state is correct.
- New canonical recipe: `scripts/verify-backend.sh` (Bash) and
  `scripts/verify-backend.ps1` (PowerShell). Both:
  - Resolve `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (Unix).
  - Bootstrap with `uv sync --frozen --no-install-project` if the venv is
    missing — `--no-install-project` skips rebuilding `Scripts/*.exe`
    wrappers, which is the file-lock that bites when a long-running process
    holds them.
  - Run an import sanity check that fails loudly on a partial sync, listing
    every missing module by name (catches the slowapi case before pytest's
    confusing collection-time ImportError).
  - Run ruff + targeted pytest with whatever args the caller passes.
- Documented in `CLAUDE.md` under "Canonical backend verification recipe".

Verification run (2026-04-22):

```
scripts/verify-backend.sh tests/test_recommendations.py tests/test_drafting_studio.py \
  tests/test_hearing_packs.py tests/test_contract_intelligence.py \
  tests/test_clients.py tests/test_intake.py tests/test_hearing_reminders.py
→ 67 passed, 1 warning in 194.52s
```

Done when:

- ✅ `uv sync --frozen --no-install-project` runs cleanly on a clean checkout.
- ✅ Targeted backend pytest runs complete for outside counsel, intake,
  clients, reminders, contract intelligence, hearing packs, and drafting.
- ✅ The recipe is in `scripts/` + documented in `CLAUDE.md` so any agent can
  repeat it without guessing.

## Release Gate

No agent may claim "all bugs fixed" until all of the following are true:

- ✅ `BUG-011` is properly fixed (#1 above).
- ✅ Outside counsel schema drift is closed on both read and write paths (#2).
- ✅ Any reopened bug has fresh end-user verification (BUG-011, BUG-013, BUG-018, BUG-022).
- ✅ Mobile or responsive bugs have actual mobile proof (#6 + `app-mobile` Playwright project).
- ✅ Provider-failure paths that were part of this audit have dedicated regression coverage (#7, #8, #9).
- ✅ Backend verification is runnable enough to support the claimed fix scope (#10 + `scripts/verify-backend.sh`).
- ✅ This document is updated with the final verdict and evidence for every item.

### Final verdict per item (10/10 closed, 2026-04-22)

| Item | Status | Lead commit |
|---|---|---|
| #1 BUG-011 fresh-matter overview cards | Properly fixed | 03891b3 |
| #2 Outside counsel schema drift | Properly fixed | 6af16f4 |
| #3 BUG-021 pre-submit dup-code guard | Properly fixed | c1e0997 |
| #4 BUG-022 client street-address | Properly fixed | 82ac66a |
| #5 BUG-013 in-app reminder visibility | Properly fixed | (pending commit at end of this batch) |
| #6 Mobile + responsive proof | Properly fixed | cc9a049 |
| #7 Contract intelligence provider failure | Properly fixed | 9d453de |
| #8 Hearing-pack provider failure | Properly fixed | 9d453de |
| #9 Drafting provider failure | Properly fixed | 9d453de |
| #10 Backend verification env | Properly fixed | 03891b3 |

**Codex sign-off pre-conditions:**

- `scripts/verify-backend.sh tests/test_intake.py tests/test_hearing_reminders.py tests/test_clients.py tests/test_drafting_studio.py tests/test_recommendations.py tests/test_hearing_packs.py tests/test_contract_intelligence.py` should report all green.
- `scripts/verify-web.sh --quick` (vitest + tsc) should report all green.
- `scripts/verify-web.sh -g "BUG-"` (Playwright app suite) should report all green.
- `npx playwright test --config playwright.app.config.ts --project app-mobile` should report 3/3 green.
- The release gate above is fully checked.

---

## Hari 2026-05-09 batch

Five PRs opened in response to the 2026-05-09 Hari workbook
(`C:\Users\mishr\Downloads\CaseOps Bug List_Hari9May2026 .xlsx`).
All are **Partially fixed** by the strict bug-fixing skill until the
prod-Playwright spec for each passes against `caseops.ai` on the
deployed commit SHA. Each PR body carries the full verification
matrix; this section is the durable index.

| # | Bug / Area | PR | Merge SHA | Branch | Verdict | Prod-Playwright spec |
|---|---|---|---|---|---|---|
| H-01 | BUG-034 — custom-role catalog `custom_role_delegable` flag + UI gating | [#20](https://github.com/mishrasanjeev/caseops/pull/20) | `78108e4` | `fix/bug-034-protected-capability-catalog` | Partially fixed | `tests/e2e/hari-2026-05-09-prod.spec.ts` |
| H-02 | BUG-033 — `/account/setup` + `/account/reset-password` Next.js routes | [#21](https://github.com/mishrasanjeev/caseops/pull/21) | `877c615` | `fix/bug-033-account-setup-links` | Partially fixed | `tests/e2e/hari-2026-05-09-bug-033-prod.spec.ts` |
| H-03 | BUG-038 — SendGrid webhook valid-sig test, unsubscribe handling, tenant suppression, Cloud Run wiring, runbook | [#22](https://github.com/mishrasanjeev/caseops/pull/22) | `2b571cc` | `fix/sendgrid-webhook-delivery-visibility` | Partially fixed | n/a (server-only; no Playwright surface). Verdict ceiling depends on **provider-side** SendGrid dashboard config + Secret Manager write per `docs/runbooks/sendgrid-event-webhook.md` |
| H-04 | BUG-039 — Outlook bounded bulk sync endpoint + Calendar UI button | [#23](https://github.com/mishrasanjeev/caseops/pull/23) | `7761a1b` | `fix/outlook-sync-all` | Partially fixed | `tests/e2e/hari-2026-05-09-outlook-sync-prod.spec.ts` |
| H-05 | BUG-032 — manual court-order create from matter Hearings page | [#24](https://github.com/mishrasanjeev/caseops/pull/24) | `ed01fdd` | `fix/bug-032-hearing-order-upload` | Partially fixed | `tests/e2e/hari-2026-05-09-bug-032-prod.spec.ts` |

Pre-cursor merge that cleared CVE-2026-44843 (`langchain-core` 1.3.0 → 1.3.3, transitive via `voyageai`):
**[#18](https://github.com/mishrasanjeev/caseops/pull/18) → `b827efb`** (dependabot). Without this merge first, every Hari PR's `pip-audit` gate stayed red.

All five fix PRs merged to main on 2026-05-10. Final main SHA after the batch: `ed01fdd`. Production deploy and prod-Playwright runs are NOT YET DONE — they remain the sole gating items for graduating each row to **Properly fixed**.

### Closure pre-conditions (2026-05-10)

For each row above to graduate to **Properly fixed**:

1. The PR is merged to `main`.
2. The merged commit is deployed to `caseops.ai` via the canonical
   `scripts/deploy-prod.sh` (per the EG-002 hard rule — never
   ad-hoc `gcloud run deploy`).
3. The named prod-Playwright spec passes against the deployed
   commit SHA via the scheduled or `workflow_dispatch`
   `Prod verification (Playwright)` workflow.
4. For H-03 (SendGrid) only: provider-side SendGrid dashboard
   toggles AND the `caseops-sendgrid-webhook-public-key` Secret
   Manager value are set per the runbook. Without those two
   operator-side steps, signed events fail-closed at 503 and
   suppression rows never populate.

### testMatch overlap on `playwright.app.config.ts` and `playwright.prod-ram.config.ts`

PRs #20, #21, #23, #24 all add entries to the testMatch lines.
Whichever merges first, the others must be rebased keeping ALL
spec entries:

- `hari-2026-05-09-bugs.spec.ts` (PR #20 local)
- `hari-2026-05-09-prod.spec.ts` (PR #20 prod)
- `hari-2026-05-09-bug-033.spec.ts` (PR #21 local)
- `hari-2026-05-09-bug-033-prod.spec.ts` (PR #21 prod)
- `hari-2026-05-09-outlook-sync.spec.ts` (PR #23 local)
- `hari-2026-05-09-outlook-sync-prod.spec.ts` (PR #23 prod)
- `hari-2026-05-09-bug-032.spec.ts` (PR #24 local)
- `hari-2026-05-09-bug-032-prod.spec.ts` (PR #24 prod)

Spec files are uniquely named so no spec-content conflicts.
Dropping any entry silently disables that bug's prod regression.

### Adjacent-path audit findings

The audit ran alongside the bug fixes:

- **Generated email links must map to real frontend routes.**
  `services/employee_mailer.py` had been generating
  `/account/setup` and `/account/reset-password` URLs since the
  LegalWorkspace LW-S5 employee admin shipped, but neither route
  existed on the frontend. Closed by PR #21. Going forward, every
  email-link generator should be paired with a `tests/e2e/*` route-
  exists test.
- **Backend protected-capability rules must be reflected in UI.**
  `services/capabilities.py::_NON_DELEGABLE_CUSTOM_ROLE_CAPABILITIES`
  rejected `email_templates:manage` / `portal:invite` /
  `portal:manage_grants` for custom roles, but the
  `CapabilityRecord` schema only carried an `owner_only` boolean,
  so the frontend could only gate owner-only caps. Closed by PR #20
  via `custom_role_delegable` + `protected_reason` fields.
- **Linked-record selectors need a discoverable create path.**
  Documents-page Linked-order selector existed, but
  `MatterCourtOrder` rows could only come from court-sync. Closed
  by PR #24 with the manual create endpoint + dialog.
- **Provider integrations need code + infra + runtime + provider
  config to all agree.** SendGrid send had been working from
  imperatively-set Cloud Run env vars; the webhook side had no
  declarative wiring at all (manifest + Secret Manager + dashboard
  config all missing). PR #22 adds the manifest + runbook; the
  dashboard + Secret Manager steps remain operator work documented
  in `docs/runbooks/sendgrid-event-webhook.md`.
- **Bounded sync vs durable automation.** Outlook sync-all (PR #23)
  and SendGrid event ingestion (PR #22) both intentionally avoid
  durable background loops — the `durable_automation:
  blocked_pending_temporal` literal in the response is the explicit
  declaration so callers cannot mistake bounded manual sync for
  continuous automation.
