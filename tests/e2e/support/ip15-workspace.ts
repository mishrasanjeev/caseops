import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { expect, type APIRequestContext, type APIResponse, type Page } from "@playwright/test";

import type { IpDocket } from "../../../apps/web/lib/api/endpoints";
import { localTransportHeaders, noPaidProviderHeaders } from "./cost-controls";
import { e2eEnv, repoRoot } from "./env";
import { assertPublicReleaseIdentity } from "./public-release-identity";

type Ip15Actor = {
  company: { id: string; slug: string };
  membership: { id: string };
  access_token: string;
};

export type Ip15Workspace = {
  web: URL;
  api: URL;
  headers: Record<string, string>;
  release: () => Promise<void>;
  run: string;
  actor: Ip15Actor;
  local: boolean;
  timezone: string;
};

const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing IP15 setup is not a skip.`);
  return value;
}

async function body(response: APIResponse, operation: string, expected = 200) {
  expect(response.status(), `${operation} failed; response body intentionally not logged.`).toBe(expected);
  return response.json();
}

function localRuntime() {
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  if (database.startsWith("postgresql+psycopg://")) {
    const target = new URL(database);
    if (!loopback(target) || target.search || target.hash || target.pathname.length < 2) {
      throw new Error("IP15 requires a loopback test database without connection overrides.");
    }
  } else if (database.startsWith("sqlite+pysqlite:///")) {
    const filename = database.slice("sqlite+pysqlite:///".length);
    const relative = path.relative(repoRoot, path.resolve(filename));
    if (!path.isAbsolute(filename) || filename.startsWith("//") || filename.startsWith("\\\\")
      || /[?#%]/.test(filename) || relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error("IP15 SQLite fixtures must belong to this candidate.");
    }
  } else throw new Error("Unsupported IP15 fixture database; no grant attempted.");
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  const relative = path.relative(path.join(repoRoot, "apps/api/.venv"), path.resolve(python));
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("IP15 requires candidate-owned Python.");
  return { database, python };
}

function grantFreshLocalWorkspace(web: URL, api: URL, actor: Ip15Actor, slug: string) {
  if (![web, api].every(loopback) || !slug.startsWith("ip15-") || !uuid.test(slug.slice(5))
    || actor.company.slug !== slug || !uuid.test(actor.company.id) || !uuid.test(actor.membership.id)) {
    throw new Error("IP15 entitlement requires the exact newly bootstrapped loopback tenant.");
  }
  const { database, python } = localRuntime();
  const script = [
    "import os",
    "from pathlib import Path",
    "from sqlalchemy.engine import make_url",
    "url=make_url(os.environ['CASEOPS_DATABASE_URL'])",
    "assert not url.query",
    "assert (url.drivername=='postgresql+psycopg' and url.host in {'localhost','127.0.0.1','::1'} and url.database) or (url.drivername=='sqlite+pysqlite' and Path(url.database).is_absolute() and Path(url.database).resolve().is_relative_to(Path.cwd().resolve()))",
    "from caseops_api.db.models import Company,CompanyMembership,BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "with get_session_factory()() as session:",
    "    company=session.get(Company,os.environ['IP15_COMPANY_ID'])",
    "    assert company and company.slug==os.environ['IP15_SLUG'] and company.slug.startswith('ip15-')",
    "    owner=session.get(CompanyMembership,os.environ['IP15_OWNER_ID'])",
    "    assert owner and owner.company_id==company.id and owner.is_active and owner.role=='owner'",
    "    session.add(BillingSubscription(company_id=company.id,status='manual_active',segment='law_firm',source='ip15_local_fixture',externally_billable=False,entitlement_overrides_json={'ip_workspace':True,'ip_rule_governance':True}))",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], { cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: { ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: database, CASEOPS_LLM_PROVIDER: "mock",
      CASEOPS_EMBEDDING_PROVIDER: "mock", IP15_COMPANY_ID: actor.company.id, IP15_SLUG: slug,
      IP15_OWNER_ID: actor.membership.id, PYTHONPATH: path.join(repoRoot, "apps/api/src") } });
  expect(result.status, "Isolated IP15 fixture grant failed; private process output omitted.").toBe(0);
}

/** Callers disable traces/screenshots/video; returned credentials never belong in evidence. */
export async function prepareIp15Workspace(
  page: Page, request: APIRequestContext, baseURL: string | undefined, width: number,
): Promise<Ip15Workspace> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const api = new URL(process.env.PROD_API_BASE_URL ?? (loopback(web)
    ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}` : required("PROD_API_BASE_URL")));
  if (![web, api].every(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password)
    || loopback(web) !== loopback(api)) throw new Error("Unsafe or mixed IP15 origins.");
  const local = loopback(web) && loopback(api);
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote IP15 acceptance requires canonical production origins.");
  }
  if (local) localRuntime();
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("IP15 requires the exact expected 40-hex release.");
  const release = async () => {
    await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  };
  await release();
  const run = randomUUID();
  const credentials = local ? { slug: `ip15-${run}`, email: `owner-${run}@example.com`, password: `Synthetic!${randomUUID()}` }
    : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() || required("CASEOPS_TEST_LEGAL_PROD_PASSWORD") };
  if (!local && credentials.slug !== "test-legal") throw new Error("Production IP15 acceptance is test-legal only.");
  let freshId: string | undefined;
  if (local) {
    const fresh = await body(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders,
      data: { company_name: `Synthetic IP15 ${run}`, company_slug: credentials.slug, company_type: "law_firm",
        owner_full_name: "Synthetic IP15 owner", owner_email: credentials.email, owner_password: credentials.password } }), "Local bootstrap");
    expect(fresh.company.slug).toBe(credentials.slug);
    freshId = fresh.company.id;
  }
  const actor = await body(await request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } }), "IP15 login") as Ip15Actor;
  if (!uuid.test(actor.company.id) || !uuid.test(actor.membership.id) || typeof actor.access_token !== "string" || !actor.access_token
    || actor.company.slug !== credentials.slug || (local && actor.company.id !== freshId)) {
    throw new Error("IP15 authenticated tenant identity did not match the intended fixture.");
  }
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
  if (local) {
    grantFreshLocalWorkspace(web, api, actor, credentials.slug);
    const configured = await body(await request.put(`${api.origin}/api/ip/workspace/configuration`, { headers, data: {
      expected_version: null, enabled_asset_types: ["trademark"], jurisdictions: ["IN"], offices: ["IP India"],
      timezone: "Asia/Kolkata", holiday_calendar_key: "ip15", working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1", event_catalog_version: "ip-events-v1", deadline_rule_versions: { IN: "2026.1" },
      notification_channels: ["in_app"], critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: actor.membership.id, provider_keys: [], provider_terms_version: null, accept_provider_terms: false,
    } }), "Local workspace configuration");
    await body(await request.post(`${api.origin}/api/ip/workspace/enable`, { headers,
      data: { expected_config_version: configured.configuration.version, enabled_automations: [] } }), "Local workspace enablement");
  }
  const readiness = await body(await request.get(`${api.origin}/api/ip/readiness`, { headers }), "IP15 readiness");
  expect(readiness.workspace_available, "Workspace unavailable; no readiness or entitlement override is permitted remotely.").toBe(true);
  expect(readiness.manual_docketing_available).toBe(true);
  expect(readiness.configuration_status.configuration.workspace_enabled).toBe(true);
  const timezone = readiness.configuration_status.configuration.timezone;
  expect(typeof timezone).toBe("string");
  new Intl.DateTimeFormat("en", { timeZone: timezone }).format();
  if (local) {
    expect(timezone).toBe("Asia/Kolkata");
    expect(readiness.configuration_status.configuration.enabled_automations_json).toEqual([]);
  }
  await page.setViewportSize({ width, height: 1000 });
  await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
  await page.goto(`${web.origin}/sign-in`);
  await page.locator("#company-slug").fill(credentials.slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await release();
  return { web, api, headers, release, run, actor, local, timezone };
}

export async function createIp15ManualTrademark(
  workspace: Ip15Workspace, request: APIRequestContext, title = "Synthetic IP15 controls",
): Promise<{ docket: IpDocket; application: { id: string } }> {
  if (!workspace.local && workspace.actor.company.slug !== "test-legal") throw new Error("IP15 mutation requires the authorized QA tenant.");
  await workspace.release();
  const result = await body(await request.post(`${workspace.api.origin}/api/ip/trademark-applications/manual`, {
    headers: workspace.headers, data: {
      title: `${title} ${workspace.run}`, asset_title: `Synthetic IP15 mark ${workspace.run}`,
      jurisdiction: "IN", office: "IP India", filing_phase: "pre_filing", source_pending_identifier_allocation: false,
      particulars: { form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "Synthetic IP15 mark", evidence_reference: `fixture:ip15-mark:${workspace.run}` },
        classes: [{ class_number: 9, specification: "Synthetic controls software" }],
        parties: [{ role: "applicant", name: "Synthetic IP15 applicant" }],
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true,
          evidence_reference: `fixture:ip15-mark:${workspace.run}` }] },
    },
  }), "Manual trademark creation", 201);
  expect(result.docket.company_id).toBe(workspace.actor.company.id);
  expect(result.application.id).toMatch(uuid);
  await workspace.release();
  return result;
}
