/**
 * Ram 2026-10-30 (CaseOps_Bugs (4).xlsx) BUG-009, BUG-010, BUG-011, BUG-013:
 * the New foreign-associate instruction form, signed in as the reporting
 * tester.
 *
 * Production (test-legal): Ram opens the reported record (PINE LABS, docket
 * 2cc78d06-…) and the reported target "UK" (GB). Every picker that cannot
 * offer a value must say why and link to where the missing record is made;
 * no enabled select may hold only a placeholder. Nothing is submitted there.
 *
 * Local (fresh test-legal-shaped tenant): the same reported state, then the
 * whole instruction workflow through the UI — the associate added in Outside
 * Counsel as "United Kingdom" (proving UK = GB = United Kingdom), the quote
 * recorded inline, the Matter assignment created from the blocker's link,
 * the instruction created (201) and retired (cancelled).
 *
 * Unrelated prerequisites created through the API, locally only, because
 * their own UI paths belong to other lanes and are not what these bugs are
 * about: the IP record itself, its Matter, and one uploaded document.
 */
import {
  expect, test, type APIRequestContext, type Locator, type Page, type Response, type TestInfo,
} from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

/** The record Ram reported (test-legal), selected by server identity. */
const PROD_PINE_LABS = { id: "2cc78d06-8fc5-535b-b21f-75da52914233", search: "4009154" };
const MOBILE = { width: 393, height: 851 };

type CreateOptions = {
  docket_id: string;
  target_jurisdiction: string | null;
  matter_id: string | null;
  associates: Array<{ id: string; name: string; filing_jurisdictions: string[] }>;
  assignment_required: boolean;
  assignments: Array<{ id: string; counsel_id: string; currency: string; compatible_estimate_ids: string[] }>;
  estimates: Array<{ id: string }>;
  client_instructions: unknown[];
  documents: Array<{ id: string; title: string }>;
  can_record_estimate: boolean;
  blockers: Array<{ code: string; message: string; href: string | null }>;
  jurisdictions: Array<{ code: string; associate_count: number }>;
};

const isOptions = (target_jurisdiction: string | null) => (response: Response) => {
  const url = new URL(response.url());
  return url.pathname.endsWith("/api/ip/foreign-associate-instructions/create-options")
    && response.request().method() === "GET"
    && url.searchParams.get("target_jurisdiction") === target_jurisdiction;
};

/** Local only: the IP record (and optionally its Matter) plus one document. */
async function localRecord(rt: TesterRuntime, request: APIRequestContext, withMatter: boolean) {
  expect(rt.local, "Local fixture records are never created in production").toBe(true);
  const title = stamp(withMatter ? "ASTER GB filing" : "PINE LABS GB filing");
  let matterId: string | null = null;
  if (withMatter) {
    const matter = await json(await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
      title, matter_code: `FA-${rt.run}`.replace(/[^A-Z0-9-]/gi, "").toUpperCase().slice(0, 60),
      practice_area: "intellectual_property", forum_level: "tribunal", status: "intake",
    } }), "Local Matter (unrelated prerequisite)");
    matterId = matter.id;
  }
  const docket = await json(await request.post(`${rt.api.origin}/api/ip/dockets`, { headers: rt.headers, data: {
    title, matter_id: matterId, restricted: false,
    particulars: {
      form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
      representation: { text: "PINE", evidence_reference: `e2e:bugs4:mark:${rt.run}` },
      classes: [{ class_number: 9, specification: "Payment terminals and point-of-sale software" }],
      use_priority: null, parties: [{ role: "applicant", name: "Pine Labs Private Limited" }], agent: null,
      filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: `e2e:bugs4:mark:${rt.run}` }],
    },
  } }), "Local IP record (unrelated prerequisite)", 201);
  await json(await request.post(`${rt.api.origin}/api/ip/document-taxonomy/seed`, { headers: rt.headers }), "Local document taxonomy");
  const documentTitle = stamp("Filing instruction pack");
  await json(await request.post(`${rt.api.origin}/api/ip/documents/upload`, { headers: rt.headers, multipart: {
    metadata_json: JSON.stringify({
      taxonomy_key: "evidence", title: documentTitle, confidentiality: "internal", is_privileged: false,
      client_code: "CASEOPS-QA", asset_type: "Trademark", mark: "PINE", jurisdiction: "GB", document_date: "2026-10-30",
      links: [{ target_type: "docket", target_id: docket.id }],
    }),
    upload: { name: "instruction-pack.txt", mimeType: "text/plain", buffer: Buffer.from(`Synthetic instruction pack ${rt.run}; no legal effect.`) },
  } }), "Local document upload (unrelated prerequisite)");
  return { docketId: docket.id as string, search: title, matterId, documentTitle };
}

/** Outside Counsel → Add counsel, exactly as a lawyer adds a panel firm. */
async function addCounselInUi(page: Page, rt: TesterRuntime, name: string, jurisdictions: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/outside-counsel`);
  await page.getByTestId("new-counsel-trigger").first().click();
  const dialog = page.getByRole("dialog", { name: "Add outside counsel to the panel" });
  await dialog.locator("#counsel-name").fill(name);
  await dialog.locator("#contact-name").fill("Filing partner");
  await dialog.locator("#contact-email").fill(`filings-${rt.run.replace(/\W/g, "").toLowerCase()}@example.com`);
  await dialog.locator("#firm-city").fill("London");
  await dialog.locator("#jurisdictions").fill(jurisdictions);
  await expect(dialog.locator("#jurisdictions-hint")).toContainText("United Kingdom or GB");
  const created = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/outside-counsel/profiles"
    && response.request().method() === "POST");
  await dialog.getByTestId("new-counsel-submit").click();
  const profile = await json(await created, "Add counsel through the UI");
  await expect(dialog).toBeHidden();
  return profile.id as string;
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
  return json<CreateOptions>(await loaded, "Create options for the record");
}

async function chooseJurisdiction(page: Page, form: Locator, code: string): Promise<CreateOptions> {
  const jurisdiction = form.getByLabel("Target jurisdiction");
  await expect(jurisdiction).toBeEnabled();
  const loaded = page.waitForResponse(isOptions(code));
  await jurisdiction.selectOption(code);
  return json<CreateOptions>(await loaded, `Create options for ${code}`);
}

/** The reported state: PINE LABS-shaped Matterless record, target UK, nothing set up. */
async function reportedState(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  let record = { docketId: PROD_PINE_LABS.id, search: PROD_PINE_LABS.search };
  if (rt.local) {
    // test-legal's panel holds domestic litigation counsel only (Delhi); mirror it through the UI.
    await addCounselInUi(page, rt, stamp("Delhi litigation chambers"), "Delhi High Court, Delhi");
    record = await localRecord(rt, request, false);
  }
  const form = await openNewInstruction(page, rt);
  // Before a record is chosen nothing claims "Matterless record" (BUG-010).
  await expect(form.locator("#fa-assignment-hint")).toHaveText("Select an IP record first.");
  await chooseRecord(page, form, record.docketId, record.search);
  await expect(form.locator("#fa-associate-hint")).toHaveText("Choose the target jurisdiction first.");
  const gb = await chooseJurisdiction(page, form, "GB");

  // Preconditions: this is the reported state, read from the server.
  expect(gb.docket_id).toBe(record.docketId);
  expect(gb.target_jurisdiction).toBe("GB");
  expect(gb.associates, "Reported state: no GB associate on the panel").toEqual([]);
  expect(gb.assignment_required, "Reported state: the record has no Matter").toBe(false);
  expect(gb.client_instructions, "Reported state: no accepted client-portal instruction").toEqual([]);
  expect(gb.estimates, "Reported state: no active estimate on the record").toEqual([]);
  expect(gb.can_record_estimate, "Ram is an owner (fee-management permission)").toBe(true);
  expect(gb.blockers.map((row) => row.code)).toEqual(expect.arrayContaining(["no_associate_for_jurisdiction", "no_active_estimate"]));

  // BUG-009: the associate picker says why it is empty and where to add one.
  const associate = form.getByLabel("Approved associate");
  await expect(associate).toBeDisabled();
  const associateHint = form.locator("#fa-associate-hint");
  await expect(associateHint).toContainText("No approved associate on the panel files in GB · United Kingdom");
  await expect(associateHint.getByRole("link", { name: /Add counsel in Outside Counsel/ })).toHaveAttribute("href", "/app/outside-counsel");
  await expect(associate).toHaveAttribute("aria-describedby", /fa-associate-hint/);

  // BUG-010: the disabled assignment explains the Matter requirement and links to Link Matter.
  const assignment = form.getByLabel("Approved Matter assignment");
  await expect(assignment).toBeDisabled();
  const assignmentHint = form.locator("#fa-assignment-hint");
  await expect(assignmentHint).toContainText("This record has no linked Matter, so no Matter assignment or budget applies.");
  await expect(assignmentHint.getByRole("link", { name: /Link a Matter on the IP record/ }))
    .toHaveAttribute("href", `/app/ip?docket=${record.docketId}`);

  // BUG-011: no placeholder-only select; the written-authority path is explicit.
  await expect(form.getByLabel("Accepted client instruction")).toHaveCount(0);
  const authority = form.getByLabel("Client's written authority");
  await expect(authority).toBeEditable();
  await expect(authority).toHaveAttribute("required", "");
  await expect(form.locator("#fa-authority-hint")).toContainText("No accepted client-portal instruction exists for this record");
  await expect(form.locator("#fa-authority-hint").getByRole("link", { name: /IP client portal/ })).toHaveAttribute("href", "/app/ip/client-portal");

  // BUG-013: the estimate is closed with the reason, and the quote path is in the form.
  const estimate = form.getByLabel("Estimate", { exact: true });
  await expect(estimate).toBeDisabled();
  await expect(form.locator("#fa-estimate-hint")).toContainText("No active associate estimate is recorded on this record.");
  const quote = form.getByRole("region", { name: "Record associate quote" });
  await expect(quote).toContainText("Owners and admins (fee-management permission) record quotes.");

  // Every server blocker is on screen, and Create says why it is disabled.
  for (const blocker of gb.blockers) await expect(form.getByText(blocker.message).first()).toBeVisible();
  const create = form.getByRole("button", { name: "Create instruction" });
  await expect(create).toBeDisabled();
  await expect(create).toHaveAttribute("aria-describedby", "fa-create-blockers");
  await expect(form.locator("#fa-create-blockers")).toContainText("Approved associate: none on the panel files in GB.");
  expect(await deadSelects(page, form), "No enabled select may hold only a placeholder").toEqual([]);

  if (mobile) {
    await expectNoPageOverflow(page);
    for (const hint of [associateHint, assignmentHint, form.locator("#fa-estimate-hint"), form.locator("#fa-create-blockers")]) {
      await hint.scrollIntoViewIfNeeded();
      await expectOnScreen(hint, "The explanation is readable at 393px");
    }
    const box = await form.locator("#fa-create-blockers").boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= MOBILE.width + 1, "Blockers fit the phone width").toBe(true);
  }
  await markPositive(info, "foreign-associate-reported-state", { local: rt.local, docket: record.docketId, blockers: gb.blockers.map((row) => row.code) });
}

test("BUG-009/010/011/013 New instruction explains every missing prerequisite on the reported record", async ({ page, request, baseURL }, info) => {
  test.setTimeout(4 * 60_000);
  await reportedState(page, request, baseURL, info, false);
});

test("[mobile] BUG-009/010/011/013 New instruction explanations fit a 393px phone", async ({ page, request, baseURL }, info) => {
  test.setTimeout(4 * 60_000);
  await reportedState(page, request, baseURL, info, true);
});

async function recordQuote(page: Page, form: Locator, docketId: string, currency: string, amount: string) {
  const quote = form.getByRole("region", { name: "Record associate quote" });
  await expect(quote).toBeVisible();
  const reference = stamp("Associate quote email");
  await quote.getByLabel("Quoted amount").fill(amount);
  await quote.getByLabel("Quote currency").fill(currency);
  await quote.getByLabel("Quote reference").fill(reference);
  const saved = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/ip/dockets/${docketId}/cost-items`
    && response.request().method() === "POST");
  await quote.getByRole("button", { name: "Save quote" }).click();
  const docket = await json(await saved, "Record the associate quote in the form");
  const recorded = docket.cost_items.find((row: { evidence_reference: string }) => row.evidence_reference === reference);
  expect(recorded).toMatchObject({ cost_nature: "estimate", category: "associate_fee", currency, lineage_status: "active" });
  await expect(form.getByLabel("Estimate", { exact: true })).toHaveValue(recorded.id);
  await expect(quote).toHaveCount(0);
  return recorded.id as string;
}

async function completeAndCreate(page: Page, form: Locator, documentTitle: string, authority: string) {
  await form.getByLabel("Client's written authority").fill(authority);
  await form.getByLabel("Thread key").fill(stamp("PINE-GB"));
  await form.getByLabel("Source reference").fill("Indian application 4009154");
  await form.getByLabel("Nice classes in scope").fill("9");
  await form.getByLabel("Budget policy").fill("Foreign filing budget policy BP-2026");
  await form.getByLabel("Reason", { exact: true }).fill("Instruct the UK associate to file the national application.");
  await form.getByLabel(documentTitle).check();
  await expect(form.locator("#fa-create-blockers")).toHaveCount(0);
  expect(await deadSelects(page, form)).toEqual([]);
  const created = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/ip/foreign-associate-instructions"
    && response.request().method() === "POST");
  await form.getByRole("button", { name: "Create instruction" }).click();
  return json(await created, "Create the instruction through the form", 201);
}

/** Retire what the run created: cancel the instruction through the Actions tab. */
async function retireInstruction(page: Page, instructionId: string) {
  await page.getByRole("tab", { name: "Actions" }).click();
  await page.getByLabel("Transaction").selectOption("cancel");
  await page.getByLabel("Reason", { exact: true }).fill("Retire the synthetic tester instruction.");
  const cancelled = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith(`/foreign-associate-instructions/${instructionId}/transactions`)
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Record Cancel" }).click();
  const result = await json(await cancelled, "Retire the instruction", 201);
  expect(result.instruction.status).toBe("cancelled");
}

test("[local-only] BUG-009/011/013 Ram adds a United Kingdom associate, records the quote and creates the GB instruction", async ({ page, request, baseURL }, info) => {
  test.setTimeout(5 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "[local-only] journey").toBe(true);
  const record = await localRecord(rt, request, false);
  // BUG-009: the profile says "United Kingdom"; the instruction targets GB.
  const counselName = stamp("Thames Marks LLP");
  const counselId = await addCounselInUi(page, rt, counselName, "United Kingdom");

  const form = await openNewInstruction(page, rt);
  await chooseRecord(page, form, record.docketId, record.search);
  const gb = await chooseJurisdiction(page, form, "GB");
  expect(gb.associates.map((row) => [row.id, row.filing_jurisdictions])).toEqual([[counselId, ["GB"]]]);
  const associate = form.getByLabel("Approved associate");
  await expect(associate).toBeEnabled();
  await associate.selectOption(counselId);
  await expect(form.locator("#fa-associate-hint")).toContainText("London · Filing partner");
  await expect(form.locator("#fa-associate-hint")).toContainText("Files in GB · Panel: Active");
  await expect(form.getByLabel("Approved Matter assignment")).toBeDisabled();

  // BUG-013: no estimate yet, so Ram records the associate's quote right here.
  const estimateId = await recordQuote(page, form, record.docketId, "GBP", "1500.00");
  // BUG-011: no portal instruction exists; the written authority is the explicit path.
  const instruction = await completeAndCreate(page, form, record.documentTitle, "Client email of 30 Oct 2026, ref PL-118");
  expect(instruction).toMatchObject({
    docket_id: record.docketId, target_jurisdiction: "GB", outside_counsel_id: counselId, assignment_id: null,
    estimate_cost_item_id: estimateId, source_client_instruction_id: null, status: "draft",
  });
  await expect(page.getByRole("heading", { name: counselName })).toBeVisible();
  await retireInstruction(page, instruction.id);
  await markPositive(info, "foreign-associate-gb-instruction-created", { instruction: instruction.id });
});

test("[local-only] BUG-010 the Matter assignment blocker links to Assign counsel and the budgeted assignment becomes selectable", async ({ page, request, baseURL }, info) => {
  test.setTimeout(5 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "[local-only] journey").toBe(true);
  const record = await localRecord(rt, request, true);
  const counselName = stamp("Albion Filings LLP");
  const counselId = await addCounselInUi(page, rt, counselName, "GB");

  const form = await openNewInstruction(page, rt);
  await chooseRecord(page, form, record.docketId, record.search);
  const gb = await chooseJurisdiction(page, form, "GB");
  expect(gb.assignment_required).toBe(true);
  expect(gb.assignments).toEqual([]);
  await form.getByLabel("Approved associate").selectOption(counselId);
  const assignment = form.getByLabel("Approved Matter assignment");
  await expect(assignment).toBeDisabled();
  const hint = form.locator("#fa-assignment-hint");
  await expect(hint).toContainText(`No approved assignment with a budget ceiling links ${counselName} to the Matter`);
  const link = hint.getByRole("link", { name: /Open the Matter's Outside counsel tab/ });
  await expect(link).toHaveAttribute("href", `/app/matters/${record.matterId}/outside-counsel`);
  expect(await deadSelects(page, form)).toEqual([]);

  // Follow the link (new tab, so the half-filled form survives) and assign with a budget.
  const [tab] = await Promise.all([page.context().waitForEvent("page"), link.click()]);
  await tab.waitForLoadState("domcontentloaded");
  await tab.getByTestId("matter-oc-assign-open").first().click();
  await tab.getByTestId("matter-oc-counsel-picker").click();
  await tab.getByRole("option", { name: counselName }).click();
  await tab.locator("#oc-role").fill("UK filing associate");
  await tab.locator("#oc-budget").fill("5000");
  const assigned = tab.waitForResponse((response) => new URL(response.url()).pathname === "/api/outside-counsel/assignments"
    && response.request().method() === "POST");
  await tab.getByTestId("matter-oc-assign-submit").click();
  const created = await json(await assigned, "Assign counsel with a budget on the Matter");
  await tab.close();

  const refreshed = page.waitForResponse(isOptions("GB"));
  await form.getByRole("button", { name: "Check again" }).click();
  const after = await json<CreateOptions>(await refreshed, "Create options after the assignment");
  expect(after.assignments.map((row) => row.id)).toEqual([created.id]);
  await expect(assignment).toBeEnabled();
  await assignment.selectOption(created.id);
  // The quote must fit the assignment: the form defaults the currency to it.
  await expect(form.getByRole("region", { name: "Record associate quote" }).getByLabel("Quote currency")).toHaveValue("INR");
  const estimateId = await recordQuote(page, form, record.docketId, "INR", "1000");
  const instruction = await completeAndCreate(page, form, record.documentTitle, "Client letter of 29 Oct 2026, ref AST-7");
  expect(instruction).toMatchObject({ assignment_id: created.id, outside_counsel_id: counselId, estimate_cost_item_id: estimateId });
  await retireInstruction(page, instruction.id);
  await markPositive(info, "foreign-associate-matter-assignment", { instruction: instruction.id, assignment: created.id });
});
