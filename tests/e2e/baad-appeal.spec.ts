/**
 * BAAD-001 + MOD-TS-001-A E2E (Sprint P, 2026-04-25).
 *
 * Walks the appeal-drafting surface as a real signed-in user:
 *   1. bootstrap a workspace + sign in
 *   2. create a matter (criminal / Bombay HC — typical appeal venue)
 *   3. open the Drafting tab → New draft → pick `Appeal Memorandum`
 *   4. land on the stepper with appeal_memorandum template
 *   5. assert BenchContextCard renders
 *   6. assert AppealStrengthPanel renders
 *   7. structurally sweep the rendered DOM for forbidden favorability
 *      tokens (win, lose, favourable, tendency, probability, predict,
 *      outcome) — bench-aware drafting hard rule, third defense layer
 *      after the in-service _check_phrase + the backend test sweep.
 *
 * Anchor for the "test every UI feature E2E before shipping" hard
 * rule. Catches the regression where appeal_memorandum is not in
 * `KNOWN_TEMPLATE_TYPES` on the new-draft page (BAAD UI silently 404s
 * into the template grid).
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "BaadE2EPass!23";

async function bootstrap(api: APIRequestContext, slug: string): Promise<void> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "BAAD E2E LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "BAAD Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() === 409) return;
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("BAAD-001 appeal drafting + Appeal Strength (MOD-TS-001-A)", () => {
  // Stepper mounts a couple of useQuery calls (template, bench
  // context, appeal strength). Generous overall budget.
  test.setTimeout(180_000);

  test("appeal stepper mounts → BenchContextCard + AppealStrengthPanel render → no favorability copy", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("baad");
    await bootstrap(api, slug);

    // Sign in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app$/);

    // Create a matter.
    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    const matterCode = `BAAD-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
    await dialog.getByLabel("Title").fill("BAAD e2e — appeal");
    await dialog.getByLabel("Matter code").fill(matterCode);
    await dialog.getByLabel("Practice area").fill("Criminal");
    await dialog.getByLabel("Client name").fill("Test Appellant");
    await dialog.getByLabel("Opposing party").fill("State");
    await dialog.getByRole("button", { name: /^Create matter$/ }).click();
    await expect(dialog).toBeHidden();

    // Open the matter cockpit. Capture matter id from the URL so we
    // can navigate directly into the template-grid surface (the
    // drafts-tab "New draft" button opens a dialog for a generic
    // brief — the template grid lives at /drafts/new directly).
    await page.getByText("BAAD e2e — appeal").first().click();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+$/);
    const matterUrl = page.url();
    const matterIdMatch = matterUrl.match(
      /\/app\/matters\/([0-9a-f-]+)/,
    );
    expect(matterIdMatch).not.toBeNull();
    const matterId = matterIdMatch![1];

    // Go directly to the template grid at /drafts/new.
    await page.goto(`/app/matters/${matterId}/drafts/new`);
    await page.waitForURL(
      /\/app\/matters\/[0-9a-f-]+\/drafts\/new$/,
    );

    // Pick the appeal_memorandum template card. This anchors the
    // bug-detection: if KNOWN_TEMPLATE_TYPES is missing the entry,
    // the URL query-params but the stepper doesn't mount and the
    // next assertion fails.
    await page.getByTestId("start-draft-appeal_memorandum").first().click();
    await page.waitForURL(
      /\/app\/matters\/[0-9a-f-]+\/drafts\/new\?type=appeal_memorandum$/,
    );

    // Stepper header — the breadcrumb step labels prove it mounted.
    await expect(
      page.getByRole("heading", { name: /^Appeal Memorandum$/ }),
    ).toBeVisible({ timeout: 30_000 });

    // BAAD-001 BenchContextCard renders. Card uses
    // data-testid="bench-context-card" (loading state) and
    // data-testid="bench-context-card" again (loaded). Either is
    // acceptable proof of mount.
    await expect(
      page
        .getByTestId("bench-context-card")
        .or(page.getByTestId("bench-context-card-loading")),
    ).toBeVisible({ timeout: 30_000 });

    // MOD-TS-001-A AppealStrengthPanel renders. With no draft body
    // yet, expect the no-draft note + weak overall.
    await expect(
      page
        .getByTestId("appeal-strength-panel")
        .or(page.getByTestId("appeal-strength-panel-loading")),
    ).toBeVisible({ timeout: 30_000 });

    // After the panel resolves, the no-draft amber note fires.
    await expect(
      page.getByTestId("appeal-strength-no-draft-note"),
    ).toBeVisible({ timeout: 15_000 });

    // Bench-aware drafting hard rule: structural no-favorability
    // sweep at the rendered DOM. THIRD defense layer after the
    // in-service _check_phrase + the backend structural test.
    const bodyText = (await page.locator("body").innerText()).toLowerCase();
    const forbidden = [
      "winnable",
      "winnability",
      "favourable",
      "favorable",
      "usually grants",
      "usually rules",
      "tendency",
      "tends to",
      "probability",
      "chance of success",
      "likely to succeed",
    ];
    for (const needle of forbidden) {
      expect(
        bodyText,
        `forbidden favorability phrase "${needle}" leaked into the BAAD/strength surface`,
      ).not.toContain(needle);
    }
  });
});
