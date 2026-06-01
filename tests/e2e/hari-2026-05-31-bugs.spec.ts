/**
 * Hari 2026-05-31 bug sheet regressions.
 *
 * These specs lock the *user-visible* failure modes that made BUG-042 (case
 * search) and BUG-049 (statutes legal-update watchlist) read as "broken /
 * unreliable" even though the backend was responding. The root cause of the
 * reopens was silent failure: a configured search that returned zero rows
 * rendered nothing, and a watchlist create/run that errored showed no message.
 *
 * Provider calls are stubbed at the network boundary (page.route) so the full
 * UI workflow is exercised deterministically without a live eCourtsIndia
 * credential. Live-data verification is tracked separately (token-blocked).
 *
 * Covers:
 * - BUG-042: configured search with zero results shows an explicit empty state.
 * - BUG-042: a provider error renders the backend `detail` verbatim (not a
 *   hard-coded "check configuration" string that hides the real reason).
 * - BUG-049: a failed watchlist create renders the backend `detail` verbatim.
 * - BUG-049: a successful watchlist create persists and appears in the list.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page, Route } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariMay31Bugs!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-05-31 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari May 31 Owner",
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

const configuredStatus = {
  enabled: true,
  provider: "ecourtsindia",
  configured: true,
  reason: null,
};

test.describe("Hari 2026-05-31 case tracking + statutes silent-failure regressions", () => {
  test.setTimeout(120_000);

  test("BUG-042: configured search with zero results shows an explicit empty state", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h531-empty");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    await page.route("**/api/case-tracking/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(configuredStatus),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ bookmarks: [] }),
      }),
    );
    await page.route("**/api/case-tracking/search", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ provider: "ecourtsindia", results: [] }),
      }),
    );

    await page.goto("/app/case-tracking");
    await page.getByTestId("case-tracking-query").fill("Nonexistent Party Name");
    await page.getByTestId("case-tracking-search-submit").click();

    await expect(page.getByTestId("case-tracking-search-empty")).toBeVisible();
    await expect(page.getByTestId("case-tracking-search-empty")).toContainText(
      /No cases matched your search/i,
    );
  });

  test("BUG-042: provider error renders the backend detail verbatim", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h531-err");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    const providerDetail =
      "eCourtsIndia provider is unavailable. Try again shortly.";
    await page.route("**/api/case-tracking/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(configuredStatus),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ bookmarks: [] }),
      }),
    );
    await page.route("**/api/case-tracking/search", (route) =>
      route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: providerDetail }),
      }),
    );

    await page.goto("/app/case-tracking");
    await page.getByTestId("case-tracking-query").fill("Example Petitioner");
    await page.getByTestId("case-tracking-search-submit").click();

    await expect(page.getByTestId("case-tracking-search-error")).toContainText(
      providerDetail,
    );
  });

  test("BUG-049: failed watchlist create renders the backend detail verbatim", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h531-wl-err");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    await page.route("**/api/statutes/", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ statutes: [], total_section_count: 0 }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/watchlists", (route: Route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Watchlist must include at least one bounded filter.",
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ watchlists: [] }),
      });
    });
    await page.route("**/api/statutes/legal-updates?**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ updates: [] }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/digest-preview**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          generated_at: "2026-05-31T00:00:00Z",
          unread_count: 0,
          dismissed_count: 0,
          updates: [],
          delivery_status: "in_app_only",
          delivery_note: "In-app preview only.",
        }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/source-records**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ records: [] }),
      }),
    );

    await page.goto("/app/statutes");
    await page.getByTestId("legal-update-name").fill("NI Act monitor");
    await page.getByTestId("legal-update-terms").fill("Section 138");
    await page.getByTestId("legal-update-create").click();

    await expect(page.getByTestId("legal-update-create-error")).toContainText(
      "Watchlist must include at least one bounded filter.",
    );
  });

  test("BUG-049: successful watchlist create persists into the list", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h531-wl-ok");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    const created = {
      id: "wl-created",
      company_id: "company-e2e",
      name: "NI Act monitor",
      practice_area: null,
      statute_id: null,
      jurisdiction: null,
      statute_terms: ["Section 138"],
      source_key: null,
      source_category: null,
      update_types: ["amendment", "notification"],
      since_date: null,
      until_date: null,
      matter_id: null,
      contract_id: null,
      is_archived: false,
      created_by_membership_id: "membership-e2e",
      created_at: "2026-05-31T00:00:00Z",
      updated_at: "2026-05-31T00:00:00Z",
      archived_at: null,
    };
    let watchlists: unknown[] = [];

    await page.route("**/api/statutes/", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ statutes: [], total_section_count: 0 }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/watchlists", (route: Route) => {
      if (route.request().method() === "POST") {
        watchlists = [created];
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(created),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ watchlists }),
      });
    });
    await page.route("**/api/statutes/legal-updates?**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ updates: [] }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/digest-preview**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          generated_at: "2026-05-31T00:00:00Z",
          unread_count: 0,
          dismissed_count: 0,
          updates: [],
          delivery_status: "in_app_only",
          delivery_note: "In-app preview only.",
        }),
      }),
    );
    await page.route("**/api/statutes/legal-updates/source-records**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ records: [] }),
      }),
    );

    await page.goto("/app/statutes");
    await page.getByTestId("legal-update-name").fill("NI Act monitor");
    await page.getByTestId("legal-update-terms").fill("Section 138");
    await page.getByTestId("legal-update-create").click();

    await expect(page.getByText("NI Act monitor").first()).toBeVisible();
    await expect(page.getByTestId("legal-update-create-error")).toHaveCount(0);
  });
});
