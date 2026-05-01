/**
 * PG-004 (2026-05-01) — prod verification of the Today cockpit
 * (commit ebe9ca6) and its three follow-ups (commit a2601b5):
 *   - GET /api/me/today is reachable from the QA workspace and
 *     returns the 5-stream payload.
 *   - /app/today renders all 5 sections.
 *   - /app auto-redirects to /app/today when the QA workspace has
 *     at least one active matter.
 *   - GET /api/matters/{id}/next-action is reachable and returns
 *     either a NextAction or null (never 5xx).
 *   - The matter cockpit page renders without 5xx (the
 *     NextActionCard either renders the card or auto-hides — both
 *     are valid; absence is not a failure).
 *
 * Run:
 *   PROD_BASE_URL=https://caseops.ai npx playwright test \
 *     --config playwright.prod-ram.config.ts \
 *     tests/e2e/pg-004-today-cockpit-2026-05-01-prod.spec.ts
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

async function firstMatterId(page: Page): Promise<string | null> {
  const resp = await page.context().request.get(
    `${PROD_API_BASE_URL}/api/matters/`,
    {
      headers: {
        Cookie: await cookieHeader(page),
        Accept: "application/json",
      },
    },
  );
  if (!resp.ok()) return null;
  const body = await resp.json();
  const matters = body?.matters ?? [];
  return matters[0]?.id ?? null;
}

test.describe("PG-004 — Today cockpit prod verification", () => {
  test("GET /api/me/today returns the 5-stream payload", async ({ page }) => {
    const resp = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/me/today`,
      {
        headers: {
          Cookie: await cookieHeader(page),
          Accept: "application/json",
        },
      },
    );
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    // Each stream is a list (possibly empty). Presence of all 5 keys
    // is the contract; emptiness is fine on a quiet workspace.
    expect(Array.isArray(body.hearings_next_7d)).toBe(true);
    expect(Array.isArray(body.tasks_due_or_overdue)).toBe(true);
    expect(Array.isArray(body.drafts_in_review)).toBe(true);
    expect(Array.isArray(body.overdue_invoices)).toBe(true);
    expect(Array.isArray(body.deadlines_next_7d)).toBe(true);
  });

  test("/app/today renders all 5 sections", async ({ page }) => {
    await page.goto(`${PROD_BASE_URL}/app/today`, { waitUntil: "networkidle" });
    expect(page.url()).toMatch(/\/app\/today$/);

    // Assert each section heading is present. The empty-state card
    // ("All clear for now") replaces the per-section cards only when
    // every stream is empty; on a real workspace we expect at least
    // one section to render. Either way, the page must not 5xx and
    // the title must render.
    await expect(page.getByText("Today", { exact: true }).first()).toBeVisible();

    // Assert at least one of the section card headings or the
    // empty-state copy is visible — covers both the "quiet workspace"
    // and "active workspace" paths.
    const sectionHeadings = [
      "Hearings (next 7 days)",
      "Tasks due or overdue",
      "Drafts awaiting review",
      "Overdue invoices",
      "Deadlines (next 7 days)",
      "All clear for now",
    ];
    let foundCount = 0;
    for (const heading of sectionHeadings) {
      const locator = page.getByText(heading, { exact: false }).first();
      if (await locator.isVisible().catch(() => false)) {
        foundCount += 1;
      }
    }
    expect(foundCount).toBeGreaterThanOrEqual(1);
  });

  test("/app redirects to /app/today when workspace has ≥1 active matter", async ({
    page,
  }) => {
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters; redirect path doesn't apply.");
      return;
    }

    await page.goto(`${PROD_BASE_URL}/app`, { waitUntil: "networkidle" });
    // The redirect is a client-side router.replace() inside a
    // useEffect, so wait briefly for it to resolve.
    await page.waitForURL(/\/app\/today$/, { timeout: 10_000 });
    expect(page.url()).toMatch(/\/app\/today$/);
  });

  test("GET /api/matters/{id}/next-action returns a NextAction or null", async ({
    page,
  }) => {
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters; next-action path doesn't apply.");
      return;
    }
    const resp = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/next-action`,
      {
        headers: {
          Cookie: await cookieHeader(page),
          Accept: "application/json",
        },
      },
    );
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    if (body !== null) {
      expect(typeof body.kind).toBe("string");
      expect(["hearing", "task", "draft", "invoice", "deadline"]).toContain(
        body.kind,
      );
      expect(["urgent", "soon", "normal"]).toContain(body.severity);
      expect(typeof body.label).toBe("string");
      expect(typeof body.detail).toBe("string");
      expect(typeof body.href).toBe("string");
    }
  });

  test("Matter cockpit page renders cleanly (no 5xx)", async ({ page }) => {
    const matterId = await firstMatterId(page);
    if (!matterId) {
      test.skip(true, "QA workspace has no matters.");
      return;
    }
    const resp = await page.goto(
      `${PROD_BASE_URL}/app/matters/${matterId}`,
      { waitUntil: "networkidle" },
    );
    expect(resp).not.toBeNull();
    if (resp) {
      expect(resp.status()).toBeLessThan(500);
    }
    // The "Matter summary" card is always rendered on the cockpit;
    // its presence is a clean-render signal regardless of whether
    // NextActionCard surfaced an action.
    await expect(page.getByText("Matter summary", { exact: false }).first()).toBeVisible();
  });
});
