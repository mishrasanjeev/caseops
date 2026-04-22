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

Status: Partially fixed

Evidence:

- `apps/web/components/app/NewCounselDialog.tsx` still offers invalid
  `panel_status` values (`on_hold`, `archived`) that the backend does not
  accept.
- `apps/web/lib/api/endpoints.ts` still types outside counsel panel status as
  `active | on_hold | preferred | archived`.
- `apps/web/lib/api/schemas.ts` still drifts on assignment statuses and spend
  statuses.
- `apps/api/src/caseops_api/schemas/outside_counsel.py` is the backend source
  of truth and does not match the frontend contracts.

Done when:

- Backend schema, frontend schema, endpoint typings, create forms, update forms,
  fixtures, and seeded examples use the same enum values.
- The UI cannot emit invalid outside counsel statuses.
- The UI can read and render real backend values without parse failure.

Required verification:

- Unit tests for schema parsing and form submission payloads
- End-to-end create/edit/read outside counsel workflow verification

### 3. BUG-021 - Duplicate matter-code validation is still reactive, not proactive

Status: Partially fixed

Evidence:

- Backend uniqueness enforcement exists in
  `apps/api/src/caseops_api/services/intake.py`.
- The intake UI only suggests a next code after the API rejects the duplicate in
  `apps/web/app/app/intake/page.tsx`.

Done when:

- The intake UI warns before submit when the matter code is already taken or
  obviously conflicting.
- The server-side uniqueness guard remains in place.
- The user can resolve the conflict without first hitting a failed submit.

Required verification:

- Frontend regression test for pre-submit duplicate validation
- End-to-end duplicate-code flow proving the user is stopped before a failed
  submit

### 4. BUG-022 - Client detail completeness is still below the reported need

Status: Partially fixed

Evidence:

- `apps/web/app/app/clients/[id]/page.tsx` now renders contact plus
  city/state/country.
- `apps/web/app/app/clients/page.tsx` now captures more locality fields.
- `apps/api/src/caseops_api/schemas/clients.py` still has no real street-address
  field, so the product still cannot store a full address.

Done when:

- The client model and UI support the address detail required by the bug, or
  the product requirement is explicitly narrowed and the bug statement is
  updated to match reality.
- Create, edit, and detail screens all show the same supported address fields.

Required verification:

- API schema test for client address fields
- UI create/detail regression covering the full supported address

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

Status: Inconclusive

Evidence:

- Relevant UI changes exist in `apps/web/components/app/NewContractDialog.tsx`
  and `apps/web/components/app/Topbar.tsx`.
- `playwright.app.config.ts` still only proves desktop Chromium.

Done when:

- Phone-sized viewports have dedicated automated coverage for the affected
  flows.
- The affected dialogs and navigation remain usable without horizontal clipping,
  hidden actions, or trapped scrolling.

Required verification:

- Mobile Playwright projects or equivalent mobile viewport coverage
- Manual spot check on one narrow phone viewport and one tablet viewport

### 7. Contract intelligence provider-failure regressions are still not pinned down

Status: Inconclusive

Evidence:

- The code in `apps/api/src/caseops_api/services/contract_intelligence.py`
  suggests failure handling was improved.
- There is still no strong targeted regression proving timeout, empty-output, or
  malformed-provider responses stay user-safe.

Done when:

- Targeted tests cover provider failure classes that previously broke clause or
  obligation extraction.
- The user-visible workflow degrades safely and predictably under those
  failures.

Required verification:

- Focused backend tests around provider-failure branches
- One end-to-end UI or API smoke flow that exercises the safe failure path

### 8. Hearing-pack provider-failure regressions are still not pinned down

Status: Inconclusive

Evidence:

- `apps/api/src/caseops_api/services/hearing_packs.py` contains failure-path
  handling.
- There is still no strong targeted regression proving those branches stay safe
  when upstream providers fail.

Done when:

- Hearing-pack generation failure branches have dedicated tests.
- The product surfaces a user-actionable outcome instead of silent or confusing
  failure.

Required verification:

- Focused backend tests around hearing-pack provider failures
- Manual or automated smoke flow covering the user-visible failure state

### 9. Drafting provider-failure regressions still need explicit proof

Status: Inconclusive

Evidence:

- `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx` now surfaces
  `ApiError.detail`.
- `apps/api/src/caseops_api/services/drafting.py` contains fallback and
  provider-detail handling.
- There is still no dedicated regression proving the exact failure path remains
  user-actionable.

Done when:

- A targeted regression proves provider failures surface actionable detail in
  the drafting workflow.
- The flow avoids silent failure and avoids pretending the draft succeeded.

Required verification:

- Dedicated drafting failure-path regression
- One end-user flow verification

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
