/** Batch 2 BUG-001..007: local governed fixtures; persistent test-legal only in production. */
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { request as playwrightRequest, type APIRequestContext, type APIResponse, type Locator, type Page } from "@playwright/test";
import type { IpCoreRecords, IpDeadlineWorkspace } from "../../apps/web/lib/api/endpoints";

import { expect, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv, repoRoot } from "./support/env";
import { createIp15ManualTrademark, prepareIp15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("IP15 requires a configured baseURL.");
  await use(localTransportHeaders(baseURL));
}, storageState: { cookies: [], origins: [] },
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
  const proceeding = await json(await api.post(`${workspace.api.origin}/api/ip/dockets/${docketId}/proceedings`, { headers: workspace.headers, data: {
    application_id: created.application.id, proceeding_kind: "opposition", side: "applicant", office: "IP India",
    jurisdiction: "IN", stage: "draft", origin_kind: "manual_intake", source_pending_identifier_allocation: true,
  } }), 201);
  expect(typeof proceeding.id, "The created proceeding must return its canonical identity.").toBe("string");
  const recordIds = { applicationId: created.application.id, proceedingId: proceeding.id as string };
  if (!workspace.local) return { ...workspace, docketId, ...recordIds, legal: null, reviewerId: "" };
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
  const actorIds = [workspace.actor.membership.id, ...members.map(member => member.id)];
  if (actorIds.some(id => typeof id !== "string" || !id) || new Set(actorIds).size !== 3) {
    throw new Error("IP15 requires three distinct local governance actors.");
  }
  const matchesLegalIdentity = (actor: {
    company?: { id?: string; slug?: string; is_active?: boolean };
    membership?: { id?: string; role?: string; is_active?: boolean };
  } | null | undefined) => actor?.company?.id === workspace.actor.company.id
    && actor.company.slug === workspace.actor.company.slug && actor.company.is_active === true
    && actor.membership?.id === members[0].id && actor.membership.role === "admin"
    && actor.membership.is_active === true;
  const authentication = await playwrightRequest.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  let legalToken: string;
  try {
    const actor = await json(await authentication.post(`${workspace.api.origin}/api/auth/login`, {
      data: { company_slug: workspace.actor.company.slug, email: members[0].email, password },
    }));
    if (!matchesLegalIdentity(actor) || actor.token_type !== "bearer"
      || typeof actor.access_token !== "string" || !actor.access_token.trim() || /\s/.test(actor.access_token)) {
      throw new Error("IP15 legal login identity or token did not match the intended active admin.");
    }
    legalToken = actor.access_token;
  } finally {
    await authentication.dispose();
  }
  const legal = await playwrightRequest.newContext({ extraHTTPHeaders: {
    ...noPaidProviderHeaders, Authorization: `Bearer ${legalToken}`,
  } });
  try {
    const current = await json(await legal.get(`${workspace.api.origin}/api/auth/me`));
    if (!matchesLegalIdentity(current) || !Array.isArray(current.capabilities)
      || !current.capabilities.includes("ip:rules_activate")) {
      throw new Error("IP15 current legal identity or activation capability did not match the intended actor.");
    }
    await workspace.release();
    return { ...workspace, docketId, ...recordIds, legal, reviewerId: members[1].id };
  } catch (error) {
    await legal.dispose();
    throw error;
  }
}

type GeometryStage = "synthetic-guard" | "deadline-initial" | "hearing-initial" | "governance-initial"
  | "governance-selected-identity" | "hearing-reloaded" | "hearing-rescheduled-reloaded"
  | "deadline-created-long-values" | "opposition";

async function checkGeometry(page: Page, scope: Locator, requiredSourceValues: readonly string[] = [], stage: GeometryStage = "synthetic-guard") {
  await expect(scope).toBeVisible();
  expect(await scope.locator("input, select, textarea, button").count()).toBeGreaterThan(0);
  const measurements = await scope.evaluate((root, requiredValues) => {
    const elements = Array.from(root.querySelectorAll<HTMLElement>("input:not([type=checkbox]), select, textarea, button"));
    const rectangle = (element: Element) => {
      const box = element.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height };
    };
    const normalize = (value: string | null) => value?.replace(/\s+/g, " ").trim() ?? "";
    return elements.flatMap((element, index) => {
      const box = rectangle(element);
      if (!box.width || !box.height) return [];
      const parent = element.closest("form");
      const parentBox = parent ? rectangle(parent) : null;
      const ownerBox = parentBox ?? rectangle(root);
      const minimum = element.tagName === "BUTTON" ? 36 : Math.min(200, ownerBox.width);
      let selectedDetail: { readable: boolean; currentIdentity: boolean; completeLabel: boolean; width: number; height: number } | null = null;
      if (element instanceof HTMLSelectElement && element.value) {
        const label = normalize(element.selectedOptions[0]?.label ?? "");
        for (const id of (element.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean)) {
          const targets = document.querySelectorAll<HTMLElement>(`#${CSS.escape(id)}`);
          if (targets.length !== 1) continue;
          const detail = targets[0];
          if (!root.contains(detail)) continue;
          const bounds = rectangle(detail);
          const style = getComputedStyle(detail);
          const currentIdentity = detail.dataset.selectedOptionValue === element.value;
          const completeLabel = Boolean(label) && normalize(detail.textContent) === label;
          let visible = detail.isConnected && bounds.width > 0 && bounds.height > 0;
          for (let ancestor: Element | null = detail; ancestor; ancestor = ancestor.parentElement) {
            const ancestorStyle = getComputedStyle(ancestor);
            if (ancestorStyle.display === "none" || ancestorStyle.visibility !== "visible" || Number(ancestorStyle.opacity) === 0) visible = false;
            const ancestorBox = rectangle(ancestor);
            const clipLeft = ancestorBox.left + ancestor.clientLeft;
            const clipTop = ancestorBox.top + ancestor.clientTop;
            if (["hidden", "clip"].includes(ancestorStyle.overflowX)
              && (bounds.left < clipLeft - 1 || bounds.right > clipLeft + ancestor.clientWidth + 1)) visible = false;
            if (["hidden", "clip"].includes(ancestorStyle.overflowY)
              && (bounds.top < clipTop - 1 || bounds.bottom > clipTop + ancestor.clientHeight + 1)) visible = false;
            if (ancestorStyle.clipPath !== "none" || ancestorStyle.clip !== "auto"
              || !["", "none", "0"].includes(ancestorStyle.webkitLineClamp) || ancestorStyle.contentVisibility === "hidden") visible = false;
          }
          const unclipped = !["hidden", "clip"].includes(style.overflowX)
            && !["hidden", "clip"].includes(style.overflowY) && style.textOverflow !== "ellipsis"
            && ["", "none", "0"].includes(style.webkitLineClamp) && style.clipPath === "none"
            && style.clip === "auto" && style.whiteSpace !== "nowrap"
            && detail.scrollWidth <= detail.clientWidth + 1 && detail.scrollHeight <= detail.clientHeight + 1;
          const contained = bounds.left >= ownerBox.left - 1 && bounds.right <= ownerBox.right + 1
            && bounds.top >= ownerBox.top - 1 && bounds.bottom <= ownerBox.bottom + 1
            && bounds.left >= 0 && bounds.right <= document.documentElement.clientWidth + 1
            && bounds.width >= Math.min(200, ownerBox.width);
          const normalFlow = ["static", "relative"].includes(style.position);
          const overlapsControl = elements.some(control => {
            const controlBox = rectangle(control);
            return controlBox.width > 0 && controlBox.height > 0 && bounds.left < controlBox.right - 1
              && bounds.right > controlBox.left + 1 && bounds.top < controlBox.bottom - 1 && bounds.bottom > controlBox.top + 1;
          });
          const readable = currentIdentity && completeLabel && visible && unclipped && contained && normalFlow && !overlapsControl;
          selectedDetail = { readable, currentIdentity, completeLabel, width: bounds.width, height: bounds.height };
          if (readable) break;
        }
      }
      const failures = {
        usefulWidth: box.width < minimum,
        viewportLeft: box.left < 0,
        viewportRight: box.right > document.documentElement.clientWidth + 1,
        formLeft: Boolean(parentBox && box.left < parentBox.left - 1),
        formRight: Boolean(parentBox && box.right > parentBox.right + 1),
        unreadableOverflow: element.scrollWidth > element.clientWidth + 1 && !selectedDetail?.readable,
        requiredCurrentValue: element instanceof HTMLSelectElement && requiredValues.includes(element.value) && !selectedDetail?.readable,
      };
      return [{ control: `${element.tagName.toLowerCase()}${element instanceof HTMLInputElement ? `:${element.type}` : ""}[${index}]`,
        box, parentBox, minimum, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, selectedDetail, failures }];
    });
  }, requiredSourceValues);
  const issues = measurements.filter(row => Object.values(row.failures).some(Boolean));
  expect(issues, `[${stage}] Every control must have useful width, readable current value and stay in its form; numeric evidence excludes private labels.`).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  return measurements;
}

async function assertSelectedDescription(select: Locator, detail: Locator, expectedValue: string, facts: Readonly<Record<string, string>>) {
  await expect(select).toBeVisible();
  await expect(detail).toBeVisible();
  expect(await select.inputValue() === expectedValue, "The native selection must retain the current source identity.").toBe(true);
  const detailId = await detail.getAttribute("id");
  expect(Boolean(detailId) && (await select.getAttribute("aria-describedby") ?? "").split(/\s+/).includes(detailId!),
    "The current detail must be the select's actual accessible description.").toBe(true);
  expect(await detail.getAttribute("data-selected-option-value") === expectedValue, "Description identity must not be stale.").toBe(true);
  const text = (await detail.textContent() ?? "").replace(/\s+/g, " ").trim();
  const caption = (await select.locator("option:checked").textContent() ?? "").replace(/\s+/g, " ").trim();
  expect(Boolean(text) && text === caption, "The complete selected caption must be visible, not merely present in a native option.").toBe(true);
  for (const [field, fact] of Object.entries(facts)) {
    expect(typeof fact, `Source caption fact '${field}' must be supplied as text.`).toBe("string");
    if (field === "office" && !fact) continue;
    expect(Boolean(fact) && text.toLowerCase().includes(fact.toLowerCase()),
      `The current caption must retain source distinguishing fact '${field}'; private values are omitted.`).toBe(true);
  }
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
      const selectedId = await select.inputValue();
      if (label === "Active rule version") {
        const row = data.rules.find(rule => rule.id === selectedId)!;
        await assertSelectedDescription(select, scope.locator("#ip-active-rule-detail"), selectedId,
          { key: row.key, version: `version ${row.version}`, jurisdiction: row.jurisdiction, office: row.office ?? "", status: row.status });
      } else {
        const row = data.calendars.find(calendar => calendar.id === selectedId)!;
        await assertSelectedDescription(select, scope.locator("#ip-active-calendar-detail"), selectedId,
          { name: row.name, version: `version ${row.version}`, jurisdiction: row.jurisdiction, office: row.office ?? "", timezone: row.timezone, status: row.status });
      }
    }
  }
  if (!ruleIds.length || !calendarIds.length) {
    await expect(scope.getByText("Independent approval is required before a working calendar or deadline rule can be used. Company policy must select the active rule.", { exact: true })).toBeVisible();
    await expect(scope.getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
  }
  return { eligible_rule_ids: ruleIds, active_calendar_ids: calendarIds };
}

for (const scenario of ["current", "missing-link", "stale-id-same-caption", "wrong-caption", "hidden", "transparent",
  "clipped", "ellipsis", "absolute", "narrow-outside-form", "outside-form", "outside-viewport", "empty-selection", "button-overflow",
  "required-no-overflow", "missing-required-no-overflow", "ancestor-clipped", "outside-owner-vertical"] as const) {
  test(`IP15 geometry guard ${scenario}`, async ({ page }) => {
    let requests = 0;
    page.on("request", () => { requests += 1; });
    await page.setViewportSize({ width: 393, height: 900 });
    const caption = "Synthetic selected colleague with a long unbroken identity legal-operations-reviewer@example.com · active";
    const privatePurpose = "Synthetic private hearing purpose that must not enter numeric evidence";
    await page.setContent(`<form data-testid="geometry-guard" style="display:grid;gap:8px;width:280px;max-width:100%;margin:0">
      <select id="guard-choice" aria-label="${privatePurpose}" aria-describedby="guard-detail" style="box-sizing:border-box;width:100%;height:40px;min-width:0">
        <option value="">Select a colleague</option><option value="source-a" selected>${caption}</option>
      </select><p id="guard-detail" data-selected-option-value="source-a"
        style="margin:0;min-width:0;white-space:normal;overflow-wrap:anywhere;font:14px/20px sans-serif">${caption}</p></form>`);
    await page.evaluate(kind => {
      const select = document.querySelector<HTMLSelectElement>("#guard-choice")!;
      const detail = document.querySelector<HTMLElement>("#guard-detail")!;
      // Exercise the exception deterministically; native select scroll extents differ by Chromium/platform.
      Object.defineProperty(select, "scrollWidth", { configurable: true, get: () => select.clientWidth + (kind.endsWith("no-overflow") ? 0 : 140) });
      if (kind === "missing-link" || kind === "missing-required-no-overflow") select.removeAttribute("aria-describedby");
      if (kind === "stale-id-same-caption") detail.dataset.selectedOptionValue = "source-b";
      if (kind === "wrong-caption") detail.textContent = "A different selected colleague";
      if (kind === "hidden") detail.hidden = true;
      if (kind === "transparent") detail.style.opacity = "0";
      if (kind === "clipped") { detail.style.height = "5px"; detail.style.overflow = "hidden"; }
      if (kind === "ancestor-clipped") {
        const wrapper = document.createElement("div");
        wrapper.style.cssText = "height:5px;overflow:hidden";
        detail.replaceWith(wrapper);
        wrapper.append(detail);
      }
      if (kind === "ellipsis") detail.style.textOverflow = "ellipsis";
      if (kind === "absolute") detail.style.position = "absolute";
      if (kind === "narrow-outside-form") {
        const form = select.closest("form")!;
        const root = document.createElement("div");
        root.dataset.testid = "geometry-guard";
        root.style.cssText = form.style.cssText;
        root.append(...form.childNodes);
        form.replaceWith(root);
        select.style.width = "24px";
      }
      if (kind === "outside-form") select.style.marginLeft = "20px";
      if (kind === "outside-viewport") select.style.transform = "translateX(320px)";
      if (kind === "outside-owner-vertical") detail.style.transform = "translateY(400px)";
      if (kind === "empty-selection") select.value = "";
      if (kind === "button-overflow") {
        const button = document.createElement("button");
        button.textContent = "Synthetic action";
        button.style.cssText = "width:240px;height:40px";
        Object.defineProperty(button, "scrollWidth", { get: () => button.clientWidth + 100 });
        select.parentElement!.append(button);
      }
    }, scenario);
    const required = scenario.endsWith("no-overflow") ? ["source-a"] : [];
    const result = checkGeometry(page, page.getByTestId("geometry-guard"), required);
    if (scenario === "current" || scenario === "required-no-overflow") {
      const measurements = await result;
      if (scenario === "current") expect(measurements[0].scrollWidth).toBeGreaterThan(measurements[0].clientWidth);
      expect(measurements[0].selectedDetail?.readable).toBe(true);
      expect(JSON.stringify(measurements)).not.toContain(privatePurpose);
      expect(JSON.stringify(measurements)).not.toContain(caption);
      if (scenario === "current") {
        const createdSnapshot = { status: "draft" };
        const activatedSnapshot = { status: "active" };
        const select = page.locator("#guard-choice");
        const detail = page.locator("#guard-detail");
        await expect(assertSelectedDescription(select, detail, "source-a", createdSnapshot)).rejects.toThrow(/fact 'status'/);
        await assertSelectedDescription(select, detail, "source-a", activatedSnapshot);
      }
    } else {
      await expect(result).rejects.toThrow(/Every control must have useful width/);
    }
    expect(requests, "Geometry guard fixtures must not call CaseOps or external providers.").toBe(0);
  });
}

for (const width of [393, 639, 640, 641, 767, 768, 769, 1023, 1024, 1025, 1279, 1280, 1281, 1535, 1536, 1537]) {
  test(`IP15 BUG-001..007 governed controls and readable forms at ${width}px`, async ({ page, request, baseURL }, testInfo) => {
    const fixture = await prepare(page, request, baseURL, width);
    const geometry: Array<{ stage: GeometryStage; measurements: Awaited<ReturnType<typeof checkGeometry>> }> = [];
    const captureGeometry = async (stage: GeometryStage, scope: Locator, requiredSources: readonly string[] = []) => {
      geometry.push({ stage, measurements: await checkGeometry(page, scope, requiredSources, stage) });
    };
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
      await captureGeometry("deadline-initial", workspace, [...currentWorkspace.eligible_rule_version_ids,
        ...currentWorkspace.calendars.filter(row => row.status === "active").map(row => row.id)]);
      const hearingFields = page.getByTestId("ip-hearing-workflow");
      for (const label of ["Hearing date", "Time precision", "IANA timezone", "Forum", "Purpose", "Mode",
        "Location", "Virtual hearing link", "Source", "Reminder offsets (hours)"]) {
        const control = label === "Time precision" || label === "Mode"
          ? hearingFields.getByRole("combobox", { name: label, exact: true })
          : hearingFields.getByLabel(label, { exact: true });
        await expect(control).toBeVisible();
      }
      await captureGeometry("hearing-initial", hearingFields);
      const governance = page.getByTestId("ip-deadline-governance");
      await captureGeometry("governance-initial", governance);
      // Reviewers are chosen per candidate rule from the server's eligible list
      // (2026-10-31 BUG-006); with no candidate there is no reviewer picker to fill.
      await expect(governance.getByRole("combobox", { name: "Independent fixture reviewer", exact: true })).toHaveCount(0);

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
      await captureGeometry("hearing-reloaded", hearing);
      const rescheduleDate = persistedHearing.getByLabel(`Reschedule ${purpose}`, { exact: true });
      await expect(rescheduleDate).toHaveValue("2099-12-20");
      await rescheduleDate.fill("2099-12-21");
      const rescheduleResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/ip/hearings/${savedHearing.id}` && response.request().method() === "PATCH");
      await persistedHearing.getByRole("button", { name: "Reschedule", exact: true }).click();
      expect(await json(await rescheduleResponse)).toMatchObject({ id: savedHearing.id, hearing_on: "2099-12-21",
        hearing_time: "10:30:00", time_status: "exact", timezone: fixture.timezone, purpose, status: "scheduled" });
      await expect(persistedHearing).toContainText(`2099-12-21 · 10:30:00 · ${fixture.timezone}`);
      await page.reload();
      await expect(persistedHearing).toContainText(`2099-12-21 · 10:30:00 · ${fixture.timezone}`);
      await expect(persistedHearing.getByLabel(`Reschedule ${purpose}`, { exact: true })).toHaveValue("2099-12-21");
      const rescheduled = await json(await request.get(`${fixture.api.origin}/api/ip/hearings?docket_id=${fixture.docketId}`, {
        headers: fixture.headers,
      }));
      expect(rescheduled.hearings.find((row: { id: string }) => row.id === savedHearing.id)).toMatchObject({
        hearing_on: "2099-12-21", hearing_time: "10:30:00", time_status: "exact", timezone: fixture.timezone, purpose,
      });
      await captureGeometry("hearing-rescheduled-reloaded", hearing);

      if (fixture.local && fixture.legal) {
      const calendar = await json(await request.post(`${fixture.api.origin}/api/ip/working-calendars`, { headers: fixture.headers, data: {
        key: "ip15-calendar", name: "Synthetic reviewed working calendar for independently checked domestic trademark response and renewal operations", jurisdiction: "IN", office: "IP India",
        timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [], exceptional_working_days: [],
        source_priority: ["official_gazette"], source_reference: "fixture:ip15-calendar", source_hash: "a".repeat(64), effective_from: "2026-01-01",
      } }), 201);
      const activeCalendar = await json(await fixture.legal.post(`${fixture.api.origin}/api/ip/working-calendars/${calendar.id}/activate`, {
        data: { reason: "Independent review of the isolated synthetic calendar.", conflict_reviewed: true },
      }));
      expect(activeCalendar).toMatchObject({ id: calendar.id, status: "active" });
      const definition = { deadline_kind: "legal_deadline", trigger_kind: "examination_report_received", duration_value: 1,
        duration_unit: "days", calendar_method: "business_days", direction: "after", include_base_date: false,
        next_working_day: true, extension_days: 0, rule_citation: "Synthetic IP15 fixture, not legal advice" };
      const rule = await json(await request.post(`${fixture.api.origin}/api/ip/deadline-rules`, { headers: fixture.headers, data: {
        key: `ip15-response-${"reviewed-".repeat(10)}source`, rule_kind: "deadline", jurisdiction: "IN", office: "IP India", right_kind: "trademark",
        proceeding_kind: "application", role: "applicant", stage: "examination", source_record_id: "fixture-ip15-source",
        source_hash: "b".repeat(64), source_reference: "fixture:ip15-rule", effective_from: "2026-01-01",
        engine_compatibility: "caseops-ip-deadline-v1", definition,
        fixtures: [{ id: "ip15-one-business-day", fixture_kind: "boundary", expected_state: "candidate", expected_result_on: "2026-10-16",
          evidence_reference: "fixture:ip15-source", calculation: { ...definition, base_date: "2026-10-15", base_date_certainty: "certain",
            rule_version_id: "fixture-ip15-rule", source_version: "fixture-ip15-source", engine_version: "caseops-ip-deadline-v1",
            calendar: { calendar_version_id: calendar.id, timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [],
              exceptional_working_days: [], source_reference: calendar.source_reference, source_hash: calendar.source_hash } } }],
      } }), 201);
      const activeRule = await json(await fixture.legal.post(`${fixture.api.origin}/api/ip/deadline-rules/${rule.id}/activate`, {
        data: { reviewer_membership_id: fixture.reviewerId, select_for_company: true, auto_confirm_eligible: false },
      }));
      expect(activeRule).toMatchObject({ id: rule.id, status: "active" });
      await page.reload();
      const approved: IpDeadlineWorkspace = await json(await request.get(
        `${fixture.api.origin}/api/ip/dockets/${fixture.docketId}/deadline-workspace`, { headers: fixture.headers },
      ));
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
      await assertSelectedDescription(calendarSelect, workspace.locator("#ip-active-calendar-detail"), calendar.id,
        { name: calendar.name, version: `version ${calendar.version}`, jurisdiction: calendar.jurisdiction,
          office: calendar.office ?? "", timezone: calendar.timezone, status: activeCalendar.status });
      await workspace.getByLabel("Trigger / base date").fill("2026-10-15");
      const proposal = page.waitForResponse(response => response.url().endsWith(`/dockets/${fixture.docketId}/deadlines`) && response.request().method() === "POST");
      await workspace.getByRole("button", { name: "Calculate deadline proposal" }).click();
      const saved = await json(await proposal, 201);
      expect(saved).toMatchObject({ rule_version_id: rule.id, calendar_version_id: calendar.id, result_on: "2026-10-16", state: "candidate" });
      await expect(workspace.getByTestId(`ip-legal-deadline-${saved.id}`)).toContainText("2026-10-16");
      await captureGeometry("deadline-created-long-values", workspace, [rule.id, calendar.id, fixture.actor.membership.id]);
      await page.reload();
      const persisted: IpDeadlineWorkspace = await json(await request.get(
        `${fixture.api.origin}/api/ip/dockets/${fixture.docketId}/deadline-workspace`, { headers: fixture.headers },
      ));
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
      const core: IpCoreRecords = await json(await request.get(
        `${fixture.api.origin}/api/ip/dockets/${fixture.docketId}/core-records`, { headers: fixture.headers },
      ));
      const application = core.applications.find(row => row.id === fixture.applicationId);
      const proceeding = core.proceedings.find(row => row.id === fixture.proceedingId);
      expect(application, "The current API response must retain the created application.").toBeDefined();
      expect(proceeding, "The current API response must retain the created opposition.").toBeDefined();
      const applicationSelect = opposition.getByRole("combobox", { name: "Trademark application", exact: true });
      const proceedingSelect = opposition.getByRole("combobox", { name: "Opposition proceeding", exact: true });
      for (const [select, ids] of [
        [applicationSelect, core.applications.map(row => row.id)],
        [proceedingSelect, core.proceedings.filter(row => row.proceeding_kind === "opposition").map(row => row.id)],
      ] as const) {
        await expect.poll(() => select.locator("option").evaluateAll(options =>
          options.map(option => (option as HTMLOptionElement).value).filter(Boolean))).toEqual(ids);
      }
      // Native scroll metrics vary by platform; current record captions must always remain readable.
      const recordDetail = (id: string) => opposition.locator(`[data-selected-option-value=${JSON.stringify(id)}]`);
      await assertSelectedDescription(applicationSelect, recordDetail(fixture.applicationId), fixture.applicationId, {
        number: core.identifiers.find(row => row.application_id === fixture.applicationId && row.identifier_kind === "application")?.raw_value
          ?? "Application number pending", office: application!.office,
      });
      await assertSelectedDescription(proceedingSelect, recordDetail(fixture.proceedingId), fixture.proceedingId, {
        side: proceeding!.side, stage: proceeding!.stage.replaceAll("_", " "), office: proceeding!.office,
      });
      await captureGeometry("opposition", opposition, [fixture.applicationId, fixture.proceedingId]);
      await testInfo.attach("ip15-control-coverage", { contentType: "application/json", body: Buffer.from(JSON.stringify({
        width, local: fixture.local, source: "API-backed manual trademark", governance_positive: fixture.local,
        observed_options_after_retry: observedOptions,
        geometry,
        production_limitation: fixture.local ? null : "Read-only existing rule/calendar eligibility and keyboard selection; no synthetic production governance publication or deadline calculation.",
      })) });
    } finally {
      try { await fixture.release(); } finally { await fixture.legal?.dispose(); }
    }
  });
}
