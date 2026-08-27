/** IPLF-046B: deterministic pleading validation and append-only filing lifecycle. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "PleadingValidation2026!";

function runPython(lines: string[], environment: Record<string, string>): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const result = spawnSync(python, ["-c", lines.join("; ")], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      ...environment,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

function grantIpEntitlement(companyId: string): void {
  runPython([
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_046_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ], { COMPANY_ID: companyId });
}

function seedAuthority(citation: string, title: string): void {
  runPython([
    "import os, uuid",
    "from datetime import UTC, date, datetime",
    "from caseops_api.db.models import AuthorityDocument, AuthorityDocumentType, MatterForumLevel",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(AuthorityDocument(id=str(uuid.uuid4()),source='iplf-046-e2e',adapter_name='seed',court_name='Delhi High Court',forum_level=MatterForumLevel.HIGH_COURT,document_type=AuthorityDocumentType.JUDGMENT,title=os.environ['TITLE'],case_reference=None,bench_name='IP Division',neutral_citation=os.environ['CITATION'],decision_date=date(2026,8,20),canonical_key='iplf046::'+os.environ['CITATION'],source_reference=None,summary=os.environ['TITLE']+' trademark opposition procedural directions and relief',document_text=None,ingested_at=datetime.now(UTC)))",
    "session.commit()",
    "session.close()",
  ], { CITATION: citation, TITLE: title });
}

async function bootstrap(api: APIRequestContext) {
  const slug = `pleading-validation-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 046 Pleading LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Pleading Review Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const tenant = await response.json();
  grantIpEntitlement(tenant.company.id as string);
  return { ...tenant, slug, email };
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
      holiday_calendar_key: "iplf-046-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "trade-marks-rules-2017@2026-08-24" },
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

async function signIn(page: Page, tenant: any): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.email);
  await page.locator("#password").fill(PASSWORD);
  const loginResponse = page.waitForResponse((response) =>
    response.url().includes("/api/auth/login")
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const response = await loginResponse;
  expect(response.status(), await response.text()).toBe(200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function clickTransition(page: Page, name: string): Promise<void> {
  const response = page.waitForResponse((row) =>
    row.url().includes("/drafts/") && row.request().method() === "POST",
  );
  await page.getByRole("button", { name, exact: true }).click();
  expect((await response).status()).toBe(200);
}

test("IPLF-046B validates, corrects, files, rejects, refiles, and serves", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const title = `IPLF 046 MARK ${Date.now()}`;
  const applicationResponse = await api.post(
    `${apiBaseUrl}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title,
        restricted: false,
        asset_title: title,
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "draft",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: `TM-APP-046-${Date.now()}`,
          source: "e2e registry fixture",
          effective_from: "2026-08-24",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: { text: title, evidence_reference: "e2e:mark:046" },
          classes: [{ class_number: 45, specification: "Legal services" }],
          use_priority: null,
          parties: [{ role: "applicant", name: "Validation Industries Private Limited" }],
          agent: null,
          filing_manifest: [{
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "e2e:mark:046",
          }],
        },
      },
    },
  );
  expect(applicationResponse.status(), await applicationResponse.text()).toBe(201);
  const application = await applicationResponse.json();
  const docket = application.docket;
  const proceedingResponse = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.application.id,
        proceeding_kind: "opposition",
        side: "opponent",
        office: "Trade Marks Registry Delhi",
        jurisdiction: "IN",
        stage: "draft",
        origin_kind: "registry_event",
        source_pending_identifier_allocation: true,
      },
    },
  );
  expect(proceedingResponse.status(), await proceedingResponse.text()).toBe(201);
  const proceeding = await proceedingResponse.json();
  const citation = `2026 SCC OnLine Del ${Date.now().toString().slice(-6)}`;
  seedAuthority(citation, title);
  const base = `${apiBaseUrl}/api/ip/dockets/${docket.id}/proceedings/${proceeding.id}`;
  const created = await api.post(`${base}/drafts`, {
    headers,
    data: { title: "Notice of opposition", template_key: "trademark_opposition_notice" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const draft = await created.json();
  const generated = await api.post(`${base}/drafts/${draft.id}/generate`, {
    headers,
    data: { focus_note: title },
  });
  expect(generated.status(), await generated.text()).toBe(200);

  await signIn(page, tenant);
  await page.goto(`/app/ip?docket=${docket.id}`);
  await page.getByRole("tab", { name: "Proceedings" }).click();
  const workspace = page.getByTestId("ip-pleading-workspace");
  await expect(workspace).toBeVisible();
  await expect(workspace.getByTestId("ip-draft-validation")).toContainText("0 blockers");

  const body = workspace.getByLabel("Pleading body");
  const original = await body.inputValue();
  await body.fill(`${original}\n\nFiling date: [DATE]. See Annexure A.`);
  await workspace.getByRole("button", { name: "Save revision" }).click();
  await expect(workspace.getByTestId("ip-draft-validation")).toContainText("2 blockers");
  await body.fill(`${original}\n\nFiling date: 24 August 2026.`);
  await workspace.getByRole("button", { name: "Save revision" }).click();
  await expect(workspace.getByTestId("ip-draft-validation")).toContainText("0 blockers");
  await expect(workspace.getByTestId("ip-draft-comparison")).toBeVisible();

  await clickTransition(page, "Submit");
  await clickTransition(page, "Approve");
  await clickTransition(page, "Finalize");
  const download = page.waitForEvent("download");
  await workspace.getByRole("button", { name: "Filing bundle" }).click();
  expect((await download).suggestedFilename()).toContain("filing-bundle.zip");
  await workspace.getByLabel("Registry reference").fill("TM-O/046/FILED-1");
  await clickTransition(page, "Mark filed");
  await workspace.getByLabel("Registry reference").fill("TM-O/046/REJECTED-1");
  await clickTransition(page, "Rejected");

  await body.fill(`${await body.inputValue()}\nCorrected Registry particular.`);
  await workspace.getByRole("button", { name: "Save revision" }).click();
  await clickTransition(page, "Submit");
  await clickTransition(page, "Approve");
  await clickTransition(page, "Finalize");
  await workspace.getByLabel("Registry reference").fill("TM-O/046/FILED-2");
  await clickTransition(page, "Mark filed");
  await workspace.getByLabel("Registry reference").fill("TM-O/046/SERVICE-1");
  await workspace.getByLabel("Service method").fill("registered-post");
  await clickTransition(page, "Mark served");
  await expect(workspace.getByText("served", { exact: true })).toBeVisible();
  await workspace.getByText("Review and filing history", { exact: true }).click();
  await expect(workspace.getByText("file on revision 3", { exact: false })).toBeVisible();
  await expect(workspace.getByText("file on revision 4", { exact: false })).toBeVisible();

  await api.dispose();
});
