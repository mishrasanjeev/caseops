/**
 * Tester workbook dated 25 Nov 2026, row 1 (Nova Legal Associates, nova-legal):
 * "Act and Section dropdown options are not clickable while adding a reference."
 *
 * The reported Acts were the Constitution of India (1 verified of 11
 * catalogued: only Article 14 could be attached) and the Income-tax Act, 1961
 * (0 verified). The fix compiles every Article of the official Constitution
 * edition and the Income Tax Department edition of the 1961 Act (a retained
 * repealed-law edition: the Income-tax Act, 2025 replaced it from 1 April
 * 2026) into the release bundle. Entries that cannot be attached (quarantined
 * tables, omitted sections) stay visible but are grouped apart and disabled.
 *
 * Each journey signs in as the reporting tester through the sign-in page,
 * creates its own matter through the UI, chooses the Act and the provision with
 * a real pointer (mouse on desktop, touch on a phone), attaches the reference,
 * checks it through the API oracle, then removes it and disposes the matter.
 * Locally the release statute seed (the same `_seed` the release job runs) is
 * applied first, so the journey never depends on another spec having seeded
 * the catalogue; in production the catalogue comes from the deployed release.
 *
 * Production runs need CASEOPS_EXPECTED_RELEASE_SHA and the tester's
 * credentials in CASEOPS_NOVA_PROD_EMAIL / CASEOPS_NOVA_PROD_PASSWORD (never
 * committed). Missing setup fails; nothing here skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";
import { seedVerifiedLocalStatute } from "./support/verified-statute-fixture";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const DESKTOP = { width: 1365, height: 900 };
const PHONE = { width: 393, height: 851 };
/** Articles the tester could not attach before the fix (pending in production on 26 Nov 2026). */
const REPORTED_ARTICLES = ["Article 19", "Article 21", "Article 32", "Article 226", "Article 227"];
/** Income-tax sections a tax practice cites; Section 139 holds an unreconciled table and stays withheld. */
const INCOME_TAX_ATTACHABLE = ["Section 80C", "Section 148A", "Section 194-I", "Section 292A"];

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  headers: Record<string, string>;
};
type StatuteRef = { id: string; statute_id: string; section_number: string; relevance: string };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

function localCredentials(): TesterCredentials {
  const slug = process.env.CASEOPS_NOVA_LOCAL_SLUG?.trim();
  const email = process.env.CASEOPS_NOVA_LOCAL_EMAIL?.trim();
  const password = process.env.CASEOPS_NOVA_LOCAL_PASSWORD?.trim();
  if (slug && email && password) return { slug, email, password };
  return { slug: `nov25-nova-${randomUUID()}`, email: `nova-${randomUUID()}@example.com`,
    password: `Synthetic!${randomUUID()}` };
}

async function runtimeFor(baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const local = loopback(web);
  const api = new URL(local ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
    : required("PROD_API_BASE_URL"));
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote acceptance requires the canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  // CI app-mobile ran this file before any spec that seeds the catalogue (26 Nov 2026).
  seedVerifiedLocalStatute(local);
  const credentials: TesterCredentials = local ? localCredentials() : {
    slug: process.env.CASEOPS_NOVA_PROD_SLUG?.trim() || "nova-legal",
    email: required("CASEOPS_NOVA_PROD_EMAIL"),
    password: required("CASEOPS_NOVA_PROD_PASSWORD"),
  };
  if (!local && credentials.slug !== "nova-legal") {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Nova Legal Associates", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Riya Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` } };
}

const isRequest = (method: string, pattern: RegExp) => (r: { url(): string; request(): { method(): string } }) =>
  r.request().method() === method && pattern.test(new URL(r.url()).pathname);

async function createMatterThroughUi(page: Page, rt: Runtime, practiceArea = "Constitutional Law"): Promise<string> {
  const code = `N25S-${randomUUID().slice(0, 8).toUpperCase()}`;
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(stamp("Nov25 statute reference matter"));
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill(practiceArea);
  const created = page.waitForResponse(isRequest("POST", /^\/api\/matters\/?$/));
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await json<{ id: string; matter_code: string }>(await created, "Create matter through the Matters page");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter.id;
}

async function references(request: APIRequestContext, rt: Runtime, matterId: string): Promise<StatuteRef[]> {
  return (await json<{ references: StatuteRef[] }>(await request.get(
    `${rt.api.origin}/api/matters/${matterId}/statute-references`, { headers: rt.headers }),
  "Statute reference oracle")).references;
}

async function disposeMatter(page: Page, rt: Runtime, matterId: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  await page.getByTestId("matter-dispose-trigger").click();
  await page.getByTestId("matter-lifecycle-reason").fill("Nov 25 statute reference journey retires its own test matter.");
  const disposed = page.waitForResponse((r) => r.request().method() === "PATCH"
    && new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status`);
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await json<{ status: string }>(await disposed, "Dispose the journey matter")).status).toBe("disposed");
}

/** Pointer activation the tester used: a mouse click on desktop, a touch tap on a phone. */
async function press(target: Locator, phone: boolean) {
  await expect(target).toBeVisible();
  if (phone) await target.tap();
  else await target.click();
}

async function attachArticle21(page: Page, rt: Runtime, matterId: string, phone: boolean) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/statutes`);
  await press(page.getByTestId("matter-statute-add-trigger"), phone);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await press(dialog.getByTestId("matter-statute-act-select"), phone);
  const actList = page.getByRole("listbox");
  await expect(actList).toBeVisible();
  // Attachable Acts come first; Acts with no verified text are grouped apart and disabled.
  const attachableActs = page.getByTestId("matter-statute-act-group-attachable");
  const constitution = attachableActs.getByRole("option", { name: /^Constitution — The Constitution of India \(\d+ verified of \d+ catalogued\)$/ });
  await expect(constitution).toHaveCount(1);
  await expect(constitution).not.toHaveAttribute("data-disabled", /.*/);
  const label = (await constitution.textContent()) ?? "";
  const [, verified, catalogued] = label.match(/\((\d+) verified of (\d+) catalogued\)/) ?? [];
  expect(Number(verified), "Constitution Articles with verified official text").toBeGreaterThanOrEqual(400);
  expect(Number(catalogued)).toBeGreaterThanOrEqual(Number(verified));
  // The Income-tax Act, 1961 now has verified edition text: listed once, attachable, enabled.
  const incomeTax = page.getByRole("option", { name: /^Income Tax Act — / });
  await expect(incomeTax, "The Income Tax Act is listed exactly once").toHaveCount(1);
  await expect(attachableActs.getByRole("option", { name: /^Income Tax Act — / })).toHaveCount(1);
  await expect(incomeTax).not.toHaveAttribute("data-disabled", /.*/);
  await press(constitution, phone);
  await expect(dialog.getByTestId("matter-statute-act-select")).toContainText("The Constitution of India");

  await press(dialog.getByTestId("matter-statute-section-select"), phone);
  await expect(page.getByRole("listbox")).toBeVisible();
  const attachableSections = page.getByTestId("matter-statute-section-group-attachable");
  for (const article of REPORTED_ARTICLES) {
    const option = attachableSections.getByRole("option", { name: new RegExp(`^${article} — `) });
    await expect(option, `${article} must be attachable`).toHaveCount(1);
    await expect(option).not.toHaveAttribute("data-disabled", /.*/);
  }
  await press(attachableSections.getByRole("option", { name: /^Article 21 — Protection of life and personal liberty/ }), phone);
  await expect(dialog.getByTestId("matter-statute-section-select")).toContainText("Article 21");

  const submit = dialog.getByTestId("matter-statute-add-submit");
  await expect(submit).toBeEnabled();
  const attached = page.waitForResponse(isRequest("POST", new RegExp(`^/api/matters/${matterId}/statute-references$`)));
  await press(submit, phone);
  const response = await attached;
  const created = await json<StatuteRef>(response, "Attach Article 21 through the dialog", 201);
  expect([created.statute_id, created.section_number, created.relevance]).toEqual(["constitution-india", "Article 21", "cited"]);
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId(`matter-statute-ref-${created.id}`)).toContainText("Article 21");
  return created;
}

async function attachIncomeTax80C(page: Page, rt: Runtime, matterId: string, phone: boolean) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/statutes`);
  await press(page.getByTestId("matter-statute-add-trigger"), phone);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await press(dialog.getByTestId("matter-statute-act-select"), phone);
  await expect(page.getByRole("listbox")).toBeVisible();
  const incomeTax = page.getByTestId("matter-statute-act-group-attachable")
    .getByRole("option", { name: /^Income Tax Act — Income-tax Act, 1961 \(\d+ verified of \d+ catalogued\)$/ });
  await expect(incomeTax, "The Income-tax Act is in the attachable group").toHaveCount(1);
  await expect(incomeTax).not.toHaveAttribute("data-disabled", /.*/);
  const [, verified, catalogued] = ((await incomeTax.textContent()) ?? "").match(/\((\d+) verified of (\d+) catalogued\)/) ?? [];
  expect(Number(verified), "Income-tax sections with verified edition text").toBeGreaterThanOrEqual(800);
  expect(Number(catalogued)).toBeGreaterThan(Number(verified));
  await press(incomeTax, phone);
  await expect(dialog.getByTestId("matter-statute-act-select")).toContainText("Income-tax Act, 1961");

  await press(dialog.getByTestId("matter-statute-section-select"), phone);
  await expect(page.getByRole("listbox")).toBeVisible();
  const attachableSections = page.getByTestId("matter-statute-section-group-attachable");
  // Every attachable section of this edition says it is the historical repealed-law text.
  for (const number of INCOME_TAX_ATTACHABLE) {
    const option = attachableSections.getByRole("option", {
      name: new RegExp(`^${number} — .+ \\(historical repealed-law edition\\)$`),
    });
    await expect(option, `${number} must be attachable and labelled repealed`).toHaveCount(1);
    await expect(option).not.toHaveAttribute("data-disabled", /.*/);
  }
  // Section 139 is listed but withheld: its due-date table is not reconciled.
  const returns = page.getByRole("option", { name: /^Section 139 — Return of income/ });
  await expect(returns).toHaveCount(1);
  await expect(attachableSections.getByRole("option", { name: /^Section 139 — / })).toHaveCount(0);
  await expect(returns).toHaveAttribute("data-disabled", /.*/);
  await press(attachableSections.getByRole("option", { name: /^Section 80C — Deduction in respect of life insurance premia/ }), phone);
  await expect(dialog.getByTestId("matter-statute-section-select")).toContainText("Section 80C");

  const submit = dialog.getByTestId("matter-statute-add-submit");
  await expect(submit).toBeEnabled();
  const attached = page.waitForResponse(isRequest("POST", new RegExp(`^/api/matters/${matterId}/statute-references$`)));
  await press(submit, phone);
  const created = await json<StatuteRef>(await attached, "Attach Income-tax Section 80C through the dialog", 201);
  expect([created.statute_id, created.section_number, created.relevance]).toEqual(["income-tax-1961", "Section 80C", "cited"]);
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId(`matter-statute-ref-${created.id}`)).toContainText("Section 80C");
  return created;
}

async function removeReference(page: Page, matterId: string, ref: StatuteRef, phone: boolean) {
  const removed = page.waitForResponse(isRequest("DELETE",
    new RegExp(`^/api/matters/${matterId}/statute-references/${ref.id}$`)));
  await press(page.getByRole("button", { name: new RegExp(`^Remove .*${ref.section_number}$`) }), phone);
  expect((await removed).status(), "Remove the reference").toBe(204);
  await expect(page.getByTestId(`matter-statute-ref-${ref.id}`)).toHaveCount(0);
}

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}row 1 Constitution Article 21 is chosen and attached from the Add Reference dialog`, async ({ page, request, baseURL }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(phone ? PHONE : DESKTOP);
    const rt = await runtimeFor(baseURL, request);
    await signIn(page, { web: rt.web }, rt.credentials);
    let matterId: string | undefined;
    try {
      matterId = await createMatterThroughUi(page, rt);
      const ref = await attachArticle21(page, rt, matterId, phone);
      const stored = await references(request, rt, matterId);
      expect(stored.map((row) => [row.statute_id, row.section_number])).toEqual([["constitution-india", "Article 21"]]);
      await removeReference(page, matterId, ref, phone);
      expect(await references(request, rt, matterId)).toEqual([]);
    } finally {
      if (matterId) await disposeMatter(page, rt, matterId);
    }
  });

  test(`${phone ? "[mobile] " : ""}row 1 Income-tax Act Section 80C is chosen and attached from the Add Reference dialog`, async ({ page, request, baseURL }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(phone ? PHONE : DESKTOP);
    const rt = await runtimeFor(baseURL, request);
    await signIn(page, { web: rt.web }, rt.credentials);
    let matterId: string | undefined;
    try {
      matterId = await createMatterThroughUi(page, rt, "Direct Tax");
      const ref = await attachIncomeTax80C(page, rt, matterId, phone);
      const stored = await references(request, rt, matterId);
      expect(stored.map((row) => [row.statute_id, row.section_number])).toEqual([["income-tax-1961", "Section 80C"]]);
      // Oracle: the attached provision is the edition's verified text and carries its repeal status.
      const detail = await json<{ statute: { legal_status: string }; section: { verification_status: string; legal_status: string; section_text: string } }>(
        await request.get(`${rt.api.origin}/api/statutes/income-tax-1961/sections/${encodeURIComponent("Section 80C")}`,
          { headers: rt.headers }),
        "Income-tax Section 80C detail");
      expect([detail.section.verification_status, detail.section.legal_status, detail.statute.legal_status])
        .toEqual(["verified_official", "repealed", "repealed"]);
      expect(detail.section.section_text).toMatch(/^80C\. \(1\) In computing the total income/);
      await removeReference(page, matterId, ref, phone);
      expect(await references(request, rt, matterId)).toEqual([]);
    } finally {
      if (matterId) await disposeMatter(page, rt, matterId);
    }
  });
}
