/** IPLF-039F: the four UJ-52 cost paths through the real IP workspace.
 *
 * These four paths were closed in PR #283 with API and database proof but no
 * end-user proof, which under the repository's bug-fixing protocol caps the
 * slice at `Inconclusive` however green the unit tests are. This spec is that
 * missing half.
 *
 * It deliberately drives the browser rather than the API for the assertions
 * that matter, because two of the four defects were *user-visible* rather than
 * server-side:
 *
 *   UJ-52-EXC-01  the cost card replaced its whole form with "Cost items
 *                 require a linked Matter" whenever the record had no billing
 *                 Matter, so the surface whose job is preserving an
 *                 already-paid registry fee offered no way to record one. A
 *                 passing API test would not have caught that.
 *   UJ-52-EXC-05  a withheld rate must read as withheld. Rendering it as 0.00
 *                 is indistinguishable to the reader from a cost of nothing,
 *                 and only the rendered page can prove which one appears.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "CostEvidence2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_039f_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `cost-evidence-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 039F Cost Evidence LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Cost Finance Owner",
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

/** A docket with no billing Matter at all — the UJ-52-EXC-01 subject. */
async function createMatterlessDocket(api: APIRequestContext, headers: Record<string, string>) {
  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "UNBILLED CLEARANCE MARK",
      restricted: false,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "UNBILLED CLEARANCE", evidence_reference: "e2e:mark:039f" },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Unbilled Clearance Applicant LLP" }],
        agent: null,
        filing_manifest: [
          {
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "e2e:mark:039f",
          },
        ],
      },
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const body = await docket.json();
  expect(body.matter_id, "this path needs a docket with no billing owner").toBeNull();
  return body;
}

async function signIn(page: Page, slug: string, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-039F records a nonbillable cost on a record with no billing Matter", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  await createMatterlessDocket(api, headers);

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip");

  const costs = page.getByTestId("ip-cost-workspace");
  await expect(costs).toBeVisible();

  // UJ-52-EXC-01. The old surface replaced this whole form with a dead end.
  await expect(costs.getByText(/no Matter billing owner/i)).toBeVisible();
  const submit = costs.getByRole("button", { name: "Add nonbillable cost evidence" });
  await expect(submit).toBeVisible();

  await costs.getByLabel("Description").fill("Official filing fee paid before a billing Matter existed.");
  await costs.getByLabel(/^Amount/).fill("9000");
  await costs.getByLabel("Evidence reference").fill("receipt:registry-fee-unbilled-2026");
  await submit.click();

  // The fee is preserved, and reported as nonbillable rather than as awaiting
  // a billing link it can never receive.
  await expect(
    costs.getByText("Official filing fee paid before a billing Matter existed."),
  ).toBeVisible();
  // `exact` matters here: the card's explanatory copy and its submit button both
  // contain the word "nonbillable", so a loose match resolves to four elements
  // and proves nothing about the recorded row's status.
  await expect(costs.getByText("Nonbillable", { exact: true })).toBeVisible();

  await api.dispose();
});

test("IPLF-039F shows an estimate as an estimate and withholds a confidential rate", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const docket = await createMatterlessDocket(api, headers);

  // Two costs on one record: one ordinary, one whose rate is confidential.
  for (const cost of [
    {
      category: "official_fee",
      description: "Ordinary official fee, visible to everyone.",
      amount_minor: 900000,
      evidence_reference: "receipt:registry-fee-2026",
      billable: false,
      cost_nature: "actual",
      rate_confidential: false,
    },
    {
      category: "associate_fee",
      description: "Negotiated associate quote under a confidential arrangement.",
      amount_minor: 475000,
      evidence_reference: "attachment:confidential-fee-2026",
      billable: false,
      cost_nature: "estimate",
      rate_confidential: true,
    },
  ]) {
    const created = await api.post(
      `${apiBaseUrl}/api/ip/dockets/${docket.id}/cost-items`,
      { headers, data: { currency: "INR", ...cost } },
    );
    expect(created.status(), await created.text()).toBe(200);
  }

  // The owner holds ip:fees_manage and sees every amount.
  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip");
  const ownerCosts = page.getByTestId("ip-cost-workspace");
  await expect(ownerCosts).toBeVisible();
  await expect(ownerCosts.getByText("INR 9000.00")).toBeVisible();
  await expect(ownerCosts.getByText("INR 4750.00")).toBeVisible();
  // UJ-52-EXC-04: a quote is captured, and labelled as not an expense.
  await expect(ownerCosts.getByText(/Estimate — not an expense/)).toBeVisible();

  // A partner holds ip:fees_view but not ip:fees_manage.
  const partnerEmail = `partner-${tenant.slug}@example.com`;
  const invited = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers,
    data: {
      full_name: "Cost Reading Partner",
      email: partnerEmail,
      role: "partner",
      password: PASSWORD,
    },
  });
  expect(invited.status(), await invited.text()).toBe(200);

  const partnerContext = await browser.newContext();
  const partnerPage = await partnerContext.newPage();
  await signIn(partnerPage, tenant.slug, partnerEmail);
  await partnerPage.goto("/app/ip");
  const partnerCosts = partnerPage.getByTestId("ip-cost-workspace");
  await expect(partnerCosts).toBeVisible();

  // UJ-52-EXC-05. The non-confidential cost is unaffected...
  await expect(partnerCosts.getByText("INR 9000.00")).toBeVisible();
  // ...and the confidential one reads as withheld, never as a cost of nothing.
  await expect(
    partnerCosts.getByText(/Amount withheld — requires fee-management access/),
  ).toBeVisible();
  await expect(partnerCosts.getByText("INR 4750.00")).toHaveCount(0);
  await expect(partnerCosts.getByText("INR 0.00")).toHaveCount(0);
  // The existence of the cost is not the secret.
  await expect(
    partnerCosts.getByText("Negotiated associate quote under a confidential arrangement."),
  ).toBeVisible();

  await partnerContext.close();
  await api.dispose();
});
