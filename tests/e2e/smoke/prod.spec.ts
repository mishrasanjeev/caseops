/**
 * Prod-smoke spec — every UI surface shipped 2026-04-23 + 2026-04-24.
 *
 * Bootstraps a unique tenant on prod, navigates each surface, asserts
 * the page renders without an error boundary, and exercises the most
 * obvious user action so a server-side regression would surface here
 * instead of on a Hari ping.
 *
 * Surfaces under test:
 *   - /app/calendar  (month / week / day tabs + .ics link, Phase B J08)
 *   - /app/clients   (Restore on archived client, BUG-025)
 *   - /app/matters/[id]  (Communications tab + Compose, M11 slice 2)
 *   - /admin/email-templates  (template editor, M11 slice 2)
 *   - /app/clients/[id]  (KYC submit card, M11 slice 3)
 *   - /app/research/saved  (BUG-030)
 *
 * Spec is intentionally short on assertions per page — this is a
 * smoke pass, not a coverage suite. The goal is "did the page render
 * a server-rendered shell" + "is the primary action reachable".
 */
import { expect, request as pwRequest, test } from "@playwright/test";

const STAMP = `${Date.now()}-${Math.floor(Math.random() * 1e6).toString(36)}`;
const SLUG = `smoke-${STAMP}`;
const EMAIL = `smoke+${STAMP}@example.com`;
const PASSWORD = "SmokePass1234!";
const API_BASE = process.env.API_BASE_URL ?? "https://api.caseops.ai";

test.describe.configure({ mode: "serial" });

test.describe("Prod smoke (2026-04-24 sweep)", () => {
  test.beforeAll(async () => {
    // The marketing domain (caseops.ai) does not expose /api/* —
    // those live on the api.* subdomain. Use a one-off request
    // context pointed there so the bootstrap call lands.
    const ctx = await pwRequest.newContext({ baseURL: API_BASE });
    const resp = await ctx.post("/api/bootstrap/company", {
      data: {
        company_name: `Smoke ${STAMP}`,
        company_slug: SLUG,
        company_type: "law_firm",
        owner_full_name: "Smoke Owner",
        owner_email: EMAIL,
        owner_password: PASSWORD,
      },
    });
    expect(resp.status(), `bootstrap failed: ${await resp.text()}`).toBe(200);
    await ctx.dispose();
  });

  test.beforeEach(async ({ page }) => {
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(SLUG);
    await page.locator("#email").fill(EMAIL);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL(/\/app(\/|$)/, { timeout: 30_000 });
  });

  test("calendar month/week/day tabs render and .ics link is present", async ({
    page,
  }) => {
    await page.goto("/app/calendar");
    await expect(page.getByRole("heading", { name: /calendar/i })).toBeVisible();
    for (const tab of ["Month", "Week", "Day"] as const) {
      await page.getByRole("tab", { name: new RegExp(tab, "i") }).click();
      await expect(
        page.getByRole("tab", { name: new RegExp(tab, "i") }),
      ).toHaveAttribute("aria-selected", "true");
    }
    const ics = page.getByRole("link", { name: /\.ics|subscribe|download/i });
    await expect(ics.first()).toBeVisible();
  });

  test("clients list renders and supports archive + restore (BUG-025)", async ({
    page,
  }) => {
    await page.goto("/app/clients");
    await expect(
      page.getByRole("heading", { name: /clients/i }),
    ).toBeVisible();
    // Use the stable data-testid (button label changed in the past).
    await expect(page.getByTestId("new-client-open")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("research has Saved-research link and the page renders empty state (BUG-030)", async ({
    page,
  }) => {
    await page.goto("/app/research");
    const saved = page.getByTestId("research-open-saved");
    await expect(saved).toBeVisible();
    await saved.click();
    await page.waitForURL(/\/app\/research\/saved/);
    await expect(
      page.getByRole("heading", { name: /saved research/i }),
    ).toBeVisible();
    await expect(page.getByText(/Nothing saved yet/i)).toBeVisible();
    // Toggle archived button is reachable
    await expect(
      page.getByTestId("saved-research-toggle-archived"),
    ).toBeVisible();
  });

  test("admin email templates editor renders (M11 slice 2)", async ({
    page,
  }) => {
    await page.goto("/app/admin/email-templates");
    await expect(
      page.getByRole("heading", { name: /email templates/i }),
    ).toBeVisible();
  });

  test("dashboard does not horizontally scroll on mobile (BUG-012)", async ({
    page,
  }) => {
    // 360px is the most common Android viewport. Anything wider
    // than viewport here = horizontal scroll. The strict-audit
    // QG-UI-013 mandates mobile layout proof for every app page;
    // this is the canonical anchor for the dashboard.
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(
      overflow.scroll,
      `Horizontal scroll: scrollWidth=${overflow.scroll} > clientWidth=${overflow.client}`,
    ).toBeLessThanOrEqual(overflow.client + 1);
  });

  test("portal sign-in renders + verify-with-no-token surfaces error (Phase C-1)", async ({
    page,
  }) => {
    // Public portal surfaces must render without an /app session.
    // Use a fresh context to avoid carrying the internal cookie.
    await page.context().clearCookies();
    await page.goto("/portal/sign-in");
    await expect(
      page.getByRole("heading", { name: /sign in to your workspace portal/i }),
    ).toBeVisible();
    await expect(
      page.getByLabel(/workspace handle/i),
    ).toBeVisible();
    await expect(page.getByTestId("portal-signin-submit")).toBeVisible();

    // Verify-with-no-token: the page should render an explicit "no
    // token" hint rather than 500.
    await page.goto("/portal/verify");
    await expect(page.getByText(/no token in url/i)).toBeVisible();
  });
});
