import { expect, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { expectStatus } from "./support/iplf058b";

test("IPLF-UJ-22-NORMAL and exceptions run through the Product Guide UI", async ({ page }) => {
  const runId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `guide-workflow-${runId}`;
  const email = `owner-${runId}@example.com`;
  const password = "GuideWorkflow2026!";
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Guide Workflow ${runId}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Guide Workflow Owner",
      owner_email: email,
      owner_password: password,
    },
  });
  await expectStatus(bootstrap, 200, "guide-workflow tenant bootstrap");
  const session = await bootstrap.json();

  await page.goto("/");
  await page.evaluate(
    (context) => window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );

  await page.route("**/api/product-guide/search?**", async (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set("client_version", "2026.08.22.1");
    await route.continue({ url: url.toString() });
  });

  await page.goto("/guide");
  const search = page.getByRole("searchbox", { name: "Search the CaseOps guide" });
  await search.fill("deadline control");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("product-guide-stale")).toContainText("search is using the current guide");
  const deadlineLink = page.getByRole("link", { name: /Deadline control/ });
  await expect(deadlineLink).toHaveAttribute("href", "/app/ip/docket");
  await deadlineLink.click();
  await expect(page).toHaveURL(/\/app\/ip\/docket$/);

  await page.goto("/guide");
  await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).fill("platform admin");
  await page.getByRole("button", { name: "Search" }).click();
  const permission = page.getByTestId("product-guide-permission");
  await expect(permission).toContainText("This task needs additional workspace access.");
  await expect(permission).toContainText("Required access: Platform admin");
  await expect(page.getByRole("link", { name: /Platform admin/ })).toHaveCount(0);

  await search.fill("xylophone nebula quasar");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByTestId("product-guide-no-match")).toContainText(
    "does not have approved guidance",
  );
  await page.getByRole("button", { name: "research" }).click();
  await expect(page.getByTestId("product-guide-results")).toContainText("Research");

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/guide");
  const tool = page.getByTestId("product-guide-search");
  await expect(tool).toBeVisible();
  const inputBox = await page.getByRole("searchbox", { name: "Search the CaseOps guide" }).boundingBox();
  expect(inputBox?.width ?? 0).toBeGreaterThan(250);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1),
  ).toBe(false);
});
