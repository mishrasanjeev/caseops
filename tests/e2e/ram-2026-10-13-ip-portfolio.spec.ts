/** IP13-02..09 / UJ-02,UJ-04: source cells -> saved records -> responsive UI.
 * IP13-01's historical upload failure is not inferred from this synthetic file.
 */
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { APIRequestContext, Page } from "@playwright/test";
import JSZip from "jszip";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv, repoRoot } from "./support/env";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0, mode: "default" });

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing setup is not a skip.`);
  return value;
}
const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
function csv(rows: string[][]): Buffer {
  return Buffer.from(rows.map(row => row.map(value => `"${value.replaceAll('"', '""')}"`).join(",")).join("\r\n"));
}

async function nativeDateWorkbook(page: Page, mark: string): Promise<Buffer> {
  const zip = await JSZip.loadAsync(readFileSync(path.join(process.cwd(),
    "tests/e2e/fixtures/ip-portfolio-native-dates-20261013.xlsx")));
  const member = zip.file("xl/worksheets/sheet1.xml");
  if (!member) throw new Error("Pinned native-date fixture worksheet is missing.");
  const xml = await page.evaluate(({ source, mark }) => {
    const doc = new DOMParser().parseFromString(source, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("Native-date fixture XML is invalid.");
    const cell = doc.querySelector('c[r="A2"] is t');
    if (!cell || cell.textContent !== "Synthetic native Excel date preview") {
      throw new Error("Native-date fixture mark contract changed.");
    }
    cell.textContent = mark;
    return new XMLSerializer().serializeToString(doc);
  }, { source: await member.async("string"), mark });
  zip.file("xl/worksheets/sheet1.xml", xml);
  return zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
}
type ImportRow = {
  created_docket_id: string | null; commit_status: string; commit_error_code: string | null;
  normalized: Record<string, unknown>; reconciliation_decision: string | null;
};
type ImportResult = {
  job: { id: string; status: string; total_rows: number; committed_rows: number; failed_rows: number;
    preview_token: string | null; version: number; recovery_available: boolean;
    valid_rows: number; invalid_rows: number; commit_batch_size: number; source_sha256: string }; rows: ImportRow[];
};

type PortfolioActor = { company: { id: string; slug: string }; membership: { id: string }; access_token: string };

function grantLocalPortfolioEntitlement(web: URL, api: URL, actor: PortfolioActor, slug: string) {
  if (![web, api].every(origin => loopback(origin) && ["http:", "https:"].includes(origin.protocol)
    && !origin.username && !origin.password)) throw new Error("Fixture grants require loopback origins.");
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  if (!slug.startsWith("ip13-") || !uuid.test(slug.slice(5)) || actor.company.slug !== slug
    || !uuid.test(actor.company.id)) throw new Error("Fixture grant must match the newly bootstrapped IP13 tenant.");
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  if (database.startsWith("postgresql+psycopg://")) {
    const target = new URL(database);
    if (!loopback(target) || target.search || target.hash || target.pathname.length <= 1) {
      throw new Error("Fixture grants require an explicit loopback database without connection overrides.");
    }
  } else if (database.startsWith("sqlite+pysqlite:///")) {
    const target = database.slice("sqlite+pysqlite:///".length);
    const relative = path.relative(repoRoot, path.resolve(target));
    if (!path.isAbsolute(target) || /[?#%]/.test(target) || target.startsWith("//") || target.startsWith("\\\\")
      || relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Fixture SQLite database must belong to this candidate.");
  } else throw new Error("Unsupported fixture database; no entitlement grant was attempted.");
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps", "api", ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const pythonRelative = path.relative(path.join(repoRoot, "apps", "api", ".venv"), path.resolve(python));
  if (pythonRelative.startsWith("..") || path.isAbsolute(pythonRelative)) throw new Error("Fixture Python must belong to this candidate.");
  const script = [
    "import os",
    "from pathlib import Path",
    "from sqlalchemy.engine import make_url",
    "url=make_url(os.environ['CASEOPS_DATABASE_URL'])",
    "assert not url.query",
    "assert (url.drivername=='postgresql+psycopg' and url.host in {'localhost','127.0.0.1','::1'} and url.database) or (url.drivername=='sqlite+pysqlite' and Path(url.database).is_absolute() and Path(url.database).resolve().is_relative_to(Path.cwd().resolve()))",
    "from caseops_api.db.models import BillingSubscription,Company,CompanyMembership",
    "from caseops_api.db.session import get_session_factory",
    "with get_session_factory()() as session:",
    "    company=session.get(Company,os.environ['CASEOPS_E2E_COMPANY_ID'])",
    "    assert company is not None and company.slug==os.environ['CASEOPS_E2E_COMPANY_SLUG'] and company.slug.startswith('ip13-')",
    "    owner=session.get(CompanyMembership,os.environ['CASEOPS_E2E_MEMBERSHIP_ID'])",
    "    assert owner is not None and owner.company_id==company.id and owner.is_active and owner.role=='owner'",
    "    session.add(BillingSubscription(company_id=company.id,status='manual_active',segment='law_firm',source='ip13_local_fixture',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], { cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: database, CASEOPS_LLM_PROVIDER: "mock",
      CASEOPS_EMBEDDING_PROVIDER: "mock", CASEOPS_E2E_COMPANY_ID: actor.company.id,
      CASEOPS_E2E_COMPANY_SLUG: slug, CASEOPS_E2E_MEMBERSHIP_ID: actor.membership.id,
      PYTHONPATH: path.join(repoRoot, "apps", "api", "src") } });
  expect(result.status, `Local fixture grant failed: ${result.error?.message ?? result.stderr}`).toBe(0);
}

function deliverLocalImportedReminder(web: URL, api: URL, actor: PortfolioActor,
  docketId: string, sourceId: string, intentId: string) {
  if (![web, api].every(origin => loopback(origin) && ["http:", "https:"].includes(origin.protocol)
    && !origin.username && !origin.password)) throw new Error("Local delivery requires loopback origins.");
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  if (!actor.company.slug.startsWith("ip13-") || !uuid.test(actor.company.slug.slice(5))
    || ![actor.company.id, actor.membership.id, docketId, sourceId, intentId].every(id => uuid.test(id))) {
    throw new Error("Local delivery must belong to a fresh isolated IP13 fixture.");
  }
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps", "api", ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const relative = path.relative(path.join(repoRoot, "apps", "api", ".venv"), path.resolve(python));
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Local delivery requires candidate-owned Python.");
  const script = [
    "import os",
    "from pathlib import Path",
    "from sqlalchemy.engine import make_url",
    "url=make_url(os.environ['CASEOPS_DATABASE_URL'])",
    "assert not url.query",
    "assert (url.drivername=='postgresql+psycopg' and url.host in {'localhost','127.0.0.1','::1'} and url.database) or (url.drivername=='sqlite+pysqlite' and Path(url.database).is_absolute() and Path(url.database).resolve().is_relative_to(Path.cwd().resolve()))",
    "from caseops_api.db.models import Company,CompanyMembership,InAppNotification,NotificationDeliveryIntent",
    "from caseops_api.db.session import get_session_factory",
    "from caseops_api.services.notification_delivery import process_notification_delivery_intent",
    "with get_session_factory()() as session:",
    "    company=session.get(Company,os.environ['CASEOPS_E2E_COMPANY_ID'])",
    "    assert company and company.slug==os.environ['CASEOPS_E2E_COMPANY_SLUG'] and company.slug.startswith('ip13-')",
    "    owner=session.get(CompanyMembership,os.environ['CASEOPS_E2E_MEMBERSHIP_ID'])",
    "    assert owner and owner.company_id==company.id and owner.is_active and owner.role=='owner'",
    "    intent=session.get(NotificationDeliveryIntent,os.environ['CASEOPS_E2E_INTENT_ID'])",
    "    assert intent and intent.company_id==company.id and intent.recipient_membership_id==owner.id",
    "    assert intent.ip_docket_id==os.environ['CASEOPS_E2E_DOCKET_ID'] and intent.source_id==os.environ['CASEOPS_E2E_SOURCE_ID']",
    "    assert str(intent.channel)=='in_app' and intent.event_type=='renewal_source_date_1month' and intent.source_type=='ip_trademark_particular_version'",
    "    result=process_notification_delivery_intent(session,intent_id=intent.id,company_id=company.id)",
    "    assert result.delivered and str(result.status)=='delivered' and result.external_calls==0",
    "    note=session.get(InAppNotification,intent.in_app_notification_id)",
    "    assert note and note.company_id==company.id and note.recipient_membership_id==owner.id and note.source_id==intent.source_id",
    "    assert note.event_type==intent.event_type and note.body==intent.body and 'private import remark' not in note.body",
    "    assert intent.attempts==1",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], { cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: database, CASEOPS_LLM_PROVIDER: "mock",
      CASEOPS_EMBEDDING_PROVIDER: "mock", CASEOPS_E2E_COMPANY_ID: actor.company.id,
      CASEOPS_E2E_COMPANY_SLUG: actor.company.slug, CASEOPS_E2E_MEMBERSHIP_ID: actor.membership.id,
      CASEOPS_E2E_DOCKET_ID: docketId, CASEOPS_E2E_SOURCE_ID: sourceId, CASEOPS_E2E_INTENT_ID: intentId,
      PYTHONPATH: path.join(repoRoot, "apps", "api", "src") } });
  expect(result.status, `Local in-app delivery failed: ${result.error?.message ?? result.stderr}`).toBe(0);
}

async function preparePortfolioWorkspace(request: APIRequestContext, web: URL, api: URL,
  local: boolean, actor: PortfolioActor, slug: string, headers: Record<string, string>) {
  if (local) {
    grantLocalPortfolioEntitlement(web, api, actor, slug);
    const configured = await request.put(`${api.origin}/api/ip/workspace/configuration`, { headers, data: {
      expected_version: null, enabled_asset_types: ["trademark"], jurisdictions: ["IN"], offices: ["IP India"],
      timezone: "Asia/Kolkata", holiday_calendar_key: "ip13-synthetic-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] }, document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1", deadline_rule_versions: { IN: "2026.1" },
      notification_channels: ["in_app"], critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: actor.membership.id, provider_keys: [], provider_terms_version: null,
      accept_provider_terms: false,
    } });
    expect(configured.status(), await configured.text()).toBe(200);
    const configuration = (await configured.json()).configuration;
    expect(configuration.version).toBeGreaterThan(0);
    const enabled = await request.post(`${api.origin}/api/ip/workspace/enable`, { headers,
      data: { expected_config_version: configuration.version, enabled_automations: [] } });
    expect(enabled.status(), await enabled.text()).toBe(200);
  }
  const response = await request.get(`${api.origin}/api/ip/readiness`, { headers });
  expect(response.status(), await response.text()).toBe(200);
  const readiness = await response.json();
  if (!readiness.workspace_available || !readiness.manual_docketing_available) {
    throw new Error(`IP portfolio workspace precondition failed: ${JSON.stringify({
      features: readiness.features.map((feature: { feature_id: string; reason: string }) =>
        ({ feature_id: feature.feature_id, reason: feature.reason })),
      blockers: readiness.configuration_status.enablement_blockers,
    })}`);
  }
  expect(readiness.configuration_status.configuration.workspace_enabled).toBe(true);
  for (const id of ["workspace_core", "manual_docketing"]) {
    expect(readiness.features.find((feature: { feature_id: string }) => feature.feature_id === id))
      .toMatchObject({ available: true, entitled: true, rollout_enabled: true, reason: "available" });
  }
  if (local) expect(readiness.configuration_status.configuration.enabled_automations_json).toEqual([]);
}

async function preparePortfolio(page: Page, request: APIRequestContext, baseURL: string | undefined, width: number) {
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const api = new URL(process.env.PROD_API_BASE_URL ?? (loopback(web)
      ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
      : required("PROD_API_BASE_URL")));
    if (web.username || web.password || api.username || api.password) throw new Error("Credential-bearing origins are forbidden.");
    if (loopback(web) !== loopback(api)) throw new Error("Mixed local/remote origins are forbidden before any request.");
    const local = loopback(web) && loopback(api);
    if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
      throw new Error("Only canonical production origins may be used.");
    }
    const sha = local ? required("CASEOPS_RELEASE_SHA") : required("CASEOPS_EXPECTED_RELEASE_SHA");
    expect(sha).toMatch(/^[a-f0-9]{40}$/);
    const run = randomUUID();
    const credentials = local ? {
      slug: `ip13-${run}`, email: `owner-${run}@example.com`, password: `Portfolio!${randomUUID()}`,
    } : {
      slug: process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal",
      email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() || required("CASEOPS_TEST_LEGAL_PROD_PASSWORD"),
    };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production writes are test-legal only.");
    async function release(client: APIRequestContext) {
      for (const path of [`${api.origin}/api/build`, `${web.origin}/api/release-identity`]) {
        const response = await client.get(path, { headers: noPaidProviderHeaders });
        expect(response.status(), "exact serving API/web identity before authentication").toBe(200);
        expect((await response.json()).release_sha).toBe(sha);
      }
    }
    await release(request);
    let freshCompanyId: string | undefined;
    if (local) {
      const bootstrap = await request.post(`${api.origin}/api/bootstrap/company`, {
        headers: noPaidProviderHeaders, data: {
          company_name: `Isolated IP import ${run}`, company_slug: credentials.slug,
          company_type: "law_firm", owner_full_name: "Isolated IP portfolio owner",
          owner_email: credentials.email, owner_password: credentials.password,
        },
      });
      expect(bootstrap.status(), await bootstrap.text()).toBe(200);
      const fresh = await bootstrap.json() as PortfolioActor;
      expect(fresh.company.slug).toBe(credentials.slug);
      freshCompanyId = fresh.company.id;
    }
    const login = await request.post(`${api.origin}/api/auth/login`, {
      headers: noPaidProviderHeaders,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
    });
    expect(login.status(), await login.text()).toBe(200);
    const actor = await login.json();
    expect(actor.company.slug).toBe(credentials.slug);
    if (local) expect(actor.company.id).toBe(freshCompanyId);
    const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
    await preparePortfolioWorkspace(request, web, api, local, actor, credentials.slug, headers);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    return { web, api, local, run, headers, release, actor: actor as PortfolioActor };
}

for (const width of [1280, 393]) {
  test(`source-tolerant portfolio import, duplicate skip and renewal alert at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(660_000);
    const { web, api, local, run, headers, release, actor } = await preparePortfolio(page, request, baseURL, width);
    // Actual Excel datetime cells, independently pinned to this synthetic fixture.
    const nativeName = `ip13-native-${run}.xlsx`;
    const nativeMark = `Synthetic native Excel date ${run}`;
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByLabel("CSV or XLSX file").setInputFiles({
      name: `ip13-invalid-${run}.xlsx`,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("isolated invalid spreadsheet bytes"),
    });
    const parserRejected = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/ip/imports/upload"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const rejectedFile = await parserRejected;
    expect(rejectedFile.status(), await rejectedFile.text()).toBe(422);
    const safeProblem = await rejectedFile.json();
    expect(safeProblem.detail).toBe("The XLSX file could not be read.");
    expect(rejectedFile.headers()["access-control-allow-origin"]).toBe(web.origin);
    expect(rejectedFile.headers()["x-request-id"]).toBe(safeProblem.request_id);
    await expect(page.getByText("The XLSX file could not be read.", { exact: true })).toBeVisible();
    await page.getByLabel("CSV or XLSX file").setInputFiles({ name: nativeName,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: await nativeDateWorkbook(page, nativeMark) });
    const nativeUploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const nativeResponse = await nativeUploaded;
    expect(nativeResponse.status(), await nativeResponse.text()).toBe(201);
    expect(nativeResponse.headers()["access-control-allow-origin"]).toBe(web.origin);
    const nativePreview = await nativeResponse.json() as ImportResult;
    expect(nativePreview.job.total_rows).toBe(1);
    expect(nativePreview.rows[0].normalized.application_date).toBe("2026-01-31");
    expect(nativePreview.rows[0].normalized.renewal_due_date).toBe("2035-03-31");
    expect(nativePreview.rows[0].normalized.class_numbers).toEqual([9, 36]);
    expect(nativePreview.rows[0].created_docket_id).toBeNull();
    await expect(page.getByRole("heading", { name: `Review ${nativeName}`, exact: true })).toBeVisible();
    await expect(page.getByText("2035-03-31", { exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: new RegExp(nativeName.replace(".xlsx", "\\.xlsx")) }).click();
    await expect(page.getByRole("heading", { name: `Review ${nativeName}`, exact: true })).toBeVisible();
    await expect(page.getByText("2035-03-31", { exact: true })).toBeVisible();
    const retainedNative = await request.get(`${api.origin}/api/ip/imports/${nativePreview.job.id}`, { headers });
    expect(retainedNative.status()).toBe(200);
    expect((await retainedNative.json()).rows).toEqual(nativePreview.rows);
    const noNativeDocket = await request.get(`${api.origin}/api/ip/portfolio`, {
      headers, params: { query: nativeMark },
    });
    expect(noNativeDocket.status()).toBe(200);
    expect((await noNativeDocket.json()).rows).toHaveLength(0);
    const nativeCommitted = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${nativePreview.job.id}/commit`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const nativeCommit = await nativeCommitted;
    expect(nativeCommit.status(), await nativeCommit.text()).toBe(200);
    const nativeSaved = await nativeCommit.json() as ImportResult;
    expect(nativeSaved.job.committed_rows).toBe(1);
    expect(nativeSaved.job.failed_rows).toBe(0);
    expect(nativeSaved.rows[0].commit_status).toBe("committed");
    expect(nativeSaved.rows[0].created_docket_id).toBeTruthy();
    const nativeRecord = await request.get(
      `${api.origin}/api/ip/dockets/${nativeSaved.rows[0].created_docket_id}`, { headers });
    expect(nativeRecord.status()).toBe(200);
    const nativeDocket = await nativeRecord.json();
    expect(nativeDocket.title).toBe(nativeMark);
    expect(nativeDocket.status).toBe("draft");
    expect(nativeDocket.current_particulars.representation_json.portfolio_import.application_date)
      .toBe("2026-01-31");
    expect(nativeDocket.current_particulars.representation_json.portfolio_import.renewal_due_date)
      .toBe("2035-03-31");
    expect(nativeDocket.current_particulars.classes_json.map((item: { class_number: number }) => item.class_number))
      .toEqual([9, 36]);
    await page.reload();
    await page.getByRole("button", { name: new RegExp(nativeName.replace(".xlsx", "\\.xlsx")) }).click();
    await expect(page.getByRole("region", { name: `Review ${nativeName}`, exact: true })
      .getByText(/1 created; 0 linked; 0 skipped/)).toBeVisible();
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(nativeMark);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(page.getByRole("link", { name: nativeMark, exact: true })).toBeVisible();
    const nativePortfolioRow = (width >= 768 ? page.getByRole("row") : page.getByRole("article"))
      .filter({ has: page.getByRole("link", { name: nativeMark, exact: true }) });
    await expect(nativePortfolioRow.getByText("2035-03-31", { exact: true })).toBeVisible();
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByLabel("CSV or XLSX file").setInputFiles({
      name: `ip13-native-separate-${run}.xlsx`,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: await nativeDateWorkbook(page, nativeMark),
    });
    const duplicateNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/ip/imports/upload"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const duplicateNative = await duplicateNativeResponse;
    expect(duplicateNative.status(), await duplicateNative.text()).toBe(201);
    const duplicateNativePreview = await duplicateNative.json() as ImportResult;
    expect(duplicateNativePreview.rows[0].reconciliation_decision).toBe("skip");
    await page.getByLabel("Decision for row 1").click();
    await page.getByRole("option", { name: "Create separate record", exact: true }).click();
    const reconciledNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${duplicateNativePreview.job.id}/reconcile`);
    await page.getByRole("button", { name: "Save duplicate decisions", exact: true }).click();
    const reconciledNative = await reconciledNativeResponse;
    expect(reconciledNative.status(), await reconciledNative.text()).toBe(200);
    const separateNativeResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === `/api/ip/imports/${duplicateNativePreview.job.id}/commit`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const separateNative = await separateNativeResponse;
    expect(separateNative.status(), await separateNative.text()).toBe(200);
    const separateSaved = await separateNative.json() as ImportResult;
    expect(separateSaved.job.committed_rows).toBe(1);
    expect(separateSaved.job.failed_rows).toBe(0);
    expect(separateSaved.rows[0].created_docket_id).toBeTruthy();
    expect(separateSaved.rows[0].created_docket_id).not.toBe(nativeSaved.rows[0].created_docket_id);
    const mark = `IP source ${run}`;
    const number = `IP13/${run}`;
    const due = `${new Date().getUTCFullYear() + 3}-03-31`;
    const sourceHeaders = ["S.No.", "Trademark", "Trademark Image", "Application Date", "Renewal Due Date",
      "Applicant Name(s)", "Class", "Application No.", "Status", "Comment", "Takeover request",
      "Name Change request", "Address Change request", "Internal Remarks", "Jurisdiction", "Office", "Extra column"];
    const positive = ["source-1", mark, "logo-source-reference", "31/01/2026", due,
      "Source Owner One; Source Owner Two", "9, 36, and 42", number, "Registered", "Original source comment",
      "Pending", "N.A.", "No", "private import remark", "IN", "IP India", "extra source evidence"];
    const separate = [...positive]; separate[0] = "source-3"; separate[7] = `${number}-B`;
    const warning = [...positive]; warning[0] = "source-4"; warning[1] = `${mark} optional`;
    warning[3] = "invalid optional date"; warning[4] = "NA"; warning[5] = "N/A";
    warning[6] = "N.A."; warning[7] = `${number}-C`;
    const content = csv([sourceHeaders, positive, positive, separate, warning, Array(17).fill("")]);
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await expect(page.getByRole("heading", { name: "Trademark portfolio import", exact: true })).toBeVisible();
    await page.getByLabel("CSV or XLSX file").setInputFiles({ name: `ip13-${run}.csv`, mimeType: "text/csv", buffer: content });
    const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const upload = await uploaded;
    expect(upload.status(), await upload.text()).toBe(201);
    expect(upload.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    const preview = await upload.json() as ImportResult;
    expect(preview.job.total_rows).toBe(5);
    expect(preview.rows[1].reconciliation_decision).toBe("skip");
    expect(preview.rows[0].normalized.class_numbers).toEqual([9, 36, 42]);
    expect(preview.rows[0].normalized._source_values).toEqual(Object.fromEntries(
      sourceHeaders.map((header, index) => [header, positive[index]]),
    ));
    expect(preview.rows[3].normalized._warnings).toContainEqual({ field: "application_date", code: "invalid_optional_date" });
    expect(preview.rows[3].normalized.application_date).toBeUndefined();
    expect(preview.rows.every(row => row.created_docket_id === null)).toBe(true);
    const before = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: number } });
    expect(before.status()).toBe(200);
    expect((await before.json()).rows).toHaveLength(0);
    await expect(page.getByRole("heading", { name: `Review ip13-${run}.csv`, exact: true })).toBeVisible();
    await page.getByLabel("Decision for row 2").click();
    await expect(page.getByRole("option", { name: "Create separate record", exact: true })).toHaveCount(0);
    await page.getByRole("option", { name: "Skip row", exact: true }).click();
    await page.getByText("Source column mapping", { exact: true }).click();
    const expectedMappings = [
      ["S.No.", "source_reference", "source metadata"], ["Trademark", "mark_text", "canonical"],
      ["Trademark Image", "image_reference", "source metadata"], ["Application Date", "application_date", "canonical"],
      ["Renewal Due Date", "renewal_due_date", "canonical"], ["Applicant Name(s)", "applicant_name", "canonical"],
      ["Class", "class_number", "canonical"], ["Application No.", "application_number", "canonical"],
      ["Status", "source_status", "source metadata"], ["Comment", "comment", "source metadata"],
      ["Takeover request", "takeover_request", "source metadata"], ["Name Change request", "name_change_request", "source metadata"],
      ["Address Change request", "address_change_request", "source metadata"], ["Internal Remarks", "internal_remarks", "source metadata"],
    ];
    for (const [source, target, handling] of expectedMappings) {
      await expect(page.getByText(`${source}: ${target} (${handling})`, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Extra column: Unmapped (unmapped)", { exact: true })).toBeVisible();
    await expect(page.getByRole("row").filter({ has: page.getByText(`${number}-C`, { exact: true }) })
      .getByText("application_date: invalid optional date", { exact: true })).toBeVisible();
    const rawSource = page.getByRole("region", { name: `Review ip13-${run}.csv`, exact: true })
      .getByRole("row").filter({ has: page.getByRole("cell", { name: "1", exact: true }) }).locator("details");
    await rawSource.getByText("Source values", { exact: true }).click();
    await expect(rawSource.locator("dl > div")).toHaveCount(sourceHeaders.length);
    for (const [index, header] of sourceHeaders.entries()) {
      const cell = rawSource.locator("dl > div").filter({ has: page.getByText(header, { exact: true }) });
      await expect(cell.locator("dt")).toBeVisible();
      await expect(cell.locator("dd")).toHaveText(positive[index]);
    }
    await expect(page.getByRole("button", { name: "Commit to portfolio", exact: true })).toBeEnabled();
    const committed = page.waitForResponse(response => new URL(response.url()).pathname === `/api/ip/imports/${preview.job.id}/commit`);
    await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
    const commit = await committed;
    expect(commit.status(), await commit.text()).toBe(200);
    const saved = await commit.json() as ImportResult;
    expect(saved.job.status).toBe("committed");
    expect(saved.job.committed_rows).toBe(3);
    expect(saved.job.failed_rows).toBe(0);
    expect(saved.rows.map(row => row.commit_status)).toEqual(["committed", "skipped", "committed", "committed", "skipped"]);
    expect(saved.rows[1].commit_error_code).toBe("duplicate_skipped");
    const committedKey = await page.evaluate(jobId =>
      sessionStorage.getItem(`ip-import-commit:${jobId}`), preview.job.id);
    expect(committedKey).toBeTruthy();
    const explicitReplay = await request.post(`${api.origin}/api/ip/imports/${preview.job.id}/commit`, {
      headers, data: { preview_token: preview.job.preview_token, idempotency_key: committedKey },
    });
    expect(explicitReplay.status(), await explicitReplay.text()).toBe(200);
    const replayed = await explicitReplay.json();
    expect(replayed.replayed).toBe(true);
    expect(replayed.rows).toEqual(saved.rows);
    await expect(page.getByRole("region", { name: `Review ip13-${run}.csv`, exact: true })
      .getByText(/3 created; 0 linked; 2 skipped \(1 duplicates\); .*0 failed\./)).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    await expect(page.getByRole("heading", { name: `Review ip13-${run}.csv`, exact: true })).toBeVisible();
    const persisted = await request.get(`${api.origin}/api/ip/imports/${preview.job.id}`, { headers });
    expect(persisted.status()).toBe(200);
    expect((await persisted.json()).rows).toEqual(saved.rows);
    for (const row of saved.rows.filter(row => row.created_docket_id)) {
      const record = await request.get(`${api.origin}/api/ip/dockets/${row.created_docket_id}`, { headers });
      expect(record.status()).toBe(200);
      const docket = await record.json();
      expect(docket.status).toBe("draft");
      expect(docket.current_particulars.readiness_status).toBe("incomplete");
      expect(recordText(docket)).not.toContain("private import remark");
      if (row.normalized.application_number === `${number}-C`) {
        expect(docket.current_particulars.parties_json).toEqual([]);
        expect(docket.current_particulars.classes_json).toEqual([]);
      } else {
        expect(docket.current_particulars.classes_json.map((scope: { class_number: number }) => scope.class_number)).toEqual([9, 36, 42]);
        expect(docket.current_particulars.classes_json.every((scope: { specification: string }) => scope.specification === "")).toBe(true);
        expect(docket.current_particulars.representation_json.portfolio_import.renewal_due_date).toBe(due);
      }
    }
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(mark);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(page.getByRole("link", { name: mark, exact: true })).toHaveCount(2);
    for (const index of [0, 2]) {
      const row = (width >= 768 ? page.getByRole("row") : page.getByRole("article"))
        .filter({ has: page.getByText(String(saved.rows[index].normalized.application_number), { exact: true }) });
      await expect(row.getByRole("link", { name: mark, exact: true }))
        .toHaveAttribute("href", `/app/ip?docket=${saved.rows[index].created_docket_id}`);
    }
    const sourceRow = (width >= 768 ? page.getByRole("row") : page.getByRole("article"))
      .filter({ has: page.getByText(number, { exact: true }) });
    await expect(sourceRow.getByText(due, { exact: true })).toBeVisible();
    await expect(sourceRow.getByText("Alert: queued", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await sourceRow.getByRole("link", { name: mark, exact: true }).click();
    await expect(page).toHaveURL(`${web.origin}/app/ip?docket=${saved.rows[0].created_docket_id}`);
    await expect(page.getByRole("heading", { name: mark, exact: true })).toBeVisible();
    const docketId = saved.rows[0].created_docket_id;
    expect(docketId).toBeTruthy();
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    const importedRow = page.getByRole("row")
      .filter({ has: page.getByText(number, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Edit source renewal date", exact: true }) });
    const correctedDue = `${new Date().getUTCFullYear() + 3}-04-30`;
    for (const nextDue of [correctedDue, null]) {
      await importedRow.getByRole("button", { name: "Edit source renewal date", exact: true }).click();
      const editor = page.getByRole("dialog", { name: "Correct source renewal date" });
      await expect(editor).toBeVisible();
      await expect(editor.getByLabel("Renewal due date")).toHaveValue(nextDue ? due : correctedDue);
      if (nextDue) await editor.getByLabel("Renewal due date").fill(nextDue);
      else await editor.getByRole("button", { name: "Clear date", exact: true }).click();
      await editor.getByLabel("Correction reason").fill(nextDue ? "Synthetic source date correction" : "Synthetic source date withdrawn");
      const updated = page.waitForResponse(response => new URL(response.url()).pathname ===
        `/api/ip/dockets/${docketId}/portfolio-renewal-date` && response.request().method() === "PATCH");
      await editor.getByRole("button", { name: "Save source date", exact: true }).click();
      const update = await updated;
      expect(update.status(), await update.text()).toBe(200);
      await expect(editor).not.toBeVisible();
      const current = await request.get(`${api.origin}/api/ip/dockets/${docketId}`, { headers });
      expect(current.status()).toBe(200);
      expect((await current.json()).current_particulars.representation_json.portfolio_import.renewal_due_date).toBe(nextDue);
      const portfolio = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: number } });
      expect(portfolio.status()).toBe(200);
      const currentRow = (await portfolio.json()).rows.find((row: { docket_id: string }) => row.docket_id === docketId);
      expect(currentRow.source_renewal_due_on).toBe(nextDue);
      expect(currentRow.source_renewal_alert_status).toBe(nextDue ? "queued" : null);
      await page.goto(`${web.origin}/app/ip/portfolio`);
      await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
      await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
      await expect(sourceRow).toBeVisible();
      if (nextDue) {
        await expect(sourceRow.getByText(nextDue, { exact: true })).toBeVisible();
        await expect(sourceRow.getByText(due, { exact: true })).toHaveCount(0);
        await expect(sourceRow.getByText("Alert: queued", { exact: true })).toBeVisible();
        await page.reload();
        await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
        await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
        await expect(sourceRow.getByText(nextDue, { exact: true })).toBeVisible();
      } else {
        await expect(sourceRow.getByText(correctedDue, { exact: true })).toHaveCount(0);
        await expect(sourceRow.getByText("Alert: queued", { exact: true })).toHaveCount(0);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      await page.goto(`${web.origin}/app/ip/portfolio/imports`);
      await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    }
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    await importedRow.getByRole("button", { name: "Edit source renewal date", exact: true }).click();
    const deliveryEditor = page.getByRole("dialog", { name: "Correct source renewal date" });
    await deliveryEditor.getByLabel("Renewal due date").fill(tomorrow);
    await deliveryEditor.getByLabel("Correction reason").fill("Synthetic due-soon in-app delivery acceptance");
    const deliveryCorrection = page.waitForResponse(response => new URL(response.url()).pathname ===
      `/api/ip/dockets/${docketId}/portfolio-renewal-date` && response.request().method() === "PATCH");
    await deliveryEditor.getByRole("button", { name: "Save source date", exact: true }).click();
    const deliveryUpdate = await deliveryCorrection;
    expect(deliveryUpdate.status(), await deliveryUpdate.text()).toBe(200);
    await expect(deliveryEditor).not.toBeVisible();
    const deliveryDocket = await request.get(`${api.origin}/api/ip/dockets/${docketId}`, { headers });
    expect(deliveryDocket.status()).toBe(200);
    const deliverySourceId = (await deliveryDocket.json()).current_particulars.id as string;
    type SourceIntent = { id: string; source_id: string; source_type: string; channel: string;
      event_type: string; status: string; attempts: number; destination: string | null };
    async function currentSourceIntent(): Promise<SourceIntent> {
      const response = await request.get(`${api.origin}/api/admin/notifications`, { headers, params: { limit: 200 } });
      expect(response.status(), await response.text()).toBe(200);
      const matches = ((await response.json()).intents as SourceIntent[])
        .filter(intent => intent.source_id === deliverySourceId && intent.event_type === "renewal_source_date_1month");
      expect(matches, "exact current-version renewal intent must remain visible").toHaveLength(1);
      return matches[0];
    }
    const deliveryIntent = await currentSourceIntent();
    expect(deliveryIntent).toMatchObject({ source_type: "ip_trademark_particular_version", channel: "in_app", destination: null });
    // Only loopback fixtures invoke the real owner directly. Production observes
    // the ordinary scheduler and never starts a global/provider delivery job.
    if (local) deliverLocalImportedReminder(web, api, actor, docketId!, deliverySourceId, deliveryIntent.id);
    await expect.poll(async () => (await currentSourceIntent()).status, {
      timeout: local ? 15_000 : 420_000, intervals: [1000, 5000, 10_000],
      message: "the source-renewal-specific in-app intent must actually be delivered",
    }).toBe("delivered");
    expect(await currentSourceIntent()).toMatchObject({ id: deliveryIntent.id, attempts: 1 });
    const deliveredPortfolio = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: number } });
    expect(deliveredPortfolio.status()).toBe(200);
    const deliveredRow = (await deliveredPortfolio.json()).rows
      .find((row: { docket_id: string }) => row.docket_id === docketId);
    const deliveredBody = deliveredRow.source_renewal_alert_body;
    expect(typeof deliveredBody).toBe("string");
    expect(deliveredBody).toContain(`${mark}; application ${number}; classes 9, 36, 42;`);
    expect(deliveredBody).toContain("Source Owner One");
    expect(deliveredBody).toContain("Source Owner Two");
    expect(deliveredBody).toContain(`Source renewal date ${tomorrow} (not a verified legal deadline).`);
    expect(deliveredBody).toMatch(/\d+ days remaining on the alert date\./);
    expect(deliveredBody).toContain(`/app/ip?docket=${docketId}`);
    expect(deliveredBody).not.toContain("private import remark");
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(sourceRow.getByText(tomorrow, { exact: true })).toBeVisible();
    await expect(sourceRow.getByText("Alert: delivered", { exact: true })).toBeVisible();
    await sourceRow.locator("summary").filter({ hasText: /^Renewal alert$/ }).click();
    await expect(sourceRow.getByTestId(`ip-source-renewal-alert-${docketId}`)).toHaveText(deliveredBody);
    await expect(sourceRow.getByTestId(`ip-source-renewal-alert-${docketId}`)).toBeVisible();
    await page.reload();
    await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(sourceRow.getByText("Alert: delivered", { exact: true })).toBeVisible();
    await sourceRow.locator("summary").filter({ hasText: /^Renewal alert$/ }).click();
    await expect(sourceRow.getByTestId(`ip-source-renewal-alert-${docketId}`)).toHaveText(deliveredBody);
    await expect(sourceRow.getByTestId(`ip-source-renewal-alert-${docketId}`)).toBeVisible();
    await page.goto(`${web.origin}/app/admin/notifications`);
    const receipt = page.getByTestId(`notification-intent-${deliveryIntent.id}`);
    await expect(receipt.getByText("delivered", { exact: true })).toBeVisible();
    await expect(receipt.getByText("renewal source date 1month", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByRole("button", { name: new RegExp(`ip13-${run}\\.csv`) }).click();
    await importedRow.getByRole("button", { name: "Edit source renewal date", exact: true }).click();
    await deliveryEditor.getByRole("button", { name: "Clear date", exact: true }).click();
    await deliveryEditor.getByLabel("Correction reason").fill("Synthetic delivered source date withdrawn");
    const deliveredClear = page.waitForResponse(response => new URL(response.url()).pathname ===
      `/api/ip/dockets/${docketId}/portfolio-renewal-date` && response.request().method() === "PATCH");
    await deliveryEditor.getByRole("button", { name: "Save source date", exact: true }).click();
    const clearResponse = await deliveredClear;
    expect(clearResponse.status(), await clearResponse.text()).toBe(200);
    await expect(deliveryEditor).not.toBeVisible();
    expect(await currentSourceIntent()).toMatchObject({ id: deliveryIntent.id, status: "delivered", attempts: 1 });
    const immutableSource = await request.get(`${api.origin}/api/ip/imports/${preview.job.id}`, { headers });
    expect((await immutableSource.json()).rows).toEqual(saved.rows);
    await page.goto(`${web.origin}/app/ip/portfolio`);
    await page.getByPlaceholder("Mark, application number, opposition number").fill(number);
    await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
    await expect(sourceRow.getByText(due, { exact: true })).toHaveCount(0);
    await expect(sourceRow.getByText("Alert: queued", { exact: true })).toHaveCount(0);
    await expect(sourceRow.getByTestId(`ip-source-renewal-alert-${docketId}`)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    if (local) await test.info().attach(`ip-import-${width}px`, { body: await page.screenshot(), contentType: "image/png" });
    await release(request);
  });

  test(`acknowledged 50-row batches recover from keyless history at ${width}px`, async ({ page, request, baseURL }) => {
    test.setTimeout(180_000);
    const { web, api, run, headers, release } = await preparePortfolio(page, request, baseURL, width);
    const filename = `ip13-batches-${run}.csv`;
    const prefix = `IP13 batch ${run}`;
    const numbers = Array.from({ length: 101 }, (_, index) => `${run}-${index + 1}`);
    const content = csv([["Trademark", "Application No.", "Jurisdiction", "Office"],
      ...numbers.map((number, index) => [`${prefix} ${index + 1}`, number, "IN", "IP India"])]);
    await page.goto(`${web.origin}/app/ip/portfolio/imports`);
    await page.getByLabel("CSV or XLSX file").setInputFiles({ name: filename, mimeType: "text/csv", buffer: content });
    const uploaded = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/imports/upload"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Validate file", exact: true }).click();
    const upload = await uploaded;
    expect(upload.status(), await upload.text()).toBe(201);
    const preview = await upload.json() as ImportResult;
    expect(preview.job.total_rows).toBe(101);
    expect(preview.job.valid_rows).toBe(101);
    expect(preview.job.invalid_rows).toBe(0);
    expect(preview.rows.every(row => row.created_docket_id === null)).toBe(true);
    expect(preview.rows.every(row => !row.normalized.application_date && !row.normalized.renewal_due_date
      && !row.normalized.applicant_name && !(row.normalized.class_numbers as unknown[])?.length)).toBe(true);
    expect(preview.rows.every(row => (row.normalized._warnings as Array<{ field: string; code: string }>).some(
      warning => warning.field === "applicant_name" && warning.code === "source_incomplete_draft",
    ))).toBe(true);
    const key = randomUUID();
    await page.evaluate(({ id, key }) => sessionStorage.setItem(`ip-import-commit:${id}`, key), { id: preview.job.id, key });
    // Only an acknowledged successful server batch is resumed; no failed mutation is retried.
    const first = await request.post(`${api.origin}/api/ip/imports/${preview.job.id}/commit`, {
      headers, data: { preview_token: preview.job.preview_token, idempotency_key: key },
    });
    expect(first.status(), await first.text()).toBe(202);
    const staged = await first.json() as ImportResult;
    expect(staged.job.status).toBe("staged");
    expect(staged.job.committed_rows).toBe(50);
    expect(staged.job.failed_rows).toBe(0);
    expect(staged.job.commit_batch_size).toBe(50);
    expect(staged.job.recovery_available).toBe(true);
    expect(staged.rows.filter(row => row.commit_status === "pending")).toHaveLength(51);
    const originalIds = staged.rows.slice(0, 50).map(row => row.created_docket_id);
    expect(originalIds.every(Boolean)).toBe(true);
    const health = await request.get(`${api.origin}/api/health`, { headers: noPaidProviderHeaders });
    expect(health.status()).toBe(200);
    await page.evaluate(() => sessionStorage.clear());
    await page.reload();
    await page.getByRole("button", { name: new RegExp(filename.replace(".csv", "\\.csv")) }).click();
    await expect(page.getByRole("heading", { name: `Review ${filename}`, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Commit to portfolio", exact: true })).toBeEnabled();
    expect(await page.evaluate(id => sessionStorage.getItem(`ip-import-commit:${id}`), preview.job.id)).toBeNull();
    const continuationRequests: Array<{ pathname: string; marker: string; body: Record<string, unknown> }> = [];
    const transportFailures: string[] = [];
    const continuations: Array<Promise<{ status: number; body: ImportResult }>> = [];
    const matches = (operation: import("@playwright/test").Request) => operation.method() === "POST"
      && new URL(operation.url()).pathname.startsWith(`/api/ip/imports/${preview.job.id}/`);
    const observeRequest = (operation: import("@playwright/test").Request) => {
      if (!matches(operation)) return;
      continuationRequests.push({ pathname: new URL(operation.url()).pathname,
        marker: operation.headers()["x-caseops-automated-test"], body: operation.postDataJSON() as Record<string, unknown> });
    };
    const observeFailure = (operation: import("@playwright/test").Request) => {
      if (matches(operation)) transportFailures.push(operation.failure()?.errorText ?? "unknown transport failure");
    };
    const observeResponse = (response: import("@playwright/test").Response) => {
      if (!matches(response.request())) return;
      continuations.push(response.json().then(body => ({ status: response.status(), body })));
    };
    page.on("request", observeRequest);
    page.on("requestfailed", observeFailure);
    page.on("response", observeResponse);
    try {
      await page.getByRole("button", { name: "Commit to portfolio", exact: true }).click();
      await expect(page.getByRole("region", { name: `Review ${filename}`, exact: true })
        .getByText(/101 created; 0 linked; 0 skipped \(0 duplicates\); 101 with warnings; 0 failed\./)).toBeVisible();
      const results = await Promise.all(continuations);
      expect(transportFailures).toEqual([]);
      expect(results.map(result => result.status)).toEqual([202, 200]);
      expect(results.map(result => result.body.job.committed_rows)).toEqual([100, 101]);
      expect(continuationRequests.map(item => item.pathname)).toEqual([
        `/api/ip/imports/${preview.job.id}/resume`, `/api/ip/imports/${preview.job.id}/resume`,
      ]);
      expect(continuationRequests.map(item => item.marker)).toEqual(["no-paid-providers", "no-paid-providers"]);
      expect(continuationRequests.map(item => item.body)).toEqual([
        { expected_job_version: staged.job.version, preview_token: staged.job.preview_token },
        { expected_job_version: results[0].body.job.version, preview_token: results[0].body.job.preview_token },
      ]);
      const saved = results[1].body;
      expect(saved.job.status).toBe("committed");
      expect(saved.job.source_sha256).toBe(preview.job.source_sha256);
      expect(saved.rows.every(row => row.commit_status === "committed")).toBe(true);
      expect(new Set(saved.rows.map(row => row.created_docket_id)).size).toBe(101);
      expect(saved.rows.slice(0, 50).map(row => row.created_docket_id)).toEqual(originalIds);
      expect(await page.evaluate(id => sessionStorage.getItem(`ip-import-commit:${id}`), preview.job.id)).toBeNull();
      await page.reload();
      await page.getByRole("button", { name: new RegExp(filename.replace(".csv", "\\.csv")) }).click();
      await expect(page.getByRole("region", { name: `Review ${filename}`, exact: true })
        .getByText(/101 created; 0 linked; 0 skipped \(0 duplicates\); 101 with warnings; 0 failed\./)).toBeVisible();
      const retained = await request.get(`${api.origin}/api/ip/imports/${preview.job.id}`, { headers });
      expect(retained.status()).toBe(200);
      expect((await retained.json()).rows).toEqual(saved.rows);
      const portfolio = await request.get(`${api.origin}/api/ip/portfolio`, { headers, params: { query: prefix, limit: 200 } });
      expect(portfolio.status()).toBe(200);
      const persisted = (await portfolio.json()).rows as Array<{ docket_id: string; application_numbers: string[] }>;
      expect(persisted).toHaveLength(101);
      expect(persisted.map(row => row.docket_id).sort()).toEqual(saved.rows.map(row => row.created_docket_id).sort());
      expect(persisted.flatMap(row => row.application_numbers).sort()).toEqual([...numbers].sort());
      await page.goto(`${web.origin}/app/ip/portfolio`);
      await page.getByPlaceholder("Mark, application number, opposition number").fill(numbers[100]);
      await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
      await expect(page.getByRole("link", { name: `${prefix} 101`, exact: true })).toBeVisible();
      await page.reload();
      await page.getByPlaceholder("Mark, application number, opposition number").fill(numbers[100]);
      await page.getByRole("button", { name: "Search portfolio", exact: true }).click();
      await expect(page.getByRole("link", { name: `${prefix} 101`, exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      await release(request);
    } finally {
      page.off("request", observeRequest);
      page.off("requestfailed", observeFailure);
      page.off("response", observeResponse);
    }
  });
}

function recordText(value: unknown): string { return JSON.stringify(value); }
