import { randomBytes } from "node:crypto";
import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { controlBounds, json, noOverflow, safeGet, safePost, type LocalFixture, type Origins } from "./platform-report-admin";

export type Lead = {
  id: string; submitted_at: string; contact_name: string | null; contact_email: string | null;
  contact_mobile: string | null; company_name: string | null; segment: string; selected_plan: string | null;
  source: string; role: string | null; intent: string | null; notes: string | null; privacy_notice_version: string | null;
  notification: { status: "not_requested" | "pending" | "sending" | "accepted" | "retry_pending" | "exhausted" | "outcome_unknown";
    attempts: number; last_error_code: string | null; eligible: boolean };
};
export type LeadPage = { items: Lead[]; next_cursor: string | null; has_more: boolean };

// Pending coordinated test-wrapper support, never a production route or a bypass of the no-paid fence.
export type LocalLeadFixture = {
  run_id: string; historical_ids: string[]; excluded_commercial_id: string;
  transport: "deterministic_local"; external_calls: 0; automated_marker_required: true;
  automated_request_preserved: true; production_rate_limit: "5/hour"; founder_unchanged: true;
};
type CapturedLeadNotification = {
  lead_id: string; recipient_email: string; subject: string; body: string;
  transport: "deterministic_local"; provider_call_performed: false;
  automated_request_preserved: true;
};

function fixturePath(target: Origins, fixture: LocalFixture) {
  if (!target.local) throw new Error("Lead fixture controls are strictly loopback-only; no request attempted.");
  return `${target.api.origin}/_e2e/platform-console/fixtures/${fixture.run_id}/leads`;
}

function fixtureCsrf() {
  const nonce = randomBytes(24).toString("hex");
  return { Cookie: `caseops_csrf=${nonce}`, "X-CSRF-Token": nonce };
}

export async function prepareLocalLeads(api: APIRequestContext, target: Origins, fixture: LocalFixture): Promise<LocalLeadFixture> {
  const result = await safePost(api, fixturePath(target, fixture), {
    headers: fixtureCsrf(), data: { web_origin: target.web.origin, manager_id: fixture.manager.id, historical_count: 251 },
  });
  if (result.status() === 404) throw new Error("Missing coordinated loopback lead fixture: retained pagination rows, isolated rate windows and deterministic no-paid notification capture are required. No mocked admission or skip is permitted.");
  const receipt = await json<LocalLeadFixture>(result, 201, "Loopback lead fixture");
  expect(receipt).toMatchObject({ run_id: fixture.run_id, transport: "deterministic_local", external_calls: 0,
    automated_marker_required: true, automated_request_preserved: true, production_rate_limit: "5/hour", founder_unchanged: true });
  expect(receipt.historical_ids).toHaveLength(251);
  expect(new Set(receipt.historical_ids).size).toBe(251);
  expect(receipt.historical_ids).not.toContain(receipt.excluded_commercial_id);
  return receipt;
}

export async function freshLocalAdmissionWindow(api: APIRequestContext, target: Origins, fixture: LocalFixture) {
  const receipt = await json(await safePost(api, `${fixturePath(target, fixture)}/window`, {
    headers: fixtureCsrf(), data: { web_origin: target.web.origin },
  }), 200, "Isolated loopback admission window");
  expect(receipt).toEqual({ run_id: fixture.run_id, scope: "dedicated_loopback_test_limiter", production_rate_limit: "5/hour",
    no_paid_marker_preserved: true, external_calls: 0 });
}

export async function capturedLeadNotifications(api: APIRequestContext, target: Origins, fixture: LocalFixture) {
  const receipt = await json<{ items: CapturedLeadNotification[]; external_calls: number }>(
    await safeGet(api, `${fixturePath(target, fixture)}/mail`), 200, "Deterministic lead notification ledger");
  expect(receipt.external_calls).toBe(0);
  for (const item of receipt.items) {
    expect(item).toMatchObject({ transport: "deterministic_local", provider_call_performed: false, automated_request_preserved: true });
    expect(item.recipient_email).toBe("sanjeev@orchestrum.in");
    expect(item.subject).toBe("CaseOps public enquiry saved");
    expect(item.body).toBe(`Public enquiry ${item.lead_id} is saved.\nReview its details in the protected administrative dashboard: https://caseops.ai/platform/leads\n`);
  }
  return receipt.items;
}

export async function drainLocalLeadNotifications(api: APIRequestContext, target: Origins, fixture: LocalFixture) {
  const receipt = await json(await safePost(api, `${fixturePath(target, fixture)}/drain`, {
    headers: fixtureCsrf(), data: { web_origin: target.web.origin },
  }), 200, "Bounded local notification drain");
  expect(receipt).toEqual({ run_id: fixture.run_id, selected: 7, external_calls: 0 });
}

export async function cleanupLocalLeads(api: APIRequestContext, target: Origins, fixture: LocalFixture) {
  const receipt = await json<{ run_id: string; retained: boolean; persisted_verified: boolean; no_provider_calls: boolean;
    founder_unchanged: boolean; production_rate_limit: string; pending_fixture_notifications: number }>(
    await safePost(api, `${fixturePath(target, fixture)}/cleanup`, {
      headers: fixtureCsrf(), data: { web_origin: target.web.origin, manager_id: fixture.manager.id },
    }), 200, "Retained loopback lead cleanup");
  expect(receipt).toMatchObject({ run_id: fixture.run_id, retained: true, persisted_verified: true,
    no_provider_calls: true, founder_unchanged: true, production_rate_limit: "5/hour", pending_fixture_notifications: 0 });
  return receipt;
}

export const publicLeadForms = [
  { path: "/#cta", source: "homepage", segment: "solo", intent: "demo" },
  { path: "/pricing", source: "pricing_page", segment: "solo", intent: "pricing" },
  { path: "/demo/solo-lawyers", source: "solo_lawyers", segment: "solo", intent: "pilot" },
  { path: "/demo/law-firms", source: "law_firms", segment: "firm", intent: "pilot" },
  { path: "/demo/general-counsels", source: "general_counsels", segment: "gc", intent: "pilot" },
  { path: "/demo/guide", source: "guide", segment: "firm", intent: "demo" },
  { path: "/demo/resource", source: "resource", segment: "firm", intent: "demo" },
] as const;

export function leadRow(page: Page, id: string): Locator {
  return page.getByRole("region", { name: "Public leads", exact: true }).getByRole("row")
    .filter({ has: page.getByText(id, { exact: true }) });
}

export async function leadDetails(page: Page, lead: Lead): Promise<void> {
  const row = leadRow(page, lead.id);
  await expect(row).toHaveCount(1);
  const summary = row.getByText("View submission", { exact: true });
  await controlBounds(summary, page, 16);
  await summary.click();
  await expect(row.locator("details")).toHaveAttribute("open", "");
  for (const [label, value] of [
    ["Reference", lead.id], ["Full name", lead.contact_name], ["Email", lead.contact_email],
    ["Phone", lead.contact_mobile], ["Firm or company", lead.company_name], ["Practice segment", lead.segment],
    ["Role", lead.role], ["Intent", lead.intent], ["Selected plan", lead.selected_plan],
    ["Public entry point", lead.source], ["Privacy notice", lead.privacy_notice_version], ["Notes", lead.notes],
  ]) {
    const valueNode = row.locator("dt").filter({ hasText: new RegExp(`^${label}$`) }).locator("+ dd");
    expect(await valueNode.textContent()).toBe(value ?? "Not provided");
  }
  const time = row.locator("time");
  await expect(time).toHaveAttribute("datetime", lead.submitted_at);
  await expect(time).toHaveText(new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata",
  }).format(new Date(lead.submitted_at)));
  await expect(row.locator("script, img, iframe")).toHaveCount(0);
  await noOverflow(page);
}

export async function leadControls(page: Page): Promise<void> {
  for (const name of ["Reload leads", "Previous page", "Next page"]) {
    await controlBounds(page.getByRole("button", { name, exact: true }), page);
  }
  const region = page.getByRole("region", { name: "Public leads", exact: true });
  await expect(region).toHaveAttribute("tabindex", "0");
  expect(await region.evaluate(node => {
    const bounds = node.getBoundingClientRect();
    const main = node.closest("main")!.getBoundingClientRect();
    return bounds.width > 200 && bounds.left >= main.left - 1 && bounds.right <= main.right + 1;
  }), "The wide table must scroll inside the available work area, not widen the page.").toBe(true);
  await noOverflow(page);
}
