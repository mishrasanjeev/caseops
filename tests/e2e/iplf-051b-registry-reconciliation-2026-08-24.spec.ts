/** IPLF-051B / UJ-07 / UJ-19: registry evidence and reviewed reconciliation. */

import { spawnSync } from "node:child_process";
import path from "node:path";

import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "RegistryReconcile2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_051_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True, 'ip_registry_sync': True}))",
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
      PYTHONPATH: [
        path.join(repoRoot, "apps", "api", "src"),
        process.env.PYTHONPATH,
      ]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function bootstrap(api: APIRequestContext) {
  const slug = `registry-reconcile-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 051 Registry Reconciliation LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Registry Reconciliation Partner",
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
  const configured = await api.put(
    `${apiBaseUrl}/api/ip/workspace/configuration`,
    {
      headers,
      data: {
        expected_version: null,
        enabled_asset_types: ["trademark"],
        jurisdictions: ["IN"],
        offices: ["Trade Marks Registry Delhi"],
        timezone: "Asia/Kolkata",
        holiday_calendar_key: "registry-reconciliation-calendar",
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
    },
  );
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

async function createApplication(
  api: APIRequestContext,
  headers: Record<string, string>,
) {
  const response = await api.post(
    `${apiBaseUrl}/api/ip/trademark-applications/manual`,
    {
      headers,
      data: {
        title: "ASTER REGISTRY MARK",
        restricted: false,
        asset_title: "ASTER REGISTRY MARK",
        jurisdiction: "IN",
        office: "Trade Marks Registry Delhi",
        filing_phase: "draft",
        source_pending_identifier_allocation: false,
        application_number: {
          raw_value: "TM-APP-051-2026",
          source: "e2e registry fixture",
          effective_from: "2026-08-24",
          is_primary: true,
        },
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: { text: "ASTER", evidence_reference: "e2e:aster-registry" },
          classes: [
            { class_number: 42, specification: "Legal software services" },
          ],
          use_priority: null,
          parties: [{ role: "applicant", name: "Aster Registry Limited" }],
          agent: null,
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: "e2e:aster-registry",
            },
          ],
        },
      },
    },
  );
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

test("IPLF-051 reconciles immutable registry evidence without claiming a provider call", async ({
  page,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(20_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = await enableWorkspace(api, tenant);
  const application = await createApplication(api, headers);

  const linked = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${application.docket.id}/registry-links`,
    {
      headers,
      data: {
        application_id: application.application.id,
        provider_key: "ipindia-registry",
        office: "Trade Marks Registry Delhi",
        jurisdiction: "IN",
        identifier_kind: "application",
        raw_identifier: "TM-APP-051-2026",
        source_url: "https://ipindia.gov.in/registry/TM-APP-051-2026",
        match_confidence: 0.98,
        match_evidence: {
          identifier: "TM-APP-051-2026",
          office: "Trade Marks Registry Delhi",
        },
        terms_version: null,
        capability_version: "manual-evidence-v1",
      },
    },
  );
  expect(linked.status(), await linked.text()).toBe(201);
  const link = await linked.json();
  const confirmed = await api.post(
    `${apiBaseUrl}/api/ip/registry-links/${link.id}/match-decision`,
    {
      headers,
      data: {
        expected_version: link.version,
        decision: "confirm",
        reason: "Application number, office and jurisdiction match the captured source.",
      },
    },
  );
  expect(confirmed.status(), await confirmed.text()).toBe(200);
  const confirmedLink = await confirmed.json();

  const snapshot = await api.post(
    `${apiBaseUrl}/api/ip/registry-links/${link.id}/snapshots/manual`,
    {
      headers,
      data: {
        expected_link_version: confirmedLink.version,
        idempotency_key: `iplf051-snapshot-${Date.now()}`,
        source_url: link.source_url,
        source_retrieved_at: "2026-08-24T12:00:00Z",
        parser_version: "e2e-manual-normalizer-v1",
        schema_version: 1,
        attribution: { publisher: "IP India", capture_method: "manual" },
        raw_snapshot: { status: "Registered", mark: "ASTER REGISTRY MARK" },
        normalized_snapshot: {
          office: "Trade Marks Registry Delhi",
          jurisdiction: "IN",
          status: "registered",
          mark_name: "ASTER REGISTRY MARK",
          renewal_date: "2036-08-24",
          parties: [{ name: "Aster Registry Limited", role: "proprietor" }],
        },
      },
    },
  );
  expect(snapshot.status(), await snapshot.text()).toBe(201);
  const snapshotResult = await snapshot.json();
  expect(snapshotResult.attempt.external_call).toBe(false);
  expect(snapshotResult.link.freshness_status).toBe("current");
  expect(snapshotResult.diffs).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ field_path: "/mark_name", change_kind: "added" }),
      expect.objectContaining({ field_path: "/status", change_kind: "changed" }),
      expect.objectContaining({
        field_path: "/renewal_date",
        deadline_recalculation_state: "required",
      }),
    ]),
  );

  await signIn(page, tenant.slug, tenant.email);
  await page.goto("/app/ip/registry");
  await expect(page.getByRole("heading", { name: "TM-APP-051-2026" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open source" })).toHaveAttribute(
    "href",
    link.source_url,
  );
  await expect(page.getByText("No external call")).toBeVisible();

  const markRow = page.getByRole("row").filter({ hasText: "/mark_name" });
  await expect(markRow).toContainText("added");
  await page
    .locator("#review-reason")
    .fill("The mark name is verified against the immutable registry capture.");
  const acceptedResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/ip/registry-diffs/") &&
      response.url().endsWith("/resolve") &&
      response.request().method() === "POST",
  );
  await markRow.getByRole("button", { name: "Accept" }).click();
  const accepted = await acceptedResponse;
  expect(accepted.status(), await accepted.text()).toBe(200);
  await expect(markRow).toContainText("accepted");
  await expect(markRow).toContainText("Event recorded");

  await page
    .getByLabel("Redactable operator detail")
    .fill("Authorization: Bearer registry-e2e-secret provider timeout");
  const failureResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/ip/registry-links/${link.id}/failures`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Record failure" }).click();
  const failure = await failureResponse;
  expect(failure.status(), await failure.text()).toBe(201);
  const failureResult = await failure.json();
  expect(failureResult.snapshot).toBeNull();
  expect(failureResult.link.last_snapshot_id).toBe(snapshotResult.snapshot.id);
  expect(JSON.stringify(failureResult)).not.toContain("registry-e2e-secret");
  await expect(page.getByText("failed", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("registry-e2e-secret")).toHaveCount(0);
  await api.dispose();
});
