import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "AccessWorkflow2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_026b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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
  const slug = `access-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 026B Access Workflow LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Access Workflow Owner",
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

test("IPLF-026B previews, grants, and revokes independent IP access at 360px", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const ownerHeaders = { Authorization: `Bearer ${tenant.access_token as string}` };
  const suffix = Date.now();

  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers: ownerHeaders,
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
    headers: ownerHeaders,
    data: {
      expected_config_version: (await configured.json()).configuration.version,
      enabled_automations: [],
    },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);

  const member = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers: ownerHeaders,
    data: {
      full_name: "IP Access Reviewer",
      email: `ip-access-reviewer-${suffix}@example.com`,
      role: "admin",
      password: PASSWORD,
    },
  });
  expect(member.status(), await member.text()).toBe(200);
  const membershipId = (await member.json()).membership_id as string;
  const memberApi = await request.newContext();
  const memberLogin = await memberApi.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: tenant.slug,
      email: `ip-access-reviewer-${suffix}@example.com`,
      password: PASSWORD,
    },
  });
  expect(memberLogin.status(), await memberLogin.text()).toBe(200);
  const memberHeaders = {
    Authorization: `Bearer ${(await memberLogin.json()).access_token as string}`,
  };

  const matter = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: ownerHeaders,
    data: {
      title: "Independent linked Matter",
      matter_code: `IPLF-026B-${suffix}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
      status: "active",
    },
  });
  expect(matter.status(), await matter.text()).toBe(200);
  const matterId = (await matter.json()).id as string;
  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers: ownerHeaders,
    data: {
      title: "Restricted independent IP access",
      primary_identifier: `TM-ACCESS-${suffix}`,
      matter_id: matterId,
      restricted: true,
      particulars: {
        form_key: "TM-A",
        form_version: "2026.1",
        mark_kind: "word",
        representation: { text: "ACCESS WORKFLOW" },
        classes: [{ class_number: 42, specification: "Legal workflow software" }],
        parties: [{ role: "applicant", name: "Access Workflow LLP" }],
        filing_manifest: [
          {
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "fixture:iplf-026b",
          },
        ],
      },
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const docketId = (await docket.json()).id as string;
  const restrictedMatter = await api.post(
    `${apiBaseUrl}/api/matters/${matterId}/access/restricted`,
    { headers: ownerHeaders, data: { restricted: true } },
  );
  expect(restrictedMatter.status(), await restrictedMatter.text()).toBe(200);
  expect(
    (await memberApi.get(`${apiBaseUrl}/api/ip/dockets/${docketId}`, { headers: memberHeaders })).status(),
  ).toBe(404);

  await page.setViewportSize({ width: 360, height: 820 });
  await signIn(page, tenant.slug as string, tenant.email as string);
  await page.goto(`/app/ip?docket=${encodeURIComponent(docketId)}`);
  const workspace = page.getByTestId("ip-access-workspace");
  await expect(workspace).toBeVisible();
  await expect(workspace.getByRole("heading", { name: "Internal access and ethical walls" })).toBeVisible();
  await expect(workspace.getByText(/Linked Matter permissions are never copied/i)).toBeVisible();
  await expect(workspace.getByRole("button", { name: "Preview grant" })).toBeVisible();
  await expect(workspace.getByRole("button", { name: "Preview default access" })).toBeVisible();

  await workspace.getByLabel("Reason for change").fill("Assigned for privileged IP review.");
  await workspace.getByLabel("Person or team").selectOption(membershipId);
  await workspace.getByRole("button", { name: "Preview grant" }).click();
  const preview = workspace.getByTestId("ip-access-preview");
  await expect(preview).toContainText("Gains: 1");
  await expect(preview).toContainText("this change never copies permissions");
  await expect(preview.getByRole("button", { name: "Apply access change" })).toBeVisible();
  await preview.getByRole("button", { name: "Apply access change" }).click();
  await expect(workspace.getByText("v2", { exact: true })).toBeVisible();

  expect(
    (await memberApi.get(`${apiBaseUrl}/api/ip/dockets/${docketId}`, { headers: memberHeaders })).status(),
  ).toBe(200);
  expect(
    (await memberApi.get(`${apiBaseUrl}/api/matters/${matterId}`, { headers: memberHeaders })).status(),
  ).toBe(404);

  await workspace.getByLabel("Reason for change").fill("The review assignment has now ended.");
  await workspace
    .getByRole("button", { name: "Preview revoke access for IP Access Reviewer" })
    .click();
  await expect(preview).toContainText("Losses: 1");
  await preview.getByRole("button", { name: "Apply access change" }).click();
  await expect(workspace.getByText("v3", { exact: true })).toBeVisible();
  await expect(workspace.getByText("Revoked")).toBeVisible();
  expect(
    (await memberApi.get(`${apiBaseUrl}/api/ip/dockets/${docketId}`, { headers: memberHeaders })).status(),
  ).toBe(404);
  const hiddenList = await memberApi.get(`${apiBaseUrl}/api/ip/dockets`, { headers: memberHeaders });
  expect(hiddenList.status(), await hiddenList.text()).toBe(200);
  expect((await hiddenList.json()).count).toBe(0);

  const panel = await api.get(`${apiBaseUrl}/api/ip/dockets/${docketId}/access`, {
    headers: ownerHeaders,
  });
  expect(panel.status(), await panel.text()).toBe(200);
  const panelBody = await panel.json();
  expect(panelBody.excluded_persistence).toEqual([
    "portal_grants",
    "access_review_campaigns",
    "emergency_access_sessions",
  ]);
  const creatorGrant = panelBody.grants.find(
    (row: { subject_id: string; revoked_at: string | null }) =>
      row.subject_id === tenant.membership.id && row.revoked_at === null,
  );
  const selfLockout = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docketId}/access/preview`,
    {
      headers: ownerHeaders,
      data: {
        action: "revoke_grant",
        expected_access_policy_version: 3,
        reason: "Attempt to remove final owner access.",
        grant_id: creatorGrant.id,
      },
    },
  );
  expect(selfLockout.status()).toBe(409);

  const otherSlug = `other-access-${suffix}`;
  const otherApi = await request.newContext();
  const other = await otherApi.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Other Access Company",
      company_slug: otherSlug,
      company_type: "law_firm",
      owner_full_name: "Other Owner",
      owner_email: `owner-${otherSlug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(other.status(), await other.text()).toBe(200);
  const crossCompany = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docketId}/access/preview`,
    {
      headers: ownerHeaders,
      data: {
        action: "grant",
        expected_access_policy_version: 3,
        reason: "Cross-company subjects must fail closed.",
        subject_type: "membership",
        subject_id: (await other.json()).membership.id,
      },
    },
  );
  expect(crossCompany.status()).toBe(400);

  await otherApi.dispose();
  await memberApi.dispose();
  await api.dispose();
});
