/**
 * Ram 2026-10-30 (CaseOps_Bugs (4).xlsx) BUG-009, BUG-010, BUG-011, BUG-013:
 * the New foreign-associate instruction form, signed in as the reporting
 * tester.
 *
 * Production (test-legal) and local (a fresh test-legal-shaped tenant) run the
 * same walk. Its empty state is read from server data, never from a shared
 * record that earlier runs (or Ram) may have changed: Ram creates a fresh
 * Matterless IP record through the UI, so it has no Matter, quote, document or
 * client instruction, and the target is a jurisdiction whose associate_count
 * is 0 in create-options at that moment. Every empty picker must say why and
 * link to where its prerequisite is made (no enabled select holds only a
 * placeholder). Ram then makes each prerequisite through the UI, following the
 * form's own links in new tabs: adds the associate in Outside Counsel by
 * country name, records the quote inline, uploads the instruction document in
 * the record's Documents tab and records the client's written authority. He
 * creates the instruction (201) and retires what he made: the instruction is
 * cancelled and the quote voided through the UI; the counsel profile is set
 * inactive through the API, because Outside Counsel has no edit screen. The
 * stamped IP record and its document stay as inert history.
 *
 * [local-only] BUG-010: from a Matterless record Ram follows "Link a Matter"
 * into the record's Access and links view, links an operational Matter, then
 * follows the assignment blocker to Assign counsel in GBP with a budget
 * ceiling and creates a GBP instruction against it. The Matter itself is
 * created through the API (local only) because Matter creation is not what
 * these bugs are about.
 */
import {
  expect, test, type APIRequestContext, type APIResponse, type Locator, type Page, type Response, type TestInfo,
} from "@playwright/test";

import { localTransportHeaders } from "./support/cost-controls";
import {
  deadSelects, expectNoPageOverflow, expectOnScreen, markPositive, prepareTester, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";
import { retireDocumentThroughUi } from "./support/ip-documents";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const MOBILE = { width: 393, height: 851 };
const QUOTE_CURRENCY: Record<string, string> = { GB: "GBP", AU: "AUD" };
const REGIONAL_OFFICES = ["EM", "WO", "EP"];

type Jurisdiction = { code: string; name: string; associate_count: number };
type CreateOptions = {
  docket_id: string;
  target_jurisdiction: string | null;
  matter_id: string | null;
  jurisdictions: Jurisdiction[];
  associates: Array<{ id: string; name: string; filing_jurisdictions: string[] }>;
  assignment_required: boolean;
  assignments: Array<{ id: string; counsel_id: string; currency: string; compatible_estimate_ids: string[] }>;
  estimates: Array<{ id: string }>;
  client_instructions: unknown[];
  documents: Array<{ id: string; title: string }>;
  can_record_estimate: boolean;
  can_manage_counsel: boolean;
  blockers: Array<{ code: string; message: string; href: string | null }>;
};

/** Status-checked JSON from a browser or API response; bodies are never logged. */
async function ok<T = any>(response: Response | APIResponse, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

const path = (response: Response) => new URL(response.url()).pathname;
const isPost = (expected: string) => (response: Response) => response.request().method() === "POST" && path(response) === expected;
const isOptions = (target: string | null) => (response: Response) => {
  const url = new URL(response.url());
  return url.pathname.endsWith("/api/ip/foreign-associate-instructions/create-options")
    && response.request().method() === "GET"
    && url.searchParams.get("target_jurisdiction") === target;
};

/** Every page Ram opens (including the form's new tabs) carries the no-paid-provider headers. */
async function startTester(page: Page, request: APIRequestContext, baseURL: string | undefined, mobile: boolean) {
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  await page.context().setExtraHTTPHeaders(localTransportHeaders(rt.web.origin));
  return rt;
}

/** IP → New trademark: a fresh, Matterless record, created as a lawyer does. */
async function createRecordInUi(page: Page, rt: TesterRuntime) {
  const title = stamp("PINE LABS foreign filing");
  await page.goto(`${rt.web.origin}/app/ip`);
  await page.getByRole("button", { name: "New trademark" }).click();
  const card = page.locator("form").filter({ has: page.getByRole("button", { name: "Create application" }) });
  await card.getByLabel("Docket title", { exact: true }).fill(title);
  await card.getByLabel("Word mark", { exact: true }).fill("PINE");
  await card.getByLabel("Goods / services specification", { exact: true }).fill("Payment terminals and point-of-sale software");
  await card.getByLabel("Applicant", { exact: true }).fill("Pine Labs Private Limited");
  await card.getByLabel("Representation evidence reference", { exact: true }).fill(`e2e:bugs4:mark:${rt.run}`);
  const created = page.waitForResponse(isPost("/api/ip/trademark-applications/manual"));
  await card.getByRole("button", { name: "Create application" }).click();
  const body = await ok(await created, "Create the IP record through New trademark", 201);
  expect(body.docket).toMatchObject({ title, matter_id: null });
  return { docketId: body.docket.id as string, title };
}

async function followNewTab(page: Page, link: Locator): Promise<Page> {
  const [tab] = await Promise.all([page.waitForEvent("popup"), link.click()]);
  await tab.waitForLoadState("domcontentloaded");
  return tab;
}

/** Outside Counsel → Add counsel, on a tab already showing Outside Counsel. */
async function addCounsel(tab: Page, rt: TesterRuntime, name: string, jurisdictions: string): Promise<string> {
  await tab.getByTestId("new-counsel-trigger").first().click();
  const dialog = tab.getByRole("dialog", { name: "Add outside counsel to the panel" });
  await dialog.locator("#counsel-name").fill(name);
  await dialog.locator("#contact-name").fill("Filing partner");
  await dialog.locator("#contact-email").fill(`filings-${rt.run.replace(/\W/g, "").toLowerCase()}@example.com`);
  await dialog.locator("#firm-city").fill("London");
  await dialog.locator("#jurisdictions").fill(jurisdictions);
  await expect(dialog.locator("#jurisdictions-hint")).toContainText("Switzerland, not CH");
  const created = tab.waitForResponse(isPost("/api/outside-counsel/profiles"));
  await dialog.getByTestId("new-counsel-submit").click();
  const profile = await ok(await created, "Add counsel through the UI");
  await expect(dialog).toBeHidden();
  return profile.id as string;
}

/** Cleanup only: Outside Counsel has no edit screen, so the profile is set inactive through the API. */
async function retireCounsel(request: APIRequestContext, rt: TesterRuntime, counselId: string) {
  const retired = await ok(await request.patch(`${rt.api.origin}/api/outside-counsel/profiles/${counselId}`, {
    headers: rt.headers, data: { panel_status: "inactive" },
  }), "Retire the stamped counsel");
  expect(retired.panel_status).toBe("inactive");
}

async function openNewInstruction(page: Page, rt: TesterRuntime): Promise<Locator> {
  await page.goto(`${rt.web.origin}/app/ip/foreign-associates`);
  await page.getByRole("button", { name: "New instruction" }).click();
  const form = page.getByRole("form", { name: "New foreign-associate instruction" });
  await expect(form).toBeVisible();
  return form;
}

/** IpDocketPicker: server-side search, then select by server identity. */
async function chooseRecord(page: Page, form: Locator, docketId: string, search: string): Promise<CreateOptions> {
  await form.getByLabel("Find IP record").fill(search);
  const record = form.getByLabel("IP record", { exact: true });
  await expect(record.locator(`option[value="${docketId}"]`)).toHaveCount(1);
  const loaded = page.waitForResponse(isOptions(null));
  await record.selectOption(docketId);
  return ok<CreateOptions>(await loaded, "Create options for the record");
}

async function chooseJurisdiction(page: Page, form: Locator, code: string): Promise<CreateOptions> {
  const jurisdiction = form.getByLabel("Target jurisdiction");
  await expect(jurisdiction).toBeEnabled();
  const loaded = page.waitForResponse(isOptions(code));
  await jurisdiction.selectOption(code);
  return ok<CreateOptions>(await loaded, `Create options for ${code}`);
}

async function checkAgain(page: Page, form: Locator, code: string, operation: string): Promise<CreateOptions> {
  const loaded = page.waitForResponse(isOptions(code));
  await form.getByRole("button", { name: "Check again" }).click();
  return ok<CreateOptions>(await loaded, operation);
}

/**
 * A jurisdiction the panel does not cover right now, read from the server.
 * The two projects take opposite ends of the list so parallel production
 * runs never pick one the other is about to cover.
 */
function uncoveredJurisdiction(options: CreateOptions, preferred: string, fromEnd: boolean): Jurisdiction {
  const empty = options.jurisdictions.filter((row) => row.associate_count === 0 && !REGIONAL_OFFICES.includes(row.code));
  const chosen = empty.find((row) => row.code === preferred) ?? (fromEnd ? empty.at(-1) : empty[0]);
  expect(chosen, "Some jurisdiction has no approved associate").toBeTruthy();
  return chosen!;
}

async function recordQuote(page: Page, form: Locator, docketId: string, currency: string, amount: string) {
  const quote = form.getByRole("region", { name: "Record associate quote" });
  await expect(quote).toBeVisible();
  const reference = stamp("Associate quote email");
  await quote.getByLabel("Quoted amount").fill(amount);
  await quote.getByLabel("Quote currency").fill(currency);
  await quote.getByLabel("Quote reference").fill(reference);
  const saved = page.waitForResponse(isPost(`/api/ip/dockets/${docketId}/cost-items`));
  await quote.getByRole("button", { name: "Save quote" }).click();
  const docket = await ok(await saved, "Record the associate quote in the form");
  const recorded = docket.cost_items.find((row: { evidence_reference: string }) => row.evidence_reference === reference);
  expect(recorded).toMatchObject({ cost_nature: "estimate", category: "associate_fee", currency, lineage_status: "active" });
  await expect(form.getByLabel("Estimate", { exact: true })).toHaveValue(recorded.id);
  await expect(quote).toHaveCount(0);
  return recorded.id as string;
}

/** The Documents blocker opens the record's Documents tab with the record chosen; upload there. */
async function uploadFromBlocker(
  page: Page, form: Locator, docketId: string, code: string,
): Promise<{ title: string; documentId: string }> {
  const link = form.locator("#fa-documents-hint").getByRole("link", { name: /Open the record's Documents tab/ });
  await expect(link).toHaveAttribute("href", `/app/ip?docket=${docketId}&tab=documents`);
  const tab = await followNewTab(page, link);
  await expect(tab.getByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
  const workspace = tab.getByTestId("ip-document-workspace");
  await expect(workspace.locator("#ip-document-docket")).toHaveValue(docketId);
  const title = stamp("Filing instruction pack");
  await workspace.locator("#ip-document-file").setInputFiles({
    name: "instruction-pack.txt", mimeType: "text/plain",
    buffer: Buffer.from(`Synthetic instruction pack ${title}; no legal effect.`),
  });
  await workspace.locator("#ip-document-title").fill(title);
  await workspace.locator("#ip-document-client").fill("CASEOPS-QA");
  await workspace.locator("#ip-document-mark").fill("PINE");
  await workspace.locator("#ip-document-jurisdiction").fill(code);
  const classification = workspace.locator("#ip-document-taxonomy");
  await expect(classification).toBeEnabled();
  const key = await classification.locator('option:not([value=""])').first().getAttribute("value");
  await classification.selectOption(key ?? "");
  const previewed = tab.waitForResponse(isPost("/api/ip/documents/naming-preview"));
  await workspace.getByRole("button", { name: "Preview controlled name" }).click();
  await ok(await previewed, "Preview the controlled document name");
  const uploaded = tab.waitForResponse(isPost("/api/ip/documents/upload"));
  await workspace.getByRole("button", { name: /Upload reviewed document/ }).click();
  const result = await ok(await uploaded, "Upload the instruction document in the Documents tab");
  expect(result.outcome).toBe("created");
  await tab.close();
  return { title, documentId: result.document.id as string };
}

async function completeAndCreate(page: Page, form: Locator, documentTitle: string, authority: string) {
  await form.getByLabel("Client's written authority").fill(authority);
  await form.getByLabel("Thread key").fill(stamp("PINE-FA"));
  await form.getByLabel("Source reference").fill("Indian application 4009154");
  await form.getByLabel("Nice classes in scope").fill("9");
  await form.getByLabel("Budget policy").fill("Foreign filing budget policy BP-2026");
  await form.getByLabel("Reason", { exact: true }).fill("Instruct the associate to file the national application.");
  await form.getByLabel(documentTitle).check();
  await expect(form.locator("#fa-create-blockers")).toHaveCount(0);
  expect(await deadSelects(page, form)).toEqual([]);
  const created = page.waitForResponse(isPost("/api/ip/foreign-associate-instructions"));
  await form.getByRole("button", { name: "Create instruction" }).click();
  return ok(await created, "Create the instruction through the form", 201);
}

/** Retire the instruction: cancel it through the Actions tab. */
async function retireInstruction(page: Page, instructionId: string) {
  await page.getByRole("tab", { name: "Actions" }).click();
  await page.getByLabel("Transaction").selectOption("cancel");
  await page.getByLabel("Reason", { exact: true }).fill("Retire the synthetic tester instruction.");
  const cancelled = page.waitForResponse(isPost(`/api/ip/foreign-associate-instructions/${instructionId}/transactions`));
  await page.getByRole("button", { name: "Record Cancel" }).click();
  const result = await ok(await cancelled, "Retire the instruction", 201);
  expect(result.instruction.status).toBe("cancelled");
}

/** Retire the quote: void it in the IP record's cost evidence. */
async function voidQuote(page: Page, rt: TesterRuntime, docketId: string, estimateId: string) {
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}`);
  const row = page.getByTestId(`ip-cost-item-${estimateId}`);
  await row.getByRole("button", { name: "Correct or void" }).click();
  await row.getByLabel("Correction action").selectOption("void");
  await row.getByLabel("Correction reason").fill("Retire the synthetic tester quote.");
  await row.getByLabel("Correction evidence reference").fill(`e2e:bugs4:void:${rt.run}`);
  const voided = page.waitForResponse(isPost(`/api/ip/dockets/${docketId}/cost-items/${estimateId}/corrections`));
  await row.getByRole("button", { name: "Void cost evidence" }).click();
  await ok(await voided, "Void the synthetic quote");
  await expect(row).toContainText("Voided");
}

/** Everything the reported state must explain, on a record and target the server says are empty. */
async function expectReportedExplanations(page: Page, form: Locator, options: CreateOptions, target: Jurisdiction, docketId: string) {
  expect(options).toMatchObject({
    docket_id: docketId, target_jurisdiction: target.code, matter_id: null, assignment_required: false,
    associates: [], estimates: [], client_instructions: [], documents: [], can_record_estimate: true,
  });
  expect(options.blockers.map((row) => row.code)).toEqual(
    expect.arrayContaining(["no_associate_for_jurisdiction", "no_active_estimate", "no_linked_documents"]),
  );

  // BUG-009: the associate picker says why it is empty and where to add one.
  const associate = form.getByLabel("Approved associate");
  await expect(associate).toBeDisabled();
  const associateHint = form.locator("#fa-associate-hint");
  await expect(associateHint).toContainText(`No approved associate on the panel files in ${target.code} · ${target.name}`);
  await expect(associateHint.getByRole("link", { name: /Add counsel in Outside Counsel/ })).toHaveAttribute("href", "/app/outside-counsel");
  await expect(associate).toHaveAttribute("aria-describedby", /fa-associate-hint/);

  // BUG-010: the disabled assignment explains the Matter requirement and links to Link Matter.
  await expect(form.getByLabel("Approved Matter assignment")).toBeDisabled();
  const assignmentHint = form.locator("#fa-assignment-hint");
  await expect(assignmentHint).toContainText("This record has no linked Matter, so no Matter assignment or budget applies.");
  await expect(assignmentHint.getByRole("link", { name: /Link a Matter on the IP record/ }))
    .toHaveAttribute("href", `/app/ip?docket=${docketId}&view=access`);

  // BUG-011: no placeholder-only select; the written-authority path is explicit.
  await expect(form.getByLabel("Accepted client instruction")).toHaveCount(0);
  const authority = form.getByLabel("Client's written authority");
  await expect(authority).toBeEditable();
  await expect(authority).toHaveAttribute("required", "");
  await expect(form.locator("#fa-authority-hint")).toContainText("No accepted client-portal instruction exists for this record");
  await expect(form.locator("#fa-authority-hint").getByRole("link", { name: /IP client portal/ })).toHaveAttribute("href", "/app/ip/client-portal");

  // BUG-013: the estimate is closed with the reason, and the quote path is in the form.
  await expect(form.getByLabel("Estimate", { exact: true })).toBeDisabled();
  await expect(form.locator("#fa-estimate-hint")).toContainText("No active associate estimate is recorded on this record.");
  await expect(form.getByRole("region", { name: "Record associate quote" })).toContainText("Owners and admins (fee-management permission) record quotes.");

  // Documents: the upload path opens the record's Documents tab.
  await expect(form.locator("#fa-documents-hint").getByRole("link", { name: /Open the record's Documents tab/ }))
    .toHaveAttribute("href", `/app/ip?docket=${docketId}&tab=documents`);

  // Every server blocker is on screen, and Create says why it is disabled.
  for (const blocker of options.blockers) await expect(form.getByText(blocker.message).first()).toBeVisible();
  const create = form.getByRole("button", { name: "Create instruction" });
  await expect(create).toBeDisabled();
  await expect(create).toHaveAttribute("aria-describedby", "fa-create-blockers");
  await expect(form.locator("#fa-create-blockers")).toContainText(`Approved associate: none on the panel files in ${target.code}.`);
  expect(await deadSelects(page, form), "No enabled select may hold only a placeholder").toEqual([]);

  // Readable without horizontal scrolling at this viewport (393px on the phone project).
  await expectNoPageOverflow(page);
  const width = page.viewportSize()?.width ?? 0;
  for (const hint of [associateHint, assignmentHint, form.locator("#fa-estimate-hint"), form.locator("#fa-create-blockers")]) {
    await hint.scrollIntoViewIfNeeded();
    await expectOnScreen(hint, "The explanation is readable on screen");
    const box = await hint.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= width + 1, "The explanation fits the viewport width").toBe(true);
  }
}

async function instructionWalk(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  const rt = await startTester(page, request, baseURL, mobile);
  const record = await createRecordInUi(page, rt);
  const form = await openNewInstruction(page, rt);
  // Before a record is chosen nothing claims "Matterless record" (BUG-010).
  await expect(form.locator("#fa-assignment-hint")).toHaveText("Select an IP record first.");
  const initial = await chooseRecord(page, form, record.docketId, record.title);
  await expect(form.locator("#fa-associate-hint")).toHaveText("Choose the target jurisdiction first.");
  const target = uncoveredJurisdiction(initial, mobile ? "AU" : "GB", mobile);
  const empty = await chooseJurisdiction(page, form, target.code);
  await expectReportedExplanations(page, form, empty, target, record.docketId);

  // BUG-009: Ram adds the associate from the blocker's link, by country name.
  const counselTab = await followNewTab(page, form.locator("#fa-associate-hint").getByRole("link", { name: /Add counsel in Outside Counsel/ }));
  const counselName = stamp("Filing associates LLP");
  const counselId = await addCounsel(counselTab, rt, counselName, `Delhi High Court, ${target.name}`);
  await counselTab.close();
  let retired = false;
  try {
    const covered = await checkAgain(page, form, target.code, "Create options after adding the associate");
    expect(covered.associates.find((row) => row.id === counselId)?.filing_jurisdictions).toEqual([target.code]);
    const associate = form.getByLabel("Approved associate");
    await expect(associate).toBeEnabled();
    await associate.selectOption(counselId);
    await expect(form.locator("#fa-associate-hint")).toContainText("London · Filing partner");
    await expect(form.locator("#fa-associate-hint")).toContainText(`Files in ${target.code} · Panel: Active`);
    await expect(form.getByLabel("Approved Matter assignment")).toBeDisabled();

    // BUG-013: no estimate yet, so Ram records the associate's quote right here.
    const currency = QUOTE_CURRENCY[target.code] ?? "USD";
    const estimateId = await recordQuote(page, form, record.docketId, currency, "1500.00");

    // The instruction document is uploaded where the blocker points.
    const { title: documentTitle, documentId } = await uploadFromBlocker(page, form, record.docketId, target.code);
    const withDocument = await checkAgain(page, form, target.code, "Create options after the upload");
    expect(withDocument.documents.map((row) => row.title)).toContain(documentTitle);
    expect(withDocument.blockers).toEqual([]);

    // BUG-011: no portal instruction exists; the written authority is the explicit path.
    const instruction = await completeAndCreate(page, form, documentTitle, "Client email of 30 Oct 2026, ref PL-118");
    expect(instruction).toMatchObject({
      docket_id: record.docketId, target_jurisdiction: target.code, outside_counsel_id: counselId, assignment_id: null,
      estimate_cost_item_id: estimateId, source_client_instruction_id: null, status: "draft",
    });
    await expect(page.getByRole("heading", { name: counselName })).toBeVisible();
    await retireInstruction(page, instruction.id);
    // The cancelled instruction no longer relies on the pack: retire it in the Documents tab (B4-ADJ-07).
    await retireDocumentThroughUi(page, rt, documentId, `Synthetic instruction pack ${rt.run} retired after its instruction.`,
      { history: false, mobile });
    await voidQuote(page, rt, record.docketId, estimateId);
    await retireCounsel(request, rt, counselId);
    retired = true;
    await markPositive(info, mobile ? "foreign-associate-walk-mobile" : "foreign-associate-walk", {
      local: rt.local, docket: record.docketId, target: target.code, instruction: instruction.id,
      reported_blockers: empty.blockers.map((row) => row.code),
    });
  } finally {
    if (!retired) await retireCounsel(request, rt, counselId);
  }
}

test("BUG-009/010/011/013 Ram walks a new instruction from every empty picker to a created and retired instruction", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  await instructionWalk(page, request, baseURL, info, false);
});

test("[mobile] BUG-009/010/011/013 Ram walks the new instruction, records the quote and creates it at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  await instructionWalk(page, request, baseURL, info, true);
});

/** Local only: a Matter to link (Matter creation is not under test). */
async function localMatter(rt: TesterRuntime, request: APIRequestContext) {
  expect(rt.local, "Local fixture records are never created in production").toBe(true);
  const title = stamp("ASTER UK filing");
  const code = `FA-${rt.run}`.replace(/[^A-Z0-9-]/gi, "").toUpperCase().slice(0, 60);
  const matter = await ok(await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
    title, matter_code: code, practice_area: "intellectual_property", forum_level: "tribunal", status: "intake",
  } }), "Local Matter (unrelated prerequisite)");
  return { id: matter.id as string, title, code };
}

test("[local-only] BUG-010 Ram links a Matter from the Matterless explanation, assigns the associate in GBP and creates the instruction", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await startTester(page, request, baseURL, false);
  expect(rt.local, "[local-only] journey").toBe(true);
  const matter = await localMatter(rt, request);
  const record = await createRecordInUi(page, rt);
  const counselTab = await page.context().newPage();
  await counselTab.goto(`${rt.web.origin}/app/outside-counsel`);
  const counselName = stamp("Albion Filings LLP");
  const counselId = await addCounsel(counselTab, rt, counselName, "United Kingdom");
  await counselTab.close();

  const form = await openNewInstruction(page, rt);
  await chooseRecord(page, form, record.docketId, record.title);
  const gb = await chooseJurisdiction(page, form, "GB");
  expect(gb).toMatchObject({ assignment_required: false, matter_id: null });
  await form.getByLabel("Approved associate").selectOption(counselId);

  // The Matterless explanation opens Link Matter in the record's Access and links view.
  const linkMatter = form.locator("#fa-assignment-hint").getByRole("link", { name: /Link a Matter on the IP record/ });
  await expect(linkMatter).toHaveAttribute("href", `/app/ip?docket=${record.docketId}&view=access`);
  const accessTab = await followNewTab(page, linkMatter);
  await expect(accessTab.getByRole("tab", { name: "Access and links" })).toHaveAttribute("aria-selected", "true");
  const links = accessTab.getByTestId("ip-matter-links-panel");
  await links.getByRole("button", { name: "Link Matter" }).click();
  await links.locator("#ip-link-matter-search").fill(matter.code);
  await links.locator("#ip-link-matter").click();
  await accessTab.getByRole("option", { name: `${matter.code} - ${matter.title}` }).click();
  await links.locator("#ip-link-role").click();
  await accessTab.getByRole("option", { name: "Operational" }).click();
  await links.locator("#ip-link-reason").fill("Bill the UK filing against the client Matter budget.");
  const linked = accessTab.waitForResponse(isPost(`/api/ip/dockets/${record.docketId}/matter-links`));
  await links.getByRole("button", { name: "Add relationship" }).click();
  expect(await ok(await linked, "Link the operational Matter in Access and links", 201)).toMatchObject({ matter_id: matter.id, relation_role: "operational" });
  await accessTab.close();

  // Back on the half-filled form: the Matter now needs a budgeted assignment.
  const withMatter = await checkAgain(page, form, "GB", "Create options after linking the Matter");
  expect(withMatter).toMatchObject({ assignment_required: true, matter_id: matter.id, assignments: [] });
  expect(withMatter.blockers.map((row) => row.code)).toContain("no_assignment_for_matter");
  const assignment = form.getByLabel("Approved Matter assignment");
  await expect(assignment).toBeDisabled();
  const hint = form.locator("#fa-assignment-hint");
  await expect(hint).toContainText(`No approved assignment with a budget ceiling links ${counselName} to the Matter`);
  const assignLink = hint.getByRole("link", { name: /Open the Matter's Outside counsel tab/ });
  await expect(assignLink).toHaveAttribute("href", `/app/matters/${matter.id}/outside-counsel`);
  expect(await deadSelects(page, form)).toEqual([]);

  // Assign counsel in GBP with a budget ceiling (the currency is chosen, not fixed to INR).
  const matterTab = await followNewTab(page, assignLink);
  await matterTab.getByTestId("matter-oc-assign-open").first().click();
  await matterTab.getByTestId("matter-oc-counsel-picker").click();
  await matterTab.getByRole("option", { name: counselName }).click();
  await matterTab.locator("#oc-role").fill("UK filing associate");
  await matterTab.locator("#oc-budget").fill("2000");
  await matterTab.locator("#oc-currency").fill("GBP");
  await expect(matterTab.getByText("Budget ceiling (GBP)")).toBeVisible();
  const assigned = matterTab.waitForResponse(isPost("/api/outside-counsel/assignments"));
  await matterTab.getByTestId("matter-oc-assign-submit").click();
  const created = await ok(await assigned, "Assign counsel with a GBP budget on the Matter");
  expect(created).toMatchObject({ currency: "GBP", budget_amount_minor: 200000 });
  await matterTab.close();

  const budgeted = await checkAgain(page, form, "GB", "Create options after the assignment");
  expect(budgeted.assignments.map((row) => [row.id, row.currency])).toEqual([[created.id, "GBP"]]);
  await expect(assignment).toBeEnabled();
  await assignment.selectOption(created.id);
  // The quote must fit the assignment: the form defaults the currency to it.
  await expect(form.getByRole("region", { name: "Record associate quote" }).getByLabel("Quote currency")).toHaveValue("GBP");
  const estimateId = await recordQuote(page, form, record.docketId, "GBP", "1500.00");
  const { title: documentTitle } = await uploadFromBlocker(page, form, record.docketId, "GB");
  await checkAgain(page, form, "GB", "Create options after the upload");
  const instruction = await completeAndCreate(page, form, documentTitle, "Client letter of 29 Oct 2026, ref AST-7");
  expect(instruction).toMatchObject({ assignment_id: created.id, outside_counsel_id: counselId, estimate_cost_item_id: estimateId, target_jurisdiction: "GB" });
  await retireInstruction(page, instruction.id);
  await voidQuote(page, rt, record.docketId, estimateId);
  await retireCounsel(request, rt, counselId);
  await markPositive(info, "foreign-associate-link-matter-gbp-assignment", { instruction: instruction.id, assignment: created.id, matter: matter.id });
});
