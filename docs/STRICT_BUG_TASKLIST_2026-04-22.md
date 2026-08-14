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
| H-01 | BUG-034 — custom-role catalog `custom_role_delegable` flag + UI gating | [#20](https://github.com/mishrasanjeev/caseops/pull/20) | `78108e4` | `fix/bug-034-protected-capability-catalog` | **Properly fixed** | `tests/e2e/hari-2026-05-09-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |
| H-02 | BUG-033 — `/account/setup` + `/account/reset-password` Next.js routes | [#21](https://github.com/mishrasanjeev/caseops/pull/21) | `877c615` | `fix/bug-033-account-setup-links` | **Properly fixed** | `tests/e2e/hari-2026-05-09-bug-033-prod.spec.ts` (3/3 pass on prod `ec55dc2`, run 25628453223) |
| H-03 | BUG-038 — SendGrid webhook valid-sig test, unsubscribe handling, tenant suppression, Cloud Run wiring, runbook | [#22](https://github.com/mishrasanjeev/caseops/pull/22) | `2b571cc` | `fix/sendgrid-webhook-delivery-visibility` | **Partially fixed** — provider, runtime, and live ingestion all verified; only DB-side suppression-row proof outstanding | n/a (server-only). Runtime proof: `CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY` wired via `secretKeyRef name=caseops-sendgrid-webhook-public-key key=latest` on `caseops-api-00132-c6n` (image `:ec55dc2`); fail-closed verified — invalid + missing signatures both return 401 at canonical URL `https://api.caseops.ai/api/webhooks/sendgrid/events`. Provider proof (2026-05-10, Codex): SendGrid Event Webhook enabled in dashboard with all 6 required event types (`delivered`, `bounce`, `dropped`, `spam_report`, `unsubscribe`, `group_unsubscribe`) + `public_key_present: true`; SendGrid official webhook test API returned **HTTP 204** (settings id `c3d614d6-40fa-4db7-b295-c3e6cf44cd92`); Cloud Run logs show real `User-Agent: SendGrid Event API` POSTs to `/api/webhooks/sendgrid/events` returning **HTTP 200** (samples: `2026-05-10T15:42:14Z` 0.162s, `2026-05-10T15:40:03Z` 0.094s, `2026-05-10T15:35:17Z` 1.738s). Remaining caveat — sole reason for not graduating to Properly fixed: a database-side query showing a tenant-scoped `EmailSuppression` row written from a real production bounce/unsubscribe event. The 200 status is strong indirect evidence (the route handler writes the row before returning), but per the bug-fixing skill we hold the conservative verdict until the row is observed. |
| H-04 | BUG-039 — Outlook bounded bulk sync endpoint + Calendar UI button | [#23](https://github.com/mishrasanjeev/caseops/pull/23) | `7761a1b` | `fix/outlook-sync-all` | **Properly fixed** | `tests/e2e/hari-2026-05-09-outlook-sync-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |
| H-05 | BUG-032 — manual court-order create from matter Hearings page | [#24](https://github.com/mishrasanjeev/caseops/pull/24) | `ed01fdd` | `fix/bug-032-hearing-order-upload` | **Properly fixed** | `tests/e2e/hari-2026-05-09-bug-032-prod.spec.ts` (2/2 pass on prod `ec55dc2`, run 25628453223) |

Pre-cursor merge that cleared CVE-2026-44843 (`langchain-core` 1.3.0 → 1.3.3, transitive via `voyageai`):
**[#18](https://github.com/mishrasanjeev/caseops/pull/18) → `b827efb`** (dependabot). Without this merge first, every Hari PR's `pip-audit` gate stayed red.

URL-fix follow-up that corrected stale `https://api.caseops.ai/api/sendgrid/events` references in workbook + audit docs to the canonical `https://api.caseops.ai/api/webhooks/sendgrid/events`:
**[#26](https://github.com/mishrasanjeev/caseops/pull/26) → `ec55dc2`**. Application code unchanged; runbook was already correct.

All five fix PRs + #18 + #26 merged to main on 2026-05-10. Final main SHA: `ec55dc2`. Deployed to production via `scripts/deploy-prod.sh ec55dc2` (caseops-api revision `caseops-api-00132-c6n`, caseops-web revision `caseops-web-00121-278`, ClamAV sidecar present, health 200).

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
  blocked_pending_provider_approval` literal in the response is the explicit
  declaration so callers cannot mistake bounded manual sync for
  continuous automation.

## Hari 2026-05-11 batch — BUG-042 to BUG-048

Reported on `CaseOpsBugList_Hari11May2026.xlsx` (Downloads). Worktree branch
`worktree-hari-bugs-2026-05-11`, HEAD commit `91d31d1`. Local Playwright
proof in `tests/e2e/hari-2026-05-11-bugs.spec.ts` (9/9 PASSED). Prod
re-run required after `scripts/deploy-prod.sh`. Summary xlsx:
`C:\Users\mishr\Downloads\CaseOpsBugFixSummary_Hari11May2026.xlsx`.

| ID | Severity | Verdict | Spec | Notes |
|----|----------|---------|------|-------|
| BUG-042 | P2 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::185` | View order document button on hearings order list |
| BUG-043 | P2 | Properly fixed (local, client-side scope) | `hari-2026-05-11-bugs.spec.ts::213` | Search + hearing-filter on documents tab |
| BUG-044 | P1 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::245+261` | Outlook 409 → Connect Outlook pre-empt + actionable toast |
| BUG-045 | P2 | Properly fixed (local) — migration required at deploy | `hari-2026-05-11-bugs.spec.ts::286` | `matter_attachments.hearing_id` FK + UI |
| BUG-046 | P2 | Stale report | `hari-2026-05-11-bugs.spec.ts::351` | BenchStrategyPanel already mounts at `apps/web/app/app/matters/[id]/page.tsx:100` |
| BUG-047 | P1 | Stale report | `hari-2026-05-11-bugs.spec.ts::371` | Role select ships in both create + edit dialogs |
| BUG-048 | P1 | Properly fixed (local) | `hari-2026-05-11-bugs.spec.ts::387+455` | Matter access admin panel on EditEmployeeDialog |

Adjacent gaps surfaced by the audit (NOT fixed in this batch — separate
tickets to be filed):

- **Upload-but-no-view (BUG-042 class).** `contracts/[id]/page.tsx:602-650`
  only renders View redline for DOCX; PDF/TXT contract attachments have no
  View affordance. Same pattern as BUG-042.
- **Raw `apiErrorMessage` on actionable failure (BUG-044 class).** Five
  highest-value sites where the toast should pre-empt or render an actionable
  CTA: documents upload 422, contracts upload 422, draft create 429/422,
  court-sync 400 (no live adapter), calendar visible-range sync 401/403.
- **Backend exists, no admin UI (BUG-048 class).** `services/custom_roles.py`,
  `services/notification_rules.py`, `services/conflict_checks.py` all ship
  REST routes but have no admin page; admins must run SQL to use them.

## Hari 2026-05-31 batch (BUG-042 reopen, BUG-043, BUG-049)

Full writeup + runbook: `docs/BUG_FIX_HARI_2026-05-31.md`.

- **BUG-042 (P1, reopened) — Partially fixed.** Root cause is a deploy/credential
  seam, not missing code: Secret Manager has no `caseops-ecourtsindia-api-token`
  (api-service.yaml references it → deploy would fail), and the search UI failed
  silently on 0-results / provider errors. Fixed UI legibility (verbatim error +
  empty-state) and locked the adapter contract. LIVE search = Inconclusive pending
  token (Runbook A) + automation deploy (Runbook B).
- **BUG-043 (P2) — Partially fixed.** Bookmark + poll→in-app-notification already
  exist and are tested; the nightly poll Cloud Run job + scheduler were committed
  as YAML but never deployed. Automation = Inconclusive pending Runbook B (and the
  eCourts token).
- **BUG-049 (P2) — Partially fixed.** "Inputs unreliable" = silent-failing
  create/run/source-sync mutations (now render verbatim errors); create→persist
  verified. Nightly PRS sync job + scheduler committed but never deployed
  (token-free) → Inconclusive pending Runbook B.
- **Adjacent class confirmed:** only `caseops-ecourtsindia-api-token` is missing of
  all cloudrun secretKeyRefs; no app/app page-level mutation lacks an error surface
  after this batch. Proof: vitest (3 new), Playwright `hari-2026-05-31-bugs.spec.ts`
  (4, PASSED), backend test_case_tracking.py + test_statutes_routes.py (42 PASSED).

---

## Hari 2026-06-24 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari24Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| BUG-001 | P1 High | Locally fixed | Matters / Add Matters / District Court forum selector | Valid reopened bug. The shallow all-state fallback was replaced with a scraped India.gov.in District Courts Contact Directory seed: 36 states/UTs, 724 scraped rows, 723 unique active district court catalog entries. The selector still provides typed uncatalogued fallback, but catalog-to-Other now clears inherited catalog metadata so district/court names are required. Strict verdict remains below `Properly fixed` until PR CI, merge, deploy, and production Playwright pass on the shipped commit. |

Regression evidence added:

- `apps/api/alembic/versions/20260624_0001_seed_india_gov_district_courts.py` - India.gov district court seed migration with scrape-count validation.
- `apps/api/src/caseops_api/scripts/seed_data/india_gov_district_courts.json` - scraped source snapshot: 36 states/UTs, 724 rows, 723 unique active courts.
- `apps/web/components/matters/ForumSelector.test.tsx` - India.gov state list, Assam fallback, and catalog-to-Other clearing behavior.
- `apps/web/components/app/NewMatterDialog.test.tsx` - New Matter creates uncatalogued Assam lower-court metadata only after district and court names are supplied.
- `apps/web/components/matters/MatterForumCard.test.tsx` - edit path preserves no-catalog/stale-catalog lower-court state/district/court metadata without resubmitting inactive catalog IDs.
- `apps/api/tests/test_legalworkspace_forum_selector.py` - backend exposes 723 active India.gov district courts and accepts uncatalogued lower-court metadata.
- `tests/e2e/hari-2026-06-24-bugs.spec.ts` - browser workflow for all India.gov jurisdictions, Assam catalog rows, and fallback-required metadata.
- `tests/e2e/hari-2026-06-23-bugs.spec.ts` - prior Delhi regression updated to India.gov Delhi directory entries.

Local verification on 2026-06-24:

- `uv --directory apps/api run ruff check alembic/versions/20260624_0001_seed_india_gov_district_courts.py tests/test_legalworkspace_forum_selector.py` - PASS.
- `uv --directory apps/api run pytest tests/test_legalworkspace_forum_selector.py` - PASS 4/4.
- `npm run test:web -- ForumSelector.test.tsx MatterForumCard.test.tsx` - PASS 9/9.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-24-bugs.spec.ts --project app-chromium` - PASS 1/1.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-23-bugs.spec.ts --project app-chromium` - PASS 1/1.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-24_HARI.md`.

---

## Hari 2026-06-26 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari26Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Locally fixed | Research / Context Research | Valid bug. Prior UI-only garbled-preview masking was shallow. Retrieval now penalizes low-quality OCR text and the authority route orders readable results ahead of garbled OCR before pagination. Production verdict remains below `Properly fixed` until committed Playwright passes against the deployed build. |
| bug-002 | Low | Locally fixed | Matters / New Matter | Valid bug. Matter Code now has a shared backend grammar and frontend grammar: uppercase letters, numbers, and hyphens only; spaces, underscores, slashes, and other special characters are rejected. Direct matter create, availability, intake promotion, and New Matter UI are covered. Production verdict remains below `Properly fixed` until committed Playwright passes against the deployed build. |

Regression evidence added:

- `apps/api/src/caseops_api/services/retrieval.py` - OCR readability classifier and rank penalty.
- `apps/api/src/caseops_api/services/authorities.py` - readable authority results are ordered ahead of low-quality OCR before pagination.
- `apps/api/src/caseops_api/schemas/matters.py` - shared backend Matter Code grammar and normalization.
- `apps/api/src/caseops_api/schemas/intake.py` - intake promotion reuses the same grammar.
- `apps/api/tests/test_authorities.py` - contextual cheque dishonour search ranks readable Section 138/142 authority ahead of a matching garbled OCR authority.
- `apps/api/tests/test_matter_code_validation.py` - invalid Matter Code rejected by create, availability, and intake promotion paths.
- `apps/web/lib/matter-code.ts` - shared frontend Matter Code grammar.
- `apps/web/components/app/NewMatterDialog.test.tsx` - New Matter rejects invalid code before submit.
- `apps/web/app/app/intake/page.test.tsx` - Intake promotion rejects invalid code before availability check or submit.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` - Playwright workflow for Context Research and New Matter validation.
- `playwright.app.config.ts` - June 26 Playwright regression registered in the normal app suite.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-26_HARI.md`.

---

## Hari 2026-06-27 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari27Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Locally fixed; formal production verdict Inconclusive | Research / Context Research | Valid reopened bug. The June 26 fix still allowed a garbled OCR authority card to occupy result slots when readable authorities existed. Authority search now suppresses low-quality OCR rows whenever readable results are available, while preserving damaged OCR as a last-resort fallback when no readable source exists. |
| bug-002 | Medium | Locally fixed; formal production verdict Inconclusive | Research | Valid bug. Draft filter controls are now separated from committed search criteria. Filter edits no longer auto-fire stale searches or disable the explicit Search action; keyword and contextual modes both submit the selected filters only when Search is clicked. |
| case-reopening audit | Medium | Locally fixed; formal production verdict Inconclusive | Matters / status lifecycle | Not a workbook row, but explicitly requested. Backend already normalizes legacy `closed` to `disposed`; added reload/read-back Playwright proof that a disposed matter remains disposed and aligned portfolio terminology to `Dispose`. |

Regression evidence added:

- `apps/api/src/caseops_api/services/authorities.py` - low-quality OCR authority rows are suppressed when readable authority results exist.
- `apps/api/tests/test_authorities.py` - readable Section 138 / Section 142 authority suppresses the matching garbled OCR authority; garbled OCR remains available only when it is the only match.
- `apps/web/app/app/research/page.tsx` - draft filter state is committed into `SearchCriteria` only on submit.
- `apps/web/app/app/research/page.test.tsx` - filter edits stay staged until Search is clicked, and garbled OCR result cards are hidden when readable results exist.
- `apps/web/app/app/matters/page.tsx` and `apps/web/app/app/matters/page.test.tsx` - portfolio lifecycle label uses `Dispose`.
- `tests/e2e/hari-2026-06-27-bugs.spec.ts` - browser proof for bug-001, bug-002 in keyword and contextual modes, and disposed-status persistence after reload.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` - prior OCR regression strengthened so it no longer preserves the shallow "bad card visible with placeholder" behavior.
- `playwright.app.config.ts` - June 27 Playwright regression registered in the normal app suite.

Local verification on 2026-06-27:

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/matters/page.test.tsx` - PASS, 11 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 4 tests.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-26-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_gba_law_office_prd.py::test_matter_status_closed_input_normalizes_to_disposed` - PASS, 1 test.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-27_HARI.md`.

---

## Hari 2026-06-29 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari29Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | Medium | Already fixed in current main; revalidated locally | Research / Context Research | Valid product symptom. Current `main` already suppresses low-quality OCR authorities when readable authorities exist, preserving damaged OCR only as last-resort fallback. No new code path was needed; the existing June 27 regression remains the anchor. |
| bug-002 | Medium | Locally fixed; formal production verdict Inconclusive | Research | Valid bug. UI promised `Court name contains`, but backend authority search used exact equality across multiple retrieval branches. Search now uses case-insensitive substring court filtering in the exact-name prefilter, pgvector probe/filtered CTE, fallback scan, and boost logic. |
| case-reopening audit | Medium | Process learning updated | Cross-product regression quality | No new matter-status defect was present in the workbook. Reopen cause here was shallow proof: prior bug-002 tests proved payload submission, not backend filter semantics. |

Regression evidence added:

- `apps/api/src/caseops_api/services/authorities.py` - shared court filter normalization and contains semantics across authority retrieval paths.
- `apps/api/tests/test_authorities.py` - seeded `Madras High Court` authority returned by partial `court_name: "madras"` for the workbook bail query.
- `apps/web/app/app/research/page.test.tsx` - partial `Madras` filter is submitted and returned `Madras High Court` result renders.
- `tests/e2e/hari-2026-06-29-bugs.spec.ts` - browser proof that the Research UI submits `Madras` and renders a matching `Madras High Court` result.
- `playwright.app.config.ts` - June 29 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-06-29_HARI.md` - root cause and permanent learning added.

Local verification on 2026-06-29:

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_authority_search_court_name_filter_is_case_insensitive_contains apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 3 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx` - PASS, 6 tests.
- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-29-bugs.spec.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 5 tests.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-29_HARI.md`.

---

## Hari 2026-06-30 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari30Jun2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| bug-001 | High | Locally fixed; formal production verdict Inconclusive | Matter Management / Matter Creation / eCourt Integration | Valid bug. Direct matter creation now auto-registers a matter-scoped case-tracking bookmark when case tracking is enabled/configured and the matter has a valid CNR or case number. The `/app/matters` New Matter dialog now captures and submits case number + CNR; a backend-only fix would have left the reported UI path broken. |
| case-reopening audit | High | Process learning updated | Cross-product regression quality | Reopen cause was shallow proof: prior eCourt work tested manual sync/bookmark flows, not the matter-create lifecycle invariant. |

Regression evidence added:

- `apps/api/src/caseops_api/services/case_tracking.py` - reusable bookmark upsert and matter-create auto-link helper.
- `apps/api/src/caseops_api/services/matters.py` - direct create path calls the helper and records auditable auto-link metadata.
- `apps/web/components/app/NewMatterDialog.tsx` - New Matter UI captures case number and CNR.
- `apps/api/tests/test_case_tracking.py` - configured auto-link, disabled-provider non-blocking create, support-matrix-blocked non-blocking create.
- `apps/web/components/app/NewMatterDialog.test.tsx` - UI submits case identity fields.
- `tests/e2e/hari-2026-06-30-bugs.spec.ts` - browser workflow creates the matter from `/app/matters` and verifies Case Tracking contains the linked CNR/case.
- `playwright.app.config.ts` - June 30 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-06-30_HARI.md` - root cause and permanent learning added.

Local verification on 2026-06-30:

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/case_tracking.py apps/api/src/caseops_api/services/matters.py apps/api/tests/test_case_tracking.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_case_tracking.py` - PASS, 11 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_audit_events.py` - PASS, 6 tests.
- `npm --prefix apps/web test -- components/app/NewMatterDialog.test.tsx` - PASS, 10 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-30-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 1 test.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-06-30_HARI.md`.

---

## Hari 2026-07-02 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari02Jul2026.xlsx`.

| ID | Severity | Verdict | Area | Notes |
|----|----------|---------|------|-------|
| BUG-001 | High | Locally fixed; formal production verdict Inconclusive | Research / Context Search | Valid reopened bug. Context Research must not render corrupted authority title, summary, or snippet text. Authority search now omits unreadable preview records entirely and returns an explicit omitted-record notice when the only matches are unreadable. |
| BUG-00X | High | Locally fixed; formal production verdict Inconclusive | Matter Management / Matter Details | Valid enhancement/bug. Notice documents already existed as attachment metadata, but the matter cockpit did not expose a Notice workflow. Matter details now include a Notices tab with notice-only listing and notice-classified upload. |
| case-reopening audit | High | Process learning updated | Cross-product regression quality | Reopen cause was shallow OCR proof: previous fixes preserved a corrupted last-resort path and did not test the exact screenshot-shaped corpus path through the real API and browser route. |

Regression evidence added:

- `apps/api/src/caseops_api/services/retrieval.py` - screenshot-shaped ASCII OCR fragment detection.
- `apps/api/src/caseops_api/services/authorities.py` - unreadable authority card suppression, readable-result backfill before final limit slicing, and contextual omitted-record coverage notice.
- `apps/api/tests/test_authorities.py` - API proof that the exact July 2 corrupted cheque dishonour authority is omitted when no readable preview exists.
- `apps/web/app/app/research/page.tsx` - defense-in-depth unreadable result filter and empty-state notice.
- `apps/web/app/app/research/page.test.tsx` and `apps/web/app/app/research/isGarbledSnippet.test.ts` - UI and detector proof for the July 2 OCR shape.
- `apps/web/components/app/MatterCockpitNav.tsx` - Notices tab registered in the matter cockpit.
- `apps/web/app/app/matters/[id]/notices/page.tsx` - notice-only list, summary counters, and notice-classified upload workflow.
- `apps/web/app/app/matters/[id]/notices/page.test.tsx` - notice listing and upload metadata regression.
- `tests/e2e/hari-2026-07-02-bugs.spec.ts` - browser proof for Context Research corrupted-content omission and Matter Notices upload.
- `playwright.app.config.ts` - July 2 Playwright regression registered in the normal app suite.
- `docs/BUG_REOPEN_LEARNINGS_2026-07-02_HARI.md` - root cause and permanent learning added.

Local verification on 2026-07-02:

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/retrieval.py apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_omits_corrupted_authority_when_no_readable_preview_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/research/isGarbledSnippet.test.ts "app/app/matters/[id]/notices/page.test.tsx"` - PASS, 13 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-07-02-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-07-02-bugs.spec.ts --project app-chromium` - both browser tests passed, then the command hit a Windows web-server teardown timeout; the no-webserver replay above is the clean exit-code evidence.

Reopen learning: `docs/BUG_REOPEN_LEARNINGS_2026-07-02_HARI.md`.

## Hari 2026-07-03 Matter Management Reopen Rules

- `BUG-003`: Matter edit is not fixed by an API route alone. The reported matter page must expose an editor, persist title/code/parties/case identifiers/status/forum/court/summary fields, reject duplicate matter codes, and show the corrected values after save.
- `BUG-004`: Multi-document download must be a selected-document ZIP workflow with tenant/matter scoping, deterministic archive names, row selection UI, selected count, browser download proof, and cross-tenant denial coverage.
- `BUG-005`: Notice upload must capture notice source, notice subject/about, date received, and reply/response as durable schema fields. The Notices page must display those facts, not only the uploaded filename.
- Every Hari workbook fix must update API schema/service tests, React UI tests, and a registered Playwright spec for the exact reported page flow.
- Do not mark a workbook item production-fixed until the deployed build has been re-tested with the supplied tester credentials or an explicitly created local equivalent when deployment has not occurred.

---

## Ram 2026-07-15 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram15Jul2026.xlsx`.
Detailed root-cause record:
`docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`.

| ID | Severity | Classification | Formal verdict | Scope |
| --- | --- | --- | --- | --- |
| BUG-001 | Medium | Valid product enhancement | `Properly fixed` for the deployed July 15 scope; reconciled 2026-07-22 | Standalone tenant-wide Notice Management from main navigation; create received/sent notices independently with zero or multiple matter links, search/filter/assign/track, and retain secure file handling plus legacy matter-notice visibility. |
| BUG-002 | Medium | Valid workflow/policy enhancement | `Properly fixed` for the deployed July 15 creation-only scope; superseded by the July 22 policy | New matters default to Active and direct Active creation is allowed without mandatory conflict clearance. The historical July 15 contract retained the explicit Intake/On-hold activation gate; that clause is no longer current. |
| Lifecycle adjacent defect | High | Valid systemic defect | `Properly fixed` for the deployed July 15 lifecycle scope; conflict-gate clause superseded July 22 | Explicit terminal state machine, optimistic concurrency, dirty metadata PATCH, reason/capability/audit, reopen to Intake with prior clearance retained as historical evidence, and post-disposal operational/background guards. |

Pre-change production reproduction on the `legal` tester tenant:

- authenticated login succeeded;
- main navigation exposed zero Notice links and `/app/notices` returned 404;
- direct Active matter create returned 409 with the mandatory
  Intake/conflict-clearance message;
- generic Disposed PATCH returned 200 and read back as Disposed, demonstrating
  persistence but not protection from stale or background writers.

Required closure evidence for this batch:

- API tests for Notice independence/multi-link/security, Active create policy,
  lifecycle transition matrix/concurrency/side effects;
- React tests for the global Notice workflow, Active default, dirty-field edits,
  and explicit Dispose/Reopen actions;
- registered `tests/e2e/ram-2026-07-15-bugs.spec.ts` local proof;
- registered `tests/e2e/ram-2026-07-15-prod.spec.ts` deployed proof;
- exact deployed commit/build identity paired with each final verdict.

The rows above were reconciled on 2026-07-22 with the deployment and production
Playwright evidence recorded in `docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`.
That historical evidence does not close the newer July 22 policy.

Historical local-candidate evidence captured before the later July 15
deployment, with final regression shards completed on 2026-07-16:

- complete 2,120-test API inventory collected and covered through three
  disjoint product-final-tree shards: 2,089 passed, 31 environment-gated skips,
  and 0 outstanding failures. One exact-text PG-001 documentation assertion
  exposed by the shards passed immediately after correcting only that ledger
  line. The 13 PostgreSQL-only tests executed separately on PostgreSQL 17;
  overlapping focused and shard run counts were not summed;
- fresh PostgreSQL 17 + pgvector suite: 13/13 passed after upgrade to head,
  including prior-revision legacy-child and provider-calendar tombstone repair;
- complete web suite: 115 files / 540 tests passed;
- Ruff lint across 490 in-scope Python files, TypeScript typecheck, optimized
  production build, strict dated-spec compilation, and single-head Alembic
  verification passed;
- `tests/e2e/ram-2026-07-15-bugs.spec.ts`: 3/3 passed against fresh local
  `legal` tenant data and the exact tester identity, using the production web
  build and no mocks;
- the complete run exposed and corrected three false-green patterns: dangling
  notification/custom-role foreign-key fixtures, legacy Matter PATCH callers
  missing mandatory CAS, and a test shortcut that created a terminal alias
  instead of using the lifecycle endpoint. Permanent controls now require valid
  parent fixtures, repository-wide mutation-call-site audits, and denial of
  terminal entry through create/import/generic PATCH;
- at that checkpoint, production execution was still pending. The later
  deployed-build identity and production Playwright closure are recorded in
  `docs/BUG_REOPEN_LEARNINGS_2026-07-15_RAM.md`; they close only that dated
  scope.

---

## Ram 2026-07-22 batch

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram22Jul2026.xlsx`.
Detailed root-cause record:
`docs/BUG_REOPEN_LEARNINGS_2026-07-22_RAM.md`.

| ID | Severity | Classification | Formal verdict | Scope |
| --- | --- | --- | --- | --- |
| BUG-001 | Medium | Valid workflow/policy enhancement, not a regression against the July 15 creation-only contract | `Properly fixed` on deployed `34f19ad` | Conflict review remains optional and auditable. Missing, pending, conflicted, cleared, waived, invalid, stale-scope, and pre-reopen results must not block creation or an Intake/On-hold to Active transition. |

Why the bug appeared to reopen:

- July 15 exempted direct matter creation but explicitly kept the later status
  gate. July 22 expands the contract to all activation paths.
- Exact 409 tests, UI recovery copy, lifecycle documentation, public copy, and
  helper fixtures fossilized the older invariant, so changing only one service
  branch would be another shallow fix.
- Cases themselves do not reopen accidentally: the dedicated, capability- and
  CAS-gated lifecycle endpoint is still the only Disposed-to-Intake path.

Required closure evidence:

- API matrix for Intake and On hold with no check plus pending, conflicted,
  stale-party-scope, and pre-reopen results; every transition must persist and
  emit no conflict-gate denial;
- conflict scan, candidate review, clear/conflict/waive, tenant/access,
  performance, and audit behavior still works independently;
- React proof removes blocking guidance while keeping the optional card usable;
- registered local and production July 22 Playwright specs exercise final
  read-back with the tester account/local equivalent; and
- exact deployed commit/build identity is paired with the passing production
  run before changing `Inconclusive` to `Properly fixed`.

Local candidate evidence captured on 2026-07-22:

- canonical backend verification passed Ruff plus all 59 tests in the affected
  conflict, lifecycle, intake, and import files;
- three focused React files passed 19 tests, TypeScript passed, and the
  64-route production Next.js build passed;
- the combined July 15 and July 22 local Chromium run passed 5/5 in 20.5s with
  the shared exact local tester identity. The July 22 spec passed 2/2: the
  no-check Intake case in 1.3s and the controlled
  Dispose -> Reopen -> Historical-cleared -> Active case in 2.1s, including
  lifecycle-version/CAS assertions and final reload persistence; and
- before deployment, the extended production spec authenticated as the
  supplied tester and reproduced the prior build's legacy HTTP 409. The second
  serial controlled-reopen case did not run, while `afterAll` emitted no
  cleanup failure;
- exact commit `34f19ad2bc0a5b48398144998cf546cc9e7a815a` was deployed to API
  revision `caseops-api-00210-fnv` and web revision
  `caseops-web-00189-k9f`, with registry/runtime digest equality and 100%
  traffic proved independently; and
- the committed July 22 production spec passed 2/2 with the supplied `legal`
  tester account. GitHub run `29929098217` then passed both cases on the
  independent QA tenant, the RAM batch (46 passed, four expected conditional
  skips), and the notice module (2 passed).

The formal production verdict is `Properly fixed`. See
`docs/runbooks/release-signoff-2026-07-22-34f19ad.md`.

## Ram 2026-07-28 product-boundary and deployed lifecycle audit

Source workbook: `C:\Users\mishr\Downloads\Enhancements_Ram28Jul2026.xlsx`.
Permanent learning record: `docs/BUG_REOPEN_LEARNINGS_2026-07-28_RAM.md`.

| ID | Classification | Verdict | Evidence / action |
| --- | --- | --- | --- |
| Workbook rows 1-3 | Valid-looking Edumatica work items, invalid for this CaseOps repository | `Inconclusive` / out of scope | The modules and external URL are absent from this repository. No CaseOps implementation was made for an unrelated product. |
| ADJ-REOPEN-2026-07-28 | Valid deployed CaseOps lifecycle defect or deployment drift | `Inconclusive` | Local lifecycle code and local API/Playwright regressions pass; deployed `tests/e2e/ram-2026-07-15-prod.spec.ts:676` accepted pre-reopen conflict clearance with HTTP 200 and reactivated the Matter. Deploy the candidate, prove build identity, and rerun the same spec. |
| ADJ-NOTICE-FILTER-2026-07-28 | Suspected transient production filter failure | `Inconclusive` | First production replay showed an empty combined filter result; the second replay passed and a direct authenticated production API probe returned the filtered record. Keep the existing notice regression and monitor; do not claim a code fix from one flaky observation. |

Why cases were reopening: previous local evidence was allowed to stand in for
deployed-build evidence. The exact production lifecycle journey still allowed
old conflict clearance to reactivate a reopened Matter. This audit does not
upgrade the production verdict until the corrected candidate is deployed and
the dated production spec passes on a provable build.

## CaseOps BUG-001 — Ram 2026-07-28 Judge Aliases navigation

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bugs_Ram28Jul2026.xlsx`.

| ID | Classification | Formal verdict | Evidence / action |
| --- | --- | --- | --- |
| BUG-001 | Valid CaseOps UI/navigation bug | `Properly fixed` | `apps/web/components/app/Sidebar.tsx` now exposes `/app/admin/judge-aliases` with the `workspace:admin` capability gate. Local `tests/e2e/ram-2026-07-28-bugs.spec.ts` passed 1/1 and deployed `tests/e2e/ram-2026-07-28-prod.spec.ts` passed 1/1 on web candidate `7495bc6`, Cloud Run revision `caseops-web-00191-vn9`, 100% traffic. |
| DEPLOY-GATE-2026-07-28 | Valid adjacent release blocker | `Inconclusive` | `caseops-migrate-job-7mmw2` failed before API rollout because production references absent Alembic revision `20260723_0001`. The web-only fix was deployed; API traffic was not changed. |

The previous shallow failure pattern was also present in this row's shape: the
route and Admin landing-page link existed, so a direct-URL or page-only test
could pass while the actual main navigation remained broken. The regression now
starts at the shared desktop/mobile navigation primitive and proves the loaded
destination. The summary workbook records the item-level fix separately from
the release-level migration blocker.

## CaseOps BUG-001..004 — Ram 2026-08-14 Bulk Matter Upload

Source workbook: `C:\Users\mishr\Downloads\CaseOps_Bug_list_Ram14Aug2026.xlsx`.
Summary workbook: `C:\Users\mishr\Downloads\CaseOps_Bug_list_Ram14Aug2026_BugFixSummary.xlsx`.
Permanent learning record: `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md`.
Fix commit: `6db34b64` (deployed) on `claude/bulk-import-ram-20260814`, PR #222.

| ID | Classification | Formal verdict | Evidence / action |
| --- | --- | --- | --- |
| BUG-001 | Valid CaseOps import/validation bug | `Properly fixed` | Forum values outside the alias tables leaked the raw pydantic Literal error to the user. Aliases expanded and unsupported values now return an actionable message. `tests/e2e/ram-2026-08-14-prod.spec.ts:286` PASSED on deployed `6db34b64` (rev `caseops-api-00289-l9g`); prod matter `RAM814-FAM` stored `forum_level=lower_court`. |
| BUG-002 | Valid CaseOps import/validation bug | `Properly fixed` | Bulk import was stricter than manual creation for the identical object; proved on production that `POST /api/matters/` accepted `tribunal` + free-text "DRT Delhi" while bulk rejected it. Categories now fail open to the canonical level, with scoped token matching retaining lineage on match. `tests/e2e/ram-2026-08-14-prod.spec.ts:286,352` PASSED on `6db34b64`. |
| BUG-003 | Valid, reported one layer off | `Properly fixed` | Duplicates were already excluded from creation; the defect was classifying them `invalid`. New `duplicate` row status is skipped and excluded from `validation_error_count`/`failed_count`, first-occurrence-wins so the original still imports. `tests/e2e/ram-2026-08-14-prod.spec.ts:409` PASSED on `6db34b64`. |
| BUG-004 | Valid in part | `Properly fixed` | Header aliases accepted a bare name column while resolution was email-only. Owner/lawyer now resolve by unique full name too; ambiguous names rejected, not guessed. `tests/e2e/ram-2026-08-14-prod.spec.ts:467` PASSED on `6db34b64`. |
| ADJ-TEAM-SCOPING-2026-08-14 | Not a defect | n/a | "Matter owner must belong to the assigned team" also fires on manual creation (`services/matters.py:1376`). It is a scoping control; only the message was made actionable. Deliberately not weakened. |
| ADJ-DEPLOY-COLLISION-2026-08-14 | Valid release-process defect (self-inflicted) | `Properly fixed` | Deploying migration-bearing `6db34b64` from an unmerged branch applied `20260814_0001` to production and failed the concurrent `f24d5aff` migrate job (`caseops-migrate-job-2kg2t`) with `Can't locate revision identified by '20260814_0001'`. Resolved by merging PR #222 so the revision rejoins the chain. `alembic_version` was never hand-edited. |

Why this case reopened: the 2026-08-11 prevention rule 5 specified strictness
in one direction only and was implemented as a three-family allowlist, making
bulk import stricter than the manual path it was meant to match. That rule is
now annotated as superseded in place. Two structural guards close the class:
`test_bulk_import_is_never_stricter_than_manual_creation` and
`test_every_forum_the_template_offers_can_actually_be_imported`.
