/** IPLF-037B: renewal instructions, reminders, filing, acceptance and grace. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "RenewalWorkflow2026!";

function pythonPath(): string {
  return process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
}

function runPython(args: string[], env: Record<string, string>): string {
  const result = spawnSync(pythonPath(), args, {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      ...env,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  return result.stdout.trim();
}

function grantIpEntitlement(companyId: string): void {
  runPython(
    [
      "-c",
      [
        "import os",
        "from caseops_api.db.models import BillingSubscription",
        "from caseops_api.db.session import get_session_factory",
        "session=get_session_factory()()",
        "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_037b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
        "session.commit()",
        "session.close()",
      ].join("; "),
    ],
    { CASEOPS_E2E_COMPANY_ID: companyId },
  );
}

async function bootstrap(api: APIRequestContext) {
  const slug = `renewal-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 037B Renewal LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Renewal Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
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
      jurisdictions: ["IN"],
      offices: ["Trade Marks Registry"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "renewal-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "2026.1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: tenant.membership.id,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  expect(configured.status(), await configured.text()).toBe(200);
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: {
      expected_config_version: (await configured.json()).configuration.version,
      enabled_automations: [],
    },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);
  return headers;
}

function seedRenewal(companyId: string, membershipId: string) {
  return JSON.parse(
    runPython(
      [path.join(repoRoot, "tests", "e2e", "support", "seed_iplf037b.py")],
      {
        CASEOPS_E2E_COMPANY_ID: companyId,
        CASEOPS_E2E_MEMBERSHIP_ID: membershipId,
      },
    ),
  ) as Record<string, string>;
}

async function createTerm(
  api: APIRequestContext,
  headers: Record<string, string>,
  ids: Record<string, string>,
) {
  const response = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${ids.docket}/renewal-terms`,
    {
      headers,
      data: {
        registration_event_id: ids.registration,
        renewal_deadline_id: ids.renewal,
        grace_deadline_id: ids.grace,
        fee_cost_item_id: ids.fee,
      },
    },
  );
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-037B completes UJ-26 and renewal exception paths", async ({ page }) => {
  test.setTimeout(240_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const ids = seedRenewal(tenant.company.id, tenant.membership.id);
  const originalTerm = await createTerm(api, headers, ids);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip/renewals");
  await expect(page.getByRole("heading", { name: "Trademark renewals" })).toBeVisible();
  await expect(page.getByText("ASTER renewal").first()).toBeVisible();
  await expect(page.getByText("Trade Marks Act and applicable rules")).toBeVisible();
  await expect(page.getByText("registry-renewal-rules-2026-v1")).toBeVisible();
  await expect(page.getByText(/Renewal official fee quote/)).toBeVisible();
  await expect(page.getByText("Reconciliation: unlinked")).toBeVisible();

  await page.getByRole("button", { name: "Schedule instruction notifications" }).click();
  await expect(page.getByText(/1 delivered · 6 queued/)).toBeVisible();

  await page.getByLabel("Authority name").fill("Authorized client contact");
  await page.getByLabel("Authority reference").fill("BOARD-2026-08");
  await page.getByLabel("Evidence reference").fill("portal://instruction/renewal-1");
  await page.getByRole("button", { name: "Record instruction" }).click();
  await expect(page.getByText("Authorized client contact")).toBeVisible();
  await expect(page.getByText(/1 delivered · 0 queued/)).toBeVisible();

  await page.getByLabel("Review reason").fill("Authority and renewal scope verified");
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByRole("table").getByText("Instructed")).toBeVisible();

  await page.getByLabel("Reason").fill("Provider filing instruction submitted");
  await page.getByLabel("Filing initiation reference").fill("PROVIDER-ACK-1");
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(
    page.getByRole("table").getByText("Filing in progress"),
  ).toBeVisible();

  await page.getByLabel("Reason").fill("Confirmed filing event linked");
  await page.getByLabel("Confirmed filing event ID").fill(ids.filing);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByRole("table").getByText("Filed")).toBeVisible();

  await page.getByLabel("Reason").fill("Registry acceptance verified");
  await page.getByLabel("Registry acceptance event ID").fill(ids.acceptance);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(
    page.getByRole("table").getByText("Registry accepted"),
  ).toBeVisible();

  await page.getByLabel("Reason").fill("Certificate and next term verified");
  await page.getByLabel("Accepted certificate document ID").fill(ids.certificate);
  await page.getByLabel("Confirmed next-term deadline ID").fill(ids.next_term);
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByRole("table").getByText("Completed")).toBeVisible();
  await expect(page.getByText("This renewal term is closed.")).toBeVisible();

  const completed = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${ids.docket}/renewal-terms`,
    { headers },
  );
  expect(completed.status(), await completed.text()).toBe(200);
  expect((await completed.json()).items[0]).toMatchObject({
    id: originalTerm.id,
    state: "completed",
    filing_initiated_reference: "PROVIDER-ACK-1",
    filing_event_id: ids.filing,
    acceptance_event_id: ids.acceptance,
    certificate_document_id: ids.certificate,
    next_term_deadline_id: ids.next_term,
  });

  const graceIds = seedRenewal(tenant.company.id, tenant.membership.id);
  await createTerm(api, headers, graceIds);
  runPython(
    [
      "-c",
      [
        "import os",
        "from datetime import date,timedelta",
        "from caseops_api.db.models import IpDeadline",
        "from caseops_api.db.session import get_session_factory",
        "session=get_session_factory()()",
        "renewal=session.get(IpDeadline,os.environ['RENEWAL_ID'])",
        "grace=session.get(IpDeadline,os.environ['GRACE_ID'])",
        "renewal.result_on=date.today()-timedelta(days=7)",
        "grace.result_on=date.today()+timedelta(days=30)",
        "session.commit()",
        "session.close()",
      ].join("; "),
    ],
    { RENEWAL_ID: graceIds.renewal, GRACE_ID: graceIds.grace },
  );
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByLabel("Renewal state").selectOption("grace");
  await expect(page.getByText("Recorded state: Due")).toBeVisible();
  await expect(page.getByText(/calendar is in grace/i)).toBeVisible();
  await page.getByLabel("Next state").selectOption("grace");
  await page.getByLabel("Reason").fill("Verified renewal grace period entered");
  await page.getByRole("button", { name: "Record transition" }).click();
  await expect(page.getByText("Recorded state: Due")).not.toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Trademark renewals" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
