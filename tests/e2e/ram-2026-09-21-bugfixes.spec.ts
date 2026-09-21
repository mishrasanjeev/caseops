import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot } from "./support/env";
import { plusDays } from "./support/helpers";

const web = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3100";
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const isProduction = Boolean(process.env.PROD_BASE_URL || process.env.CASEOPS_PROD_TEST_SLUG);
const fixtureRoot = path.join(repoRoot, "tests", "fixtures");
const bulkFixture = path.join(fixtureRoot, "matter-bulk-update.xlsx");
const docxFixture = path.join(fixtureRoot, "matter-preview.docx");
const BULK_CODE = "BULK-UPDATE-CASEOPS";

type Matter = {
  id: string;
  matter_code: string;
  title: string;
  updated_at: string;
  next_hearing_on: string | null;
};

async function authenticate(request: import("@playwright/test").APIRequestContext) {
  const suffix = randomUUID().slice(0, 8);
  const credentials = isProduction
    ? {
        slug: process.env.CASEOPS_PROD_TEST_SLUG ?? process.env.CASEOPS_RAM_PROD_SLUG,
        email: process.env.CASEOPS_PROD_TEST_EMAIL ?? process.env.CASEOPS_RAM_PROD_EMAIL,
        password: process.env.CASEOPS_PROD_TEST_PASSWORD ?? process.env.CASEOPS_RAM_PROD_PASSWORD,
      }
    : {
        slug: `ram-sep21-${suffix}`,
        email: `sep21-${suffix}@example.com`,
        password: `Sep21-${suffix}!`,
      };
  if (!credentials.slug || !credentials.email || !credentials.password) {
    throw new Error("Production verification credentials must be supplied at runtime.");
  }
  const verifiedCredentials = {
    slug: credentials.slug,
    email: credentials.email,
    password: credentials.password,
  };
  if (!isProduction) {
    const bootstrap = await request.post(`${api}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders,
      data: {
        company_name: `Ram Sep21 ${suffix}`,
        company_slug: credentials.slug,
        company_type: "law_firm",
        owner_full_name: "Ram Sep21 Owner",
        owner_email: credentials.email,
        owner_password: credentials.password,
      },
    });
    expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  }
  const login = await request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: {
      company_slug: verifiedCredentials.slug,
      email: verifiedCredentials.email,
      password: verifiedCredentials.password,
    },
  });
  expect(login.status(), await login.text()).toBe(200);
  return {
    ...verifiedCredentials,
    headers: {
      ...noPaidProviderHeaders,
      Authorization: `Bearer ${(await login.json()).access_token as string}`,
    },
  };
}

async function ensureMatter(
  request: import("@playwright/test").APIRequestContext,
  headers: Record<string, string>,
  code: string,
  title: string,
  nextHearing: string,
): Promise<Matter> {
  const listed = await request.get(`${api}/api/matters/?q=${encodeURIComponent(code)}&limit=100`, { headers });
  expect(listed.status(), await listed.text()).toBe(200);
  const existing = ((await listed.json()) as { matters: Matter[] }).matters.find((row) => row.matter_code === code);
  if (existing) {
    const edited = await request.patch(`${api}/api/matters/${existing.id}`, {
      headers,
      data: {
        expected_updated_at: existing.updated_at,
        title,
        next_hearing_on: nextHearing,
        status: "active",
      },
    });
    expect(edited.status(), await edited.text()).toBe(200);
    return (await edited.json()) as Matter;
  }
  const created = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title,
      matter_code: code,
      practice_area: "Civil",
      forum_level: "high_court",
      status: "active",
      court_name: "Delhi High Court",
      case_number: "WP(C) 2121/2026",
      client_name: "CaseOps QA Client",
      opposing_party: "CaseOps QA Opponent",
      next_hearing_on: nextHearing,
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  return (await created.json()) as Matter;
}

async function signIn(page: import("@playwright/test").Page, credentials: { slug: string; email: string; password: string }) {
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(credentials.slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("BUG-006 DOCX is visibly rendered and ENH-007 updates only an existing matter", async ({ page, request }) => {
  test.setTimeout(240_000);
  const auth = await authenticate(request);
  const hearingDate = plusDays(4);
  const matter = await ensureMatter(request, auth.headers, BULK_CODE, "Bulk update baseline", hearingDate);

  const upload = await request.post(`${api}/api/matters/${matter.id}/attachments`, {
    headers: auth.headers,
    multipart: {
      file: {
        name: "matter-preview.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: fs.readFileSync(docxFixture),
      },
    },
  });
  expect(upload.status(), await upload.text()).toBe(200);
  const attachment = (await upload.json()) as { id: string };

  await signIn(page, auth);
  await page.goto(`${web}/app/matters/${matter.id}/documents/${attachment.id}/view`);
  await expect(page.getByText("CaseOps DOCX preview acceptance", { exact: true })).toBeVisible();
  await expect(page.getByText("This text must be visible inside the authenticated document viewer.", { exact: true })).toBeVisible();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();

  await page.goto(`${web}/app/matters/bulk-update`);
  await page.locator('input[type="file"]').setInputFiles(bulkFixture);
  await page.getByRole("button", { name: "Preview changes" }).click();
  await expect(page.getByTestId("bulk-update-summary")).toContainText("1 changed");
  await expect(page.getByTestId("bulk-update-summary")).toContainText("0 invalid");
  await page.getByRole("button", { name: "Apply reviewed changes" }).click();
  await expect(page.getByText(/Updated 1 existing matters\./)).toBeVisible();
  await page.goto(`${web}/app/matters/${matter.id}`);
  await expect(page.getByText("Bulk update Playwright title", { exact: true })).toBeVisible();
});

test("ENH-006 next hearing flows from new matter into hearings, calendar, and cause list", async ({ page, request }) => {
  test.setTimeout(180_000);
  const auth = await authenticate(request);
  const code = `SEP21-${randomUUID().slice(0, 8).toUpperCase()}`;
  const hearingDate = plusDays(5);
  await signIn(page, auth);
  await page.goto(`${web}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill("New matter hearing regression");
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Civil");
  await dialog.getByTestId("new-matter-next-hearing-on").fill(hearingDate);
  await dialog.getByRole("button", { name: /Create matter/i }).click();
  await expect(dialog).toBeHidden();

  const listed = await request.get(`${api}/api/matters/?q=${encodeURIComponent(code)}&limit=100`, { headers: auth.headers });
  expect(listed.status(), await listed.text()).toBe(200);
  const created = ((await listed.json()) as { matters: Matter[] }).matters.find((row) => row.matter_code === code);
  expect(created?.next_hearing_on).toBe(hearingDate);

  await page.goto(`${web}/app/hearings`);
  await expect(page.getByText("New matter hearing regression", { exact: true })).toBeVisible();
  await page.goto(`${web}/app/calendar`);
  await page.getByRole("tab", { name: "week" }).click();
  const calendarDay = page.getByTestId(`calendar-week-day-${hearingDate}`);
  await expect(calendarDay).toBeVisible();
  const calendarEvent = calendarDay.locator('[data-testid^="calendar-event-"]').first();
  await expect(calendarEvent).toBeVisible();
  await expect(calendarEvent).toHaveAttribute("title", /New matter hearing regression/);
  await page.goto(`${web}/app/cause-list`);
  await page.locator("label").filter({ hasText: /^From$/ }).locator("input").fill(hearingDate);
  await page.locator("label").filter({ hasText: /^To$/ }).locator("input").fill(hearingDate);
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText("New matter hearing regression", { exact: true })).toBeVisible();
  await expect(page.getByText(hearingDate, { exact: true })).toBeVisible();
});
