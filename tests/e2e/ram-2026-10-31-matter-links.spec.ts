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
 * code-like captions, through the product's bulk Matter import, plus one
 * trademark docket through the product API), because neither Matter creation
 * nor docket creation is under test here. The Matter that gets linked is
 * always created through the New matter dialog and found by typing.
 * Production uses Ram's real retained data (more than 100 Matters) and the
 * reported docket, selected by server identity. Every run retires its link
 * (also after a failure) and disposes its stamped, neutrally named Matter.
 */
import { expect, test, type APIRequestContext, type Locator, type Page, type Response } from "@playwright/test";

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
type LinkRow = { id: string; matter_id: string; relation_role: string; retired_at: string | null; updated_at: string };
/** What a run created, so cleanup can undo it even after a failure. */
type Created = { linkId?: string };

/** Status and body of a response the browser received (the UI request itself, not an oracle). */
async function uiJson<T>(response: Response, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

/** Local prerequisite volume through the product's bulk Matter import (preview, then commit). */
async function seedLocalVolume(rt: TesterRuntime, request: APIRequestContext) {
  const titles = [
    "Shivani Khullar & Anr. Vs Samir Bajpai & Ors - trademark infringement and passing off",
    "Isolated Calendar diagnostic CALDIAG-100dc57d-d4da-48c3-9398-568e8a67f784",
    "M/s Pine Labs Private Limited v. Registrar of Trade Marks and another (rectification)",
  ];
  const run = rt.run.replace(/\W+/g, "");
  const rows = Array.from({ length: LOCAL_VOLUME }, (_, index) => {
    const code = index % 3 === 1
      ? `CALDIAG-${run.slice(-12)}-${String(index).padStart(3, "0")}`
      : `VOL-${String(index).padStart(3, "0")}-${run.slice(-10)}`;
    return [`${titles[index % 3]} ${index}`, code.slice(0, 40), "Intellectual Property", "intake", "High Court"]
      .map(csvCell).join(",");
  });
  const preview = await json<{ id: string; valid_rows: number; invalid_rows: number }>(
    await request.post(`${rt.api.origin}/api/matters/imports/preview`, {
      headers: rt.headers,
      multipart: { file: {
        name: `bug-007-volume-${run.slice(-10)}.csv`,
        mimeType: "text/csv",
        buffer: Buffer.from(["Matter Title,Matter Code,Practice Area,Matter Status,Forum", ...rows].join("\n"), "utf8"),
      } },
      timeout: 120_000,
    }), "Local volume import preview");
  expect(preview.valid_rows, "every volume row validates").toBe(LOCAL_VOLUME);
  expect(preview.invalid_rows).toBe(0);
  const committed = await json<{ created_matter_ids: string[] }>(
    await request.post(`${rt.api.origin}/api/matters/imports/${preview.id}/commit`, { headers: rt.headers, timeout: 120_000 }),
    "Local volume import commit");
  expect(committed.created_matter_ids).toHaveLength(LOCAL_VOLUME);
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

/** The tester creates the Matter to be linked through the New matter dialog (neutral synthetic caption). */
async function createMatterInUi(page: Page, rt: TesterRuntime, tap: boolean): Promise<MatterRow> {
  const label = stamp("ML");
  const code = label.replace(/\s+/g, "-").toUpperCase().slice(0, 40);
  await page.goto(`${rt.web.origin}/app/matters`);
  const trigger = page.getByTestId("new-matter-trigger").first();
  if (tap) await trigger.tap(); else await trigger.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(`${label} BUG-007 synthetic acceptance Matter, disposed after the run`);
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

/** Choose an option without typing a search, and prove its full caption is on screen. */
async function chooseUnfiltered(page: Page, panel: Locator, select: Locator, pick: "longest" | "last"): Promise<string> {
  const value = await select.evaluate((element, mode) => {
    const enabled = Array.from((element as HTMLSelectElement).options).filter((option) => option.value && !option.disabled);
    if (mode === "last") return enabled[enabled.length - 1]?.value ?? "";
    return enabled.reduce((best, option) => (option.text.length > best.text.length ? option : best), enabled[0])?.value ?? "";
  }, pick);
  expect(value, `an enabled ${pick} option`).toBeTruthy();
  await select.selectOption(value);
  const description = panel.locator(`[data-selected-option-value="${value}"]`);
  await description.scrollIntoViewIfNeeded();
  await expectOnScreen(description, `The full caption of the ${pick} unfiltered choice is visible`);
  const box = await description.boundingBox();
  const width = page.viewportSize()!.width;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  await expectNoPageOverflow(page);
  return value;
}

/** Find by typing, choose the Matter, then the Role (the Matter survives), link, see it listed, retire it. */
async function linkAndRetire(
  page: Page, rt: TesterRuntime, request: APIRequestContext, docketId: string, matter: MatterRow,
  created: Created, previouslyChosen: string,
) {
  const panel = page.getByTestId("ip-matter-links-panel");
  const select = panel.getByLabel("Matter", { exact: true });

  const searched = page.waitForResponse((row) => {
    const url = new URL(row.url());
    return url.pathname === "/api/matters/" && url.searchParams.get("q") === matter.matter_code;
  });
  await panel.getByLabel("Search Matters").fill(matter.matter_code);
  const page1 = await uiJson<{ matters: MatterRow[] }>(await searched, "Server-side Matter search");
  expect(page1.matters.map((row) => row.id)).toContain(matter.id);
  // The server's results, plus the earlier choice, which stays listed until it is changed.
  const keptEarlier = page1.matters.some((row) => row.id === previouslyChosen) ? 0 : 1;
  await expect(select.locator("option")).toHaveCount(1 + page1.matters.length + keptEarlier);
  await select.selectOption(matter.id);

  const description = panel.locator(`[data-selected-option-value="${matter.id}"]`);
  await expect(description).toHaveText(new RegExp(`^${matter.matter_code} · `));
  await expect(description).toContainText(matter.title);

  // Role after Matter, the order of the form: the chosen Matter and its caption survive.
  await panel.getByLabel("Role").click();
  await expect(page.getByRole("listbox")).toBeVisible();
  expect(await collectOpenPopoverOffenders(page), "Role list geometry").toEqual([]);
  await page.getByRole("option", { name: "Advisory", exact: true }).click();
  await expect(select).toHaveValue(matter.id);
  await expect(description).toHaveText(new RegExp(`^${matter.matter_code} · `));
  await expect(select).not.toHaveAttribute("aria-invalid", "true");
  await description.scrollIntoViewIfNeeded();
  await expectOnScreen(description, "The full caption of the chosen Matter is visible after the Role change");
  expect(await select.getAttribute("aria-describedby")).toContain(await description.getAttribute("id"));
  await expectNoPageOverflow(page);

  const reason = `${stamp("BUG-007")} advisory reference for trademark counsel`;
  await panel.getByLabel("Reason").fill(reason);
  const posted = page.waitForResponse((row) =>
    row.url().endsWith(`/api/ip/dockets/${docketId}/matter-links`) && row.request().method() === "POST");
  await panel.getByRole("button", { name: "Add relationship" }).click();
  const link = await uiJson<{ id: string; matter_id: string }>(await posted, "Link create", 201);
  created.linkId = link.id;
  expect(link.matter_id).toBe(matter.id);

  const row = panel.locator("li", { hasText: matter.matter_code });
  await expect(row.getByRole("link", { name: new RegExp(matter.matter_code) })).toHaveAttribute(
    "href", `/app/matters/${matter.id}`);
  await expect(row.getByText("Advisory", { exact: true })).toBeVisible();
  await row.scrollIntoViewIfNeeded();
  await expectOnScreen(row, "The new relationship is listed");
  const listed = await json<{ links: LinkRow[] }>(
    await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}/matter-links`, { headers: rt.headers }),
    "Link read-back");
  expect(listed.links.find((item) => item.id === link.id)).toMatchObject({
    matter_id: matter.id, relation_role: "advisory", retired_at: null,
  });

  await row.getByRole("button", { name: "Retire" }).first().click();
  await expect(row.getByText("At least 8 characters. Recorded in the audit trail.")).toBeVisible();
  await row.getByLabel("Retirement reason").fill(`${stamp("BUG-007")} acceptance run complete`);
  const retired = page.waitForResponse((r) => r.url().includes(`/matter-links/${link.id}/retire`));
  await row.getByRole("button", { name: "Retire" }).last().click();
  expect((await retired).status()).toBe(200);
  await expect(row.getByText("Retired", { exact: true })).toBeVisible();
  const after = await json<{ links: LinkRow[] }>(
    await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}/matter-links`, { headers: rt.headers }),
    "Retired link read-back");
  expect(after.links.find((item) => item.id === link.id)?.retired_at).toBeTruthy();
}

/** Undo what the run created: retire a link a failure left active, then dispose the stamped Matter. */
async function cleanUp(rt: TesterRuntime, request: APIRequestContext, docketId: string, matterId: string, created: Created) {
  if (created.linkId) {
    const links = await json<{ links: LinkRow[] }>(await request.get(
      `${rt.api.origin}/api/ip/dockets/${docketId}/matter-links`, { headers: rt.headers }), "Cleanup link read");
    const open = links.links.find((item) => item.id === created.linkId && item.retired_at === null);
    if (open) {
      const docket = await json<{ updated_at: string }>(await request.get(
        `${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }), "Cleanup docket read");
      await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/matter-links/${open.id}/retire`, {
        headers: rt.headers,
        data: { reason: "BUG-007 acceptance run cleanup", expected_link_updated_at: open.updated_at,
          expected_docket_updated_at: docket.updated_at },
      }), "Cleanup link retire");
    }
  }
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
  const created: Created = {};
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
    // Choosing without typing works too: the last loaded Matter, from the second page.
    await chooseUnfiltered(page, panel, select, "last");

    // Typing reaches a Matter beyond the first page (the old picker capped the list silently).
    const oracle = await json<{ matters: MatterRow[] }>(await request.get(`${rt.api.origin}/api/matters/?limit=100`,
      { headers: rt.headers }), "Matter list oracle");
    expect(oracle.matters.length).toBeGreaterThan(60);
    const older = oracle.matters[oracle.matters.length - 1];
    const olderSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === older.matter_code);
    await panel.getByLabel("Search Matters").fill(older.matter_code);
    expect((await olderSearch).status()).toBe(200);
    await expect(select.locator(`option[value="${older.id}"]`)).toHaveCount(1);
    await select.selectOption(older.id);
    await panel.getByLabel("Search Matters").fill("");

    // The panel takes the full Access tab width from 1440 down to tablet: never squeezed beside an empty cell.
    for (const width of [1440, 1280, 1024, 768]) {
      await page.setViewportSize({ width, height: width <= 1024 ? 768 : 900 });
      const tab = await page.getByTestId("ip-access-tab-panels").boundingBox();
      const box = await panel.boundingBox();
      const field = await select.boundingBox();
      expect(tab && box && field, `geometry at ${width}`).toBeTruthy();
      expect(box!.width, `panel width at ${width}`).toBeGreaterThan(tab!.width - 2);
      expect(field!.width, `Matter field width at ${width}`).toBeGreaterThan(300);
      await expectNoPageOverflow(page);
    }
    await page.setViewportSize({ width: 1440, height: 900 });

    await linkAndRetire(page, rt, request, docketId, matter, created, older.id);
    await markPositive(test.info(), "bug-007-desktop-link-retire", { local: rt.local, docketId, matterId: matter.id });
  } finally {
    await cleanUp(rt, request, docketId, matter.id, created);
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
  const created: Created = {};
  try {
    const panel = await openLinkForm(page, rt, docketId);
    const select = panel.getByLabel("Matter", { exact: true });
    await expect(select).toBeEnabled();
    await expect(panel.getByText(/Showing the 50 most recently updated Matters/)).toBeVisible();
    await expectNoPageOverflow(page);
    const box = await select.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);

    // The longest code-like caption, chosen without a search, wraps inside a 393 px screen.
    const longest = await chooseUnfiltered(page, panel, select, "longest");

    await linkAndRetire(page, rt, request, docketId, matter, created, longest);
    await expectNoPageOverflow(page);
    await markPositive(test.info(), "bug-007-mobile-link-retire", { local: rt.local, docketId, matterId: matter.id });
  } finally {
    await cleanUp(rt, request, docketId, matter.id, created);
    await rt.release();
  }
});

// The same picker grants portal access to a Matter. Local-only: Ram's portal:invite capability in
// test-legal is not established, and the journey never sends an invite.
test("BUG-007 [mobile] [local-only] portal invite Matter grant: Enter in the search never sends the invite, and the picker fits a phone", async ({
  page, request, baseURL,
}) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  const first = await createMatterInUi(page, rt, true);
  const second = await createMatterInUi(page, rt, true);
  const invites: string[] = [];
  page.on("request", (row) => {
    if (row.url().includes("/api/admin/portal/invitations")) invites.push(`${row.method()} ${row.url()}`);
  });
  try {
    await page.goto(`${rt.web.origin}/app/admin`);
    const select = page.getByLabel("Matter grant", { exact: true });
    const search = page.getByLabel("Search Matters to grant");
    await page.getByTestId("portal-invite-name").fill("Acceptance Counsel");
    await page.getByTestId("portal-invite-email").fill(`bug007-${rt.run.replace(/\W+/g, "").slice(-10)}@example.invalid`);

    const firstSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === first.matter_code);
    await search.fill(first.matter_code);
    expect((await firstSearch).status()).toBe(200);
    await select.selectOption(first.id);
    await expect(page.getByTestId("portal-invite-submit")).toBeEnabled();

    // Switching Matters starts with a search; Enter searches at once and never grants the earlier Matter.
    const secondSearch = page.waitForResponse((row) => new URL(row.url()).searchParams.get("q") === second.matter_code);
    await search.fill(second.matter_code);
    await search.press("Enter");
    expect((await secondSearch).status()).toBe(200);
    await expect(select.locator(`option[value="${second.id}"]`)).toHaveCount(1);
    expect(invites, "Enter in the Matter search must not send a portal invite").toEqual([]);
    await expect(select).toHaveValue(first.id);

    await select.selectOption(second.id);
    const description = page.locator(`[data-selected-option-value="${second.id}"]`);
    await expect(description).toHaveText(new RegExp(`^${second.matter_code} · `));
    await description.scrollIntoViewIfNeeded();
    await expectOnScreen(description, "The full caption of the granted Matter is visible");
    const box = await select.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    await expectNoPageOverflow(page);
    expect(invites).toEqual([]);
    await markPositive(test.info(), "bug-007-mobile-portal-grant-picker", { local: rt.local, matterId: second.id });
  } finally {
    for (const matter of [first, second]) await cleanUp(rt, request, "", matter.id, {});
    await rt.release();
  }
});
