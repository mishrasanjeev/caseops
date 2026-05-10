/**
 * BUG-033 (Hari 2026-05-09) — local-app Playwright regression for
 * the employee onboarding setup link and the password reset link.
 *
 * Symptom from Hari's report: clicking the email link
 *   https://caseops.ai/account/setup?token=...
 * landed on the not-found page ("This page isn't on the matter graph")
 * because no Next.js route existed at /account/setup. Backend POST
 * handler /api/auth/account-setup/complete already worked; the gap
 * was on the frontend.
 *
 * What this spec proves on the local app config:
 *   1. /account/setup with no `?token=...` renders the actionable
 *      missing-token state, not the 404.
 *   2. /account/setup?token=<value> renders the form (h1 + password
 *      fields visible), not the 404.
 *   3. Same for /account/reset-password (no token + with token).
 *
 * The full happy-path round-trip (create employee → use debug_token →
 * submit → redirect to /app authenticated) is covered by:
 *   - apps/web/app/account/setup/page.test.tsx (vitest, mocks the
 *     completeAccountSetup endpoint, asserts session storage +
 *     redirect)
 *   - apps/api/tests/test_legalworkspace_employee_admin.py
 *     test_account_setup_complete_is_single_use_and_enables_login
 *     (full backend round-trip incl. token consumption)
 *
 * Why the happy-path is not driven from this Playwright spec:
 * `_debug_tokens_allowed()` in services/employees.py returns true
 * only when CASEOPS_ENV is in {"local", "test"}. The Playwright local
 * app config sets CASEOPS_ENV=e2e (production-like fixture), so the
 * setup-token response does not include `debug_token`. Switching to
 * CASEOPS_ENV=test would change behaviour for every other spec in
 * the project. The vitest + pytest pair above cover the same logic
 * with full assertions; the prod-Playwright variant additionally
 * proves the route is live on caseops.ai.
 */
import { expect, test } from "@playwright/test";

test.describe("BUG-033 Hari 2026-05-09 — account setup + password reset", () => {
  test.setTimeout(60_000);

  test("BUG-033 (setup): missing-token query string renders an actionable empty state, not the 404 page", async ({
    page,
  }) => {
    await page.goto(`/account/setup`);
    await expect(
      page.getByRole("heading", { level: 1, name: /Set up your CaseOps account/i }),
    ).toBeVisible();
    await expect(page.getByTestId("account-setup-missing-token")).toBeVisible();
    // The not-found page's signature heading must NOT be on the
    // page. This is the regression assertion for Hari's symptom.
    await expect(
      page.getByRole("heading", { name: /isn't on the matter graph/i }),
    ).toHaveCount(0);
  });

  test("BUG-033 (setup): /account/setup?token=<value> renders the password form, not the 404 page", async ({
    page,
  }) => {
    // Token is intentionally invalid (the regression we are pinning
    // is route-existence; submission against a bad token returns 400
    // and lands on SubmitErrorState, which is asserted by the prod
    // spec). The form must render BEFORE submit.
    await page.goto(
      `/account/setup?token=local-probe-${Date.now()}-aaaaaaaaaaaaaaaa`,
    );
    await expect(
      page.getByRole("heading", { level: 1, name: /Set up your CaseOps account/i }),
    ).toBeVisible();
    await expect(page.getByTestId("account-setup-password")).toBeVisible();
    await expect(page.getByTestId("account-setup-confirm")).toBeVisible();
    await expect(page.getByTestId("account-setup-submit")).toBeEnabled();
    await expect(
      page.getByRole("heading", { name: /isn't on the matter graph/i }),
    ).toHaveCount(0);
  });

  test("BUG-033 (reset): missing-token query string renders an actionable empty state, not the 404 page", async ({
    page,
  }) => {
    await page.goto(`/account/reset-password`);
    await expect(
      page.getByRole("heading", { level: 1, name: /Reset your CaseOps password/i }),
    ).toBeVisible();
    await expect(
      page.getByTestId("reset-password-missing-token"),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /isn't on the matter graph/i }),
    ).toHaveCount(0);
  });

  test("BUG-033 (reset): /account/reset-password?token=<value> renders the password form, not the 404 page", async ({
    page,
  }) => {
    await page.goto(
      `/account/reset-password?token=local-probe-${Date.now()}-aaaaaaaaaaaaaaaa`,
    );
    await expect(
      page.getByRole("heading", { level: 1, name: /Reset your CaseOps password/i }),
    ).toBeVisible();
    await expect(page.getByTestId("reset-password-password")).toBeVisible();
    await expect(page.getByTestId("reset-password-confirm")).toBeVisible();
    await expect(page.getByTestId("reset-password-submit")).toBeEnabled();
    await expect(
      page.getByRole("heading", { name: /isn't on the matter graph/i }),
    ).toHaveCount(0);
  });
});
