/**
 * BUG-019 Codex fix 2026-04-21: the per-matter outside-counsel route
 * is no longer a redirect. It renders the actual Linked Counsel card
 * with KPIs + assignments + an assignment dialog.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "MatterOCAssign2026!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Matter OC test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Matter OC Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug, token: (await resp.json()).access_token as string };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 6)}`;
}


test.describe("Per-matter Outside Counsel", () => {
  test.setTimeout(120_000);

  test("renders assignments + KPIs for the matter (not a redirect)", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("moc");
    const { token } = await bootstrap(api, slug);
    const headers = { Authorization: `Bearer ${token}` };

    const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: "BUG-019 per-matter counsel",
        matter_code: unique("MOC").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    expect(matterResp.status()).toBe(200);
    const matter = (await matterResp.json()) as { id: string };

    const counselResp = await api.post(
      `${apiBaseUrl}/api/outside-counsel/profiles`,
      {
        headers,
        data: {
          name: "Vanguard Legal Associates",
          primary_contact_name: "Adv. Venkat",
          panel_status: "preferred",
        },
      },
    );
    expect(counselResp.status()).toBe(200);
    const counsel = (await counselResp.json()) as { id: string };

    await api.post(`${apiBaseUrl}/api/outside-counsel/assignments`, {
      headers,
      data: {
        matter_id: matter.id,
        counsel_id: counsel.id,
        role_summary: "Lead counsel — bail application",
        budget_amount_minor: 5_00_00_00, // INR 5 lakh
        status: "approved",
      },
    });

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    // Visit per-matter OC URL.
    await page.goto(`/app/matters/${matter.id}/outside-counsel`);

    // Should NOT redirect to the workspace list.
    await expect(page).toHaveURL(
      new RegExp(`/app/matters/${matter.id}/outside-counsel`),
    );
    // Real content — assignment visible by counsel name + role.
    await expect(page.getByText(/Vanguard Legal Associates/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByText(/Lead counsel — bail application/i),
    ).toBeVisible();
    // KPI cards — counsel assigned count + budget.
    await expect(page.getByText(/Counsel assigned/i)).toBeVisible();
    await expect(page.getByText(/Approved budget/i)).toBeVisible();
    // Assign-counsel button is present for owners.
    await expect(page.getByTestId("matter-oc-assign-open")).toBeVisible();
  });
});
