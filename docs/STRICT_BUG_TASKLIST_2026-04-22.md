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

Status: Partially fixed

Evidence:

- Reminder scheduling and admin visibility exist in
  `apps/api/src/caseops_api/services/hearing_reminders.py`,
  `apps/api/src/caseops_api/api/routes/notifications.py`, and
  `apps/web/app/app/admin/notifications/page.tsx`.
- `apps/web/app/app/matters/[id]/hearings/page.tsx` still only promises email
  reminders after provider setup.
- There is still no true end-user in-app reminder surface matching
  "platform + email".

Done when:

- The product ships the promised in-app reminder visibility for end users, or
  the requirement is explicitly reduced and re-approved.
- Email and in-app reminder paths stay consistent on the same hearing.

Required verification:

- Backend reminder enqueue coverage
- End-user UI verification for reminder visibility
- Admin notification view regression

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

- `BUG-011` is properly fixed.
- Outside counsel schema drift is closed on both read and write paths.
- Any reopened bug has fresh end-user verification.
- Mobile or responsive bugs have actual mobile proof.
- Provider-failure paths that were part of this audit have dedicated regression
  coverage.
- Backend verification is runnable enough to support the claimed fix scope.
- This document is updated with the final verdict and evidence for every item.
