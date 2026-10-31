/**
 * BUG-007 (Ram 2026-10-30, IP UJ-44 Matter relationships): on the IP docket
 * "Access and links" tab, the Matter picker rendered every Matter in an
 * unbounded popover (959 x 3214 px, unscrollable, off-screen at every size)
 * and silently capped the list at 100. The tester must be able to find a
 * Matter by typing, link it, see it listed, and retire the link, at desktop
 * and phone widths, with the panel using the full tab width.
 *
 * Both modes drive the real UI as the tester. Local runs bootstrap a fresh
 * test-legal-shaped tenant and add prerequisite volume (66 Matters with long,
 * code-like captions, plus one trademark docket) through the product API,
 * because neither Matter creation nor docket creation is under test here.
 * The Matter that gets linked is always created through the New matter
 * dialog and found by typing. Production uses Ram's real retained data (more
 * than 100 Matters) and the reported docket, selected by server identity.
 * Every run retires its link and disposes its stamped Matter.
 */
import { expect, test, type APIRequestContext, type Page, type Response } from "@playwright/test";

import {
  collectOpenPopoverOffenders, deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

// The docket in the production report, resolved by server identity.
const PROD_DOCKET_ID = "2cc78d06-8fc5-535b-b21f-75da52914233";
const LOCAL_VOLUME = 66;

type MatterRow = { id: string; matter_code: string; title: string; status: string; updated_at: string };

/** Status and body of a response the browser received (the UI request itself, not an oracle). */
async function uiJson<T>(response: Response, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

async function seedLocalVolume(rt: TesterRuntime, request: APIRequestContext) {
  const titles = [
    "Shivani Khullar & Anr. Vs Samir Bajpai & Ors - trademark infringement and passing off",
    "Isolated Calendar diagnostic CALDIAG-100dc57d-d4da-48c3-9398-568e8a67f784",
    "M/s Pine Labs Private Limited v. Registrar of Trade Marks and another (rectification)",
  ];
  for (let start = 0; start < LOCAL_VOLUME; start += 6) {
    await Promise.all(Array.from({ length: Math.min(6, LOCAL_VOLUME - start) }, async (_, offset) => {
      const index = start + offset;
      const code = index % 3 === 1
        ? `CALDIAG-${rt.run.replace(/\W+/g, "").slice(-12)}-${String(index).padStart(3, "0")}`
        : `VOL-${String(index).padStart(3, "0")}-${rt.run.replace(/\W+/g, "").slice(-10)}`;
      await json(await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
        title: `${titles[index % 3]} ${index}`, matter_code: code.slice(0, 40), practice_area: "Intellectual property",
        forum_level: "high_court", status: "intake",
      } }), `Local volume Matter ${index}`);
    }));
  }
}

async function resolveDocket(rt: TesterRuntime, request: APIRequestContext): Promise<string> {
  if (!rt.local) {
    const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${PROD_DOCKET_ID}`,
      { headers: rt.headers }), "Reported docket read");
    expect(docket.id).toBe(PROD_DOCKET_ID);
    return docket.id;
  }
  const created = await json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
    headers: rt.headers,
    data: {
      title: `PINE LABS ${rt.run}`, matter_id: null, restricted: false, asset_title: `PINE LABS ${rt.run}`,
      jurisdiction: "IN", office: "IP India", filing_phase: "draft", source_pending_identifier_allocation: false,
      application_number: {
        raw_value: `ML${Date.now()}`, source: "local prerequisite", effective_from: "2026-10-01", is_primary: true,
      },
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "PINE LABS", evidence_reference: "local:mark:bug007" },
        classes: [{ class_number: 36, specification: "Financial services" }], use_priority: null,
        parties: [{ role: "applicant", name: "Pine Labs Private Limited" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true,
          evidence_reference: "local:mark:bug007" }],
      },
    },
  }), "Local prerequisite docket", 201);
  return created.docket.id;
}

/** The tester creates the Matter to be linked through the New matter dialog. */
async function createMatterInUi(page: Page, rt: TesterRuntime, tap: boolean): Promise<MatterRow> {
  const label = stamp("ML");
  const code = label.replace(/\s+/g, "-").toUpperCase().slice(0, 40);
  await page.goto(`${rt.web.origin}/app/matters`);
  const trigger = page.getByTestId("new-matter-trigger").first();
  if (tap) await trigger.tap(); else await trigger.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(`${label} Shivani Khullar & Anr. Vs Samir Bajpai & Ors - trademark advisory`);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Intellectual property");
  const created = page.waitForResponse((row) =>
    new URL(row.url()).pathname === "/api/matters/" && row.request().method() === "POST");
  await dialog.getByRole("button", { name: /Create matter/i }).click();
  const matter = await uiJson<MatterRow>(await created, "UI Matter create");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter;
}

async function openLinkForm(page: Page, rt: TesterRuntime, docketId: string) {
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&view=access`);
  const panel = page.getByTestId("ip-matter-links-panel");
  await expect(panel).toBeVisible();
  const matterPage = page.waitForResponse((row) => {
    const url = new URL(row.url());
    return url.pathname === "/api/matters/" && !url.searchParams.has("q") && !url.searchParams.has("cursor");
  });
  await panel.getByRole("button", { name: "Link Matter" }).click();
  expect((await matterPage).status()).toBe(200);
  await expect(panel.getByLabel("Matter", { exact: true })).toBeEnabled();
  expect(await deadSelects(page, panel), "No enabled select without a real choice").toEqual([]);
  return panel;
}

/** Find by typing, link, see it listed (screen + API), then retire it. */
async function linkAndRetire(page: Page, rt: TesterRuntime, request: APIRequestContext, docketId: string, matter: MatterRow) {
  const panel = page.getByTestId("ip-matter-links-panel");
  const select = panel.getByLabel("Matter", { exact: true });

  // The role is chosen first: changing it clears the Matter choice.
  await panel.getByLabel("Role").click();
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await collectOpenPopoverOffenders(page), "Role list geometry").toEqual([]);
  await page.getByRole("option", { name: "Advisory", exact: true }).click();

  const searched = page.waitForResponse((row) => {
    const url = new URL(row.url());
    return url.pathname === "/api/matters/" && url.searchParams.get("q") === matter.matter_code;
  });
  await panel.getByLabel("Search Matters").fill(matter.matter_code);
  const page1 = await uiJson<{ matters: MatterRow[] }>(await searched, "Server-side Matter search");
  expect(page1.matters.map((row) => row.id)).toContain(matter.id);
  await expect(select.locator("option")).toHaveCount(1 + page1.matters.length);
  await select.selectOption(matter.id);

  const description = panel.locator(`[data-selected-option-value="${matter.id}"]`);
  await expect(description).toHaveText(new RegExp(`^${matter.matter_code} · `));
  await expect(description).toContainText(matter.title);
  await description.scrollIntoViewIfNeeded();
  await expectOnScreen(description, "The full caption of the chosen Matter is visible");
  expect(await select.getAttribute("aria-describedby")).toContain(await description.getAttribute("id"));
  await expectNoPageOverflow(page);

  const reason = `${stamp("BUG-007")} advisory reference for trademark counsel`;
  await panel.getByLabel("Reason").fill(reason);
  const posted = page.waitForResponse((row) =>
    row.url().endsWith(`/api/ip/dockets/${docketId}/matter-links`) && row.request().method() === "POST");
  await panel.getByRole("button", { name: "Add relationship" }).click();
  const created = await uiJson<{ id: string; matter_id: string }>(await posted, "Link create", 201);
  expect(created.matter_id).toBe(matter.id);
  const linkId = created.id;

  const row = panel.locator("li", { hasText: matter.matter_code });
  await expect(row.getByRole("link", { name: new RegExp(matter.matter_code) })).toHaveAttribute(
    "href", `/app/matters/${matter.id}`);
  await expect(row.getByText("Advisory", { exact: true })).toBeVisible();
  await row.scrollIntoViewIfNeeded();
  await expectOnScreen(row, "The new relationship is listed");
  const listed = await json<{ links: Array<{ id: string; matter_id: string; relation_role: string; retired_at: string | null }> }>(
    await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}/matter-links`, { headers: rt.headers }),
    "Link read-back");
  expect(listed.links.find((link) => link.id === linkId)).toMatchObject({
    matter_id: matter.id, relation_role: "advisory", retired_at: null,
  });

  await row.getByRole("button", { name: "Retire" }).first().click();
  await row.getByLabel("Retirement reason").fill(`${stamp("BUG-007")} acceptance run complete`);
  const retired = page.waitForResponse((r) => r.url().includes(`/matter-links/${linkId}/retire`));
  await row.getByRole("button", { name: "Retire" }).last().click();
  expect((await retired).status()).toBe(200);
  await expect(row.getByText("Retired", { exact: true })).toBeVisible();
  const after = await json<{ links: Array<{ id: string; retired_at: string | null }> }>(
    await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}/matter-links`, { headers: rt.headers }),
    "Retired link read-back");
  expect(after.links.find((link) => link.id === linkId)?.retired_at).toBeTruthy();
  return linkId;
}

async function disposeMatter(rt: TesterRuntime, request: APIRequestContext, matterId: string) {
  const current = await json<MatterRow>(await request.get(`${rt.api.origin}/api/matters/${matterId}`,
    { headers: rt.headers }), "Stamped Matter read");
  await json(await request.patch(`${rt.api.origin}/api/matters/${matterId}/lifecycle/status`, { headers: rt.headers,
    data: { to_status: "disposed", expected_from_status: current.status, expected_updated_at: current.updated_at,
      reason: "BUG-007 acceptance run cleanup" } }), "Stamped Matter disposal");
}

test("BUG-007 Ram finds a Matter by typing among 60+ Matters, links it and retires it at 1440x900", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  if (rt.local) await seedLocalVolume(rt, request);
  const docketId = await resolveDocket(rt, request);
  const matter = await createMatterInUi(page, rt, false);
  try {
    const panel = await openLinkForm(page, rt, docketId);
    const select = panel.getByLabel("Matter", { exact: true });

    // Unfiltered: one bounded page from more than 60 Matters, honestly labelled, with a way to the rest.
    await expect(select).toBeEnabled();
    expect(await select.evaluate((el) => el.tagName)).toBe("SELECT");
    await expect(select.locator("option")).toHaveCount(51);
    await expect(panel.getByText(/Showing the 50 most recently updated Matters/)).toBeVisible();
    const more = page.waitForResponse((row) => new URL(row.url()).searchParams.has("cursor"));
    await panel.getByRole("button", { name: "Load more Matters" }).click();
    expect((await more).status()).toBe(200);
    await expect.poll(() => select.locator("option").count()).toBeGreaterThan(61);

    // Typing reaches a Matter beyond the first page (the old picker capped the list silently).
    const oracle = await json<{ matters: MatterRow[] }>(await request.get(`${rt.api.origin}/api/matters/?limit=100`,
      { headers: rt.headers }), "Matter list oracle");
    expect(oracle.matters.length).toBeGreaterThan(60);
    const older = oracle.matters[oracle.matters.length - 1];
    const olderSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === older.matter_code);
    await panel.getByLabel("Search Matters").fill(older.matter_code);
    expect((await olderSearch).status()).toBe(200);
    await expect(select.locator(`option[value="${older.id}"]`)).toHaveCount(1);
    await panel.getByLabel("Search Matters").fill("");

    // The panel takes the full Access tab width at 1440, 1280 and 1024: never squeezed beside an empty cell.
    for (const width of [1440, 1280, 1024]) {
      await page.setViewportSize({ width, height: width === 1024 ? 768 : 900 });
      const tab = await page.getByTestId("ip-access-tab-panels").boundingBox();
      const box = await panel.boundingBox();
      const field = await select.boundingBox();
      expect(tab && box && field, `geometry at ${width}`).toBeTruthy();
      expect(box!.width, `panel width at ${width}`).toBeGreaterThan(tab!.width - 2);
      expect(field!.width, `Matter field width at ${width}`).toBeGreaterThan(300);
      await expectNoPageOverflow(page);
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    await linkAndRetire(page, rt, request, docketId, matter);
    await markPositive(test.info(), "bug-007-desktop-link-retire", { local: rt.local, docketId, matterId: matter.id });
  } finally {
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});

test("BUG-007 [mobile] Ram finds, links and retires a Matter on a phone without overflow", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  if (rt.local) await seedLocalVolume(rt, request);
  const docketId = await resolveDocket(rt, request);
  const matter = await createMatterInUi(page, rt, true);
  try {
    const panel = await openLinkForm(page, rt, docketId);
    const select = panel.getByLabel("Matter", { exact: true });
    await expect(select).toBeEnabled();
    await expect(panel.getByText(/Showing the 50 most recently updated Matters/)).toBeVisible();
    await expectNoPageOverflow(page);
    const box = await select.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);

    await linkAndRetire(page, rt, request, docketId, matter);
    await expectNoPageOverflow(page);
    await markPositive(test.info(), "bug-007-mobile-link-retire", { local: rt.local, docketId, matterId: matter.id });
  } finally {
    await disposeMatter(rt, request, matter.id);
    await rt.release();
  }
});
