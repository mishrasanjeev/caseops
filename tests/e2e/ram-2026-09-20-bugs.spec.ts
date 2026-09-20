import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { plusDays } from "./support/helpers";

const RUN_ID = randomUUID().slice(0, 8);
const SLUG = `ram-sep20-${RUN_ID}`;
const EMAIL = `${SLUG}@example.com`;
const PASSWORD = `RamSep20-${RUN_ID}!`;

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL("**/app");
}

test("Ram 2026-09-20 dashboard counts, hearing filters, follow-up queues and court handoff", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const bootstrap = await request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Ram Sep20 ${RUN_ID}`,
      company_slug: SLUG,
      company_type: "law_firm",
      owner_full_name: "Ram Sep20 Owner",
      owner_email: EMAIL,
      owner_password: PASSWORD,
    },
  });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  const token = ((await bootstrap.json()) as { access_token: string }).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  const exactDate = plusDays(2);
  const overdueDate = plusDays(-1);
  let linkedMatterId = "";

  for (let index = 0; index < 52; index += 1) {
    const create = await request.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: `Sep20 dashboard active ${index}`,
        matter_code: `S20-A-${index.toString().padStart(2, "0")}`,
        practice_area: "Civil",
        forum_level: "high_court",
        status: "active",
        court_name: "Delhi High Court",
        case_number: index === 0 ? `WP(C) ${RUN_ID}/2026` : undefined,
        client_name: "Regression Client",
        opposing_party: "Regression Opponent",
        next_hearing_on: index < 6 ? exactDate : undefined,
      },
    });
    expect(create.status(), await create.text()).toBe(200);
    if (index === 0) linkedMatterId = ((await create.json()) as { id: string }).id;
  }
  const overdue = await request.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      title: "Sep20 overdue hearing",
      matter_code: "S20-OVERDUE",
      practice_area: "Civil",
      forum_level: "high_court",
      status: "active",
      court_name: "Delhi High Court",
      client_name: "Regression Client",
      opposing_party: "Regression Opponent",
      next_hearing_on: overdueDate,
    },
  });
  expect(overdue.status(), await overdue.text()).toBe(200);
  for (let index = 0; index < 3; index += 1) {
    const intake = await request.post(`${apiBaseUrl}/api/matters/`, {
      headers,
      data: {
        title: `Sep20 dashboard intake ${index}`,
        matter_code: `S20-I-${index}`,
        practice_area: "Civil",
        forum_level: "high_court",
        status: "intake",
        court_name: "Delhi High Court",
        client_name: "Regression Client",
        opposing_party: "Regression Opponent",
      },
    });
    expect(intake.status(), await intake.text()).toBe(200);
  }

  await signIn(page);
  await expect(page.getByRole("heading", { name: /Good to have you back/i })).toBeVisible();
  await expect(page.getByText("53", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("56 total in workspace", { exact: true })).toBeVisible();
  await expect(page.getByText("6", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("3", { exact: true }).first()).toBeVisible();

  await page.goto("/app/hearings");
  await page.getByLabel("Exact hearing date").fill(exactDate);
  await expect(page.getByRole("heading", { name: /Past listing date \(1\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Missing hearing date \(46\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /2026 \(6\)/ })).toBeVisible();
  await expect(page.getByText("Sep20 dashboard active 0")).toBeVisible();
  await expect(page.getByText("Sep20 overdue hearing")).toBeVisible();

  await page.goto(`/app/matters/${linkedMatterId}`);
  const courtLink = page.getByRole("link", { name: "Delhi High Court" }).first();
  await expect(courtLink).toHaveAttribute("target", "_blank");
  await expect(courtLink).toHaveAttribute("href", /\/app\/case-tracking\?/);
});
