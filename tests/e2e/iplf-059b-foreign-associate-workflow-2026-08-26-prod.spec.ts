/** IPLF-059B exact-release production acceptance for foreign associates. */

import { expect, request, test, type Page } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";
import {
  createForeignAssociateFixture,
  exerciseForeignAssociateJourney,
} from "./support/iplf059b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function authenticate(page: Page) {
  const response = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(response, 200, "IP QA sign-in");
  const session = await response.json();
  await page.goto(`${WEB}/`);
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
  return session;
}

test("IPLF-059B production proves every UJ-37 path and source-backed responsive UI", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(25_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const session = await authenticate(page);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const api = await request.newContext();
  const runId = `${Date.now()}`;
  const fixture = await createForeignAssociateFixture(
    api, API, headers, session.membership.id, runId,
  );
  await exerciseForeignAssociateJourney(api, API, headers, fixture);

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/app/ip/foreign-associates`);
  await expect(page.getByRole("heading", { name: "Foreign associates" })).toBeVisible();
  for (const name of ["All", "Awaiting acknowledgement", "Missing independent evidence"]) {
    const control = page.getByRole("button", { name });
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);

  await page.getByRole("button").filter({ hasText: "Completed" }).first().click();
  for (const name of ["Instruction", "Actions", "Reminders", "History"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }
  await expect(page.getByText("Delivered", { exact: true })).toBeVisible();
  await expect(page.getByText("Received", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("link", { name: "Open source" }).first()).toHaveAttribute(
    "href",
    new RegExp(`/evidence/`),
  );

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "Instruction" }).click();
  await expect(page.getByText(`US-TM-${runId}`)).toBeVisible();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Reminders" }).click();
  await expect(page.getByText(/acknowledgement due/i).first()).toBeVisible();

  await page.goto(`${WEB}/guide`);
  await expect(page.getByRole("heading", { name: "Foreign-associate filings" })).toBeVisible();
  await page.goto(`${WEB}/law-firms`);
  await expect(page.getByRole("heading", { name: "Foreign-associate filing control" })).toBeVisible();
  await api.dispose();
});
