/**
 * Hari 2026-06-29 workbook regressions.
 *
 * BUG-002: "Court name contains" must submit the partial court name and render
 * matching authorities instead of behaving like an exact court-name filter.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun29Bugs!";
const BAIL_QUERY =
  "Triple test for bail under BNSS s.483; parity; custody duration";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-29 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun29 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return { ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Hari 2026-06-29 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-002: Research submits partial court filter and renders matching authority", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62902");
    const { ownerEmail } = await bootstrap(api, slug);
    await api.dispose();
    await signIn(page, slug, ownerEmail);

    let searchPayload: Record<string, unknown> | null = null;
    await page.route("**/api/authorities/search", async (route) => {
      searchPayload = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: BAIL_QUERY,
          mode: "keyword",
          provider: "caseops-authority-search-v2",
          generated_at: new Date().toISOString(),
          contextual_plan: null,
          coverage_notice: null,
          total_after_filter: 1,
          offset: 0,
          results: [
            {
              authority_document_id: "madras-bnss-483-bail",
              title: "Triple test for bail under BNSS section 483",
              court_name: "Madras High Court",
              forum_level: "high_court",
              document_type: "judgment",
              decision_date: "2026-06-15",
              case_reference: "CRL.O.P. 483/2026",
              bench_name: "Justice M. Sundar",
              summary:
                "Madras High Court judgment on parity and custody duration.",
              source: "test",
              source_reference: "https://official.example.test/madras-bail.pdf",
              snippet:
                "The Madras High Court applied the triple test for bail under BNSS section 483, considering parity and custody duration.",
              score: 220,
              matched_terms: ["triple", "bail", "bnss", "parity", "custody"],
              relevance_reason: null,
              worst_treatment: null,
              adverse_count: 0,
            },
          ],
        }),
      });
    });

    await page.goto("/app/research");
    await page.getByTestId("research-query-input").fill(BAIL_QUERY);
    await page.getByTestId("research-filter-court").fill("Madras");
    await expect(page.getByTestId("research-query-submit")).toBeEnabled();
    await page.getByTestId("research-query-submit").click();

  await expect(
    page.getByRole("heading", {
      name: "Triple test for bail under BNSS section 483",
    }),
  ).toBeVisible();
  await expect(page.getByText("Madras High Court").first()).toBeVisible();
    expect(searchPayload).toMatchObject({
      query: BAIL_QUERY,
      mode: "keyword",
      court_name: "Madras",
    });
  });
});
