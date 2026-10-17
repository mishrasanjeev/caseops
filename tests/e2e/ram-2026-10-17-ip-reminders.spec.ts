/** IP15-004/017: real persisted hearing policy and recipient-owned retained alerts. */
import { spawnSync } from "node:child_process";
import path from "node:path";
import type { APIRequestContext, APIResponse, Locator, Page } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv, repoRoot } from "./support/env";
import { createIp15ManualTrademark, prepareIp15Workspace, type Ip15Workspace } from "./support/ip15-workspace";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0 });

async function json(response: Pick<APIResponse, "status" | "json">, status = 200) {
  expect(response.status(), "IP17 request failed; private response content omitted.").toBe(status);
  return response.json();
}

async function openSchedule(page: Page, workspace: Ip15Workspace, docketId: string) {
  await page.goto(`${workspace.web.origin}/app/ip?docket=${encodeURIComponent(docketId)}&view=schedule`);
  await page.getByRole("tab", { name: "Hearings and deadlines", exact: true }).click();
  await expect(page.getByTestId("ip-hearing-workflow")).toBeVisible();
}

async function readHearing(request: APIRequestContext, workspace: Ip15Workspace, docketId: string, id: string) {
  const list = await json(await request.get(`${workspace.api.origin}/api/ip/hearings`, {
    headers: workspace.headers, params: { docket_id: docketId },
  }));
  const current = list.hearings.find((row: { id: string }) => row.id === id);
  expect(current, "The actual saved hearing must survive reload.").toBeTruthy();
  return current;
}

async function assertSavedPolicy(card: Locator, policy: { offsets_hours: number[]; channels: string[];
  recipient_membership_ids: string[] }, source: string, recipientLabel: string) {
  await expect(card.getByText(`Source: ${source}`, { exact: true })).toBeVisible();
  await expect(card.getByText(`Reminder offsets: ${policy.offsets_hours.join(", ")} hours`, { exact: true })).toBeVisible();
  await expect(card.getByText(`Channels: ${policy.channels.join(", ")}`, { exact: true })).toBeVisible();
  await expect(card.getByTestId("ip-hearing-policy-recipients")).toHaveAttribute(
    "data-recipient-membership-ids", policy.recipient_membership_ids.join(","),
  );
  await expect(card.getByRole("list", { name: "Saved reminder recipients", exact: true })
    .getByText(recipientLabel, { exact: true })).toBeVisible();
}

function deliverOwnLocalReceipt(workspace: Ip15Workspace, docketId: string, sourceId: string, intentId: string) {
  if (!workspace.local || ![workspace.web, workspace.api].every(url => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))
    || !/^ip15-[a-f0-9-]{36}$/.test(workspace.actor.company.slug)
    || ![docketId, sourceId, intentId].every(id => /^[a-f0-9-]{36}$/.test(id))) throw new Error("Local delivery fixture identity rejected.");
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const relative = path.relative(path.join(repoRoot, "apps/api/.venv"), path.resolve(python));
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Local delivery requires candidate-owned Python.");
  const script = [
    "import os", "from pathlib import Path", "from datetime import UTC,datetime", "from sqlalchemy.engine import make_url",
    "url=make_url(os.environ['CASEOPS_DATABASE_URL'])", "assert not url.query",
    "assert (url.drivername=='postgresql+psycopg' and url.host in {'localhost','127.0.0.1','::1'} and url.database) or (url.drivername=='sqlite+pysqlite' and Path(url.database).is_absolute() and Path(url.database).resolve().is_relative_to(Path.cwd().resolve()))",
    "from caseops_api.db.models import Company,CompanyMembership,NotificationDeliveryIntent,InAppNotification",
    "from caseops_api.db.session import get_session_factory", "from caseops_api.services.notification_delivery import process_notification_delivery_intent",
    "with get_session_factory()() as session:",
    "    company=session.get(Company,os.environ['IP17_COMPANY'])", "    member=session.get(CompanyMembership,os.environ['IP17_MEMBER'])",
    "    assert company and company.slug==os.environ['IP17_SLUG'] and company.slug.startswith('ip15-')",
    "    assert member and member.company_id==company.id and member.is_active and member.role=='owner'",
    "    intent=session.get(NotificationDeliveryIntent,os.environ['IP17_INTENT'])",
    "    assert intent and intent.company_id==company.id and intent.ip_docket_id==os.environ['IP17_DOCKET'] and intent.recipient_membership_id==member.id",
    "    assert intent.source_id==os.environ['IP17_SOURCE'] and intent.source_type=='ip_trademark_particular_version' and intent.event_type=='renewal_source_date_1month' and intent.channel=='in_app'",
    "    scheduled=intent.scheduled_for if intent.scheduled_for.tzinfo else intent.scheduled_for.replace(tzinfo=UTC)",
    "    assert scheduled<=datetime.now(UTC)",
    "    result=process_notification_delivery_intent(session,intent_id=intent.id,company_id=company.id)",
    "    assert result.delivered and result.external_calls==0 and intent.attempts==1",
    "    note=session.get(InAppNotification,intent.in_app_notification_id)",
    "    assert note and note.recipient_membership_id==member.id and note.source_id==intent.source_id and note.body==intent.body",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], { cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL,
      IP17_COMPANY: workspace.actor.company.id, IP17_SLUG: workspace.actor.company.slug, IP17_MEMBER: workspace.actor.membership.id,
      IP17_DOCKET: docketId, IP17_SOURCE: sourceId, IP17_INTENT: intentId, PYTHONPATH: path.join(repoRoot, "apps/api/src") } });
  expect(result.status, "Exact local in-app owner dispatch failed; private process output omitted.").toBe(0);
}

for (const width of [1280, 393]) {
  test(`IP17 hearing reminder policy and time confirmation at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(120_000);
    const workspace = await prepareIp15Workspace(page, request, baseURL, width);
    const me = await json(await request.get(`${workspace.api.origin}/api/auth/me`, { headers: workspace.headers }));
    expect(me.membership.id).toBe(workspace.actor.membership.id);
    expect(typeof me.user.full_name).toBe("string");
    expect(typeof me.user.email).toBe("string");
    const recipientLabel = `${me.user.full_name} — ${me.user.email}`;
    const { docket } = await createIp15ManualTrademark(workspace, request, "Synthetic IP17 hearing");
    await openSchedule(page, workspace, docket.id);
    const form = page.getByTestId("ip-hearing-workflow");
    const purpose = `Synthetic IP17 hearing ${workspace.run}`;
    await form.getByLabel("Hearing date", { exact: true }).fill("2099-12-20");
    await form.getByRole("combobox", { name: "Time precision", exact: true }).selectOption("time_not_published");
    await form.getByLabel("IANA timezone", { exact: true }).fill(workspace.timezone);
    await form.getByLabel("Purpose", { exact: true }).fill(purpose);
    await form.getByLabel("Source", { exact: true }).fill("manual");
    await form.getByLabel("Reminder offsets (hours)", { exact: true }).fill("48, 24");
    await form.getByLabel("Email", { exact: true }).uncheck();
    await form.getByLabel("In app", { exact: true }).check();
    await form.getByRole("button", { name: "Preview recipients and policy", exact: true }).click();
    await expect(form.getByTestId("ip-hearing-preview")).toContainText("Date-based reminder only");
    const creating = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/hearings" && response.request().method() === "POST");
    await form.getByRole("button", { name: "Confirm hearing and reminders", exact: true }).click();
    const created = await json(await creating, 201);
    const policy = { offsets_hours: [48, 24], channels: ["in_app"], recipient_membership_ids: [workspace.actor.membership.id] };
    expect(created).toMatchObject({ ip_docket_id: docket.id, hearing_on: "2099-12-20", time_status: "time_not_published", hearing_time: null,
      timezone: workspace.timezone, source: "manual", responsible_membership_id: workspace.actor.membership.id,
      reminder_policy: { ...policy, date_reminder_local_time: "18:00:00", critical: true }, current_schedule_generation: 1 });
    expect(created.reminders).toHaveLength(2);
    expect(created.reminders.every((row: { channel: string; status: string; recipient_membership_id: string }) =>
      row.channel === "in_app" && row.status === "queued" && row.recipient_membership_id === workspace.actor.membership.id)).toBe(true);
    await page.reload();
    const card = page.getByTestId(`ip-hearing-${created.id}`);
    await assertSavedPolicy(card, policy, "manual", recipientLabel);
    expect(await readHearing(request, workspace, docket.id, created.id)).toMatchObject({ reminder_policy: policy, hearing_time: null });
    await card.getByLabel(`Published time for ${purpose}`, { exact: true }).fill("14:30");
    const confirming = page.waitForResponse(response => new URL(response.url()).pathname === `/api/ip/hearings/${created.id}` && response.request().method() === "PATCH");
    await card.getByRole("button", { name: "Confirm published time", exact: true }).click();
    const confirmed = await json(await confirming);
    expect(confirmed).toMatchObject({ hearing_time: "14:30:00", time_status: "exact", reminder_policy: policy, current_schedule_generation: 2, time_confirmation_required: false });
    expect(confirmed.reminders).toHaveLength(4);
    const originalGeneration = confirmed.reminders.filter((row: { schedule_generation: number }) => row.schedule_generation === 1);
    expect(originalGeneration).toHaveLength(2);
    expect(originalGeneration.map((row: { id: string }) => row.id).sort()).toEqual(created.reminders.map((row: { id: string }) => row.id).sort());
    expect(originalGeneration.every((row: { status: string; replacement_generation: number }) => row.status === "cancelled" && row.replacement_generation === 2)).toBe(true);
    await expect(card).toContainText("14:30:00");
    await page.reload();
    await expect(card).toContainText("2099-12-20 · 14:30:00");
    expect(await readHearing(request, workspace, docket.id, created.id)).toMatchObject({ hearing_time: "14:30:00", time_status: "exact", reminder_policy: policy, current_schedule_generation: 2 });
    await card.getByLabel(`Reschedule ${purpose}`, { exact: true }).fill("2099-12-21");
    const rescheduling = page.waitForResponse(response => new URL(response.url()).pathname === `/api/ip/hearings/${created.id}` && response.request().method() === "PATCH");
    await card.getByRole("button", { name: "Reschedule", exact: true }).click();
    const rescheduled = await json(await rescheduling);
    expect(rescheduled).toMatchObject({ hearing_on: "2099-12-21", hearing_time: "14:30:00", reminder_policy: policy, source: "manual", current_schedule_generation: 3 });
    expect(rescheduled.reminders).toHaveLength(6);
    expect(rescheduled.reminders.filter((row: { schedule_generation: number }) => row.schedule_generation === 3)).toHaveLength(2);
    await expect(card).toContainText("2099-12-21 · 14:30:00");
    await page.reload();
    await assertSavedPolicy(card, policy, "manual", recipientLabel);
    expect(await readHearing(request, workspace, docket.id, created.id)).toMatchObject({ hearing_on: "2099-12-21", hearing_time: "14:30:00", timezone: workspace.timezone, source: "manual", reminder_policy: policy });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await workspace.release();
  });

  test(`IP17 recipient dismisses and restores delivered renewal at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(540_000);
    const workspace = await prepareIp15Workspace(page, request, baseURL, width);

    // A fresh import yields an immediate current-source alert independently of
    // the workspace's daily delivery time. No legal date/source is certified.
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: workspace.timezone,
      year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
    const part = (type: Intl.DateTimeFormatPartTypes) => Number(today.find(item => item.type === type)!.value);
    const due = new Date(Date.UTC(part("year"), part("month") - 1, part("day") + 1)).toISOString().slice(0, 10);
    const mark = `Synthetic IP17 renewal ${workspace.run}`;
    const preview = await json(await request.post(`${workspace.api.origin}/api/ip/imports/upload`, { headers: workspace.headers,
      multipart: { file: { name: `ip17-${workspace.run}.csv`, mimeType: "text/csv",
        buffer: Buffer.from(`Trademark,Application Number,Applicant,Class,Renewal Date,Internal Remarks\n${mark},IP17-${workspace.run},Synthetic IP17 owner,9,${due},private import remark\n`) } } }), 201);
    const imported = await json(await request.post(`${workspace.api.origin}/api/ip/imports/${preview.job.id}/commit`, { headers: workspace.headers,
      data: { preview_token: preview.job.preview_token, idempotency_key: `ip17-${workspace.run}` } }));
    expect(imported.job.committed_rows).toBe(1);
    const alertDocketId = imported.rows[0].created_docket_id as string;
    const alertDocket = await json(await request.get(`${workspace.api.origin}/api/ip/dockets/${alertDocketId}`, { headers: workspace.headers }));
    const sourceId = alertDocket.current_particulars.id;
    const admin = await json(await request.get(`${workspace.api.origin}/api/admin/notifications`, { headers: workspace.headers, params: { limit: 200 } }));
    const matches = admin.intents.filter((row: { source_id: string; event_type: string }) => row.source_id === sourceId && row.event_type === "renewal_source_date_1month");
    expect(matches).toHaveLength(1);
    if (workspace.local) deliverOwnLocalReceipt(workspace, alertDocketId, sourceId, matches[0].id);
    const list = async (dismissed = false) => json(await request.get(`${workspace.api.origin}/api/in-app-notifications`, {
      headers: workspace.headers, params: { docket_id: alertDocketId, dismissed: String(dismissed) },
    }));
    await expect.poll(async () => (await list()).items.length, { timeout: workspace.local ? 15_000 : 420_000, intervals: [1000, 5000, 10_000],
      message: "A current recipient alert requires an actual ordinary delivered in-app receipt." }).toBeGreaterThan(0);
    const notes = (await list()).items;
    const receipt = notes.find((row: { body: string | null }) => row.body?.includes(mark));
    expect(receipt, "The exact fresh imported mark must have its actual delivered receipt.").toBeTruthy();
    expect(receipt.body).toContain(due);
    expect(receipt.body).toContain(`/app/ip?docket=${alertDocketId}`);
    expect(receipt.body).not.toContain("private import remark");
    await openSchedule(page, workspace, alertDocketId);
    const center = page.getByTestId("ip-recipient-notifications");
    const note = center.getByTestId(`in-app-notification-${receipt.id}`);
    await expect(note.getByTestId(`in-app-notification-body-${receipt.id}`)).toHaveText(receipt.body);
    const dismissing = page.waitForResponse(response => new URL(response.url()).pathname === `/api/in-app-notifications/${receipt.id}` && response.request().method() === "PATCH");
    await note.getByRole("button", { name: "Dismiss alert", exact: true }).click();
    expect(await json(await dismissing)).toMatchObject({ id: receipt.id, body: receipt.body, status: "dismissed" });
    await expect(note).toHaveCount(0);
    await page.reload();
    await expect(note).toHaveCount(0);
    await center.getByRole("tab", { name: "Dismissed alerts", exact: true }).click();
    await expect(note.getByTestId(`in-app-notification-body-${receipt.id}`)).toHaveText(receipt.body);
    expect((await list(true)).items.find((row: { id: string }) => row.id === receipt.id)).toMatchObject({ status: "dismissed", body: receipt.body });
    const restoring = page.waitForResponse(response => new URL(response.url()).pathname === `/api/in-app-notifications/${receipt.id}` && response.request().method() === "PATCH");
    await note.getByRole("button", { name: "Restore alert", exact: true }).click();
    expect(await json(await restoring)).toMatchObject({ id: receipt.id, body: receipt.body, status: "unread" });
    await center.getByRole("tab", { name: "Active alerts", exact: true }).click();
    await expect(note.getByTestId(`in-app-notification-body-${receipt.id}`)).toBeVisible();
    await page.reload();
    await expect(note.getByTestId(`in-app-notification-body-${receipt.id}`)).toHaveText(receipt.body);
    expect((await list()).items.find((row: { id: string }) => row.id === receipt.id)).toMatchObject({ status: "unread", body: receipt.body });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await workspace.release();
  });
}
