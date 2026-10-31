/**
 * BUG-015 / FT-099 (J03, J08, J11, IP UJ-37/44/47): signed in as the reporting
 * tester in their own tenant, every visible select or combobox on the IP,
 * billing and calendar routes must either offer a selectable option or be
 * disabled with an explanation, open inside the viewport, and no
 * lawyer-facing field may ask for an internal ID, hash or raw JSON.
 *
 * The crawl never submits anything: it only opens tabs, disclosure toggles
 * (aria-expanded) and an explicit allowlist of "New ..." form toggles, opens
 * and escapes each dropdown, and reads the DOM. It is safe on production.
 * One test per route keeps evidence granular and bounded.
 */
import {
  expect, request as playwrightRequest, test, type BrowserContext, type Locator, type Page, type Response,
} from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import {
  collectOpenPopoverOffenders, deadSelects, markPositive, prepareTester, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type Offender = { route: string; kind: string; detail: string };

const FORM_TOGGLES = [
  "New trademark", "Link Matter", "New instruction", "New recordal", "New record", "New intake", "New disclosure",
];
const TAB_NAMES = [
  "Docket", "Documents", "Domain availability", "Overview", "Proceedings", "Hearings and deadlines", "Access and links",
  "Journal intake", "Hits", "Runs", "Profiles", "Month", "Week", "Day", "Year",
];
const INTERNAL_FIELD = /\b(?:membership ids?|member ids?|uuid|sha-?256|raw (?:source )?json|json)\b/i;

const ROUTES = [
  "/app/ip", "/app/ip/portfolio", "/app/ip/renewals", "/app/ip/madrid", "/app/ip/recordals",
  "/app/ip/foreign-associates", "/app/ip/registry", "/app/ip/watch", "/app/ip/reports", "/app/ip/client-portal",
  "/app/ip/patents", "/app/ip/specialist", "/app/calendar", "/app/admin/matter-billing",
];
// The reported records, selected by server identity (production retains them).
const PROD_ROUTES = [
  "/app/ip?docket=2cc78d06-8fc5-535b-b21f-75da52914233",
  "/app/matters/56264441-dd0d-48e6-9c57-691892c63912/billing",
];

let context: BrowserContext;
let page: Page;
let rt: TesterRuntime;
const apiFailures: string[] = [];

async function settle(target: Page) {
  await target.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => undefined);
  await target.waitForTimeout(250);
}

async function clickIfVisible(target: Locator): Promise<boolean> {
  if (!(await target.isVisible().catch(() => false)) || !(await target.isEnabled().catch(() => false))) return false;
  await target.click({ timeout: 5_000 }).catch(() => undefined);
  return true;
}

async function inspect(route: string, offenders: Offender[]) {
  const main = page.locator("main");
  for (const label of await deadSelects(page, main)) offenders.push({ route, kind: "dead-select", detail: label });
  const internal = await main.evaluate((root, pattern) => {
    const re = new RegExp(pattern, "i");
    const out: string[] = [];
    for (const field of Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"))) {
      if (field.type === "hidden" || field.disabled || field.getBoundingClientRect().width === 0) continue;
      const label = field.labels?.[0]?.innerText || field.getAttribute("aria-label") || field.placeholder || "";
      if (re.test(label)) out.push(label.trim().split("\n")[0]);
    }
    return out;
  }, INTERNAL_FIELD.source);
  for (const label of internal) offenders.push({ route, kind: "internal-identifier-input", detail: label });
  const comboboxes = main.locator("button[role=combobox]");
  const total = Math.min(await comboboxes.count(), 25);
  for (let index = 0; index < total; index += 1) {
    const box = comboboxes.nth(index);
    if (!(await box.isVisible().catch(() => false)) || !(await box.isEnabled().catch(() => false))) continue;
    const name = ((await box.getAttribute("aria-label")) || (await box.innerText().catch(() => "")).trim()
      || `combobox ${index}`).slice(0, 60);
    await box.click({ timeout: 5_000 }).catch(() => undefined);
    await page.waitForTimeout(200);
    if (await page.locator("[role=listbox]").count() > 0) {
      if (await page.locator("[role=listbox] [role=option]").count() === 0) {
        offenders.push({ route, kind: "empty-combobox", detail: name });
      }
      for (const geometry of await collectOpenPopoverOffenders(page)) {
        offenders.push({ route, kind: `popover-${geometry.reason}`, detail: `${name}: ${geometry.detail}` });
      }
    }
    await page.keyboard.press("Escape");
    await page.waitForTimeout(100);
  }
}

async function crawl(path: string): Promise<Offender[]> {
  const offenders: Offender[] = [];
  await page.goto(`${rt.web.origin}${path}`);
  await settle(page);
  if (!(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1))) {
    offenders.push({ route: path, kind: "page-overflow", detail: "horizontal" });
  }
  await inspect(path, offenders);
  for (const name of FORM_TOGGLES) {
    if (await clickIfVisible(page.locator("main").getByRole("button", { name, exact: true }).first())) {
      await settle(page);
      await inspect(`${path} [${name}]`, offenders);
    }
  }
  for (const name of TAB_NAMES) {
    const tab = page.locator("main").getByRole("tab", { name, exact: true })
      .or(page.locator("main").getByRole("button", { name, exact: true })).first();
    if (await clickIfVisible(tab)) {
      await settle(page);
      await inspect(`${path} [${name}]`, offenders);
    }
  }
  const disclosures = page.locator("main button[aria-expanded=false]");
  const count = Math.min(await disclosures.count(), 10);
  for (let index = 0; index < count; index += 1) {
    if (!(await clickIfVisible(disclosures.first()))) break;
    await page.waitForTimeout(150);
  }
  if (count > 0) await inspect(`${path} [disclosures]`, offenders);
  return offenders;
}

test.beforeAll(async ({ browser }) => {
  test.setTimeout(5 * 60_000);
  // Hooks only receive worker fixtures; build the request context explicitly.
  const baseURL = test.info().project.use.baseURL;
  const api = await playwrightRequest.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, extraHTTPHeaders: noPaidProviderHeaders });
  page = await context.newPage();
  rt = await prepareTester(page, api, baseURL);
  page.on("response", (response: Response) => {
    const url = new URL(response.url());
    if (url.origin === rt.api.origin && response.status() >= 500) {
      apiFailures.push(`${response.status()} ${response.request().method()} ${url.pathname}`);
    }
  });
});

test.afterAll(async () => {
  await context?.close();
});

for (const path of [...ROUTES, ...PROD_ROUTES]) {
  test(`BUG-015 controls on ${path} are usable or explain themselves`, async ({}, info) => {
    test.setTimeout(6 * 60_000);
    test.skip(PROD_ROUTES.includes(path) && rt.local, "Reported production records exist only in test-legal.");
    const before = apiFailures.length;
    const offenders = await crawl(path);
    const failures = apiFailures.slice(before);
    await info.attach("control-crawl-offenders", { body: JSON.stringify(offenders, null, 2), contentType: "application/json" });
    await info.attach("control-crawl-api-5xx", { body: JSON.stringify(failures, null, 2), contentType: "application/json" });
    await markPositive(info, "control-crawl", { path, offenders: offenders.length, local: rt.local });
    expect(failures, "No API 5xx while a tester browses").toEqual([]);
    expect(offenders, `Dead or misleading controls:\n${offenders.map(o => `${o.route} :: ${o.kind} :: ${o.detail}`).join("\n")}`)
      .toEqual([]);
  });
}
