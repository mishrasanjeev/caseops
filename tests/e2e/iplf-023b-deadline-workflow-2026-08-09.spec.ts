import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "IpDeadlineProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function grantIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session = get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'], status='manual_active', segment='law_firm', source='iplf_023b_playwright', externally_billable=False, entitlement_overrides_json={'ip_workspace': True}))",
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

function promoteSyntheticAdmin(membershipId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from sqlalchemy import update",
    "from caseops_api.db.models import CompanyMembership, MembershipRole",
    "from caseops_api.db.session import get_session_factory",
    "session = get_session_factory()()",
    "session.execute(update(CompanyMembership).where(CompanyMembership.id == os.environ['CASEOPS_E2E_MEMBERSHIP_ID']).values(role=MembershipRole.ADMIN))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_MEMBERSHIP_ID: membershipId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function createAdmin(
  api: APIRequestContext,
  ownerToken: string,
  slug: string,
  label: string,
): Promise<{ membershipId: string; token: string }> {
  const email = `${label}-${slug}@example.com`;
  const created = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: {
      full_name: `${label} deadline approver`,
      email,
      password: PASSWORD,
      role: "member",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  const membershipId = (await created.json()).membership_id as string;
  promoteSyntheticAdmin(membershipId);
  const loginApi = await request.newContext();
  const login = await loginApi.post(`${apiBaseUrl}/api/auth/login`, {
    data: { email, password: PASSWORD, company_slug: slug },
  });
  expect(login.status(), await login.text()).toBe(200);
  const token = (await login.json()).access_token as string;
  await loginApi.dispose();
  return {
    membershipId,
    token,
  };
}

async function bootstrap(api: APIRequestContext): Promise<{
  slug: string;
  ownerToken: string;
  ownerMembershipId: string;
}> {
  const slug = `dl-${Math.random().toString(36).slice(2, 10)}`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 023B Deadline Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Deadline Proof Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  const ownerToken = body.access_token as string;
  const ownerMembershipId = body.membership.id as string;
  const headers = { Authorization: `Bearer ${ownerToken}` };
  const configuration = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["IP India"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "iplf-023b-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { "IN-TM": "2026.1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: ownerMembershipId,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  expect(configuration.status(), await configuration.text()).toBe(200);
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: { expected_config_version: 1, enabled_automations: [] },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);
  return { slug, ownerToken, ownerMembershipId };
}

async function seedDeadlineWorkflow(
  api: APIRequestContext,
  ownerToken: string,
  ownerMembershipId: string,
  slug: string,
): Promise<{ docketId: string; deadlineId: string; backupMembershipId: string; matterId: string }> {
  const ownerHeaders = { Authorization: `Bearer ${ownerToken}` };
  const legal = await createAdmin(api, ownerToken, slug, "legal");
  const reviewer = await createAdmin(api, ownerToken, slug, "reviewer");
  const legalApi = await request.newContext();
  const legalHeaders = { Authorization: `Bearer ${legal.token}` };

  const matterResponse = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: ownerHeaders,
    data: {
      title: "IPLF-023B legal deadline Matter",
      matter_code: unique("IP-DL").toUpperCase(),
      practice_area: "intellectual_property",
      forum_level: "tribunal",
      status: "intake",
    },
  });
  expect(matterResponse.status(), await matterResponse.text()).toBe(200);
  const matter = await matterResponse.json();
  const conflict = await api.post(`${apiBaseUrl}/api/matters/${matter.id}/conflict-checks`, {
    headers: ownerHeaders,
    data: { opposing_party_name: "Unrelated Deadline Fixture Co", related_party_names: [] },
  });
  expect(conflict.status(), await conflict.text()).toBe(200);
  const activatedMatter = await api.patch(`${apiBaseUrl}/api/matters/${matter.id}`, {
    headers: ownerHeaders,
    data: { status: "active", expected_updated_at: matter.updated_at },
  });
  expect(activatedMatter.status(), await activatedMatter.text()).toBe(200);

  const docketResponse = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers: ownerHeaders,
    data: {
      title: "DEADLINE FLOW mark",
      matter_id: matter.id,
      primary_identifier: unique("TM-DEADLINE"),
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: {
          text: "DEADLINE FLOW",
          evidence_reference: "attachment:deadline-flow-mark",
        },
        classes: [{ class_number: 42, specification: "Legal deadline software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Deadline Flow LLP" }],
        agent: null,
        filing_manifest: [{
          key: "representation",
          label: "Mark representation",
          required: true,
          evidence_reference: "attachment:deadline-flow-mark",
        }],
      },
    },
  });
  expect(docketResponse.status(), await docketResponse.text()).toBe(201);
  const docketId = (await docketResponse.json()).id as string;

  const calendarResponse = await api.post(`${apiBaseUrl}/api/ip/working-calendars`, {
    headers: ownerHeaders,
    data: {
      key: unique("ip-india-calendar"),
      name: "IP India verified calendar",
      jurisdiction: "IN",
      office: "IP India",
      timezone: "Asia/Kolkata",
      weekend_days: [5, 6],
      holidays: ["2026-08-17"],
      exceptional_working_days: [],
      source_priority: ["official_gazette"],
      source_reference: "https://official.example/ip-india/calendar/2026",
      source_hash: "a".repeat(64),
      effective_from: "2026-01-01",
      effective_until: "2026-12-31",
    },
  });
  expect(calendarResponse.status(), await calendarResponse.text()).toBe(201);
  const calendar = await calendarResponse.json();
  const calendarActivation = await legalApi.post(
    `${apiBaseUrl}/api/ip/working-calendars/${calendar.id}/activate`,
    {
      headers: legalHeaders,
      data: { reason: "Independent review of the official calendar source." },
    },
  );
  expect(calendarActivation.status(), await calendarActivation.text()).toBe(200);

  const ruleCalculation = {
    deadline_kind: "legal_deadline",
    trigger_kind: "examination_report_received",
    base_date: "2026-08-14",
    base_date_certainty: "certain",
    duration_value: 1,
    duration_unit: "days",
    calendar_method: "business_days",
    direction: "after",
    include_base_date: false,
    next_working_day: true,
    extension_days: 0,
    rule_version_id: "fixture-rule",
    rule_citation: "Trade Marks Rules, verified test citation",
    source_version: "fixture-source",
    engine_version: "caseops-ip-deadline-v1",
    calendar: {
      calendar_version_id: calendar.id,
      timezone: "Asia/Kolkata",
      weekend_days: [5, 6],
      holidays: ["2026-08-17"],
      exceptional_working_days: [],
      source_reference: calendar.source_reference,
      source_hash: calendar.source_hash,
    },
  };
  const ruleResponse = await api.post(`${apiBaseUrl}/api/ip/deadline-rules`, {
    headers: ownerHeaders,
    data: {
      key: unique("in-tm-response"),
      rule_kind: "deadline",
      jurisdiction: "IN",
      office: "IP India",
      right_kind: "trademark",
      proceeding_kind: "application",
      role: "applicant",
      stage: "examination",
      source_record_id: "official-tm-rules-2026-08-09",
      source_hash: "b".repeat(64),
      source_reference: "https://official.example/ip-india/tm-rules",
      effective_from: "2026-01-01",
      effective_until: null,
      engine_compatibility: "caseops-ip-deadline-v1",
      definition: {
        deadline_kind: "legal_deadline",
        trigger_kind: "examination_report_received",
        duration_value: 1,
        duration_unit: "days",
        calendar_method: "business_days",
        direction: "after",
        include_base_date: false,
        next_working_day: true,
        extension_days: 0,
        rule_citation: "Trade Marks Rules, verified test citation",
      },
      fixtures: [{
        id: "weekend-holiday-boundary",
        fixture_kind: "boundary",
        calculation: ruleCalculation,
        expected_state: "candidate",
        expected_result_on: "2026-08-18",
        evidence_reference: "fixture:official-calendar",
      }],
    },
  });
  expect(ruleResponse.status(), await ruleResponse.text()).toBe(201);
  const rule = await ruleResponse.json();
  const ruleActivation = await legalApi.post(
    `${apiBaseUrl}/api/ip/deadline-rules/${rule.id}/activate`,
    {
      headers: legalHeaders,
      data: {
        reviewer_membership_id: reviewer.membershipId,
        select_for_company: true,
        auto_confirm_eligible: false,
      },
    },
  );
  expect(ruleActivation.status(), await ruleActivation.text()).toBe(200);

  const proposal = await legalApi.post(`${apiBaseUrl}/api/ip/dockets/${docketId}/deadlines`, {
    headers: legalHeaders,
    data: {
      title: "Respond to examination report",
      rule_version_id: rule.id,
      calendar_version_id: calendar.id,
      base_date: "2026-08-14",
      base_date_certainty: "certain",
      is_critical: true,
    },
  });
  expect(proposal.status(), await proposal.text()).toBe(201);
  const deadlineId = (await proposal.json()).id as string;
  await legalApi.dispose();
  return {
    docketId,
    deadlineId,
    backupMembershipId: reviewer.membershipId,
    matterId: matter.id as string,
  };
}

async function installSession(page: Page, slug: string): Promise<void> {
  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: slug,
      email: `owner-${slug}@example.com`,
      password: PASSWORD,
    },
  });
  expect(login.status(), await login.text()).toBe(200);
  const session = (await login.json()) as Record<string, unknown>;
  await page.addInitScript((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

test("IPLF-023B legal deadline remains explicit, immutable, and usable at 360px", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const { slug, ownerToken, ownerMembershipId } = await bootstrap(api);
  const seeded = await seedDeadlineWorkflow(api, ownerToken, ownerMembershipId, slug);
  await installSession(page, slug);
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto("/app/ip");

  await expect(page.getByRole("heading", { name: "DEADLINE FLOW mark" })).toBeVisible();
  await page.getByRole("tab", { name: "Hearings and deadlines" }).click();
  const deadlineWorkspace = page.getByTestId("ip-deadline-workspace");
  await expect(deadlineWorkspace).toContainText("Calculations are proposals");
  await expect(deadlineWorkspace.getByText("Exception queue")).toBeVisible();
  await expect(deadlineWorkspace.getByText(/unowned/)).toBeVisible();
  await expect(deadlineWorkspace.getByText("2026-08-18 Â· candidate Â· v1")).toBeVisible();
  await expect(
    deadlineWorkspace.getByRole("link", { name: /Open verified rule source/ }),
  ).toHaveAttribute("href", "https://official.example/ip-india/tm-rules");
  await deadlineWorkspace.getByRole("button", { name: "View calculation provenance" }).click();
  const provenance = deadlineWorkspace.getByTestId(
    `ip-deadline-provenance-${seeded.deadlineId}`,
  );
  await expect(provenance).toContainText("Manual base date");
  await expect(provenance).toContainText("No approved extension is included");
  await expect(provenance).toContainText("calendar v1");
  await deadlineWorkspace.getByLabel("Backup").selectOption(seeded.backupMembershipId);
  await deadlineWorkspace.getByLabel("Internal target").fill("2026-08-16");

  for (const name of ["Calculate deadline proposal", "Confirm legal deadline"]) {
    const control = deadlineWorkspace.getByRole("button", { name });
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }

  await deadlineWorkspace.getByRole("button", { name: "Confirm legal deadline" }).click();
  await expect(page.getByText("Legal deadline workspace updated")).toBeVisible();
  await expect(deadlineWorkspace.getByText(/confirmed Â· v2/)).toBeVisible();

  const confirmedWorkspace = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${seeded.docketId}/deadline-workspace`,
    { headers: { Authorization: `Bearer ${ownerToken}` } },
  );
  expect(confirmedWorkspace.status(), await confirmedWorkspace.text()).toBe(200);
  const confirmedDeadline = (await confirmedWorkspace.json()).deadlines.find(
    (row: { id: string }) => row.id === seeded.deadlineId,
  );
  const calendarResponse = await api.get(
    `${apiBaseUrl}/api/calendar/events?from=2026-08-16&to=2026-08-18`,
    { headers: { Authorization: `Bearer ${ownerToken}` } },
  );
  expect(calendarResponse.status(), await calendarResponse.text()).toBe(200);
  const calendarEvents = (await calendarResponse.json()).events as Array<{
    id: string;
    display_type: string;
    ip_docket_id: string | null;
  }>;
  const filingEvent = calendarEvents.find(
    (event) => event.display_type === "filing_deadline",
  );
  const targetEvent = calendarEvents.find(
    (event) => event.display_type === "internal_target",
  );
  expect(filingEvent).toMatchObject({ ip_docket_id: seeded.docketId });
  expect(targetEvent).toMatchObject({ ip_docket_id: seeded.docketId });

  await page.goto("/app/calendar");
  await page.getByTestId("calendar-view-day").click();
  const now = new Date();
  const currentDay = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const filingDay = Date.UTC(2026, 7, 18);
  const filingOffset = Math.round((filingDay - currentDay) / 86_400_000);
  const direction = filingOffset < 0 ? "calendar-prev-month" : "calendar-next-month";
  for (let index = 0; index < Math.abs(filingOffset); index += 1) {
    await page.getByTestId(direction).click();
  }
  const filingLink = page.getByTestId(`calendar-event-${filingEvent!.id}`);
  await expect(filingLink).toContainText("Legal filing deadline");
  await expect(filingLink).toContainText("Respond to examination report");
  await expect(
    filingLink,
  ).toHaveAttribute("href", `/app/ip?docket=${seeded.docketId}`);
  await page.getByTestId("calendar-prev-month").click();
  await page.getByTestId("calendar-prev-month").click();
  const targetLink = page.getByTestId(`calendar-event-${targetEvent!.id}`);
  await expect(targetLink).toContainText("Internal target");
  await expect(targetLink).toContainText("Respond to examination report");
  await expect(targetLink).toHaveAttribute("href", `/app/ip?docket=${seeded.docketId}`);
  const operationalBypass = await api.patch(
    `${apiBaseUrl}/api/matters/${seeded.matterId}/deadlines/${confirmedDeadline.matter_deadline_id}`,
    {
      headers: { Authorization: `Bearer ${ownerToken}` },
      data: { status: "done" },
    },
  );
  const operationalBypassBody = await operationalBypass.json();
  expect(operationalBypass.status(), JSON.stringify(operationalBypassBody)).toBe(409);
  expect(operationalBypassBody.code).toBe("ip_deadline_workflow_required");
  await page.goto(`/app/ip?docket=${seeded.docketId}`);
  await page.getByRole("tab", { name: "Hearings and deadlines" }).click();
  await expect(page.getByTestId(`ip-legal-deadline-${seeded.deadlineId}`)).toContainText(
    "confirmed",
  );

  const refreshed = page.getByTestId("ip-deadline-workspace");
  await refreshed.getByLabel("Evidence reference").fill("receipt:official-response-filing");
  await refreshed
    .getByLabel("Completion attestation")
    .fill("Verified the official filing receipt and legal completion evidence.");
  await refreshed.getByRole("button", { name: "Complete with legal evidence" }).click();
  await expect(page.getByText("Legal deadline workspace updated")).toBeVisible();
  await expect(refreshed.getByText(/completed Â· v3/)).toBeVisible();

  const governance = page.getByTestId("ip-deadline-governance");
  for (const name of [
    "Propose calendar version",
    "Propose rule and fixture",
    "Preview impact and emergency-disable",
  ]) {
    const control = governance.getByRole("button", { name });
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  await api.dispose();
});
