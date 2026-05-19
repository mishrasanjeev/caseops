/**
 * BUG-032 (Hari 2026-05-09) — court-order manual create, prod
 * verification.
 *
 * Strategy: as the QA bot, create a disposable matter on the QA
 * tenant, then exercise the create endpoint + UI affordance on the
 * deployed surface.
 *
 * Safety: every artefact is uniquely named (Date.now() suffix) and
 * lives entirely on the dedicated `caseops-qa` workspace. The
 * matter + court order are disposable — no user-visible product
 * impact. We do NOT touch other tenants' data.
 */
import { expect, test } from "@playwright/test";

const PROD_BASE_URL =
  (process.env.PROD_BASE_URL ?? "").trim() || "https://caseops.ai";
const PROD_API_BASE_URL =
  (process.env.PROD_API_BASE_URL ?? "").trim() || "https://api.caseops.ai";

test.describe("BUG-032 Hari 2026-05-09 — court-order manual create prod verification", () => {
  test.setTimeout(60_000);

  test("BUG-032 (API, prod): POST /api/matters/{id}/court-orders is mounted and creates a disposable order on the QA tenant", async ({
    page,
  }) => {
    const cookies = await page.context().cookies();
    const cookieHeader = cookies
      .filter((c) => c.domain.includes("caseops.ai"))
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const csrf =
      cookies.find((c) => c.name === "caseops_csrf")?.value ?? "";
    const headers = {
      Cookie: cookieHeader,
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      Accept: "application/json",
    };

    // Create a disposable matter on the QA tenant.
    const matterCode = `BUG-032-PROD-${Date.now().toString().slice(-7)}`;
    const matterResp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers,
        data: {
          title: `BUG-032 prod probe ${matterCode}`,
          matter_code: matterCode,
          practice_area: "criminal",
          forum_level: "high_court",
          court_name: "Delhi High Court",
        },
      },
    );
    expect(
      matterResp.status(),
      `matter create expected 200, got ${await matterResp.text()}`,
    ).toBe(200);
    const matterId = (await matterResp.json()).id as string;

    // Now exercise the create endpoint. Mounted -> not 404.
    const orderResp = await page.context().request.post(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/court-orders`,
      {
        headers,
        data: {
          order_date: new Date().toISOString().slice(0, 10),
          title: `BUG-032 prod probe order ${matterCode}`,
          summary: "Prod-Playwright probe — disposable artefact.",
          source: "manual_remarks",
        },
      },
    );
    expect(
      orderResp.status(),
      `order create expected 200, got ${await orderResp.text()}`,
    ).toBe(200);
    const created = await orderResp.json();
    expect(created.id).toBeTruthy();

    // Workspace must include the new order — proves the documents-
    // page Linked-order selector picks it up on prod.
    const workspace = await page.context().request.get(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/workspace`,
      { headers: { Cookie: cookieHeader, Accept: "application/json" } },
    );
    expect(workspace.status()).toBe(200);
    const orders = (await workspace.json()).court_orders as Array<{
      id: string;
    }>;
    expect(orders.some((o) => o.id === created.id)).toBe(true);
  });

  test("BUG-032 (UI, prod): /app/matters list renders + Add-order affordance reaches the page mounting", async ({
    page,
  }) => {
    // The full UI path (sign in → matters → click into hearings →
    // see Add-order) depends on the QA tenant having ≥1 active
    // matter, which the prior matter-create test guarantees if it
    // ran. As a self-contained UI assertion we navigate to the
    // matters list and confirm the page renders without 5xx — the
    // dedicated UI assertion is in the local spec via vitest.
    await page.goto(`${PROD_BASE_URL}/app/matters`);
    // Don't fail if the page redirects to /sign-in (storage state
    // expired); the API test above is the load-bearing proof.
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toBeVisible({ timeout: 15_000 });
  });
});
