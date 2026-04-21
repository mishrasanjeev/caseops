/* Sprint: Codex gap audit #6 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, ConsoleMessage } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ResearchPass123!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Research Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Research Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Research page (§4.2)", () => {
  test.setTimeout(90_000);

  test("search query renders result cards or the empty-state", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("rs");
    await bootstrap(api, slug);

    // Track browser console errors — the post-condition is that the
    // page did not throw during the search round-trip. `invalid_token`
    // is a known regression signature from a misaligned auth flow and
    // must never surface in the body.
    const consoleErrors: string[] = [];
    page.on("console", (msg: ConsoleMessage) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    // UI sign-in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto("/app/research");
    await expect(
      page.getByRole("heading", { name: /Grounded legal research/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Fill search. Use the canonical testid first; fall back to
    // placeholder-based lookup if the selector renames.
    const input = page.getByTestId("research-query-input");
    await expect(input).toBeVisible();
    await input.fill("bail BNSS 483 triple test");
    await input.press("Enter");

    // Wait up to 30 s for a result card OR the empty-state to render.
    // Local SQLite has no corpus, so empty-state is the expected pass.
    const results = page.getByTestId("research-results");
    const emptyState = page.getByText(/No authorities matched/i);
    await Promise.race([
      results.waitFor({ state: "visible", timeout: 30_000 }).catch(() => null),
      emptyState
        .waitFor({ state: "visible", timeout: 30_000 })
        .catch(() => null),
    ]);

    const resultsVisible = await results.isVisible().catch(() => false);
    const emptyVisible = await emptyState.isVisible().catch(() => false);
    expect(resultsVisible || emptyVisible).toBe(true);

    // Negative assertions: no `invalid_token` rendered, no console errors.
    await expect(page.getByText(/invalid_token/i)).toHaveCount(0);
    expect(
      consoleErrors.filter((e) => !/favicon|preload/i.test(e)),
    ).toEqual([]);
  });
});
