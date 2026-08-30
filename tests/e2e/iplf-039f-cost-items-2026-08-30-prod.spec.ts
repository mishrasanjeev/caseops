/**
 * IPLF-039F deployed acceptance through public HTTP surfaces only.
 *
 * Unlike the local Docker spec, this file never shells into a database, creates
 * a tenant, or grants an entitlement. It fails closed unless the runner names a
 * dedicated fixture tenant, its matterless IP docket, and the complete set of
 * Matters whose public workspaces form the billing/payment snapshot.
 */

import { expect, test, type APIResponse, type Page } from "@playwright/test";

const WEB = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const API = process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const TENANT_ACK = "I_CONFIRM_DEDICATED_IP_COST_TEST_TENANT";

type Json = Record<string, unknown>;
type Auth = {
  access_token: string;
  company: { id: string; slug: string };
  user: { email: string; full_name: string };
  membership: { id: string; role: string };
  capabilities: string[];
};
type MatterList = {
  matters: Array<{ id: string }>;
  next_cursor: string | null;
};
type Cost = {
  id: string;
  description: string;
  evidence_reference: string;
  matter_id: string | null;
  billable: boolean;
  billing_link_type: string | null;
  billing_link_id: string | null;
  reconciliation_status: string;
  canonical_amount_minor: number | null;
  reconciliation_difference_minor: number | null;
  lineage_status: "active" | "voided" | "superseded";
};
type Docket = { id: string; matter_id: string | null; cost_items: Cost[] };

function required(name: string): string {
  const value = (process.env[name] ?? "").trim();
  if (!value) {
    throw new Error(`${name} is required for IPLF-039F deployed acceptance.`);
  }
  return value;
}

async function json<T>(response: APIResponse, expected: number, label: string): Promise<T> {
  const body = await response.text();
  expect(response.status(), `${label}: ${body}`).toBe(expected);
  return JSON.parse(body) as T;
}

function fixtureMatterIds(): string[] {
  const raw = required("CASEOPS_IP_COST_PROD_BILLING_MATTER_IDS_JSON");
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("CASEOPS_IP_COST_PROD_BILLING_MATTER_IDS_JSON must be a JSON array.");
  }
  if (!Array.isArray(parsed) || parsed.some((value) => typeof value !== "string")) {
    throw new Error("CASEOPS_IP_COST_PROD_BILLING_MATTER_IDS_JSON must contain only Matter IDs.");
  }
  const ids = parsed.map((value) => value.trim());
  if (ids.some((value) => !value) || new Set(ids).size !== ids.length) {
    throw new Error("Production billing Matter fixture IDs must be non-empty and unique.");
  }
  return ids.sort();
}

async function allMatterIds(page: Page, headers: Record<string, string>): Promise<string[]> {
  const ids: string[] = [];
  let cursor: string | null = null;
  do {
    const response = await page.request.get(`${API}/api/matters/`, {
      headers,
      params: { limit: "200", ...(cursor ? { cursor } : {}) },
    });
    const body = await json<MatterList>(response, 200, "list dedicated tenant Matters");
    ids.push(...body.matters.map((matter) => matter.id));
    cursor = body.next_cursor;
  } while (cursor);
  return ids.sort();
}

function canonicalBillingWorkspace(workspace: Json): Json {
  const timeEntries = (workspace.time_entries as Json[]).map((entry) => ({
    id: entry.id,
    duration_minutes: entry.duration_minutes,
    rate_amount_minor: entry.rate_amount_minor,
    billable: entry.billable,
  })).sort((left, right) => String(left.id).localeCompare(String(right.id)));
  const invoices = (workspace.invoices as Json[]).map((invoice) => ({
    id: invoice.id,
    status: invoice.status,
    currency: invoice.currency,
    subtotal_amount_minor: invoice.subtotal_amount_minor,
    tax_amount_minor: invoice.tax_amount_minor,
    total_amount_minor: invoice.total_amount_minor,
    amount_received_minor: invoice.amount_received_minor,
    balance_due_minor: invoice.balance_due_minor,
    line_items: (invoice.line_items as Json[]).map((line) => ({
      id: line.id,
      time_entry_id: line.time_entry_id,
      line_total_amount_minor: line.line_total_amount_minor,
    })).sort((left, right) => String(left.id).localeCompare(String(right.id))),
    payment_attempts: (invoice.payment_attempts as Json[]).map((attempt) => ({
      id: attempt.id,
      status: attempt.status,
      amount_minor: attempt.amount_minor,
      amount_received_minor: attempt.amount_received_minor,
      currency: attempt.currency,
    })).sort((left, right) => String(left.id).localeCompare(String(right.id))),
  })).sort((left, right) => String(left.id).localeCompare(String(right.id)));
  return { time_entries: timeEntries, invoices };
}

async function billingSnapshot(
  page: Page,
  headers: Record<string, string>,
  matterIds: string[],
): Promise<Record<string, Json>> {
  const snapshot: Record<string, Json> = {};
  for (const matterId of matterIds) {
    const workspace = await json<Json>(
      await page.request.get(`${API}/api/matters/${matterId}/workspace`, { headers }),
      200,
      `read billing workspace ${matterId}`,
    );
    snapshot[matterId] = canonicalBillingWorkspace(workspace);
  }
  return snapshot;
}

test("IPLF-039F deployed matterless correction is append-only and has no billing effect", async ({
  page,
}) => {
  test.setTimeout(240_000);
  expect(required("CASEOPS_IP_COST_PROD_TEST_TENANT_ACK")).toBe(TENANT_ACK);
  for (const endpoint of [WEB, API]) {
    const url = new URL(endpoint);
    expect(url.protocol, "Deployed acceptance must use HTTPS.").toBe("https:");
    expect(["localhost", "127.0.0.1", "::1"]).not.toContain(url.hostname);
  }

  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA").toLowerCase();
  expect(expectedSha).toMatch(/^[0-9a-f]{40}$/);
  const [apiBuild, webBuild] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  expect((await json<{ release_sha: string }>(apiBuild, 200, "API release identity")).release_sha)
    .toBe(expectedSha);
  expect((await json<{ release_sha: string }>(webBuild, 200, "web release identity")).release_sha)
    .toBe(expectedSha);

  const slug = required("CASEOPS_IP_COST_PROD_COMPANY_SLUG");
  const email = required("CASEOPS_IP_COST_PROD_EMAIL");
  const auth = await json<Auth>(
    await page.request.post(`${API}/api/auth/login`, {
      data: {
        company_slug: slug,
        email,
        password: required("CASEOPS_IP_COST_PROD_PASSWORD"),
      },
    }),
    200,
    "authenticate dedicated IP cost fixture",
  );
  expect(auth.company.slug).toBe(slug);
  expect(auth.user.email.toLowerCase()).toBe(email.toLowerCase());
  expect(auth.capabilities).toEqual(expect.arrayContaining(["ip:read", "ip:write", "ip:fees_manage"]));
  const headers = { Authorization: `Bearer ${auth.access_token}` };

  const docketId = required("CASEOPS_IP_COST_PROD_DOCKET_ID");
  const initialDocket = await json<Docket>(
    await page.request.get(`${API}/api/ip/dockets/${docketId}`, { headers }),
    200,
    "read dedicated matterless IP docket",
  );
  expect(initialDocket.matter_id, "Fixture docket must not have a billing Matter.").toBeNull();

  const expectedMatterIds = fixtureMatterIds();
  expect(
    await allMatterIds(page, headers),
    "The declared Matter list must be the complete dedicated tenant billing surface.",
  ).toEqual(expectedMatterIds);
  const before = await billingSnapshot(page, headers, expectedMatterIds);
  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const evidence = `prod-acceptance:iplf-039f:${nonce}`;
  const createdDocket = await json<Docket>(
    await page.request.post(`${API}/api/ip/dockets/${docketId}/cost-items`, {
      headers,
      data: {
        category: "official_fee",
        description: `Synthetic matterless official fee ${nonce}`,
        amount_minor: 901234,
        currency: "INR",
        evidence_reference: evidence,
        billable: false,
        cost_nature: "actual",
      },
    }),
    200,
    "append production nonbillable evidence",
  );
  const created = createdDocket.cost_items.find((cost) => cost.evidence_reference === evidence);
  expect(created, "Created cost must be returned with immutable evidence.").toBeDefined();
  expect(created).toMatchObject({
    matter_id: null,
    billable: false,
    billing_link_type: null,
    billing_link_id: null,
    reconciliation_status: "nonbillable",
    canonical_amount_minor: null,
    reconciliation_difference_minor: null,
    lineage_status: "active",
  });

  const reconciliation = await json<Json>(
    await page.request.post(`${API}/api/ip/dockets/${docketId}/cost-items/reconcile`, {
      headers,
      data: {},
    }),
    200,
    "verify production nonbillable evidence",
  );
  const row = (reconciliation.rows as Json[]).find((candidate) => candidate.cost_item_id === created!.id);
  expect(row).toMatchObject({
    status: "nonbillable",
    lineage_status: "active",
    included_in_totals: true,
    canonical_amount_minor: null,
    difference_minor: null,
  });
  expect(await billingSnapshot(page, headers, expectedMatterIds)).toEqual(before);

  await page.goto(WEB, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: auth.company,
    user: auth.user,
    membership: auth.membership,
    capabilities: auth.capabilities,
  });
  await page.goto(`${WEB}/app/ip?docket=${docketId}`, {
    waitUntil: "domcontentloaded",
    timeout: 30_000,
  });
  const costCard = page.getByTestId(`ip-cost-item-${created!.id}`);
  await expect(costCard).toBeVisible({ timeout: 30_000 });
  await expect(costCard.getByText(`Evidence: ${evidence}`, { exact: true })).toBeVisible();
  await expect(costCard.getByText("Nonbillable", { exact: true })).toBeVisible();
  await costCard.getByRole("button", { name: "Correct or void" }).click();
  await costCard.getByLabel("Correction action").selectOption("void");
  await costCard.getByLabel("Correction reason").fill(
    "Dated deployed acceptance row completed; preserve it only as inactive evidence.",
  );
  await costCard.getByLabel("Correction evidence reference").fill(
    `prod-acceptance:void:${nonce}`,
  );
  const correctionResponse = page.waitForResponse((response) =>
    response.url().includes(`/cost-items/${created!.id}/corrections`)
    && response.request().method() === "POST",
  );
  await costCard.getByRole("button", { name: "Void cost evidence" }).click();
  expect((await correctionResponse).status()).toBe(200);
  await expect(costCard.getByText(/Voided — excluded from totals/)).toBeVisible();
  await expect(costCard.getByText(`Evidence: ${evidence}`, { exact: true })).toBeVisible();

  const finalDocket = await json<Docket>(
    await page.request.get(`${API}/api/ip/dockets/${docketId}`, { headers }),
    200,
    "read preserved void history",
  );
  expect(finalDocket.cost_items.find((cost) => cost.id === created!.id)).toMatchObject({
    evidence_reference: evidence,
    lineage_status: "voided",
    matter_id: null,
    billable: false,
    billing_link_type: null,
    billing_link_id: null,
    reconciliation_status: "nonbillable",
    canonical_amount_minor: null,
    reconciliation_difference_minor: null,
  });
  expect(await billingSnapshot(page, headers, expectedMatterIds)).toEqual(before);
});
