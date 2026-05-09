/**
 * Hari 2026-05-09 P1 batch — PROD verification suite.
 *
 * Mirror of the local-app `hari-2026-05-09-bugs.spec.ts` against the
 * deployed caseops.ai surface. Required by the bug-fixing skill: no
 * "Properly fixed" verdict can land without a Playwright spec that
 * exercises the user-visible workflow on the deployed commit SHA.
 *
 * Auth: reuses the dedicated CaseOps QA Bot (workspace slug
 * `caseops-qa`), persisted by `setup/qa-auth.setup.ts`. No real-user
 * credentials are referenced. The QA workspace is the only tenant
 * mutated, and only by read-only / 403-rejected calls in this batch
 * (no rows are written on a 403, so no cleanup is required).
 *
 * Run:
 *   PROD_BASE_URL=https://caseops.ai npx playwright test \
 *     --config playwright.prod-ram.config.ts \
 *     tests/e2e/hari-2026-05-09-prod.spec.ts
 */
import { expect, test, type Page } from "@playwright/test";

const envOr = (key: string, fallback: string): string => {
  const v = (process.env[key] ?? "").trim();
  return v.length > 0 ? v : fallback;
};
const PROD_BASE_URL = envOr("PROD_BASE_URL", "https://caseops.ai");
const PROD_API_BASE_URL = envOr("PROD_API_BASE_URL", "https://api.caseops.ai");

async function cookieHeader(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies
    .filter((c) => c.domain.includes("caseops.ai"))
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
}

async function csrfFromCookies(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "caseops_csrf");
  return csrf?.value ?? "";
}

test.describe("Hari 2026-05-09 P1 — prod verification", () => {
  test.setTimeout(60_000);

  // ----------------------------------------------------------------
  // BUG-034 — Custom-role catalog flags non-delegable capabilities,
  // and the create endpoint rejects them with 403.
  //
  // Read-only path on prod: hits GET /api/companies/current/capabilities
  // (safe), then POSTs each protected capability against the create
  // endpoint expecting 403 (no row created on 403, so no cleanup).
  // ----------------------------------------------------------------
  test("BUG-034 (API): catalog flags non-delegable caps and create rejects with 403", async ({
    page,
  }) => {
    const cookie = await cookieHeader(page);
    const csrf = await csrfFromCookies(page);

    const catalog = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/companies/current/capabilities`,
      {
        headers: {
          Cookie: cookie,
          Accept: "application/json",
        },
      },
    );
    expect(catalog.ok(), `catalog status ${catalog.status()}`).toBeTruthy();
    const body = (await catalog.json()) as {
      capabilities: Array<{
        capability: string;
        owner_only: boolean;
        custom_role_delegable?: boolean;
        protected_reason?: string | null;
      }>;
    };
    expect(body.capabilities.length).toBeGreaterThan(0);
    const byName = new Map(body.capabilities.map((row) => [row.capability, row]));

    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      const row = byName.get(cap);
      expect(row, `${cap} missing from prod catalog`).toBeDefined();
      expect(
        row!.owner_only,
        `${cap} should be protected, not owner-only`,
      ).toBe(false);
      expect(
        row!.custom_role_delegable,
        `${cap} must be flagged custom_role_delegable=false on prod`,
      ).toBe(false);
      expect(
        row!.protected_reason,
        `${cap} must carry a protected_reason on prod`,
      ).toBeTruthy();
    }

    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      // Disposable, uniquely-named role attempt; the server returns 403
      // before any row is inserted, so the QA tenant is unmutated.
      const uniqueName = `BUG-034 prod probe ${cap} ${Date.now()}`;
      const create = await page.context().request.post(
        `${PROD_API_BASE_URL}/api/companies/current/roles`,
        {
          headers: {
            Cookie: cookie,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            Accept: "application/json",
          },
          data: { name: uniqueName, permissions: [cap] },
        },
      );
      expect(
        create.status(),
        `create with ${cap} expected 403, got ${create.status()}: ${await create.text()}`,
      ).toBe(403);
      const detail = (await create.json()).detail as string;
      expect(detail.toLowerCase()).toContain("protected");
    }
  });

  test("BUG-034 (UI): protected capabilities are disabled in admin/roles", async ({
    page,
  }) => {
    await page.goto(`${PROD_BASE_URL}/app/admin/roles`);

    // Wait for the matrix to render — the catalog query must resolve.
    await page.getByTestId("custom-role-new").waitFor({ state: "visible" });

    for (const cap of [
      "email_templates:manage",
      "portal:invite",
      "portal:manage_grants",
    ]) {
      const checkbox = page.getByTestId(`capability-${cap}`);
      await expect(checkbox).toBeVisible();
      await expect(checkbox).toBeDisabled();
      await expect(page.getByTestId(`capability-${cap}-reason`)).toContainText(
        /non-delegable/i,
      );
    }

    // Sanity: a representative delegable capability stays enabled.
    await expect(page.getByTestId("capability-matters:create")).toBeEnabled();
  });
});
