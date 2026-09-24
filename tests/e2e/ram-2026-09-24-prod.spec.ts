import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";

const web = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3000";
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const production = new URL(web).hostname === "caseops.ai";

const legacyMatters = [
  ["3f01ac0c-df3c-40ea-846f-bda253168f8c", "2026-11-04", "case_tracking"],
  ["2c324e89-9ead-4e16-abd6-4a923733add6", "2026-09-25", "case_tracking"],
  ["84ac219b-1133-4cf5-8272-16bbdc2a1ee5", "2026-05-15", "unknown"],
  ["3701d1bc-a9c8-4ed6-a9f7-0f1092559733", "2026-05-15", "unknown"],
] as const;

async function waitForSignInForm(page: import("@playwright/test").Page) {
  await page.waitForFunction(() => {
    const form = document.querySelector('form[aria-label="Sign in"]');
    return form && Object.keys(form).some((key) => key.startsWith("__react"));
  });
}

test("Matter court link shows a verified case result without provider spend in local UI", async ({ page, request }) => {
  test.skip(production, "Local UI journey uses deterministic nonbillable provider evidence.");
  const suffix = randomUUID().slice(0, 8);
  const slug = `ecourt-link-${suffix}`;
  const email = `${slug}@example.com`;
  const password = `Local-${randomUUID()}!`;
  const boot = await request.post(`${api}/api/bootstrap/company`, {
    headers: noPaidProviderHeaders,
    data: {
      company_name: slug,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "eCourts QA",
      owner_email: email,
      owner_password: password,
    },
  });
  expect(boot.status(), await boot.text()).toBe(200);
  const headers = {
    ...noPaidProviderHeaders,
    Authorization: `Bearer ${(await boot.json()).access_token as string}`,
  };
  const created = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title: "Example Petitioner v Example Respondent",
      matter_code: `EC-LINK-${suffix}`,
      practice_area: "litigation",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      case_number: "WP(C) 1/2026",
      cnr_number: "DLHC010012342026",
      status: "active",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const matterId = (await created.json()).id as string;
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  await page.goto(`${web}/sign-in`);
  await waitForSignInForm(page);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await page.goto(`${web}/app/matters/${matterId}`);
  const court = page.getByRole("link", { name: "Delhi High Court" });
  await expect(court).toBeVisible();
  const href = await court.getAttribute("href");
  expect(href).toContain(`/app/case-tracking?matterId=${matterId}`);

  await page.route("**/api/case-tracking/status", async (route) => {
    await route.fulfill({ json: {
      enabled: true, configured: true, provider: "ecourtsindia",
      scheduled_sync_local_time: "18:00", scheduled_sync_timezone: "Asia/Kolkata",
    } });
  });
  await page.route(`**/api/case-tracking/matters/${matterId}/resolve`, async (route) => {
    expect(route.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    await route.fulfill({ json: {
      provider: "ecourtsindia", status: "matched", results: [{
        provider: "ecourtsindia", cnr_number: "DLHC010012342026",
        case_number: "WP(C) 1/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "Example Petitioner v Example Respondent", party_names: [],
        current_status: "Pending", current_stage: "Arguments", next_hearing_on: null,
        source_url: null, provenance_label: "Provider-normalized case status",
      }],
    } });
  });
  await page.goto(`${web}${href}`);
  await page.getByTestId("matter-case-resolve-submit").click();
  await expect(page.getByText("One case matches the Matter identifiers.")).toBeVisible();
  await expect(page.getByTestId("matter-case-candidate")).toHaveCount(1);
});

test("legacy dates have canonical hearings and automated eCourts lookup cannot spend", async ({ page, request }) => {
  test.skip(!production, "Exact reported Matter IDs exist only in the production test workspace.");
  const slug = process.env.CASEOPS_PROD_TEST_SLUG ?? process.env.CASEOPS_RAM_PROD_SLUG;
  const email = process.env.CASEOPS_PROD_TEST_EMAIL ?? process.env.CASEOPS_RAM_PROD_EMAIL;
  const password = process.env.CASEOPS_PROD_TEST_PASSWORD ?? process.env.CASEOPS_RAM_PROD_PASSWORD;
  if (!slug || !email || !password) throw new Error("Production test credentials are required.");
  const login = await request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: { company_slug: slug, email, password },
  });
  expect(login.status(), await login.text()).toBe(200);
  const headers = {
    ...noPaidProviderHeaders,
    Authorization: `Bearer ${(await login.json()).access_token as string}`,
  };
  for (const [id, date, source] of legacyMatters) {
    const workspace = await request.get(`${api}/api/matters/${id}/workspace`, { headers });
    expect(workspace.status(), await workspace.text()).toBe(200);
    const data = await workspace.json();
    expect(data.matter.next_hearing_on).toBe(date);
    expect(data.matter.next_hearing_source).toBe(source);
    expect(data.hearings.filter((row: { hearing_on: string; status: string }) =>
      row.hearing_on === date && row.status === "scheduled",
    )).toHaveLength(1);
  }
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  await page.goto(`${web}/sign-in`);
  await waitForSignInForm(page);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await page.goto(`${web}/app/matters/${legacyMatters[0][0]}`);
  const court = page.locator('a[href*="/app/case-tracking?matterId="]').first();
  await expect(court).toBeVisible();
  const href = await court.getAttribute("href");
  expect(href).toContain("/app/case-tracking?matterId=");
  await page.goto(`${web}${href}`);
  await page.getByTestId("matter-case-resolve-submit").click();
  await expect(page.getByRole("alert")).toContainText(/no external request was made/i);
  await page.goto(`${web}/app/hearings`);
  await page.getByLabel("Exact hearing date").fill("2026-09-25");
  await expect(page.locator(`a[href*="/app/matters/${legacyMatters[1][0]}"]`).first()).toBeVisible();
});
