import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";

type Matter = { id: string; status: string; updated_at: string; court_name: string;
  forum_catalog_entry_id: string; forum_district: string | null; forum_city: string | null };
type Event = {
  id: string; kind: string; occurs_on: string; matter_id: string;
  court_label: string | null; court_identity: string | null;
  forum_display_order: number | null; hearing_time: string | null;
};
type Forum = { id: string; forum_type: string; forum_level: string; name: string;
  district: string | null; display_order: number };

const web = process.env.PROD_BASE_URL ?? process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:3100";
const isLoopback = (value: string) => ["localhost", "127.0.0.1", "[::1]"].includes(new URL(value).hostname);
const webLocal = isLoopback(web);
const origin = process.env.PROD_API_BASE_URL ?? (webLocal
  ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}` : "https://api.caseops.ai");
const apiLocal = isLoopback(origin);
if ([web, origin].some(value => new URL(value).username || new URL(value).password)) {
  throw new Error("Credential-bearing acceptance origins are prohibited");
}
if (webLocal !== apiLocal) throw new Error("Mixed local/remote acceptance targets are prohibited");
const local = webLocal && apiLocal;
if (!local && (new URL(web).origin !== "https://caseops.ai" || new URL(origin).origin !== "https://api.caseops.ai")) {
  throw new Error("Production acceptance must use the authorized CaseOps origins");
}
const slug = process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal";
const email = process.env.CASEOPS_RAM_PROD_EMAIL ?? "ram@testfirm.com";
const password = process.env.CASEOPS_RAM_PROD_PASSWORD ?? process.env.CASEOPS_RAM_LOCAL_PASSWORD
  ?? (local ? "CalendarOct13Local!" : "");
const run = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
const now = new Date();
const day = (n: number) => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${n}`;
const dates = [day(15), day(16)];
let api: APIRequestContext;
let auth: Record<string, string>;
const matters: Matter[] = [];
const expectedCourt = new Map<string, { label: string; identity: string; order: number }>();

async function status(response: { status(): number; text(): Promise<string> }, value: number) {
  expect(response.status(), response.status() === value ? "" : await response.text()).toBe(value);
}

async function signIn(page: Page) {
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const signed = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await status(await signed, 200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe.serial("October 13 court Calendar acceptance", () => {
  test.beforeAll(async () => {
    expect(password, "Authorized test password must be supplied in production").not.toBe("");
    if (!local) expect(slug, "Production mutation is test-legal only").toBe("test-legal");
    api = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    const sha = local ? process.env.CASEOPS_RELEASE_SHA : process.env.CASEOPS_EXPECTED_RELEASE_SHA;
    expect(sha, "Exact accepted/serving SHA required").toMatch(/^[a-f0-9]{40}$/);
    for (const endpoint of [`${origin}/api/build`, `${web}/api/release-identity`]) {
      const identity = await api.get(endpoint);
      await status(identity, 200);
      expect((await identity.json()).release_sha).toBe(sha);
    }
    let login = await api.post(`${origin}/api/auth/login`, { data: { company_slug: slug, email, password } });
    if (local && login.status() === 401) {
      const created = await api.post(`${origin}/api/bootstrap/company`, { data: {
        company_name: "Local Calendar Acceptance", company_slug: slug, company_type: "law_firm",
        owner_full_name: "Calendar Acceptance", owner_email: email, owner_password: password,
      } });
      await status(created, 200);
      login = await api.post(`${origin}/api/auth/login`, { data: { company_slug: slug, email, password } });
    }
    await status(login, 200);
    auth = { ...noPaidProviderHeaders, Authorization: `Bearer ${(await login.json()).access_token}` };
    const catalog = await api.get(`${origin}/api/courts/forum-catalog`, { headers: auth });
    await status(catalog, 200);
    const entries = (await catalog.json()).entries as Forum[];
    const forums = ["supreme_court", "high_court", "district_court", "consumer_forum"]
      .map(kind => entries.find(entry => entry.forum_type === kind));
    expect(forums.every(Boolean), "Real configured SC/HC/DC/other catalog rows required").toBe(true);
    for (const [index, forum] of forums.entries()) {
      const saved = await api.post(`${origin}/api/matters/`, { headers: auth, data: {
        matter_code: `CAL13-${run}-${index}`, title: `Calendar court ${index} ${run}`,
        practice_area: "Civil", forum_level: forum!.forum_level, forum_catalog_entry_id: forum!.id,
      } });
      await status(saved, 200);
      const matter = await saved.json() as Matter;
      matters.push(matter);
      expect(matter.forum_catalog_entry_id).toBe(forum!.id);
      expect(matter.court_name).toBe(forum!.name);
      expect(matter.forum_district).toBe(forum!.district);
      const prefixes: Readonly<Record<string, string | undefined>> = {
        supreme_court: "SC", high_court: "HC", district_court: "DC",
      };
      const prefix = prefixes[forum!.forum_type];
      const parts = [forum!.forum_type === "district_court" ? matter.forum_district : null, matter.court_name]
        .filter((part): part is string => Boolean(part));
      const label = `${prefix ? `${prefix} - ` : ""}${[...new Set(parts)].join(", ")}`;
      const identity = [...new Set([...parts, matter.forum_city].filter((part): part is string => Boolean(part)))].join(", ");
      expectedCourt.set(matter.id, { label, identity, order: forum!.display_order });
      for (const date of dates) {
        // Reverse insertion proves time order, not accidental creation order.
        for (const time of ["10:30:00", "09:30:00"]) {
          const hearing = await api.post(`${origin}/api/matters/${matter.id}/hearings`, { headers: auth, data: {
            hearing_on: date, forum_name: forum!.name, purpose: `Next hearing ${run}`,
            time_status: "exact", hearing_time: time, timezone: "Asia/Kolkata",
          } });
          await status(hearing, 200);
        }
      }
    }
  });

  test.afterAll(async () => {
    if (!api) return;
    for (const matter of matters) {
      const current = await api.get(`${origin}/api/matters/${matter.id}`, { headers: auth });
      await status(current, 200);
      const row = await current.json() as Matter;
      if (row.status !== "disposed") {
        await status(await api.patch(`${origin}/api/matters/${row.id}/lifecycle/status`, { headers: auth, data: {
          to_status: "disposed", expected_from_status: row.status, expected_updated_at: row.updated_at,
          reason: "Complete isolated October 13 Calendar acceptance fixture",
        } }), 200);
      }
    }
    await api.dispose();
  });

  for (const width of [1280, 393]) {
    test(`saved court identities and every hidden event remain reachable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.setExtraHTTPHeaders(noPaidProviderHeaders);
      const response = await api.get(`${origin}/api/calendar/events`, { headers: auth, params: { from: dates[0], to: dates[1] } });
      await status(response, 200);
      const events = (await response.json()).events as Event[];
      const owned = events.filter(e => matters.some(m => m.id === e.matter_id));
      expect(owned).toHaveLength(16);
      for (const event of owned) {
        const expected = expectedCourt.get(event.matter_id)!;
        expect(event.court_label).toBe(expected.label);
        expect(event.court_identity).toBe(expected.identity);
        expect(event.forum_display_order).toBe(expected.order);
      }
      for (const date of dates) {
        const hearings = owned.filter(e => e.occurs_on === date);
        expect(hearings.map(e => e.forum_display_order)).toEqual(
          hearings.map(e => e.forum_display_order).sort((a, b) => a! - b!),
        );
        for (const matter of matters) {
          expect(hearings.filter(e => e.matter_id === matter.id).map(e => e.hearing_time))
            .toEqual(["09:30:00", "10:30:00"]);
        }
      }
      await signIn(page);
      await page.goto(`${web}/app/calendar`);
      for (const date of dates) {
        const expected = events.filter(e => e.occurs_on === date);
        const cell = page.getByTestId(`calendar-month-day-${date}`);
        await expect(cell.locator('[data-testid^="calendar-event-"]')).toHaveCount(3);
        expect(await cell.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes => nodes.map(n => n.getAttribute("data-testid"))))
          .toEqual(expected.slice(0, 3).map(e => `calendar-event-${e.id}`));
        await cell.getByRole("button", { name: `View all events on ${date}` }).click();
        const allDetails = page.getByRole("dialog");
        await expect(allDetails.getByRole("link")).toHaveCount(expected.length);
        for (const event of expected.filter(e => expectedCourt.has(e.matter_id))) {
          const link = allDetails.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toContainText(expectedCourt.get(event.matter_id)!.identity);
        }
        await allDetails.getByRole("button", { name: "Close", exact: true }).click();
        const trigger = cell.getByRole("button", { name: `Show ${expected.length - 3} more events on ${date}` });
        await expect(trigger).toBeVisible();
        await trigger.focus();
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog");
        await expect(dialog).toBeVisible();
        await expect(dialog.getByRole("link")).toHaveCount(expected.length - 3);
        expect(await dialog.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes => nodes.map(n => n.getAttribute("data-testid"))))
          .toEqual(expected.slice(3).map(e => `calendar-event-${e.id}`));
        for (const event of expected.slice(3).filter(e => owned.some(own => own.id === e.id))) {
          const link = dialog.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toContainText(event.court_label!);
          await expect(link).toContainText(event.court_identity!);
          await expect(link).toHaveAttribute("href", `/app/matters/${event.matter_id}/hearings`);
        }
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
        await expect(trigger).toBeFocused();
        await trigger.click();
        await expect(dialog).toBeVisible();
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
      }
      await page.reload();
      await expect(page.getByTestId(`calendar-month-day-${dates[0]}`).getByRole("button", { name: `View all events on ${dates[0]}` })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      // These controls must still work and Google connection state remains readable.
      await expect(page.getByTestId("calendar-google-panel")).toBeVisible();
      await page.getByTestId("calendar-view-week").click();
      await page.getByTestId("calendar-view-day").click();
      await page.getByTestId("calendar-view-month").click();
    });
  }
});
