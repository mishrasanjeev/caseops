/**
 * BUG-008 (Ram, CaseOps_Bugs (4).xlsx, 2026-10-30): the post-registration
 * recordal form was a dead end. Each party's Instrument picker listed only
 * documents ticked in a separate checkbox list, and a docket without an
 * instrument offered no way to upload one.
 *
 * Signed in through the real sign-in form as the tester (test-legal in
 * production, a fresh test-legal-shaped tenant locally), each run:
 *   1. creates a disposable, clock-stamped trademark docket through the IP
 *      docket's own "New trademark" form (no API shortcut);
 *   2. opens Post-registration > New recordal, finds the docket by server
 *      search and selects it by server identity, and sees the honest empty
 *      instrument state with both party pickers disabled (no dead select);
 *   3. uploads the executed instrument from inside the recordal form;
 *   4. sees both party Instrument pickers list it, creates the recordal and
 *      finds it in the list by server identity, citing the instrument;
 *   5. sees, in a second tab, that the Documents tab refuses to retire the
 *      instrument while the draft recordal relies on it (B4-ADJ-07);
 *   6. retires what it created through the product paths: withdraws the
 *      recordal, retires the docket, then retires the instrument from the
 *      Documents tab's history view.
 *   If any step fails, the same three are released through the API in that
 *   order, so a failed production run leaves no live tester record behind.
 *
 * Nothing the bug is about is created through the API or the database.
 * Traces, screenshots and video stay off because the runtime holds the
 * tester's credentials.
 */
import { expect, test, type APIRequestContext, type Page, type Response, type TestInfo } from "@playwright/test";

import {
  deadSelects,
  expectNoPageOverflow,
  expectOnScreen,
  json,
  markPositive,
  prepareTester,
  stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";
import {
  createDocketThroughUi, expectRetirementBlockedThroughUi, retireDocketByApi, retireDocumentByApi,
  retireDocumentThroughUi, runCleanup, withdrawRecordalByApi,
} from "./support/ip-documents";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const DESKTOP = { width: 1440, height: 900 };
const PIXEL_5 = { width: 393, height: 851 };

function apiCall(rt: TesterRuntime, method: string, path: string | RegExp) {
  return (response: Response) => {
    const url = new URL(response.url());
    return url.origin === rt.api.origin
      && response.request().method() === method
      && (typeof path === "string" ? url.pathname === path : path.test(url.pathname));
  };
}

/** A disposable docket, created through the IP docket's own "New trademark" panel. */
async function createDocket(page: Page, rt: TesterRuntime, title: string) {
  return createDocketThroughUi(page, rt, title, title.replace(/^BUG-008 recordal docket /, "B008 "));
}

async function retireDocketThroughUi(page: Page, rt: TesterRuntime, docket: { id: string; title: string }) {
  await page.goto(`${rt.web.origin}/app/ip?docket=${docket.id}`);
  const lifecycle = page.getByTestId("ip-lifecycle-workflow");
  await lifecycle.scrollIntoViewIfNeeded();
  await lifecycle.getByLabel("Transition").selectOption("retired");
  await lifecycle.getByLabel("Reason").fill("BUG-008 acceptance run finished; retire its disposable docket.");
  await lifecycle.getByLabel("Outcome").fill("Retired after the acceptance run");
  await lifecycle.getByLabel("Evidence reference").fill(`e2e:${docket.title}`);
  const previewed = page.waitForResponse(apiCall(rt, "POST", `/api/ip/dockets/${docket.id}/lifecycle/preview`));
  await lifecycle.getByRole("button", { name: "Preview lifecycle impact" }).click();
  const preview = await json<{ requires_exception_acknowledgement: boolean }>(await previewed, "Preview docket retirement");
  // The acknowledgement is required only when the server lists blockers.
  if (preview.requires_exception_acknowledgement) {
    await page.getByText("I reviewed and acknowledge every listed lifecycle blocker.").click();
  }
  const applied = page.waitForResponse(apiCall(rt, "POST", `/api/ip/dockets/${docket.id}/lifecycle`));
  await lifecycle.getByRole("button", { name: "Apply lifecycle transition" }).click();
  const result = await json<{ docket_id: string; status: string; is_active: boolean }>(await applied, "Retire the disposable docket");
  expect(result).toEqual(expect.objectContaining({ docket_id: docket.id, status: "retired", is_active: false }));
}

/** What this run created, recorded as soon as the server returns it. */
type Created = { docketId: string | null; deedId: string | null; recordalId: string | null };

/**
 * The journey, then failure-path cleanup in the order the retirement rule
 * requires (withdraw the recordal, retire the docket, retire the deed). When
 * the journey passed, each step finds its record already released and does
 * nothing.
 */
async function recordalJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const created: Created = { docketId: null, deedId: null, recordalId: null };
  try {
    await recordalSteps(page, rt, info, mobile, created);
  } finally {
    const { docketId, deedId, recordalId } = created;
    await runCleanup([
      ["Withdraw the acceptance recordal", recordalId ? () => withdrawRecordalByApi(request, rt, recordalId) : null],
      ["Retire the acceptance docket", docketId ? () => retireDocketByApi(request, rt, docketId) : null],
      ["Retire the acceptance instrument", deedId ? () => retireDocumentByApi(request, rt, deedId) : null],
    ]);
  }
}

async function recordalSteps(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean, created: Created) {
  const docket = await createDocket(page, rt, stamp("BUG-008 recordal docket"));
  created.docketId = docket.id;

  await page.goto(`${rt.web.origin}/app/ip/recordals`);
  await expect(page.getByRole("heading", { name: "Post-registration" })).toBeVisible();
  const toggle = page.getByRole("button", { name: "New recordal", exact: true });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  const form = page.getByRole("form", { name: "New recordal" });
  await expect(form).toBeVisible();
  const create = form.getByRole("button", { name: "Create recordal" });
  await expect(create).toBeDisabled();
  await expect(create).toHaveAccessibleDescription(/choose the IP docket/);
  const assignorInstrument = form.getByRole("group", { name: "Party 1" }).getByLabel("Instrument", { exact: true });
  const assigneeInstrument = form.getByRole("group", { name: "Party 2" }).getByLabel("Instrument", { exact: true });
  await expect(assignorInstrument).toBeDisabled();
  expect(await deadSelects(page, form), "No enabled select without a real option before a docket is chosen").toEqual([]);

  // Find the docket by server search, then select it by server identity.
  await form.getByLabel("Find IP docket").fill(docket.title);
  const docketSelect = form.getByLabel("IP docket", { exact: true });
  await expect(docketSelect.locator(`option[value="${docket.id}"]`)).toHaveCount(1);
  const emptyInstruments = page.waitForResponse(apiCall(rt, "GET", "/api/ip/recordals/instruments"));
  await docketSelect.selectOption(docket.id);
  const firstList = await json<{ docket_id: string; items: Array<{ id: string }> }>(await emptyInstruments, "List the docket's instruments");
  expect(firstList).toEqual(expect.objectContaining({ docket_id: docket.id, items: [] }));

  // The honest empty state: what is missing, and the in-form path to fix it.
  const status = form.locator("#recordal-instruments-status");
  await expect(status).toContainText("No executed instrument is filed on this docket yet");
  await expect(assignorInstrument).toBeDisabled();
  await expect(assigneeInstrument).toBeDisabled();
  await expect(assignorInstrument.locator("option:checked")).toHaveText("Upload an instrument first");
  await expect(create).toHaveAccessibleDescription(/upload the executed instrument for this docket/);
  expect(await deadSelects(page, form), "No dead select in the empty-instrument state").toEqual([]);
  if (mobile) await expectNoPageOverflow(page);

  // Upload the executed instrument from inside the recordal form.
  const upload = form.getByTestId("recordal-instrument-upload");
  const deedTitle = stamp("BUG-008 deed of assignment");
  const fileInput = upload.getByLabel("Executed instrument file");
  await fileInput.scrollIntoViewIfNeeded();
  await expectOnScreen(fileInput, "The instrument file field is on screen");
  await fileInput.setInputFiles({
    name: `${deedTitle.replaceAll(" ", "-")}.txt`,
    mimeType: "text/plain",
    buffer: Buffer.from(`Deed of assignment executed for ${docket.title}. Acceptance fixture ${deedTitle}.\n`.repeat(20)),
  });
  await upload.getByLabel("Instrument title").fill(deedTitle);
  await expect(upload.getByLabel("Classification")).toHaveValue("assignment");
  const uploaded = page.waitForResponse(apiCall(rt, "POST", "/api/ip/documents/upload"));
  const refreshed = page.waitForResponse(apiCall(rt, "GET", "/api/ip/recordals/instruments"));
  const uploadButton = upload.getByRole("button", { name: "Upload instrument" });
  await expect(uploadButton).toBeEnabled();
  await uploadButton.click();
  const uploadBody = await json<{ outcome: string; document: { id: string; title: string; links: Array<{ target_type: string; target_id: string }> } }>(
    await uploaded, "Upload the instrument from the recordal form");
  created.deedId = uploadBody.document?.id ?? null;
  expect(uploadBody.outcome).toBe("created");
  expect(uploadBody.document.title).toBe(deedTitle);
  expect(uploadBody.document.links).toEqual([expect.objectContaining({ target_type: "docket", target_id: docket.id })]);
  const deedId = uploadBody.document.id;
  const secondList = await json<{ items: Array<{ id: string }> }>(await refreshed, "Re-list the docket's instruments");
  expect(secondList.items.map((row) => row.id)).toEqual([deedId]);

  // Both party Instrument pickers now list it, without any hidden pre-step.
  for (const picker of [assignorInstrument, assigneeInstrument]) {
    await expect(picker).toBeEnabled();
    await expect(picker.locator(`option[value="${deedId}"]`)).toHaveText(new RegExp(`^${deedTitle} · Assignment`));
  }
  await expect(status).toContainText("1 instrument is filed on this docket");

  const partyName = stamp("Oldco Brands");
  await form.getByLabel("Form code").fill("TM-P");
  await form.getByLabel("Legal basis").fill("Trade Marks Act, 1999, section 45 and rule 75");
  await form.getByLabel("Execution date").fill("2026-10-01");
  await form.getByLabel("Effective date").fill("2026-10-01");
  await form.getByLabel("Affected application or registration references").fill(`TM ${docket.title}`);
  await form.getByRole("group", { name: "Party 1" }).getByLabel("Party name").fill(partyName);
  await form.getByRole("group", { name: "Party 2" }).getByLabel("Party name").fill(stamp("Newco IP"));
  await assignorInstrument.selectOption(deedId);
  await assigneeInstrument.selectOption(deedId);
  await expect(form.getByText("Cited by Assignor, Assignee")).toBeVisible();
  await form.getByLabel("Affected classes").fill("Class 9, 42");
  await form.getByLabel("Creation reason").fill("Record the executed assignment for the acceptance run.");
  expect(await deadSelects(page, form), "No dead select once the instrument exists").toEqual([]);
  if (mobile) await expectNoPageOverflow(page);
  await expect(create).toBeEnabled();
  await create.scrollIntoViewIfNeeded();
  await expectOnScreen(create, "Create recordal is on screen");
  const createdResponse = page.waitForResponse(apiCall(rt, "POST", "/api/ip/recordals"));
  await create.click();
  const recordal = await json<{
    id: string; docket_id: string; status: string; affected_classes_json: number[];
    supporting_instrument_refs_json: string[]; parties_json: Array<{ role: string; evidence_reference: string }>;
  }>(await createdResponse, "Create the recordal", 201);
  created.recordalId = recordal.id;
  expect(recordal).toEqual(expect.objectContaining({
    docket_id: docket.id, status: "draft", affected_classes_json: [9, 42], supporting_instrument_refs_json: [deedId],
  }));
  expect(recordal.parties_json.map((party) => [party.role, party.evidence_reference]))
    .toEqual([["assignor", deedId], ["assignee", deedId]]);

  // Listed, selected by server identity, and citing the uploaded instrument by title.
  const row = page.locator(`[data-recordal-id="${recordal.id}"]`);
  await expect(row).toContainText("assignment");
  await expect(row).toContainText(docket.title);
  await expect(row).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(`assignor · ${deedTitle}`)).toBeVisible();
  await expect(page.getByText(partyName, { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open IP docket" })).toHaveAttribute("href", `/app/ip?docket=${docket.id}`);
  // /app/ip/records does not exist (404); nothing on the page may link to it.
  await expect(page.locator('a[href*="/app/ip/records"]')).toHaveCount(0);
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, "bug008-recordal-from-uploaded-instrument", {
    local: rt.local, docket_id: docket.id, document_id: deedId, recordal_id: recordal.id, mobile,
  });

  // The live draft recordal relies on the instrument, so the Documents tab
  // names it and refuses to retire the instrument (checked in a second tab so
  // this recordal stays selected here).
  const documentsTab = await page.context().newPage();
  await documentsTab.setViewportSize(page.viewportSize() ?? DESKTOP);
  await expectRetirementBlockedThroughUi(documentsTab, rt, deedId,
    { label: "Assignment recordal", status: "draft", recordId: recordal.id }, { mobile });
  await documentsTab.close();
  await markPositive(info, "adj07-instrument-retirement-blocked-by-live-recordal", {
    local: rt.local, document_id: deedId, recordal_id: recordal.id, mobile,
  });

  // Retire what this run created, through the product paths.
  const transaction = page.locator("form").filter({ has: page.getByRole("heading", { name: "Record transaction" }) });
  await transaction.getByLabel("Transaction").selectOption("withdrawn");
  await transaction.getByLabel("Reason", { exact: true }).fill("BUG-008 acceptance run complete; withdraw the test recordal.");
  const withdrawn = page.waitForResponse(apiCall(rt, "POST", `/api/ip/recordals/${recordal.id}/transactions`));
  await transaction.getByRole("button", { name: "Record withdrawn" }).click();
  const withdrawnResponse = await withdrawn;
  // The untouched Effective time is stamped by the server, never by the browser clock.
  expect(withdrawnResponse.request().postDataJSON()).toEqual(expect.objectContaining({ effective_at: null, transaction_kind: "withdrawn" }));
  const withdrawal = await json<{ recordal: { status: string } }>(withdrawnResponse, "Withdraw the test recordal", 201);
  expect(withdrawal.recordal.status).toBe("withdrawn");
  await expect(page.getByText("This recordal is closed.")).toBeVisible();
  await retireDocketThroughUi(page, rt, docket);
  // The withdrawn recordal no longer relies on the instrument: retire it from history.
  await retireDocumentThroughUi(page, rt, deedId, `BUG-008 acceptance instrument ${rt.run} retired after its recordal.`,
    { history: true, mobile });
  await markPositive(info, "adj07-instrument-retired-after-recordal-and-docket", {
    local: rt.local, document_id: deedId, recordal_id: recordal.id, mobile,
  });
}

test("BUG-008 Ram uploads an instrument from the recordal form and both parties cite it", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  await recordalJourney(page, request, rt, info, false);
});

test("BUG-008 [mobile] the recordal journey works at Pixel 5 width without horizontal scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, PIXEL_5);
  expect(page.viewportSize()).toEqual(PIXEL_5);
  await recordalJourney(page, request, rt, info, true);
});
