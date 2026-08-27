import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "IpDocketProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

function grantSyntheticIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session = get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'], status='manual_active', segment='law_firm', source='playwright_fixture', externally_billable=False, entitlement_overrides_json={'ip_workspace': True}))",
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
  expect(
    result.status,
    `Could not grant the synthetic IP entitlement.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
  ).toBe(0);
}

async function configureSyntheticIpWorkspace(
  api: APIRequestContext,
  token: string,
  membershipId: string,
): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` };
  const configuration = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["IP India"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "test-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { "IN-TM": "2026.1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: membershipId,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  expect(configuration.status(), await configuration.text()).toBe(200);

  const enablement = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: { expected_config_version: 1, enabled_automations: [] },
  });
  expect(enablement.status(), await enablement.text()).toBe(200);
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<{ token: string; membershipId: string }> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IP Docket Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "IP Proof Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  const body = await response.json();
  grantSyntheticIpEntitlement(body.company.id as string);
  const token = body.access_token as string;
  const membershipId = body.membership.id as string;
  await configureSyntheticIpWorkspace(api, token, membershipId);
  return { token, membershipId };
}

async function seedLinkedIpDocket(api: APIRequestContext, token: string, membershipId: string): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` };
  const matterResponse = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers,
    data: { title: "IP operations Matter", matter_code: unique("IP-E2E").toUpperCase(), practice_area: "intellectual_property", forum_level: "tribunal", status: "intake" },
  });
  expect(matterResponse.status()).toBe(200);
  const matterId = (await matterResponse.json()).id as string;
  const communication = await api.post(`${apiBaseUrl}/api/matters/${matterId}/communications`, {
    headers,
    data: { direction: "inbound", channel: "email", subject: "Client filing instruction", body: "Proceed with the registry response." },
  });
  expect(communication.status()).toBe(200);
  const deadline = await api.post(`${apiBaseUrl}/api/matters/${matterId}/deadlines`, {
    headers,
    data: { source: "custom", kind: "filing", title: "Registry response", due_on: "2026-09-30", assignee_membership_id: membershipId },
  });
  expect(deadline.status()).toBe(200);
  const deadlineId = (await deadline.json()).id as string;
  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers,
    data: {
      title: "ORBIT linked mark", matter_id: matterId, primary_identifier: unique("TM-LINKED"),
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "ORBIT", evidence_reference: "attachment:orbit-mark" },
        classes: [{ class_number: 42, specification: "Legal software services" }],
        use_priority: null, parties: [{ role: "applicant", name: "Orbit Legal LLP" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "attachment:orbit-mark" }],
      },
    },
  });
  expect(docket.status()).toBe(201);
  const docketId = (await docket.json()).id as string;
  const asset = await api.post(`${apiBaseUrl}/api/ip/dockets/${docketId}/assets`, {
    headers,
    data: { asset_kind: "trademark", jurisdiction: "IN", title: "ORBIT" },
  });
  expect(asset.status()).toBe(201);
  const assetId = (await asset.json()).id as string;
  const application = await api.post(`${apiBaseUrl}/api/ip/dockets/${docketId}/applications`, {
    headers,
    data: {
      asset_id: assetId, office: "IP India", jurisdiction: "IN", filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: { raw_value: unique("TM-E2E"), source: "manual_e2e", effective_from: "2026-08-07", is_primary: true },
    },
  });
  expect(application.status()).toBe(201);
  const coverage = await api.post(`${apiBaseUrl}/api/ip/dockets/${docketId}/deadline-coverages`, {
    headers,
    data: { matter_deadline_id: deadlineId, responsible_membership_id: membershipId, coverage_status: "accepted" },
  });
  expect(coverage.status()).toBe(200);
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe("Ram 2026-08-01 IP law firm slices", () => {
  test.setTimeout(120_000);

  test("IP docket creates a validated trademark and keeps every grouped action visible at 360px", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ip-proof");
    await bootstrap(api, slug);
    await signIn(page, slug);

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/ip");
    await expect(page.getByRole("heading", { name: "Trademark docket" })).toBeVisible();

    const create = page.getByRole("button", { name: "New trademark" });
    await expect(create).toBeVisible();
    const createBox = await create.boundingBox();
    expect(createBox).not.toBeNull();
    expect(createBox!.x).toBeGreaterThanOrEqual(0);
    expect(createBox!.x + createBox!.width).toBeLessThanOrEqual(360);
    await create.click();

    const creationForm = page.locator("form").filter({ has: page.getByLabel("Docket title") });
    await creationForm.getByLabel("Docket title").fill("ASTER mobile mark");
    await creationForm.getByLabel("Word mark").fill("ASTER");
    await creationForm.getByLabel("Nice class").fill("42");
    await creationForm.getByLabel("Goods / services specification").fill("Legal software services");
    await creationForm.getByLabel("Applicant").fill("Aster Legal LLP");
    await creationForm
      .getByLabel("Representation evidence reference")
      .fill("attachment:mobile-mark-proof");
    await creationForm
      .getByLabel("Application number (optional before filing)")
      .fill("TM-MOBILE-001");
    const submit = creationForm.getByRole("button", { name: "Create application" });
    await expect(submit).toBeVisible();
    const submitBox = await submit.boundingBox();
    expect(submitBox).not.toBeNull();
    expect(submitBox!.x + submitBox!.width).toBeLessThanOrEqual(360);
    await submit.click();

    await expect(
      page.getByRole("heading", { name: "ASTER mobile mark", exact: true }),
    ).toBeVisible();
    const workspace = page.getByTestId("ip-docket-workspace");
    await expect(workspace).toBeVisible();
    await expect(workspace.getByText("Readiness")).toBeVisible();
    await expect(workspace.getByText("Operational links")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add ownership evidence" })).toBeVisible();
    for (const name of ["Preview lifecycle impact", "Apply lifecycle transition"]) {
      const control = page.getByRole("button", { name });
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }
    await page.getByRole("tab", { name: "Proceedings" }).click();
    for (const name of ["Preview prosecution event", "Record prosecution event"]) {
      const control = page.getByRole("button", { name });
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }
  });

  test("linked Matter evidence, obligations, coverage, and reconciliation complete through the browser", async ({ page }) => {
    const api = await request.newContext();
    const slug = unique("ip-complete");
    const { token, membershipId } = await bootstrap(api, slug);
    await seedLinkedIpDocket(api, token, membershipId);
    await signIn(page, slug);
    await page.setViewportSize({ width: 360, height: 900 });
    await page.goto("/app/ip");

    await expect(page.getByRole("heading", { name: "ORBIT linked mark", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Discover Matter evidence" }).click();
    await expect(page.getByText("Client filing instruction")).toBeVisible();
    await page.getByRole("button", { name: "Accept and link" }).click();
    await expect(page.getByText(/Evidence review recorded/)).toBeVisible();

    await page.getByLabel("Obligation", { exact: true }).fill("Record assignment");
    await page.getByLabel("Owner", { exact: true }).selectOption(membershipId);
    await page.getByLabel("Obligation evidence").fill("attachment:assignment-deed");
    await page.getByRole("button", { name: "Add recordal obligation" }).click();
    await expect(page.getByText("Record assignment")).toBeVisible();

    const costSubmit = page.getByRole("button", { name: "Add cost evidence" });
    const costForm = costSubmit.locator("xpath=ancestor::form");
    await costForm.getByLabel("Description").fill("Registry fee");
    await costForm.getByLabel("Amount (INR)").fill("9000");
    await costForm.getByLabel("Evidence reference").fill("receipt:registry-fee");
    await costSubmit.click();
    await expect(page.getByText("Registry fee")).toBeVisible();
    await page.getByRole("button", { name: "Reconcile with Matter billing" }).click();

    await page.getByRole("tab", { name: "Proceedings" }).click();
    const prosecution = page.getByTestId("ip-prosecution-workspace");
    await prosecution.getByLabel("Reason").fill("Reviewed the official formalities evidence.");
    await prosecution.getByLabel("Evidence reference").fill("attachment:formalities-evidence");
    await prosecution.getByLabel("Document reference").fill("attachment:formalities-document");
    await prosecution.getByRole("button", { name: "Preview prosecution event" }).click();
    await expect(prosecution.getByTestId("ip-event-preview")).toContainText("Preview only");
    await prosecution.getByRole("button", { name: "Record prosecution event" }).click();
    await expect(page.getByText("Prosecution event recorded in the immutable timeline.")).toBeVisible();
    await expect(prosecution.getByRole("list", { name: "Prosecution event timeline" })).toContainText("formalities");

    // 2026-08-15 (IPLF-039C): "Transfer covered deadlines" is now "Offer covered
    // deadlines". A routine coverage transfer became a proposal that the named
    // replacement must accept, so a control labelled "transfer" was claiming an
    // act it no longer performs.
    for (const name of ["Preview prosecution event", "Record prosecution event"]) {
      const control = page.getByRole("button", { name });
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }

    await page.getByRole("tab", { name: "Overview" }).click();
    for (const name of ["Discover Matter evidence", "Offer covered deadlines", "Add recordal obligation", "Reconcile with Matter billing", "Preview lifecycle impact", "Apply lifecycle transition"]) {
      const control = page.getByRole("button", { name });
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }

    const lifecycle = page.getByTestId("ip-lifecycle-workflow");
    await lifecycle.getByLabel("Reason").fill("Synthetic QA docket lifecycle completion.");
    await lifecycle.getByLabel("Outcome").fill("closed");
    await lifecycle.getByLabel("Evidence reference").fill("qa:synthetic-close-proof");
    await lifecycle.getByRole("button", { name: "Preview lifecycle impact" }).click();
    await expect(lifecycle.getByTestId("ip-lifecycle-preview")).toContainText("ready → closed");
    await lifecycle.getByRole("button", { name: "Apply lifecycle transition" }).click();
    await expect(page.getByText("Docket lifecycle transition recorded.")).toBeVisible();
  });
});
