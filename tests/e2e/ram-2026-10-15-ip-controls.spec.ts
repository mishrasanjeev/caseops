/** Batch 2 BUG-001..007: local governed fixtures; persistent test-legal only in production. */
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { request as playwrightRequest, type APIRequestContext, type APIResponse, type Locator, type Page } from "@playwright/test";
import type { IpDeadlineWorkspace } from "../../apps/web/lib/api/endpoints";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv, repoRoot } from "./support/env";
import { createIp15ManualTrademark, prepareIp15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ mode: "default", retries: 0 });

async function json(response: Pick<APIResponse, "status" | "json">, status = 200) {
  expect(response.status(), "IP15 response rejected; private response content intentionally omitted.").toBe(status);
  return response.json();
}

async function prepare(page: Page, api: APIRequestContext, baseURL: string | undefined, width: number) {
  const workspace = await prepareIp15Workspace(page, api, baseURL, width);
  const created = await createIp15ManualTrademark(workspace, api);
  const docketId = created.docket.id;
  await json(await api.post(`${workspace.api.origin}/api/ip/dockets/${docketId}/proceedings`, { headers: workspace.headers, data: {
    application_id: created.application.id, proceeding_kind: "opposition", side: "applicant", office: "IP India",
    jurisdiction: "IN", stage: "draft", origin_kind: "manual_intake", source_pending_identifier_allocation: true,
  } }), 201);
  if (!workspace.local) return { ...workspace, docketId, legal: null, reviewerId: "" };
  const password = `Synthetic!${randomUUID()}`;
  const members: Array<{ id: string; email: string }> = [];
  for (const label of ["legal", "reviewer"]) {
    const email = `${label}-${workspace.run}@example.com`;
    const member = await json(await api.post(`${workspace.api.origin}/api/companies/current/users`, { headers: workspace.headers,
      data: { full_name: `Synthetic ${label}`, email, password, role: "member" } }));
    members.push({ id: member.membership_id, email });
  }
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const relative = path.relative(path.join(repoRoot, "apps/api/.venv"), path.resolve(python));
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("IP15 roles require candidate-owned Python.");
  const script = [
    "import os,json",
    "from pathlib import Path",
    "from sqlalchemy.engine import make_url",
    "url=make_url(os.environ['CASEOPS_DATABASE_URL'])",
    "assert not url.query",
    "assert (url.drivername=='postgresql+psycopg' and url.host in {'localhost','127.0.0.1','::1'} and url.database) or (url.drivername=='sqlite+pysqlite' and Path(url.database).is_absolute() and Path(url.database).resolve().is_relative_to(Path.cwd().resolve()))",
    "from caseops_api.db.models import Company,CompanyMembership",
    "from caseops_api.db.session import get_session_factory",
    "with get_session_factory()() as session:",
    "    company=session.get(Company,os.environ['IP15_COMPANY_ID'])",
    "    assert company and company.slug==os.environ['IP15_SLUG'] and company.slug.startswith('ip15-')",
    "    for member_id in json.loads(os.environ['IP15_MEMBERS']):",
    "        member=session.get(CompanyMembership,member_id)",
    "        assert member and member.company_id==company.id and member.is_active and member.role=='member'",
    "        member.role='admin'",
    "    session.commit()",
  ].join("\n");
  const promoted = spawnSync(python, ["-c", script], { cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL,
      IP15_COMPANY_ID: workspace.actor.company.id, IP15_SLUG: workspace.actor.company.slug,
      IP15_MEMBERS: JSON.stringify(members.map(member => member.id)), PYTHONPATH: path.join(repoRoot, "apps/api/src") } });
  expect(promoted.status, "Isolated fixture role setup must succeed; process output omitted.").toBe(0);
  const legal = await playwrightRequest.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  try {
    await json(await legal.post(`${workspace.api.origin}/api/auth/login`, {
      data: { company_slug: workspace.actor.company.slug, email: members[0].email, password },
    }));
    await workspace.release();
    return { ...workspace, docketId, legal, reviewerId: members[1].id };
  } catch (error) {
    await legal.dispose();
    throw error;
  }
}

async function checkGeometry(page: Page, scope: Locator) {
  await expect(scope).toBeVisible();
  expect(await scope.locator("input, select, textarea, button").count()).toBeGreaterThan(0);
  const issues = await scope.locator("input:not([type=checkbox]), select, textarea, button").evaluateAll(elements => elements.flatMap(element => {
    const box = element.getBoundingClientRect();
    if (!box.width || !box.height) return [];
    const parent = element.closest("form")?.getBoundingClientRect();
    const name = element.getAttribute("aria-label") ?? element.textContent?.trim().slice(0, 70) ?? element.tagName;
    const minimum = element.tagName === "BUTTON" ? 36 : Math.min(200, (parent?.width ?? box.width));
    return box.width < minimum || box.left < 0 || box.right > document.documentElement.clientWidth + 1
      || (parent && (box.left < parent.left - 1 || box.right > parent.right + 1))
      || element.scrollWidth > element.clientWidth + 1 ? [name] : [];
  }));
  expect(issues, "Every control must have useful width, complete content and stay in its form.").toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
}

async function assertCurrentSelectorOptions(scope: Locator, data: IpDeadlineWorkspace) {
  await expect(scope.locator("label label")).toHaveCount(0);
  const ruleIds = data.eligible_rule_version_ids;
  expect(Array.isArray(ruleIds), "Workspace must return server-owned rule eligibility.").toBe(true);
  expect(new Set(ruleIds).size).toBe(ruleIds.length);
  for (const id of ruleIds) {
    expect(data.rules.find(row => row.id === id)).toMatchObject({ status: "active", rule_kind: "deadline" });
  }
  const calendarIds = data.calendars.filter(row => row.status === "active").map(row => row.id);
  for (const [label, expectedIds, placeholder] of [
    ["Active rule version", ruleIds, "No eligible active deadline rule"],
    ["Active working calendar", calendarIds, "No active working calendar"],
  ] as const) {
    const select = scope.getByRole("combobox", { name: label, exact: true });
    await expect(select).toHaveCount(1);
    await expect(select).toBeVisible();
    const optionIds = () => select.locator("option").evaluateAll(options =>
      options.map(option => (option as HTMLOptionElement).value).filter(Boolean));
    await expect.poll(async () => (await optionIds()).sort(), {
      message: `${label} must exactly match the current authorized source response.`,
    }).toEqual([...expectedIds].sort());
    const actualIds = await optionIds();
    if (!expectedIds.length) {
      await expect(select).toBeDisabled();
      await expect(select.getByRole("option", { name: placeholder, exact: true })).toHaveCount(1);
      await expect(select.locator("option")).toHaveCount(1);
    } else {
      await expect(select).toBeEnabled();
      await select.focus();
      await expect(select).toBeFocused();
      await select.press("Home");
      await select.press("Enter");
      await expect(select).toHaveValue(actualIds[0]);
      if (actualIds.length > 1) {
        await select.press("End");
        await select.press("Enter");
        await expect(select).toHaveValue(actualIds[actualIds.length - 1]);
      }
    }
  }
  if (!ruleIds.length || !calendarIds.length) {
    await expect(scope.getByText("Independent approval is required before a working calendar or deadline rule can be used. Company policy must select the active rule.", { exact: true })).toBeVisible();
    await expect(scope.getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
  }
  return { eligible_rule_ids: ruleIds, active_calendar_ids: calendarIds };
}

for (const width of [393, 768, 1024, 1280, 1536]) {
  test(`IP15 BUG-001..007 governed controls and readable forms at ${width}px`, async ({ page, request, baseURL }, testInfo) => {
    const fixture = await prepare(page, request, baseURL, width);
    try {
      const schedule = `${fixture.web.origin}/app/ip?docket=${fixture.docketId}&view=schedule`;
      let finishRead: () => void = () => {};
      const readGate = new Promise<void>(resolve => { finishRead = resolve; });
      const workspacePath = `**/dockets/${fixture.docketId}/deadline-workspace`;
      const failedRead = async (route: import("@playwright/test").Route) => {
        await readGate;
        await route.fulfill({ status: 503, contentType: "application/json",
          body: JSON.stringify({ detail: "Synthetic IP15 workspace read unavailable" }) });
      };
      await page.route(workspacePath, failedRead);
      const workspace = page.getByTestId("ip-deadline-workspace");
      try {
        await page.goto(schedule);
        await expect(workspace.getByRole("option", { name: "Loading working calendars…", exact: true })).toHaveCount(1);
        await expect(workspace.getByRole("combobox", { name: "Active working calendar", exact: true })).toBeDisabled();
        finishRead();
        await expect(workspace.getByRole("button", { name: "Retry deadline workspace" })).toBeVisible();
        await expect(workspace.getByRole("option", { name: "Working calendars unavailable", exact: true })).toHaveCount(1);
      } finally {
        finishRead();
        await page.unroute(workspacePath, failedRead);
      }
      const retriedWorkspace = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/ip/dockets/${fixture.docketId}/deadline-workspace`
        && response.request().method() === "GET");
      await workspace.getByRole("button", { name: "Retry deadline workspace" }).click();
      const currentWorkspace: IpDeadlineWorkspace = await json(await retriedWorkspace);
      expect(currentWorkspace.docket_id).toBe(fixture.docketId);
      await expect(workspace.getByRole("button", { name: "Retry deadline workspace" })).toHaveCount(0);
      const observedOptions = await assertCurrentSelectorOptions(workspace, currentWorkspace);
      if (fixture.local) {
        await expect(workspace.getByRole("combobox", { name: "Active working calendar", exact: true })).toBeDisabled();
        await expect(workspace.getByRole("option", { name: "No active working calendar", exact: true })).toHaveCount(1);
        await expect(workspace.getByRole("combobox", { name: "Active rule version", exact: true })).toBeDisabled();
        await expect(workspace.getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
      }
      await checkGeometry(page, workspace);
      const hearingFields = page.getByTestId("ip-hearing-workflow");
      for (const label of ["Hearing date", "Time precision", "IANA timezone", "Forum", "Purpose", "Mode",
        "Location", "Virtual hearing link", "Source", "Reminder offsets (hours)"]) {
        const control = label === "Time precision" || label === "Mode"
          ? hearingFields.getByRole("combobox", { name: label, exact: true })
          : hearingFields.getByLabel(label, { exact: true });
        await expect(control).toBeVisible();
      }
      await checkGeometry(page, hearingFields);
      await checkGeometry(page, page.getByTestId("ip-deadline-governance"));

      const hearing = page.getByTestId("ip-hearing-workflow");
      const purpose = `Synthetic IP15 hearing ${fixture.run}`;
      await hearing.getByLabel("Hearing date", { exact: true }).fill("2099-12-20");
      await hearing.getByRole("combobox", { name: "Time precision", exact: true }).selectOption("exact");
      await hearing.getByLabel("Exact local time").fill("10:30");
      await hearing.getByLabel("IANA timezone").fill(fixture.timezone);
      await hearing.getByLabel("Purpose", { exact: true }).fill(purpose);
      await hearing.getByLabel("Email", { exact: true }).uncheck();
      await hearing.getByLabel("In app", { exact: true }).check();
      await hearing.getByRole("button", { name: "Preview recipients and policy" }).click();
      await expect(hearing.getByTestId("ip-hearing-preview")).toContainText("Exact time 10:30");
      const hearingResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/hearings"
        && response.request().method() === "POST");
      await hearing.getByRole("button", { name: "Confirm hearing and reminders" }).click();
      const savedHearing = await json(await hearingResponse, 201);
      expect(savedHearing).toMatchObject({ hearing_on: "2099-12-20", hearing_time: "10:30:00",
        timezone: fixture.timezone, time_status: "exact", purpose });
      await page.reload();
      const persistedHearing = page.getByTestId(`ip-hearing-${savedHearing.id}`);
      await expect(persistedHearing).toContainText(`2099-12-20 · 10:30:00 · ${fixture.timezone}`);
      const listed = await json(await request.get(`${fixture.api.origin}/api/ip/hearings?docket_id=${fixture.docketId}`, {
        headers: fixture.headers,
      }));
      expect(listed.hearings.find((row: { id: string }) => row.id === savedHearing.id)).toMatchObject({
        hearing_on: "2099-12-20", hearing_time: "10:30:00", timezone: fixture.timezone, purpose,
      });
      await checkGeometry(page, hearing);

      if (fixture.local && fixture.legal) {
      const calendar = await json(await request.post(`${fixture.api.origin}/api/ip/working-calendars`, { headers: fixture.headers, data: {
        key: "ip15-calendar", name: "Synthetic reviewed working calendar", jurisdiction: "IN", office: "IP India",
        timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [], exceptional_working_days: [],
        source_priority: ["official_gazette"], source_reference: "fixture:ip15-calendar", source_hash: "a".repeat(64), effective_from: "2026-01-01",
      } }), 201);
      await json(await fixture.legal.post(`${fixture.api.origin}/api/ip/working-calendars/${calendar.id}/activate`, {
        data: { reason: "Independent review of the isolated synthetic calendar.", conflict_reviewed: true },
      }));
      const definition = { deadline_kind: "legal_deadline", trigger_kind: "examination_report_received", duration_value: 1,
        duration_unit: "days", calendar_method: "business_days", direction: "after", include_base_date: false,
        next_working_day: true, extension_days: 0, rule_citation: "Synthetic IP15 fixture, not legal advice" };
      const rule = await json(await request.post(`${fixture.api.origin}/api/ip/deadline-rules`, { headers: fixture.headers, data: {
        key: "ip15-rule", rule_kind: "deadline", jurisdiction: "IN", office: "IP India", right_kind: "trademark",
        proceeding_kind: "application", role: "applicant", stage: "examination", source_record_id: "fixture-ip15-source",
        source_hash: "b".repeat(64), source_reference: "fixture:ip15-rule", effective_from: "2026-01-01",
        engine_compatibility: "caseops-ip-deadline-v1", definition,
        fixtures: [{ id: "ip15-one-business-day", fixture_kind: "boundary", expected_state: "candidate", expected_result_on: "2026-10-16",
          evidence_reference: "fixture:ip15-source", calculation: { ...definition, base_date: "2026-10-15", base_date_certainty: "certain",
            rule_version_id: "fixture-ip15-rule", source_version: "fixture-ip15-source", engine_version: "caseops-ip-deadline-v1",
            calendar: { calendar_version_id: calendar.id, timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [],
              exceptional_working_days: [], source_reference: calendar.source_reference, source_hash: calendar.source_hash } } }],
      } }), 201);
      await json(await fixture.legal.post(`${fixture.api.origin}/api/ip/deadline-rules/${rule.id}/activate`, {
        data: { reviewer_membership_id: fixture.reviewerId, select_for_company: true, auto_confirm_eligible: false },
      }));
      const approvedRead = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/ip/dockets/${fixture.docketId}/deadline-workspace`
        && response.request().method() === "GET");
      await page.reload();
      const approved: IpDeadlineWorkspace = await json(await approvedRead);
      expect(approved.docket_id).toBe(fixture.docketId);
      expect(approved.eligible_rule_version_ids).toEqual([rule.id]);
      expect(approved.calendars.filter(row => row.status === "active").map(row => row.id)).toEqual([calendar.id]);
      await assertCurrentSelectorOptions(workspace, approved);
      const ruleSelect = workspace.getByRole("combobox", { name: "Active rule version", exact: true });
      const calendarSelect = workspace.getByRole("combobox", { name: "Active working calendar", exact: true });
      await expect(ruleSelect).toBeEnabled();
      await ruleSelect.selectOption(rule.id);
      await calendarSelect.focus();
      await expect(calendarSelect).toBeFocused();
      await calendarSelect.press("Home");
      await calendarSelect.press("Enter");
      await expect(calendarSelect).toHaveValue(calendar.id);
      await expect(workspace.getByText("Synthetic reviewed working calendar · version 1 · Asia/Kolkata", { exact: true })).toBeVisible();
      await workspace.getByLabel("Trigger / base date").fill("2026-10-15");
      const proposal = page.waitForResponse(response => response.url().endsWith(`/dockets/${fixture.docketId}/deadlines`) && response.request().method() === "POST");
      await workspace.getByRole("button", { name: "Calculate deadline proposal" }).click();
      const saved = await json(await proposal, 201);
      expect(saved).toMatchObject({ rule_version_id: rule.id, calendar_version_id: calendar.id, result_on: "2026-10-16", state: "candidate" });
      await checkGeometry(page, workspace);
      const persistedRead = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/ip/dockets/${fixture.docketId}/deadline-workspace`
        && response.request().method() === "GET");
      await page.reload();
      const persisted: IpDeadlineWorkspace = await json(await persistedRead);
      expect(persisted.docket_id).toBe(fixture.docketId);
      expect(persisted.deadlines.find(row => row.id === saved.id)).toMatchObject({
        rule_version_id: rule.id, calendar_version_id: calendar.id, result_on: "2026-10-16", state: "candidate",
      });
      await expect(workspace.getByTestId(`ip-legal-deadline-${saved.id}`)).toContainText("2026-10-16");
      }
      await page.getByRole("tab", { name: "Proceedings", exact: true }).click();
      const opposition = page.getByTestId("ip-opposition-workspace");
      await expect(opposition.getByRole("heading", { name: "Trademark opposition", exact: true })).toBeVisible();
      await expect(opposition.getByRole("button", { name: "Apply stage" })).toBeDisabled();
      await checkGeometry(page, opposition);
      await testInfo.attach("ip15-control-coverage", { contentType: "application/json", body: Buffer.from(JSON.stringify({
        width, local: fixture.local, source: "API-backed manual trademark", governance_positive: fixture.local,
        observed_options_after_retry: observedOptions,
        production_limitation: fixture.local ? null : "Read-only existing rule/calendar eligibility and keyboard selection; no synthetic production governance publication or deadline calculation.",
      })) });
    } finally {
      try { await fixture.release(); } finally { await fixture.legal?.dispose(); }
    }
  });
}
