/** IPLF-039D: complete UJ-58 incident review through the real IP workspace. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "IncidentReview2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_039d_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `incident-review-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 039D Incident Review LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Incident Risk Partner",
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
      holiday_calendar_key: "test-calendar",
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

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-039D opens, assesses, communicates and resolves an incident", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "INCIDENT CONTROL MARK",
      restricted: true,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "INCIDENT CONTROL", evidence_reference: "e2e:mark:1" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Incident Control Applicant LLP" }],
        agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:mark:1" }],
      },
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip");
  const workspace = page.getByTestId("ip-incident-workspace");
  await expect(workspace).toBeVisible();
  await workspace.getByLabel("Incident summary").fill("Suspected missed opposition response deadline.");
  await workspace.getByLabel("Defect fingerprint").fill("opposition-rule-v7-source-v2");
  await workspace.getByLabel("Source evidence reference").fill("registry:event:opaque-17");
  await workspace.getByRole("button", { name: "Open incident" }).click();
  await expect(workspace.getByText("open", { exact: true })).toBeVisible();

  for (const actionType of ["containment", "corrective_task", "prevention"] as const) {
    const actionReference = workspace.getByLabel("Action reference", { exact: true });
    const actionButton = workspace.getByRole("button", { name: "Record action" });
    await workspace.getByRole("combobox", { name: /^Action/ }).first().selectOption(actionType);
    await actionReference.fill(`task:${actionType}:1`);
    await workspace.getByLabel("Evidence reference", { exact: true }).fill(`evidence:${actionType}:1`);
    await workspace.getByLabel("Action details", { exact: true }).fill(`Risk partner completed ${actionType}.`);
    await expect(actionButton).toBeEnabled();
    const responsePromise = page.waitForResponse((response) =>
      response.url().endsWith("/actions") && response.request().method() === "POST",
    );
    await actionButton.click();
    const response = await responsePromise;
    expect(response.status(), await response.text()).toBe(200);
    await expect(actionReference).toHaveValue("");
  }

  await workspace.getByRole("button", { name: "Impact" }).click();
  await workspace.getByLabel("Record reference").fill("TM-1234567");
  await workspace.getByLabel("Relationship").fill("same rule and source version");
  await workspace.getByRole("combobox", { name: /^Assessment/ }).selectOption("affected");
  await workspace.getByLabel("Scan method").fill("defect fingerprint scan");
  await workspace.getByLabel("Scan evidence").fill("scan:2026-08-21:1");
  await workspace.getByLabel("Complete impact scan").check();
  await workspace.getByRole("button", { name: "Record impact" }).click();

  await workspace.getByRole("button", { name: "Recipients" }).click();
  const recipientMetric = workspace.getByText("Recipient decisions").locator("..");
  for (const [index, recipient] of ["client", "insurer", "regulator", "court"].entries()) {
    await workspace.getByRole("combobox", { name: /^Recipient/ }).selectOption(recipient);
    await workspace.getByLabel("Private recipient reference").fill(`${recipient}:opaque-1`);
    await workspace.getByRole("combobox", { name: /^Decision/ }).selectOption("not_applicable");
    await workspace.getByLabel("Approval evidence").fill(`approval:${recipient}:1`);
    await workspace.getByLabel("Decision rationale").fill("Risk partner approved no communication.");
    await workspace.getByRole("button", { name: "Record recipient decision" }).click();
    await expect(recipientMetric.getByText(String(index + 1), { exact: true })).toBeVisible();
  }

  await workspace.getByRole("button", { name: "Resolution" }).click();
  await workspace.getByLabel("Resolution evidence").fill("resolution:verified:1");
  await workspace.getByLabel("Corrective action").fill("Corrective filing was completed and reviewed.");
  await workspace.getByLabel("Root cause").fill("A rule-version mismatch caused the calculation error.");
  await workspace.getByLabel("Preventive action").fill("Regression checks now pin every rule and source version.");
  await workspace.getByRole("button", { name: "Resolve incident" }).click();
  await expect(workspace.getByText("verified", { exact: true })).toBeVisible();

  await api.dispose();
});
