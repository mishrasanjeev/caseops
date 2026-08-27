/** IPLF-044B: effective-dated Matter linkage with independent lifecycle display. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "MatterLinkage2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_044_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `matter-linkage-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 044 Linkage LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "IP Linkage Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function enableWorkspace(api: APIRequestContext, tenant: any) {
  const headers = { Authorization: `Bearer ${tenant.access_token}` };
  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      expected_version: null,
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["Trade Marks Registry Delhi"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "iplf-044-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "trade-marks-rules-2017@2026-08-23" },
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

async function createMatter(
  api: APIRequestContext,
  headers: Record<string, string>,
  code: string,
  title: string,
) {
  const created = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      title,
      matter_code: code,
      practice_area: "civil",
      forum_level: "high_court",
      status: "intake",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const matter = await created.json();
  const conflict = await api.post(`${apiBaseUrl}/api/matters/${matter.id}/conflict-checks`, {
    headers,
    data: { opposing_party_name: "Linked Brands LLP", related_party_names: [] },
  });
  expect(conflict.status(), await conflict.text()).toBe(200);
  const activated = await api.patch(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers,
    data: { status: "active", expected_updated_at: matter.updated_at },
  });
  expect(activated.status(), await activated.text()).toBe(200);
  return activated.json();
}

async function signIn(page: Page, tenant: any) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-044B links independent Matter and IP lifecycles end to end", async ({ page }) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const operationalMatter = await createMatter(
    api,
    headers,
    `IPLF-044-OPS-${Date.now()}`,
    "Trademark portfolio operations",
  );
  const litigationMatter = await createMatter(
    api,
    headers,
    `IPLF-044-LIT-${Date.now()}`,
    "Trademark infringement litigation",
  );
  const application = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "IPLF 044 LINKED MARK",
      matter_id: operationalMatter.id,
      restricted: false,
      asset_title: "IPLF 044 LINKED MARK",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: `TM-APP-044-${Date.now()}`,
        source: "e2e registry fixture",
        effective_from: "2026-08-23",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "IPLF 044 LINKED MARK", evidence_reference: "e2e:mark:044" },
        classes: [{ class_number: 45, specification: "Legal services" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Linked Industries Private Limited" }],
        agent: null,
        filing_manifest: [{
          key: "representation",
          label: "Mark representation",
          required: true,
          evidence_reference: "e2e:mark:044",
        }],
      },
    },
  });
  expect(application.status(), await application.text()).toBe(201);
  const applicationBody = await application.json();
  const docket = applicationBody.docket;

  await signIn(page, tenant);
  await page.goto(`/app/ip?docket=${docket.id}&view=access`);
  const panel = page.getByTestId("ip-matter-links-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Operational", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Link Matter" }).click();
  await panel.getByLabel("Search Matters").fill(litigationMatter.matter_code);
  await panel.getByLabel("Matter", { exact: true }).click();
  await page
    .getByRole("option", { name: new RegExp(litigationMatter.matter_code) })
    .click();
  await panel
    .getByLabel("Reason")
    .fill("Trademark enforcement proceedings require a litigation reference.");
  const linked = page.waitForResponse(
    (row) => row.url().endsWith(`/api/ip/dockets/${docket.id}/matter-links`) && row.request().method() === "POST",
  );
  await panel.getByRole("button", { name: "Add relationship" }).click();
  const linkedResponse = await linked;
  expect(linkedResponse.status()).toBe(201);
  const linkedBody = await linkedResponse.json();

  const event = await api.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/events`, {
    headers,
    data: {
      expected_lifecycle_version: docket.lifecycle_version,
      event_kind: "formalities",
      source: "registry",
      source_reference: "registry:formalities:iplf-044",
      effective_at: new Date().toISOString(),
      responsible_membership_id: tenant.membership.id,
      reason: "Registry formalities review recorded for both linked workstreams.",
      evidence_refs: ["registry:formalities:iplf-044"],
      document_refs: [],
      resulting_deadline_refs: [],
      candidate_status: "candidate",
      acknowledged_exception_codes: [],
      payload: {},
    },
  });
  expect(event.status(), await event.text()).toBe(201);
  await page.reload();
  await expect(panel.getByText("Litigation", { exact: true })).toBeVisible();
  await expect(panel.getByText("Matter lifecycle", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("IP lifecycle", { exact: true }).first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(panel).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.goto(`/app/matters/${litigationMatter.id}`);
  const matterPanel = page.getByTestId("matter-ip-links-panel");
  await expect(matterPanel.getByText("IPLF 044 LINKED MARK", { exact: true })).toBeVisible();
  await expect(matterPanel.getByRole("link", { name: "Open IP" })).toHaveAttribute(
    "href",
    `/app/ip?docket=${docket.id}`,
  );

  await page.goto(`/app/matters/${litigationMatter.id}/timeline`);
  await expect(page.getByText("IP event", { exact: true }).first()).toBeVisible();
  const openIp = page.getByRole("link", { name: "Open IP record" }).first();
  await expect(openIp).toHaveAttribute("href", `/app/ip?docket=${docket.id}`);
  await openIp.click();
  await expect(page).toHaveURL(new RegExp(`/app/ip\\?docket=${docket.id}$`));
  await page.getByRole("tab", { name: "Access and links" }).click();

  const refreshedPanel = page.getByTestId("ip-matter-links-panel");
  const litigationRow = refreshedPanel
    .getByRole("link", { name: new RegExp(litigationMatter.matter_code) })
    .locator("xpath=ancestor::li");
  await litigationRow.getByRole("button", { name: "Retire" }).first().click();
  await litigationRow.getByLabel("Retirement reason").fill("Litigation engagement concluded after final instructions.");
  const retired = page.waitForResponse(
    (row) => row.url().endsWith(`/matter-links/${linkedBody.id}/retire`) && row.request().method() === "POST",
  );
  await litigationRow.getByRole("button", { name: "Retire" }).last().click();
  expect((await retired).status()).toBe(200);
  await expect(litigationRow.getByText("Retired", { exact: true })).toBeVisible();

  const finalLinks = await api.get(`${apiBaseUrl}/api/ip/dockets/${docket.id}/matter-links`, {
    headers,
  });
  expect(finalLinks.status(), await finalLinks.text()).toBe(200);
  const finalBody = await finalLinks.json();
  expect(finalBody.count).toBe(2);
  expect(finalBody.active_count).toBe(1);
  expect(finalBody.links.find((row: any) => row.id === linkedBody.id).retired_at).not.toBeNull();
  await api.dispose();
});
