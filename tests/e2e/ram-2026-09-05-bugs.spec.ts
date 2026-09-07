/** September 05: real browser journeys; no paid providers and no synthetic law. */
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";

const BASE =
  process.env.PROD_BASE_URL ||
  process.env.CASEOPS_WEB_BASE_URL ||
  "http://127.0.0.1:3100";
const LOCAL = ["localhost", "127.0.0.1"].includes(new URL(BASE).hostname);
const API =
  process.env.PROD_API_BASE_URL ||
  (LOCAL
    ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT || "8000"}`
    : "https://api.caseops.ai");
const RUN =
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`.toUpperCase();
const SLUG = LOCAL
  ? `ram05-${RUN.toLowerCase()}`
  : process.env.CASEOPS_RAM_PROD_SLUG || "test-legal";
const EMAIL = LOCAL
  ? `${SLUG}@example.com`
  : process.env.CASEOPS_RAM_PROD_EMAIL || "ram@testfirm.com";
const PASSWORD = LOCAL
  ? "Ram05LocalFixture123!"
  : process.env.CASEOPS_RAM_PROD_PASSWORD || "";
type Matter = {
  id: string;
  status: string;
  is_active: boolean;
  updated_at: string;
  lifecycle_version: number;
  temporary_e_case_number: string | null;
  case_number: string | null;
  cnr_number: string | null;
  matter_code: string;
  forum_catalog_entry_id: string | null;
  court_name: string | null;
};
let api: APIRequestContext;
let token = "";
const owned = new Set<string>();
const headers = () => ({ Authorization: `Bearer ${token}` });

async function login(page: Page) {
  await page.goto(`${BASE}/sign-in`);
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/auth/login" &&
      r.request().method() === "POST",
  );
  await page.locator('button[type="submit"]').click();
  const result = await response;
  expect(result.status(), await result.text()).toBe(200);
  token = (await result.json()).access_token;
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

async function readMatter(id: string): Promise<Matter> {
  const response = await api.get(`${API}/api/matters/${id}`, {
    headers: headers(),
  });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function disposeMatter(id: string) {
  const current = await readMatter(id);
  if (current.status === "disposed") return;
  const response = await api.patch(
    `${API}/api/matters/${id}/lifecycle/status`,
    {
      headers: headers(),
      data: {
        to_status: "disposed",
        expected_from_status: current.status,
        expected_updated_at: current.updated_at,
        reason: "Close the owned September 05 regression fixture.",
      },
    },
  );
  expect(response.status(), await response.text()).toBe(200);
}

test.describe("Ram September 05 reported workflows", () => {
  test.setTimeout(180_000);
  test.beforeAll(async () => {
    if (!PASSWORD) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required.");
    api = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    if (LOCAL) {
      const response = await api.post(`${API}/api/bootstrap/company`, {
        data: {
          company_name: `Ram September 05 ${RUN}`,
          company_slug: SLUG,
          company_type: "law_firm",
          owner_full_name: "Ram September Tester",
          owner_email: EMAIL,
          owner_password: PASSWORD,
        },
      });
      expect(response.status(), await response.text()).toBe(200);
      token = (await response.json()).access_token;
    } else {
      const expected = process.env.CASEOPS_EXPECTED_RELEASE_SHA || "";
      expect(expected).toMatch(/^[0-9a-f]{40}$/);
      for (const url of [`${API}/api/build`, `${BASE}/api/release-identity`]) {
        const response = await api.get(url);
        expect(response.status()).toBe(200);
        expect((await response.json()).release_sha).toBe(expected);
      }
    }
  });
  test.afterAll(async () => {
    try {
      for (const id of owned) await disposeMatter(id);
    } finally {
      await api?.dispose();
    }
  });

  test("billing profile save waits for discovery and remains visible after reload", async ({ page }) => {
    await login(page);
    const originalResponse = await api.get(`${API}/api/admin/matter-billing`, { headers: headers() });
    expect(originalResponse.status()).toBe(200);
    const original = (await originalResponse.json()).profiles.find((profile: { is_default: boolean }) => profile.is_default);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let fetched!: () => void;
    const started = new Promise<void>((resolve) => { fetched = resolve; });
    let held = false;
    await page.route("**/api/admin/matter-billing", async (route) => {
      if (route.request().method() !== "GET" || held) return route.continue();
      held = true;
      const response = await route.fetch();
      fetched();
      await gate;
      await route.fulfill({ response });
    });
    try {
      await page.goto(`${BASE}/app/admin/matter-billing`);
      await started;
      const save = page.getByRole("button", { name: "Save default profile" });
      await expect(save).toBeDisabled();
      await expect(page.getByText("Loading billing profiles...")).toBeVisible();
      await expect(page.getByText("No billing profiles")).toBeHidden();
      release();
      await expect(save).toBeEnabled();
      await page.getByLabel("GSTIN", { exact: true }).fill("07ABCDE1234F1Z5");
      await page.getByLabel("PAN", { exact: true }).fill("ABCDE1234F");
      await page.getByLabel("Place of supply", { exact: true }).fill("Delhi");
      await page.getByLabel("Default SAC/HSN", { exact: true }).fill("9982");
      const saved = page.waitForResponse((response) =>
        new URL(response.url()).pathname.startsWith("/api/admin/matter-billing")
        && ["POST", "PATCH"].includes(response.request().method()),
      );
      await save.click();
      const result = await saved;
      expect(result.status(), await result.text()).toBe(200);
      const savedProfile = await result.json();
      if (original) expect(savedProfile.id).toBe(original.id);
      await expect(page.getByRole("cell", { name: "07ABCDE1234F1Z5", exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole("cell", { name: "07ABCDE1234F1Z5", exact: true })).toBeVisible();
      await expect(page.getByLabel("GSTIN", { exact: true })).toHaveValue("07ABCDE1234F1Z5");
      const policy = await api.patch(`${API}/api/admin/matter-billing/${savedProfile.id}`, {
        headers: headers(), data: { billing_mode: "mixed", payment_terms_days: 47, gst_applicable: false },
      });
      expect(policy.status()).toBe(200);
      await page.reload();
      await expect(page.getByLabel("GSTIN", { exact: true })).toHaveValue("07ABCDE1234F1Z5");
      await page.getByLabel("Firm address", { exact: true }).fill(`Address ${RUN}`);
      const editing = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/admin/matter-billing/${savedProfile.id}` && response.request().method() === "PATCH");
      await save.click();
      const edited = await editing;
      expect(edited.status()).toBe(200);
      expect(edited.request().postDataJSON()).toEqual({ firm_address: `Address ${RUN}` });
      expect(await edited.json()).toEqual(expect.objectContaining({
        billing_mode: "mixed", payment_terms_days: 47, gst_applicable: false,
        firm_gstin: "07ABCDE1234F1Z5", firm_address: `Address ${RUN}`,
      }));
      const reloaded = await api.get(`${API}/api/admin/matter-billing`, { headers: headers() });
      expect((await reloaded.json()).profiles.filter((profile: { is_default: boolean }) => profile.is_default)).toHaveLength(1);
    } finally {
      release();
      if (original) {
        const restoreFields = [
          "name", "is_default", "currency", "firm_legal_name", "firm_address", "firm_gstin",
          "firm_pan", "default_place_of_supply", "default_sac_hsn", "gst_applicable",
          "gstin_state_code", "cgst_rate_bps", "sgst_rate_bps", "igst_rate_bps", "tax_rate_bps",
          "invoice_prefix", "payment_terms_days", "billing_mode", "default_rate_minor_per_hour",
          "expense_categories", "retainer_adjustments_enabled",
        ];
        const restored = await api.patch(`${API}/api/admin/matter-billing/${original.id}`, {
          headers: headers(), data: Object.fromEntries(restoreFields.map((field) => [field, original[field]])),
        });
        expect(restored.status(), await restored.text()).toBe(200);
      }
    }
  });

  for (const width of [393, 1280]) {
  test(`BUG-010: complete reported Act catalog, attach, source detail and reload (${width}px)`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await login(page);
    const response = await api.post(`${API}/api/matters/`, {
      headers: headers(),
      data: {
        title: `September statute acceptance ${width} ${RUN}`,
        matter_code: `RAM905-STAT-${width}-${RUN}`,
        practice_area: "Civil",
        forum_level: "high_court",
      },
    });
    expect(response.status(), await response.text()).toBe(200);
    const matter = await response.json();
    owned.add(matter.id);
    await page.goto(`${BASE}/app/matters/${matter.id}/statutes`);
    await page.getByTestId("matter-statute-add-trigger").click();
    const picker = page.getByTestId("matter-statute-act-select");
    await expect(
      picker.locator('option[value="constitution-india"]'),
    ).toBeAttached();
    // Never seed a synthetic verified provision to make this release gate pass.
    for (const id of [
      "arbitration-1996",
      "bns-2023",
      "bnss-2023",
      "companies-2013",
      "cpc-1908",
    ]) {
      const option = picker.locator(`option[value="${id}"]`);
      await expect.soft(option, `${id}: the catalog entry must exist`).toBeAttached();
      await expect.soft(option).not.toHaveAttribute("disabled", "");
      const sectionsResponse = await api.get(`${API}/api/statutes/${id}/sections`, {
        headers: headers(),
      });
      expect(sectionsResponse.status(), await sectionsResponse.text()).toBe(200);
      const payload = await sectionsResponse.json();
      const expectedCounts: Record<string, [number, number]> = {
        "arbitration-1996": [106, 104], "bns-2023": [358, 358], "bnss-2023": [531, 531],
        "companies-2013": [523, 480], "cpc-1908": [171, 158],
      };
      expect.soft(payload.catalog_section_count, `${id}: full official numbered inventory`).toBe(expectedCounts[id][0]);
      expect.soft(payload.verified_section_count, `${id}: verified/non-retired inventory`).toBe(expectedCounts[id][1]);
      expect.soft(payload.sections.length, `${id}: real verified sections are required`).toBeGreaterThan(0);
      if (payload.sections.length === 0) continue;
      const section = payload.sections[0];
      expect(section.verification_status).toBe("verified_official");
      await picker.selectOption(id);
      const sections = page.getByTestId("matter-statute-section-select");
      await expect(sections.locator(`option[value="${section.id}"]`)).toBeAttached();
      await sections.selectOption(section.id);
      await expect(page.getByTestId("matter-statute-add-submit")).toBeEnabled();
      for (const control of [picker, sections, page.getByTestId("matter-statute-add-submit")]) {
        await expect(control).toBeVisible();
        expect((await control.boundingBox())!.width).toBeGreaterThan(90);
      }
      const attach = page.waitForResponse((result) =>
        new URL(result.url()).pathname === `/api/matters/${matter.id}/statute-references`
        && result.request().method() === "POST",
      );
      await page.getByTestId("matter-statute-add-submit").click();
      expect((await attach).status()).toBe(201);
      await page.reload();
      const savedLink = page.getByTestId("matter-statute-refs-list").locator(
        `a[href="/app/statutes/${id}/sections/${encodeURIComponent(section.section_number)}"]`,
      );
      await expect(savedLink).toBeVisible();
      await savedLink.click();
      await expect(page).toHaveURL(new RegExp(`/app/statutes/${id}/sections/`));
      await expect(page.getByRole("heading", { name: section.section_number, exact: true })).toBeVisible();
      await expect(page.getByTestId("statute-section-text")).toBeVisible();
      const detail = await api.get(`${API}/api/statutes/${id}/sections/${encodeURIComponent(section.section_number)}`, {
        headers: headers(),
      });
      expect(detail.status(), await detail.text()).toBe(200);
      const official = (await detail.json()).section;
      await expect(page.getByTestId("statute-section-text")).toHaveText(official.section_text);
      const sourceLink = page.getByRole("link", { name: "Open source", exact: true });
      await expect(sourceLink).toBeVisible();
      await expect(sourceLink).toHaveAttribute("target", "_blank");
      const guardedSource = `${API}/api/source-actions/targets/statute_section/${official.id}/open?origin=statute`;
      await expect(sourceLink).toHaveAttribute("href", guardedSource);
      // Use the browser's cookies, preserving the real authorization/audit route.
      const opened = await page.request.get(guardedSource, { maxRedirects: 0 });
      expect(opened.status(), await opened.text()).toBe(307);
      expect(opened.headers().location).toBe(official.section_url);
      expect(opened.headers()["cache-control"]).toBe("no-store");
      expect(opened.headers()["referrer-policy"]).toBe("no-referrer");
      expect(new URL(official.section_url).hostname).toBe("www.indiacode.nic.in");
      expect(new URL(official.section_url).hash).toMatch(/^#page=\d+$/);
      if (LOCAL) await page.screenshot({ path: testInfo.outputPath(`BUG-010-${id}-${width}.png`), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
      await page.goto(`${BASE}/app/matters/${matter.id}/statutes`);
      await expect(savedLink).toBeVisible();
      await page.getByTestId("matter-statute-add-trigger").click();
    }
  });
  }

  for (const width of [393, 1280]) {
    test(`ECASE: create, search, add final identifiers, retain temporary identity and terminal state (${width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await login(page);
      await page.goto(`${BASE}/app/matters`);
      const createTrigger = page
        .locator("header")
        .getByTestId("new-matter-trigger");
      await expect(createTrigger).toBeVisible();
      await createTrigger.click();
      const dialog = page.getByRole("dialog");
      const title = `September 05 temporary filing ${width} ${RUN}`;
      const code = `RAM905-${width}-${RUN}`;
      const temporary = `TEMP/2026/${width}/${RUN}`;
      const finalCase = `${1234 + width}/2026/${RUN}`;
      const finalCnr = `DLHC01${Date.now().toString().slice(-6)}2026`;
      await dialog.getByLabel("Title", { exact: true }).fill(title);
      await dialog.getByLabel("Matter code", { exact: true }).fill(code);
      await dialog.getByLabel("Practice area", { exact: true }).fill("Civil");
      const temp = dialog.getByLabel("Temporary E-Case number", {
        exact: true,
      });
      await temp.fill(temporary);
      await expect(temp).toBeVisible();
      expect((await temp.boundingBox())!.width).toBeGreaterThan(120);
      await expect(
        dialog.getByLabel("Case number", { exact: true }),
      ).toHaveValue("");
      await expect(
        dialog.getByLabel("CNR number", { exact: true }),
      ).toHaveValue("");
      const creating = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/api/matters/" &&
          r.request().method() === "POST",
      );
      await dialog.getByRole("button", { name: /^Create matter$/ }).click();
      const created = await creating;
      expect(created.status(), await created.text()).toBe(200);
      const matter: Matter = await created.json();
      owned.add(matter.id);
      expect(matter.temporary_e_case_number).toBe(temporary);
      expect(matter.case_number).toBeNull();
      expect(matter.cnr_number).toBeNull();
      await page.goto(`${BASE}/app/matters`);
      await page.locator("#matter-filter-q").fill(temporary);
      await page.getByRole("button", { name: /Apply/i }).click();
      await expect(page.getByText(code, { exact: true })).toBeVisible();
      await page.goto(`${BASE}/app/matters/${matter.id}`);
      await expect(page.getByText(temporary, { exact: true })).toBeVisible();
      await page.getByTestId("matter-edit-open").click();
      await expect(
        page.getByTestId("matter-edit-temporary-e-case-number"),
      ).toHaveValue(temporary);
      await page.getByTestId("matter-edit-case-number").fill(finalCase);
      await page.getByTestId("matter-edit-cnr-number").fill(finalCnr);
      const saving = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === `/api/matters/${matter.id}` &&
          r.request().method() === "PATCH",
      );
      await page.getByTestId("matter-edit-save").click();
      const saved = await saving;
      expect(saved.status(), await saved.text()).toBe(200);
      const updated = await saved.json();
      expect(updated.temporary_e_case_number).toBe(temporary);
      expect(updated.lifecycle_version).toBe(matter.lifecycle_version);
      await page.reload();
      for (const value of [temporary, finalCase, finalCnr])
        await expect(page.getByText(value, { exact: true })).toBeVisible();
      const stale = await api.patch(`${API}/api/matters/${matter.id}`, {
        headers: headers(),
        data: {
          expected_updated_at: matter.updated_at,
          temporary_e_case_number: "MUST-NOT-APPLY",
        },
      });
      expect(stale.status()).toBe(409);
      await disposeMatter(matter.id);
      const terminal = await readMatter(matter.id);
      const rejected = await api.patch(`${API}/api/matters/${matter.id}`, {
        headers: headers(),
        data: {
          expected_updated_at: terminal.updated_at,
          temporary_e_case_number: "MUST-NOT-REOPEN",
        },
      });
      expect(rejected.status()).toBe(409);
      await page.reload();
      const final = await readMatter(matter.id);
      expect(final.status).toBe("disposed");
      expect(final.is_active).toBe(false);
      expect(final.temporary_e_case_number).toBe(temporary);
      const audit = await api.get(
        `${API}/api/matters/${matter.id}/audit-events`,
        { headers: headers() },
      );
      expect(audit.status()).toBe(200);
      expect(await audit.text()).toContain("disposed");
    });
  }

  test("BULK: duplicate identities, ambiguous courts, conflicting lineage and unsupported courts remain actionable without changing existing data", async ({
    page,
  }) => {
    await login(page);
    const existingCode = `RAM905-EXISTING-${RUN}`;
    const existingTitle = `Existing import guard ${RUN}`;
    const existingCase = `CASE-${RUN}`;
    const response = await api.post(`${API}/api/matters/`, {
      headers: headers(),
      data: {
        title: existingTitle,
        matter_code: existingCode,
        case_number: existingCase,
        client_name: `Client ${RUN}`,
        practice_area: "Civil",
        forum_level: "high_court",
      },
    });
    expect(response.status(), await response.text()).toBe(200);
    const original = await response.json();
    owned.add(original.id);
    const csv = [
      "Matter Title,Matter Code,Practice Area,Forum,Court,Case Number,Client Name,Forum State,Forum Catalog Entry ID",
      `Other title ${RUN},${existingCode},Civil,High Court,,,,,`,
      `Other case ${RUN},RAM905-CASE-${RUN},Civil,High Court,,${existingCase},,,,`,
      `${existingTitle},RAM905-TITLE-${RUN},Civil,High Court,,,Client ${RUN},,`,
      `Ambiguous ${RUN},RAM905-AMB-${RUN},Civil,Tis Hazari,,,,,`,
      `Conflict ${RUN},RAM905-CON-${RUN},Civil,Saket,,,,Karnataka,`,
      `Unknown ${RUN},RAM905-UNK-${RUN},Civil,GURMEET MADAM-ARBITRATOR,,,,,`,
      `Catalog conflict ${RUN},RAM905-ID-${RUN},Civil,High Court,,,,Karnataka,hc:delhi`,
      `Named court conflict ${RUN},RAM905-NAME-${RUN},Civil,High Court,Delhi High Court,,,Karnataka,`,
      `Valid court ${RUN},RAM905-OK-${RUN},Civil,High Court,Delhi High Court,,,Delhi,hc:delhi`,
    ].join("\n");
    await page.goto(`${BASE}/app/matters/imports`);
    await page.getByTestId("matter-import-file").setInputFiles({
      name: `ram05-guards-${RUN}.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from(csv),
    });
    const previewing = page.waitForResponse(
      (r) =>
        r.url().includes("/api/matters/imports/preview") &&
        r.request().method() === "POST",
    );
    await page.getByTestId("matter-import-validate").click();
    const preview = await previewing;
    expect(preview.status(), await preview.text()).toBe(200);
    const job = await preview.json();
    expect(job.rows.map((row: { status: string }) => row.status)).toEqual([
      "duplicate",
      "duplicate",
      "duplicate",
      "invalid",
      "invalid",
      "invalid",
      "invalid",
      "invalid",
      "valid",
    ]);
    await expect(
      page.getByText(/matches multiple active Exact Court records/),
    ).toBeVisible();
    await expect(
      page.getByText(/context does not match the selected forum catalog entry/),
    ).toHaveCount(2);
    expect(await readMatter(original.id)).toEqual(
      expect.objectContaining({
        case_number: original.case_number,
        updated_at: original.updated_at,
        status: original.status,
      }),
    );
  });

  test("BULK: reported qualified court aliases resolve and persist without guessing ambiguous courts", async ({ page }) => {
    await login(page);
    const entries = [
      ["Tis Hazari", "Tis Hazari (West)", "district:india-gov:delhi:westdelhi"],
      ["Dwarka_SWCF", "Dwarka-Consumer Forum", "consumer:dcdrc:delhi:dwarka"],
      ["TDSAT- New Delhi", "", "tdsat:delhi"],
    ];
    const csv = [
      "Matter Title,Matter Code,Practice Area,Forum,Court",
      ...entries.map(([forum, court], index) => `Qualified court ${index} ${RUN},RAM905-ALIAS-${index}-${RUN},Civil,${forum},${court}`),
    ].join("\n");
    await page.goto(`${BASE}/app/matters/imports`);
    await page.getByTestId("matter-import-file").setInputFiles({ name: "qualified-courts.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    const previewing = page.waitForResponse((response) => response.url().includes("/api/matters/imports/preview") && response.request().method() === "POST");
    await page.getByTestId("matter-import-validate").click();
    const preview = await previewing;
    expect(preview.status(), await preview.text()).toBe(200);
    const job = await preview.json();
    expect(job.valid_rows, JSON.stringify(job.rows)).toBe(3);
    expect(job.invalid_rows).toBe(0);
    const committing = page.waitForResponse((response) => response.url().includes(`/api/matters/imports/${job.id}/commit`));
    await page.getByTestId("matter-import-confirm").click();
    const committed = await committing;
    expect(committed.status(), await committed.text()).toBe(200);
    const ids = (await committed.json()).created_matter_ids as string[];
    expect(ids).toHaveLength(3);
    for (const id of ids) owned.add(id);
    for (const id of ids) {
      const matter = await readMatter(id);
      const index = Number(matter.matter_code.split("-")[2]);
      expect(matter.forum_catalog_entry_id).toBe(entries[index][2]);
      await page.goto(`${BASE}/app/matters/${id}`);
      await expect(page.getByText(matter.court_name!, { exact: true }).first()).toBeVisible();
      await page.reload();
      expect((await readMatter(id)).forum_catalog_entry_id).toBe(entries[index][2]);
    }
  });

  test("BULK: invalid-first row does not suppress the valid copy; preview, commit and replay preserve identifiers", async ({
    page,
  }) => {
    await login(page);
    await page.goto(`${BASE}/app/matters/imports`);
    const code = `RAM905-BULK-${RUN}`;
    const temporary = `TEMP/BULK/${RUN}`;
    const csv = [
      "Matter Title,Matter Code,Practice Area,Forum,Temporary E-Case Number,CNR Number,Matter Owner,Assigned Team,Responsible Lawyer",
      `Invalid assignment ${RUN},${code},Civil,High Court,${temporary},DLHC010012342026,owner@example.com,commercial-litigation,lawyer@example.com`,
      `Valid import ${RUN},${code},Civil,High Court,${temporary},DLHC010012342026,,,`,
    ].join("\n");
    await page.getByTestId("matter-import-file").setInputFiles({
      name: `ram05-${RUN}.csv`,
      mimeType: "text/csv",
      buffer: Buffer.from(csv),
    });
    const previewing = page.waitForResponse(
      (r) =>
        r.url().includes("/api/matters/imports/preview") &&
        r.request().method() === "POST",
    );
    await page.getByTestId("matter-import-validate").click();
    const response = await previewing;
    expect(response.status(), await response.text()).toBe(200);
    const job = await response.json();
    expect(job.rows.map((row: { status: string }) => row.status)).toEqual([
      "invalid",
      "valid",
    ]);
    expect(job.rows[0].errors.join(" ")).toMatch(/owner/i);
    expect(job.rows[0].errors.join(" ")).toMatch(/team/i);
    expect(job.rows[0].errors.join(" ")).toMatch(/lawyer/i);
    await expect(page.getByTestId("matter-import-confirm")).toBeEnabled();
    const committing = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/matters/imports/${job.id}/commit`) &&
        r.request().method() === "POST",
    );
    await page.getByTestId("matter-import-confirm").click();
    const committed = await committing;
    expect(committed.status(), await committed.text()).toBe(200);
    const result = await committed.json();
    expect(result.created_matter_ids).toHaveLength(1);
    const id = result.created_matter_ids[0];
    owned.add(id);
    const replay = await api.post(
      `${API}/api/matters/imports/${job.id}/commit`,
      { headers: headers() },
    );
    expect(replay.status()).toBe(200);
    expect((await replay.json()).created_matter_ids).toEqual([id]);
    const matter = await readMatter(id);
    expect(matter.temporary_e_case_number).toBe(temporary);
    expect(matter.cnr_number).toBe("DLHC010012342026");
    await page.goto(`${BASE}/app/matters/${id}`);
    await expect(page.getByText(temporary, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(temporary, { exact: true })).toBeVisible();

    for (const [label, row] of [
      ["invalid", `Missing required practice,RAM905-INVALID-${RUN},,High Court`],
      ["duplicate", `Already created,${code},Civil,High Court`],
    ]) {
      await page.goto(`${BASE}/app/matters/imports`);
      await page.getByTestId("matter-import-file").setInputFiles({
        name: `all-${label}.csv`,
        mimeType: "text/csv",
        buffer: Buffer.from(`Matter Title,Matter Code,Practice Area,Forum\n${row}\n`),
      });
      const validating = page.waitForResponse((r) =>
        r.url().includes("/api/matters/imports/preview") && r.request().method() === "POST",
      );
      await page.getByTestId("matter-import-validate").click();
      const validation = await validating;
      expect(validation.status()).toBe(200);
      const rejected = await validation.json();
      expect(rejected.valid_rows).toBe(0);
      await expect(page.getByTestId("matter-import-confirm")).toBeDisabled();
      const forced = await api.post(`${API}/api/matters/imports/${rejected.id}/commit`, {
        headers: headers(),
      });
      expect(forced.status(), await forced.text()).toBe(400);
      expect(await readMatter(id)).toEqual(matter);
    }
  });
});
