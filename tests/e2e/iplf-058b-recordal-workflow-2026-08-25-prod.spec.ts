/** IPLF-058B dated production acceptance for post-registration recordals. */

import { expect, request, test, type Page } from "@playwright/test";

import { createRecordalFixture, expectStatus, recordTransaction } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai").trim();

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function authenticate(page: Page) {
  const response = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(response, 200, "IP QA sign-in");
  const session = await response.json();
  await page.goto(`${WEB}/`);
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
  return session;
}

test("IPLF-058B production proves every UJ-36 path and the dated UJ-61 view", async ({ page }) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(25_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const session = await authenticate(page);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const api = await request.newContext();
  const runId = `${Date.now()}`;
  const fixture = await createRecordalFixture(
    api,
    API,
    headers,
    session.membership.id,
    runId,
  );

  const reviewed = await recordTransaction(
    api, API, headers, session.membership.id, fixture, "review_approved",
  );
  expect(reviewed.projected_title_interests).toEqual(expect.arrayContaining([
    expect.objectContaining({
      party_name: "Nova Holdings LLP",
      recordal_status: "pending",
      scope_json: expect.objectContaining({ scope_kind: "partial", affected_classes: [9] }),
    }),
  ]));
  const docketResponse = await api.get(`${API}/api/ip/dockets/${fixture.docket.id}`, { headers });
  await expectStatus(docketResponse, 200, "production pending title docket");
  expect((await docketResponse.json()).title_interests).toEqual(expect.arrayContaining([
    expect.objectContaining({ party_name: "Oldco Brands Limited", recordal_status: "recorded" }),
    expect.objectContaining({ party_name: "Nova Holdings LLP", recordal_status: "pending" }),
  ]));

  await recordTransaction(api, API, headers, session.membership.id, fixture, "filed");
  await recordTransaction(api, API, headers, session.membership.id, fixture, "defect_noted");
  const invalidCorrection = await recordTransaction(
    api,
    API,
    headers,
    session.membership.id,
    fixture,
    "corrected",
    { evidence_refs: [], document_refs: [] },
    422,
  );
  expect(await invalidCorrection.text()).toContain("corrected");
  await recordTransaction(api, API, headers, session.membership.id, fixture, "corrected");
  await recordTransaction(api, API, headers, session.membership.id, fixture, "filed");

  const registryAcceptance = {
    source_url: fixture.snapshot.source_url,
    source_reference: `ipindia:production:${runId}`,
    registry_snapshot_id: fixture.snapshot.id,
    registry_recorded_on: "2026-08-25",
  };
  const unresolved = await recordTransaction(
    api,
    API,
    headers,
    session.membership.id,
    fixture,
    "accepted",
    registryAcceptance,
    422,
  );
  expect(await unresolved.text()).toContain("conflict review");
  const accepted = await recordTransaction(
    api,
    API,
    headers,
    session.membership.id,
    fixture,
    "accepted",
    {
      ...registryAcceptance,
      details: { client_registry_conflict_reviewed: true },
    },
  );
  expect(accepted.recordal.status).toBe("accepted");
  expect(accepted.registry_projection_applied).toBe(true);
  expect(accepted.event.payload_json).toEqual(expect.objectContaining({
    client_registry_conflict_detected: true,
    client_registry_conflict_reviewed: true,
  }));

  const recordalPageRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/ip/")) recordalPageRequests.push(url.toString());
  });
  const aggregateResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname
      === `/api/ip/recordals/${fixture.recordal.id}/workspace`,
    { timeout: 60_000 },
  );
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`${WEB}/app/ip/recordals`);
  await expect(page.getByRole("heading", { name: "Post-registration" })).toBeVisible();
  for (const name of ["Recordal", "Title at date", "Evidence and controls", "History"]) {
    const tab = page.getByRole("tab", { name });
    await expect(tab).toBeVisible();
    const box = await tab.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);
  expect((await aggregateResponse).ok()).toBe(true);
  expect(recordalPageRequests.filter((requestUrl) => new URL(requestUrl).pathname
    === `/api/ip/recordals/${fixture.recordal.id}/workspace`)).toHaveLength(1);
  expect(recordalPageRequests.some((requestUrl) => {
    const url = new URL(requestUrl);
    return url.pathname === `/api/ip/dockets/${fixture.docket.id}`
      || (url.pathname === "/api/ip/documents" && url.searchParams.has("docket_id"))
      || url.pathname === "/api/ip/registry-links"
      || url.pathname === `/api/ip/dockets/${fixture.docket.id}/deadline-workspace`;
  })).toBe(false);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("tab", { name: "Title at date" }).click();
  await expect(page.getByRole("heading", { name: "Registry-recorded position" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Nova Holdings LLP" }).first()).toBeVisible();
  await expect(page.getByText(/partial scope in classes 9/i)).toBeVisible();
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("link", { name: new RegExp(`ipindia:production:${runId}`) })).toHaveAttribute(
    "href",
    "https://ipindia.gov.in/trademark/",
  );

  await page.goto(`${WEB}/guide`);
  await expect(page.getByRole("heading", { name: "Post-registration recordals and title" })).toBeVisible();
  await page.goto(`${WEB}/law-firms`);
  await expect(page.getByRole("heading", { name: "Post-registration recordals and title" })).toBeVisible();
  await api.dispose();
});
