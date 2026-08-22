/** IPLF-030B: searchable portfolio, personal view and background export. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "PortfolioWorkflow2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_030b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `portfolio-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 030B Portfolio LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Portfolio Partner",
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
      offices: ["Trade Marks Registry Mumbai"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "portfolio-calendar",
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

async function seedPortfolio(api: APIRequestContext, headers: Record<string, string>) {
  const docketResponse = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "ASTER DEVICE",
      restricted: false,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "device",
        representation: { document_reference: "document:aster-device", evidence_reference: "e2e:mark:1" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Products Private Limited" }],
        agent: { name: "Rao Trademark Agents" },
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:mark:1" }],
      },
    },
  });
  expect(docketResponse.status(), await docketResponse.text()).toBe(201);
  const docket = await docketResponse.json();
  const assetResponse = await api.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/assets`, {
    headers,
    data: { asset_kind: "trademark", jurisdiction: "IN", title: "Aster Device" },
  });
  expect(assetResponse.status(), await assetResponse.text()).toBe(201);
  const asset = await assetResponse.json();
  const applicationResponse = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docket.id}/applications`,
    {
      headers,
      data: {
        asset_id: asset.id,
        office: "Trade Marks Registry Mumbai",
        jurisdiction: "IN",
        filing_phase: "draft",
        application_number: {
          raw_value: "TM / 2026 / 00421",
          source: "e2e_registry_fixture",
          effective_from: "2026-08-21",
          is_primary: true,
        },
      },
    },
  );
  expect(applicationResponse.status(), await applicationResponse.text()).toBe(201);
  const application = (await applicationResponse.json()).application;
  const proceedingResponse = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.id,
        proceeding_kind: "opposition",
        side: "applicant",
        office: "Trade Marks Registry Mumbai",
        jurisdiction: "IN",
        stage: "evidence",
      },
    },
  );
  expect(proceedingResponse.status(), await proceedingResponse.text()).toBe(201);
  const oppositionResponse = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docket.id}/identifiers`,
    {
      headers,
      data: {
        identifier_kind: "opposition",
        raw_value: "OPP / 88 / 2026",
        office: "Trade Marks Registry Mumbai",
        jurisdiction: "IN",
        source: "e2e_registry_fixture",
        effective_from: "2026-08-21",
        is_primary: true,
        proceeding_id: (await proceedingResponse.json()).id,
      },
    },
  );
  expect(oppositionResponse.status(), await oppositionResponse.text()).toBe(201);
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-030B completes UJ-04 normal and exception workflow", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  await seedPortfolio(api, headers);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip/portfolio");
  await expect(page.getByRole("heading", { name: "Trademark portfolio" })).toBeVisible();
  await expect(page.getByText("Aster Device").first()).toBeVisible();
  await expect(page.getByText("TM / 2026 / 00421").first()).toBeVisible();
  await expect(page.getByText("OPP / 88 / 2026").first()).toBeVisible();
  await expect(page.getByText("Registry sync unavailable")).toBeVisible();

  await page.getByLabel("Search marks and registry numbers").fill("opp-88-2026");
  await page.getByRole("button", { name: "Search portfolio" }).click();
  await expect(page.getByText("Aster Device").first()).toBeVisible();

  await page.getByRole("button", { name: "Save view" }).click();
  await page.getByLabel("View name").fill("Opposition register");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("button", { name: "Update view" })).toBeVisible();

  await page.getByRole("button", { name: "Export" }).click();
  await expect(page.getByRole("heading", { name: "Confirm portfolio export" })).toBeVisible();
  await expect(page.getByText("1 accessible records will be included")).toBeVisible();
  await page.getByRole("button", { name: "Queue export" }).click();
  await expect(page.getByRole("heading", { name: "Recent exports" })).toBeVisible();
  const downloadButton = page.getByRole("button", { name: "Download export" });
  await expect(downloadButton).toBeVisible({ timeout: 30_000 });
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^trademark-portfolio-.+\.csv$/);

  await page.goto("/app/ip/portfolio/imports");
  await expect(page.getByRole("heading", { name: "Trademark portfolio import" })).toBeVisible();
  await page.getByLabel("CSV or XLSX file").setInputFiles({
    name: "iplf-030b-register.csv",
    mimeType: "text/csv",
    buffer: Buffer.from([
      "Title,Mark Text,Nice Class,Applicant,Application Number,Goods/Services,Agent,Jurisdiction,Office",
      "NOVA COUNSEL,NOVA COUNSEL,42,Nova Legal Private Limited,TM / 2026 / 00991,Legal advisory services,Rao Trademark Agents,IN,Trade Marks Registry Mumbai",
      "ASTER DEVICE,ASTER DEVICE,9,Aster Products Private Limited,TM / 2026 / 00421,Downloadable legal software,Rao Trademark Agents,IN,Trade Marks Registry Mumbai",
    ].join("\n")),
  });
  await page.getByRole("button", { name: "Validate file" }).click();
  await expect(page.getByRole("heading", { name: "Review iplf-030b-register.csv" })).toBeVisible();
  await expect(page.getByText("1 duplicate rows still need a decision.")).toBeVisible();

  await page.getByLabel("Decision for row 2").click();
  await page.getByRole("option", { name: "Link existing docket" }).click();
  await page.getByLabel("Existing docket for row 2").click();
  await page.getByRole("option", { name: "Aster Device" }).click();
  await page.getByRole("button", { name: "Save duplicate decisions" }).click();
  await expect(page.getByText("All rows are ready for a controlled commit.")).toBeVisible();
  await page.getByRole("button", { name: "Commit to portfolio" }).click();
  await expect(
    page.getByLabel("Review iplf-030b-register.csv").getByText("2 rows committed; 0 failed."),
  ).toBeVisible();

  await page.locator("#main").getByRole("link", { name: "Portfolio", exact: true }).click();
  await page.getByLabel("Search marks and registry numbers").fill("TM / 2026 / 00991");
  await page.getByRole("button", { name: "Search portfolio" }).click();
  await expect(page.getByText("NOVA COUNSEL").first()).toBeVisible();
  await expect(page.getByText("TM / 2026 / 00991").first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("a:visible", { hasText: "NOVA COUNSEL" })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true);
  await api.dispose();
});
