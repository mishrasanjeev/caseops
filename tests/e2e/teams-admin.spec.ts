/* Sprint: Codex gap audit #6 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "TeamsPass123!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Teams Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Teams Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token: string };
  return { slug, token: body.access_token };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Teams admin (Sprint 8c)", () => {
  test("create team via API, see row, delete, confirm removal", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ta");
    const { token } = await bootstrap(api, slug);
    const authHeaders = { Authorization: `Bearer ${token}` };

    // Create a team via the API. UI sign-in is only for the assertion.
    const teamSlug = `litigation-${Math.random().toString(36).slice(2, 6)}`;
    const teamName = "Litigation Team";
    const createResp = await api.post(`${apiBaseUrl}/api/teams/`, {
      headers: authHeaders,
      data: {
        name: teamName,
        slug: teamSlug,
        kind: "team",
        description: "Contentious matters — bail, commercial writs.",
      },
    });
    expect(createResp.status()).toBe(201);
    const team = (await createResp.json()) as { id: string };

    // UI sign-in.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Navigate to /app/admin/teams — row must be visible.
    await page.goto("/app/admin/teams");
    const list = page.getByTestId("teams-list");
    await expect(list).toBeVisible();
    await expect(list.getByText(teamName)).toBeVisible();
    await expect(list.getByText(teamSlug)).toBeVisible();

    // Delete the team via the UI button (data-testid includes slug).
    await page.getByTestId(`team-delete-${teamSlug}`).click();

    // Confirm removal — the row with that slug is gone.
    await expect(page.getByText(teamSlug)).toHaveCount(0, { timeout: 10_000 });

    // Double-check via API: the team no longer appears in the list.
    const listResp = await api.get(`${apiBaseUrl}/api/teams/`, {
      headers: authHeaders,
    });
    expect(listResp.status()).toBe(200);
    const body = (await listResp.json()) as {
      teams: Array<{ id: string; slug: string }>;
    };
    expect(body.teams.find((t) => t.id === team.id)).toBeUndefined();
  });
});
