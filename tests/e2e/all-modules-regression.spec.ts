import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { plusDays, uniqueId } from "./support/helpers";

const PASSWORD = "AllModulesE2E123!";

type Tenant = {
  email: string;
  slug: string;
  token: string;
};

async function bootstrapTenant(api: APIRequestContext): Promise<Tenant> {
  const suffix = uniqueId("modules").slice(-12).toLowerCase();
  const slug = `modules-${suffix}`;
  const email = `owner-${suffix}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `All Modules E2E ${suffix}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "All Modules Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return {
    email,
    slug,
    token: ((await response.json()) as { access_token: string }).access_token,
  };
}

async function signIn(page: Page, tenant: Tenant): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

function formatLegalDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

test.describe.serial("All modules and critical court operations", () => {
  test.setTimeout(360_000);
  let api: APIRequestContext;
  let tenant: Tenant;

  test.beforeAll(async () => {
    api = await request.newContext();
    tenant = await bootstrapTenant(api);
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test.beforeEach(async ({ page }) => {
    await signIn(page, tenant);
  });

  test("every capability-visible module loads without a server error", async ({
    page,
  }) => {
    const serverErrors: string[] = [];
    page.on("response", (response) => {
      if (
        response.status() >= 500 &&
        (response.url().startsWith(apiBaseUrl) || response.url().includes("127.0.0.1"))
      ) {
        serverErrors.push(
          `${response.status()} ${response.request().method()} ${response.url()}`,
        );
      }
    });

    const sidebar = page.locator('aside[aria-label="Primary navigation"]');
    await expect(sidebar).toBeVisible();
    await expect.poll(() => sidebar.locator("a[href]").count()).toBeGreaterThan(30);
    const routes = await sidebar.locator("a[href]").evaluateAll((links) =>
      links.map((link) => ({
        href: link.getAttribute("href") ?? "",
        label: link.getAttribute("aria-label") ?? link.textContent?.trim() ?? "",
      })),
    );

    expect(new Set(routes.map((route) => route.href)).size).toBe(routes.length);
    for (const route of routes) {
      const response = await page.goto(route.href);
      expect(response?.status(), `${route.label} (${route.href})`).toBeLessThan(400);
      await expect(page.locator("h1").first(), `${route.label} heading`).toBeVisible({
        timeout: 30_000,
      });
    }

    expect(serverErrors).toEqual([]);
  });

  test("e-List search uses the entered case number through the real Docker API", async ({
    page,
  }) => {
    test.skip(
      !process.env.CASEOPS_E2E_DOCKER_PROJECT,
      "The deterministic court provider is available only in Docker acceptance.",
    );
    const caseNumber = `WP(C) ${Date.now().toString().slice(-6)}/2026`;
    await page.goto("/app/case-tracking");
    const caseNumberInput = page.getByTestId("case-tracking-case-number");
    await expect(caseNumberInput).toBeEnabled({ timeout: 20_000 });
    await expect(page.getByTestId("case-tracking-disabled")).toHaveCount(0);
    await caseNumberInput.fill(caseNumber);
    await expect(page.getByTestId("case-tracking-search-submit")).toBeEnabled();
    const searchRequest = page.waitForRequest(
      (candidate) =>
        candidate.url().includes("/api/case-tracking/search") &&
        candidate.method() === "POST",
    );
    const searchResponse = page.waitForResponse(
      (candidate) =>
        candidate.url().includes("/api/case-tracking/search") &&
        candidate.request().method() === "POST",
    );
    await page.getByTestId("case-tracking-search-submit").click();

    expect((await searchRequest).postDataJSON()).toEqual({
      query: null,
      cnr_number: null,
      case_number: caseNumber,
      court_code: null,
    });
    const response = await searchResponse;
    expect(response.status(), await response.text()).toBe(200);
    const body = (await response.json()) as {
      results: Array<{ case_number: string; case_title: string }>;
    };
    expect(body.results).toHaveLength(1);
    expect(body.results[0].case_number).toBe(caseNumber);
    expect(body.results[0].case_title).toBe(
      "Local Docker Petitioner v Local Docker Respondent",
    );

    await expect(
      page.getByText("Local Docker Petitioner v Local Docker Respondent").first(),
    ).toBeVisible();
    const bookmarkResponse = page.waitForResponse(
      (candidate) =>
        candidate.url().endsWith("/api/case-tracking/bookmarks") &&
        candidate.request().method() === "POST",
    );
    await page.getByRole("button", { name: /^Bookmark$/ }).click();
    expect((await bookmarkResponse).status()).toBe(201);
    await expect(
      page
        .getByTestId("case-tracking-bookmarks")
        .getByText("Local Docker Petitioner v Local Docker Respondent"),
    ).toBeVisible();
  });

  test("next hearing and cause-list preview/PDF stay consistent end to end", async ({
    page,
  }) => {
    const suffix = uniqueId("court").slice(-10).toUpperCase();
    const matterCode = `COURT-${suffix}`;
    const matterTitle = `Court operations ${suffix}`;
    const caseNumber = `CS(COMM) ${Date.now().toString().slice(-5)}/2026`;
    const headers = { Authorization: `Bearer ${tenant.token}` };
    const create = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: matterTitle,
        matter_code: matterCode,
        practice_area: "Commercial Litigation",
        forum_level: "high_court",
        court_name: "Delhi High Court",
        case_number: caseNumber,
        client_name: "Local Docker Petitioner",
        opposing_party: "Local Docker Respondent",
        status: "active",
      },
    });
    expect(create.status(), await create.text()).toBe(200);
    const matter = (await create.json()) as { id: string };

    const hearingDate = plusDays(6);
    await page.goto(`/app/matters/${matter.id}/hearings`);
    await page.getByTestId("schedule-hearing-open").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByTestId("schedule-hearing-date").fill(hearingDate);
    await dialog.getByLabel(/Forum \/ bench/i).fill("Delhi High Court, Court 12");
    await dialog.getByLabel(/Purpose \/ stage/i).fill("Final arguments");
    await dialog.getByTestId("schedule-hearing-submit").click();
    await expect(dialog).toBeHidden({ timeout: 20_000 });
    await expect(page.getByText(/Scheduled:/).first()).toBeVisible();

    await page.goto("/app/matters");
    await page.locator("#matter-filter-q").fill(matterCode);
    await page.getByRole("button", { name: /Apply/i }).click();
    await expect(page.getByText(matterCode)).toBeVisible();
    await expect(page.getByText(formatLegalDate(hearingDate))).toBeVisible();

    await page.goto("/app/hearings");
    const portfolioHearing = page.getByRole("link", { name: new RegExp(matterTitle) });
    await expect(portfolioHearing).toBeVisible();
    await expect(portfolioHearing).toContainText(formatLegalDate(hearingDate));

    const causeListDate = plusDays(9);
    const imported = await api.post(
      `${apiBaseUrl}/api/matters/${matter.id}/court-sync/import`,
      {
        headers,
        data: {
          source: "Local Docker cause list",
          summary: "Deterministic local Docker cause-list import.",
          cause_list_entries: [
            {
              listing_date: causeListDate,
              forum_name: "Delhi High Court",
              bench_name: "Justice Local Docker",
              courtroom: "Court 12",
              item_number: "42",
              stage: "Final hearing",
              notes: "Listed for final arguments.",
              source_reference: `cause-list-${causeListDate}.pdf`,
            },
          ],
          orders: [],
        },
      },
    );
    expect(imported.status(), await imported.text()).toBe(200);

    const persisted = await api.get(`${apiBaseUrl}/api/matters/${matter.id}`, {
      headers,
    });
    expect(persisted.status(), await persisted.text()).toBe(200);
    expect(((await persisted.json()) as { next_hearing_on: string }).next_hearing_on).toBe(
      hearingDate,
    );

    await page.goto("/app/cause-list");
    await page.getByLabel("From").fill(causeListDate);
    await page.getByRole("textbox", { name: "To", exact: true }).fill(causeListDate);
    await page
      .locator("label", { hasText: /^Source/ })
      .locator("select")
      .selectOption("cause_list_entries");
    const previewResponse = page.waitForResponse(
      (candidate) =>
        candidate.url().endsWith("/api/cause-lists/preview") &&
        candidate.request().method() === "POST",
    );
    await page.getByRole("button", { name: /^Preview$/ }).click();
    expect((await previewResponse).status()).toBe(200);

    const row = page.getByRole("row").filter({ hasText: caseNumber });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(matterCode);
    await expect(row).toContainText(matterTitle);
    await expect(row).toContainText("Justice Local Docker");
    await expect(row).toContainText("Court 12/42");
    await expect(row).toContainText(causeListDate);

    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("button", { name: /^PDF$/ }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe(
      `cause-list-${causeListDate}-to-${causeListDate}.pdf`,
    );
    expect(await download.failure()).toBeNull();
  });
});
