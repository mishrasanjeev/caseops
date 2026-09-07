import { expect, test, type Page } from "@playwright/test";
import { apiBaseUrl, assertPatentRelease, existingPatentQa } from "./support/patent-acceptance";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { DOMAIN_STAGE_LABELS, ipDomainCatalogueSchema } from "../../apps/web/lib/ip/domain-catalog";
import {
  bootstrapPatentTenant,
  enablePatentWorkspace,
  signInPatentTenant,
} from "./support/patent-acceptance";

test.use({ extraHTTPHeaders: noPaidProviderHeaders });
test.beforeEach(async ({ request }) => { await assertPatentRelease(request); });

async function assertRows(page: Page, rows: ReturnType<typeof ipDomainCatalogueSchema.parse>["domains"]) {
  const region = page.getByRole("region", { name: "IP domain availability" });
  await expect(region).toBeVisible();
  for (const row of rows) {
    const item = region.getByTestId(`ip-domain-${row.domain}`);
    await item.scrollIntoViewIfNeeded();
    await expect(item.getByText(row.label, { exact: true })).toBeVisible();
    await expect(item.getByText(DOMAIN_STAGE_LABELS[row.stage], { exact: true })).toBeVisible();
    const boxes = await item.evaluate((element) => {
      const measure = (selector: string) => {
        const node = element.querySelector(selector)!;
        const range = document.createRange();
        range.selectNodeContents(node);
        return { box: node.getBoundingClientRect().toJSON(),
          lines: Array.from(range.getClientRects(), (rect) => rect.toJSON()) };
      };
      return { label: measure("dt"), state: measure("dd"), width: window.innerWidth };
    });
    for (const measured of [boxes.label, boxes.state]) {
      expect(measured.box.width).toBeGreaterThan(0);
      expect(measured.lines.length).toBeGreaterThan(0);
      for (const line of measured.lines) {
        expect(line.width).toBeGreaterThan(0);
        expect(line.left).toBeGreaterThanOrEqual(measured.box.left - 1);
        expect(line.right).toBeLessThanOrEqual(measured.box.right + 1);
        expect(line.right).toBeLessThanOrEqual(boxes.width);
      }
    }
    const label = boxes.label.box;
    const state = boxes.state.box;
    const sameLine = label.top < state.bottom && state.top < label.bottom;
    if (sameLine) expect(label.right).toBeLessThanOrEqual(state.left);
  }
}

for (const width of [360, 768, 1280]) {
  test(`IPLF-079B public claims match the server at ${width}px`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const response = await request.get(`${apiBaseUrl}/api/ip-domains`, { headers: noPaidProviderHeaders });
    expect(response.status()).toBe(200);
    const catalogue = ipDomainCatalogueSchema.parse(await response.json());
    expect(catalogue.domains).toHaveLength(11);
    await page.goto("/");
    await assertRows(page, catalogue.domains);
    await page.getByRole("region", { name: "IP domain availability" }).screenshot({ path: testInfo.outputPath(`domains-${width}.png`) });
    await page.reload();
    await assertRows(page, catalogue.domains);
  });
}

test("IPLF-079B tenant readiness uses the same catalogue without duplicate discovery", async ({ page, request }) => {
  const slug = `domains-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `${slug}@example.com`;
  const password = "DomainLocalFixture2026!";
  const response = existingPatentQa ? null : await request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    headers: noPaidProviderHeaders,
    data: { company_name: "Domain Local QA", company_slug: slug, company_type: "law_firm",
      owner_full_name: "Domain QA", owner_email: email, owner_password: password },
  });
  if (response) expect(response.status(), await response.text()).toBe(200);
  const tenant = response ? await response.json() : await bootstrapPatentTenant(request, true);
  const readiness = await request.get(`${apiBaseUrl}/api/ip/readiness`, {
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${tenant.access_token}` },
  });
  expect(readiness.status(), await readiness.text()).toBe(200);
  const readinessState = await readiness.json();
  const domains = readinessState.domains;
  const publicResponse = await request.get(`${apiBaseUrl}/api/ip-domains`, { headers: noPaidProviderHeaders });
  expect(domains).toEqual((await publicResponse.json()).domains);
  if (existingPatentQa) {
    await signInPatentTenant(page, tenant);
    await expect(page.getByRole("region", { name: "IP domain availability" })
      .getByTestId("ip-domain-patent")).toBeVisible();
  } else {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  }
  let supportingCalls = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/ip-domains") supportingCalls += 1;
  });
  await page.setViewportSize({ width: 393, height: 852 });
  await page.goto("/app/ip");
  const availability = page.getByRole("tab", { name: "Domain availability", exact: true });
  if (readinessState.workspace_available) await availability.click();
  await assertRows(page, domains);
  expect(supportingCalls).toBe(0);
  await page.reload();
  if (readinessState.workspace_available) await availability.click();
  await assertRows(page, domains);
  expect(supportingCalls).toBe(0);
});

test("IPLF-079B public availability outage has no supported-domain claims", async ({ page }) => {
  await page.route("**/api/ip-domains", (route) => route.fulfill({ status: 503, body: "unavailable" }));
  await page.goto("/");
  const region = page.getByRole("region", { name: "IP domain availability" });
  await expect(region.getByRole("alert")).toContainText("could not be verified");
  await expect(region.locator("dl")).toHaveCount(0);
  await page.unroute("**/api/ip-domains");
  await region.getByRole("button", { name: "Retry" }).click();
  await expect(region.getByTestId("ip-domain-patent")).toBeVisible();
});

test("IPLF-079B a stalled availability request times out and only retries explicitly", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/ip-domains", () => { calls += 1; });
  await page.goto("/");
  const region = page.getByRole("region", { name: "IP domain availability" });
  await expect(region.getByRole("alert")).toContainText("could not be verified", { timeout: 7500 });
  await expect(region.locator("dl")).toHaveCount(0);
  expect(calls).toBe(1);
  await page.unroute("**/api/ip-domains");
  await region.getByRole("button", { name: "Retry" }).click();
  await expect(region.getByTestId("ip-domain-patent")).toBeVisible();
});

test("IPLF-079B configured workspace keeps its docket and exposes domain availability", async ({ page }) => {
  const tenant = await bootstrapPatentTenant(page.request);
  const headers = await enablePatentWorkspace(page.request, tenant);
  const readiness = await page.request.get(`${apiBaseUrl}/api/ip/readiness`, { headers });
  expect(readiness.status(), await readiness.text()).toBe(200);
  const domains = (await readiness.json()).domains;
  await signInPatentTenant(page, tenant);
  // The sign-in helper visits the public landing page. Finish its discovery
  // before measuring the separate authenticated workspace's supporting calls.
  await expect(page.getByRole("region", { name: "IP domain availability" })
    .getByTestId("ip-domain-patent")).toBeVisible();
  let supportingCalls = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/ip-domains") supportingCalls += 1;
  });
  for (const width of [393, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/ip");
    await expect(page.getByRole("tab", { name: "Docket", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.getByRole("tab", { name: "Domain availability", exact: true }).click();
    await assertRows(page, domains);
    await page.getByRole("tab", { name: "Docket", exact: true }).click();
    await expect(page.getByRole("tab", { name: "Docket", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.reload();
    await page.getByRole("tab", { name: "Domain availability", exact: true }).click();
    await assertRows(page, domains);
  }
  expect(supportingCalls).toBe(0);
});
