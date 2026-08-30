/** IPLF-043: shared hearing, order, and appeal journey. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "SharedOpposition2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_043_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `opposition-resolution-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 043 Resolution LLP",
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
      holiday_calendar_key: "iplf-043-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "trade-marks-rules-2017@2026-08-23" },
      notification_channels: ["in_app", "email"],
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

async function createMatter(api: APIRequestContext, headers: Record<string, string>) {
  const created = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      title: "IPLF 043 applicant opposition",
      matter_code: `IPLF-043-${Date.now()}`,
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

async function createApplication(
  api: APIRequestContext,
  headers: Record<string, string>,
  matterId: string,
) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "IPLF 043 TARGET MARK",
      matter_id: matterId,
      restricted: false,
      asset_title: "IPLF 043 TARGET MARK",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: "TM-APP-043-E2E",
        source: "e2e registry fixture",
        effective_from: "2026-08-23",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "IPLF 043 TARGET MARK", evidence_reference: "e2e:mark:043" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Applicant Industries Private Limited" }],
        agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:mark:043" }],
      },
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function createOpposition(
  api: APIRequestContext,
  headers: Record<string, string>,
  application: any,
  membershipId: string,
) {
  const created = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.application.id,
        proceeding_kind: "opposition",
        side: "applicant",
        office: "Trade Marks Registry Delhi",
        jurisdiction: "IN",
        stage: "draft",
        origin_kind: "registry_event",
        source_pending_identifier_allocation: false,
        opposition_number: {
          raw_value: "OPP / 043 / E2E",
          source: "e2e registry notice",
          effective_from: "2026-08-23",
          is_primary: true,
        },
      },
    },
  );
  expect(created.status(), await created.text()).toBe(201);
  const proceeding = await created.json();
  const profile = await api.put(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${proceeding.id}/opposition-workspace`,
    {
      headers,
      data: {
        expected_lifecycle_version: application.docket.lifecycle_version,
        expected_proceeding_version: proceeding.version,
        source: "manual",
        source_reference: "registry:opposition:043",
        source_notice_reference: "notice:opposition:043",
        source_notice_document_ref: "document:notice:043",
        effective_at: "2026-11-01T12:00:00+05:30",
        responsible_membership_id: membershipId,
        reason: "Counsel confirmed the opposition profile and source notice.",
        applicable_rule_version: "trade-marks-rules-2017@2026-08-23",
        forum: "Trade Marks Registry Delhi",
        client_instruction_state: "not_required",
        parties: [
          { role: "applicant", party_name: "Applicant Industries Private Limited", source: "notice" },
          { role: "opponent", party_name: "Opponent Brands LLP", source: "notice" },
        ],
        grounds: [{ category: "earlier_mark", lawyer_detail: "Earlier mark ground confirmed by counsel." }],
        challenged_scope: [{ class_number: 9, goods_services_segment: "Downloadable legal software" }],
        relied_on_rights: [],
        service: {
          method: "registry email",
          destination: "applicant@example.test",
          served_on: "2026-08-23",
          starts_response_period: true,
          evidence_refs: ["service:notice:043"],
        },
        evidence_refs: ["evidence:notice:043"],
        document_refs: ["document:notice:043"],
      },
    },
  );
  expect(profile.status(), await profile.text()).toBe(200);
  return proceeding;
}

async function signIn(page: Page, tenant: any) {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenant.slug);
  await page.locator("#email").fill(tenant.email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function fillCommon(
  shared: ReturnType<Page["getByTestId"]>,
  effectiveAt: string,
  suffix: string,
) {
  await shared.getByLabel("Effective at").fill(effectiveAt);
  await shared.getByLabel("Source reference").fill(`registry:${suffix}:043`);
  await shared.getByLabel("Lawyer confirmation").fill("Approved by responsible IP counsel");
  await shared.getByLabel("Evidence references").fill(`evidence:${suffix}:043`);
  await shared.getByLabel("Document references").fill(`document:${suffix}:043`);
  await shared.getByLabel("Reason").fill(`Counsel verified the complete ${suffix} record.`);
}

test("IPLF-043 carries a shared hearing through order and linked appeal", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const matter = await createMatter(api, headers);
  const application = await createApplication(api, headers, matter.id);
  const opposition = await createOpposition(
    api,
    headers,
    application,
    tenant.membership.id as string,
  );

  const hearingPending = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: opposition.version,
        to_stage: "hearing_pending",
        transition_kind: "skipped",
        source: "manual",
        source_reference: "registry:hearing-pending:043",
        effective_at: "2026-11-02T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Registry direction moved the opposition to hearing.",
        authority_reference: "registry-direction:043",
        evidence_refs: ["evidence:registry-direction:043"],
        authorized_confirmation: "Approved by responsible IP counsel.",
      },
    },
  );
  expect(hearingPending.status(), await hearingPending.text()).toBe(200);

  await signIn(page, tenant);
  await page.goto(`/app/ip?docket=${application.docket.id}&view=proceedings`);
  const specialized = page.getByTestId("ip-opposition-specialized-paths");
  await expect(specialized).toBeVisible();
  await specialized.getByLabel("Class 9 decision").selectOption("continuing");
  await fillCommon(specialized, "2026-11-03T12:00", "class-scope");
  const scopeRecorded = page.waitForResponse(
    (row) => row.url().endsWith("/opposition-shared-actions") && row.request().method() === "POST",
  );
  await specialized.getByTestId("ip-opposition-specialized-submit").click();
  expect((await scopeRecorded).status()).toBe(201);

  const shared = page.getByTestId("ip-opposition-shared-workflow");
  await expect(shared.getByText("Next: Schedule Hearing", { exact: true })).toBeVisible();
  await shared.getByLabel("Hearing date").fill("2026-12-10");
  const scheduled = page.waitForResponse((row) => row.url().endsWith("/api/ip/hearings") && row.request().method() === "POST");
  await shared.getByRole("button", { name: "Schedule hearing" }).click();
  expect((await scheduled).status()).toBe(201);

  const scheduledStage = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: 2,
        to_stage: "hearing_scheduled",
        transition_kind: "normal",
        source: "manual",
        source_reference: "registry:hearing-scheduled:043",
        effective_at: "2026-12-10T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Registry hearing was scheduled.",
        evidence_refs: ["evidence:cause-list:043"],
      },
    },
  );
  expect(scheduledStage.status(), await scheduledStage.text()).toBe(200);
  await page.reload();
  await expect(shared.getByText("Next: Record Hearing Preparation", { exact: true })).toBeVisible();
  await shared.getByLabel("Checklist items").fill("Paper book checked, Authorities paginated");
  await shared.getByLabel("Issues").fill("Likelihood of confusion, Prior use");
  await shared.getByLabel("Evidence documents").fill("document:evidence-bundle:043");
  await shared.getByLabel("Authorities").fill("case:authority:043");
  await shared.getByLabel("Written submissions").fill("document:submissions:043");
  await shared.getByLabel("Cause-list source").fill("registry:cause-list:2026-12-10");
  await fillCommon(shared, "2026-12-11T12:00", "hearing-preparation");
  const prepared = page.waitForResponse((row) => row.url().endsWith("/opposition-shared-actions") && row.request().method() === "POST");
  await shared.getByRole("button", { name: "Record hearing preparation" }).click();
  expect((await prepared).status()).toBe(201);

  const reserved = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: 3,
        to_stage: "reserved_for_order",
        transition_kind: "normal",
        source: "manual",
        source_reference: "registry:reserved:043",
        effective_at: "2026-12-12T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Registry reserved the opposition for order.",
        evidence_refs: ["evidence:hearing-complete:043"],
      },
    },
  );
  expect(reserved.status(), await reserved.text()).toBe(200);
  await page.reload();
  await expect(shared.getByText("Next: Record Order", { exact: true })).toBeVisible();
  await shared.getByLabel("Operative result").fill("Opposition allowed for the challenged goods and services.");
  await shared.getByLabel("Costs and directions").fill("Applicant to bear registry costs");
  await shared.getByLabel("Compliance direction").fill("File a compliance report with the Registry");
  await shared.getByLabel("Compliance due date").fill("2027-01-10");
  await shared.getByLabel("Order document").fill("document:opposition-order:043");
  await shared.getByLabel("Appeal review").selectOption("required");
  await fillCommon(shared, "2026-12-13T12:00", "order");
  const ordered = page.waitForResponse((row) => row.url().endsWith("/opposition-shared-actions") && row.request().method() === "POST");
  await shared.getByRole("button", { name: "Record opposition order" }).click();
  expect((await ordered).status()).toBe(201);

  const decided = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: 4,
        to_stage: "decided",
        transition_kind: "normal",
        source: "manual",
        source_reference: "registry:decided:043",
        effective_at: "2026-12-14T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Registry issued the opposition order.",
        evidence_refs: ["document:opposition-order:043"],
      },
    },
  );
  expect(decided.status(), await decided.text()).toBe(200);
  const appeal = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: application.application.id,
        proceeding_kind: "appeal",
        side: "respondent",
        office: "High Court of Delhi",
        jurisdiction: "IN",
        stage: "filed",
        origin_kind: "registry_event",
      },
    },
  );
  expect(appeal.status(), await appeal.text()).toBe(201);
  const appealBody = await appeal.json();
  const appealNumber = "C.A.(COMM.IPD-TM) 43/2026";
  const identifier = await api.post(`${apiBaseUrl}/api/ip/dockets/${application.docket.id}/identifiers`, {
    headers,
    data: {
      identifier_kind: "appeal",
      raw_value: appealNumber,
      office: "High Court of Delhi",
      jurisdiction: "IN",
      source: "court-filing:043",
      effective_from: "2026-12-15",
      is_primary: true,
      proceeding_id: appealBody.id,
    },
  });
  expect(identifier.status(), await identifier.text()).toBe(201);
  const appealPending = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: 5,
        to_stage: "appeal_pending",
        transition_kind: "normal",
        source: "manual",
        source_reference: "court:appeal-pending:043",
        effective_at: "2026-12-15T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Counsel confirmed the filed appeal.",
        evidence_refs: ["court-filing:043"],
      },
    },
  );
  expect(appealPending.status(), await appealPending.text()).toBe(200);
  await page.reload();
  await expect(shared.getByText("Next: Link Appeal", { exact: true })).toBeVisible();
  await shared.getByLabel("Target record ID").fill(appealBody.id);
  await shared.getByLabel("Appeal identifier").fill(appealNumber);
  await fillCommon(shared, "2026-12-16T12:00", "appeal");
  const linked = page.waitForResponse((row) => row.url().endsWith("/opposition-shared-actions") && row.request().method() === "POST");
  await shared.getByRole("button", { name: "Record appeal link" }).click();
  expect((await linked).status()).toBe(201);

  const appealed = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/stage`,
    {
      headers,
      data: {
        expected_lifecycle_version: 0,
        expected_proceeding_version: 6,
        to_stage: "appealed",
        transition_kind: "normal",
        source: "manual",
        source_reference: "court:appealed:043",
        effective_at: "2026-12-17T12:00:00+05:30",
        responsible_membership_id: tenant.membership.id,
        reason: "Counsel linked the appeal record and identifier.",
        evidence_refs: ["court-filing:043"],
      },
    },
  );
  expect(appealed.status(), await appealed.text()).toBe(200);

  const finalWorkflow = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/proceedings/${opposition.id}/opposition-shared-workflow`,
    { headers },
  );
  expect(finalWorkflow.status(), await finalWorkflow.text()).toBe(200);
  const finalBody = await finalWorkflow.json();
  expect(finalBody.current_stage).toBe("appealed");
  expect(finalBody.shared_actions.map((row: any) => row.payload_json.action_kind)).toEqual([
    "scope_review_recorded",
    "hearing_preparation_recorded",
    "order_recorded",
    "appeal_linked",
  ]);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(shared).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
