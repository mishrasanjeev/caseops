/**
 * BUG-032 (Hari 2026-05-09) — manual court-order create from the
 * matter Hearings page, local-app Playwright regression.
 *
 * Symptom: at /app/matters/{id}/hearings, the Orders-on-file card
 * had no Add-order affordance. Court-sync was the only path that
 * produced MatterCourtOrder rows, so the documents page Linked-
 * order selector was effectively unavailable for any matter that
 * hadn't been court-synced.
 *
 * What this spec proves on the local app config:
 *   1. POST /api/matters/{id}/court-orders is mounted (NOT 404).
 *   2. End-to-end metadata-only create succeeds and the new order
 *      appears in the workspace `court_orders` array (which is what
 *      the documents-page Linked-order selector feeds from).
 *   3. The hearings page renders the Add-order trigger (header +
 *      empty state) for a fresh matter with no orders.
 *
 * Full UI happy-path through the dialog (open → fill → submit) is
 * covered by the vitest test against the page; the local Playwright
 * here proves the route + UI mounting on the deployed bundle.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "Bug032Order2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "BUG-032 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "BUG-032 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug, token: (await resp.json()).access_token as string, ownerEmail };
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `BUG-032 matter ${code}`,
      matter_code: code,
      practice_area: "criminal",
      forum_level: "high_court",
      status: "active",
      court_name: "Delhi High Court",
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Matter create failed: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).id as string;
}

test.describe("BUG-032 Hari 2026-05-09 — court-order manual create", () => {
  test.setTimeout(120_000);

  test("BUG-032 (API): POST /api/matters/{id}/court-orders creates an order and surfaces in workspace", async () => {
    const api = await request.newContext();
    const slug = unique("b32a");
    const { token } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B32A");

    const create = await api.post(
      `${apiBaseUrl}/api/matters/${matterId}/court-orders`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: {
          order_date: "2026-05-10",
          title: "Stay continued — bail application",
          summary: "Honble Court continued the interim stay.",
          source: "manual_upload",
          order_kind: "interim_order",
          is_interim_order: true,
          stay_status: "continued",
        },
      },
    );
    expect(create.status(), `expected 200, got ${await create.text()}`).toBe(200);
    const created = await create.json();
    expect(created.title).toBe("Stay continued — bail application");
    expect(created.stay_status).toBe("continued");
    expect(created.is_interim_order).toBe(true);

    // Workspace must include the new order — proves the documents-
    // page Linked-order selector will pick it up (same array).
    const workspace = await api.get(
      `${apiBaseUrl}/api/matters/${matterId}/workspace`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(workspace.status()).toBe(200);
    const orders = (await workspace.json()).court_orders as Array<{ id: string }>;
    expect(orders.some((o) => o.id === created.id)).toBe(true);
  });

  test("BUG-032 (UI): Hearings page Orders-on-file card mounts the Add-order trigger", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b32b");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B32B");

    await page.goto("/sign-in");
    await page.locator("#company-slug").fill(slug);
    await page.locator("#email").fill(ownerEmail);
    await page.locator("#password").fill(PASSWORD);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app/);

    await page.goto(`/app/matters/${matterId}/hearings`);
    // Add-order trigger should be present (header + empty state →
    // at least 2). The dialog mount + happy-path field submission
    // is covered by the vitest page-test; here we verify the
    // route + mount on the deployed bundle.
    const triggers = page.getByTestId("add-court-order-open");
    await expect(triggers.first()).toBeVisible();
    await expect(await triggers.count()).toBeGreaterThanOrEqual(2);
  });
});
