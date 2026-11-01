/**
 * Adjacent data-correctness defects found while fixing Ram's batch 4
 * (CaseOps_Bugs (4).xlsx, 2026-10-30):
 *
 * - B4-ADJ-11: a portfolio import's Status column sets the real filing phase,
 *   keeps "Registered" as the unverified source status beside it, and refuses
 *   an unreadable status or a filed status without a number at the field.
 * - B4-ADJ-19: IP hearing reminder offsets keep "48h" / "1d" and name any
 *   token they cannot read; the preview names recipients, never ids.
 * - B4-ADJ-20: a manual-only journal watch profile shows no scheduled check
 *   and the scheduler records no "succeeded 0/0" run for it.
 * - B4-ADJ-23: calendar-copy candidates show decoded email text.
 *
 * Signed in as the tester through the real form. The reminder-offset check
 * runs in production on an active docket chosen by server identity and never
 * submits, so it changes nothing. The import, watch and calendar-copy
 * journeys are [local-only]: portfolio import jobs, email imports and
 * calendar candidates have no retire path, so a production run would leave
 * records the product cannot remove (AGENTS.md fixture rule).
 */
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type ImportRow = {
  id: string; row_number: number; validation_status: string; commit_status: string;
  created_docket_id: string | null; errors: { field: string; code: string }[];
  normalized: Record<string, unknown> & { _warnings?: { field: string; code: string }[] };
};
type ImportResult = { job: { id: string; status: string; committed_rows: number; preview_token: string }; rows: ImportRow[] };

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

/** B4-ADJ-11 through the imports page: one registered mark, one typo, one numberless row. */
async function importRegisteredMark(page: Page, rt: TesterRuntime, mobile: boolean) {
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
  expect(preview.rows.map(row => row.validation_status)).toEqual(["valid", "invalid", "invalid"]);
  expect(preview.rows[0].normalized.filing_phase).toBe("filed");
  expect(preview.rows[0].normalized.declared_status).toBe("registered");
  expect(preview.rows[1].errors).toContainEqual({ field: "source_status", code: "unsupported_status" });
  expect(preview.rows[2].errors).toContainEqual({ field: "application_number", code: "required_for_source_status" });

  const note = page.getByRole("group", { name: "Non-blocking notes for row 1", exact: true })
    .getByText(/^Status: Imported as Filed\. "Registered" is kept as the unverified source status/);
  await note.scrollIntoViewIfNeeded();
  await expectOnScreen(note, "The registered row says it imports as Filed with an unverified source status");
  const typo = page.getByRole("group", { name: "Blocking issues for row 2", exact: true })
    .getByText(/^Status: "Regsitered" is not a recognised trademark status/);
  await typo.scrollIntoViewIfNeeded();
  await expectOnScreen(typo, "The unreadable status is refused at its field");
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
  expect(saved.job.committed_rows).toBe(1);
  expect(saved.rows.map(row => row.commit_status)).toEqual(["committed", "skipped", "skipped"]);
  const docketId = saved.rows[0].created_docket_id;
  expect(docketId).toMatch(/^[0-9a-f-]{36}$/);
  return { docketId: docketId as string, mark, number };
}

async function portfolioShowsDeclaredStatus(page: Page, request: APIRequestContext, rt: TesterRuntime, imported: { docketId: string; number: string }) {
  const oracle = await json(await request.get(`${rt.api.origin}/api/ip/portfolio`, { headers: rt.headers, params: { query: imported.number } }), "Portfolio oracle");
  const row = oracle.rows.find((item: { docket_id: string }) => item.docket_id === imported.docketId);
  expect(row.filing_phase).toBe("filed");
  expect(row.source_declared_status).toBe("registered");
  await page.goto(`${rt.web.origin}/app/ip/portfolio`);
  await page.getByLabel("Search marks and registry numbers").fill(imported.number);
  const searched = page.waitForResponse(r => new URL(r.url()).pathname === "/api/ip/portfolio" && new URL(r.url()).searchParams.get("query") === imported.number);
  await page.getByRole("button", { name: "Search portfolio" }).click();
  expect((await searched).status()).toBe(200);
  const declared = page.getByTestId(`ip-portfolio-declared-status-${imported.docketId}`).first();
  await declared.scrollIntoViewIfNeeded();
  await expectOnScreen(declared, "The imported registered mark shows its unverified source status");
  await expect(declared).toHaveText("Source status: registered (unverified)");
  await expect(page.getByText("Filing phase: filed").first()).toBeVisible();
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
  await offsets.scrollIntoViewIfNeeded();
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
  const rt = await prepareTester(page, request, baseURL, mobile ? { width: 393, height: 851 } : undefined);
  let created: string | null = null;
  try {
    // Locally the tester has no docket yet; one is made through the imports page.
    const docketId = rt.local ? (created = (await importRegisteredMark(page, rt, mobile)).docketId) : await productionDocket(request, rt);
    await reminderOffsets(page, request, rt, docketId, mobile, info);
  } finally {
    if (created) await retireDocket(request, rt, created);
  }
}

test("B4-ADJ-19 reminder offsets keep 48h and name an unreadable token at the field", async ({ page, request, baseURL }, info) => {
  await offsetsJourney(page, request, baseURL, info, false);
});

test("B4-ADJ-19 [mobile] reminder offsets at phone width", async ({ page, request, baseURL }, info) => {
  await offsetsJourney(page, request, baseURL, info, true);
});

async function importJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? { width: 393, height: 851 } : undefined);
  expect(rt.local, "Import jobs cannot be retired; this journey is local-only").toBe(true);
  const imported = await importRegisteredMark(page, rt, mobile);
  try {
    await portfolioShowsDeclaredStatus(page, request, rt, imported);
    if (mobile) await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-11-import", { docket_id: imported.docketId, filing_phase: "filed", declared: "registered" });

    // B4-ADJ-20: a manual profile on this docket shows no scheduled check.
    const profile = await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles`, {
      headers: rt.headers,
      data: { docket_id: imported.docketId, name: stamp("ADJ20 manual watch"), word_terms: ["ADJ20"], frequency: "publication",
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
    const workspace = await json(await request.get(`${rt.api.origin}/api/ip/watch`, { headers: rt.headers }), "Watch oracle");
    expect(workspace.ingestion_runs.filter((run: { idempotency_key: string }) => run.idempotency_key.startsWith("scheduler:"))).toEqual([]);
    if (mobile) await expectNoPageOverflow(page);
    await markPositive(info, "b4-adj-20-manual-profile", { profile_id: profile.id });
    await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles/${profile.id}/status`, {
      headers: rt.headers, data: { expected_version: profile.version, poll_status: "disabled", reason: "Adjacent acceptance cleanup" },
    }), "Disable acceptance watch profile");
  } finally {
    await retireDocket(request, rt, imported.docketId);
  }
}

test("[local-only] B4-ADJ-11 B4-ADJ-20 an imported registered mark reads Filed with its source status, and a manual watch has no scheduled check", async ({ page, request, baseURL }, info) => {
  await importJourney(page, request, baseURL, info, false);
});

test("[local-only] B4-ADJ-11 B4-ADJ-20 [mobile] import and manual watch at phone width", async ({ page, request, baseURL }, info) => {
  await importJourney(page, request, baseURL, info, true);
});

async function calendarCopyJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo, mobile: boolean) {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, mobile ? { width: 393, height: 851 } : undefined);
  expect(rt.local, "Email imports and calendar candidates cannot be retired; this journey is local-only").toBe(true);
  // Prerequisites through the API: the email import is not the workflow under test; the candidate text is.
  const matter = await json(await request.post(`${rt.api.origin}/api/matters`, {
    headers: rt.headers,
    data: { matter_code: slug("ADJ23"), title: stamp("ADJ23 calendar copy"), practice_area: "Civil", forum_level: "high_court" },
  }), "Local matter prerequisite");
  await json(await request.post(`${rt.api.origin}/api/matters/${matter.id}/communications/import-email`, {
    headers: rt.headers,
    data: {
      provider: "manual", provider_message_id: slug("adj23-invite"), sender_email: "client@example.in", sender_name: "Client Sender",
      to_recipients: ["lawyer@example.in"], subject: "Invitation: Strategy conference", received_at: new Date().toISOString(),
      body_preview: "Calendar invitation for 2099-06-15 at 10:30 AM. Venue: Court &amp; Chamber 4. Bring the client&#39;s file now.",
      attachments: [],
    },
  }), "Local email import prerequisite");
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
  expect(candidate.source_preview).toContain("client's file");
  expect(candidate.source_preview).not.toMatch(/&#39;|&amp;/);
  const preview = panel.getByText(/Bring the client's file now\./);
  await preview.scrollIntoViewIfNeeded();
  await expectOnScreen(preview, "The candidate preview shows decoded text");
  await expect(panel).not.toContainText("&#39;");
  await expect(panel).not.toContainText("&amp;");
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, "b4-adj-23-calendar-copy", { candidate_id: candidate.id });
}

test("[local-only] B4-ADJ-23 calendar-copy candidates show decoded email text", async ({ page, request, baseURL }, info) => {
  await calendarCopyJourney(page, request, baseURL, info, false);
});

test("[local-only] B4-ADJ-23 [mobile] calendar-copy candidate text at phone width", async ({ page, request, baseURL }, info) => {
  await calendarCopyJourney(page, request, baseURL, info, true);
});
