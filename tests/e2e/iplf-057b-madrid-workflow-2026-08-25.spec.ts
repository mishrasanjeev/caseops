/** IPLF-057B / UJ-35: Madrid registration, designation, and source reconciliation. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "MadridWorkflow2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_057b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `madrid-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 057B Madrid LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Madrid Portfolio Partner",
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
      jurisdictions: ["IN", "EM"],
      offices: ["Trade Marks Registry Delhi", "WIPO International Bureau", "EUIPO"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "madrid-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { Madrid: "lawyer-reviewed-manual-only-v1" },
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

async function createBasicApplication(api: APIRequestContext, headers: Record<string, string>) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "ASTER INDIA BASIC MARK",
      restricted: false,
      asset_title: "ASTER",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "filed",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: `TM-MAD-${Date.now()}`,
        source: "official Indian application receipt",
        effective_from: "2026-08-25",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ASTER", evidence_reference: "e2e:057b:basic-mark" },
        classes: [
          { class_number: 9, specification: "Downloadable legal software" },
          { class_number: 42, specification: "Legal software as a service" },
        ],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Labs Private Limited" }],
        agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:057b:basic-mark" }],
      },
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function createRecord(
  api: APIRequestContext,
  headers: Record<string, string>,
  data: Record<string, unknown>,
) {
  const response = await api.post(`${apiBaseUrl}/api/ip/international-registrations`, {
    headers,
    data: {
      docket_title: "ASTER Madrid record",
      restricted: false,
      international_application_number: null,
      ir_number: null,
      wipo_reference: `WIPO-057B-${Date.now()}-${Math.random()}`,
      holder_name: "Aster Labs Private Limited",
      mark_name: "ASTER",
      designated_office: null,
      classes: [9, 42],
      goods_services: { "9": "Downloadable legal software", "42": "Legal software as a service" },
      priority_claims: [],
      wipo_status: null,
      national_status: null,
      local_agent_name: null,
      source_url: "https://www.wipo.int/madrid/monitor/fixture-057b",
      source_reference: `wipo:057b:${Date.now()}:${Math.random()}`,
      source_retrieved_at: new Date().toISOString(),
      application_date: null,
      international_registration_date: null,
      notification_date: null,
      publication_date: null,
      statement_date: null,
      dependency_end_date: null,
      renewal_due_date: null,
      ...data,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function workspace(api: APIRequestContext, headers: Record<string, string>, recordId: string) {
  const response = await api.get(`${apiBaseUrl}/api/ip/international-registrations/${recordId}/workspace`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function action(
  api: APIRequestContext,
  headers: Record<string, string>,
  membershipId: string,
  recordId: string,
  actionKind: string,
  authority: string,
  input: Record<string, unknown> = {},
) {
  const current = await workspace(api, headers, recordId);
  const response = await api.post(`${apiBaseUrl}/api/ip/international-registrations/${recordId}/actions`, {
    headers,
    data: {
      expected_version: current.record.version,
      expected_lifecycle_version: current.docket.lifecycle_version,
      action_kind: actionKind,
      authority,
      effective_at: new Date().toISOString(),
      responsible_membership_id: membershipId,
      reason: `IPLF-057B ${actionKind} reviewed by counsel.`,
      source_url: ["wipo", "office_of_origin", "national_office"].includes(authority)
        ? "https://www.wipo.int/madrid/monitor/fixture-057b"
        : null,
      source_reference: `iplf057b:${actionKind}:${Date.now()}:${Math.random()}`,
      source_retrieved_at: new Date().toISOString(),
      evidence_refs: [`evidence:${actionKind}:057b`],
      document_refs: [],
      deadline_refs: [],
      cost_item_refs: [],
      details: {},
      ...input,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return response.json();
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: { company_slug: slug, email, password: PASSWORD },
  });
  expect(login.status(), await login.text()).toBe(200);
  const session = await login.json();
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

test("IPLF-057B completes UJ-35 and all Madrid exception paths", async ({ page }) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const readinessResponse = await api.get(`${apiBaseUrl}/api/admin/provider-operations/readiness`, { headers });
  expect(readinessResponse.status(), await readinessResponse.text()).toBe(200);
  const readiness = new Map(
    (await readinessResponse.json()).providers.map((row: { provider: string }) => [row.provider, row]),
  );
  expect(readiness.get("wipo-madrid")).toEqual(expect.objectContaining({
    configured: false,
    enabled: false,
    external_calls_enabled: false,
    adapter_contract: expect.objectContaining({ endpoint_paths: [], implemented_capabilities: [] }),
  }));
  const basic = await createBasicApplication(api, headers);

  const registration = await createRecord(api, headers, {
    docket_title: "ASTER international registration",
    record_kind: "international_registration",
    direction: "outbound",
    basic_application_id: basic.application.id,
    office_of_origin: "IP India",
    form_kind: "MM2",
    parent_registration_id: null,
    designated_member_code: null,
    jurisdiction: null,
    designation_kind: null,
    designation_effective_date: null,
  });
  await action(api, headers, tenant.membership.id, registration.id, "form_prepared", "internal");
  await action(api, headers, tenant.membership.id, registration.id, "office_of_origin_certified", "office_of_origin");
  const irRecorded = await action(api, headers, tenant.membership.id, registration.id, "international_registration_recorded", "internal", {
    ir_number: `IR-${Date.now()}`,
    international_registration_date: "2026-08-25",
  });
  expect(irRecorded.record.ir_number).toMatch(/^IR-/);

  const india = await createRecord(api, headers, {
    docket_title: "ASTER India designation",
    record_kind: "international_designation",
    direction: "outbound",
    parent_registration_id: registration.id,
    basic_application_id: null,
    office_of_origin: null,
    designated_member_code: "IN",
    designated_office: "Trade Marks Registry India",
    jurisdiction: "IN",
    designation_kind: "original",
    designation_effective_date: "2026-08-25",
    form_kind: null,
  });
  const eu = await createRecord(api, headers, {
    docket_title: "ASTER EU designation",
    record_kind: "international_designation",
    direction: "outbound",
    parent_registration_id: registration.id,
    basic_application_id: null,
    office_of_origin: null,
    designated_member_code: "EM",
    designated_office: "EUIPO",
    jurisdiction: "EM",
    designation_kind: "subsequent",
    designation_effective_date: "2026-08-26",
    form_kind: null,
  });

  const impact = await action(api, headers, tenant.membership.id, registration.id, "central_attack_impact_review", "internal", {
    details: { impact_scope: [registration.id, india.id, eu.id], recommended_action: "Review dependency evidence and jurisdiction-specific conversion options." },
  });
  expect(impact.impact_review_only).toBe(true);
  expect(impact.record.wipo_status).toBeNull();

  const refusalCandidate = await action(api, headers, tenant.membership.id, india.id, "source_snapshot", "national_office", {
    national_status: "provisional_refusal",
    source_url: "https://ipindia.gov.in/trademark/designation/fixture-057b",
  });
  expect(refusalCandidate.status_applied).toBe(false);
  const indiaAfterCandidate = await workspace(api, headers, india.id);
  expect(indiaAfterCandidate.record.national_status).toBeNull();
  const refusalDecision = await action(api, headers, tenant.membership.id, india.id, "source_reconciliation", "internal", {
    reconciles_event_id: refusalCandidate.event.id,
    reconciliation_decision: "same_fact",
  });
  expect(refusalDecision.status_applied).toBe(true);
  expect(refusalDecision.record.national_status).toBe("provisional_refusal");
  expect((await workspace(api, headers, eu.id)).record.national_status).toBeNull();
  expect((await workspace(api, headers, registration.id)).record.wipo_status).toBeNull();

  const wipoCandidate = await action(api, headers, tenant.membership.id, eu.id, "source_snapshot", "wipo", {
    wipo_status: "notified",
  });
  const nationalCandidate = await action(api, headers, tenant.membership.id, eu.id, "source_snapshot", "national_office", {
    national_status: "examination_pending",
    source_url: "https://euipo.europa.eu/designation/fixture-057b",
  });
  const conflict = await workspace(api, headers, eu.id);
  expect(conflict.unresolved_source_candidates.map((row: { id: string }) => row.id)).toEqual(
    expect.arrayContaining([wipoCandidate.event.id, nationalCandidate.event.id]),
  );
  expect(conflict.record.wipo_status).toBeNull();
  expect(conflict.record.national_status).toBeNull();

  const agent = await action(api, headers, tenant.membership.id, india.id, "local_agent_instruction", "local_agent", {
    local_agent_name: "Delhi Madrid Counsel",
  });
  expect(agent.record.local_agent_name).toBe("Delhi Madrid Counsel");
  expect(agent.record.wipo_status).toBeNull();
  expect(agent.event.payload_json.authority).toBe("local_agent");

  const stale = await api.post(`${apiBaseUrl}/api/ip/international-registrations/${india.id}/actions`, {
    headers,
    data: {
      expected_version: 1,
      expected_lifecycle_version: 0,
      action_kind: "change_recorded",
      authority: "internal",
      effective_at: new Date().toISOString(),
      responsible_membership_id: tenant.membership.id,
      reason: "This stale writer must be rejected.",
      source_reference: "iplf057b:stale",
      source_retrieved_at: new Date().toISOString(),
    },
  });
  expect(stale.status(), await stale.text()).toBe(409);

  await signIn(page, tenant.slug, tenant.email);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/app/ip/madrid");
  await expect(page.getByRole("heading", { name: "Madrid portfolio" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New record" })).toBeVisible();
  for (const name of ["Status and sources", "Designations", "Deadlines and evidence", "History"]) {
    const tab = page.getByRole("tab", { name });
    await expect(tab).toBeVisible();
    const box = await tab.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    expect(box!.width).toBeGreaterThan(80);
  }
  const hasHorizontalOverflow = await page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(hasHorizontalOverflow).toBe(false);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button").filter({ hasText: "IN" }).first().click();
  await expect(page.getByText("National: provisional_refusal")).toBeVisible();
  await expect(page.getByText("Delhi Madrid Counsel")).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  const sourceLinks = page.getByRole("link", { name: /iplf057b:source_snapshot/i });
  expect(await sourceLinks.count()).toBeGreaterThan(0);
  for (const link of await sourceLinks.all()) {
    await expect(link).toHaveAttribute("href", /^https:\/\/ipindia\.gov\.in\//);
  }

  await page.goto("/guide");
  await expect(page.getByRole("heading", { name: "Madrid international registrations" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Madrid portfolio" })).toHaveAttribute("href", "/app/ip/madrid");
  await page.goto("/law-firms");
  await expect(page.getByRole("heading", { name: "Madrid international portfolio" })).toBeVisible();
  await expect(page.getByText(/not a claim of live provider sync/i)).toBeVisible();

  await api.dispose();
});
