/**
 * Hari-II-BUG-019 Codex fix 2026-04-21: the per-matter
 * outside-counsel route is no longer a redirect. It renders the
 * actual Linked Counsel card with KPIs + assignments + an
 * assignment dialog. Bug-ID namespace note: the Hari III sheet
 * (2026-04-22) numbers a different bug as "BUG-019" (drafting
 * 503) — always use the Hari-II / Hari-III prefix when
 * cross-referencing.
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

  // Hari-BUG-018/023 follow-up (2026-04-22): the workspace-level OC
  // page used to throw Zod parse errors on real backend rows because
  // panel_status, assignment status, and spend status enums all
  // drifted from the backend StrEnums. This test seeds canonical
  // backend values for ALL THREE enums and verifies the workspace
  // page renders without a page-level error — adjacent-path proof
  // for the schema fix in apps/web/lib/api/schemas.ts.
  test("workspace OC page renders canonical assignment + spend statuses", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ocws");
    const { token } = await bootstrap(api, slug);
    const headers = { Authorization: `Bearer ${token}` };

    const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: "Workspace OC drift smoke",
        matter_code: unique("OCWS").toUpperCase(),
        practice_area: "civil",
        forum_level: "high_court",
        status: "active",
      },
    });
    const matter = (await matterResp.json()) as { id: string };

    // Counsel with panel_status = inactive (the third panel value
    // that the prior frontend enum REJECTED — schemas.test.ts pins
    // it; this proves the workspace fetch round-trips it cleanly).
    const counselResp = await api.post(
      `${apiBaseUrl}/api/outside-counsel/profiles`,
      {
        headers,
        data: {
          name: "Drift Smoke Counsel",
          primary_contact_name: "Adv. Drift",
          panel_status: "inactive",
        },
      },
    );
    expect(counselResp.status()).toBe(200);
    const counsel = (await counselResp.json()) as { id: string };

    // Assignment with status = active (canonical backend value the
    // prior frontend Zod did NOT accept — would have crashed the page).
    const assignResp = await api.post(
      `${apiBaseUrl}/api/outside-counsel/assignments`,
      {
        headers,
        data: {
          matter_id: matter.id,
          counsel_id: counsel.id,
          role_summary: "Drift smoke assignment",
          budget_amount_minor: 1_00_00_00,
          status: "active",
        },
      },
    );
    expect(assignResp.status()).toBe(200);
    const assignment = (await assignResp.json()) as { id: string };

    // Spend with status = partially_approved (canonical backend value
    // missing from the prior frontend Zod). Same Zod-crash class.
    const spendResp = await api.post(
      `${apiBaseUrl}/api/outside-counsel/spend-records`,
      {
        headers,
        data: {
          matter_id: matter.id,
          counsel_id: counsel.id,
          assignment_id: assignment.id,
          description: "Drift smoke partial-approval spend",
          amount_minor: 50_00_00,
          approved_amount_minor: 30_00_00,
          status: "partially_approved",
        },
      },
    );
    expect(spendResp.status()).toBe(200);

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(`owner-${slug}@example.com`);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto("/app/outside-counsel");
    await expect(page).toHaveURL(/\/app\/outside-counsel$/);
    // Page header renders → Zod parse succeeded.
    await expect(
      page.getByRole("heading", { name: /Outside counsel & spend/i }),
    ).toBeVisible({ timeout: 15_000 });
    // The seeded counsel name appears → workspace.profiles[] parsed.
    await expect(page.getByText(/Drift Smoke Counsel/i)).toBeVisible();
  });

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
        title: "Hari-II-BUG-019 per-matter counsel",
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
