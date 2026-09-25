import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot, webBaseUrl } from "./support/env";
import { plusDays } from "./support/helpers";

const web = process.env.PROD_BASE_URL || webBaseUrl;
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const isProduction = Boolean(process.env.PROD_BASE_URL || process.env.CASEOPS_PROD_TEST_SLUG);
const fixtureRoot = path.join(repoRoot, "tests", "fixtures");
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
  const code = `${BULK_CODE}-${randomUUID().slice(0, 8).toUpperCase()}`;
  const bulkFilename = `matter-bulk-update-${code}.csv`;
  const matter = await ensureMatter(request, auth.headers, code, "Bulk update baseline", hearingDate);

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
  const docxFrame = page.frameLocator('[data-testid="docx-preview-frame"]');
  await expect(docxFrame.getByText("CaseOps DOCX preview acceptance", { exact: true })).toBeVisible();
  await expect(docxFrame.getByText("This text must be visible inside the authenticated document viewer.", { exact: true })).toBeVisible();
  await expect(docxFrame.getByText("Verified", { exact: true })).toBeVisible();

  const imageUpload = await request.post(`${api}/api/matters/${matter.id}/attachments`, {
    headers: auth.headers,
    multipart: {
      file: {
        name: "matter-inline-view.png",
        mimeType: "image/png",
        buffer: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p5sAAAAASUVORK5CYII=",
          "base64",
        ),
      },
    },
  });
  expect(imageUpload.status(), await imageUpload.text()).toBe(200);
  const imageAttachment = (await imageUpload.json()) as { id: string };
  await page.goto(`${web}/app/matters/${matter.id}/documents/${imageAttachment.id}/view`);
  const image = page.getByRole("img", { name: "matter-inline-view.png" });
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${web}/app/matters/${matter.id}/documents`);
  const documentScroller = page.getByTestId("matter-document-group-unclassified").locator(".overflow-x-auto");
  await expect(documentScroller).toBeVisible();
  await expect(page.getByTestId(`matter-attachment-view-${attachment.id}`)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // 2026-09-25 production shape: the persistent QA tenant retained an earlier upload
  // with the same filename, and `.first()` expanded it instead of this run's operation.
  // The per-run filename avoids other runs' history; seeding a same-name operation here
  // keeps that ambiguity in every environment, so this upload is followed by operation ID.
  const csvEscape = (value: string) => `"${value.replaceAll('"', '""')}"`;
  const bulkCsvFor = (header: string, rows: Array<Record<string, string>>) => {
    const columns = header.replace(/^\uFEFF/, "").split(",");
    const lines = rows.map((row) => columns.map((column) => csvEscape(row[column] ?? "")).join(","));
    return Buffer.from(`${header}\r\n${lines.join("\r\n")}\r\n`, "utf-8");
  };
  const apiTemplate = await request.get(`${api}/api/matters/bulk-update/template?format=csv`, { headers: auth.headers });
  expect(apiTemplate.status(), await apiTemplate.text()).toBe(200);
  const apiHeader = (await apiTemplate.text()).split(/\r?\n/, 1)[0] ?? "";
  const retainedCsv = bulkCsvFor(apiHeader, [{ "Matter Code": code, "Matter Title": "Bulk update retained prior title" }]);
  const retainedPreview = await request.post(`${api}/api/matters/bulk-update/preview`, {
    headers: auth.headers,
    multipart: { file: { name: bulkFilename, mimeType: "text/csv", buffer: retainedCsv } },
  });
  expect(retainedPreview.status(), await retainedPreview.text()).toBe(200);
  const retainedApply = await request.post(`${api}/api/matters/bulk-update/apply`, {
    headers: auth.headers,
    multipart: {
      preview_token: ((await retainedPreview.json()) as { preview_token: string }).preview_token,
      file: { name: bulkFilename, mimeType: "text/csv", buffer: retainedCsv },
    },
  });
  expect(retainedApply.status(), await retainedApply.text()).toBe(200);
  const retainedOperationId = ((await retainedApply.json()) as { operation_id: string }).operation_id;
  expect(retainedOperationId).toBeTruthy();

  await page.goto(`${web}/app/matters/bulk-update`);
  await expect(page.getByTestId(`bulk-update-operation-${retainedOperationId}`)).toBeVisible();
  const templateDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "XLSX", exact: true }).click();
  expect((await templateDownload).suggestedFilename()).toBe("matter-bulk-update-template.xlsx");
  const csvDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV", exact: true }).click();
  const csvTemplate = await csvDownload;
  expect(csvTemplate.suggestedFilename()).toBe("matter-bulk-update-template.csv");
  const templateStream = await csvTemplate.createReadStream();
  const templateChunks: Buffer[] = [];
  for await (const chunk of templateStream) templateChunks.push(Buffer.from(chunk));
  const header = Buffer.concat(templateChunks).toString("utf-8").split(/\r?\n/, 1)[0] ?? "";
  const values = header.replace(/^\uFEFF/, "").split(",").map((column) => {
    if (column === "Matter Title") return "Bulk update Playwright title";
    if (column === "Matter Code") return code;
    return "";
  });
  const unknownCode = `BULK-UNKNOWN-${randomUUID().slice(0, 8).toUpperCase()}`;
  const invalidValues = header.replace(/^\uFEFF/, "").split(",").map((column) => {
    if (column === "Matter Title") return "Must not be created";
    if (column === "Matter Code") return unknownCode;
    return "";
  });
  const bulkCsv = Buffer.from(`${header}\r\n${values.map(csvEscape).join(",")}\r\n${invalidValues.map(csvEscape).join(",")}\r\n`, "utf-8");
  await page.locator('input[type="file"]').setInputFiles({
    name: bulkFilename,
    mimeType: "text/csv",
    buffer: bulkCsv,
  });
  await page.getByRole("button", { name: "Preview changes" }).click();
  await expect(page.getByTestId("bulk-update-summary")).toContainText("1 changed");
  await expect(page.getByTestId("bulk-update-summary")).toContainText("1 invalid");
  const applyResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && new URL(response.url()).pathname === "/api/matters/bulk-update/apply");
  await page.getByRole("button", { name: "Apply reviewed changes" }).click();
  const applied = await applyResponse;
  expect(applied.status(), await applied.text()).toBe(200);
  const operationId = ((await applied.json()) as { operation_id: string }).operation_id;
  expect(operationId).toBeTruthy();
  expect(operationId).not.toBe(retainedOperationId);
  await expect(page.getByText(/Updated 1 of 2 rows; 1 skipped, 0 failed\./)).toBeVisible();
  await expect(page.getByTestId("bulk-update-final-result")).toContainText("2 rows");
  await expect(page.getByTestId("bulk-update-final-result")).toContainText("1 updated");
  await expect(page.getByTestId("bulk-update-final-result")).toContainText("1 skipped");
  await expect(page.getByRole("button", { name: "Apply reviewed changes" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Operation history" })).toBeVisible();
  const operationRow = page.getByTestId(`bulk-update-operation-${operationId}`);
  await expect(operationRow).toBeVisible();
  await expect(operationRow).toHaveAttribute("aria-current", "true");
  await expect(operationRow.getByRole("cell").first()).toHaveText(`${bulkFilename}This upload`);
  const retainedRow = page.getByTestId(`bulk-update-operation-${retainedOperationId}`);
  await expect(retainedRow).toBeVisible();
  await expect(retainedRow).not.toHaveAttribute("aria-current", "true");
  const viewResults = operationRow.getByRole("button", { name: `View results for ${bulkFilename} uploaded ` });
  await expect(viewResults).toHaveAccessibleName(new RegExp(`, operation ${operationId}$`));
  await expect(page.getByRole("button", { name: `operation ${operationId}` })).toHaveCount(2);
  await viewResults.click();
  const operationResults = page.getByTestId(`bulk-update-operation-results-${operationId}`);
  await expect(operationResults.getByRole("listitem")).toHaveCount(2);
  await expect(operationResults.getByText(`Row 2: ${code} — applied`, { exact: false })).toBeVisible();
  await expect(operationResults.getByText(`Row 3: ${unknownCode} — invalid`, { exact: false })).toBeVisible();
  await expect(page.getByTestId(`bulk-update-operation-results-${retainedOperationId}`)).toHaveCount(0);
  const resultDownload = page.waitForEvent("download");
  await operationRow.getByRole("button", { name: `Download results for ${bulkFilename} uploaded ` }).click();
  const downloadedResult = await resultDownload;
  expect(downloadedResult.suggestedFilename()).toBe(`matter-bulk-update-${operationId}-results.csv`);
  const resultStream = await downloadedResult.createReadStream();
  const resultChunks: Buffer[] = [];
  for await (const chunk of resultStream) resultChunks.push(Buffer.from(chunk));
  const resultText = Buffer.concat(resultChunks).toString("utf-8");
  expect(resultText).toContain(`${code}`);
  expect(resultText).toContain(`${unknownCode}`);
  expect(resultText).toContain("Matter Code must match one existing matter");
  const missing = await request.get(`${api}/api/matters/?q=${encodeURIComponent(unknownCode)}`, { headers: auth.headers });
  expect(missing.status(), await missing.text()).toBe(200);
  expect(((await missing.json()) as { matters: Matter[] }).matters.some((row) => row.matter_code === unknownCode)).toBe(false);
  await page.goto(`${web}/app/matters/${matter.id}`);
  await expect(page.getByText("Bulk update Playwright title", { exact: true })).toBeVisible();

  await page.goto(`${web}/app/admin/provider-operations`);
  await expect(page.getByRole("heading", { name: "Provider operations", exact: true })).toBeVisible();
  await expect(page.getByText("Could not load provider operations")).toHaveCount(0);
  await page.goto(`${web}/app/admin/integrations`);
  await expect(page.getByRole("heading", { name: /Integrations/i }).first()).toBeVisible();
  await expect(page.getByText("Readiness, configuration names, and delivery gates for workspace connectors.")).toBeVisible();
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
  expect(created).toBeDefined();
  expect(created?.next_hearing_on).toBe(hearingDate);

  await page.goto(`${web}/app/hearings`);
  await page.getByLabel("Exact hearing date").fill(hearingDate);
  await expect(page.getByText("New matter hearing regression", { exact: true }).first()).toBeVisible();
  await page.goto(`${web}/app/calendar`);
  await page.getByRole("tab", { name: "week" }).click();
  const calendarDay = page.getByTestId(`calendar-week-day-${hearingDate}`);
  if ((await calendarDay.count()) === 0) {
    await page.getByTestId("calendar-next-month").click();
  }
  await expect(calendarDay).toBeVisible();
  const calendarEvent = calendarDay.locator(`a[href="/app/matters/${created!.id}/hearings"]`).first();
  await expect(calendarEvent).toBeVisible();
  await expect(calendarEvent).toHaveAttribute("title", /New matter hearing regression.*Next hearing/);

  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto(`${web}/app/matters/${created!.id}/tasks`);
  await expect(page.getByLabel("Task")).toBeVisible();
  await expect(page.getByLabel("Deadline", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(600);
  expect(await page.getByLabel("Task").evaluate((element: HTMLInputElement) => element.getBoundingClientRect().width)).toBeGreaterThan(160);
  await page.goto(`${web}/app/cause-list`);
  await page.locator("label").filter({ hasText: /^From$/ }).locator("input").fill(hearingDate);
  await page.locator("label").filter({ hasText: /^To$/ }).locator("input").fill(hearingDate);
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText("New matter hearing regression", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(hearingDate, { exact: true }).first()).toBeVisible();
});
