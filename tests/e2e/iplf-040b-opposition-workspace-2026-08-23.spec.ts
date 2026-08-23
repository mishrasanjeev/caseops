/** IPLF-040B: applicant and opponent baseline opposition workspaces. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "OppositionWorkspace2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_040b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `opposition-workspace-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 040B Opposition LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Opposition Partner",
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
      offices: ["Trade Marks Registry Delhi"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "opposition-workspace-calendar",
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

function applicationPayload(title: string, applicationNumber: string) {
  return {
    title,
    restricted: false,
    asset_title: title,
    jurisdiction: "IN",
    office: "Trade Marks Registry Delhi",
    filing_phase: "draft",
    source_pending_identifier_allocation: false,
    application_number: {
      raw_value: applicationNumber,
      source: "e2e registry fixture",
      effective_from: "2026-08-23",
      is_primary: true,
    },
    particulars: {
      form_key: "TM-A",
      form_version: "2026.1",
      mark_kind: "word",
      representation: { text: title, evidence_reference: `e2e:${title}` },
      classes: [{ class_number: 9, specification: "Downloadable legal software" }],
      use_priority: null,
      parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }],
      agent: null,
      filing_manifest: [{
        key: "representation",
        label: "Mark representation",
        required: true,
        evidence_reference: `e2e:${title}`,
      }],
    },
  };
}

async function createApplication(
  api: APIRequestContext,
  headers: Record<string, string>,
  title: string,
  applicationNumber: string,
) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: applicationPayload(title, applicationNumber),
  });
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

async function createOpposition(
  page: Page,
  docketId: string,
  side: "Applicant" | "Opponent",
  oppositionNumber: string,
) {
  await page.goto(`/app/ip?docket=${docketId}`);
  const workspace = page.getByTestId("ip-opposition-workspace");
  await expect(workspace).toBeVisible();
  await workspace.getByRole("button", { name: side }).click();
  await workspace.getByLabel("Intake source").selectOption("registry_event");
  await workspace.getByLabel("Opposition number").fill(oppositionNumber);
  await workspace.getByLabel("Number source").fill("e2e registry notice");
  const response = page.waitForResponse((row) =>
    row.url().endsWith(`/api/ip/dockets/${docketId}/proceedings`) &&
    row.request().method() === "POST",
  );
  await workspace.getByRole("button", { name: "Create opposition" }).click();
  expect((await response).status()).toBe(201);
  await expect(workspace.getByText(oppositionNumber, { exact: true })).toBeVisible();
  return workspace;
}

async function fillCommonProfile(
  workspace: ReturnType<Page["getByTestId"]>,
  applicant: string,
  opponent: string,
) {
  await workspace.getByLabel("Applicable rule version").fill("trade-marks-rules-2017@2026-08-23");
  await workspace.getByLabel("Forum").fill("Trade Marks Registry Delhi");
  await workspace.getByLabel("Notice source reference").fill("notice:e2e:040b");
  await workspace.getByLabel("Profile source URL or reference").fill("https://ipindia.gov.in/");
  await workspace.getByLabel("Party 1 name").fill(applicant);
  await workspace.getByLabel("Party 2 name").fill(opponent);
  await workspace.getByLabel("Ground 1 classification source").selectOption("ai_assisted");
  await workspace.getByLabel("Ground 1 lawyer detail").fill(
    "Opposition counsel confirmed the pleaded earlier-mark ground.",
  );
  await workspace.getByLabel("Scope 1 class").fill("9");
  await workspace.getByLabel("Scope 1 goods and services").fill("Downloadable legal software");
}

test("IPLF-040B completes applicant and opponent opposition workspace baselines", async ({ page }) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(15_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const applicantApplication = await createApplication(
    api,
    headers,
    "ASTER APPLICANT",
    "TM-APP-040B-A",
  );
  const opponentApplication = await createApplication(
    api,
    headers,
    "ASTER OPPONENT",
    "TM-APP-040B-O",
  );
  await signIn(page, tenant.slug, tenant.email);

  const applicant = await createOpposition(
    page,
    applicantApplication.docket.id,
    "Applicant",
    "OPP-040B-A",
  );
  await fillCommonProfile(
    applicant,
    "Applicant Industries Private Limited",
    "Opponent Brands LLP",
  );
  await applicant.getByLabel("Method").fill("registry email");
  await applicant.getByLabel("Destination").fill("applicant@example.com");
  await applicant.getByLabel("Served on").fill("2026-08-20");
  await applicant.getByLabel("Service evidence").fill("evidence:service:applicant");
  const applicantSave = page.waitForResponse((row) =>
    row.url().includes("/opposition-workspace") && row.request().method() === "PUT",
  );
  await applicant.getByRole("button", { name: "Confirm opposition profile" }).click();
  const applicantSaved = await applicantSave;
  expect(applicantSaved.status(), await applicantSaved.text()).toBe(200);
  expect((await applicantSaved.json()).ready_for_stage_progression).toBe(true);
  await expect(applicant.getByText("Ready", { exact: true })).toBeVisible();
  const applicantStage = applicant.getByTestId("ip-opposition-stage-form");
  await applicantStage.getByLabel("Reason").fill("Filed the reviewed notice of opposition.");
  await applicantStage.getByLabel("Source reference").fill("registry:notice:040b-a");
  await applicantStage.getByLabel("Evidence references").fill("evidence:filing:040b-a");
  const stageResponse = page.waitForResponse((row) =>
    row.url().endsWith("/stage") && row.request().method() === "POST",
  );
  await applicantStage.getByRole("button", { name: "Apply stage" }).click();
  expect((await stageResponse).status()).toBe(200);
  const stageSummary = applicant.getByText("Stage", { exact: true }).locator("..");
  await expect(stageSummary.getByText("notice filed", { exact: true })).toBeVisible();

  const opponent = await createOpposition(
    page,
    opponentApplication.docket.id,
    "Opponent",
    "OPP-040B-O",
  );
  await fillCommonProfile(
    opponent,
    "Applicant Products Limited",
    "Opponent Brands LLP",
  );
  await opponent.getByLabel("Client instruction").selectOption("confirmed");
  await opponent.getByLabel("Instruction reference").fill("instruction:email:040b-o");
  await opponent.getByLabel("Limitation date").fill("2026-09-20");
  await opponent.getByRole("button", { name: "Add right" }).click();
  await opponent.getByLabel("Right 1 mark").fill("PRIOR ASTER");
  await opponent.getByLabel("Right 1 identifier").fill("TM-PRIOR-100");
  await opponent.getByLabel("Right 1 owner").fill("Opponent Brands LLP");
  await opponent.getByLabel("Right 1 status").fill("registered");
  await opponent.getByLabel("Right 1 goods and services").fill("Downloadable legal software");
  const opponentSave = page.waitForResponse((row) =>
    row.url().includes("/opposition-workspace") && row.request().method() === "PUT",
  );
  await opponent.getByRole("button", { name: "Confirm opposition profile" }).click();
  const opponentSaved = await opponentSave;
  expect(opponentSaved.status(), await opponentSaved.text()).toBe(200);
  expect((await opponentSaved.json()).ready_for_stage_progression).toBe(true);
  await expect(opponent.getByText("Ready", { exact: true })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(opponent).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
