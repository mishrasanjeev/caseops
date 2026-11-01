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
 *
 * Client portal: in production Ram opens every client grant offered and each
 * one must load its shareable versions or explain why there are none, never
 * fail. Locally ([local-only], fresh tenant, no real email) Ram uploads and
 * approves an evidence document, grants a client the evidence category,
 * publishes exactly that version and revokes the grant, all through the UI.
 */
import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

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

/** Labels that ask a lawyer to type an internal record id ("... ID"). */
async function internalIdFields(scope: Locator): Promise<string[]> {
  const labels = await scope.locator("label").allInnerTexts();
  return labels.map((label) => label.trim()).filter((label) => /\bIDs?$/.test(label));
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
      .toHaveAttribute("href", `/app/ip?docket=${record.docket_id}&tab=documents`);
    await expect(page.getByRole("combobox", { name: "Linked deadline" })).toBeDisabled();
    // A fee transaction needs an active cost; on an empty docket it is not offered.
    await expect(page.getByRole("option", { name: /Fee recorded/ })).toHaveJSProperty("disabled", true);
    expect(await deadSelects(page, page.locator("main"))).toEqual([]);
    expect(await internalIdFields(page.locator("main"))).toEqual([]);
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

type GrantRow = { id: string; publishable: boolean; publication_blocked_reason: string | null };

test("BUG-015 client portal: every offered grant loads its shareable versions or says why there are none", async ({ page, request }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL);
  const grantsResponse = page.waitForResponse(apiResponse(rt, "GET", /\/api\/admin\/portal\/ip-grants$/));
  await page.goto(`${rt.web.origin}/app/ip/client-portal`);
  const { grants } = await json<{ grants: GrantRow[] }>(await grantsResponse, "Read portal grants");
  const version = page.getByRole("combobox", { name: "Approved version" });
  await expect(version).toBeDisabled();
  await expect(version.locator("option").first()).toHaveText("Choose a client grant first");
  await expect(page.getByRole("combobox", { name: "IP docket" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Approved document categories" })).toBeVisible();
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);

  // The grant choice offers exactly the grants the API says publishing accepts
  // (production retains closed-docket grants from earlier runs; none may appear).
  const grantSelect = page.getByRole("combobox", { name: "Client grant" });
  const offered = (await grantSelect.locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value))).filter(Boolean);
  expect(offered.sort()).toEqual(grants.filter((row) => row.publishable).map((row) => row.id).sort());
  for (const grantId of offered.slice(0, 8)) {
    const shareable = page.waitForResponse(apiResponse(rt, "GET", new RegExp(`/api/ip/portal/grants/${grantId}/shareable-documents$`)));
    await grantSelect.selectOption(grantId);
    const body = await json<{ documents: unknown[] }>(await shareable, `Shareable versions for grant ${grantId}`);
    if (body.documents.length) await expect(version).toBeEnabled();
    else await expect(version.locator("option").first()).toHaveText("No shareable version on this docket");
    await expect(page.locator("#publication-document-hint [role=alert]")).toHaveCount(0);
  }
  await markPositive(info, "client-portal-controls", { local: rt.local, grantsChecked: Math.min(offered.length, 8) });
});

test("BUG-015 client portal [local-only]: Ram publishes exactly the approved evidence version a new grant can receive", async ({ page, request }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL);
  expect(rt.local, "This journey invites a client; it runs only in a fresh local tenant").toBe(true);
  const title = stamp("PORTALDOC");
  const basic = await createBasicMark(page, rt, title);
  try {
    // The Madrid/portal upload links land on the Documents tab with this docket chosen.
    await page.goto(`${rt.web.origin}/app/ip?docket=${basic.docketId}&tab=documents`);
    await expect(page.getByRole("tab", { name: "Documents", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.getByLabel("Original file", { exact: true }).setInputFiles({
      name: `${title}.txt`, mimeType: "text/plain", buffer: Buffer.from(`Registry evidence for ${title}. `.repeat(40)),
    });
    await page.getByLabel("Title", { exact: true }).fill(`Evidence ${title}`);
    await page.getByLabel("Client code", { exact: true }).fill("TESTLEGAL");
    await page.getByLabel("Mark", { exact: true }).fill(title.split(" ")[0]);
    await page.getByLabel("Classification", { exact: true }).selectOption("evidence");
    await expect(page.getByLabel("Linked docket", { exact: true })).toHaveValue(basic.docketId);
    await page.getByRole("button", { name: "Preview controlled name" }).click();
    await expect(page.getByText("Controlled name preview", { exact: true })).toBeVisible();
    const uploaded = page.waitForResponse(apiResponse(rt, "POST", /\/api\/ip\/documents\/upload$/));
    await page.getByRole("button", { name: "Upload reviewed document" }).click();
    const upload = await json<{ document: { id: string; versions: Array<{ version: number }> } }>(await uploaded, "Upload evidence");
    const documentId = upload.document.id;
    const card = page.getByTestId(`ip-document-${documentId}`);
    for (const state of ["review", "approved"]) {
      const moved = page.waitForResponse(apiResponse(rt, "POST", new RegExp(`/api/ip/documents/${documentId}/versions/1/transition$`)));
      await card.getByRole("button", { name: `Move to ${state}` }).click();
      await json(await moved, `Move evidence to ${state}`);
      await expect(card.getByText(`${state} · v1`)).toBeVisible();
    }

    await page.goto(`${rt.web.origin}/app/ip/client-portal`);
    const clientName = `Client ${title}`;
    await page.getByLabel("Client name").fill(clientName);
    await page.getByLabel("Work email").fill(`client-${rt.run.toLowerCase().replace(/[^a-z0-9-]/g, "-")}@example.com`);
    await page.getByLabel("Find the client's docket").fill(title);
    const docket = page.getByRole("combobox", { name: "IP docket" });
    await expect(docket.locator(`option[value="${basic.docketId}"]`)).toHaveCount(1);
    await docket.selectOption(basic.docketId);
    await expect(page.getByRole("checkbox", { name: "Evidence" })).toBeChecked();
    const invited = page.waitForResponse(apiResponse(rt, "POST", /\/api\/admin\/portal\/invitations$/));
    await page.getByRole("button", { name: "Grant access" }).click();
    const invitation = await json<{ grants: Array<{ id: string; ip_docket_record_id: string | null }> }>(await invited, "Grant client access", 201);
    const grant = invitation.grants.find((row) => row.ip_docket_record_id === basic.docketId);
    expect(grant, "The new grant covers the chosen docket").toBeTruthy();

    const grantSelect = page.getByRole("combobox", { name: "Client grant" });
    await expect(grantSelect.locator(`option[value="${grant!.id}"]`)).toHaveCount(1);
    const shareable = page.waitForResponse(apiResponse(rt, "GET", new RegExp(`/api/ip/portal/grants/${grant!.id}/shareable-documents$`)));
    await grantSelect.selectOption(grant!.id);
    const listed = await json<{ documents: Array<{ document_id: string; version_number: number }> }>(await shareable, "Shareable versions");
    expect(listed.documents.map((row) => `${row.document_id}:${row.version_number}`)).toEqual([`${documentId}:1`]);
    const version = page.getByRole("combobox", { name: "Approved version" });
    await expect(version).toBeEnabled();
    expect((await version.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))))
      .toEqual(["", `${documentId}:1`]);
    await version.selectOption(`${documentId}:1`);
    await page.getByLabel("Client title").fill(`Evidence for ${clientName}`);
    const published = page.waitForResponse(apiResponse(rt, "POST", /\/api\/ip\/portal\/document-publications$/));
    await page.getByRole("button", { name: "Publish approved version" }).click();
    const publication = await json<{ id: string }>(await published, "Publish approved evidence", 201);
    expect(publication.id).toBeTruthy();
    expect(await deadSelects(page, page.locator("main"))).toEqual([]);

    await page.getByLabel(`Revocation reason for ${clientName}`).fill("Acceptance client access removed after verification.");
    const revoked = page.waitForResponse(apiResponse(rt, "POST", new RegExp(`/api/admin/portal/ip-grants/${grant!.id}/revoke$`)));
    await page.getByRole("button", { name: "Revoke" }).click();
    const revokedGrant = await json<{ publishable: boolean; publication_blocked_reason: string | null }>(await revoked, "Revoke client grant");
    expect([revokedGrant.publishable, revokedGrant.publication_blocked_reason]).toEqual([false, "revoked"]);
    await expect(grantSelect.locator(`option[value="${grant!.id}"]`)).toHaveCount(0);
    await markPositive(info, "client-portal-publish", { local: rt.local, publication: publication.id });
  } finally {
    await closeDocket(page, rt, basic.docketId, "Acceptance portal docket retired after verification.");
  }
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

test("BUG-015 sweep: Madrid, client portal, renewals and reports ask for no internal record ID", async ({ page, request }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, info.project.use.baseURL);
  for (const route of ["/app/ip/madrid", "/app/ip/client-portal", "/app/ip/renewals", "/app/ip/reports"]) {
    await page.goto(`${rt.web.origin}${route}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await internalIdFields(page.locator("main")), route).toEqual([]);
    expect(await deadSelects(page, page.locator("main")), route).toEqual([]);
  }
  await markPositive(info, "lane-no-id-fields", { local: rt.local });
});
