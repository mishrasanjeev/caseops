/** IPLF-055 / UJ-27: explicit IP grants, reviewed reports, instructions, and revocation. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "ClientPortal2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.platform === "win32"
    ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
    : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_055_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `client-portal-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 055 Client Portal LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Client Portal Partner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const tenant = await response.json();
  grantIpEntitlement(tenant.company.id as string);
  return { ...tenant, slug, email };
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
      holiday_calendar_key: "client-portal-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "lawyer-reviewed-manual-only-v1" },
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

async function createApplication(api: APIRequestContext, headers: Record<string, string>) {
  const response = await api.post(`${apiBaseUrl}/api/ip/trademark-applications/manual`, {
    headers,
    data: {
      title: "ASTER CLIENT PORTAL",
      restricted: false,
      asset_title: "ASTER CLIENT PORTAL",
      jurisdiction: "IN",
      office: "Trade Marks Registry Delhi",
      filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: {
        raw_value: "TM-APP-055-2026",
        source: "IPLF-055 dated browser fixture",
        effective_from: "2026-08-25",
        is_primary: true,
      },
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ASTER", evidence_reference: "e2e:iplf-055" },
        classes: [{ class_number: 42, specification: "Legal software as a service" }],
        use_priority: null,
        parties: [{ role: "applicant", name: "Aster Client Limited" }],
        agent: null,
        filing_manifest: [{
          key: "representation",
          label: "Mark representation",
          required: true,
          evidence_reference: "e2e:iplf-055",
        }],
      },
    },
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

test("IPLF-055 completes UJ-27 grant, report, instruction, acknowledgement, and revoke", async ({ page }) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  await enableWorkspace(api, tenant);
  const created = await createApplication(api, {
    Authorization: `Bearer ${tenant.access_token}`,
  });
  const docketId = created.docket.id as string;
  const clientEmail = `client-${tenant.slug}@example.com`;

  await signIn(page, tenant.slug, tenant.email);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app/ip/client-portal");
  await expect(page.getByRole("heading", { name: "Client portal" })).toBeVisible();
  for (const selector of [
    "#ip-client-name",
    "#ip-client-email",
    "#ip-client-docket",
    "#ip-client-expiry",
    "#ip-client-categories",
  ]) {
    const control = page.locator(selector);
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByLabel("Client name").fill("Aster Client Contact");
  await page.getByLabel("Work email").fill(clientEmail);
  await page.locator("#ip-client-docket").selectOption(docketId);
  await page.getByLabel("Access expires").fill("2026-09-25T10:00");
  const invitationResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/admin/portal/invitations")
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Grant access" }).click();
  const invitationResult = await invitationResponse;
  expect(invitationResult.status(), await invitationResult.text()).toBe(201);
  const invitation = await invitationResult.json();
  expect(invitation.debug_token).toBeTruthy();
  await expect(
    page.getByRole("paragraph").filter({ hasText: "Aster Client Contact · ASTER CLIENT PORTAL" }),
  ).toBeVisible();

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/app/ip/reports");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByTestId("ip-report-result")).toContainText("TM-APP-055-2026");
  await page.locator("#report-client").selectOption(invitation.portal_user.id);
  await page.getByRole("checkbox", { name: "ASTER CLIENT PORTAL" }).check();
  await page.locator("#report-client-title").fill("Aster portfolio status update");
  const publicationResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/ip/portal/report-publications")
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Publish" }).click();
  const publicationResult = await publicationResponse;
  expect(publicationResult.status(), await publicationResult.text()).toBe(201);
  const publication = await publicationResult.json();

  const verified = await page.request.post(`${apiBaseUrl}/api/portal/auth/verify-link`, {
    data: { token: invitation.debug_token },
  });
  expect(verified.status(), await verified.text()).toBe(200);
  await page.goto("/portal");
  await expect(page.getByTestId(`portal-ip-${docketId}`)).toContainText("TM-APP-055-2026");
  await page.goto(`/portal/ip/${docketId}`);
  await expect(page.getByRole("heading", { name: "ASTER CLIENT PORTAL" })).toBeVisible();
  await expect(page.getByText("TM-APP-055-2026").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Aster portfolio status update" })).toBeVisible();
  await expect(page.getByText(/provenance|source_refs/)).toHaveCount(0);

  await page.getByLabel("Approved publication").selectOption(publication.id);
  await page.getByLabel("Instruction type").selectOption("renewal");
  await expect(page.getByLabel("Decision")).toHaveValue("renew");
  await page.getByLabel("Instruction type").selectOption("proceeding");
  await expect(page.getByLabel("Decision")).toHaveValue("proceed");
  await page.getByLabel("Instruction details").fill("Please proceed after confirming the current registry record.");
  const instructionResponse = page.waitForResponse(
    (response) => response.url().includes(`/api/portal/publications/${publication.id}/instructions`)
      && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send for firm acknowledgement" }).click();
  const instructionResult = await instructionResponse;
  expect(instructionResult.status(), await instructionResult.text()).toBe(201);

  await page.goto("/app/ip/client-portal");
  await expect(page.getByText("Please proceed after confirming the current registry record.")).toBeVisible();
  await page.getByLabel("Acknowledgement reason for ASTER CLIENT PORTAL").fill(
    "Current proceeding and registry evidence reviewed by the firm.",
  );
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByText("accepted", { exact: true })).toBeVisible();

  await page.getByLabel("Revocation reason for Aster Client Contact").fill("Client access scope completed.");
  await page.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
  await page.goto("/portal/ip/" + docketId);
  await page.waitForURL(/\/portal\/sign-in$/);
  await expect(page.getByRole("heading", { name: /sign in to your workspace portal/i })).toBeVisible();

  await api.dispose();
});
