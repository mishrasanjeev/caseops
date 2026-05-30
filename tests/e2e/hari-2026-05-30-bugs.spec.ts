/**
 * Hari 2026-05-30 bug sheet regressions.
 *
 * Covers:
 * - BUG-042/043: case tracking inputs remain usable when provider calls are
 *   blocked, and configured search supports party/name query plus bookmark flow.
 * - BUG-024: Research no longer renders or fetches the removed Judgment Alerts
 *   submodule.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page, Route } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariMay30Bugs!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-05-30 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari May 30 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug, ownerEmail };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

const searchResult = {
  provider: "ecourtsindia",
  cnr_number: "DLHC010012342026",
  case_number: "WP(C) 1/2026",
  court_code: "DLHC",
  court_name: "Delhi High Court",
  case_title: "Example Petitioner v Example Respondent",
  party_names: ["Example Petitioner", "Example Respondent"],
  current_status: "Pending",
  current_stage: "Arguments",
  next_hearing_on: "2026-06-15",
  source_url: "https://webapi.ecourtsindia.com/api/partner/case/DLHC010012342026",
  provenance_label: "Provider-normalized case status",
};

const bookmark = {
  id: "bm-e2e",
  company_id: "company-e2e",
  tracked_case_id: "tc-e2e",
  created_by_membership_id: "membership-e2e",
  matter_id: "matter-e2e",
  name: null,
  notification_enabled: true,
  is_archived: false,
  created_at: "2026-05-30T00:00:00Z",
  updated_at: "2026-05-30T00:00:00Z",
  archived_at: null,
  update_count: 1,
  tracked_case: {
    id: "tc-e2e",
    provider: "ecourtsindia",
    cnr_number: "DLHC010012342026",
    case_number: "WP(C) 1/2026",
    court_code: "DLHC",
    court_name: "Delhi High Court",
    case_title: "Example Petitioner v Example Respondent",
    party_names: ["Example Petitioner", "Example Respondent"],
    current_status: "Pending",
    current_stage: "Arguments",
    next_hearing_on: "2026-06-15",
    last_provider_checked_at: "2026-05-30T00:00:00Z",
    last_error: null,
    metadata: {},
  },
};

test.describe("Hari 2026-05-30 case tracking and research regressions", () => {
  test.setTimeout(120_000);

  test("BUG-042: disabled provider still allows typing but blocks provider calls", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h530-disabled");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    let searchCalls = 0;
    await page.route("**/api/case-tracking/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: false,
          provider: "disabled",
          configured: false,
          reason: "Case tracking is disabled.",
        }),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ bookmarks: [] }),
      }),
    );
    await page.route("**/api/case-tracking/search", (route) => {
      searchCalls += 1;
      return route.fulfill({ status: 500, body: "{}" });
    });

    await page.goto("/app/case-tracking");
    await expect(page.getByTestId("case-tracking-disabled")).toBeVisible();
    await page.getByTestId("case-tracking-query").fill("Example Petitioner");
    await page.getByTestId("case-tracking-cnr").fill("DLHC010012342026");

    await expect(page.getByTestId("case-tracking-query")).toHaveValue(
      "Example Petitioner",
    );
    await expect(page.getByTestId("case-tracking-cnr")).toHaveValue(
      "DLHC010012342026",
    );
    await expect(page.getByTestId("case-tracking-search-submit")).toBeDisabled();
    expect(searchCalls).toBe(0);
  });

  test("BUG-042/043: configured search supports name query and bookmark updates", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h530-case");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    let storedBookmarks: unknown[] = [];
    await page.route("**/api/case-tracking/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          provider: "ecourtsindia",
          configured: true,
          reason: null,
        }),
      }),
    );
    await page.route("**/api/case-tracking/search", async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      expect(body.query).toBe("Example Petitioner");
      expect(body.court_code).toBe("DLHC");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ provider: "ecourtsindia", results: [searchResult] }),
      });
    });
    await page.route("**/api/case-tracking/bookmarks", async (route: Route) => {
      if (route.request().method() === "POST") {
        storedBookmarks = [bookmark];
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(bookmark),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ bookmarks: storedBookmarks }),
      });
    });
    await page.route("**/api/case-tracking/bookmarks/bm-e2e/updates", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          updates: [
            {
              id: "upd-e2e",
              company_id: "company-e2e",
              tracked_case_id: "tc-e2e",
              update_type: "new_judgment",
              source_record_key: "judgment:1",
              title: "Final judgment dated 30 May 2026",
              summary: "Source-backed case update summary for lawyer review.",
              ai_summary: {
                review_framing:
                  "Source-backed case update summary for lawyer review.",
              },
              source_url:
                "https://webapi.ecourtsindia.com/api/partner/case/DLHC010012342026/order/judgment-1.pdf",
              order_date: "2026-05-30",
              hearing_date: null,
              provider_metadata: {},
              created_at: "2026-05-30T00:00:00Z",
            },
          ],
        }),
      }),
    );

    await page.goto("/app/case-tracking?matterId=matter-e2e");
    await page.getByTestId("case-tracking-query").fill("Example Petitioner");
    await page.getByTestId("case-tracking-court-code").fill("DLHC");
    await page.getByTestId("case-tracking-search-submit").click();

    await expect(
      page.getByText("Example Petitioner v Example Respondent").first(),
    ).toBeVisible();
    await page.getByRole("button", { name: /Bookmark/i }).first().click();
    await expect(page.getByText("Final judgment dated 30 May 2026")).toBeVisible();
    await expect(page.getByText(/lawyer review/i).first()).toBeVisible();
  });

  test("BUG-024: Research does not render or fetch Judgment Alerts", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h530-research");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    let alertCalls = 0;
    await page.route("**/api/**judgment-alert**", (route) => {
      alertCalls += 1;
      return route.fulfill({ status: 500, body: "{}" });
    });

    await page.goto("/app/research");
    await expect(
      page.getByRole("heading", { name: /Grounded legal research/i }),
    ).toBeVisible();
    await expect(page.getByTestId("judgment-alert-center")).toHaveCount(0);
    await expect(page.getByText(/Judgment alerts/i)).toHaveCount(0);
    expect(alertCalls).toBe(0);
  });
});
