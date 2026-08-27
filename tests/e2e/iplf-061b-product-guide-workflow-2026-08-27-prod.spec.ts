import { expect, test } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

test("IPLF-061B production proves the exact Product Guide user workflow", async ({ page }) => {
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const login = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(login, 200, "IP QA sign-in");
  const session = await login.json();

  await page.goto(WEB);
  await page.evaluate(
    (context) => window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  await page.goto(`${WEB}/guide`);

  const search = page.getByRole("searchbox", { name: "Search the CaseOps guide" });
  await search.fill("deadline control");
  await page.getByRole("button", { name: "Search" }).click();
  const command = page.getByRole("link", { name: /Deadline control/ });
  await expect(command).toHaveAttribute("href", "/app/ip/docket");
  await command.click();
  await expect(page).toHaveURL(/\/app\/ip\/docket$/);

  await page.goto(`${WEB}/guide`);
  await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).fill("platform admin");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("product-guide-permission")).toContainText(
    "This task needs additional workspace access.",
  );
  await expect(page.getByRole("link", { name: /Platform admin/ })).toHaveCount(0);

  await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).fill(
    "xylophone nebula quasar",
  );
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("product-guide-no-match")).toBeVisible();

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/guide`);
  const inputBox = await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).boundingBox();
  expect(inputBox?.width ?? 0).toBeGreaterThan(250);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1),
  ).toBe(false);
});
