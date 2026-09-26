import { randomUUID } from "node:crypto";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, webBaseUrl } from "./support/env";
import { collectFormLayoutOffenders } from "./support/form-layout";
import { plusDays } from "./support/helpers";

/**
 * Ram workbook (IV), 2026-09-26.
 *
 * BUG-032  Case Tracking called a Matter's own eCourts case "Does not match".
 * BUG-033  Cause List PDF text overlapped adjacent columns.
 * BUG-034  Tasks & Deadlines title fields collapsed when two cards shared the row.
 *
 * Plus a product-wide form layout sweep so a squeezed field anywhere fails the
 * suite instead of waiting for a tester to find it.
 */

const web = process.env.PROD_BASE_URL || webBaseUrl;
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const isProduction = Boolean(process.env.PROD_BASE_URL || process.env.CASEOPS_PROD_TEST_SLUG);
const LONG_TITLE =
  "Satish Kumar Mehani and Another versus Punjab National Bank and Others through its Chief Manager Recovery";
const LONG_JUDGE = "Hon'ble Mr. Justice Subramonium Prasad and Hon'ble Mr. Justice Harish Vaidyanathan";
const LAYOUT_WIDTHS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1536, height: 864 },
  { width: 1920, height: 1080 },
];
// Mirrors CAUSE_LIST_PDF_HEADINGS / CAUSE_LIST_PDF_WEIGHTS in services/cause_lists.py.
const CAUSE_LIST_COLUMNS = ["Sr", "Date", "File", "Court", "Case No", "Title", "Judge", "Court/Item", "Lawyer"];
const CAUSE_LIST_WEIGHTS = [7, 18, 24, 36, 30, 58, 32, 20, 40];

type Credentials = { slug: string; email: string; password: string; headers: Record<string, string> };

async function authenticate(request: APIRequestContext): Promise<Credentials> {
  const suffix = randomUUID().slice(0, 8);
  const supplied = isProduction
    ? {
        slug: process.env.CASEOPS_PROD_TEST_SLUG ?? process.env.CASEOPS_RAM_PROD_SLUG,
        email: process.env.CASEOPS_PROD_TEST_EMAIL ?? process.env.CASEOPS_RAM_PROD_EMAIL,
        password: process.env.CASEOPS_PROD_TEST_PASSWORD ?? process.env.CASEOPS_RAM_PROD_PASSWORD,
      }
    : process.env.CASEOPS_LOCAL_TEST_SLUG
      ? {
          // A tester-supplied account recreated in local Docker (never production).
          slug: process.env.CASEOPS_LOCAL_TEST_SLUG,
          email: process.env.CASEOPS_LOCAL_TEST_EMAIL,
          password: process.env.CASEOPS_LOCAL_TEST_PASSWORD,
        }
      : { slug: `ram-sep26-${suffix}`, email: `sep26-${suffix}@example.com`, password: `Sep26-${suffix}!` };
  if (!supplied.slug || !supplied.email || !supplied.password) {
    throw new Error("Production verification credentials must be supplied at runtime.");
  }
  const credentials = { slug: supplied.slug, email: supplied.email, password: supplied.password };
  const existing = isProduction || !process.env.CASEOPS_LOCAL_TEST_SLUG
    ? null
    : await request.post(`${api}/api/auth/login`, {
        headers: noPaidProviderHeaders,
        data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
      });
  if (!isProduction && existing?.status() !== 200) {
    const bootstrap = await request.post(`${api}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders,
      data: {
        company_name: `Ram Sep26 ${suffix}`,
        company_slug: credentials.slug,
        company_type: "law_firm",
        owner_full_name: "Ram Sep26 Owner",
        owner_email: credentials.email,
        owner_password: credentials.password,
      },
    });
    expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  }
  const login = await request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
  });
  expect(login.status(), await login.text()).toBe(200);
  const token = (await login.json()).access_token as string;
  return { ...credentials, headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${token}` } };
}

async function signIn(page: Page, credentials: Credentials) {
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(credentials.slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function createMatter(
  request: APIRequestContext,
  headers: Record<string, string>,
  overrides: Record<string, unknown>,
): Promise<{ id: string; matter_code: string }> {
  const code = `SEP26-${randomUUID().slice(0, 8).toUpperCase()}`;
  const response = await request.post(`${api}/api/matters/`, {
    headers,
    data: {
      title: `Sep26 regression ${code}`,
      matter_code: code,
      practice_area: "Civil",
      forum_level: "high_court",
      status: "active",
      court_name: "Delhi High Court",
      client_name: "CaseOps QA Client",
      opposing_party: "CaseOps QA Opponent",
      ...overrides,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as { id: string; matter_code: string };
}

test.describe("Ram 2026-09-26 workbook (IV)", () => {
  test("BUG-034 task and deadline forms keep usable fields at every layout width and save", async ({ page, request }) => {
    test.setTimeout(240_000);
    const auth = await authenticate(request);
    const matter = await createMatter(request, auth.headers, {});
    await signIn(page, auth);
    for (const size of LAYOUT_WIDTHS) {
      await page.setViewportSize(size);
      await page.goto(`${web}/app/matters/${matter.id}/tasks`);
      const task = page.getByLabel("Task", { exact: true });
      const deadline = page.getByLabel("Deadline", { exact: true });
      await expect(task).toBeVisible();
      await expect(deadline).toBeVisible();
      for (const field of [task, deadline]) {
        const box = await field.boundingBox();
        expect(box?.width ?? 0, `${field} at ${size.width}px`).toBeGreaterThanOrEqual(176);
      }
      expect(await collectFormLayoutOffenders(page), `layout at ${size.width}px`).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(size.width);
    }

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${web}/app/matters/${matter.id}/tasks`);
    const taskTitle = `Prepare reply affidavit ${randomUUID().slice(0, 6)}`;
    const deadlineTitle = `File rejoinder ${randomUUID().slice(0, 6)}`;
    await page.getByLabel("Task", { exact: true }).fill(taskTitle);
    await page.getByRole("button", { name: "Add" }).first().click();
    await expect(page.getByText(taskTitle, { exact: true })).toBeVisible();
    await page.getByLabel("Deadline", { exact: true }).fill(deadlineTitle);
    await page.locator('form:has(input[placeholder="File rejoinder"]) input[type="date"]').fill(plusDays(9));
    await page.getByRole("button", { name: "Add" }).last().click();
    await expect(page.getByText(deadlineTitle, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(taskTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(deadlineTitle, { exact: true })).toBeVisible();
  });

  test("BUG-033 cause list PDF keeps every value inside its own column", async ({ page, request }) => {
    test.setTimeout(240_000);
    const auth = await authenticate(request);
    const hearingDate = plusDays(3);
    const matter = await createMatter(request, auth.headers, {
      title: LONG_TITLE,
      judge_name: LONG_JUDGE,
      court_name: "High Court of Delhi at New Delhi, Principal Bench",
      case_number: `W.P.(C) ${Math.floor(Math.random() * 9000) + 1000}/2026 with CM APPL. 12345/2026`,
    });
    const hearing = await request.post(`${api}/api/matters/${matter.id}/hearings`, {
      headers: auth.headers,
      data: {
        hearing_on: hearingDate,
        forum_name: "High Court of Delhi at New Delhi, Principal Bench",
        purpose: "Arguments",
        status: "scheduled",
      },
    });
    expect(hearing.status(), await hearing.text()).toBe(200);

    await signIn(page, auth);
    await page.goto(`${web}/app/cause-list`);
    await page.locator("label").filter({ hasText: /^From$/ }).locator("input").fill(hearingDate);
    await page.locator("label").filter({ hasText: /^To$/ }).locator("input").fill(hearingDate);
    await page.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByText(LONG_TITLE, { exact: true }).first()).toBeVisible();
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("button", { name: /PDF/ }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe(`cause-list-${hearingDate}-to-${hearingDate}.pdf`);
    const chunks: Buffer[] = [];
    for await (const chunk of await download.createReadStream()) chunks.push(Buffer.from(chunk));
    const layout = await readPdfTextRuns(Buffer.concat(chunks));

    const offenders: string[] = [];
    const titleColumn: string[] = [];
    for (const pageRuns of layout) {
      const borders = columnBorders(pageRuns.width, CAUSE_LIST_WEIGHTS);
      const headingTop = Math.max(
        ...pageRuns.runs.filter((run) => run.text === "Sr").map((run) => run.y),
        Number.NEGATIVE_INFINITY,
      );
      for (const run of pageRuns.runs) {
        if (!run.text.trim()) continue;
        if (run.x < borders[0] - 0.5 || run.x + run.width > borders.at(-1)! + 0.5) {
          offenders.push(`outside printable width: ${run.text}`);
        }
        if (run.y > headingTop + 0.5) continue;
        const column = borders.findIndex((border, index) => index > 0 && run.x < border);
        if (column < 1 || run.x + run.width > borders[column] + 0.5) {
          offenders.push(`crosses column border: ${run.text}`);
        }
        if (column - 1 === CAUSE_LIST_COLUMNS.indexOf("Title")) titleColumn.push(run.text);
      }
    }
    expect(offenders).toEqual([]);
    const compact = (value: string) => value.replace(/\s+/g, "");
    expect(compact(titleColumn.join(""))).toContain(compact(LONG_TITLE));
    for (const heading of CAUSE_LIST_COLUMNS) {
      expect(layout.some((pageRuns) => pageRuns.runs.some((run) => run.text === heading)), heading).toBe(true);
    }
  });

  test("BUG-032 case tracking recognises a Matter's own eCourts case and opens the existing Matter", async ({ page, request }) => {
    test.setTimeout(180_000);
    const auth = await authenticate(request);
    const cnr = "DLHC010091232026";
    if (isProduction) {
      // Provider search is credit-bearing. Automated production runs must prove
      // the no-paid rejection without spending; the live search is human use.
      const blocked = await request.post(`${api}/api/case-tracking/search`, {
        headers: auth.headers,
        data: { cnr_number: cnr },
      });
      expect(blocked.status(), await blocked.text()).toBe(409);
      expect((await blocked.json()).detail?.code).toBe("paid_provider_blocked_for_test");
      return;
    }
    // The Docker provider emulator publishes "Delhi High Court" with parties
    // "Local Docker Petitioner" / "Local Docker Respondent". The Matter records
    // the same CNR with different court and party wording, as in the report.
    const matter = await createMatter(request, auth.headers, {
      title: "Local Docker Petitioner v Local Docker Respondent",
      court_name: "High Court of Delhi",
      client_name: "Local Docker Petitioner & Anr.",
      opposing_party: "Local Docker Respondent and Others",
      case_number: "WP(CIVIL)/9123/2026",
      cnr_number: cnr,
    });
    await signIn(page, auth);
    await page.goto(
      `${web}/app/case-tracking?matterId=${matter.id}&cnr=${cnr}&caseNumber=${encodeURIComponent("WP(CIVIL)/9123/2026")}`,
    );
    await page.getByTestId("case-tracking-query").fill(cnr);
    await page.getByTestId("case-tracking-search-submit").click();
    const linkedOrLinkable = page.getByTestId("matter-search-linked").or(page.getByTestId("matter-search-link-submit"));
    await expect(linkedOrLinkable.first()).toBeVisible();
    await expect(page.getByTestId("matter-search-unmatched")).toHaveCount(0);
    if (await page.getByTestId("matter-search-link-submit").count()) {
      await page.getByTestId("matter-search-link-submit").click();
      await expect(page.getByTestId("matter-search-linked")).toHaveText("Linked to this Matter");
    }
    await page.reload();
    await page.getByTestId("case-tracking-query").fill(cnr);
    await page.getByTestId("case-tracking-search-submit").click();
    await expect(page.getByTestId("matter-search-linked")).toHaveText("Linked to this Matter");

    // Outside Matter scope, search points at the existing Matter instead.
    await page.goto(`${web}/app/case-tracking`);
    await page.getByTestId("case-tracking-query").fill(cnr);
    await page.getByTestId("case-tracking-search-submit").click();
    const open = page.getByTestId(`existing-matter-open-${matter.id}`);
    await expect(open).toBeVisible();
    await open.click();
    await expect(page).toHaveURL(new RegExp(`/app/matters/${matter.id}$`));
    await expect(page.getByRole("heading", { name: "Local Docker Petitioner v Local Docker Respondent" }).first()).toBeVisible();
  });
});

test.describe("Product-wide form layout sweep (2026-09-26)", () => {
  for (const size of [
    { width: 1280, height: 800 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
    { width: 390, height: 844 },
  ]) {
    test(`no squeezed or overlapping form fields at ${size.width}px`, async ({ page, request }) => {
      // Every navigable page at four widths does not fit the 40-minute production
      // job ceiling; the complete inventory runs in the local Docker suite.
      test.skip(isProduction, "Full layout inventory runs in local Docker acceptance.");
      test.setTimeout(900_000);
      const auth = await authenticate(request);
      const matter = await createMatter(request, auth.headers, {});
      await signIn(page, auth);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${web}/app`);
      // The inventory is the product's own navigation, so new pages join automatically.
      const appRoutes = await page
        .locator('aside[aria-label="Primary navigation"] a[href^="/app"]')
        .evaluateAll((links) => [...new Set(links.map((link) => link.getAttribute("href") ?? ""))]);
      await page.goto(`${web}/app/matters/${matter.id}`);
      const matterRoutes = await page
        .locator('nav[aria-label="Matter cockpit tabs"] a[href]')
        .evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""));
      const routes = [...appRoutes, ...matterRoutes].filter(Boolean);
      expect(appRoutes.length, "sidebar inventory").toBeGreaterThan(10);
      expect(matterRoutes.length, "matter tab inventory").toBeGreaterThan(10);

      await page.setViewportSize(size);
      const failures: string[] = [];
      for (const route of routes) {
        const response = await page.goto(`${web}${route}`, { waitUntil: "load" });
        if (!response || response.status() >= 400) {
          failures.push(`${route}: HTTP ${response?.status()}`);
          continue;
        }
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await expect(page.locator("main").first()).toBeVisible();
        const offenders = await collectFormLayoutOffenders(page);
        failures.push(...offenders.map((offender) => `${route}: ${offender}`));
      }
      expect(failures, `form layout at ${size.width}px across ${routes.length} pages`).toEqual([]);
    });
  }
});

type TextRun = { text: string; x: number; y: number; width: number };

async function readPdfTextRuns(data: Buffer): Promise<Array<{ width: number; runs: TextRun[] }>> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const document = await pdfjs.getDocument({ data: new Uint8Array(data), useSystemFonts: false }).promise;
  const pages = [];
  for (let number = 1; number <= document.numPages; number += 1) {
    const pdfPage = await document.getPage(number);
    const [, , width] = pdfPage.view;
    const content = await pdfPage.getTextContent();
    const runs = content.items.flatMap((item) =>
      "str" in item
        ? [{ text: item.str, x: item.transform[4], y: item.transform[5], width: item.width }]
        : [],
    );
    pages.push({ width, runs });
  }
  return pages;
}

function columnBorders(pageWidth: number, weights: number[]): number[] {
  const mm = 72 / 25.4;
  const left = 10 * mm;
  const usable = pageWidth - 20 * mm;
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const borders = [left];
  for (const weight of weights) borders.push(borders.at(-1)! + (usable * weight) / total);
  return borders;
}
