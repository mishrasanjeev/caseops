/**
 * BUG-012 (Ram 2026-10-30, CaseOps_Bugs (4).xlsx; IP UJ registry reconciliation):
 * the registry page's "Legal record" offered only "Select record" because the
 * page auto-selected the most recently updated docket, a Madrid international
 * registration with no application, could not reach any docket after the first
 * page, and asked for raw JSON to record evidence.
 *
 * Signed in as the tester, these journeys prove in the real UI that:
 * - nothing is selected for the tester and only national dockets are listed
 *   (server-side, so totals and pages are honest);
 * - a docket beyond the first 50 is found by typing its number, and a
 *   `?docket=` deep link reopens it;
 * - the legal records carry their numbers, the identity form is prefilled, and
 *   an identity is added (stamp) and shown under Registry identities;
 * - register evidence is entered through structured fields (no JSON), queued
 *   for review and shown; then the review row is rejected and the identity
 *   retired, so production keeps no live test record;
 * - a Madrid docket explains itself and points to the Madrid portfolio.
 *
 * Production (test-legal) picks a real docket beyond the first 50 by server
 * identity. Locally the portfolio it searches (one target application created
 * first, 55 newer dockets and one newer Madrid record) is seeded through the
 * API: creating dockets is not the workflow under test.
 */
import { expect, test, type APIRequestContext, type Page, type Response } from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type Target = {
  docketId: string;
  title: string;
  number: string;
  applicationId: string;
  applicationIdentifier: string;
  madridDocketId: string;
};

type CoreIdentifier = {
  application_id: string | null; proceeding_id: string | null; effective_until: string | null;
  identifier_kind: string; is_primary: boolean; raw_value: string;
};

const INTERNAL_FIELD = /\b(?:membership ids?|member ids?|uuid|sha-?256|raw (?:source )?json|json|parser version)\b/i;
const PICKER_PAGE = 50;

function particulars(mark: string) {
  return {
    form_key: "TM-A",
    form_version: "2026.1",
    mark_kind: "word",
    representation: { text: mark, evidence_reference: `e2e:${mark.toLowerCase().replace(/\s+/g, "-")}` },
    classes: [{ class_number: 9, specification: "Downloadable legal software" }],
    use_priority: null,
    parties: [{ role: "applicant", name: "Test Legal Clients LLP" }],
    agent: null,
    filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:registry" }],
  };
}

/** Local only: the portfolio the tester searches. Not the workflow under test. */
async function seedLocalPortfolio(rt: TesterRuntime, request: APIRequestContext): Promise<Target> {
  expect(rt.local).toBe(true);
  const title = stamp("B4 REGISTRY TARGET");
  const number = `${Date.now()}`.slice(-9);
  const created = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
    headers: rt.headers,
    data: {
      title, restricted: false, asset_title: title, jurisdiction: "IN", office: "IP India", filing_phase: "draft",
      source_pending_identifier_allocation: false,
      application_number: { raw_value: number, source: "e2e registry fixture", effective_from: "2026-10-01", is_primary: true },
      particulars: particulars(title),
    },
  }), "Local target application", 201);
  for (let index = 0; index < 55; index += 1) {
    await json(await request.post(`${rt.api.origin}/api/ip/dockets`, {
      headers: rt.headers,
      data: { title: `Newer filler ${index}`, primary_identifier: `FILL-${index}`, restricted: false, particulars: particulars(`FILLER ${index}`) },
    }), `Local filler docket ${index}`, 201);
  }
  const madrid = await json(await request.post(`${rt.api.origin}/api/ip/international-registrations`, {
    headers: rt.headers,
    data: {
      docket_title: stamp("B4 MADRID IR"), restricted: false, record_kind: "international_registration", direction: "inbound",
      international_application_number: null, ir_number: `${Date.now()}`.slice(-7), wipo_reference: stamp("WIPO-B4"),
      holder_name: "Overseas Holder SA", mark_name: "TASTYBITE", designated_office: null, classes: [30],
      goods_services: { "30": "Biscuits" }, priority_claims: [], wipo_status: "recorded", national_status: null,
      local_agent_name: null, source_url: "https://www.wipo.int/madrid/monitor/en/", source_reference: stamp("wipo:b4"),
      source_retrieved_at: new Date().toISOString(),
    },
  }), "Local Madrid record (most recently updated docket)", 201);
  return {
    docketId: created.docket.id, title, number, applicationId: created.application.id,
    applicationIdentifier: created.identifier.raw_value, madridDocketId: madrid.docket_id,
  };
}

async function dockets(rt: TesterRuntime, request: APIRequestContext, params: Record<string, string>) {
  const search = new URLSearchParams({ record_type: "trademark", limit: String(PICKER_PAGE), ...params });
  return json(await request.get(`${rt.api.origin}/api/ip/dockets?${search}`, { headers: rt.headers }), "Docket oracle");
}

/** Production: a real national docket beyond the first 50, selected by server identity. */
async function findProductionTarget(rt: TesterRuntime, request: APIRequestContext): Promise<Target> {
  const madrid = await json(await request.get(
    `${rt.api.origin}/api/ip/dockets?record_type=international_registration&record_type=international_designation&limit=1`,
    { headers: rt.headers },
  ), "Madrid oracle");
  expect(madrid.dockets.length, "test-legal holds the reported Madrid record").toBe(1);
  const first = await dockets(rt, request, {});
  expect(first.has_more, "test-legal has more national dockets than one picker page").toBe(true);
  let cursor: string | null = first.next_cursor;
  for (let pages = 0; pages < 4 && cursor; pages += 1) {
    const next = await dockets(rt, request, { cursor });
    for (const docket of next.dockets) {
      if (!docket.primary_identifier || docket.restricted) continue;
      const core = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docket.id}/core-records`, { headers: rt.headers }), "Core records oracle");
      const application = core.applications[0];
      // The form prefills the primary active application number, as here.
      const identifier = application && core.identifiers
        .filter((row: CoreIdentifier) => row.application_id === application.id && !row.proceeding_id
          && row.effective_until === null && row.identifier_kind === "application")
        .sort((a: CoreIdentifier, b: CoreIdentifier) => Number(b.is_primary) - Number(a.is_primary))[0];
      if (!identifier) continue;
      const found = await dockets(rt, request, { query: docket.primary_identifier });
      if (!found.dockets.some((row: { id: string }) => row.id === docket.id)) continue;
      return {
        docketId: docket.id, title: docket.title, number: docket.primary_identifier, applicationId: application.id,
        applicationIdentifier: identifier.raw_value, madridDocketId: madrid.dockets[0].id,
      };
    }
    cursor = next.next_cursor;
  }
  throw new Error("No searchable national docket with an application was found beyond the first picker page.");
}

function isDocketList(response: Response, query?: string) {
  const url = new URL(response.url());
  return url.pathname === "/api/ip/dockets" && response.request().method() === "GET"
    && url.searchParams.getAll("record_type").join(",") === "trademark"
    && (query === undefined ? !url.searchParams.get("query") : url.searchParams.get("query") === query);
}

async function internalFields(page: Page): Promise<string[]> {
  return page.locator("main").evaluate((root, pattern) => {
    const re = new RegExp(pattern, "i");
    return Array.from(root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"))
      .filter(field => field.type !== "hidden" && !field.disabled && field.getBoundingClientRect().width > 0)
      .map(field => field.labels?.[0]?.innerText || field.getAttribute("aria-label") || field.placeholder || "")
      .filter(label => re.test(label));
  }, INTERNAL_FIELD.source);
}

async function journey(page: Page, request: APIRequestContext, rt: TesterRuntime, target: Target, info: Parameters<typeof markPositive>[0], mobile: boolean) {
  const main = page.locator("main");
  const firstList = page.waitForResponse(response => isDocketList(response));
  await page.goto(`${rt.web.origin}/app/ip/registry`);
  const listed = await (await firstList).json();
  expect(listed.dockets.every((row: { record_type: string }) => row.record_type === "trademark"), "Only national dockets are listed").toBe(true);
  expect(listed.dockets.map((row: { id: string }) => row.id)).not.toContain(target.madridDocketId);
  expect(listed.dockets.map((row: { id: string }) => row.id), "The target is beyond the first picker page").not.toContain(target.docketId);
  expect(listed.total_count).toBeGreaterThan(PICKER_PAGE);

  const picker = main.getByRole("combobox", { name: "IP docket" });
  await expect(picker).toBeEnabled();
  await expect(picker, "The page never selects a docket by itself").toHaveValue("");
  await expect(main.getByText("Select a docket to begin.", { exact: false })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Add registry identity" })).toHaveCount(0);
  await expect(main.getByText(/Showing 50 of [\d,]+ dockets/)).toBeVisible();
  if (mobile) await expectNoPageOverflow(page);

  const search = main.getByLabel("Find a docket by mark or number");
  const searched = page.waitForResponse(response => isDocketList(response, target.number));
  await search.fill(target.number);
  const found = await (await searched).json();
  expect(found.dockets.map((row: { id: string }) => row.id)).toContain(target.docketId);
  const core = page.waitForResponse(response => response.url().endsWith(`/api/ip/dockets/${target.docketId}/core-records`));
  await picker.selectOption(target.docketId);
  expect((await core).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`[?&]docket=${target.docketId}`));

  const record = main.getByRole("combobox", { name: "Legal record" });
  await expect(record).toBeEnabled();
  await record.selectOption(`application:${target.applicationId}`);

  // A -> B -> A (triage step 4): a record chosen on one docket never travels to another.
  const other = listed.dockets[0];
  await search.fill("");
  await expect(picker.locator(`option[value="${other.id}"]`)).toHaveCount(1);
  const otherCore = page.waitForResponse(response => response.url().endsWith(`/api/ip/dockets/${other.id}/core-records`));
  await picker.selectOption(other.id);
  expect((await otherCore).status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`[?&]docket=${other.id}`));
  await expect(record, "The other docket does not inherit the first docket's record").not.toHaveValue(`application:${target.applicationId}`);
  await search.fill(target.number);
  await expect(picker.locator(`option[value="${target.docketId}"]`)).toHaveCount(1);
  await picker.selectOption(target.docketId);
  await expect(page).toHaveURL(new RegExp(`[?&]docket=${target.docketId}`));
  await expect(record).toBeEnabled();
  await record.selectOption(`application:${target.applicationId}`);
  await expect(record).toHaveAccessibleDescription(new RegExp(`Application ${target.applicationIdentifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  const identifier = main.getByLabel("Identifier", { exact: true });
  await expect(identifier, "The identity is prefilled from the chosen record").toHaveValue(target.applicationIdentifier);
  await expect(main.getByRole("combobox", { name: "Identifier type" })).toHaveValue("application");
  expect(await deadSelects(page, main), "No enabled select without a real option").toEqual([]);
  expect(await internalFields(page), "No field asks for an internal id, hash or JSON").toEqual([]);

  const identity = stamp(mobile ? "B4-REG-M" : "B4-REG");
  await identifier.fill(identity);
  await main.getByLabel("Official source URL").fill(`https://tmrsearch.ipindia.gov.in/eregister/?b4=${encodeURIComponent(identity)}`);
  const add = main.getByRole("button", { name: "Add identity" });
  await add.scrollIntoViewIfNeeded();
  await expectOnScreen(add, "Add identity is reachable");
  const created = page.waitForResponse(response => response.url().endsWith(`/api/ip/dockets/${target.docketId}/registry-links`) && response.request().method() === "POST");
  await add.click();
  const linkResponse = await created;
  expect(linkResponse.status()).toBe(201);
  const link = await linkResponse.json();
  let liveLinkId: string | null = link.id;
  try {
    expect(link).toMatchObject({ docket_id: target.docketId, application_id: target.applicationId, proceeding_id: null, raw_identifier: identity, match_status: "candidate" });

    const listed = main.getByRole("button", { name: new RegExp(identity) });
    await listed.scrollIntoViewIfNeeded();
    await expectOnScreen(listed, "The new identity is listed under Registry identities");
    await listed.click();
    const heading = main.getByRole("heading", { name: identity });
    await expect(heading).toBeVisible();

    await main.getByLabel("Reason", { exact: true }).fill(`${identity}: identifier and office match the register page.`);
    const confirmed = page.waitForResponse(response => response.url().endsWith(`/api/ip/registry-links/${link.id}/match-decision`));
    await main.getByRole("button", { name: "Confirm", exact: true }).click();
    expect((await confirmed).status()).toBe(200);

    const mark = main.getByLabel("Mark as shown on the register");
    await expect(mark).toBeEnabled();
    await expect(main.getByLabel("Status on the register")).not.toHaveValue("");
    await mark.fill(identity);
    await main.getByLabel("Text shown on the register page (optional)").fill(`Word mark ${identity} as shown on the e-Register.`);
    expect(await internalFields(page), "Evidence is entered without JSON").toEqual([]);
    expect(await deadSelects(page, main)).toEqual([]);
    const recordEvidence = main.getByRole("button", { name: "Record register evidence" });
    await recordEvidence.scrollIntoViewIfNeeded();
    await expectOnScreen(recordEvidence, "Record register evidence is reachable");
    if (mobile) await expectNoPageOverflow(page);
    const snapshot = page.waitForResponse(response => response.url().endsWith(`/api/ip/registry-links/${link.id}/snapshots/manual`));
    await recordEvidence.click();
    const snapshotResponse = await snapshot;
    expect(snapshotResponse.status()).toBe(201);
    const evidence = await snapshotResponse.json();
    expect(evidence.attempt.external_call).toBe(false);
    expect(evidence.snapshot.raw_json).toMatchObject({ capture_method: "manual_register_form", source_text: expect.stringContaining(identity) });
    expect(evidence.diffs).toEqual([expect.objectContaining({ field_path: "/mark_name", change_kind: "added", after_value_json: identity })]);

    // Phones list one entry per change (decision buttons on screen); wider screens keep the table.
    // Rows read by field name and plain values; the register path is only technical detail.
    // The diff stacks into a list whenever its card is narrower than its table (B4-ADJ-13).
    const row = main.getByRole("row").or(main.getByRole("listitem"))
      .filter({ hasText: "Mark as shown on the register" }).filter({ visible: true });
    await row.scrollIntoViewIfNeeded();
    await expectOnScreen(row, "The register change is queued for review");
    await expect(row).toContainText(identity);
    await expect(row).not.toContainText(`"${identity}"`);
    await expect(row.getByText("/mark_name")).toBeHidden();
    await expect(main.getByText("No snapshots recorded.")).toHaveCount(0);
    await markPositive(info, "bug-012-registry-identity-and-structured-evidence", {
      local: rt.local, mobile, docket: target.docketId, link: link.id, snapshot: evidence.snapshot.id,
    });

    // Retire the test evidence: reject the queued change, then the identity.
    await main.locator("#review-reason").fill(`${identity}: test evidence, not a register change.`);
    const rejected = page.waitForResponse(response => /\/api\/ip\/registry-diffs\/[^/]+\/resolve$/.test(new URL(response.url()).pathname));
    const reject = row.getByRole("button", { name: "Reject" });
    // The confirmation toast (top-right, auto-dismissed) has been read before the next decision.
    await expect(page.locator("[data-sonner-toast]")).toHaveCount(0, { timeout: 15_000 });
    await reject.scrollIntoViewIfNeeded();
    await expectOnScreen(reject, "Reject is on screen next to the change");
    await reject.click();
    expect((await rejected).status()).toBe(200);
    await expect(main.getByText("No field changes are awaiting a decision.")).toBeVisible();
    await main.getByLabel("Reason", { exact: true }).fill(`${identity}: retiring the tester's verification identity.`);
    const retired = page.waitForResponse(response => response.url().endsWith(`/api/ip/registry-links/${link.id}/match-decision`));
    await main.getByRole("button", { name: "Retire", exact: true }).click();
    const retiredResponse = await retired;
    expect(retiredResponse.status()).toBe(200);
    expect((await retiredResponse.json()).match_status).toBe("retired");
    liveLinkId = null;
  } finally {
    if (liveLinkId) {
      // Cleanup only (the assertion already failed): never leave a live test identity.
      const current = await request.get(`${rt.api.origin}/api/ip/registry-links?limit=25&offset=0&docket_id=${target.docketId}`, { headers: rt.headers });
      const items = current.ok() ? (await current.json()).items ?? [] : [];
      const live = items.find((row: { link: { id: string } }) => row.link.id === liveLinkId);
      if (live && live.link.match_status !== "retired") {
        await request.post(`${rt.api.origin}/api/ip/registry-links/${liveLinkId}/match-decision`, {
          headers: rt.headers, data: { expected_version: live.link.version, decision: "retire", reason: "B4 cleanup after a failed verification run." },
        });
      }
    }
  }

  // The deep link reopens the docket beyond the first page.
  await page.goto(`${rt.web.origin}/app/ip/registry?docket=${target.docketId}`);
  await expect(main.getByRole("combobox", { name: "IP docket" })).toHaveValue(target.docketId);
  await expect(main.getByRole("combobox", { name: "Legal record" })).toBeEnabled();

  // A Madrid record explains itself instead of offering an empty list.
  await page.goto(`${rt.web.origin}/app/ip/registry?docket=${target.madridDocketId}`);
  const notice = main.getByText("is a Madrid international record.", { exact: false });
  await expect(notice).toBeVisible();
  await notice.scrollIntoViewIfNeeded();
  await expectOnScreen(main.getByRole("link", { name: /Open the Madrid portfolio/ }), "The Madrid pointer is visible");
  await expect(main.getByRole("link", { name: /Open the Madrid portfolio/ })).toHaveAttribute("href", "/app/ip/madrid");
  await expect(main.getByRole("combobox", { name: "Legal record" })).toHaveCount(0);
  if (mobile) await expectNoPageOverflow(page);
}

test("BUG-012 Ram finds a docket beyond the first 50 by its number and records manual registry evidence through structured fields", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  const target = rt.local ? await seedLocalPortfolio(rt, request) : await findProductionTarget(rt, request);
  await journey(page, request, rt, target, info, false);
});

test("[local-only] BUG-012 an application-less docket says it cannot take an identity and links only to paths that create one", async ({ page, request, baseURL }) => {
  const rt = await prepareTester(page, request, baseURL);
  // Prerequisite through the API (creating a docket is not the workflow under test).
  const empty = await json(await request.post(`${rt.api.origin}/api/ip/dockets`, {
    headers: rt.headers,
    data: { title: stamp("B4 EMPTY DOCKET"), primary_identifier: stamp("EMPTY"), restricted: false, particulars: particulars("EMPTY") },
  }), "Local application-less docket", 201);
  const main = page.locator("main");
  const core = page.waitForResponse(response => response.url().endsWith(`/api/ip/dockets/${empty.id}/core-records`));
  await page.goto(`${rt.web.origin}/app/ip/registry?docket=${empty.id}`);
  const records = await (await core).json();
  expect([records.applications.length, records.proceedings.length]).toEqual([0, 0]);
  const status = main.getByText("has no trademark application, so it cannot take a registry identity", { exact: false });
  await expect(status).toBeVisible();
  await expect(status).toContainText("cannot add an application to an existing docket");
  await expect(main.getByRole("link", { name: "IP workspace (New trademark)" })).toHaveAttribute("href", "/app/ip");
  await expect(main.getByRole("link", { name: "Portfolio import" })).toHaveAttribute("href", "/app/ip/portfolio/imports");
  await expect(main.getByRole("combobox", { name: "Legal record" })).toBeDisabled();
  await expect(main.getByRole("button", { name: "Add identity" })).toBeDisabled();
  expect(await deadSelects(page, main)).toEqual([]);
});

test("BUG-012 [mobile] the registry journey works at phone width without horizontal scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(8 * 60_000);
  const rt = await prepareTester(page, request, baseURL, page.viewportSize() ?? { width: 393, height: 851 });
  expect(page.viewportSize()?.width).toBeLessThanOrEqual(400);
  const target = rt.local ? await seedLocalPortfolio(rt, request) : await findProductionTarget(rt, request);
  await journey(page, request, rt, target, info, true);
});
