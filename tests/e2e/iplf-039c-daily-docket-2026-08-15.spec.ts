/**
 * IPLF-039C — the daily docket, end to end in a real browser.
 *
 * Increments 7 to 9 were proven with pytest and jsdom component tests. Two
 * things that matters most were not proven by either:
 *
 *  * the **export** produces a real file. jsdom proved only that a mocked
 *    download function was called; here the browser actually emits a download
 *    and its bytes are read back and checked.
 *  * acknowledging in the UI actually moves the manager's count, across two
 *    independent API reads rather than one component's local state.
 *  * mandatory exceptions require immutable manager decisions before the
 *    preparer can sign.
 *  * a retained review crosses sessions for an independent sample and second
 *    signature, then downloads with the complete evidence chain.
 *
 * Stable manifest test IDs:
 *
 *  * ``IPLF-CAL-OPS-09-E2E-01``  acknowledge in the UI, the docket count moves
 *  * ``IPLF-CAL-OPS-09-E2E-02``  export produces a manifest with its provenance
 *  * ``IPLF-CAL-OPS-13-E2E-01``  a review is signed and shows its signature
 */

import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "DailyDocket2026!";

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
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_039c_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
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

function particulars(mark: string) {
  return {
    form_key: "TM-A",
    form_version: "2026.1",
    mark_kind: "word",
    representation: { text: mark, evidence_reference: `e2e:${mark.toLowerCase()}` },
    classes: [{ class_number: 9, specification: "Downloadable software" }],
    use_priority: null,
    parties: [{ role: "applicant", name: "Daily Docket Applicant LLP" }],
    agent: null,
    filing_manifest: [
      {
        key: "representation",
        label: "Mark representation",
        required: true,
        evidence_reference: `e2e:${mark.toLowerCase()}`,
      },
    ],
  };
}

async function bootstrap(api: APIRequestContext) {
  const slug = `daily-docket-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 039C Daily Docket LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Daily Docket Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  return { ...body, slug, email };
}

async function enableIpWorkspace(
  api: APIRequestContext,
  tenant: { access_token: string; membership: { id: string } },
): Promise<{ Authorization: string }> {
  const ownerHeaders = { Authorization: `Bearer ${tenant.access_token}` };
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
  return ownerHeaders;
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function createReviewer(
  api: APIRequestContext,
  ownerHeaders: { Authorization: string },
  slug: string,
): Promise<{ email: string; membershipId: string }> {
  const email = `reviewer-${slug}@example.com`;
  const created = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers: ownerHeaders,
    data: {
      full_name: "Independent Docket Reviewer",
      email,
      password: PASSWORD,
      role: "admin",
    },
  });
  expect(created.status(), await created.text()).toBe(200);
  return { email, membershipId: (await created.json()).membership_id as string };
}

test("IPLF-039C acknowledges, exports and records every docket exception", async ({
  page,
}) => {
  test.setTimeout(180_000);
  // Exercise the complete grouped-control surface at a phone width.  A DOM
  // assertion alone cannot prove that the action buttons remain visible or
  // that the nested grids shrink instead of widening the page.
  await page.setViewportSize({ width: 375, height: 812 });
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const ownerHeaders = await enableIpWorkspace(api, tenant);
  const suffix = Date.now();

  const matter = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: ownerHeaders,
    data: {
      title: "Daily docket linked Matter",
      matter_code: `IPLF-039C-${suffix}`,
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
      title: "DOCKETCONTROL",
      matter_id: matterId,
      particulars: particulars("DOCKETCONTROL"),
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const docketId = (await docket.json()).id as string;

  const dueOn = new Date(Date.now() + 21 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const deadline = await api.post(`${apiBaseUrl}/api/matters/${matterId}/deadlines`, {
    headers: ownerHeaders,
    data: {
      source: "custom",
      kind: "licence_royalty",
      title: "Opposition reply",
      due_on: dueOn,
      assignee_membership_id: tenant.membership.id,
    },
  });
  expect(deadline.status(), await deadline.text()).toBe(200);
  const deadlineId = (await deadline.json()).id as string;

  const coverage = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docketId}/deadline-coverages`,
    {
      headers: ownerHeaders,
      data: {
        matter_deadline_id: deadlineId,
        responsible_membership_id: tenant.membership.id,
        // Seeded unacknowledged: taking it on is what this test exercises.
        coverage_status: "pending",
      },
    },
  );
  expect(coverage.status(), await coverage.text()).toBe(200);

  const incident = await api.post(
    `${apiBaseUrl}/api/ip/dockets/${docketId}/deadline-incidents`,
    {
      headers: ownerHeaders,
      data: {
        matter_deadline_id: deadlineId,
        severity: "high",
        summary: "Open control-review incident for fail-closed sign-off proof.",
        impact: {},
      },
    },
  );
  expect(incident.status(), await incident.text()).toBe(200);

  await signIn(page, tenant.slug as string, tenant.email as string);
  await page.goto("/app/ip/docket");

  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);

  // CAL-OPS-09: provenance is on the page, not behind a tooltip.
  const provenance = page.getByTestId("ip-docket-provenance");
  await expect(provenance.getByText(/^Generated /)).toBeVisible();
  await expect(provenance.getByText("No filters applied")).toBeVisible();
  await expect(provenance.getByText("All sources current")).toBeVisible();

  // IPLF-CAL-OPS-09-E2E-01 — the manager's count and the member's list agree,
  // and acknowledging in the UI moves both.
  const capacity = page.getByTestId("ip-docket-capacity");
  const queueRow = capacity.getByTestId(`ip-docket-queue-${tenant.membership.id as string}`);
  await expect(queueRow).toContainText("Daily Docket Owner");
  const unacknowledged = page.getByTestId(
    `ip-docket-unacknowledged-${tenant.membership.id as string}`,
  );
  await expect(unacknowledged).toHaveText("1");
  await expect(page.getByTestId(`ip-docket-assigned-${tenant.membership.id as string}`)).toHaveText(
    "1",
  );

  const acknowledge = page.getByTestId("ip-docket-acknowledge");
  await expect(acknowledge.getByText("DOCKETCONTROL")).toBeVisible();
  await expect(acknowledge.getByText(/Opposition reply/)).toBeVisible();
  await acknowledge.getByRole("button", { name: /^Select all 1$/ }).click();
  await acknowledge.getByRole("button", { name: "Acknowledge selected" }).click();

  await expect(
    acknowledge.getByText("You have acknowledged every deadline you hold.", { exact: false }),
  ).toBeVisible();
  // The count the manager reads is refetched from the API, not local state.
  await expect(unacknowledged).toHaveText("0");

  // IPLF-CAL-OPS-09-E2E-02 — the export produces a real file. This is the part
  // the jsdom test could not prove: there the download helper was mocked.
  const review = page.getByTestId("ip-docket-control-review");
  await review.getByRole("button", { name: "Generate control review" }).click();
  // The export control only appears once a review exists, so its presence is
  // the signal that generation landed.
  const exportButton = review.getByTestId("ip-docket-review-export");
  await expect(exportButton).toBeVisible();
  await expect(review.getByText("Manifest SHA-256")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await exportButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^ip-control-review-.*\.html$/);

  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const manifest = Buffer.concat(chunks).toString("utf8");

  // The provenance CAL-OPS-09 requires is in the exported artefact itself.
  expect(manifest).toContain("IP daily docket — control review");
  expect(manifest).toContain("Generated");
  expect(manifest).toContain("Filters");
  expect(manifest).toContain("Freshness");
  expect(manifest).toContain("Open incident");
  expect(manifest).toMatch(/[0-9a-f]{64}/);
  // A printout must not disclose what the firm is working on.
  expect(manifest).not.toContain("DOCKETCONTROL");

  // Acknowledgment does not erase the separate open-incident exception. The
  // generated artefact must remain visibly fail-closed.
  await expect(review.getByTestId("ip-docket-review-exceptions")).toContainText(
    "Open incident",
  );
  await expect(review.getByTestId("ip-docket-review-blocked")).toContainText(
    "Record a decision for all",
  );
  await expect(review.getByLabel("What are you attesting to?")).toHaveCount(0);
  await expect(review.getByRole("button", { name: "Add preparer signature" })).toHaveCount(0);

  while (await review.getByRole("button", { name: "Record decision" }).count()) {
    const before = await review.getByRole("button", { name: "Record decision" }).count();
    await review.getByRole("button", { name: "Record decision" }).first().click();
    await review.getByLabel("Decision note").fill("Manager reviewed and controlled this exception.");
    await review.getByLabel("Evidence reference").fill(`e2e:control-decision-${before}`);
    await review.getByRole("button", { name: "Save immutable decision" }).click();
    await expect(review.getByRole("button", { name: "Record decision" })).toHaveCount(before - 1);
  }
  await expect(review.getByRole("button", { name: "Add preparer signature" })).toBeVisible();
});

test("IPLF-039C signs off an independently generated clean daily docket review", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 375, height: 812 });
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const ownerHeaders = await enableIpWorkspace(api, tenant);
  const reviewer = await createReviewer(api, ownerHeaders, tenant.slug as string);

  const docket = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
    headers: ownerHeaders,
    data: {
      title: "CLEANREVIEW",
      matter_id: null,
      particulars: particulars("CLEANREVIEW"),
    },
  });
  expect(docket.status(), await docket.text()).toBe(201);
  const docketId = (await docket.json()).id as string;

  await signIn(page, tenant.slug as string, tenant.email as string);
  await page.goto("/app/ip/docket");

  const review = page.getByTestId("ip-docket-control-review");
  await review.getByRole("button", { name: "Generate control review" }).click();
  await expect(review.getByText("Manifest SHA-256")).toBeVisible();
  await expect(review.getByTestId("ip-docket-review-exceptions")).toHaveCount(0);
  await expect(review.getByTestId("ip-docket-review-blocked")).toHaveCount(0);

  // IPLF-CAL-OPS-13-E2E-01 — the preparer signs first, but the report is not
  // represented as complete until an independent reviewer signs.
  await review
    .getByLabel("What are you attesting to?")
    .fill("Prepared and checked today's clean daily docket.");
  await review.getByRole("button", { name: "Add preparer signature" }).click();
  await expect(review.getByTestId("ip-docket-review-signatures")).toContainText(
    "Daily Docket Owner (preparer)",
  );
  await expect(review.getByTestId("ip-docket-review-signed")).toHaveCount(0);
  await expect(review.getByTestId("ip-docket-review-export")).toHaveCount(0);

  await page.getByRole("button", { name: "Open user menu" }).click();
  await page.getByTestId("sign-out").click();
  await page.waitForURL(/\/sign-in(?:\?|$)/);
  await signIn(page, tenant.slug as string, reviewer.email);
  await page.goto("/app/ip/docket");

  const retained = page.getByTestId("ip-docket-control-review");
  await expect(retained.getByTestId("ip-docket-review-sample")).toBeVisible();
  await expect(retained.getByLabel("Included record")).toHaveValue(docketId);
  await retained.getByLabel("Source evidence reference").fill("e2e:registry-snapshot");
  await retained
    .getByLabel("Calculation evidence reference")
    .fill("e2e:deadline-calculation");
  await retained.getByLabel("Coverage evidence reference").fill("e2e:coverage-check");
  await retained.getByLabel("Reviewer sample notes").fill("All sampled evidence agrees.");
  await retained.getByRole("button", { name: "Record sample" }).click();

  await retained
    .getByLabel("What are you attesting to?")
    .fill("Independently sampled source, calculation and coverage evidence.");
  await retained.getByRole("button", { name: "Add reviewer signature" }).click();
  await expect(retained.getByTestId("ip-docket-review-signed")).toContainText(
    "Independent Docket Reviewer",
  );

  const signedDownload = page.waitForEvent("download");
  await retained.getByTestId("ip-docket-review-download-signed").click();
  const signedFile = await signedDownload;
  const signedStream = await signedFile.createReadStream();
  const signedChunks: Buffer[] = [];
  for await (const chunk of signedStream) signedChunks.push(Buffer.from(chunk));
  const signedManifest = Buffer.concat(signedChunks).toString("utf8");
  expect(signedManifest).toContain("Signatures (2/2)");
  expect(signedManifest).toContain("Independent Docket Reviewer");
  expect(signedManifest).toContain("e2e:registry-snapshot");
});
