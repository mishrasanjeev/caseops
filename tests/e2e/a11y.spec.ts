import AxeBuilder from "@axe-core/playwright";
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

// Phase 10 a11y gate: zero `serious` or `critical` axe violations on the
// public marketing surface, the sign-in page, and the authenticated app
// spine. WCAG 2.1 AA tags only — we are not chasing 2.2 yet.
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

const PASSWORD = "AxeAllyPass123!";

async function bootstrap(api: APIRequestContext, slug: string): Promise<void> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Axe Ally LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Axe Ally",
      owner_email: `axe-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() === 409) return;
  if (resp.status() !== 200) {
    throw new Error(
      `Bootstrap for slug ${slug} failed with ${resp.status()}: ${await resp.text()}`,
    );
  }
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`axe-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function expectNoSeriousViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  if (blocking.length > 0) {
    const summary = blocking
      .map((v) => {
        const nodes = v.nodes
          .slice(0, 5)
          .map((n) => `    · ${n.target.join(" ")} — ${n.failureSummary}`)
          .join("\n");
        return `- [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node${
          v.nodes.length === 1 ? "" : "s"
        }) → ${v.helpUrl}\n${nodes}`;
      })
      .join("\n");
    throw new Error(`Axe found blocking violations on ${label}:\n${summary}`);
  }
}

test.describe("Accessibility (axe-core)", () => {
  test("landing page has no serious/critical violations", async ({ page }) => {
    await page.goto("/");
    await expectNoSeriousViolations(page, "/");
  });

  test("sign-in page has no serious/critical violations", async ({ page }) => {
    await page.goto("/sign-in");
    await expect(
      page.getByRole("heading", { level: 1, name: /sign in/i }),
    ).toBeVisible();
    await expectNoSeriousViolations(page, "/sign-in");
  });

  test("authenticated app shell has no serious/critical violations", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = `axe-${Math.random().toString(36).slice(2, 8)}`;
    await bootstrap(api, slug);
    await signIn(page, slug);

    await expect(page.getByRole("link", { name: /skip to main content/i })).toHaveCount(1);
    await expect(page.locator("#main")).toBeVisible();

    await page.goto("/app");
    await expectNoSeriousViolations(page, "/app");

    await page.goto("/app/matters");
    await expectNoSeriousViolations(page, "/app/matters");

    await page.goto("/app/contracts");
    await expectNoSeriousViolations(page, "/app/contracts");
  });
});
