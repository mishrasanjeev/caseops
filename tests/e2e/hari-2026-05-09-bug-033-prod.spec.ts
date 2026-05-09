/**
 * BUG-033 (Hari 2026-05-09) — PROD verification.
 *
 * On prod we cannot drive the full happy-path workflow because the
 * backend deliberately omits `setup.debug_token` and
 * `password_reset.debug_token` outside test/local environments — that
 * is the anti-enumeration / anti-credential-replay guard, not a
 * limitation. The local spec covers the happy path against the dev
 * server fixture; this prod spec proves the user-visible symptom (a
 * dead 404 on `/account/setup` and `/account/reset-password`) is
 * fixed on the deployed surface.
 *
 * Strategy:
 *   1. Visit `/account/setup` with no token → MissingTokenState
 *      renders, the not-found heading is absent.
 *   2. Same for `/account/reset-password`.
 *   3. Visit `/account/setup?token=<deliberately-invalid>` → form
 *      renders; submitting surfaces the SubmitError panel with the
 *      real backend detail (proving the route + form + API wiring
 *      are live on prod, not just a static page).
 *
 * No QA-tenant mutation: the account/setup endpoint consumes the
 * token but on a clearly-invalid token it returns 400 before any DB
 * write. The session is unaffected (the endpoint accepts unauthed
 * requests; the QA bot's storage state cookies just go along for the
 * ride and do not authenticate the operation).
 */
import { expect, test } from "@playwright/test";

const PROD_BASE_URL =
  (process.env.PROD_BASE_URL ?? "").trim() || "https://caseops.ai";

test.describe("BUG-033 Hari 2026-05-09 — prod verification", () => {
  test.setTimeout(60_000);

  test("BUG-033 (setup, prod): missing-token state renders, NOT the 404 page", async ({
    page,
  }) => {
    await page.goto(`${PROD_BASE_URL}/account/setup`);

    await expect(
      page.getByRole("heading", { level: 1, name: /Set up your CaseOps account/i }),
    ).toBeVisible();
    await expect(page.getByTestId("account-setup-missing-token")).toBeVisible();
    // The route is live; the not-found page's signature heading must
    // not appear (this is the regression assertion for the symptom
    // Hari reported).
    await expect(
      page.getByRole("heading", { name: /isn't on the matter graph/i }),
    ).toHaveCount(0);
  });

  test("BUG-033 (reset, prod): missing-token state renders, NOT the 404 page", async ({
    page,
  }) => {
    await page.goto(`${PROD_BASE_URL}/account/reset-password`);

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

  test("BUG-033 (setup, prod): invalid-token submission surfaces actionable error", async ({
    page,
  }) => {
    // Deliberately invalid token: 32-char random hex that won't hash
    // to any row in `account_setup_tokens`. The server returns 400.
    const invalidToken = `bug-033-prod-probe-${Date.now()}-aaaaaaaaaaaaaaaaaaaa`;
    await page.goto(
      `${PROD_BASE_URL}/account/setup?token=${encodeURIComponent(invalidToken)}`,
    );

    await expect(page.getByTestId("account-setup-password")).toBeVisible();

    await page.getByTestId("account-setup-password").fill("ProdProbe1234!");
    await page.getByTestId("account-setup-confirm").fill("ProdProbe1234!");
    await page.getByTestId("account-setup-submit").click();

    // Either the inline submit-error panel or the toast carries the
    // backend's reason. The panel is the durable signal.
    await expect(
      page.getByTestId("account-setup-submit-error"),
    ).toBeVisible({ timeout: 15_000 });
    // The user must NOT have been redirected to /app on a bad token.
    expect(page.url()).toContain("/account/setup");
  });
});
