/**
 * BUG-001 / BUG-002 (Ram, 2026-10-30): on /app/ip, "New trademark" must
 * visibly open the form, classes are chosen from the WIPO Nice catalogue as
 * rows (goods/services per class, Nice edition recorded), the readiness line
 * states truthfully why each IP feature is unavailable, and the Documents
 * tab's Classification offers the product-provisioned taxonomy so a real
 * upload works.
 *
 * Signed in as the tester through the real form (production: Ram on
 * test-legal; local: a fresh tenant entitled like test-legal). The docket is
 * created only through the UI with a clock+serial title and retired at the
 * end; the API is used only as an oracle and for that cleanup. The uploaded
 * document is then retired through the Documents tab's history view
 * (B4-ADJ-07), so a production run leaves no current record behind.
 */
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import {
  collectOpenPopoverOffenders, deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive,
  prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";
import { retireDocketByApi, retireDocumentByApi, retireDocumentThroughUi, runCleanup } from "./support/ip-documents";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type Feature = { feature_id: string; available: boolean; reason: string; blocked_reasons: string[] };

// Mirrors the grouping the page states: who can change each failing gate.
const GROUP: Record<string, string> = {
  unknown_feature: "rollout", rollout_disabled: "rollout", rollout_expired: "rollout",
  missing_entitlement: "entitlement",
  workspace_not_configured: "configuration", tenant_disabled: "configuration", readiness_test_failed: "configuration",
  missing_capability: "capability", incident_kill_switch: "incident",
};
const ORDER = ["rollout", "entitlement", "configuration", "capability", "incident"];
const PHRASE: Record<string, (n: number) => string> = {
  rollout: n => `${n} paused by CaseOps`,
  entitlement: n => `${n} not in your plan`,
  configuration: n => `${n} ${n === 1 ? "needs" : "need"} setup`,
  capability: n => `${n} your role cannot use`,
  incident: n => `${n} stopped by a risk incident`,
};

const TITLE: Record<string, string> = {
  rollout: "Paused by CaseOps.", entitlement: "Not in your plan.", configuration: "Needs setup.",
  capability: "Your role cannot use it.", incident: "Stopped by a risk incident.",
};

function expectedSummary(features: Feature[], manual: boolean): string | null {
  const blocked = features.filter(f => !f.available);
  if (blocked.length === 0) return null;
  const counts = ORDER.map(group => [group, blocked.filter(f => f.blocked_reasons.some(r => GROUP[r] === group)).length] as const)
    .filter(([, n]) => n > 0).map(([group, n]) => PHRASE[group](n));
  const noun = blocked.length === 1 ? "IP feature is" : "IP features are";
  return `${manual ? "Manual docketing is available. " : ""}${blocked.length} ${noun} unavailable: ${counts.join(", ")}.`;
}

async function retireDocket(request: APIRequestContext, rt: TesterRuntime, docketId: string) {
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Read docket for cleanup");
  const body = {
    expected_lifecycle_version: docket.lifecycle_version, to_status: "retired", effective_at: new Date().toISOString(),
    reason: `Ram batch-4 acceptance record ${rt.run}`, outcome: "test record retired", source: "manual_review",
    evidence_ref: `e2e:${rt.run}`, successor_docket_id: null, acknowledged_exception_codes: [] as string[],
    second_approver_membership_id: null, client_report_handling: "retain", linked_matter_handling: "not_linked",
  };
  const preview = await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle/preview`,
    { headers: rt.headers, data: body }), "Preview docket retirement");
  body.acknowledged_exception_codes = preview.blocker_codes ?? [];
  await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle`, { headers: rt.headers, data: body }),
    "Retire acceptance docket");
}

async function chooseClass(page: Page, row: number, query: string, option: RegExp) {
  const input = page.getByRole("combobox", { name: `Nice class, row ${row}` });
  await expect(input).toBeEnabled();
  await input.click();
  await input.fill(query);
  const listbox = page.getByRole("listbox");
  await expect(listbox).toBeVisible();
  expect(await collectOpenPopoverOffenders(page), "Nice class list stays inside the viewport").toEqual([]);
  await listbox.getByRole("option", { name: option }).click();
}

async function createTwoClassTrademark(page: Page, request: APIRequestContext, rt: TesterRuntime, mobile: boolean) {
  await page.goto(`${rt.web.origin}/app/ip`);
  await expect(page.getByRole("heading", { name: "Trademark docket" })).toBeVisible();

  // Readiness: the one-line summary is exactly what blocked_reasons says.
  const readiness = await json(await request.get(`${rt.api.origin}/api/ip/readiness`, { headers: rt.headers }), "Readiness oracle");
  const expected = expectedSummary(readiness.features, readiness.manual_docketing_available);
  await expect(page.getByText(/owner (integrations|legal-rules|product-ip|billing)/)).toHaveCount(0);
  const details = page.getByRole("button", { name: "Show details" });
  if (expected === null) {
    // Every IP feature is available, so the page has nothing to explain.
    await expect(page.getByTestId("ip-automation-summary")).toHaveCount(0);
    await expect(details).toHaveCount(0);
  } else {
    await expect(page.getByTestId("ip-automation-summary")).toHaveText(expected);
    await expect(details).toHaveCount(1);
    // Each unavailable feature lists every failing gate with who can change it.
    await details.click();
    for (const feature of (readiness.features as Feature[]).filter(f => !f.available)) {
      const row = page.getByTestId(`ip-automation-${feature.feature_id}`);
      await expect(row.locator("[data-reason]")).toHaveCount(feature.blocked_reasons.length);
      for (const reason of feature.blocked_reasons) {
        await expect(row.locator(`[data-reason="${reason}"]`)).toContainText(TITLE[GROUP[reason]]);
      }
      // Lawyers read what a role lacks, never a capability id.
      await expect(row).not.toContainText("ip:");
    }
    if (mobile) await expectNoPageOverflow(page);
    await page.getByRole("button", { name: "Hide details" }).click();
  }

  // BUG-001: the click visibly opens the form and focuses it, with no fill or scroll in between.
  const toggle = page.getByRole("button", { name: "New trademark", exact: true });
  await toggle.click();
  await expectOnScreen(page.getByRole("heading", { name: "New trademark application" }), "The opened form is on screen");
  await expect(page.getByLabel("Docket title", { exact: true })).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  if (mobile) await expectNoPageOverflow(page);

  const catalogue = await json(await request.get(`${rt.api.origin}/api/ip/nice-classes`, { headers: rt.headers }), "Nice catalogue oracle");
  const title = stamp(`BUG-001 TM ${mobile ? "mobile" : "desktop"}`);
  await page.getByLabel("Docket title", { exact: true }).fill(title);
  await page.getByLabel("Word mark", { exact: true }).fill(`RAMB4${mobile ? "M" : "D"}`);
  expect(await deadSelects(page, page.getByRole("region", { name: "New trademark application" })), "No dead select in the form").toEqual([]);

  // BUG-002: classes are chosen by heading from the catalogue, one row per class.
  await chooseClass(page, 1, "advertising", /^Class 35, services:/);
  await expect(page.locator("#ip-tm-class-0-selected-description")).toContainText("Advertising");
  await page.getByLabel("Goods and services, row 1").fill("Advertising; business management services");
  await page.getByRole("button", { name: "Add class row" }).click();
  await chooseClass(page, 2, "9", /^Class 9, goods:/);
  await page.getByLabel("Goods and services, row 2").fill("Downloadable software");
  await page.getByLabel("Applicant", { exact: true }).fill("Ram Batch Four Applicant LLP");
  await page.getByLabel("Representation evidence reference").fill(`attachment:${rt.run}`);
  if (mobile) await expectNoPageOverflow(page);

  const created = page.waitForResponse(r => new URL(r.url()).pathname === "/api/ip/trademark-applications/manual"
    && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create application" }).click();
  const response = await created;
  expect(response.status(), "Manual trademark create").toBe(201);
  const sent = response.request().postDataJSON();
  expect(sent.particulars.classes.map((row: { class_number: number; nice_edition: string }) => [row.class_number, row.nice_edition]))
    .toEqual([[35, catalogue.edition], [9, catalogue.edition]]);
  const docketId: string = (await response.json()).docket.id;

  try {
    const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Created docket oracle");
    expect(docket.title).toBe(title);
    expect(docket.current_particulars.classes_json).toEqual([
      { class_number: 35, specification: "Advertising; business management services", nice_edition: catalogue.edition },
      { class_number: 9, specification: "Downloadable software", nice_edition: catalogue.edition },
    ]);

    // The new docket is the selected record, on screen and focused.
    const heading = page.locator("#ip-docket-title");
    await expect(heading).toHaveText(title);
    await expect(heading).toBeFocused();
    await expectOnScreen(heading, "The created docket is on screen");
    await expect(page.getByTestId(`ip-docket-class-35`)).toContainText("Advertising; business management, organization");
    await expect(page.getByTestId(`ip-docket-class-9`)).toContainText(`Nice edition ${catalogue.edition}`);
    if (mobile) await expectNoPageOverflow(page);
    return { docketId, title };
  } catch (error) {
    await retireDocket(request, rt, docketId);
    throw error;
  }
}

// BUG-002 (Documents): Classification lists the provisioned taxonomy and a UI upload works.
async function uploadClassifiedDocument(
  page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, docketId: string, mobile: boolean,
  created: { documentId: string | null },
) {
  await page.getByRole("tab", { name: "Documents", exact: true }).click();
  await expect(page).toHaveURL(/[?&]tab=documents(?:&|$)/);
  const taxonomy = await json(await request.get(`${rt.api.origin}/api/ip/document-taxonomy`, { headers: rt.headers }), "Taxonomy oracle");
  const active = taxonomy.entries.filter((entry: { is_active: boolean }) => entry.is_active);
  expect(active.length, "An enabled IP workspace always has document classifications").toBeGreaterThanOrEqual(14);
  const classification = page.getByLabel("Classification", { exact: true });
  await expect(classification).toBeEnabled();
  const offered = await classification.locator("option:not([disabled])").evaluateAll(o => o.map(x => (x as HTMLOptionElement).value));
  expect(offered).toEqual(active.map((entry: { key: string }) => entry.key));
  if (mobile) await expectNoPageOverflow(page);

  const title = stamp(`BUG-002 evidence ${mobile ? "mobile" : "desktop"}`);
  await page.getByLabel("Original file", { exact: true }).setInputFiles({
    name: `bug-002-${Date.now()}.txt`, mimeType: "text/plain",
    buffer: Buffer.from(`Ram batch-4 classification evidence ${rt.run} `.repeat(20)),
  });
  await page.getByLabel("Title", { exact: true }).fill(title);
  await classification.selectOption(active[0].key);
  await page.getByLabel("Linked docket", { exact: true }).selectOption(docketId);
  await page.getByRole("button", { name: "Preview controlled name" }).click();
  await expect(page.getByText("Controlled name preview", { exact: true })).toBeVisible();
  if (mobile) await expectNoPageOverflow(page);
  const uploaded = page.waitForResponse(r => new URL(r.url()).pathname === "/api/ip/documents/upload" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Upload reviewed document" }).click();
  const upload = await uploaded;
  expect(upload.status(), "Document upload").toBe(200);
  const result = await upload.json();
  // Recorded before any further assertion, so failure-path cleanup can retire it.
  created.documentId = result.document?.id ?? null;
  expect(result.outcome).toBe("created");
  const documentId: string = result.document.id;
  await markPositive(info, `ip-documents-upload-${mobile ? "mobile" : "desktop"}`, {
    taxonomy: active.length, documentId, documentTitle: title, docketId, local: rt.local,
  });

  // ?tab= deep link opens the Documents tab directly; an unknown tab falls back to Docket.
  await page.goto(`${rt.web.origin}/app/ip?tab=documents`);
  await expect(page.getByRole("tab", { name: "Documents", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.goto(`${rt.web.origin}/app/ip?tab=unknown`);
  await expect(page.getByRole("tab", { name: "Docket", exact: true })).toHaveAttribute("aria-selected", "true");
  if (mobile) await expectNoPageOverflow(page);
  return documentId;
}

/** Create, upload, then retire both: the docket first, then its document through the UI. */
async function journey(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const { docketId } = await createTwoClassTrademark(page, request, rt, mobile);
  const created: { documentId: string | null } = { documentId: null };
  try {
    await markPositive(info, `ip-create-${mobile ? "mobile" : "desktop"}`, { docketId, local: rt.local });
    await uploadClassifiedDocument(page, request, rt, info, docketId, mobile, created);
    await retireDocket(request, rt, docketId);
    // The closed docket's document is reached through the history view, shown
    // read-only (no state change, new version or bulk selection), and retired there.
    expect(created.documentId, "The upload returned the created document").toBeTruthy();
    await retireDocumentThroughUi(page, rt, created.documentId as string,
      `Ram batch-4 acceptance upload ${rt.run} retired after its docket.`, { history: true, mobile, closedRecord: true });
    await markPositive(info, `ip-document-retired-${mobile ? "mobile" : "desktop"}`, {
      documentId: created.documentId, docketId, local: rt.local,
    });
  } finally {
    // No-ops when the journey passed: the docket and document are already retired.
    const documentId = created.documentId;
    await runCleanup([
      ["Retire the acceptance docket", () => retireDocketByApi(request, rt, docketId)],
      ["Retire the acceptance upload", documentId ? () => retireDocumentByApi(request, rt, documentId) : null],
    ]);
  }
}

test("BUG-001 BUG-002 Ram creates a two-class trademark that opens in view and records its Nice edition", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  await journey(page, request, rt, info, false);
});

test("BUG-001 BUG-002 [mobile] Ram creates a two-class trademark on a phone without horizontal scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, { width: 393, height: 851 });
  await journey(page, request, rt, info, true);
});
