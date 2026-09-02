/** IPLF-054B: licensed legal-source readiness, attribution, and source access. */

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "LicensedResearch2026!";

async function bootstrap(api: APIRequestContext) {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `licensed-research-${suffix}`;
  const email = `owner-${suffix}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 054 Licensed Research LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Licensed Research Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return { ...(await response.json()), slug, email };
}

async function signIn(page: Page, tenant: { slug: string; email: string }) {
  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: tenant.slug,
      email: tenant.email,
      password: PASSWORD,
    },
  });
  expect(login.status(), await login.text()).toBe(200);
  const session = await login.json();
  await page.goto("/");
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

test.describe.serial("IPLF-054 licensed Indian Kanoon research", () => {
  let api: APIRequestContext;
  let tenant: Awaited<ReturnType<typeof bootstrap>>;

  test.beforeAll(async () => {
    api = await request.newContext();
    tenant = await bootstrap(api);
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test("default-off API and browser state make no provider call", async ({ page }) => {
    const headers = { Authorization: `Bearer ${tenant.access_token}` };
    const readiness = await api.get(
      `${apiBaseUrl}/api/authorities/providers/indian-kanoon/readiness`,
      { headers },
    );
    expect(readiness.status(), await readiness.text()).toBe(200);
    const readinessBody = await readiness.json();
    expect(readinessBody.external_calls_enabled).toBe(false);

    const blockedSearch = await api.post(
      `${apiBaseUrl}/api/authorities/providers/indian-kanoon/search`,
      {
        headers,
        data: { query: "constitutional proportionality" },
      },
    );
    expect(blockedSearch.status(), await blockedSearch.text()).toBe(503);
    expect((await blockedSearch.json()).code).toBe("provider_disabled");

    await signIn(page, tenant);
    await page.goto("/app/research");
    await page.getByTestId("research-source-indian-kanoon").click();
    await expect(page.getByTestId("research-indian-kanoon-readiness")).toContainText(
      "Licensed access is disabled by the runtime switch",
    );
    await page.getByTestId("research-query-input").fill("constitutional proportionality");
    await expect(page.getByTestId("research-query-submit")).toBeDisabled();
  });

  test("ready UI renders attribution, cost, freshness, and protected source URL", async ({
    page,
  }) => {
    await page.route(/\/api\/authorities\/providers\/indian-kanoon\/readiness(?:\?.*)?$/, (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          provider: "indian-kanoon",
          state: "ready",
          configured: true,
          enabled: true,
          external_calls_enabled: true,
          missing_config_names: [],
          invalid_terms_config: [],
          missing_approval_keys: [],
          missing_cost_categories: [],
          permitted_uses: ["document_display", "research_storage", "search"],
          daily_budget_minor: 10000,
          monthly_budget_minor: 100000,
          retention_days: 30,
          terms_owner: "E2E legal fixture",
          terms_approved_at: "2026-08-24T00:00:00Z",
          terms_expires_at: "2026-09-24T00:00:00Z",
          kill_switch_name: "INDIAN_KANOON_ENABLED",
          attribution: {
            label: "Powered by Indian Kanoon",
            provider_url: "https://indiankanoon.org/",
            terms_url: "https://indiankanoon.org/terms.html",
            logo_required: true,
          },
          limitations: [],
        }),
      }),
    );
    await page.route(/\/api\/authorities\/providers\/indian-kanoon\/search(?:\?.*)?$/, async (route) => {
      const requestBody = route.request().postDataJSON();
      expect(requestBody.query).toBe("constitutional proportionality");
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          query: requestBody.query,
          page_number: 0,
          returned_count: 1,
          results: [
            {
              document_id: "12345",
              title: "Example Industries v State",
              publisher: "Supreme Court of India",
              jurisdiction: "India",
              issuing_body: "Supreme Court of India",
              source_category: "supreme_court",
              document_type: "judgment",
              decision_or_publication_date: "2026-08-20",
              canonical_citation: "2026 INSC 101",
              authority_status: "provider_record_unreviewed",
              binding_status: "verify_jurisdiction_and_precedential_status",
              canonical_url: "https://indiankanoon.org/doc/12345/",
              source_action: {
                state: "available",
                label: "Open source",
                open_url:
                  "/api/source-actions/open?url=https%3A%2F%2Findiankanoon.org%2Fdoc%2F12345%2F",
                source_reference: "https://indiankanoon.org/doc/12345/",
                reason: null,
                opens_new_tab: true,
              },
              attribution: {
                label: "Powered by Indian Kanoon",
                provider_url: "https://indiankanoon.org/",
                terms_url: "https://indiankanoon.org/terms.html",
                logo_required: true,
              },
              rank: 1,
              headline: "The exact passage matched the query.",
            },
          ],
          call: {
            cached: false,
            stale: false,
            freshness_warning: null,
            retrieved_at: "2026-08-25T00:00:00Z",
            estimated_cost_minor: 50,
            currency: "INR",
            cost_category: "legal_source_search",
            cost_basis: "verified_actual",
          },
          attribution: {
            label: "Powered by Indian Kanoon",
            provider_url: "https://indiankanoon.org/",
            terms_url: "https://indiankanoon.org/terms.html",
            logo_required: true,
          },
          disclaimer: "Verify the exact passage and subsequent treatment before reliance.",
        }),
      });
    });

    await signIn(page, tenant);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/app/research");
    await page.getByTestId("research-source-indian-kanoon").click();
    await expect(page.getByTestId("research-indian-kanoon-readiness")).toContainText(
      "Licensed access is active",
    );
    await page.getByTestId("research-query-input").fill("constitutional proportionality");
    await page.getByTestId("research-query-submit").click();
    await expect(page.getByText("Example Industries v State")).toBeVisible();
    await expect(page.getByTestId("research-indian-kanoon-attribution")).toContainText(
      "Powered by Indian Kanoon",
    );
    await expect(page.getByTestId("research-indian-kanoon-attribution")).toContainText(
      "₹0.50",
    );
    const source = page.getByTestId("source-action-open");
    await expect(source).toBeVisible();
    await expect(source).toHaveAttribute(
      "href",
      /\/api\/source-actions\/open\?url=https%3A%2F%2Findiankanoon\.org/,
    );
    const layout = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    expect(layout.scroll).toBeLessThanOrEqual(layout.viewport);
  });
});
