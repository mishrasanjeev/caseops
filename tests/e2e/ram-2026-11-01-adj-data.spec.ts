/**
 * Adjacent data-correctness defects found while fixing Ram's batch 4
 * (CaseOps_Bugs (4).xlsx, 2026-10-30):
 *
 * - B4-ADJ-11: a portfolio import's Status column sets the real filing phase.
 *   An imported Registered mark's portfolio Status leads with "Registered
 *   (source, unverified)", never a Draft badge; the docket's particulars state
 *   is labelled beneath it. Wording the import does not recognise imports as
 *   draft with a note and is shown the same way; a filed status without an
 *   application number is refused at that field.
 * - B4-ADJ-19: reminder offsets keep "48h" / "1d" and name any token they
 *   cannot read, on the IP hearing form and on the foreign-associate
 *   acknowledgement reminders; the hearing preview names recipients, never ids.
 * - B4-ADJ-20: a manual-only journal watch profile shows no scheduled check.
 *   (That the scheduler records no "succeeded 0/0" run is proven in pytest:
 *   the scheduler worker does not run in the local browser stack.)
 * - B4-ADJ-23: a Gmail-imported email's escaped snippet reads decoded, and
 *   identically, on the calendar-copy candidate and the matter timeline.
 *
 * Signed in as the tester through the real form. The reminder-offset checks
 * run in production on a record chosen by server identity and never submit,
 * so they change nothing. The import, watch, Gmail and acknowledgement-submit
 * journeys are [local-only]: portfolio import jobs, Gmail mailbox imports,
 * calendar candidates and foreign-associate instructions have no retire path,
 * a Gmail mailbox exists only through the local offline fixture, so a
 * production run would leave records the product cannot remove (AGENTS.md
 * fixture rule).
 */
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { createForeignAssociateFixture, createInstruction, recordForeignAssociateTransaction } from "./support/iplf059b";
import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const MOBILE = { width: 393, height: 851 };

type ImportRow = {
  id: string; row_number: number; validation_status: string; commit_status: string;
  created_docket_id: string | null; errors: { field: string; code: string }[];
  normalized: Record<string, unknown> & { _warnings?: { field: string; code: string }[] };
};
type ImportResult = { job: { id: string; status: string; committed_rows: number; preview_token: string }; rows: ImportRow[] };
type Imported = { registeredId: string; unrecognisedId: string; mark: string; number: string };

const slug = (prefix: string) => stamp(prefix).replace(/[^A-Za-z0-9]+/g, "-");

function csv(rows: string[][]): Buffer {
  return Buffer.from(rows.map(row => row.map(cell => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\r\n"), "utf8");
}

async function retireDocket(request: APIRequestContext, rt: TesterRuntime, docketId: string) {
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Read docket for cleanup");
  const body = {
    expected_lifecycle_version: docket.lifecycle_version, to_status: "retired", effective_at: new Date().toISOString(),
    reason: `Ram batch-4 adjacent acceptance record ${rt.run}`, outcome: "test record retired", source: "manual_review",
    evidence_ref: `e2e:${rt.run}`, successor_docket_id: null, acknowledged_exception_codes: [] as string[],
    second_approver_membership_id: null, client_report_handling: "retain", linked_matter_handling: "not_linked",
  };
  const preview = await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle/preview`,
    { headers: rt.headers, data: body }), "Preview docket retirement");
  body.acknowledged_exception_codes = preview.blocker_codes ?? [];
  await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle`, { headers: rt.headers, data: body }),
    "Retire acceptance docket");
}

/** B4-ADJ-11 through the imports page: a registered mark, unrecognised wording, a numberless row. */
async function importRegisteredMark(page: Page, rt: TesterRuntime, mobile: boolean): Promise<Imported> {
  const mark = stamp("ADJ11 REGISTERED");
  const number = slug("TM-ADJ11");
  const content = csv([
    ["Trademark", "Application No.", "Class", "Applicant", "Status", "Jurisdiction", "Office"],
    [mark, number, "9", "Adjacent Source LLP", "Registered", "IN", "IP India"],
    [`${mark} typo`, `${number}-T`, "9", "Adjacent Source LLP", "Regsitered", "IN", "IP India"],
    [`${mark} numberless`, "", "9", "Adjacent Source LLP", "Registered", "IN", "IP India"],
  ]);
  await page.goto(`${rt.web.origin}/app/ip/portfolio/imports`);
  await expect(page.getByRole("heading", { name: "Trademark portfolio import", exact: true })).toBeVisible();
  await page.getByLabel("CSV or XLSX file").setInputFiles({ name: `adj11-${rt.run}.csv`, mimeType: "text/csv", buffer: content });
  const uploaded = page.waitForResponse(r => new URL(r.url()).pathname === "/api/ip/imports/upload" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Validate file", exact: true }).click();
  const uploadResponse = await uploaded;
  expect(uploadResponse.status(), "Validate import").toBe(201);
  const preview = await uploadResponse.json() as ImportResult;
  expect(preview.rows.map(row => row.validation_status)).toEqual(["valid", "valid", "invalid"]);
  expect(preview.rows[0].normalized.filing_phase).toBe("filed");
  expect(preview.rows[0].normalized.declared_status).toBe("registered");
  // Unrecognised wording never blocks a row: it imports as draft with a note.
  expect(preview.rows[1].errors).toEqual([]);
  expect(preview.rows[1].normalized.filing_phase).toBeUndefined();
  expect(preview.rows[1].normalized._warnings).toContainEqual({ field: "source_status", code: "unrecognised_status" });
  expect(preview.rows[2].errors).toContainEqual({ field: "application_number", code: "required_for_source_status" });

  const note = page.getByRole("group", { name: "Non-blocking notes for row 1", exact: true })
    .getByText(/^Status: Imported as Filed\. "Registered" is kept as the unverified source status/);
  await note.scrollIntoViewIfNeeded();
  await expectOnScreen(note, "The registered row says it imports as Filed with an unverified source status");
  const typo = page.getByRole("group", { name: "Non-blocking notes for row 2", exact: true })
    .getByText(/^Status: "Regsitered" is not a status this import recognises, so the row imports in the Draft phase/);
  await typo.scrollIntoViewIfNeeded();
  await expectOnScreen(typo, "Unrecognised wording is explained as a non-blocking note at its field");
  await expect(page.getByRole("group", { name: "Blocking issues for row 2", exact: true })).toHaveCount(0);
  const numberless = page.getByRole("group", { name: "Blocking issues for row 3", exact: true })
    .getByText(/^Application number: Required: a "Registered" mark has been filed/);
  await numberless.scrollIntoViewIfNeeded();
  await expectOnScreen(numberless, "The missing application number is named at its field");
  if (mobile) await expectNoPageOverflow(page);
  expect(await deadSelects(page, page.locator("main"))).toEqual([]);

  const committing = page.waitForResponse(r => new URL(r.url()).pathname === `/api/ip/imports/${preview.job.id}/commit`);
  await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
  const commitResponse = await committing;
  expect(commitResponse.status(), "Commit import").toBe(200);
  const saved = await commitResponse.json() as ImportResult;
  expect(saved.job.status).toBe("committed");
  expect(saved.job.committed_rows).toBe(2);
  expect(saved.rows.map(row => row.commit_status)).toEqual(["committed", "committed", "skipped"]);
  const [registeredId, unrecognisedId] = saved.rows.map(row => row.created_docket_id);
  expect(registeredId).toMatch(/^[0-9a-f-]{36}$/);
  expect(unrecognisedId).toMatch(/^[0-9a-f-]{36}$/);
  return { registeredId: registeredId as string, unrecognisedId: unrecognisedId as string, mark, number };
}

async function portfolioLeadsWithSourceStatus(page: Page, request: APIRequestContext, rt: TesterRuntime, imported: Imported) {
  const oracle = await json(await request.get(`${rt.api.origin}/api/ip/portfolio`, { headers: rt.headers, params: { query: imported.mark } }), "Portfolio oracle");
  const byId = new Map((oracle.rows as Array<Record<string, unknown> & { docket_id: string }>).map(row => [row.docket_id, row]));
  expect(byId.get(imported.registeredId)).toMatchObject({
    filing_phase: "filed", docket_status: "draft", source_declared_status: "registered", source_status_text: "Registered",
  });
  expect(byId.get(imported.unrecognisedId)).toMatchObject({
    filing_phase: "draft", source_declared_status: null, source_status_text: "Regsitered",
  });
  await page.goto(`${rt.web.origin}/app/ip/portfolio`);
  await page.getByLabel("Search marks and registry numbers").fill(imported.mark);
  const searched = page.waitForResponse(r => new URL(r.url()).pathname === "/api/ip/portfolio" && new URL(r.url()).searchParams.get("query") === imported.mark);
  await page.getByRole("button", { name: "Search portfolio" }).click();
  expect((await searched).status()).toBe(200);
  // The table renders at desktop and the cards at phone width; read whichever is shown.
  const registered = page.getByTestId(`ip-portfolio-status-${imported.registeredId}`).filter({ visible: true });
  await expect(registered).toHaveCount(1);
  await registered.scrollIntoViewIfNeeded();
  await expectOnScreen(registered, "The imported registered mark's Status is on screen");
  await expect(registered.locator(":scope > *").first()).toHaveText("Registered (source, unverified)");
  await expect(registered).toContainText("Filing phase: Filed");
  await expect(registered).toContainText("Record: particulars draft");
  await expect(registered.locator(":scope > *").filter({ hasText: /^draft$/i })).toHaveCount(0);
  const unrecognised = page.getByTestId(`ip-portfolio-status-${imported.unrecognisedId}`).filter({ visible: true });
  await expect(unrecognised).toHaveCount(1);
  await expect(unrecognised.locator(":scope > *").first()).toHaveText("Regsitered (source, unverified)");
  await expect(unrecognised).toContainText("Filing phase: Draft");
}

/** B4-ADJ-19 on the docket's hearing form; nothing is submitted. */
async function reminderOffsets(page: Page, request: APIRequestContext, rt: TesterRuntime, docketId: string, mobile: boolean, info: TestInfo) {
  const me = await json(await request.get(`${rt.api.origin}/api/auth/me`, { headers: rt.headers }), "Signed-in member");
  await page.goto(`${rt.web.origin}/app/ip?docket=${encodeURIComponent(docketId)}&view=schedule`);
  await page.getByRole("tab", { name: "Hearings and deadlines", exact: true }).click();
  const form = page.getByTestId("ip-hearing-workflow");
  await expect(form).toBeVisible();
  const offsets = form.getByLabel("Reminder offsets", { exact: true });
  const preview = form.getByRole("button", { name: "Preview recipients and policy", exact: true });
  await offsets.fill("48h, soon");
  await expect(offsets).toHaveAttribute("aria-invalid", "true");
  const error = form.locator("#ip-hearing-reminder-offsets-help");
  await expect(error).toHaveText(/^"soon" is not a reminder offset\./);
  await expect(error).toHaveAttribute("role", "alert");
  await error.scrollIntoViewIfNeeded();
  await expectOnScreen(error, "The unreadable offset is named under its field");
  await expect(preview).toBeDisabled();

  await offsets.fill("48h, 1d");
  await expect(offsets).not.toHaveAttribute("aria-invalid", "true");
  await expect(error).toHaveText(/^Before the hearing: 48, 24 hours\./);
  await preview.click();
  const policy = form.getByTestId("ip-hearing-preview");
  await expectOnScreen(policy, "The confirmed policy is on screen");
  await expect(policy).toContainText("Offsets: 48, 24 hours");
  await expect(policy).toContainText(me.user.full_name);
  await expect(policy).not.toContainText(rt.actor.membership.id);
  if (mobile) await expectNoPageOverflow(page);
  await form.getByRole("button", { name: "Edit details", exact: true }).click();
  await expect(policy).toHaveCount(0);
  await markPositive(info, "b4-adj-19-offsets", { docket_id: docketId, offsets_hours: [48, 24], submitted: false });
}

/** Production: an active docket the tester can open, chosen by server identity. */
async function productionDocket(request: APIRequestContext, rt: TesterRuntime): Promise<string> {
  const list = await json(await request.get(`${rt.api.origin}/api/ip/dockets`, { headers: rt.headers, params: { limit: 50, record_type: "trademark" } }), "Tester trademark dockets");
  const active = (list.dockets as { id: string; is_active: boolean; status: string }[])
    .find(row => row.is_active && !["retired", "archived", "closed", "abandoned", "transferred"].includes(row.status));
  expect(active, "The tester needs one active IP docket to open the hearing form").toBeTruthy();
  return (active as { id: string }).id;
}

async function offsetsJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  const created: string[] = [];
  try {
    // Locally the tester has no docket yet; one is made through the imports page.
    let docketId: string;
    if (rt.local) {
      const imported = await importRegisteredMark(page, rt, mobile);
      created.push(imported.registeredId, imported.unrecognisedId);
      docketId = imported.registeredId;
    } else {
      docketId = await productionDocket(request, rt);
    }
    await reminderOffsets(page, request, rt, docketId, mobile, info);
  } finally {
    for (const id of created) await retireDocket(request, rt, id);
  }
}

test("B4-ADJ-19 reminder offsets keep 48h and name an unreadable token at the field", async ({ page, request, baseURL }, info) => {
  await offsetsJourney(page, request, baseURL, info, false);
});

test("B4-ADJ-19 [mobile] reminder offsets at phone width", async ({ page, request, baseURL }, info) => {
  await offsetsJourney(page, request, baseURL, info, true);
});

type Instruction = { id: string; target_jurisdiction: string; scope_json: { source_reference?: string } };

/** Opens one instruction's Reminders tab by its unique source reference. */
async function openReminders(page: Page, rt: TesterRuntime, instruction: Instruction) {
  await page.goto(`${rt.web.origin}/app/ip/foreign-associates`);
  await expect(page.getByRole("heading", { name: "Foreign associates", exact: true })).toBeVisible();
  const row = page.getByRole("button")
    .filter({ hasText: `${instruction.target_jurisdiction} · ${instruction.scope_json.source_reference}` });
  await expect(row).toHaveCount(1);
  await row.click();
  await page.getByRole("tab", { name: "Reminders", exact: true }).click();
  const offsets = page.getByLabel("Reminder offsets before due", { exact: true });
  await expect(offsets).toBeVisible();
  return offsets;
}

/** B4-ADJ-19 sibling: the acknowledgement reminder offsets read 48h/2d and name a bad token. */
async function acknowledgementOffsetsField(page: Page, offsets: ReturnType<Page["getByLabel"]>, mobile: boolean) {
  const schedule = page.getByRole("button", { name: "Schedule reminders", exact: true });
  const error = page.locator("#fa-reminder-offsets-error");
  for (const [input, message] of [
    ["48h, soon", /^"soon" is not a reminder offset\./],
    ["24, 24", /^"24" repeats an offset of 24 hours already entered\./],
    ["31d", /^"31d" is 744 hours; the most allowed is 720 hours\.$/],
  ] as const) {
    await offsets.fill(input);
    await expect(offsets).toHaveAttribute("aria-invalid", "true");
    await expect(error).toHaveText(message);
    await expect(error).toHaveAttribute("role", "alert");
    await expect(schedule).toBeDisabled();
  }
  await error.scrollIntoViewIfNeeded();
  await expectOnScreen(error, "The rejected offset is named under its field");
  await offsets.fill("48h, 1d, 0");
  await expect(offsets).not.toHaveAttribute("aria-invalid", "true");
  await expect(error).toHaveCount(0);
  const hint = page.locator("#fa-reminder-offsets-hint");
  await expect(hint).toHaveText(/^Before the acknowledgement is due: 48, 24, 0 hours\./);
  await expectOnScreen(hint, "The parsed offsets are read back under the field");
  if (mobile) await expectNoPageOverflow(page);
  return schedule;
}

/** Production: an instruction the tester can open, chosen by a unique server reference. Never submits. */
async function productionInstruction(request: APIRequestContext, rt: TesterRuntime): Promise<Instruction> {
  const list = await json(await request.get(`${rt.api.origin}/api/ip/foreign-associate-instructions`,
    { headers: rt.headers, params: { limit: 100, offset: 0 } }), "Tester foreign-associate instructions");
  const items = list.items as Instruction[];
  const label = (row: Instruction) => `${row.target_jurisdiction} · ${row.scope_json.source_reference}`;
  const unique = items.find(row => row.scope_json.source_reference && items.filter(other => label(other) === label(row)).length === 1);
  expect(unique, "The tester needs one foreign-associate instruction with a unique reference (BUG-009 runs leave cancelled ones)").toBeTruthy();
  return unique as Instruction;
}

async function acknowledgementFieldJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  const instruction = rt.local ? await localDispatchedInstruction(request, rt) : await productionInstruction(request, rt);
  const offsets = await openReminders(page, rt, instruction);
  await acknowledgementOffsetsField(page, offsets, mobile);
  await markPositive(info, "b4-adj-19-acknowledgement-offsets", { instruction_id: instruction.id, submitted: false });
}

/** Local only: an approved, dispatched instruction whose acknowledgement is outstanding. */
async function localDispatchedInstruction(request: APIRequestContext, rt: TesterRuntime): Promise<Instruction> {
  expect(rt.local, "Foreign-associate instructions cannot be retired; they are created only locally").toBe(true);
  const runId = slug("ADJ19FA");
  const fixture = await createForeignAssociateFixture(request, rt.api.origin, rt.headers, rt.actor.membership.id, runId);
  const instruction = await createInstruction(request, rt.api.origin, rt.headers, fixture, "ADJ19");
  await recordForeignAssociateTransaction(request, rt.api.origin, rt.headers, fixture, instruction, "approve");
  await recordForeignAssociateTransaction(request, rt.api.origin, rt.headers, fixture, instruction, "dispatch", {
    external_dispatch_reference: `mail:dispatch:${runId}`,
    external_delivery_reference: `mail:delivered:${runId}`,
    external_delivered_at: new Date().toISOString(),
    evidence_refs: [`https://example.com/evidence/dispatch/${runId}`],
  });
  const workspace = await json(await request.get(`${rt.api.origin}/api/ip/foreign-associate-instructions/${instruction.id}/workspace`,
    { headers: rt.headers }), "Dispatched instruction workspace");
  expect(workspace.instruction.status).toBe("dispatched");
  expect(workspace.acknowledgement_status).toBe("outstanding");
  return workspace.instruction as Instruction;
}

test("B4-ADJ-19 acknowledgement reminder offsets read 48h/1d and name a rejected token at the field", async ({ page, request, baseURL }, info) => {
  await acknowledgementFieldJourney(page, request, baseURL, info, false);
});

test("B4-ADJ-19 [mobile] acknowledgement reminder offsets at phone width", async ({ page, request, baseURL }, info) => {
  await acknowledgementFieldJourney(page, request, baseURL, info, true);
});

test("[local-only] B4-ADJ-19 Schedule reminders sends the parsed acknowledgement offsets", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  const instruction = await localDispatchedInstruction(request, rt);
  const offsets = await openReminders(page, rt, instruction);
  const schedule = await acknowledgementOffsetsField(page, offsets, false);
  await expect(schedule).toBeEnabled();
  const scheduling = page.waitForResponse(r => new URL(r.url()).pathname === `/api/ip/foreign-associate-instructions/${instruction.id}/reminders`);
  await schedule.click();
  const response = await scheduling;
  expect(response.status(), "Schedule acknowledgement reminders").toBe(200);
  expect(response.request().postDataJSON().reminder_offsets_hours).toEqual([48, 24, 0]);
  const result = await response.json();
  expect(result.created_count).toBeGreaterThan(0);
  await markPositive(info, "b4-adj-19-acknowledgement-schedule", { instruction_id: instruction.id, offsets_hours: [48, 24, 0] });
});

async function importJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  expect(rt.local, "Import jobs cannot be retired; this journey is local-only").toBe(true);
  const imported = await importRegisteredMark(page, rt, mobile);
  try {
    await portfolioLeadsWithSourceStatus(page, request, rt, imported);
    if (mobile) await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-11-import", { docket_id: imported.registeredId, filing_phase: "filed", status: "Registered (source, unverified)" });

    // B4-ADJ-20: a manual profile on this docket shows no scheduled check.
    const profile = await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles`, {
      headers: rt.headers,
      data: { docket_id: imported.registeredId, name: stamp("ADJ20 manual watch"), word_terms: ["ADJ20"], frequency: "publication",
        recipient_membership_ids: [rt.actor.membership.id], cost_currency: "INR" },
    }), "Manual watch profile prerequisite", 201);
    expect(profile.provider_key).toBe("manual-journal");
    expect(profile.next_poll_at).toBeNull();
    await page.goto(`${rt.web.origin}/app/ip/watch`);
    await page.getByRole("button", { name: "Profiles", exact: true }).click();
    const card = page.getByTestId(`watch-profile-${profile.id}`);
    const scheduled = card.getByText("None: manual intake only", { exact: true });
    await scheduled.scrollIntoViewIfNeeded();
    await expectOnScreen(scheduled, "A manual-only profile says it has no scheduled check");
    await expect(card.getByText("Next check", { exact: true })).toHaveCount(0);
    if (mobile) await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-20-manual-profile", { profile_id: profile.id });
    await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles/${profile.id}/status`, {
      headers: rt.headers, data: { expected_version: profile.version, poll_status: "disabled", reason: "Adjacent acceptance cleanup" },
    }), "Disable acceptance watch profile");
  } finally {
    await retireDocket(request, rt, imported.registeredId);
    await retireDocket(request, rt, imported.unrecognisedId);
  }
}

test("[local-only] B4-ADJ-11 B4-ADJ-20 an imported registered mark's Status reads Registered (source, unverified), and a manual watch has no scheduled check", async ({ page, request, baseURL }, info) => {
  await importJourney(page, request, baseURL, info, false);
});

test("[local-only] B4-ADJ-11 B4-ADJ-20 [mobile] import and manual watch at phone width", async ({ page, request, baseURL }, info) => {
  await importJourney(page, request, baseURL, info, true);
});

async function gmailCalendarJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? MOBILE : undefined);
  expect(rt.local, "Gmail imports and calendar candidates cannot be retired, and the Gmail mailbox is the local offline fixture").toBe(true);
  // Prerequisites through the API: the Matter, the offline Gmail mailbox and
  // the product's own Gmail import route; the decoded text is what is tested.
  const matter = await json(await request.post(`${rt.api.origin}/api/matters`, {
    headers: rt.headers,
    data: { matter_code: slug("ADJ23"), title: stamp("ADJ23 calendar copy"), practice_area: "Civil", forum_level: "high_court" },
  }), "Local matter prerequisite");
  const fixture = await json(await request.post(`${rt.api.origin}/_e2e/gmail-import/fixtures`, {
    headers: rt.headers, data: { matter_id: matter.id },
  }), "Offline Gmail mailbox prerequisite");
  expect(fixture.snippet).toContain("&amp;");
  const imported = await json(await request.post(`${rt.api.origin}/api/mailbox/gmail/import`, {
    headers: rt.headers, data: { limit: 10 },
  }), "Product Gmail import");
  expect(imported.summary.imported).toBe(1);
  const decoded = fixture.decoded as string;

  await page.goto(`${rt.web.origin}/app/calendar`);
  const panel = page.getByTestId("calendar-email-candidates-panel");
  await panel.scrollIntoViewIfNeeded();
  const extracting = page.waitForResponse(r => new URL(r.url()).pathname === "/api/calendar/email-invitation-candidates/extract");
  await panel.getByTestId("calendar-email-candidates-extract").click();
  const extractResponse = await extracting;
  expect(extractResponse.status(), "Scan imported emails").toBe(200);
  const extracted = await extractResponse.json();
  expect(extracted.created_count).toBe(1);
  const candidate = extracted.candidates[0];
  expect(candidate.matter_id).toBe(matter.id);
  expect(candidate.detected_location).toBe("Court & Chamber 4");
  expect(candidate.source_preview).toContain(decoded);
  const preview = panel.getByText(decoded);
  await preview.scrollIntoViewIfNeeded();
  await expectOnScreen(preview, "The calendar candidate shows the decoded Gmail text");
  await expect(panel).toContainText("Court & Chamber 4");
  for (const entity of ["&#39;", "&amp;", "&quot;", "&nbsp;"]) await expect(panel).not.toContainText(entity);
  if (mobile) await expectNoPageOverflow(page);

  // The same email on the matter timeline reads the same decoded sentence.
  const timeline = await json(await request.get(`${rt.api.origin}/api/matters/${matter.id}/communications/timeline`, { headers: rt.headers }), "Timeline oracle");
  const item = (timeline.items as { id: string; preview: string | null }[]).find(row => row.preview === decoded);
  expect(item, "The Gmail communication's timeline preview is the decoded sentence").toBeTruthy();
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/communications`);
  const row = page.getByTestId(`communication-timeline-${(item as { id: string }).id}`);
  await row.scrollIntoViewIfNeeded();
  await expectOnScreen(row, "The matter timeline shows the same decoded Gmail text");
  await expect(row).toContainText(decoded);
  for (const entity of ["&#39;", "&amp;", "&quot;"]) await expect(row).not.toContainText(entity);
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, "b4-adj-23-gmail-calendar-copy", { candidate_id: candidate.id, communication_timeline_id: (item as { id: string }).id });
}

test("[local-only] B4-ADJ-23 a Gmail email reads decoded on the calendar candidate and the matter timeline", async ({ page, request, baseURL }, info) => {
  await gmailCalendarJourney(page, request, baseURL, info, false);
});

test("[local-only] B4-ADJ-23 [mobile] Gmail calendar-copy and timeline text at phone width", async ({ page, request, baseURL }, info) => {
  await gmailCalendarJourney(page, request, baseURL, info, true);
});
