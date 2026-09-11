import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot } from "./support/env";
import { plusDays } from "./support/helpers";

const web = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:3100";
const api = process.env.PROD_API_BASE_URL || apiBaseUrl;
const local = ["127.0.0.1", "localhost"].includes(new URL(web).hostname);
const dockerAcceptance = local
  && Boolean(process.env.CASEOPS_E2E_DOCKER_PROJECT)
  && Boolean(process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE)
  && process.env.CASEOPS_E2E_HEARING_PROVIDER === "sep10-offline";

async function visibleMatter(page: Page, code: string, expectedDate: string | null, missingCourt: boolean) {
  for (const width of [393, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${web}/app/matters`);
    for (const reload of [false, true]) {
      if (reload) await page.reload();
      await page.locator("#matter-filter-q").fill(code);
      await page.getByRole("button", { name: /Apply/i }).click();
      const row = page.locator("tbody tr").filter({ hasText: code });
      await expect(row).toHaveCount(1);
      const heading = page.getByRole("columnheader", { name: /Next hearing/i });
      const column = await heading.evaluate(el => Array.from(el.parentElement!.children).indexOf(el));
      const cell = row.locator("td").nth(column);
      await cell.scrollIntoViewIfNeeded();
      await expect(cell).toBeVisible();
      if (expectedDate) {
        const formatted = await page.evaluate(value => new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }), expectedDate);
        await expect(cell.getByText(formatted, { exact: true })).toBeVisible();
      } else {
        await expect(cell.locator("span").first()).toHaveText(String.fromCharCode(8212));
      }
      if (missingCourt) {
        const action = cell.getByRole("link", { name: "Add court details for hearing sync" });
        await expect(action).toBeVisible();
        const bounds = await action.boundingBox();
        expect(bounds!.width).toBeGreaterThan(80);
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      }
      await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    }
    await page.screenshot({ path: test.info().outputPath(`hearing-${code}-${width}.png`), fullPage: true });
  }
}

function poll() {
  const project = process.env.CASEOPS_E2E_DOCKER_PROJECT;
  const file = process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE;
  if (!local || !project || !file || process.env.CASEOPS_E2E_HEARING_PROVIDER !== "sep10-offline") {
    throw new Error("The isolated September 10 hearing emulator and Docker project are required; paid polling is forbidden.");
  }
  const result = spawnSync("docker", ["compose", "--project-name", project, "--file", file, "exec", "-T", "api", "caseops-poll-tracked-cases", "--force"], { cwd: repoRoot, encoding: "utf8", timeout: 120_000 });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

test("BUG-014 scheduled CNR, combined registration and filing identities persist the nearest visible hearing", async ({ page, request }) => {
  test.skip(!dockerAcceptance, "Scheduled behavioral acceptance uses the offline emulator; host and production suites must not run it.");
  const suffix = randomUUID().slice(0, 8);
  const slug = `sep10-hearing-${suffix}`;
  const email = `${slug}@example.com`;
  const password = `Local-${randomUUID()}!`;
  const bootstrap = await request.post(`${api}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
    company_name: slug, company_slug: slug, company_type: "law_firm", owner_full_name: "Hearing QA", owner_email: email, owner_password: password,
  } });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${(await bootstrap.json()).access_token}` };
  const fixtures: { id: string; code: string; mode: string }[] = [];
  for (const mode of ["cnr", "case", "filing", "ambiguous", "missing-court"]) {
    const code = `${mode}-${suffix}`;
    const created = await request.post(`${api}/api/matters/`, { headers, data: {
      title: `September 10 ${mode}`, matter_code: code, practice_area: "litigation", forum_level: "high_court", status: "active",
      court_name: mode === "missing-court" ? null : "Delhi High Court",
      client_name: "Local Docker Petitioner", opposing_party: "Local Docker Respondent", opposing_counsel: "Local Docker Counsel",
    } });
    expect(created.status(), await created.text()).toBe(200);
    const matter = await created.json();
    const edited = await request.patch(`${api}/api/matters/${matter.id}`, { headers, data: {
      expected_updated_at: matter.updated_at,
      ...(mode === "cnr"
        ? { cnr_number: "DLHC010081232026" }
        : mode === "filing"
          ? { filing_number: "421/2026" }
          : {
              case_number:
                mode === "ambiguous"
                  ? "WP(C) 889/2026"
                  : "WP(C) 8123/2026",
            }),
    } });
    expect(edited.status(), await edited.text()).toBe(200);
    fixtures.push({ id: matter.id, code, mode });
  }
  const legacyMatter = fixtures.find(fixture => fixture.mode === "missing-court")!;
  const legacy = await request.post(`${api}/api/case-tracking/bookmarks`, { headers, data: {
    provider: "ecourtsindia", case_number: "WP(C) 8123/2026", case_title: "Legacy incomplete auto-link",
    matter_id: legacyMatter.id, metadata: { source: "matter_create_auto_link" },
  } });
  expect(legacy.status(), await legacy.text()).toBe(201);
  const legacyBookmark = await legacy.json();
  expect(legacyBookmark.tracked_case.manual_refresh_allowed).toBe(false);
  const before = await request.get(`${api}/api/case-tracking/bookmarks`, { headers });
  expect(before.status()).toBe(200);
  const beforeRows = (await before.json()).bookmarks;
  expect(beforeRows).toHaveLength(1);
  expect(beforeRows[0].matter_id).toBe(legacyMatter.id);
  poll();
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  for (const fixture of fixtures) {
    const response = await request.get(`${api}/api/matters/${fixture.id}`, { headers });
    expect(response.status()).toBe(200);
    const stored = await response.json();
    const expected = ["ambiguous", "missing-court"].includes(fixture.mode) ? null : plusDays(7);
    expect(stored.next_hearing_on).toBe(expected);
    expect(stored.status).toBe("active");
    expect(stored.is_active).toBe(true);
    expect(stored.lifecycle_version).toBe(0);
    await visibleMatter(page, fixture.code, expected, fixture.mode === "missing-court");
  }
  const current = await request.get(`${api}/api/matters/${legacyMatter.id}`, { headers });
  expect(current.status()).toBe(200);
  const correction = await request.patch(`${api}/api/matters/${legacyMatter.id}`, { headers, data: {
    court_name: "Delhi High Court", expected_updated_at: (await current.json()).updated_at,
  } });
  expect(correction.status(), await correction.text()).toBe(200);
  poll();
  const recovered = await request.get(`${api}/api/case-tracking/bookmarks`, { headers });
  expect(recovered.status()).toBe(200);
  const recoveredRows = (await recovered.json()).bookmarks.filter((row: { matter_id: string }) => row.matter_id === legacyMatter.id);
  expect(recoveredRows).toHaveLength(1);
  expect(recoveredRows[0].id).toBe(legacyBookmark.id);
  expect(recoveredRows[0].tracked_case.next_hearing_on).toBe(plusDays(7));
  await visibleMatter(page, legacyMatter.code, plusDays(7), false);
});

test("BUG-014 reported production Matters explain missing court identity without spending", async ({ page, request }) => {
  test.skip(local, "This read-only acceptance identifies the actual reported production Matters.");
  const slug = process.env.CASEOPS_RAM_PROD_SLUG;
  const email = process.env.CASEOPS_RAM_PROD_EMAIL;
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD;
  if (!slug || !email || !password) throw new Error("Production read-only credentials must be supplied at runtime.");
  await page.setExtraHTTPHeaders(noPaidProviderHeaders);
  const login = await request.post(`${api}/api/auth/login`, { headers: noPaidProviderHeaders, data: { company_slug: slug, email, password } });
  expect(login.status()).toBe(200);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${(await login.json()).access_token}` };
  const policy = await request.get(`${api}/api/case-tracking/status`, { headers });
  expect(policy.status()).toBe(200);
  expect((await policy.json()).scheduled_sync_disabled_reason).toBe("configured_test_tenant");
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  for (const [code, id] of [
    ["5977", "a543e55c-bcc9-4f8c-8341-b1f227afde0b"], ["5967", "dec98199-7055-4b00-aabe-ac432503774e"],
    ["5927", "d60c6ebe-2a47-4f75-a062-b91635801d58"],
  ]) {
    const response = await request.get(`${api}/api/matters/${id}`, { headers });
    expect(response.status()).toBe(200);
    const stored = await response.json();
    expect(stored.matter_code).toBe(code);
    expect(stored.cnr_number).toBeNull();
    expect(stored.court_name).toBeNull();
    expect(stored.next_hearing_on).toBeNull();
    expect(stored.status).toBe("active");
    expect(stored.lifecycle_version).toBe(0);
    await visibleMatter(page, code, null, true);
  }
  const scoped = await request.get(`${api}/api/matters/87bd479f-78f7-4165-81e4-1d791fb98bf8`, { headers });
  expect(scoped.status()).toBe(200);
  const fourth = await scoped.json();
  expect(fourth.matter_code).toBe("5926");
  expect(fourth.forum_catalog_entry_id).toBe("consumer:ncdrc");
  expect(fourth.next_hearing_on).toBeNull();
  await visibleMatter(page, "5926", null, false);
  const bookmarks = await request.get(`${api}/api/case-tracking/bookmarks`, { headers });
  expect(bookmarks.status()).toBe(200);
  const reported = new Set(["a543e55c-bcc9-4f8c-8341-b1f227afde0b", "dec98199-7055-4b00-aabe-ac432503774e", "d60c6ebe-2a47-4f75-a062-b91635801d58"]);
  const rows = (await bookmarks.json()).bookmarks.filter((row: { matter_id: string }) => reported.has(row.matter_id));
  expect(rows).toHaveLength(3);
  for (const row of rows) {
    expect(row.tracked_case.manual_refresh_allowed).toBe(false);
    expect(row.tracked_case.manual_refresh_disabled_reason).toContain("Add the court");
    expect(row.tracked_case.last_provider_attempted_at).toBeNull();
  }
});
