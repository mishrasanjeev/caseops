/** BUG013: real reported Acts, exact release text, attachment and reload. */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";

const BASE = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3100";
const LOCAL = ["127.0.0.1", "localhost"].includes(new URL(BASE).hostname);
const API = process.env.PROD_API_BASE_URL || (LOCAL
  ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT || "8000"}` : "https://api.caseops.ai");
const RUN = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
const SLUG = LOCAL ? `ram10-${RUN}` : process.env.CASEOPS_RAM_PROD_SLUG || "";
const EMAIL = LOCAL ? `${SLUG}@example.com` : process.env.CASEOPS_RAM_PROD_EMAIL || "";
const PASSWORD = LOCAL ? "Ram10LocalFixture123!" : process.env.CASEOPS_RAM_PROD_PASSWORD || "";
const REPORTED_MATTER_ID = process.env.CASEOPS_RAM_PROD_MATTER_ID || "";
const REPORTED = [
  ["bsa-2023", "Section 63"], ["gst-cgst-2017", "Section 7"],
  ["consumer-protection-2019", "Section 107"], ["contract-1872", "Section 238"],
  ["crpc-1973", "Section 482"], ["hindu-marriage-1955", "Section 29"],
  ["iea-1872", "Section 65B"], ["ipc-1860", "Section 302"],
  ["income-tax-1961", "Section 4"],
] as const;
type Source = { statute_id: string; section_number: string; section_text: string; source_sha256: string; source_url: string; exact_source_version: string };
const sources: Source[] = JSON.parse(readFileSync("apps/api/src/caseops_api/scripts/seed_data/verified_india_code_sources.json", "utf8"));
let api: APIRequestContext;
let token = "";
const owned = new Set<string>();
const headers = () => ({ Authorization: `Bearer ${token}` });

async function login(page: Page) {
  await page.goto(`${BASE}/sign-in`);
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  const pending = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
  await page.locator('button[type="submit"]').click();
  const response = await pending;
  expect(response.status(), await response.text()).toBe(200);
  token = (await response.json()).access_token;
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe("Ram September 10 statute reference acceptance", () => {
  test.beforeAll(async () => {
    if (!SLUG || !EMAIL || !PASSWORD) throw new Error("CASEOPS_RAM_PROD_SLUG, CASEOPS_RAM_PROD_EMAIL and CASEOPS_RAM_PROD_PASSWORD are required.");
    api = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    if (LOCAL) {
      const response = await api.post(`${API}/api/bootstrap/company`, { data: {
        company_name: `Ram September 10 ${RUN}`, company_slug: SLUG, company_type: "law_firm",
        owner_full_name: "Ram Statute Tester", owner_email: EMAIL, owner_password: PASSWORD,
      } });
      expect(response.status(), await response.text()).toBe(200);
      token = (await response.json()).access_token;
    } else {
      expect(REPORTED_MATTER_ID, "CASEOPS_RAM_PROD_MATTER_ID must identify the reported Matter").toMatch(/^[0-9a-f-]{36}$/i);
      const expected = process.env.CASEOPS_EXPECTED_RELEASE_SHA || "";
      expect(expected).toMatch(/^[0-9a-f]{40}$/);
      for (const url of [`${API}/api/build`, `${BASE}/api/release-identity`]) {
        const response = await api.get(url);
        expect(response.status(), await response.text()).toBe(200);
        expect((await response.json()).release_sha).toBe(expected);
      }
    }
  });
  test.afterAll(async () => {
    try {
      for (const id of owned) {
        const response = await api.get(`${API}/api/matters/${id}`, { headers: headers() });
        expect(response.status(), await response.text()).toBe(200);
        const current = await response.json();
        if (current.status === "disposed") continue;
        const disposed = await api.patch(`${API}/api/matters/${id}/lifecycle/status`, {
          headers: headers(), data: { to_status: "disposed", expected_from_status: current.status,
            expected_updated_at: current.updated_at, reason: "Close owned September 10 statute fixture." },
        });
        expect(disposed.status(), await disposed.text()).toBe(200);
      }
    } finally { await api?.dispose(); }
  });

  for (const width of [393, 1280]) {
    for (const [id, number] of REPORTED) {
      test(`BUG013 ${id}: positive attach, exact source and persisted reload (${width}px)`, async ({ page }, info) => {
        await page.setViewportSize({ width, height: 900 });
        await login(page);
        const responseMatter = LOCAL
          ? await api.post(`${API}/api/matters/`, { headers: headers(), data: {
            title: `September 10 ${id} ${width}`, matter_code: `RAM10-${width}-${id}-${RUN}`,
            practice_area: "Civil", forum_level: "high_court",
          } })
          : await api.get(`${API}/api/matters/${REPORTED_MATTER_ID}`, { headers: headers() });
        expect(responseMatter.status(), await responseMatter.text()).toBe(200);
        const matter = await responseMatter.json();
        if (LOCAL) owned.add(matter.id);
        const matterUrl = `${BASE}/app/matters/${matter.id}/statutes`;
        await page.goto(matterUrl);
        await page.getByTestId("matter-statute-add-trigger").click();
        const picker = page.getByTestId("matter-statute-act-select");
        const option = picker.locator(`option[value="${id}"]`);
        await expect(option, "The reported Act must remain in the catalog").toBeAttached();
        const response = await api.get(`${API}/api/statutes/${id}/sections`, { headers: headers() });
        expect(response.status(), await response.text()).toBe(200);
        const payload = await response.json();
        // A missing edition is a failed positive acceptance, never a skipped or synthetic-law pass.
        expect(payload.verified_section_count, `${id}: complete source admission required`).toBeGreaterThan(0);
        const section = payload.sections.find((row: { section_number: string }) => row.section_number === number);
        expect(section, `${id} ${number}: positive verified provision`).toBeDefined();
        const pinned = sources.find(row => row.statute_id === id && row.section_number === number);
        expect(pinned, "The source must be owned by this exact release").toBeDefined();
        await expect(option).toBeEnabled();
        await picker.selectOption(id);
        const sections = page.getByTestId("matter-statute-section-select");
        await expect(sections.locator(`option[value="${section.id}"]`)).toBeEnabled();
        await sections.selectOption(section.id);
        const submit = page.getByTestId("matter-statute-add-submit");
        await expect(submit).toBeEnabled();
        for (const control of [picker, sections, submit]) {
          await expect(control).toBeVisible();
          const bounds = (await control.boundingBox())!;
          expect(bounds.width).toBeGreaterThan(90);
          expect(bounds.x).toBeGreaterThanOrEqual(0);
          expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
        }
        const saved = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matter.id}/statute-references` && r.request().method() === "POST");
        await submit.click();
        const result = await saved;
        expect(result.status(), await result.text()).toBe(201);
        await expect(page.getByText("Statute reference attached.", { exact: true })).toBeVisible();
        await expect(page.locator('[data-sonner-toast][data-type="error"]')).toHaveCount(0);
        await page.reload();
        const savedLink = page.getByTestId("matter-statute-refs-list").locator(`a[href="/app/statutes/${id}/sections/${encodeURIComponent(number)}"]`);
        await expect(savedLink).toBeVisible();
        if (LOCAL) await page.screenshot({ path: info.outputPath(`attached-${width}.png`), fullPage: true });
        await savedLink.click();
        await expect(page.getByRole("heading", { name: number, exact: true })).toBeVisible();
        const detail = await api.get(`${API}/api/statutes/${id}/sections/${encodeURIComponent(number)}`, { headers: headers() });
        expect(detail.status(), await detail.text()).toBe(200);
        const official = (await detail.json()).section;
        expect(official.verification_status).toBe("verified_official");
        expect(official.section_text).toBe(pinned!.section_text);
        expect(official.source_sha256).toBe(pinned!.source_sha256);
        expect(createHash("sha256").update(official.section_text).digest("hex")).toBe(pinned!.source_sha256);
        expect(official.exact_source_version).toBe(pinned!.exact_source_version);
        expect(official.section_url).toBe(pinned!.source_url);
        await expect(page.getByTestId("statute-section-text")).toHaveText(pinned!.section_text);
        if (["crpc-1973", "iea-1872", "ipc-1860"].includes(id)) {
          await expect(page.getByText(/Historical repealed-law edition/)).toBeVisible();
        }
        const guarded = `${API}/api/source-actions/targets/statute_section/${official.id}/open?origin=statute`;
        await expect(page.getByRole("link", { name: "Open source", exact: true })).toHaveAttribute("href", guarded);
        const opened = await page.request.get(guarded, { maxRedirects: 0 });
        expect(opened.status(), await opened.text()).toBe(307);
        expect(opened.headers().location).toBe(pinned!.source_url);
        expect(opened.headers()["cache-control"]).toBe("no-store");
        if (LOCAL) await page.screenshot({ path: info.outputPath(`source-${width}.png`), fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
        await page.goto(matterUrl);
        await page.reload();
        await expect(savedLink).toBeVisible();
      });
    }
  }
});
