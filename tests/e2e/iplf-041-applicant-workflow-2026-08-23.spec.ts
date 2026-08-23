/** IPLF-041: governed applicant opposition work product and deadline journey. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "ApplicantWorkflow2026!";
const MEMBER_PASSWORD = "ApplicantMember2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_041_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `applicant-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 041 Applicant LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Applicant Partner",
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
      holiday_calendar_key: "iplf-041-calendar",
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

async function createMember(api: APIRequestContext, tenant: any, label: string) {
  const email = `${label}-${tenant.slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers: { Authorization: `Bearer ${tenant.access_token}` },
    data: { full_name: `IPLF 041 ${label}`, email, password: MEMBER_PASSWORD, role: "admin" },
  });
  expect(response.status(), await response.text()).toBe(200);
  const loginApi = await request.newContext();
  const login = await loginApi.post(`${apiBaseUrl}/api/auth/login`, {
    data: { email, password: MEMBER_PASSWORD, company_slug: tenant.slug },
  });
  expect(login.status(), await login.text()).toBe(200);
  const token = (await login.json()).access_token as string;
  await loginApi.dispose();
  return { membershipId: (await response.json()).membership_id as string, token };
}

function rulePayload(stage: "counterstatement_due" | "applicant_evidence_due", suffix: string) {
  const triggerKind = stage === "counterstatement_due" ? "opposition_notice_served" : "opponent_evidence_filed";
  const calculation = {
    deadline_kind: "legal_deadline",
    trigger_kind: triggerKind,
    base_date: "2026-08-14",
    base_date_certainty: "certain",
    duration_value: 1,
    duration_unit: "days",
    calendar_method: "business_days",
    direction: "after",
    include_base_date: false,
    next_working_day: true,
    extension_days: 0,
    rule_version_id: `fixture-rule-${suffix}`,
    rule_citation: `Trade Marks Rules applicant ${stage} fixture`,
    source_version: "fixture-source-2026-08-23",
    engine_version: "caseops-ip-deadline-v1",
    calendar: {
      calendar_version_id: "fixture-calendar-041",
      timezone: "Asia/Kolkata",
      weekend_days: [5, 6],
      holidays: ["2026-08-17"],
      exceptional_working_days: [],
      source_reference: "https://official.example/ip-india/calendar/2026",
      source_hash: "a".repeat(64),
    },
  };
  return {
    key: `in-tm-opposition-applicant-${stage}-${suffix}`,
    rule_kind: "deadline",
    jurisdiction: "IN",
    office: "Trade Marks Registry Delhi",
    right_kind: "trademark",
    proceeding_kind: "opposition",
    role: "applicant",
    stage,
    source_record_id: `tm-rules-applicant-${suffix}`,
    source_hash: "b".repeat(64),
    source_reference: "https://official.example/ip-india/tm-rules",
    effective_from: "2026-01-01",
    effective_until: null,
    engine_compatibility: "caseops-ip-deadline-v1",
    definition: {
      deadline_kind: "legal_deadline",
      trigger_kind: triggerKind,
      duration_value: 1,
      duration_unit: "days",
      calendar_method: "business_days",
      direction: "after",
      include_base_date: false,
      next_working_day: true,
      extension_days: 0,
      rule_citation: `Trade Marks Rules applicant ${stage} fixture`,
    },
    fixtures: [{
      id: `applicant-${suffix}-boundary`,
      fixture_kind: "boundary",
      calculation,
      expected_state: "candidate",
      expected_result_on: "2026-08-18",
      evidence_reference: `fixture:${suffix}`,
    }],
  };
}

async function governDeadlines(api: APIRequestContext, tenant: any) {
  const legal = await createMember(api, tenant, "legal");
  const reviewer = await createMember(api, tenant, "reviewer");
  const ownerHeaders = { Authorization: `Bearer ${tenant.access_token}` };
  const legalApi = await request.newContext({
    extraHTTPHeaders: { Authorization: `Bearer ${legal.token}` },
  });
  const calendar = await api.post(`${apiBaseUrl}/api/ip/working-calendars`, {
    headers: ownerHeaders,
    data: {
      key: `ip-india-041-${tenant.slug}`,
      name: "IP India applicant fixture calendar",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      timezone: "Asia/Kolkata",
      weekend_days: [5, 6],
      holidays: ["2026-08-17"],
      exceptional_working_days: [],
      source_priority: ["official_office_notice"],
      source_reference: "https://official.example/ip-india/calendar/2026",
      source_hash: "a".repeat(64),
      effective_from: "2026-01-01",
      effective_until: "2026-12-31",
    },
  });
  expect(calendar.status(), await calendar.text()).toBe(201);
  const calendarBody = await calendar.json();
  const activatedCalendar = await legalApi.post(`${apiBaseUrl}/api/ip/working-calendars/${calendarBody.id}/activate`, {
    data: { reason: "Verified synthetic official calendar fixture." },
  });
  expect(activatedCalendar.status(), await activatedCalendar.text()).toBe(200);

  for (const [stage, suffix] of [["counterstatement_due", "counter"], ["applicant_evidence_due", "evidence"]] as const) {
    const rule = await api.post(`${apiBaseUrl}/api/ip/deadline-rules`, {
      headers: ownerHeaders,
      data: rulePayload(stage, `${suffix}-${tenant.slug}`),
    });
    expect(rule.status(), await rule.text()).toBe(201);
    const activation = await legalApi.post(`${apiBaseUrl}/api/ip/deadline-rules/${(await rule.json()).id}/activate`, {
      data: {
        reviewer_membership_id: reviewer.membershipId,
        select_for_company: true,
        auto_confirm_eligible: false,
      },
    });
    expect(activation.status(), await activation.text()).toBe(200);
  }
  await legalApi.dispose();
  return { backupMembershipId: legal.membershipId };
}

async function createMatter(api: APIRequestContext, headers: Record<string, string>) {
  const created = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      title: "IPLF 041 applicant opposition",
      matter_code: `IPLF-041-${Date.now()}`,
      practice_area: "civil",
      forum_level: "high_court",
      status: "intake",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const matter = await created.json();
  const conflict = await api.post(`${apiBaseUrl}/api/matters/${matter.id}/conflict-checks`, {
    headers,
    data: { opposing_party_name: "Opponent Brands LLP", related_party_names: [] },
  });
  expect(conflict.status(), await conflict.text()).toBe(200);
  const activated = await api.patch(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers,
    data: { status: "active", expected_updated_at: matter.updated_at },
  });
  expect(activated.status(), await activated.text()).toBe(200);
  return activated.json();
}

async function createApplication(api: APIRequestContext, headers: Record<string, string>, matterId: string) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "IPLF 041 APPLICANT MARK",
      matter_id: matterId,
      restricted: false,
      asset_title: "IPLF 041 APPLICANT MARK",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: "TM-APP-041-E2E",
        source: "e2e registry fixture",
        effective_from: "2026-08-23",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "IPLF 041 APPLICANT MARK", evidence_reference: "e2e:mark:041" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }],
        agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:mark:041" }],
      },
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function signIn(page: Page, tenant: any) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function applyStage(page: Page, stage: string) {
  const form = page.getByTestId("ip-opposition-stage-form");
  await form.getByLabel("Next stage").selectOption(stage);
  await form.getByLabel("Source reference").fill(`registry:stage:${stage}`);
  await form.getByLabel("Evidence references").fill(`evidence:stage:${stage}`);
  await form.getByLabel("Reason").fill(`Counsel reviewed and authorized ${stage}.`);
  const response = page.waitForResponse((row) => row.url().endsWith("/stage") && row.request().method() === "POST");
  await form.getByRole("button", { name: "Apply stage" }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByText(stage.replaceAll("_", " "), { exact: true }).first()).toBeVisible();
}

test("IPLF-041 completes the governed applicant opposition journey", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const { backupMembershipId } = await governDeadlines(api, tenant);
  const matter = await createMatter(api, headers);
  const application = await createApplication(api, headers, matter.id);
  await signIn(page, tenant);
  await page.goto(`/app/ip?docket=${application.docket.id}`);
  const opposition = page.getByTestId("ip-opposition-workspace");
  await opposition.getByRole("button", { name: "Applicant" }).click();
  await opposition.getByLabel("Opposition number").fill("");
  const created = page.waitForResponse((row) => row.url().endsWith("/proceedings") && row.request().method() === "POST");
  await opposition.getByRole("button", { name: "Create opposition" }).click();
  expect((await created).status()).toBe(201);
  await expect(opposition.getByText("Pending allocation", { exact: true }).first()).toBeVisible();

  await opposition.getByLabel("Applicable rule version").fill("trade-marks-rules-2017@2026-08-23");
  await opposition.getByLabel("Forum").fill("Trade Marks Registry Delhi");
  await opposition.getByLabel("Notice source reference").fill("notice:e2e:041");
  await opposition.getByLabel("Notice document reference").fill("document:notice:041");
  await opposition.getByLabel("Profile source URL or reference").fill("https://ipindia.gov.in/");
  await opposition.getByLabel("Evidence references").first().fill("evidence:notice:041");
  await opposition.getByLabel("Document references").first().fill("document:notice:041");
  await opposition.getByLabel("Party 1 name").fill("Applicant Industries Private Limited");
  await opposition.getByLabel("Party 2 name").fill("Opponent Brands LLP");
  await opposition.getByLabel("Ground 1 lawyer detail").fill("Counsel confirmed the pleaded earlier-mark ground.");
  await opposition.getByLabel("Scope 1 class").fill("9");
  await opposition.getByLabel("Scope 1 goods and services").fill("Downloadable legal software");
  await opposition.getByLabel("Method").fill("registry email");
  await opposition.getByLabel("Destination").fill("applicant@example.com");
  await opposition.getByLabel("Served on").fill("2026-08-20");
  await opposition.getByLabel("Service evidence").fill("evidence:notice-service:041");
  const saved = page.waitForResponse((row) => row.url().includes("/opposition-workspace") && row.request().method() === "PUT");
  await opposition.getByRole("button", { name: "Confirm opposition profile" }).click();
  expect((await saved).status()).toBe(200);

  const applicant = opposition.getByTestId("ip-opposition-applicant-workflow");
  await expect(applicant.getByText("pending allocation", { exact: true })).toBeVisible();
  await applicant.getByLabel("Opposition number").fill("OPP / 041 / E2E");
  const numberRecorded = page.waitForResponse((row) => row.url().endsWith("/identifiers") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Record number" }).click();
  expect((await numberRecorded).status()).toBe(201);
  await expect(opposition.getByText("TM-APP-041-E2E", { exact: true })).toBeVisible();
  await expect(opposition.getByText("OPP / 041 / E2E", { exact: true })).toBeVisible();

  const counterProposal = page.waitForResponse((row) => row.url().endsWith("/applicant-deadlines") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Propose deadline" }).click();
  expect((await counterProposal).status()).toBe(201);
  await applicant.getByLabel("Backup membership ID").fill(backupMembershipId);
  const counterConfirmed = page.waitForResponse((row) => row.url().endsWith("/confirm") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Confirm" }).click();
  expect((await counterConfirmed).status()).toBe(200);
  await expect(applicant.getByText("Next: advance to counterstatement due", { exact: true })).toBeVisible();

  await applyStage(page, "notice_filed");
  await applyStage(page, "service_pending");
  await applyStage(page, "counterstatement_due");
  await expect(applicant.getByText("Next: file counterstatement", { exact: true })).toBeVisible();
  await applicant.getByLabel("TM-O filing reference").fill("TM-O-ACK-041-E2E");
  await applicant.getByLabel("Signatory").fill("Applicant Authorized Signatory");
  await applicant.getByLabel("Authority").fill("Board authority dated 2026-08-22");
  await applicant.getByLabel("Verified paragraph ranges").fill("1-12, verification");
  await applicant.getByLabel("Knowledge basis").fill("Personal knowledge and company records");
  await applicant.getByLabel("Source reference").fill("registry-filing:counterstatement:041");
  await applicant.getByLabel("Document references").fill("document:signed-counterstatement:041");
  await applicant.getByLabel("Evidence references").fill("filing-receipt:counterstatement:041");
  await applicant.getByLabel("Lawyer reason").fill("Counsel approved the signed TM-O counterstatement filing.");
  const filing = page.waitForResponse((row) => row.url().endsWith("/applicant-actions") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Record work product" }).click();
  expect((await filing).status()).toBe(201);

  await applyStage(page, "counterstatement_filed");
  await expect(applicant.getByText("Next: record counterstatement service", { exact: true })).toBeVisible();
  await applicant.getByLabel("Service method").fill("registered email");
  await applicant.getByLabel("Destination").last().fill("opponent-counsel@example.test");
  await applicant.getByLabel("Source reference").fill("service:counterstatement:041");
  await applicant.getByLabel("Evidence references").fill("service-receipt:counterstatement:041");
  await applicant.getByLabel("Lawyer reason").fill("Counsel confirmed service on the opponent.");
  const service = page.waitForResponse((row) => row.url().endsWith("/applicant-actions") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Record work product" }).click();
  expect((await service).status()).toBe(201);

  await applyStage(page, "opponent_evidence_due");
  await applyStage(page, "opponent_evidence_filed");
  await applyStage(page, "applicant_evidence_due");
  const evidenceProposal = page.waitForResponse((row) => row.url().endsWith("/applicant-deadlines") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Propose deadline" }).click();
  expect((await evidenceProposal).status()).toBe(201);
  await applicant.getByLabel("Backup membership ID").fill(backupMembershipId);
  const evidenceConfirmed = page.waitForResponse((row) => row.url().endsWith("/confirm") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Confirm" }).click();
  expect((await evidenceConfirmed).status()).toBe(200);
  await applicant.getByLabel("Rule 46 election").selectOption("rely_on_pleaded_facts");
  await applicant.getByLabel("Source reference").fill("instruction:rule-46:041");
  await applicant.getByLabel("Evidence references").fill("lawyer-instruction:rule-46:041");
  await applicant.getByLabel("Lawyer reason").fill("Counsel elected to rely on the pleaded counterstatement facts.");
  const election = page.waitForResponse((row) => row.url().endsWith("/applicant-actions") && row.request().method() === "POST");
  await applicant.getByRole("button", { name: "Record work product" }).click();
  expect((await election).status()).toBe(201);
  await applyStage(page, "applicant_evidence_filed");
  await applyStage(page, "withdrawn");
  await expect(opposition.getByText("withdrawn", { exact: true }).first()).toBeVisible();
  const preservedMatter = await api.get(`${apiBaseUrl}/api/matters/${matter.id}`, { headers });
  expect(preservedMatter.status(), await preservedMatter.text()).toBe(200);
  expect((await preservedMatter.json()).status).toBe("active");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(applicant).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
