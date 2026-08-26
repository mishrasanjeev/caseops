/** IPLF-033B: application families and prosecution exception workflows. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "ProsecutionFamilies2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_033b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `prosecution-families-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 033B Prosecution LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Prosecution Partner",
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
      jurisdictions: ["IN", "GB"],
      offices: ["IP India", "UKIPO"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "prosecution-family-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "2026.1", GB: "2026.1" },
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
): Promise<string> {
  const response = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: {
      title: `Aster prosecution ${code}`,
      matter_code: code,
      client_name: "Legacy name must not split canonical client",
      practice_area: "intellectual_property",
      forum_level: "tribunal",
      status: "active",
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()).id as string;
}

async function createDocketApplications(
  api: APIRequestContext,
  headers: Record<string, string>,
  matterId: string,
  suffix: string,
  applicationNumbers: string[],
) {
  const docketResponse = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: `ASTER FAMILY ${suffix}`,
      matter_id: matterId,
      restricted: false,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ASTER FAMILY", evidence_reference: `e2e:aster:${suffix}` },
        classes: [{ class_number: 42, specification: "Legal technology services" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Holdings Private Limited" }],
        agent: { name: "CaseOps IP Counsel" },
        filing_manifest: [],
      },
    },
  });
  expect(docketResponse.status(), await docketResponse.text()).toBe(201);
  const docket = await docketResponse.json();
  const assetResponse = await api.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/assets`, {
    headers,
    data: { asset_kind: "trademark", jurisdiction: "IN", title: `ASTER FAMILY ${suffix}` },
  });
  expect(assetResponse.status(), await assetResponse.text()).toBe(201);
  const asset = await assetResponse.json();
  const applications = [];
  for (const [index, rawValue] of applicationNumbers.entries()) {
    const response = await api.post(`${apiBaseUrl}/api/ip/dockets/${docket.id}/applications`, {
      headers,
      data: {
        asset_id: asset.id,
        office: index === 0 ? "IP India" : "UKIPO",
        jurisdiction: index === 0 ? "IN" : "GB",
        filing_phase: "draft",
        application_number: {
          raw_value: rawValue,
          source: "e2e_registry_fixture",
          effective_from: "2026-08-22",
          is_primary: true,
        },
      },
    });
    expect(response.status(), await response.text()).toBe(201);
    applications.push((await response.json()).application);
  }
  return { docket, applications };
}

function eventPayload(
  membershipId: string,
  application: { id: string; version: number },
  lifecycleVersion: number,
  overrides: Record<string, unknown> = {},
) {
  return {
    expected_lifecycle_version: lifecycleVersion,
    expected_application_version: application.version,
    application_id: application.id,
    proceeding_id: null,
    event_kind: "response",
    source: "manual",
    source_reference: null,
    effective_at: "2026-08-21T10:00:00Z",
    responsible_membership_id: membershipId,
    reason: "Recorded from controlled prosecution evidence.",
    evidence_refs: ["attachment:e2e-evidence"],
    document_refs: ["attachment:e2e-document"],
    resulting_deadline_refs: [],
    candidate_status: "confirmed",
    acknowledged_exception_codes: [],
    payload: {},
    ...overrides,
  };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-033B completes family and prosecution exception journeys", async ({ page }) => {
  test.setTimeout(240_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);

  const clientResponse = await api.post(`${apiBaseUrl}/api/clients/`, {
    headers,
    data: { name: "Aster Holdings", client_type: "corporate" },
  });
  expect(clientResponse.status(), await clientResponse.text()).toBe(200);
  const clientId = (await clientResponse.json()).id as string;
  const firstMatter = await createMatter(api, headers, `IP033B-${Date.now()}-1`);
  const secondMatter = await createMatter(api, headers, `IP033B-${Date.now()}-2`);
  for (const matterId of [firstMatter, secondMatter]) {
    const assignment = await api.post(`${apiBaseUrl}/api/matters/${matterId}/clients`, {
      headers,
      data: { client_id: clientId, role: "proprietor", is_primary: true },
    });
    expect(assignment.status(), await assignment.text()).toBe(200);
  }

  const first = await createDocketApplications(
    api,
    headers,
    firstMatter,
    "GLOBAL",
    ["TM / 2026 / 03301", "UK / 2026 / 03302"],
  );
  await createDocketApplications(
    api,
    headers,
    secondMatter,
    "INDIA",
    ["TM / 2026 / 03303"],
  );
  const original = await api.post(`${apiBaseUrl}/api/ip/dockets/${first.docket.id}/events`, {
    headers,
    data: eventPayload(tenant.membership.id, first.applications[0], 0),
  });
  expect(original.status(), await original.text()).toBe(201);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip/portfolio");
  await page.getByRole("button", { name: "Family view" }).click();
  await expect(page.getByRole("heading", { name: "ASTER FAMILY GLOBAL" })).toBeVisible();
  await expect(page.getByText("2 applications")).toBeVisible();
  await expect(page.getByText("TM / 2026 / 03301", { exact: true })).toBeVisible();
  await expect(page.getByText("UK / 2026 / 03302", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Client families" }).click();
  await expect(page.getByRole("heading", { name: "Aster Holdings" })).toBeVisible();
  await expect(page.getByText("3 applications")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("TM / 2026 / 03303", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.goto(`/app/ip?docket=${first.docket.id}`);
  const prosecution = page.getByTestId("ip-prosecution-workspace");
  await expect(prosecution.getByText("response filed", { exact: true })).toBeVisible();
  await prosecution.getByLabel("Application").selectOption(first.applications[0].id);
  await prosecution.getByLabel("Event type").selectOption("examination_report");
  await prosecution.getByLabel("Effective date and time").fill("2026-08-20T10:00");
  await prosecution.getByLabel("Reason").fill("Backdated registry examination report reviewed.");
  await prosecution.getByLabel("Correspondence direction").selectOption("inward");
  await prosecution.getByLabel("Received at").fill("2026-08-20T09:00");
  await prosecution.getByLabel("Due at").fill("2026-09-20T09:00");
  await prosecution.getByRole("button", { name: "Preview prosecution event" }).click();
  await expect(prosecution.getByText("Backdated recalculation: required")).toBeVisible();
  const recordButton = prosecution.getByRole("button", { name: "Record prosecution event" });
  await expect(recordButton).toBeDisabled();
  await prosecution
    .getByRole("checkbox", { name: /reviewed the recalculation preview/i })
    .check();
  const backdatedResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/api/ip/dockets/${first.docket.id}/events`) &&
    response.request().method() === "POST",
  );
  await recordButton.click();
  expect((await backdatedResponse).status()).toBe(201);
  await expect(prosecution.getByText("inward correspondence")).toBeVisible();
  await expect(prosecution.getByText("response filed", { exact: true })).toBeVisible();

  const currentWorkspace = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${first.docket.id}/prosecution`,
    { headers },
  );
  expect(currentWorkspace.status(), await currentWorkspace.text()).toBe(200);
  const currentCore = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${first.docket.id}/core-records`,
    { headers },
  );
  expect(currentCore.status(), await currentCore.text()).toBe(200);
  const currentApplication = (await currentCore.json()).applications.find(
    (application: { id: string }) => application.id === first.applications[0].id,
  ) as { id: string; version: number };
  const candidate = await api.post(`${apiBaseUrl}/api/ip/dockets/${first.docket.id}/events`, {
    headers,
    data: eventPayload(
      tenant.membership.id,
      currentApplication,
      (await currentWorkspace.json()).lifecycle_version as number,
      {
        event_kind: "acceptance",
        source: "registry",
        source_reference: "ipindia:e2e-candidate-033b",
        effective_at: "2026-08-21T11:00:00Z",
        reason: null,
        candidate_status: "candidate",
      },
    ),
  });
  expect(candidate.status(), await candidate.text()).toBe(201);
  await page.reload();
  await prosecution.getByRole("button", { name: "Reconcile candidate" }).click();
  await expect(prosecution.getByText(/Reconciliation will append a decision/)).toBeVisible();
  await prosecution.getByLabel("Reconciliation decision").selectOption("same_fact");
  await prosecution.getByRole("button", { name: "Preview prosecution event" }).click();
  const reconcileButton = prosecution.getByRole("button", { name: "Record prosecution event" });
  await expect(reconcileButton).toBeEnabled();
  await reconcileButton.click();
  await expect(prosecution.getByText(/same fact · reconciles/)).toBeVisible();

  const workspace = await api.get(
    `${apiBaseUrl}/api/ip/dockets/${first.docket.id}/prosecution`,
    { headers },
  );
  expect(workspace.status(), await workspace.text()).toBe(200);
  const body = await workspace.json();
  expect(body.current_phase).toBe("accepted");
  expect(body.events.some((event: { payload_json: Record<string, unknown> }) =>
    event.payload_json.recalculation_preserved_current_phase === true)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
