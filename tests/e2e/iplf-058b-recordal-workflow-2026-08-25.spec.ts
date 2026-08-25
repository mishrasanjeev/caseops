/** IPLF-058B / UJ-36 and UJ-61 post-registration workflow acceptance. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { createRecordalFixture, expectStatus, recordTransaction } from "./support/iplf058b";

const PASSWORD = "RecordalWorkflow2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_058b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `recordal-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 058B Recordal LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Recordal Portfolio Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  await expectStatus(response, 200, "bootstrap recordal tenant");
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
      offices: ["Trade Marks Registry Delhi"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "recordal-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { Recordals: "lawyer-reviewed-manual-only-v1" },
      notification_channels: ["in_app"],
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
  await expectStatus(response, 200, "recordal sign-in");
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

test("IPLF-058B completes every UJ-36 recordal path and exposes UJ-61 title evidence", async ({ page }) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const fixture = await createRecordalFixture(
    api,
    apiBaseUrl,
    headers,
    tenant.membership.id,
    `${Date.now()}`,
  );

  const reviewed = await recordTransaction(
    api, apiBaseUrl, headers, tenant.membership.id, fixture, "review_approved",
  );
  expect(reviewed.recordal.status).toBe("ready");
  expect(reviewed.projected_title_interests).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        party_name: "Nova Holdings LLP",
        recordal_status: "pending",
        scope_json: expect.objectContaining({ scope_kind: "partial", affected_classes: [9] }),
      }),
    ]),
  );
  const pendingDocketResponse = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${fixture.docket.id}`,
    { headers },
  );
  await expectStatus(pendingDocketResponse, 200, "pending title docket");
  const pendingInterests = (await pendingDocketResponse.json()).title_interests;
  expect(pendingInterests).toEqual(expect.arrayContaining([
    expect.objectContaining({ party_name: "Oldco Brands Limited", recordal_status: "recorded" }),
    expect.objectContaining({ party_name: "Nova Holdings LLP", recordal_status: "pending" }),
  ]));

  await recordTransaction(api, apiBaseUrl, headers, tenant.membership.id, fixture, "filed");
  await recordTransaction(api, apiBaseUrl, headers, tenant.membership.id, fixture, "defect_noted");
  const invalidCorrection = await recordTransaction(
    api,
    apiBaseUrl,
    headers,
    tenant.membership.id,
    fixture,
    "corrected",
    { evidence_refs: [], document_refs: [] },
    422,
  );
  expect(await invalidCorrection.text()).toContain("corrected");
  await recordTransaction(api, apiBaseUrl, headers, tenant.membership.id, fixture, "corrected");
  await recordTransaction(api, apiBaseUrl, headers, tenant.membership.id, fixture, "filed");

  const acceptance = {
    source_url: fixture.snapshot.source_url,
    source_reference: `ipindia:${fixture.application.application.id}`,
    registry_snapshot_id: fixture.snapshot.id,
    registry_recorded_on: "2026-08-25",
  };
  const unresolved = await recordTransaction(
    api,
    apiBaseUrl,
    headers,
    tenant.membership.id,
    fixture,
    "accepted",
    acceptance,
    422,
  );
  expect(await unresolved.text()).toContain("conflict review");
  const accepted = await recordTransaction(
    api,
    apiBaseUrl,
    headers,
    tenant.membership.id,
    fixture,
    "accepted",
    { ...acceptance, details: { client_registry_conflict_reviewed: true } },
  );
  expect(accepted.recordal.status).toBe("accepted");
  expect(accepted.registry_projection_applied).toBe(true);
  expect(accepted.event.payload_json).toEqual(expect.objectContaining({
    client_registry_conflict_detected: true,
    client_registry_conflict_reviewed: true,
  }));

  await signIn(page, tenant.slug, tenant.email);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/app/ip/recordals");
  await expect(page.getByRole("heading", { name: "Post-registration" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Trademark renewals/ })).toHaveAttribute("href", "/app/ip/renewals");
  await expect(page.getByRole("link", { name: /Cancellation, rectification and non-use/ })).toHaveAttribute("href", "/app/ip");
  for (const name of ["Recordal", "Title at date", "Evidence and controls", "History"]) {
    const tab = page.getByRole("tab", { name });
    await expect(tab).toBeVisible();
    const box = await tab.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "Title at date" }).click();
  await expect(page.getByRole("heading", { name: "Registry-recorded position" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Nova Holdings LLP" }).first()).toBeVisible();
  await expect(page.getByText(/partial scope in classes 9/i)).toBeVisible();
  await page.getByRole("tab", { name: "Evidence and controls" }).click();
  await expect(page.getByRole("link", { name: new RegExp(`TM${fixture.recordal.affected_registration_refs_json[0].replace("TM-", "")}`, "i") })).toHaveAttribute("href", "https://ipindia.gov.in/trademark/");
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("link", { name: /ipindia:/ })).toHaveAttribute("href", "https://ipindia.gov.in/trademark/");

  await page.goto("/guide");
  await expect(page.getByRole("heading", { name: "Post-registration recordals and title" })).toBeVisible();
  await page.goto("/law-firms");
  await expect(page.getByRole("heading", { name: "Post-registration recordals and title" })).toBeVisible();
  await api.dispose();
});
