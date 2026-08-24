/** IPLF-050: provider contracts, legal coverage, and fail-closed activation. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "ProviderContract2026!";

function grantIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_050_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True, 'ip_registry_sync': True}))",
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
  const slug = `provider-contract-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 050 Provider Contract LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Provider Contract Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test("IPLF-050 registers adapters and blocks unapproved registry calls", async ({ page }) => {
  test.setTimeout(180_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token}` };
  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      expected_version: null,
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["IP India"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "provider-contract-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "manual-only-v1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: tenant.membership.id,
      provider_keys: ["ipindia-registry"],
      provider_terms_version: "2026.1",
      accept_provider_terms: true,
    },
  });
  expect(configured.status(), await configured.text()).toBe(200);
  const configuration = await configured.json();
  expect(configuration.ready_for_manual_docketing).toBe(true);
  expect(configuration.provider_adapters).toEqual([
    expect.objectContaining({
      provider: "ipindia-registry",
      adapter_status: "blocked_pending_provider_contract",
      implemented_capabilities: [],
    }),
  ]);

  for (const testKind of ["connection", "source_open"]) {
    const probe = await api.post(`${apiBaseUrl}/api/ip/workspace/tests`, {
      headers,
      data: {
        expected_config_version: 1,
        test_kind: testKind,
        provider_key: "ipindia-registry",
      },
    });
    expect(probe.status(), await probe.text()).toBe(201);
    const result = await probe.json();
    expect(result.status).toBe("failed");
    expect(result.failure_code).toBe("provider_contract_not_approved");
    expect(result.details_json.external_call).toBe(false);
  }

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip");
  await expect(page.getByLabel("Permitted registry provider")).toHaveValue(
    "ipindia-registry",
  );
  await expect(page.getByTestId("ip-provider-contract")).toContainText(
    "blocked pending provider contract",
  );
  await expect(page.getByText(/unverified legal coverage/i)).toBeVisible();
  await expect(page.getByLabel("registry sync")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Enable manual workspace" })).toBeEnabled();

  await page.goto("/app/admin/provider-operations");
  await expect(page.getByTestId("readiness-ecourtsindia")).toContainText("court tracking");
  await expect(page.getByTestId("readiness-ipindia-registry")).toContainText(
    "external calls off",
  );
  await api.dispose();
});
