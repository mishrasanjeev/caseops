/**
 * BUG-015 family on /app/ip/madrid and /app/ip/client-portal (Ram 2026-10-31,
 * CaseOps_Bugs (4).xlsx; production crawl found "Basic mark docket", "Basic
 * Indian application", "Linked document", "Linked deadline" and "Approved
 * version" as enabled selects with no real option).
 *
 * Signed in as the reporting tester in their own tenant (a fresh
 * test-legal-shaped tenant locally, test-legal in production), Ram creates a
 * basic Indian trademark through the docket UI, then records an outbound
 * Madrid registration choosing that docket through the docket picker and its
 * Indian application from the validator-backed list. Both dockets are closed
 * afterwards. Nothing the bug is about is created through the API.
 */
import { expect, test, type Page, type Response } from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const MOBILE = { width: 393, height: 851 };

function apiResponse(rt: TesterRuntime, method: string, path: RegExp) {
  return (response: Response) => {
    const url = new URL(response.url());
    return url.origin === rt.api.origin && response.request().method() === method && path.test(url.pathname);
  };
}

/** Ram's basic Indian trademark, created through the docket UI (the prerequisite path Ram uses). */
async function createBasicMark(page: Page, rt: TesterRuntime, title: string) {
  await page.goto(`${rt.web.origin}/app/ip`);
  await page.getByRole("button", { name: "New trademark" }).click();
  const form = page.locator("form").filter({ has: page.getByLabel("Docket title") });
  await form.getByLabel("Docket title").fill(title);
  await form.getByLabel("Word mark").fill(title.split(" ")[0]);
  await form.getByLabel("Nice class").fill("9");
  await form.getByLabel("Goods / services specification").fill("Downloadable legal research software");
  await form.getByLabel("Applicant").fill("Test Legal LLP");
  await form.getByLabel("Representation evidence reference").fill(`attachment:${title}`);
  const created = page.waitForResponse(apiResponse(rt, "POST", /\/api\/ip\/trademark-applications\/manual$/));
  await form.getByRole("button", { name: "Create application" }).click();
  const body = await json<{ docket: { id: string }; application: { id: string; jurisdiction: string } }>(
    await created, "Create basic Indian trademark", 201);
  expect(body.application.jurisdiction).toBe("IN");
  await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
  return { docketId: body.docket.id, applicationId: body.application.id };
}

async function closeDocket(page: Page, rt: TesterRuntime, docketId: string, reason: string) {
  const docket = await json<{ lifecycle_version: number }>(
    await page.request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Read docket for close");
  await json(await page.request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle`, { headers: rt.headers, data: {
    expected_lifecycle_version: docket.lifecycle_version, to_status: "closed", effective_at: new Date().toISOString(),
    reason, outcome: "closed", source: "lawyer_review", evidence_ref: `acceptance:${rt.run}`, linked_matter_handling: "not_linked",
  } }), "Close acceptance docket");
}

async function openMadridIntake(page: Page, rt: TesterRuntime) {
  await page.goto(`${rt.web.origin}/app/ip/madrid`);
  await page.getByRole("button", { name: "New record" }).click();
  return page.locator("form").filter({ has: page.getByRole("button", { name: "Create record" }) });
}

test("BUG-015 Madrid: Ram records an outbound IR choosing the basic mark docket through the picker", async ({ page, request }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL);
  const title = stamp("MADRIDBASE");
  const basic = await createBasicMark(page, rt, title);
  let madridDocketId: string | null = null;
  try {
    const intake = await openMadridIntake(page, rt);
    const application = intake.getByRole("combobox", { name: "Basic Indian application" });
    // Before a docket is chosen, the application choice is disabled and says why.
    await expect(application).toBeDisabled();
    await expect(application.locator("option").first()).toHaveText("Choose the basic mark docket first");
    expect(await deadSelects(page, intake)).toEqual([]);

    await intake.getByLabel("Find the basic mark docket").fill(title);
    const docket = intake.getByRole("combobox", { name: "Basic mark docket" });
    await expect(docket.locator(`option[value="${basic.docketId}"]`)).toHaveCount(1);
    // The picker never selects on its own.
    await expect(docket).toHaveValue("");
    await docket.selectOption(basic.docketId);
    await expect(application).toBeEnabled();
    await expect(application.locator(`option[value="${basic.applicationId}"]`)).toHaveCount(1);
    await application.selectOption(basic.applicationId);
    await expectOnScreen(application, "The chosen basic application is in view");

    const mark = title;
    const irTitle = stamp("MADRIDIR");
    await intake.getByLabel("Docket title").fill(irTitle);
    await intake.getByLabel("Mark", { exact: true }).fill(mark);
    await intake.getByLabel("Holder").fill("Test Legal LLP");
    await intake.getByLabel("WIPO reference").fill(`WIPO-${rt.run}`);
    await intake.getByLabel("Nice classes").fill("Class 9, 42");
    await intake.getByLabel("Class 9 goods/services").fill("Downloadable legal research software");
    await intake.getByLabel("Class 42 goods/services").fill("Legal research software as a service");
    await intake.getByLabel("Source URL").fill("https://www.wipo.int/madrid/monitor/en/");
    await intake.getByLabel("Source reference").fill(`acceptance:${irTitle}`);
    const created = page.waitForResponse(apiResponse(rt, "POST", /\/api\/ip\/international-registrations$/));
    await intake.getByRole("button", { name: "Create record" }).click();
    const record = await json<{ id: string; docket_id: string; basic_application_id: string; classes_json: number[] }>(
      await created, "Create Madrid record", 201);
    madridDocketId = record.docket_id;
    expect(record.basic_application_id).toBe(basic.applicationId);
    expect(record.classes_json).toEqual([9, 42]);

    // The new record is selected and its evidence selects are honest about the empty docket.
    await expect(page.getByRole("heading", { name: mark, exact: true })).toBeVisible();
    const linkedDocument = page.getByRole("combobox", { name: "Linked document" });
    await expect(linkedDocument).toBeDisabled();
    await expect(page.getByRole("link", { name: "Upload one in the IP workspace Documents tab" }))
      .toHaveAttribute("href", `/app/ip?docket=${record.docket_id}`);
    await expect(page.getByRole("combobox", { name: "Linked deadline" })).toBeDisabled();
    expect(await deadSelects(page, page.locator("main"))).toEqual([]);
    const stored = await json<{ basic_application_id: string }>(await page.request.get(
      `${rt.api.origin}/api/ip/international-registrations/${record.id}`, { headers: rt.headers }), "Read Madrid record");
    expect(stored.basic_application_id).toBe(basic.applicationId);
    await markPositive(info, "madrid-picker-create", { local: rt.local, record: record.id });
  } finally {
    if (madridDocketId) await closeDocket(page, rt, madridDocketId, "Acceptance Madrid record retired after verification.");
    await closeDocket(page, rt, basic.docketId, "Acceptance basic mark retired after verification.");
  }
});

test("BUG-015 Madrid [mobile]: intake pickers fit a phone and never offer a dead choice", async ({ page, request }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL, MOBILE);
  const intake = await openMadridIntake(page, rt);
  const docket = intake.getByRole("combobox", { name: "Basic mark docket" });
  await expect(docket).toBeVisible();
  const application = intake.getByRole("combobox", { name: "Basic Indian application" });
  await application.scrollIntoViewIfNeeded();
  await expectOnScreen(application, "The basic application field is reachable on a phone");
  await expect(application).toBeDisabled();
  await expect(application.locator("option").first()).toHaveText("Choose the basic mark docket first");
  await expectNoPageOverflow(page);
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);
  await markPositive(info, "madrid-mobile", { local: rt.local });
});

test("BUG-015 client portal: the approved-version choice waits for a grant and never offers a dead select", async ({ page, request }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL);
  const grants = page.waitForResponse(apiResponse(rt, "GET", /\/api\/admin\/portal\/ip-grants$/));
  await page.goto(`${rt.web.origin}/app/ip/client-portal`);
  await json(await grants, "Read portal grants");
  const version = page.getByRole("combobox", { name: "Approved version" });
  await expect(version).toBeDisabled();
  await expect(version.locator("option").first()).toHaveText("Choose a client grant first");
  await expect(page.getByRole("combobox", { name: "IP docket" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Approved document categories" })).toBeVisible();
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);
  await markPositive(info, "client-portal-controls", { local: rt.local });
});

test("BUG-015 client portal [mobile]: grant and publish controls fit a phone", async ({ page, request }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL, MOBILE);
  await page.goto(`${rt.web.origin}/app/ip/client-portal`);
  const version = page.getByRole("combobox", { name: "Approved version" });
  await version.scrollIntoViewIfNeeded();
  await expectOnScreen(version, "The approved-version field is reachable on a phone");
  await expect(version).toBeDisabled();
  await expectNoPageOverflow(page);
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);
  await markPositive(info, "client-portal-mobile", { local: rt.local });
});
