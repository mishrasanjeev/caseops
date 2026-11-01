/**
 * Ram batch 4 adjacent defects B4-ADJ-02 and B4-ADJ-22 (raw internal-id inputs
 * and dead or pre-selected record pickers).
 *
 * - Drive, mailbox and calendar-conflict review queues asked for a typed
 *   "Matter id for actions/accept" and printed suggested Matters as UUIDs.
 *   The tester now finds a Matter by typing in the house MatterPicker and sees
 *   it named by caption. The Matter is created through the New matter dialog
 *   with a stamped code, chosen by server identity, never submitted to a queue
 *   action (nothing in a queue is changed), and disposed after the run.
 * - Notification rules asked for a "Matter or membership id" (local only:
 *   rules are shared tenant configuration, and Ram's notifications:manage in
 *   test-legal is not established).
 * - Opposition shared and specialized forms pre-selected records, left empty
 *   selects enabled and asked for a target record ID, a related application
 *   ID and comma-separated scope IDs (local only: an opposition with a
 *   confirmed profile has no UI creation path in this journey, and test-legal
 *   opposition records are shared state; the fixture is built through the
 *   product API).
 * - The hearing a specialized record accepts follows the API's served status
 *   table: with a scheduled and a completed hearing, the hearing notice is
 *   recorded on the scheduled one through the UI (201) while the completed
 *   one is listed disabled with its reason, and attendance flips both.
 * - The IP report preview printed application, docket, Matter and asset ids
 *   as its first columns; the server still sends them, the table never shows
 *   them (local only: the report needs a stamped IP record, which has no
 *   disposal path in test-legal).
 */
import { expect, test, type APIRequestContext, type Locator, type Page, type Response } from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type MatterRow = { id: string; matter_code: string; title: string; client_name: string | null; status: string; updated_at: string };

const QUEUES = [
  { path: "/app/drive", label: "Matter for Link and Import", search: "Search Matters for Link and Import", list: "/api/drive/candidates" },
  { path: "/app/mailbox", label: "Matter for Link and Request", search: "Search Matters for Link and Request", list: "/api/mailbox/imports" },
  { path: "/app/calendar/conflicts", label: "Matter for Accept", search: "Search Matters for Accept", list: "/api/calendar/provider-event-candidates" },
] as const;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const INTERNAL_FIELD = /\b(?:(?:membership|member|matter|record|scope|application|event|docket|proceeding|hearing|target) ids?|uuid)\b/i;

async function uiJson<T>(response: Response, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

function caption(matter: MatterRow): string {
  return [matter.matter_code, matter.title, matter.client_name].filter(Boolean).join(" · ");
}

async function createMatterInUi(page: Page, rt: TesterRuntime, tap: boolean): Promise<MatterRow> {
  const label = stamp("ADJ");
  const code = label.replace(/\s+/g, "-").toUpperCase().slice(0, 40);
  await page.goto(`${rt.web.origin}/app/matters`);
  const trigger = page.getByTestId("new-matter-trigger").first();
  if (tap) await trigger.tap(); else await trigger.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(`${label} B4-ADJ-02 synthetic picker Matter, disposed after the run`);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Intellectual property");
  const created = page.waitForResponse((row) =>
    new URL(row.url()).pathname === "/api/matters/" && row.request().method() === "POST");
  await dialog.getByRole("button", { name: /Create matter/i }).click();
  const matter = await uiJson<MatterRow>(await created, "UI Matter create");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter;
}

async function disposeMatter(rt: TesterRuntime, request: APIRequestContext, matterId: string) {
  const current = await json<MatterRow>(await request.get(`${rt.api.origin}/api/matters/${matterId}`,
    { headers: rt.headers }), "Stamped Matter read");
  await json(await request.patch(`${rt.api.origin}/api/matters/${matterId}/lifecycle/status`, { headers: rt.headers,
    data: { to_status: "disposed", expected_from_status: current.status, expected_updated_at: current.updated_at,
      reason: "B4-ADJ-02 acceptance run cleanup" } }), "Stamped Matter disposal");
}

async function internalIdInputs(scope: Locator): Promise<string[]> {
  return scope.evaluate((root, pattern) => {
    const re = new RegExp(pattern, "i");
    const out: string[] = [];
    for (const field of Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"))) {
      if (field.type === "hidden" || field.disabled || field.getBoundingClientRect().width === 0) continue;
      const label = field.labels?.[0]?.innerText || field.getAttribute("aria-label") || field.placeholder || "";
      if (re.test(label)) out.push(label.trim().split("\n")[0]);
    }
    return out;
  }, INTERNAL_FIELD.source);
}

/** Finds the stamped Matter by typing its code and chooses it by server identity. */
async function chooseMatterByTyping(page: Page, label: string, searchLabel: string, matter: MatterRow) {
  const select = page.getByRole("combobox", { name: label, exact: true });
  await expect(select).toBeEnabled();
  await expect(select).toHaveValue("");
  const search = page.getByLabel(searchLabel, { exact: true });
  const searched = page.waitForResponse((row) => new URL(row.url()).pathname === "/api/matters/"
    && new URL(row.url()).searchParams.get("q") === matter.matter_code);
  await search.fill(matter.matter_code);
  const found = await uiJson<{ matters: MatterRow[] }>(await searched, "Picker Matter search");
  expect(found.matters.map((row) => row.id)).toContain(matter.id);
  await expect(select.locator(`option[value="${matter.id}"]`)).toHaveCount(1);
  await select.selectOption(matter.id);
  await expect(select).toHaveValue(matter.id);
  await expect(page.locator(`[data-selected-option-value="${matter.id}"]`)).toHaveText(caption(matter));
  return select;
}

/**
 * The chosen field fits the screen: once brought into view (typing in the
 * search box above it scrolls only that box into view) the whole select is on
 * screen and inside the viewport width, so its caption is not clipped.
 */
async function expectFieldFits(page: Page, select: Locator, message: string) {
  await select.scrollIntoViewIfNeeded();
  await expectOnScreen(select, message);
  const box = await select.boundingBox();
  const width = page.viewportSize()!.width;
  expect(box, message).toBeTruthy();
  expect(box!.x, message).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, message).toBeLessThanOrEqual(width);
}

async function checkQueues(page: Page, rt: TesterRuntime, matter: MatterRow) {
  for (const queue of QUEUES) {
    const listed = page.waitForResponse((row) => new URL(row.url()).pathname === queue.list
      && row.request().method() === "GET");
    const pickerRead = page.waitForResponse((row) => new URL(row.url()).pathname === "/api/matters/"
      && row.request().method() === "GET");
    await page.goto(`${rt.web.origin}${queue.path}`);
    expect((await listed).status(), `${queue.path} queue read`).toBe(200);
    expect((await pickerRead).status(), `${queue.path} picker read`).toBe(200);
    const main = page.locator("main");
    await expect(main.getByLabel(/matter id/i)).toHaveCount(0);
    expect(await internalIdInputs(main), `${queue.path} internal-id inputs`).toEqual([]);
    const select = await chooseMatterByTyping(page, queue.label, queue.search, matter);
    await expectFieldFits(page, select, `${queue.path} Matter picker on screen`);
    expect(await deadSelects(page, main), `${queue.path} dead selects`).toEqual([]);
    await expectNoPageOverflow(page);
  }
}

test("B4-ADJ-02 review queues find the Matter by typing and name it, never by id, at 1440x900", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  const matter = await createMatterInUi(page, rt, false);
  try {
    await checkQueues(page, rt, matter);
    await markPositive(test.info(), "adj-02-queues-desktop", { local: rt.local, matterId: matter.id });
  } finally {
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});

test("B4-ADJ-02 [mobile] review queue Matter pickers fit a phone and name the Matter", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  const matter = await createMatterInUi(page, rt, true);
  try {
    await checkQueues(page, rt, matter);
    await markPositive(test.info(), "adj-02-queues-mobile", { local: rt.local, matterId: matter.id, width: viewport.width });
  } finally {
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});

async function chooseRuleScope(page: Page, scope: "Matter" | "User") {
  const form = page.getByTestId("notification-rule-form");
  await form.getByRole("combobox").first().click();
  await page.getByRole("option", { name: scope, exact: true }).click();
  return form;
}

async function notificationRuleJourney(page: Page, rt: TesterRuntime, request: APIRequestContext, matter: MatterRow) {
  await page.goto(`${rt.web.origin}/app/admin/notifications`);
  const form = page.getByTestId("notification-rule-form");
  await expect(form).toBeVisible();
  expect(await internalIdInputs(form)).toEqual([]);
  await expect(form.getByText("Every Matter and colleague in the company.")).toBeVisible();

  await chooseRuleScope(page, "User");
  const person = form.getByLabel("Rule colleague", { exact: true });
  await expect(person).toBeEnabled();
  await expect(person).toHaveValue("");
  await expect(page.getByTestId("notification-rule-create")).toBeDisabled();
  await person.selectOption(rt.actor.membership.id);
  await expect(page.getByTestId("notification-rule-create")).toBeEnabled();

  await chooseRuleScope(page, "Matter");
  await expect(page.getByTestId("notification-rule-create")).toBeDisabled();
  await expect(form.getByText("Choose the Matter this rule applies to.")).toBeVisible();
  const select = await chooseMatterByTyping(page, "Rule Matter", "Search Matters for this rule", matter);
  await expectFieldFits(page, select, "Rule Matter picker on screen");
  const created = page.waitForResponse((row) => new URL(row.url()).pathname === "/api/notification-rules"
    && row.request().method() === "POST");
  await page.getByTestId("notification-rule-create").click();
  const rule = await uiJson<{ id: string; scope_type: string; scope_id: string }>(await created, "UI rule create");
  expect(rule).toMatchObject({ scope_type: "matter", scope_id: matter.id });
  const row = page.getByTestId(`notification-rule-${rule.id}`);
  await expect(row).toContainText(caption(matter));
  await expect(row).not.toContainText(matter.id);
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);
  await expectNoPageOverflow(page);
  return rule.id;
}

async function deleteRule(rt: TesterRuntime, request: APIRequestContext, ruleId: string) {
  const deleted = await request.delete(`${rt.api.origin}/api/notification-rules/${ruleId}`, { headers: rt.headers });
  expect(deleted.status(), "Notification rule cleanup").toBe(204);
}

// Local only: notification rules are shared tenant configuration, and Ram's
// notifications:manage capability in test-legal is not established.
test("B4-ADJ-02 [local-only] notification rule scope is chosen with Matter and colleague pickers", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  expect(rt.local, "Notification rules are local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, false);
  let ruleId: string | undefined;
  try {
    ruleId = await notificationRuleJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-02-notification-rule-desktop", { ruleId, matterId: matter.id });
  } finally {
    if (ruleId) await deleteRule(rt, request, ruleId);
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});

test("B4-ADJ-02 [mobile] [local-only] notification rule pickers fit a phone", async ({ page, request, baseURL }) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  expect(rt.local, "Notification rules are local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, true);
  let ruleId: string | undefined;
  try {
    ruleId = await notificationRuleJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-02-notification-rule-mobile", { ruleId, matterId: matter.id });
  } finally {
    if (ruleId) await deleteRule(rt, request, ruleId);
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});

/** Local fixture through the product API: an opposition with a confirmed profile on a Matter-linked application. */
async function oppositionFixture(rt: TesterRuntime, request: APIRequestContext, matter: MatterRow) {
  const code = stamp("OPP").replace(/\s+/g, "-");
  const application = await json<{ docket: { id: string; lifecycle_version: number }; application: { id: string } }>(
    await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, { headers: rt.headers, data: {
      title: `${code} OPPOSED MARK`, matter_id: matter.id, restricted: false, asset_title: `${code} OPPOSED MARK`,
      jurisdiction: "IN", office: "Trade Marks Registry Delhi", filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: { raw_value: `TM-${code}`.slice(0, 60), source: "e2e registry fixture", effective_from: "2026-10-01", is_primary: true },
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: `${code} OPPOSED MARK`, evidence_reference: "e2e:mark:adj" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null, parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:mark:adj" }],
      },
    } }), "Fixture application", 201);
  const docketId = application.docket.id;
  const proceeding = await json<{ id: string; version: number }>(await request.post(
    `${rt.api.origin}/api/ip/dockets/${docketId}/proceedings`, { headers: rt.headers, data: {
      application_id: application.application.id, proceeding_kind: "opposition", side: "applicant",
      office: "Trade Marks Registry Delhi", jurisdiction: "IN", stage: "draft", origin_kind: "registry_event",
      source_pending_identifier_allocation: false,
      opposition_number: { raw_value: `OPP / ${code}`.slice(0, 60), source: "e2e registry notice", effective_from: "2026-10-01", is_primary: true },
    } }), "Fixture opposition", 201);
  await json(await request.put(
    `${rt.api.origin}/api/ip/dockets/${docketId}/proceedings/${proceeding.id}/opposition-workspace`,
    { headers: rt.headers, data: {
      expected_lifecycle_version: application.docket.lifecycle_version, expected_proceeding_version: proceeding.version,
      source: "manual", source_reference: "registry:opposition:adj", source_notice_reference: "notice:opposition:adj",
      source_notice_document_ref: "document:notice:adj", effective_at: "2026-10-01T12:00:00+05:30",
      responsible_membership_id: rt.actor.membership.id, reason: "Counsel confirmed the opposition profile and notice.",
      applicable_rule_version: "Trade Marks Rules, 2017", forum: "Trade Marks Registry Delhi",
      client_instruction_state: "not_required",
      parties: [
        { role: "applicant", party_name: "Applicant Industries Private Limited", source: "notice" },
        { role: "opponent", party_name: "Opponent Brands LLP", source: "notice" },
      ],
      grounds: [{ category: "earlier_mark", lawyer_detail: "Earlier mark ground confirmed by counsel." }],
      challenged_scope: [{ class_number: 9, goods_services_segment: "Downloadable legal software" }],
      relied_on_rights: [],
      service: { method: "registry email", destination: "applicant@example.test", served_on: "2026-10-01",
        starts_response_period: true, evidence_refs: ["service:notice:adj"] },
      evidence_refs: ["evidence:notice:adj"], document_refs: ["document:notice:adj"],
    } }), "Fixture opposition profile");
  return { docketId, proceedingId: proceeding.id, title: `${code} OPPOSED MARK` };
}

async function oppositionJourney(page: Page, rt: TesterRuntime, request: APIRequestContext, matter: MatterRow) {
  const { docketId, proceedingId } = await oppositionFixture(rt, request, matter);
  const workflowRead = page.waitForResponse((row) => new URL(row.url()).pathname
    === `/api/ip/dockets/${docketId}/proceedings/${proceedingId}/opposition-shared-workflow`);
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&view=proceedings`);
  const workflow = await uiJson<{ appeal_proceedings: unknown[]; related_applications: unknown[]; disposition_trigger_events: unknown[] }>(
    await workflowRead, "Shared workflow read");
  expect(workflow).toMatchObject({ appeal_proceedings: [], related_applications: [], disposition_trigger_events: [] });

  const shared = page.getByTestId("ip-opposition-shared-workflow");
  const specialized = page.getByTestId("ip-opposition-specialized-paths");
  await expect(shared).toBeVisible();
  await expect(specialized).toBeVisible();
  expect(await internalIdInputs(shared), "shared internal-id inputs").toEqual([]);

  // Shared: nothing to extend, no hearing, no order: each says why instead of an empty enabled select.
  await shared.getByLabel("Record type").selectOption("deadline_extended");
  await expect(shared.getByLabel("Active deadline")).toBeDisabled();
  await expect(shared.getByText(/This opposition has no confirmed deadline to extend/)).toBeVisible();
  await shared.getByLabel("Record type").selectOption("hearing_preparation_recorded");
  await expect(shared.getByLabel("Shared hearing")).toBeDisabled();
  await expect(shared.getByText(/No hearing is recorded for this IP record/)).toBeVisible();
  await shared.getByLabel("Record type").selectOption("appeal_linked");
  await expect(shared.getByLabel(/record ID/i)).toHaveCount(0);
  const target = shared.getByLabel("Appeal target");
  await expect(target).toHaveValue("");
  await expect(target.locator('option[value="appeal_proceeding"]')).toBeDisabled();
  await target.selectOption("matter");
  const appealMatter = await chooseMatterByTyping(page, "Appeal Matter", "Search Matters for the appeal", matter);
  await expectFieldFits(page, appealMatter, "Appeal Matter picker on screen");
  await expect(shared.getByLabel("Opposition order event")).toBeDisabled();
  await expect(shared.getByText(/No opposition order is recorded yet/)).toBeVisible();
  expect(await deadSelects(page, shared), "shared dead selects").toEqual([]);

  // Specialized: related application, trigger and affected classes come from the validator.
  expect(await internalIdInputs(specialized), "specialized internal-id inputs").toEqual([]);
  await expect(specialized.getByLabel("Related application")).toBeDisabled();
  await expect(specialized.getByText(/No other application is recorded on this IP record/)).toBeVisible();
  await specialized.getByTestId("ip-opposition-specialized-action").selectOption("disposition_review_recorded");
  await expect(specialized.getByLabel("Trigger event")).toBeDisabled();
  await expect(specialized.getByText(/This opposition has no order or outcome yet/)).toBeVisible();
  await expect(specialized.getByLabel("Class 9: Downloadable legal software")).toBeVisible();
  await specialized.getByTestId("ip-opposition-specialized-action").selectOption("hearing_notice_recorded");
  await expect(specialized.getByLabel("Applicable rules")).toHaveValue("Trade Marks Rules, 2017");
  await expect(specialized.getByTestId("ip-opposition-specialized-hearing")).toBeDisabled();
  expect(await deadSelects(page, specialized), "specialized dead selects").toEqual([]);
  await expectNoPageOverflow(page);
}

// Local only: an opposition with a confirmed profile has no UI creation path in
// this journey and test-legal opposition records are shared state; the
// fixture is built through the product API, the assertions drive the UI.
test("B4-ADJ-22 [local-only] opposition choices are never dead, never pre-selected and never ask for ids", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  expect(rt.local, "Opposition fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, false);
  try {
    await oppositionJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-22-opposition-desktop", { matterId: matter.id });
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-22 [mobile] [local-only] opposition choices fit a phone", async ({ page, request, baseURL }) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  expect(rt.local, "Opposition fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, true);
  try {
    await oppositionJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-22-opposition-mobile", { matterId: matter.id, width: viewport.width });
  } finally {
    await rt.release();
  }
});

async function createHearing(rt: TesterRuntime, request: APIRequestContext, docketId: string, status: "scheduled" | "completed") {
  const operational = status === "scheduled";
  return json<{ id: string; status: string }>(await request.post(`${rt.api.origin}/api/ip/hearings`, { headers: rt.headers, data: {
    docket_id: docketId, hearing_on: operational ? "2026-12-15" : "2026-10-01", forum_name: "Trade Marks Registry Delhi",
    purpose: operational ? "Opposition final hearing" : "Earlier opposition hearing", status,
    ...(operational
      ? { attendee_membership_ids: [rt.actor.membership.id], responsible_membership_id: rt.actor.membership.id }
      : { outcome_note: "Heard; orders reserved." }),
  } }), `Fixture ${status} hearing`, 201);
}

async function hearingChoiceJourney(page: Page, rt: TesterRuntime, request: APIRequestContext, matter: MatterRow) {
  const { docketId, proceedingId } = await oppositionFixture(rt, request, matter);
  const scheduled = await createHearing(rt, request, docketId, "scheduled");
  const completed = await createHearing(rt, request, docketId, "completed");
  const workflowRead = page.waitForResponse((row) => new URL(row.url()).pathname
    === `/api/ip/dockets/${docketId}/proceedings/${proceedingId}/opposition-shared-workflow`);
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&view=proceedings`);
  const workflow = await uiJson<{ hearing_statuses_by_action: Record<string, string[]>; shared_hearings: { id: string; status: string }[] }>(
    await workflowRead, "Shared workflow read");
  // The form's hearing rules are the API's table, not a copy.
  expect(workflow.hearing_statuses_by_action).toMatchObject({
    hearing_notice_recorded: ["adjourned", "scheduled"], attendance_recorded: ["completed"],
  });
  expect(workflow.shared_hearings.map((row) => `${row.id}:${row.status}`).sort()).toEqual(
    [`${scheduled.id}:scheduled`, `${completed.id}:completed`].sort());

  const specialized = page.getByTestId("ip-opposition-specialized-paths");
  await expect(specialized).toBeVisible();
  await specialized.getByTestId("ip-opposition-specialized-action").selectOption("hearing_notice_recorded");
  const hearing = specialized.getByTestId("ip-opposition-specialized-hearing");
  await expect(hearing).toBeEnabled();
  await expect(hearing).toHaveValue("");
  const completedOption = hearing.locator(`option[value="${completed.id}"]`);
  await expect(completedOption).toBeDisabled();
  await expect(completedOption).toContainText("not available for a completed hearing");
  await expect(hearing.locator(`option[value="${scheduled.id}"]`)).toBeEnabled();
  await hearing.selectOption(scheduled.id);
  await expectFieldFits(page, hearing, "Canonical hearing on screen");
  const label = stamp("NOTICE").replace(/\s+/g, "-");
  await specialized.getByLabel("Source reference").fill(`registry:hearing-notice:${label}`);
  await specialized.getByLabel("Lawyer confirmation").fill("Hearing notice reviewed by responsible counsel.");
  await specialized.getByLabel("Notice received").fill("2026-11-01");
  await specialized.getByLabel("Notice document").fill(`document:hearing-notice:${label}`);
  await expect(specialized.getByLabel("Applicable rules")).toHaveValue("Trade Marks Rules, 2017");
  await specialized.getByLabel("Policy confirmation").fill("Notice period checked against the rules.");
  await specialized.getByLabel("Evidence references").fill(`evidence:hearing-notice:${label}`);
  await specialized.getByLabel("Reason").fill("Registry hearing notice received for the scheduled hearing.");
  const submit = specialized.getByTestId("ip-opposition-specialized-submit");
  await expect(submit).toBeEnabled();
  const posted = page.waitForResponse((row) => new URL(row.url()).pathname
    === `/api/ip/dockets/${docketId}/proceedings/${proceedingId}/opposition-shared-actions` && row.request().method() === "POST");
  await submit.click();
  const after = await uiJson<{ shared_actions: { payload_json: { action_kind?: string; hearing_notice?: { shared_hearing_id?: string } } }[] }>(
    await posted, "UI hearing notice", 201);
  const notices = after.shared_actions.filter((row) => row.payload_json.action_kind === "hearing_notice_recorded");
  expect(notices.map((row) => row.payload_json.hearing_notice?.shared_hearing_id)).toEqual([scheduled.id]);

  // Attendance accepts only a completed hearing: the choice flips.
  await specialized.getByTestId("ip-opposition-specialized-action").selectOption("attendance_recorded");
  await expect(hearing).toHaveValue("");
  await expect(hearing.locator(`option[value="${scheduled.id}"]`)).toBeDisabled();
  await expect(hearing.locator(`option[value="${scheduled.id}"]`)).toContainText("mark the hearing completed first");
  await expect(hearing.locator(`option[value="${completed.id}"]`)).toBeEnabled();
  expect(await deadSelects(page, specialized), "specialized dead selects").toEqual([]);
  await expectNoPageOverflow(page);
}

// Local only: same opposition fixture as the B4-ADJ-22 journeys above.
test("B4-ADJ-22 [local-only] a specialized hearing record is accepted on the hearing the served table allows", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  expect(rt.local, "Opposition fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, false);
  try {
    await hearingChoiceJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-22-hearing-choice-desktop", { matterId: matter.id });
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-22 [mobile] [local-only] the hearing choice and submit work on a phone", async ({ page, request, baseURL }) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  expect(rt.local, "Opposition fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, true);
  try {
    await hearingChoiceJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-22-hearing-choice-mobile", { matterId: matter.id, width: viewport.width });
  } finally {
    await rt.release();
  }
});

async function reportJourney(page: Page, rt: TesterRuntime, request: APIRequestContext, matter: MatterRow) {
  const { docketId, title } = await oppositionFixture(rt, request, matter);
  await page.goto(`${rt.web.origin}/app/ip/reports`);
  await page.getByLabel("Report", { exact: true }).selectOption("portfolio_register");
  await page.getByLabel("Keyword").fill(title);
  const preview = page.waitForResponse((row) => new URL(row.url()).pathname === "/api/ip/reports/preview"
    && row.request().method() === "POST");
  await page.getByRole("button", { name: "Generate" }).click();
  const report = await uiJson<{ rows: Record<string, unknown>[] }>(await preview, "Report preview");
  const row = report.rows.find((candidate) => candidate.docket_id === docketId);
  expect(row, "The stamped IP record is in the preview").toBeTruthy();
  // The server still sends internal ids; the table must not show them.
  expect(Object.keys(row!)).toEqual(expect.arrayContaining(["application_id", "docket_id", "matter_id"]));
  const result = page.getByTestId("ip-report-result");
  const table = result.getByRole("table");
  await expect(table).toContainText(title);
  const headers = await result.getByRole("columnheader").allTextContents();
  expect(headers).toContain("Docket title");
  expect(headers.filter((header) => /\bid\b/i.test(header))).toEqual([]);
  const text = (await table.textContent()) ?? "";
  expect(text).not.toMatch(UUID);
  expect(text).not.toContain(matter.id);
  await expectOnScreen(result.getByRole("heading", { name: "Portfolio register" }), "Report heading on screen");
  await expectNoPageOverflow(page);
}

// Local only: the report needs a stamped IP record, which has no disposal path in test-legal.
test("B4-ADJ-02 [local-only] the IP report preview never shows internal id columns", async ({ page, request, baseURL }) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  expect(rt.local, "Report fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, false);
  try {
    await reportJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-02-report-columns-desktop", { matterId: matter.id });
  } finally {
    await rt.release();
  }
});

test("B4-ADJ-02 [mobile] [local-only] the IP report preview fits a phone without id columns", async ({ page, request, baseURL }) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  expect(rt.local, "Report fixture is local-only acceptance").toBe(true);
  const matter = await createMatterInUi(page, rt, true);
  try {
    await reportJourney(page, rt, request, matter);
    await markPositive(test.info(), "adj-02-report-columns-mobile", { matterId: matter.id, width: viewport.width });
  } finally {
    await rt.release();
  }
});
