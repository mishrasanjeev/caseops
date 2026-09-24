import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot } from "./support/env";

const web = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3100";
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const isProduction = Boolean(process.env.PROD_BASE_URL || process.env.CASEOPS_PROD_TEST_SLUG);
const docx = fs.readFileSync(path.join(repoRoot, "tests", "fixtures", "matter-rich-preview.docx"));

test("BUG-013 renders an authenticated DOCX structurally and retains the original download", async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const suffix = randomUUID().slice(0, 8);
  const credentials = isProduction
    ? {
        slug: process.env.CASEOPS_PROD_TEST_SLUG ?? process.env.CASEOPS_RAM_PROD_SLUG,
        email: process.env.CASEOPS_PROD_TEST_EMAIL ?? process.env.CASEOPS_RAM_PROD_EMAIL,
        password: process.env.CASEOPS_PROD_TEST_PASSWORD ?? process.env.CASEOPS_RAM_PROD_PASSWORD,
      }
    : {
        slug: `docx-qa-${suffix}`,
        email: `docx-qa-${suffix}@example.com`,
        password: `Docx-QA-${suffix}!`,
      };
  if (!credentials.slug || !credentials.email || !credentials.password) {
    throw new Error("Production verification credentials must be supplied at runtime.");
  }
  if (!isProduction) {
    const bootstrap = await request.post(`${api}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders,
      data: {
        company_name: `DOCX QA ${suffix}`,
        company_slug: credentials.slug,
        company_type: "law_firm",
        owner_full_name: "DOCX QA Owner",
        owner_email: credentials.email,
        owner_password: credentials.password,
      },
    });
    expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  }
  const login = await request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: {
      company_slug: credentials.slug,
      email: credentials.email,
      password: credentials.password,
    },
  });
  expect(login.status(), await login.text()).toBe(200);
  const headers = {
    ...noPaidProviderHeaders,
    Authorization: `Bearer ${(await login.json()).access_token as string}`,
  };
  const matter = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title: `DOCX fidelity ${suffix}`,
      matter_code: `DOCX-${suffix.toUpperCase()}`,
      practice_area: "Civil",
      forum_level: "high_court",
      status: "intake",
    },
  });
  expect(matter.status(), await matter.text()).toBe(200);
  const matterId = ((await matter.json()) as { id: string }).id;
  const upload = await request.post(`${api}/api/matters/${matterId}/attachments`, {
    headers,
    multipart: {
      file: {
        name: "matter-rich-preview.docx",
        mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: docx,
      },
    },
  });
  expect(upload.status(), await upload.text()).toBe(200);
  const attachmentId = ((await upload.json()) as { id: string }).id;

  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(credentials.slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  const view = `${web}/app/matters/${matterId}/documents/${attachmentId}/view`;
  await page.goto(view);
  const frame = page.frameLocator('[data-testid="docx-preview-frame"]');
  await expect(frame.getByText("CaseOps rich DOCX acceptance")).toBeVisible();
  await expect(frame.getByText("Second page heading")).toBeVisible();
  await expect(frame.getByText("First bullet item")).toBeVisible();
  await expect(frame.getByText("Second numbered item")).toBeVisible();
  await expect(frame.getByRole("cell", { name: "Preserved" })).toBeVisible();
  await expect(frame.getByText("bold evidence")).toHaveCSS("font-weight", /(?:bold|[6-9]00)/);
  await expect(frame.getByText("italic analysis")).toHaveCSS("font-style", "italic");
  await expect(frame.getByText("underlined citation")).toHaveCSS("text-decoration-line", "underline");
  await expect(frame.getByText("Right aligned conclusion")).toHaveCSS("text-align", "right");
  expect(await frame.locator("section.docx").count()).toBeGreaterThanOrEqual(2);
  if (!isProduction) {
    await testInfo.attach("docx-desktop", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  }

  await page.reload();
  await expect(frame.getByText("Second page heading")).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("matter-rich-preview.docx");
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  expect(Buffer.concat(chunks)).toEqual(docx);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(view);
  await expect(frame.getByText("CaseOps rich DOCX acceptance")).toBeVisible();
  const frameBounds = await page.getByTestId("docx-preview-frame").boundingBox();
  expect(frameBounds).not.toBeNull();
  expect(frameBounds!.x).toBeGreaterThanOrEqual(0);
  expect(frameBounds!.x + frameBounds!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const headingBounds = await frame.getByText("CaseOps rich DOCX acceptance").boundingBox();
  expect(headingBounds).not.toBeNull();
  expect(headingBounds!.x).toBeGreaterThanOrEqual(frameBounds!.x);
  expect(headingBounds!.x + headingBounds!.width).toBeLessThanOrEqual(frameBounds!.x + frameBounds!.width);
  const wrapper = frame.locator(".docx-wrapper");
  const horizontalTravel = await wrapper.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
    return element.scrollLeft;
  });
  expect(horizontalTravel).toBeGreaterThan(0);
  await wrapper.evaluate((element) => { element.scrollLeft = 0; });
  if (!isProduction) {
    await testInfo.attach("docx-mobile", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  }
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.getByText("80%", { exact: true })).toBeVisible();
});
