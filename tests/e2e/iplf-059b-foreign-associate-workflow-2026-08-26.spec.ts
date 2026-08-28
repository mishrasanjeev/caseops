/** IPLF-059B / UJ-37 foreign-associate workflow acceptance. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { expectStatus } from "./support/iplf058b";
import {
  createForeignAssociateFixture,
  exerciseForeignAssociateJourney,
} from "./support/iplf059b";

const PASSWORD = "ForeignAssociateWorkflow2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || (
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python")
  );
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_059b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_COMPANY_ID: companyId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function bootstrap(api: APIRequestContext) {
  const slug = `foreign-associate-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 059B Foreign Associate LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Foreign Filing Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  await expectStatus(response, 200, "bootstrap foreign-associate tenant");
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function enableWorkspace(
  api: APIRequestContext,
  tenant: { access_token: string; membership: { id: string } },
) {
  const headers = { Authorization: `Bearer ${tenant.access_token}` };
  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      expected_version: null,
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN", "US"],
      offices: ["Trade Marks Registry Delhi", "USPTO"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "foreign-associate-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { ForeignFilings: "lawyer-reviewed-manual-only-v1" },
      notification_channels: ["in_app", "email"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: tenant.membership.id,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  await expectStatus(configured, 200, "configure IP workspace");
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: {
      expected_config_version: (await configured.json()).configuration.version,
      enabled_automations: [],
    },
  });
  await expectStatus(enabled, 200, "enable IP workspace");
  return headers;
}

async function signIn(page: Page, slug: string, email: string) {
  const response = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: { company_slug: slug, email, password: PASSWORD },
  });
  await expectStatus(response, 200, "foreign-associate sign-in");
  const session = await response.json();
  await page.goto("/");
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

test("IPLF-059B completes every UJ-37 path and exposes responsive evidence queues", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const runId = `${Date.now()}`;
  const fixture = await createForeignAssociateFixture(
    api, apiBaseUrl, headers, tenant.membership.id, runId,
  );
  await exerciseForeignAssociateJourney(api, apiBaseUrl, headers, fixture);

  await signIn(page, tenant.slug, tenant.email);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/app/ip/foreign-associates");
  await expect(page.getByRole("heading", { name: "Foreign associates" })).toBeVisible();
  for (const name of ["All", "Awaiting acknowledgement", "Missing independent evidence"]) {
    const control = page.getByRole("button", { name });
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);

  const completedInstruction = page.getByRole("button")
    .filter({ hasText: `TM-US-${runId}` })
    .filter({ hasText: "Completed" });
  await expect(completedInstruction).toHaveCount(1);
  await completedInstruction.click();
  for (const name of ["Instruction", "Actions", "Reminders", "History"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }
  await expect(page.getByText("Delivered", { exact: true })).toBeVisible();
  await expect(page.getByText("Received", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  const source = page.getByRole("link", { name: "Open source" }).first();
  await expect(source).toHaveAttribute("href", new RegExp(`/evidence/`));

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "Instruction" }).click();
  await expect(page.getByText(`US-TM-${runId}`)).toBeVisible();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Reminders" }).click();
  await expect(page.getByText(/acknowledgement due/i).first()).toBeVisible();

  await page.goto("/guide");
  await expect(page.getByRole("heading", { name: "Foreign-associate filings" })).toBeVisible();
  await page.goto("/law-firms");
  await expect(page.getByRole("heading", { name: "Foreign-associate filing control" })).toBeVisible();
  await api.dispose();
});
