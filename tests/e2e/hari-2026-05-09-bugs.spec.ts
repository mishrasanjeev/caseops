/**
 * Hari 2026-05-09 P1 batch — end-to-end regressions.
 *
 * One spec per bug. Tests run against the local Playwright app config
 * (`playwright.app.config.ts`) by default and can be retargeted at the
 * deployed surface by setting BASE_URL / API_BASE_URL.
 *
 * Bugs:
 * - BUG-032 (separate spec block): matter hearings → upload order →
 *   document Linked Order list (added in a follow-up commit alongside
 *   the create-order endpoint).
 * - BUG-033 (separate spec block): /account/setup + /account/reset-password
 *   frontend pages exist and complete the workflow.
 * - BUG-034 (this commit): admin/roles non-delegable capabilities are
 *   disabled in the UI and the API rejects them with 403.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariBugs2026May!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-05-09 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari 2026-05-09 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return {
    slug,
    token: (await resp.json()).access_token as string,
    ownerEmail,
  };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Hari 2026-05-09 P1 regressions", () => {
  test.setTimeout(120_000);

  // ----------------------------------------------------------------
  // BUG-034 — Custom role create returns 403 when protected
  // capabilities (email_templates:manage / portal:invite /
  // portal:manage_grants) are selected. Backend rejection is correct;
  // the UI must disable these capabilities BEFORE submit and explain
  // why.
  //
  // Two independent assertions:
  // 1. API: catalog flags the three capabilities as
  //    custom_role_delegable=false with a protected_reason, and the
  //    create endpoint returns 403 if any is included in the payload.
  // 2. UI: at /app/admin/roles, the three capability checkboxes are
  //    rendered disabled with the protected reason visible.
  // ----------------------------------------------------------------
  test("BUG-034 (API): catalog flags non-delegable caps and create rejects with 403", async () => {
    const api = await request.newContext();
    const slug = unique("b34a");
    const { token } = await bootstrap(api, slug);

    const catalog = await api.get(
      `${apiBaseUrl}/api/companies/current/capabilities`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(catalog.status()).toBe(200);
    const body = (await catalog.json()) as {
      capabilities: Array<{
        capability: string;
        owner_only: boolean;
        custom_role_delegable: boolean;
        protected_reason: string | null;
      }>;
    };
    const byName = new Map(body.capabilities.map((row) => [row.capability, row]));

    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      const row = byName.get(cap);
      expect(row, `${cap} missing from catalog`).toBeDefined();
      expect(row!.owner_only, `${cap} should be protected, not owner-only`).toBe(false);
      expect(row!.custom_role_delegable).toBe(false);
      expect(row!.protected_reason).toBeTruthy();
    }

    // The catalog round-trip: server must reject the same caps it flags.
    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      const create = await api.post(`${apiBaseUrl}/api/companies/current/roles`, {
        headers: { Authorization: `Bearer ${token}` },
        data: { name: `Drift ${cap}`, permissions: [cap] },
      });
      expect(create.status(), `create with ${cap} expected 403`).toBe(403);
      const detail = (await create.json()).detail as string;
      expect(detail.toLowerCase()).toContain("protected");
    }
  });

  test("BUG-034 (UI): protected capabilities are disabled in admin/roles", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b34b");
    const { ownerEmail } = await bootstrap(api, slug);

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(ownerEmail);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto("/app/admin/roles");

    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      const checkbox = page.getByTestId(`capability-${cap}`);
      await expect(checkbox).toBeVisible();
      await expect(checkbox).toBeDisabled();
      // The protected_reason text is rendered alongside the disabled
      // checkbox so the user knows why selection is blocked.
      await expect(page.getByTestId(`capability-${cap}-reason`)).toContainText(
        /non-delegable/i,
      );
    }

    // A normal delegable capability stays enabled.
    await expect(page.getByTestId("capability-matters:create")).toBeEnabled();
  });
});
