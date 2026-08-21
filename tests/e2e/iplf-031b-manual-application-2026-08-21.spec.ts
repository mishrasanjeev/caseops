/** IPLF-031B: atomic manual application creation and duplicate resolution. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "ManualApplication2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_031b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `manual-application-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 031B Manual Filing LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Docketing Partner",
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
      offices: ["IP India"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "manual-application-calendar",
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

function manualPayload(title: string) {
  return {
    title,
    restricted: false,
    asset_title: title,
    jurisdiction: "IN",
    office: "IP India",
    filing_phase: "draft",
    source_pending_identifier_allocation: false,
    application_number: {
      raw_value: "TM / 2026 / 00421",
      source: "e2e_registry_fixture",
      effective_from: "2026-08-21",
      is_primary: true,
    },
    particulars: {
      form_key: "TM-A",
      form_version: "2026.1",
      mark_kind: "word",
      representation: { text: title, evidence_reference: "e2e:mark" },
      classes: [{ class_number: 9, specification: "Downloadable legal software" }],
      use_priority: null,
      parties: [{ role: "applicant", name: "Aster Products Private Limited" }],
      agent: null,
      filing_manifest: [{
        key: "representation",
        label: "Mark representation",
        required: true,
        evidence_reference: "e2e:mark",
      }],
    },
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

test("IPLF-031B completes manual identity and duplicate exception paths", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const original = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: manualPayload("ASTER ORIGINAL"),
  });
  expect(original.status(), await original.text()).toBe(201);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip");
  await page.getByRole("button", { name: "New trademark" }).click();
  const creationForm = page.locator("form").filter({ has: page.getByLabel("Docket title") });
  await creationForm.getByLabel("Docket title").fill("ASTER SEPARATE FILING");
  await creationForm.getByLabel("Word mark").fill("ASTER");
  await creationForm.getByLabel("Goods / services specification").fill("Downloadable legal software");
  await creationForm.getByLabel("Applicant").fill("Aster Products Private Limited");
  await creationForm.getByLabel("Representation evidence reference").fill("e2e:aster-separate");
  await creationForm.getByLabel("Filing phase").selectOption("filed");
  await expect(creationForm.getByRole("button", { name: "Create application" })).toBeDisabled();
  await expect(
    creationForm.getByRole("checkbox", { name: /number is still pending allocation/i }),
  ).toBeVisible();
  await creationForm
    .getByLabel("Application number (optional before filing)")
    .fill("TM / 2026 / 00421");
  await creationForm.getByLabel("Filing phase").selectOption("draft");

  const createResponse = page.waitForResponse((response) =>
    response.url().includes("/api/ip/trademark-applications/manual") &&
    response.request().method() === "POST",
  );
  await creationForm.getByRole("button", { name: "Create application" }).click();
  const createdResponse = await createResponse;
  expect(createdResponse.status()).toBe(201);
  const created = await createdResponse.json();

  const identity = page.getByTestId("ip-identity-workspace");
  await expect(identity.getByText("Application no.")).toBeVisible();
  const repeatedApplicationNumber = identity.getByText("TM / 2026 / 00421", { exact: true });
  await expect(repeatedApplicationNumber).toHaveCount(2);
  await expect(repeatedApplicationNumber.first()).toBeVisible();
  await expect(identity.getByText("ASTER ORIGINAL")).toBeVisible();
  await identity.getByLabel("Decision reason").fill("Registry evidence confirms a separate application.");
  await identity.getByRole("button", { name: "Confirm separate filing" }).click();
  await expect(identity.getByText("confirmed")).toBeVisible();
  await identity.getByLabel("Filing phase").selectOption("filed");
  await identity.getByRole("button", { name: "Update phase" }).click();

  const proceeding = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${created.docket.id}/proceedings`,
    {
      headers,
      data: {
        application_id: created.application.id,
        proceeding_kind: "opposition",
        side: "applicant",
        office: "IP India",
        jurisdiction: "IN",
        stage: "evidence",
      },
    },
  );
  expect(proceeding.status(), await proceeding.text()).toBe(201);
  const opposition = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${created.docket.id}/identifiers`,
    {
      headers,
      data: {
        identifier_kind: "opposition",
        raw_value: "OPP / 88 / 2026",
        office: "IP India",
        jurisdiction: "IN",
        source: "e2e_registry_fixture",
        effective_from: "2026-08-21",
        is_primary: true,
        proceeding_id: (await proceeding.json()).id,
      },
    },
  );
  expect(opposition.status(), await opposition.text()).toBe(201);

  await page.goto(`/app/ip?docket=${created.docket.id}`);
  await expect(page.getByTestId("ip-identity-workspace").getByText("Opposition no.")).toBeVisible();
  await expect(page.getByTestId("ip-identity-workspace").getByText("OPP / 88 / 2026")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("ip-identity-workspace")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await api.dispose();
});
