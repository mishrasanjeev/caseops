/** IP15-007..022: persisted manual dates, source provenance and tracker reload. */
import type { APIRequestContext, APIResponse, Locator, Page } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { createIp15ManualTrademark, prepareIp15Workspace, type Ip15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("IP15 requires a configured baseURL.");
  await use(localTransportHeaders(baseURL));
}, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0, mode: "default" });

async function json(response: Pick<APIResponse, "status" | "json">, expected = 200) {
  expect(response.status(), "IP15 response rejected; credentials and private response are not logged.").toBe(expected);
  return response.json();
}

async function portfolioRecord(page: Page, title: string, width: number) {
  await page.getByLabel("Search marks and registry numbers").fill(title);
  await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
  const row = page.getByRole(width >= 768 ? "row" : "article").filter({ has:
    page.getByRole("button", { name: `Edit dates for ${title}`, exact: true }) });
  await expect(row).toBeVisible();
  return row;
}

async function saveDates(page: Page, row: Locator, title: string,
  changes: { application?: string; renewal?: string }, reason: string) {
  await row.getByRole("button", { name: `Edit dates for ${title}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Edit portfolio dates", exact: true });
  await expect(dialog).toBeVisible();
  if (changes.application !== undefined) await dialog.getByLabel("Application Date", { exact: true }).fill(changes.application);
  if (changes.renewal !== undefined) await dialog.getByLabel("Renewal Due Date", { exact: true }).fill(changes.renewal);
  await dialog.getByLabel("Reason for change", { exact: true }).fill(reason);
  const saved = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/portfolio-dates")
    && response.request().method() === "PATCH");
  await dialog.getByRole("button", { name: "Save dates", exact: true }).click();
  const response = await saved;
  const payload = response.request().postDataJSON();
  expect(typeof payload, "The HTTP client must serialize the request object exactly once.").toBe("object");
  const result = await json(response);
  await expect(dialog).toHaveCount(0);
  return { result, payload };
}

async function verifyReminderConfiguration(page: Page, request: APIRequestContext, workspace: Ip15Workspace,
  docketId: string) {
  const me = await json(await request.get(`${workspace.api.origin}/api/auth/me`, { headers: workspace.headers }));
  expect(Array.isArray(me.capabilities)).toBe(true);
  const canConfigure = me.capabilities.includes("ip:taxonomy_admin");
  if (workspace.local) expect(canConfigure).toBe(true);
  const readiness = await json(await request.get(`${workspace.api.origin}/api/ip/readiness`, { headers: workspace.headers }));
  const configuration = readiness.configuration_status.configuration;
  expect(configuration).not.toBeNull();
  expect(configuration.renewal_reminder_cadence_days).toBeGreaterThanOrEqual(1);
  expect(configuration.renewal_reminder_cadence_days).toBeLessThanOrEqual(31);
  expect(configuration.renewal_reminder_delivery_time).toMatch(/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/);
  await page.goto(`${workspace.web.origin}/app/ip?docket=${encodeURIComponent(docketId)}`);
  await expect(page.getByRole("heading", { name: "Trademark docket", exact: true })).toBeVisible();
  const action = page.getByRole("button", { name: "Workspace configuration", exact: true });
  if (!canConfigure) {
    await expect(action).toHaveCount(0);
    return;
  }
  await action.click();
  const card = page.getByTestId("ip-workspace-configuration");
  await expect(card).toBeVisible();
  const cadence = card.getByLabel("Renewal reminder cadence (days)", { exact: true });
  const time = card.getByLabel("Renewal reminder local time", { exact: true });
  await expect(cadence).toHaveValue(String(configuration.renewal_reminder_cadence_days));
  await expect(time).toHaveValue(configuration.renewal_reminder_delivery_time);
  await expect(card.getByLabel("IANA timezone", { exact: true })).toHaveValue(configuration.timezone);
  // Remote acceptance observes current policy only; it never changes test-legal configuration.
  if (!workspace.local) return;
  await cadence.fill("2");
  await time.fill("10:15");
  const updatedResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/workspace/configuration"
    && response.request().method() === "PUT");
  await card.getByRole("button", { name: "Save configuration", exact: true }).click();
  const updated = (await json(await updatedResponse)).configuration;
  expect(updated.version).toBe(configuration.version + 1);
  expect(updated.renewal_reminder_cadence_days).toBe(2);
  expect(updated.renewal_reminder_delivery_time).toBe("10:15");
  const unchanged = ["enabled_asset_types_json", "jurisdictions_json", "offices_json", "timezone", "holiday_calendar_key",
    "working_day_policy_json", "document_taxonomy_version", "event_catalog_version", "deadline_rule_versions_json",
    "notification_channels_json", "critical_event_policy_json", "escalation_owner_membership_id", "provider_keys_json",
    "provider_terms_version", "provider_terms_accepted_by_membership_id", "provider_terms_accepted_at"];
  for (const key of unchanged) expect(updated[key], `A reminder edit must preserve ${key}.`).toEqual(configuration[key]);
  expect(updated.workspace_enabled).toBe(false);
  expect(updated.enabled_automations_json).toEqual([]);
  await expect(page.getByRole("heading", { name: "IP workspace setup", exact: true })).toBeVisible();
  const enabledResponse = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/workspace/enable"
    && response.request().method() === "POST");
  await card.getByRole("button", { name: "Enable manual workspace", exact: true }).click();
  const enabled = (await json(await enabledResponse)).configuration;
  expect(enabled.version).toBe(updated.version);
  expect(enabled.workspace_enabled).toBe(true);
  expect(enabled.enabled_automations_json).toEqual([]);
  await expect(action).toBeVisible();
  await page.reload();
  await action.click();
  await expect(cadence).toHaveValue("2");
  await expect(time).toHaveValue("10:15");
  await expect(card.getByLabel("IANA timezone", { exact: true })).toHaveValue(configuration.timezone);
}

for (const width of [1280, 393]) {
  test(`IP15 editable portfolio dates and persisted renewal tracker at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(240_000);
    const workspace = await prepareIp15Workspace(page, request, baseURL, width);
    const { docket } = await createIp15ManualTrademark(workspace, request, "Synthetic IP15 date tracker");
    const docketPath = `${workspace.api.origin}/api/ip/dockets/${docket.id}`;
    const before = await json(await request.get(docketPath, { headers: workspace.headers }));
    expect(Number.isInteger(before.current_version)).toBe(true);
    expect(typeof before.is_active).toBe("boolean");
    expect(before.is_active).toBe(true);
    expect(before.current_particulars.parties_json.length).toBeGreaterThan(0);
    let leapYear = new Date().getUTCFullYear() + 2;
    while (new Date(Date.UTC(leapYear, 1, 29)).getUTCMonth() !== 1) leapYear++;
    const due = `${leapYear}-03-31`;
    const replacement = `${leapYear}-04-30`;
    await page.goto(`${workspace.web.origin}/app/ip/portfolio`);
    let row = await portfolioRecord(page, docket.title, width);
    if (width >= 768) {
      await expect(page.getByRole("columnheader", { name: "Application Date", exact: true })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: "Renewal Due Date", exact: true })).toBeVisible();
    } else {
      await expect(row.getByText("Application Date", { exact: true })).toBeVisible();
      await expect(row.getByText("Renewal Due Date", { exact: true })).toBeVisible();
    }
    for (const name of ["Application Date", "Renewal Due Date"]) {
      const heading = width >= 768 ? page.getByRole("columnheader", { name, exact: true })
        : row.getByText(name, { exact: true });
      const columns = page.getByRole("button", { name: "Choose portfolio columns", exact: true });
      await columns.click();
      const checkbox = page.getByRole("checkbox", { name, exact: true });
      await expect(checkbox).toBeChecked();
      await checkbox.uncheck();
      await page.keyboard.press("Escape");
      await expect(heading).toHaveCount(0);
      await columns.click();
      await expect(checkbox).not.toBeChecked();
      await checkbox.check();
      await page.keyboard.press("Escape");
      await expect(heading).toBeVisible();
    }
    expect(await row.getByText("Not set", { exact: true }).count()).toBeGreaterThanOrEqual(2);
    const first = await saveDates(page, row, docket.title, { application: "2020-01-15", renewal: due },
      "Synthetic acceptance: record independent supplied dates");
    expect(first.payload).toEqual({ expected_current_version: before.current_version,
      application_date: "2020-01-15", renewal_due_date: due,
      reason: "Synthetic acceptance: record independent supplied dates" });
    expect(first.result.source_application_on).toBe("2020-01-15");
    expect(first.result.source_renewal_due_on).toBe(due);
    expect(first.result.source_application_state).toBe("manual");
    expect(first.result.source_renewal_state).toBe("manual");
    expect(first.result.current_version).toBe(before.current_version + 1);
    expect(first.result.tracker.reminder_start_on).toBe(`${leapYear}-02-29`);
    await page.reload();
    row = await portfolioRecord(page, docket.title, width);
    await expect(row.locator('time[datetime="2020-01-15"]')).toBeVisible();
    await expect(row.locator(`time[datetime="${due}"]`).first()).toBeVisible();
    expect(await row.getByText("Manual, unverified", { exact: true }).count()).toBe(2);
    const second = await saveDates(page, row, docket.title, { renewal: replacement },
      "Synthetic acceptance: replace renewal without altering application");
    expect(second.payload).not.toHaveProperty("application_date");
    expect(second.result.source_application_on).toBe("2020-01-15");
    expect(second.result.source_renewal_due_on).toBe(replacement);
    const applicationCleared = await saveDates(page, row, docket.title, { application: "" },
      "Synthetic acceptance: remove unsupported application date independently");
    expect(applicationCleared.payload.application_date).toBeNull();
    expect(applicationCleared.payload).not.toHaveProperty("renewal_due_date");
    expect(applicationCleared.result.source_application_on).toBeNull();
    expect(applicationCleared.result.source_application_state).toBe("missing");
    expect(applicationCleared.result.source_renewal_due_on).toBe(replacement);
    expect(applicationCleared.result.current_version).toBe(second.result.current_version + 1);
    await page.reload();
    row = await portfolioRecord(page, docket.title, width);
    await expect(row.locator('time[datetime="2020-01-15"]')).toHaveCount(0);
    await expect(row.locator(`time[datetime="${replacement}"]`).first()).toBeVisible();
    await expect(row.getByText("Not set", { exact: true })).toBeVisible();
    const applicationRestored = await saveDates(page, row, docket.title, { application: "2020-01-15" },
      "Synthetic acceptance: restore supplied application date without changing renewal");
    expect(applicationRestored.payload).not.toHaveProperty("renewal_due_date");
    expect(applicationRestored.result.source_application_on).toBe("2020-01-15");
    expect(applicationRestored.result.source_renewal_due_on).toBe(replacement);
    expect(applicationRestored.result.current_version).toBe(applicationCleared.result.current_version + 1);
    const stale = await request.patch(`${docketPath}/portfolio-dates`, { headers: workspace.headers,
      data: { expected_current_version: before.current_version, application_date: "2020-02-20",
        reason: "Synthetic stale update must not replay" } });
    expect(stale.status()).toBe(409);
    const retained = await json(await request.get(docketPath, { headers: workspace.headers }));
    expect(retained.current_particulars.representation_json.text).toEqual(before.current_particulars.representation_json.text);
    expect(retained.current_particulars.classes_json).toEqual(before.current_particulars.classes_json);
    expect(retained.current_particulars.parties_json).toEqual(before.current_particulars.parties_json);
    expect(retained.current_particulars.filing_manifest_json).toEqual(before.current_particulars.filing_manifest_json);
    expect(retained.status).toBe(before.status);
    expect(retained.is_active).toBe(before.is_active);
    await page.getByRole("button", { name: "Deadline tracker view", exact: true }).click();
    const tracker = page.getByRole("region", { name: "Deadline tracker", exact: true });
    await tracker.getByRole("textbox", { name: "Search renewal tracker", exact: true }).fill(docket.title);
    await tracker.getByRole("button", { name: "Search renewal tracker", exact: true }).click();
    let trackerRow = tracker.getByRole("row").filter({ has: page.getByRole("button", { name: `Edit dates for ${docket.title}`, exact: true }) });
    await expect(trackerRow).toBeVisible();
    const dueCell = trackerRow.locator(`time[datetime="${replacement}"]`);
    await dueCell.scrollIntoViewIfNeeded();
    await expect(dueCell).toBeInViewport();
    await expect(trackerRow.locator(`time[datetime="${leapYear}-03-30"]`)).toBeVisible();
    await expect(trackerRow.getByText("Scheduled", { exact: true })).toBeVisible();
    await expect(trackerRow.getByText(/^Delivered:/)).toHaveCount(0);
    const editAction = trackerRow.getByRole("button", { name: `Edit dates for ${docket.title}`, exact: true });
    await editAction.scrollIntoViewIfNeeded();
    await expect(editAction).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    const cleared = await saveDates(page, trackerRow, docket.title, { renewal: "" },
      "Synthetic acceptance: remove unsupported source renewal date");
    expect(cleared.payload.renewal_due_date).toBeNull();
    expect(cleared.payload).not.toHaveProperty("application_date");
    expect(cleared.result.source_application_on).toBe("2020-01-15");
    expect(cleared.result.tracker.next_reminder_at).toBeNull();
    await tracker.getByRole("combobox", { name: "Renewal tracker category" }).click();
    await page.getByRole("option", { name: "Missing Renewal Date", exact: true }).click();
    trackerRow = tracker.getByRole("row").filter({ has: page.getByRole("button", { name: `Edit dates for ${docket.title}`, exact: true }) });
    await expect(trackerRow.getByText("Missing Date", { exact: true })).toBeVisible();
    await expect(trackerRow.locator('time[datetime="2020-01-15"]')).toBeVisible();
    const final = await json(await request.get(`${workspace.api.origin}/api/ip/portfolio/renewal-tracker`, {
      headers: workspace.headers, params: { query: docket.title, category: "missing", limit: 50 } }));
    expect(final.rows).toHaveLength(1);
    expect(final.rows[0].docket_id).toBe(docket.id);
    expect(final.rows[0].source_renewal_due_on).toBeNull();
    expect(final.rows[0].source_application_on).toBe("2020-01-15");
    expect(final.counts.missing).toBe(1);
    await verifyReminderConfiguration(page, request, workspace, docket.id);
    const afterPolicy = await json(await request.get(docketPath, { headers: workspace.headers }));
    expect(afterPolicy.current_version).toBe(cleared.result.current_version);
    expect(afterPolicy.status).toBe(before.status);
    expect(afterPolicy.is_active).toBe(before.is_active);
    await workspace.release();
  });
}
