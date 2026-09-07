# Bug Reopen Learnings — Hari 2026-05-09 sweep

## September 07 Statute Reopen Analysis

BUG-010 reopened because prior acceptance confused a correctly disabled source
with a usable Act and relied on positive Constitution fixtures instead of the
reported catalogs. The repair must reconcile full official inventories, source
identity, text, publisher footnotes, inserted/omitted entries and actual
attach/detail/reload behavior. A new deterministic fixture alone is insufficient.
Published editions can contain arrangement/body errors or retain text affected
by a judgment; preserve those discrepancies and fail closed instead of claiming
all printed provisions are operative current law. Repeated seeding must retain
reviewed provenance and source history without fabricating a new link check.
The current implementation and unfulfilled release proof are recorded in
`ip-implementation/evidence/bug010-source-release-2026-09-07.md`.

September 07 browser review found three test-assumption failures after genuine
source admission. Nonselectable counts do not distinguish pending, retired and
quarantined provisions. Inspect the exact state. A canonical guarded source
action is not a broken external link: prove browser-cookie authorization,
audited redirect and exact official destination without bypassing it. Inspect
each structured failure and rerun serial siblings as well as the whole gate.
Use width/run-specific fixture identities so a passing prior journey cannot
cause a later duplicate collision. Production reuse needs exact-release checks,
dedicated QA authentication and no local database setup helpers on live data.

A durable learning doc covering the five bugs / operational areas
landed in PRs #20, #21, #22, #23, #24. Anchored on the Hari workbook
`C:\Users\mishr\Downloads\CaseOps Bug List_Hari9May2026 .xlsx`.

The point of this doc is **not** to recap the fixes (the strict
bug tasklist + each PR body do that). The point is to record
**why each of these defects shipped in the first place**, in
patterns concrete enough that the next audit can grep for the
same shape and catch new instances before they ship.

---

## September 07: Implicit Tenant Locks Are Part Of The Protocol

The same day's complete acceptance also exposed test-boundary errors. Party
browser tests saved a portfolio URL before navigation committed, or clicked
the family's Parties tab while the application route was pending. All six
failed. Explicit destination URL and record-heading assertions now precede
nested actions; the complete 13-journey replay passes against unchanged exact
Docker images, including closed-history reload and rejected terminal writes.
No product guard or timeout was relaxed. The family/application intake tests
already awaited navigation and were retained unchanged.

The original frontend run retained seven failures. Resource-controlled diagnosis
isolated a cold, expensive accessible-role loading poll. Polling the exact h2
text and then asserting its accessible heading and visibility preserves the
original deadline. The complete 899-test suite passes with that sole test
change. A targeted pass alone was not used to dismiss the original failures.
The full API run separately found a route-inventory false positive for four
real tested paths assembled through URL prefixes. Those paths are now explicit
in executed HTTP assertions, not unused strings or coverage exemptions. Exact
results, source identities and remaining release limits belong in the dated
local evidence record, not a blanket "all fixed" statement.

A new different-actor patent-party/closure PostgreSQL regression reproduced a
real deadlock. The waiting party command had inserted its idempotency claim,
which implicitly held Company KEY SHARE, before waiting on the source parent.
Closure owned that parent and later requested Company FOR UPDATE to advance
private epochs. Same-actor coverage could not expose this because the shared
membership lock serialized both commands earlier. This is local root-cause
evidence, not a retrospective diagnosis of every production alert.

The canonical private-authority fence now uses FOR NO KEY UPDATE; bootstrap
delegates to the same fence. It still serializes authority writers and blocks
deletion while allowing tenant FK checks. No retry, error suppression or
access/tombstone relaxation was added. Both family/application closure races,
three existing private-index overlap regressions and the full party PostgreSQL
selection pass (14 tests). Two additional regressions hold a real uncommitted
claim, prove authority progress, observe a second authority writer waiting,
prove deletion remains blocked, and verify one active generation. Fresh Docker
browser and production acceptance remain separate gates. References:
`test_ip_patent_party_postgres.py`, `test_private_authority_lock_postgres.py`,
and the existing private-index cases in `test_postgres_validation.py`.

Lock semantics: [PostgreSQL 17 row-level locks](https://www.postgresql.org/docs/17/explicit-locking.html#LOCKING-ROWS).

## September 06: Repeat Lifecycle Journeys Must Be Real

The old shared IP regression closed a docket and reopened it on a later day.
It did not close the reopened docket again. The expanded patent Playwright
journey reproduced the actual gap at all three widths: calendar-date duplicate
matching rejected a distinct second closure. A one-time transition test was
insufficient proof of a repeatable operational flow.

The fix retains the dedicated parent command and optimistic lifecycle version;
it does not remove duplicate checks from trademark applications or opposition
proceedings. The prosecution conflict display must use the same parent-version
distinction. Generic root event routes may not invent a lifecycle fact. Close
and reopen also share the same explicit backdate blocker in preview, commit
and retained event evidence. Required regression: close/reopen/close on one
date, stale replay, unchanged state on rejection, no child resurrection, history
reload, PostgreSQL and 393/768/1280px browser proof. The failed first browser
artifacts and fresh acceptance are recorded in the September 06 IP checkpoint.

## L1 — Backend/component proof was treated as enough

**Pattern.** Pytest passed, vitest passed, the build succeeded,
the deploy returned exit code 0 — and we declared the bug fixed.
None of those touch the deployed surface a real user sees. The
bug-fixing skill has called this out repeatedly (see
`feedback_brutal_honest_testing_no_manual_qa.md`); we still keep
doing it.

**Why this batch fell into it.** All five bugs have backend +
component coverage today, but only one (BUG-032 court-order
manual create) had its entire user-visible workflow pre-flighted
end-to-end before the PR opened. The rest depended on the
prod-Playwright spec to catch a regression after deploy.

**Going forward.**
- Every PR carries its prod-Playwright spec discoverably named
  `*-prod.spec.ts` AND wired into both Playwright config files
  (`playwright.app.config.ts` for the local mirror,
  `playwright.prod-ram.config.ts` for the deployed run).
- The PR body's verdict is **Partially fixed** until the
  prod-Playwright spec passes against the deployed commit SHA.
  No "Properly fixed" before that proof exists. No exceptions.

## L2 — Email links generated for routes that do not exist

**Pattern.** A backend service generates a link with absolute
confidence — `f"{settings.web_base_url}/account/setup?token=..."` —
and ships. Months later, a real user clicks the link, gets the
Next.js 404 ("This page isn't on the matter graph"), and the bug
reopens as "we had broken auth flow the whole time."

**This batch.** BUG-033 — `/account/setup` and
`/account/reset-password` were referenced by `services/employee_mailer.py`
since the LegalWorkspace LW-S5 employee admin shipped, but neither
Next.js route existed. The mailer test harness asserted the link
TEXT, never that the URL resolves to a 200 on the web server.

**Going forward.**
- Every email-link generator (anything that puts a URL into a
  rendered email body) needs a paired `tests/e2e/*` route-exists
  test that GETs the path on the running web app and asserts
  the response is 200 (or the appropriate sign-in redirect, never
  a 404).
- Reverse the linter: a grep for `web_base_url` should be matched
  by a corresponding test that exercises the path.

## L3 — Backend authorization rules not represented in UI controls

**Pattern.** The backend has a hard rule (StrEnum, allow-list,
`require_capability` dependency, foreign-key check). The UI has
a free-text input or unfiltered checkbox list. The user submits
something the backend will reject, gets a generic 403 toast, and
files a bug.

**This batch.** BUG-034 — `services/capabilities.py` enumerated
non-delegable capabilities (`email_templates:manage`,
`portal:invite`, `portal:manage_grants`) and the custom-role
create endpoint rejected them with 403. The
`/app/teams/admin/roles/new` form rendered them as selectable
checkboxes anyway. The user could only discover the rule by
trying to submit. The fix is the structural one: the
`CapabilityRecord` schema now carries `custom_role_delegable` +
`protected_reason`, so the UI can disable the checkbox AND
explain why before submit.

**Going forward.**
- Every backend allow-list / non-delegable list / capability
  partition needs a parallel field on the catalog response so
  the UI can gate before submit.
- Every "rejected on submit" 4xx that maps to a static rule is
  a UX bug, not a backend bug. Hide or disable the control;
  do not rely on the toast.
- Frontend allow-lists mirroring backend enums always drift
  (`feedback_brutal_bug_fixing_2026_05_01.md` rule 4); derive
  the UI from the API schema, never hand-maintain a parallel
  enum on the frontend.

## L4 — Linked-record metadata existed without a complete create/upload workflow

**Pattern.** A schema field exists. A read path renders it.
A selector dropdown queries it. There is no create path. Users
can never populate it manually; the field stays empty for any
matter that hasn't had the upstream sync run.

**This batch.** BUG-032 — `MatterCourtOrder` rows existed and
the documents-page `LinkedOrderSelect` queried them, but the
only way to produce a row was court-sync. For matters that
hadn't run court-sync (every matter in a fresh tenant, every
matter in a forum we don't sync, every matter where the user
just wants to attach a manual order), the dropdown was
permanently empty. The fix adds the
`POST /api/matters/{id}/court-orders` endpoint + the
`AddCourtOrderDialog` mounted in two places on the matter
Hearings page (header + empty state).

**Going forward.**
- Every linked-record selector needs a discoverable inline
  create path (a "+ Add" button or a dialog from the empty
  state). The empty state is the audit hotspot — if it says
  "no records" without offering a create action, treat it as
  a defect.
- Do not rely on a single upstream sync as the only path to
  populate user-editable data.

## L5 — Provider integration was code-complete while runtime/provider config remained incomplete

**Pattern.** The code lands, `pytest` passes against a stubbed
provider, the PR closes. The infra manifest, the Secret Manager
value, and the provider-side dashboard config never get done.
The first real provider event hits the endpoint, the verifier
returns 503 (no public key), and the entire audit trail of
bounces / unsubscribes / spam reports is lost for weeks.

**This batch.** BUG-038 / EH-PROV-01 — SendGrid Event Webhook.
The code path exists (signed-event verification, suppression
table, idempotent ingestion), but the Cloud Run manifest didn't
reference the `caseops-sendgrid-webhook-public-key` Secret
Manager value before this PR, and the SendGrid dashboard still
needs operator action to enable signed event delivery to
`https://api.caseops.ai/api/webhooks/sendgrid/events`.

**Going forward.**
- A provider integration is **not** "code-complete + ready to
  ship" until: (a) infra manifest references all required
  secrets/env declaratively, (b) a runbook documents the exact
  operator-side dashboard steps, (c) the runbook has been
  executed at least once against a non-prod or prod environment,
  and (d) the canonical deploy script (`scripts/deploy-prod.sh`)
  is the path of record.
- Any PR that lands provider-integration code without a runbook
  is one half of a fix.
- The `STRICT_ENTERPRISE_GAP_TASKLIST.md` carries a row for
  every such item until operator-side steps are signed off.

## L6 — UX-as-fix substituted for workflow-as-fix

**Pattern.** The user reports "I can't complete X." We respond
by softening the error message, adding a banner, redirecting
away from the 404, or tweaking copy. The user still cannot
complete X. The bug reopens.

**This batch.** Caught early: BUG-032 could have shipped as
"empty state explains why orders are missing" without an actual
create path. We did not do that, but the audit during this
sweep flagged that BUG-033 `/account/setup` 404 had previously
been "fixed" once with a copy improvement — which is exactly
this anti-pattern.

**Going forward.**
- A bug is `Properly fixed` only when the user can complete the
  intended workflow on the deployed surface.
- "Improved copy" / "added a banner" / "redirected to a different
  page" by themselves are `Partially fixed` at best.
- Disable the button, do not just toast the error
  (`feedback_root_cause_patterns_2026_04_22.md` rule 5).

---

## Future-closure checklist

Before any future closure of a bug in the same shape as the five
above, the engineer (or Codex) MUST verify:

1. **Route existence.** Every URL the backend or any service
   generates resolves to a real frontend route on the running
   web app. There is a route-exists test for it.
2. **Capability/allow-list/enum parity.** Every backend
   `require_capability` / StrEnum / allow-list is reflected in
   the catalog schema and the UI gates BEFORE submit, not via a
   rejected 4xx.
3. **Linked-record create path.** Every selector dropdown / linked
   record list has a discoverable inline create path mounted in
   the empty state AND in a normal header/toolbar location.
4. **Provider integration completeness.** Code + manifest + secret
   + provider dashboard + runbook + canonical deploy. Anything
   short of all six is a `Partially implemented` / `Stale-doc`
   row in `STRICT_ENTERPRISE_GAP_TASKLIST.md`.
5. **Adjacent-path audit.** A sibling area scan: are there other
   instances of the same pattern in the codebase right now?
   Either fix them in the same PR or log them as explicit
   tracked gaps.
6. **Committed regression.** A regression test (vitest +
   Playwright local + Playwright prod, in that order of
   strength) exists, is wired into the relevant config testMatch,
   and is named so the next audit can grep for it.
7. **Exact proof artifact.** The verdict in the PR body names
   the exact prod-Playwright spec line + commit SHA + workflow
   run that proves user-visible success. "Tests pass" / "deploy
   exit 0" / "user can verify" are forbidden as closure proof.

If any of those seven cannot be answered with a concrete pointer,
the verdict is `Partially fixed` and the bug stays open.
