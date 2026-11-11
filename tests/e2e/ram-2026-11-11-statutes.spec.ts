/** CaseOps_Bugs (5), BUG-002. J05/J07, MOD-TS-017, US-046C, FT-S4-1..4. */
import { randomUUID } from "node:crypto";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { localTransportHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { seedStatuteDropdownFixture } from "./support/statute-dropdown-fixture";

test.use({ trace: "off", screenshot: "off", video: "off" });

function required(key: string): string {
  const value = process.env[key]?.trim();
  if (!value) throw new Error(`${key} is required; missing evidence is not a skip.`);
  return value;
}
const isLocal = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
type Act = { id: string; short_name: string; section_count: number; catalog_section_count: number };
type Section = { id: string; section_number: string; verification_status: string; selection_state: string };
type Sections = { sections: Section[]; catalog_sections: Section[] };

async function contained(control: Locator, page: Page) {
  await expect(control).toBeVisible();
  const box = (await control.boundingBox())!;
  expect(box.width).toBeGreaterThan(90);
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  expect(await control.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
}

async function openAndScroll(page: Page, name: string, screenshot?: string) {
  const trigger = page.getByTestId(`matter-statute-${name.toLowerCase()}-select`);
  await expect(trigger).toHaveAccessibleName(name);
  await contained(trigger, page);
  await trigger.click();
  if (isLocal(new URL(page.url())) && screenshot) await page.screenshot({ path: screenshot });
  const list = page.getByRole("listbox");
  await contained(list, page);
  const box = (await list.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
  const viewport = list.locator("[data-radix-select-viewport]");
  expect(await viewport.evaluate(el => el.scrollHeight)).toBeGreaterThan(await viewport.evaluate(el => el.clientHeight));
  // A browser scroll event, not selectOption or a DOM-presence assertion.
  await viewport.hover();
  for (let gesture = 0; gesture < 4; gesture += 1) {
    const before = await viewport.evaluate(el => el.scrollTop);
    await page.mouse.wheel(0, await viewport.evaluate(el => el.scrollHeight));
    await expect.poll(() => viewport.evaluate(el => el.scrollTop)).toBeGreaterThan(before);
    if (await viewport.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop <= 1)) break;
  }
  if (isLocal(new URL(page.url())) && screenshot) {
    await page.screenshot({ path: screenshot.replace("-open.png", "-scrolled.png") });
  }
  const last = list.getByRole("option").last();
  await expect(last).toBeInViewport();
  await contained(last, page);
  return list;
}

async function keyboardChoose(page: Page, field: "Act" | "Section", id: string) {
  const trigger = page.getByRole("combobox", { name: field, exact: true });
  const list = page.getByRole("listbox", { name: field, exact: true });
  await expect(list).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(list).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Add statute reference" })).toBeVisible();
  await trigger.press("Space");
  await expect(list).toBeVisible();
  await expect.poll(() => list.getByRole("option").evaluateAll(options => options.some(option => option === document.activeElement))).toBe(true);
  const enabled = list.locator('[role="option"]:not([aria-disabled="true"])');
  const identities = await enabled.evaluateAll(options => options.map(option => option.getAttribute("data-value")));
  expect(identities).toContain(id);
  if (field === "Act") {
    expect(identities.length, "Bound keyboard catalog traversal without truncating it").toBeLessThanOrEqual(128);
    await page.keyboard.press("Home");
    await expect(enabled.first()).toBeFocused();
    for (let index = 1; index <= identities.indexOf(id); index += 1) {
      await page.keyboard.press("ArrowDown");
      await expect(enabled.nth(index)).toBeFocused();
    }
  } else {
    // The positive is the API's final verified provision. End/ArrowUp/Down
    // must ignore any pending provisions interspersed in the same catalog.
    expect(identities.at(-1)).toBe(id);
    await page.keyboard.press("End");
    await expect(enabled.last()).toBeFocused();
    if (identities.length > 1) {
      await page.keyboard.press("ArrowUp");
      await expect(enabled.nth(identities.length - 2)).toBeFocused();
      await page.keyboard.press("ArrowDown");
      await expect(enabled.last()).toBeFocused();
    }
  }
  await expect(list.locator(`[data-value="${id}"]`)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(list).toHaveCount(0);
  await expect(trigger).toBeFocused();
}

for (const phone of [false, true]) {
  test.describe(phone ? "Phone" : "Desktop", () => {
  test.use({ isMobile: phone, hasTouch: phone });
  test(`${phone ? "[mobile] " : ""}BUG-002 statute dropdown scrolls, attaches verified text and persists`, async ({ page, request, baseURL }, info) => {
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const local = isLocal(web);
    const api = new URL(local ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}` : required("PROD_API_BASE_URL"));
    if (local !== isLocal(api) || web.username || web.password || api.username || api.password
      || (local && (web.protocol !== "http:" || api.protocol !== "http:"))
      || (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai"))) {
      throw new Error("Statute acceptance requires loopback or the canonical production pair.");
    }
    const sha = local ? e2eEnv.CASEOPS_RELEASE_SHA : required("CASEOPS_EXPECTED_RELEASE_SHA");
    await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
    if (local) seedStatuteDropdownFixture(web.origin, api.origin);
    const nonce = randomUUID();
    const credentials = local ? { slug: `b5-statutes-${nonce.slice(0, 8)}`, email: `b5-${nonce}@example.com`, password: `Synthetic!${nonce}` }
      : { slug: required("CASEOPS_RAM_PROD_SLUG"), email: required("CASEOPS_RAM_PROD_EMAIL"), password: required("CASEOPS_RAM_PROD_PASSWORD") };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production statute acceptance is test-legal only.");
    const transport = localTransportHeaders(api.origin);
    if (local) {
      const bootstrap = await request.post(`${api.origin}/api/bootstrap/company`, { headers: transport, data: {
        company_name: "Synthetic statute layout QA", company_slug: credentials.slug, company_type: "law_firm",
        owner_full_name: "Statute QA", owner_email: credentials.email, owner_password: credentials.password,
      } });
      expect(bootstrap.status(), "Loopback-only bootstrap").toBe(200);
    }
    await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1280, height: 900 });
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    const loggingIn = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    const loggedIn = await loggingIn;
    expect(loggedIn.status()).toBe(200);
    const actor = await loggedIn.json();
    expect(actor.company.slug).toBe(credentials.slug);
    const headers = { ...transport, Authorization: `Bearer ${actor.access_token}` };
    await page.waitForURL(/\/app(?:[/?]|$)/);
    const catalogResponse = await request.get(`${api.origin}/api/statutes`, { headers });
    expect(catalogResponse.status()).toBe(200);
    const catalog = await catalogResponse.json() as { statutes: Act[] };
    const candidates = catalog.statutes.filter(s => s.section_count > 0 && s.catalog_section_count > s.section_count)
      .sort((a, b) => b.catalog_section_count - a.catalog_section_count);
    expect(candidates.length, "Bound the reviewed catalog; never truncate candidate discovery").toBeLessThanOrEqual(64);
    let selected: { act: Act; catalog: Sections } | undefined;
    for (const act of candidates) {
      const response = await request.get(`${api.origin}/api/statutes/${act.id}/sections`, { headers });
      expect(response.status()).toBe(200);
      const sections = await response.json() as Sections;
      if (sections.sections.length && sections.catalog_sections.some(s => s.selection_state === "verification_pending")) {
        selected = { act, catalog: sections };
        break;
      }
    }
    expect(selected, "A verified positive and a genuinely pending negative in the same Act are required; never synthesize production law").toBeDefined();
    const { act: target, catalog: sectionCatalog } = selected!;
    expect(target.section_count).toBeGreaterThan(0);
    const positive = sectionCatalog.sections.at(-1)!;
    const pending = sectionCatalog.catalog_sections.find(s => s.selection_state === "verification_pending")!;
    expect(positive, "Verified positive must exist").toBeTruthy();
    expect(positive.verification_status).toMatch(/^verified_(official|licensed)$/);
    expect(pending, "Retained genuinely pending negative must exist").toBeTruthy();
    // No production catalogue write, fixture seed or provider request is permitted.
    const created = await request.post(`${api.origin}/api/matters/`, { headers, data: {
      title: `Statute dropdown QA ${nonce}`, matter_code: `B5-${nonce}`, practice_area: "Civil", forum_level: "high_court",
    } });
    expect(created.status()).toBe(200);
    const matter = await created.json();
    try {
      const denied = await request.post(`${api.origin}/api/matters/${matter.id}/statute-references`, {
        headers, data: { section_id: pending.id, relevance: "cited" },
      });
      expect(denied.status(), "Pending source must remain rejected by the API").toBe(409);
      expect((await denied.json()).type).toBe("statute_section_not_verified");
      let failCatalog = true;
      let failSections = true;
      let failedSectionReads = 0;
      let recoveredSectionReads = 0;
      if (local) {
        // Fault injection never supplies legal data and cannot run in production.
        const unavailable = { status: 503, contentType: "application/problem+json", body: JSON.stringify({
          type: "about:blank", title: "Local fixture unavailable", status: 503, detail: "Deterministic loopback read failure.",
        }) };
        await page.route(url => url.origin === api.origin && url.pathname === "/api/statutes", async route => {
          if (failCatalog) await route.fulfill(unavailable);
          else await route.continue();
        });
        await page.route(url => url.origin === api.origin && url.pathname === `/api/statutes/${target.id}/sections`, async route => {
          if (failSections) {
            failedSectionReads += 1;
            await route.fulfill(unavailable);
          } else {
            recoveredSectionReads += 1;
            await route.continue();
          }
        });
      }
      await page.goto(`${web.origin}/app/matters/${matter.id}/statutes`);
      await page.getByTestId("matter-statute-add-trigger").click();
      if (local) {
        await expect(page.getByTestId("matter-statute-catalog-error")).toBeVisible();
        await expect(page.getByTestId("matter-statute-act-select")).toBeDisabled();
        await expect(page.getByTestId("matter-statute-no-selectable-acts")).toHaveCount(0);
        await expect(page.getByTestId("matter-statute-sections-error")).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Retry sections", exact: true })).toHaveCount(0);
        failCatalog = false;
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(page.getByTestId("matter-statute-add-trigger")).toBeFocused();
        await page.getByTestId("matter-statute-add-trigger").click();
      }
      await expect(page.getByTestId("matter-statute-catalog-coverage")).toBeVisible();
      const dialog = page.getByRole("dialog", { name: "Add statute reference" });
      await contained(dialog, page);
      if (local) await page.screenshot({ path: info.outputPath("settled-modal.png") });
      const acts = await openAndScroll(page, "Act", local ? info.outputPath("act-open.png") : undefined);
      if (local) await page.screenshot({ path: info.outputPath("act-bottom.png") });
      const act = acts.locator(`[data-value="${target.id}"]`);
      await expect(act).not.toHaveAttribute("aria-disabled", "true");
      await act.scrollIntoViewIfNeeded();
      if (local) expect((await act.textContent())!.length).toBeGreaterThan(100);
      await keyboardChoose(page, "Act", target.id);
      if (local) {
        await expect(page.getByTestId("matter-statute-sections-error")).toBeVisible();
        await expect(page.getByTestId("matter-statute-section-select")).toBeDisabled();
        await expect(page.getByTestId("matter-statute-add-submit")).toBeDisabled();
        await expect(page.getByTestId("matter-statute-catalog-error")).toHaveCount(0);
        const failures = failedSectionReads;
        expect(failures).toBeGreaterThan(0);
        await page.getByRole("combobox", { name: "Act", exact: true }).press("Space");
        await keyboardChoose(page, "Act", target.id);
        expect(failedSectionReads, "Reselecting the current Act does not trigger Radix onValueChange").toBe(failures);
        failSections = false;
        await page.getByRole("button", { name: "Retry sections", exact: true }).click();
        await expect(page.getByRole("combobox", { name: "Section", exact: true })).toBeEnabled();
        await expect(page.getByTestId("matter-statute-sections-error")).toHaveCount(0);
        expect(recoveredSectionReads, "One explicit same-Act recovery read").toBe(1);
      }
      const sections = await openAndScroll(page, "Section", local ? info.outputPath("section-open.png") : undefined);
      if (local) await page.screenshot({ path: info.outputPath("section-bottom.png") });
      const negative = sections.locator(`[data-value="${pending.id}"]`);
      await negative.scrollIntoViewIfNeeded();
      await expect(negative).toHaveAttribute("aria-disabled", "true");
      await expect(negative).toContainText("verification pending; not attachable");
      const section = sections.locator(`[data-value="${positive.id}"]`);
      await section.scrollIntoViewIfNeeded();
      await contained(section, page);
      await expect(section).not.toHaveAttribute("aria-disabled", "true");
      if (local) expect((await section.textContent())!.length).toBeGreaterThan(100);
      await keyboardChoose(page, "Section", positive.id);
      await expect(page.getByRole("combobox", { name: "Section", exact: true })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(page.getByTestId("matter-statute-add-trigger")).toBeFocused();
      await page.getByTestId("matter-statute-add-trigger").click();
      await expect(page.getByRole("combobox", { name: "Act", exact: true })).toContainText("Select an Act");
      await expect(page.getByRole("combobox", { name: "Section", exact: true })).toBeDisabled();
      await expect(page.getByTestId("matter-statute-add-submit")).toBeDisabled();
      await page.getByRole("combobox", { name: "Act", exact: true }).press("Space");
      await keyboardChoose(page, "Act", target.id);
      const sectionTrigger = page.getByRole("combobox", { name: "Section", exact: true });
      await expect(sectionTrigger).toBeEnabled();
      await sectionTrigger.press("Space");
      await keyboardChoose(page, "Section", positive.id);
      const relevance = page.getByRole("combobox", { name: "Relevance", exact: true });
      await relevance.press("Space");
      const relevanceOptions = page.getByRole("listbox", { name: "Relevance", exact: true });
      await expect(relevanceOptions.getByRole("option", { name: "cited (we rely on it)", exact: true })).toBeFocused();
      await page.keyboard.press("End");
      await expect(relevanceOptions.getByRole("option", { name: "context (in scope but not load-bearing)", exact: true })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(relevance).toBeFocused();
      await expect(relevance).toContainText("context");
      const submit = page.getByTestId("matter-statute-add-submit");
      await expect(submit).toBeEnabled();
      await submit.scrollIntoViewIfNeeded();
      await contained(submit, page);
      const attaching = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matter.id}/statute-references` && r.request().method() === "POST");
      await submit.click();
      const attached = await attaching;
      expect(attached.status()).toBe(201);
      const saved = await attached.json();
      expect(saved.section_id).toBe(positive.id);
      expect(saved.relevance).toBe("context");
      await expect(dialog).toHaveCount(0);
      await page.reload();
      const persisted = await request.get(`${api.origin}/api/matters/${matter.id}/statute-references`, { headers });
      expect(persisted.status()).toBe(200);
      const refs = (await persisted.json()).references;
      expect(refs.map((r: { section_id: string }) => r.section_id)).toEqual([positive.id]);
      expect(refs[0].relevance).toBe("context");
      await expect(page.getByTestId("matter-statute-refs-list").getByRole("link", {
        name: `${target.short_name} ${positive.section_number}`, exact: true,
      })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
      if (local) await page.screenshot({ path: info.outputPath("persisted.png"), fullPage: true });
    } finally {
      const currentResponse = await request.get(`${api.origin}/api/matters/${matter.id}`, { headers });
      expect(currentResponse.status()).toBe(200);
      const current = await currentResponse.json();
      const disposed = await request.patch(`${api.origin}/api/matters/${matter.id}/lifecycle/status`, { headers, data: {
        to_status: "disposed", expected_from_status: current.status, expected_updated_at: current.updated_at,
        reason: "Close owned BUG-002 statute dropdown QA fixture.",
      } });
      expect(disposed.status()).toBe(200);
    }
    info.annotations.push({ type: "caseops-b5-proof", description: "workflow-outcome" });
  });
  });
}
