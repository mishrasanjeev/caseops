/** J04/M03/US-007..009/FT-011..015: real saved notes, never a mocked workspace. */
import { randomUUID } from "node:crypto";
import type { APIResponse } from "@playwright/test";
import type { components } from "../../apps/web/lib/api/openapi-types";

import { expect, request, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";

type Note = components["schemas"]["MatterNoteRecord"];
type Matter = { id: string; matter_code: string; title: string; status: string; updated_at: string };
type Workspace = { matter: Matter; notes: Note[] };

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ mode: "serial", retries: 0 });

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing notes acceptance setup is not a skip.`);
  return value;
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object; private response omitted.`);
  }
  return value as Record<string, unknown>;
}

function stringField(value: Record<string, unknown>, field: string): string {
  if (!Object.hasOwn(value, field) || typeof value[field] !== "string" || !value[field]) {
    throw new Error(`Required ${field} must be a nonempty string; private response omitted.`);
  }
  return value[field];
}

async function response(operation: () => Promise<APIResponse>, label: string): Promise<APIResponse> {
  try { return await operation(); }
  catch { throw new Error(`${label} transport failed; no retry; private request details omitted.`); }
}

async function json(receipt: Pick<APIResponse, "status" | "json">, label: string): Promise<Record<string, unknown>> {
  expect(receipt.status(), `${label} must succeed without a retry`).toBe(200);
  let value: unknown;
  try { value = await receipt.json(); }
  catch { throw new Error(`${label} returned invalid JSON; private response omitted.`); }
  return record(value, label);
}

function matter(value: unknown): Matter {
  const row = record(value, "Matter");
  for (const key of ["id", "matter_code", "title", "status", "updated_at"]) stringField(row, key);
  return row as Matter;
}

function note(value: unknown): Note {
  const row = record(value, "Matter note");
  for (const key of ["id", "matter_id", "author_membership_id", "author_name", "author_role", "body", "created_at"]) {
    stringField(row, key);
  }
  timestamp(stringField(row, "created_at"));
  return row as Note;
}

function workspace(value: Record<string, unknown>): Workspace {
  if (!Array.isArray(value.notes)) throw new Error("Workspace notes must be an array, never null or omitted.");
  const parent = record(value.matter, "Workspace Matter");
  for (const key of ["client_name", "opposing_party", "description"]) {
    expect(Object.hasOwn(parent, key), `Nullable Matter ${key} remains a required response key`).toBe(true);
    expect(parent[key] === null, `Synthetic Matter ${key} remains explicitly null`).toBe(true);
  }
  return { matter: matter(parent), notes: value.notes.map(note) };
}

function timestamp(value: string): bigint {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?$/.exec(value);
  if (!match) throw new Error("Server note timestamp has an invalid shape.");
  // SQLite reloads known UTC persistence without an offset; keep raw values for equality.
  const wholeSecond = Date.parse(`${match[1]}${match[3] ?? "Z"}`);
  if (!Number.isFinite(wholeSecond)) throw new Error("Server note timestamp is invalid.");
  return BigInt(wholeSecond) * 1_000_000n + BigInt((match[2] ?? "").padEnd(9, "0"));
}

function newestFirst(left: Note, right: Note): number {
  const a = timestamp(left.created_at);
  const b = timestamp(right.created_at);
  return a === b ? (left.id < right.id ? 1 : left.id > right.id ? -1 : 0) : a < b ? 1 : -1;
}

test("NOTES22 newest three of four saved notes persist after reload at 1280px and 393px", async ({ page, baseURL }, info) => {
  if (!baseURL) throw new Error("Use the app, Docker or exact-release production config.");
  expect(info.config.workers, "Matter acceptance mutations require a serial producer").toBe(1);
  const web = new URL(baseURL);
  const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  const local = loopback(web);
  const api = new URL(local ? apiBaseUrl : required("PROD_API_BASE_URL"));
  if ([web, api].some(url => url.username || url.password || url.search || url.hash)
    || local !== loopback(api) || (local && web.hostname !== api.hostname)) {
    throw new Error("Mixed, credential-bearing or mismatched loopback acceptance origins are forbidden.");
  }
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Only canonical CaseOps production origins are authorized.");
  }
  const sha = required(local ? "CASEOPS_RELEASE_SHA" : "CASEOPS_EXPECTED_RELEASE_SHA");
  const release = () => assertPublicReleaseIdentity(
    [`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha,
  );
  const run = randomUUID();
  const credentials = local
    ? { company_slug: `notes22-${run}`, email: `notes22-${run}@example.com`, password: `Notes22!${randomUUID()}` }
    : { company_slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal",
        email: process.env.CASEOPS_RAM_PROD_EMAIL?.trim() || "ram@testfirm.com",
        password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (!local && credentials.company_slug !== "test-legal") throw new Error("Production notes mutations are test-legal only.");
  const client = await request.newContext({ storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: localTransportHeaders(api.origin) });
  let headers: Record<string, string> = localTransportHeaders(api.origin);
  const options = () => ({ headers, maxRetries: 0, maxRedirects: 0 });
  let saved: Matter | undefined;
  const matterCode = `NOTES22-${run}`;
  const title = `Synthetic recent notes ${run}`;
  const blocked = new Set<string>();
  try {
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await page.route("**/*", route => {
      const origin = new URL(route.request().url()).origin;
      if ([web.origin, api.origin].includes(origin)) return route.continue();
      blocked.add(origin);
      return route.abort("blockedbyclient");
    });
    await release();
    if (local) {
      await json(await response(() => client.post(`${api.origin}/api/bootstrap/company`, { ...options(), data: {
        company_name: "Isolated recent notes acceptance", company_slug: credentials.company_slug,
        company_type: "law_firm", owner_full_name: "Offline notes owner",
        owner_email: credentials.email, owner_password: credentials.password,
      } }), "Loopback fixture bootstrap"), "Loopback fixture bootstrap");
    }
    const login = await json(await response(() => client.post(`${api.origin}/api/auth/login`, {
      ...options(), data: credentials,
    }), "Normal QA login"), "Normal QA login");
    const token = stringField(login, "access_token");
    headers = { ...headers, Authorization: `Bearer ${token}` };
    const me = await json(await response(() => client.get(`${api.origin}/api/auth/me`, options()), "Authenticated QA context"), "Authenticated QA context");
    expect(stringField(record(me.company, "QA company"), "slug") === credentials.company_slug).toBe(true);
    expect(stringField(record(me.user, "QA user"), "email") === credentials.email).toBe(true);
    await release();
    saved = matter(await json(await response(() => client.post(`${api.origin}/api/matters/`, { ...options(), data: {
      matter_code: matterCode, title, status: "intake", practice_area: "Civil", forum_level: "advisory",
      client_name: null, opposing_party: null, description: null,
    } }), "Unique Intake Matter creation"), "Unique Intake Matter creation"));
    expect(saved.status).toBe("intake");
    const path = `/api/matters/${saved.id}`;
    const created: Note[] = [];
    for (const index of [1, 2, 3, 4]) {
      const body = `Synthetic NOTES22 note ${index} ${run}`;
      const added = note(await json(await response(() => client.post(`${api.origin}${path}/notes`, {
        ...options(), data: { body },
      }), "Single-attempt note admission"), "Single-attempt note admission"));
      expect(added.matter_id).toBe(saved.id);
      expect(added.body).toBe(body);
      created.push(added);
    }
    expect(new Set(created.map(row => row.id)).size).toBe(4);
    const expected = [...created].sort(newestFirst);
    const read = async () => workspace(await json(await response(
      () => client.get(`${api.origin}${path}/workspace`, options()), "Persisted notes workspace",
    ), "Persisted notes workspace"));
    const baseline = await read();
    expect(baseline.matter.id).toBe(saved.id);
    expect(baseline.notes.map(row => row.id)).toEqual(expected.map(row => row.id));
    for (const retained of baseline.notes) {
      expect(retained.body === created.find(row => row.id === retained.id)?.body).toBe(true);
    }
    const retainedBytes = JSON.stringify(baseline.notes);
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.company_slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    const signed = page.waitForResponse(receipt => new URL(receipt.url()).origin === api.origin
      && new URL(receipt.url()).pathname === "/api/auth/login" && receipt.request().method() === "POST");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    expect((await signed).status(), "Normal browser QA login").toBe(200);
    await page.waitForURL(/\/app(?:[/?]|$)/);
    await page.goto(`${web.origin}/app/matters/${saved.id}`);
    for (const width of [1280, 393]) {
      await page.setViewportSize({ width, height: 1000 });
      const loaded = page.waitForResponse(receipt => new URL(receipt.url()).origin === api.origin
        && new URL(receipt.url()).pathname === `${path}/workspace` && receipt.request().method() === "GET");
      await page.reload();
      const browserRead = workspace(await json(await loaded, "Reloaded browser workspace"));
      expect(JSON.stringify(browserRead.notes) === retainedBytes, "All four complete persisted note records survive browser reload").toBe(true);
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      const heading = page.getByRole("heading", { name: "Recent notes", exact: true });
      await expect(heading).toBeVisible();
      await heading.scrollIntoViewIfNeeded();
      const card = heading.locator("..").locator("..");
      const rows = card.getByRole("list").getByRole("listitem");
      await expect(rows).toHaveCount(3);
      await expect(rows.locator("p")).toHaveText(expected.slice(0, 3).map(row => row.body));
      for (const body of expected.slice(0, 3).map(row => row.body)) await expect(card.getByText(body, { exact: true })).toBeVisible();
      await expect(card.getByText(expected[3].body, { exact: true })).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1),
        "Recent notes must not widen the document").toBe(true);
      const rowBounds = await rows.evaluateAll(elements => elements.map(element => {
        const box = element.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom };
      }));
      for (let index = 0; index < 3; index++) {
        if (index > 0) expect(rowBounds[index].top, "Recent note rows do not overlap").toBeGreaterThanOrEqual(rowBounds[index - 1].bottom);
        const body = rows.nth(index).locator("p");
        await body.scrollIntoViewIfNeeded();
        const geometry = await body.evaluate(element => {
          const box = element.getBoundingClientRect();
          const parent = element.closest("li")!.getBoundingClientRect();
          const style = getComputedStyle(element);
          const metadata = Array.from(element.closest("li")!.querySelectorAll(":scope > div > span")).map(span => {
            const bounds = span.getBoundingClientRect();
            return { left: bounds.left, right: bounds.right, bottom: bounds.bottom,
              clipped: span.scrollWidth > span.clientWidth + 1 || span.scrollHeight > span.clientHeight + 1 };
          });
          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
          return { width: box.width, top: box.top, bottom: box.bottom,
            horizontalBounds: box.left >= parent.left && box.right <= parent.right
              && box.left >= 0 && box.right <= window.innerWidth + 1,
            verticalBounds: box.top >= parent.top && box.bottom <= parent.bottom
              && box.top >= 0 && box.bottom <= window.innerHeight + 1,
            clipped: element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1,
            fontSize: parseFloat(style.fontSize), lineHeight: parseFloat(style.lineHeight),
            unobscured: hit !== null && (hit === element || element.contains(hit)), metadata };
        });
        expect(geometry.width, "Each note body retains useful reading width").toBeGreaterThanOrEqual(160);
        expect(geometry.horizontalBounds && geometry.verticalBounds, "Each complete note remains within its row and viewport").toBe(true);
        expect(geometry.clipped, "Note text must wrap rather than clip").toBe(false);
        expect(geometry.unobscured, "No overlay may cover a visible note").toBe(true);
        expect(geometry.fontSize).toBeGreaterThanOrEqual(12);
        expect(geometry.lineHeight).toBeGreaterThanOrEqual(geometry.fontSize * 1.2);
        expect(geometry.metadata).toHaveLength(2);
        expect(geometry.metadata.every(item => !item.clipped && item.bottom <= geometry.top + 1),
          "Author and timestamp remain readable above the note body").toBe(true);
        expect(geometry.metadata[0].right, "Author and timestamp do not overlap").toBeLessThanOrEqual(geometry.metadata[1].left + 1);
      }
      expect(JSON.stringify((await read()).notes) === retainedBytes, "All four notes remain persisted after responsive readback").toBe(true);
      if (local) await info.attach(`NOTES22-recent-${width}px`, { body: await card.screenshot(), contentType: "image/png" });
    }
    expect(blocked.size, "No external browser requests are allowed").toBe(0);
    await release();
  } finally {
    try {
      if (saved) {
        await release();
        const current = matter(await json(await response(() => client.get(`${api.origin}/api/matters/${saved!.id}`, options()), "Owned fixture cleanup read"), "Owned fixture cleanup read"));
        expect(current.matter_code === matterCode && current.title === title, "Cleanup is restricted to this unique QA Matter").toBe(true);
        expect(current.status).toBe("intake");
        const disposed = matter(await json(await response(() => client.patch(`${api.origin}/api/matters/${saved!.id}/lifecycle/status`, {
          ...options(), data: { to_status: "disposed", expected_from_status: current.status,
            expected_updated_at: current.updated_at, reason: "Complete isolated October 22 notes acceptance fixture" },
        }), "Owned fixture lifecycle disposal"), "Owned fixture lifecycle disposal"));
        expect(disposed.status).toBe("disposed");
      }
    } finally { await client.dispose(); }
  }
});
