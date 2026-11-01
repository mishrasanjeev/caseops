/**
 * Shared runtime for the 2026-10-31 Ram batch (CaseOps_Bugs (4).xlsx).
 *
 * Production runs sign in through the real sign-in form as the reporting
 * tester (test-legal / CASEOPS_RAM_PROD_EMAIL) on the exact expected release.
 * Local runs bootstrap a fresh tenant shaped like test-legal after its owner
 * approved grant: an enabled IP workspace with every IP entitlement and the
 * rule-governance rollout on. Nothing the reported workflow is supposed to
 * create through the UI is created here; callers prove those paths in the UI.
 *
 * Every positive assertion block must call `markPositive`, so a production
 * run that only reads (or branches around the write) cannot be counted as a
 * pass in the fix summary.
 */
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import {
  expect, request as playwrightRequest, type APIRequestContext, type APIResponse, type Locator, type Page,
  type Response, type TestInfo,
} from "@playwright/test";

import { localTransportHeaders, noPaidProviderHeaders } from "./cost-controls";
import { e2eEnv, repoRoot } from "./env";
import { assertPublicReleaseIdentity } from "./public-release-identity";

export type TesterActor = {
  company: { id: string; slug: string };
  membership: { id: string };
  access_token: string;
};

export type TesterCredentials = { slug: string; email: string; password: string };

export type TesterRuntime = {
  web: URL;
  api: URL;
  local: boolean;
  /** Clock + serial stamp; production tenants retain every run's records. */
  run: string;
  actor: TesterActor;
  credentials: TesterCredentials;
  /** Bearer headers for API oracles only. UI journeys must not use them to create the item under test. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};

export const IP_ENTITLEMENT_KEYS = [
  "ip_workspace", "ip_registry_sync", "ip_deadline_automation", "ip_notification_automation",
  "ip_filing_operations", "ip_watch", "ip_costs", "ip_rule_governance",
] as const;

const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const CENTRAL_HOLIDAY_CALENDAR = "IN-CENTRAL-2026";
let serial = 0;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

/**
 * An API oracle response or a response the page itself received
 * (`page.waitForResponse`): both expose the status and the JSON body.
 */
export type JsonResponse = Pick<APIResponse, "status" | "json"> | Pick<Response, "status" | "json">;

export async function json<T = any>(response: JsonResponse, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

/** Clock + serial label unique across retained production runs. */
export function stamp(prefix: string): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  serial += 1;
  return `${prefix} ${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}`
    + `-${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}-${serial}`;
}

/** Records that the positive (state-changing or outcome) branch really ran. */
export async function markPositive(info: TestInfo, name: string, details: Record<string, unknown> = {}) {
  await info.attach(`positive-${name}`, {
    body: JSON.stringify({ positive_executed: true, name, ...details }, null, 2),
    contentType: "application/json",
  });
}

function localDatabase(): { database: string; python: string } {
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  if (database.startsWith("postgresql+psycopg://")) {
    const target = new URL(database);
    if (!loopback(target) || target.search || target.hash || target.pathname.length < 2) {
      throw new Error("Local tester runtime requires a loopback test database.");
    }
  } else if (database.startsWith("sqlite+pysqlite:///")) {
    const filename = database.slice("sqlite+pysqlite:///".length);
    const relative = path.relative(repoRoot, path.resolve(filename));
    if (!path.isAbsolute(filename) || relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error("Local tester SQLite database must belong to this candidate.");
    }
  } else throw new Error("Unsupported local tester database.");
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return { database, python };
}

/**
 * Local equivalent of the production owner-approved test-legal grant: a
 * nonbillable manual subscription carrying every IP entitlement. Restricted to
 * the exact tenant this runtime just bootstrapped on a loopback database.
 */
function grantLocalFullIp(actor: TesterActor, slug: string) {
  if (!slug.startsWith("bugs4-") || actor.company.slug !== slug) {
    throw new Error("Local IP grant requires the exact freshly bootstrapped tenant.");
  }
  const { database, python } = localDatabase();
  const overrides = JSON.stringify(Object.fromEntries(IP_ENTITLEMENT_KEYS.map(key => [key, true])));
  const script = [
    "import json, os",
    "from caseops_api.db.models import Company, CompanyMembership, BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "with get_session_factory()() as session:",
    "    company = session.get(Company, os.environ['BUGS4_COMPANY_ID'])",
    "    assert company and company.slug == os.environ['BUGS4_SLUG'] and company.slug.startswith('bugs4-')",
    "    owner = session.get(CompanyMembership, os.environ['BUGS4_OWNER_ID'])",
    "    assert owner and owner.company_id == company.id and owner.is_active and owner.role == 'owner'",
    "    session.add(BillingSubscription(company_id=company.id, status='manual_active', segment='law_firm',",
    "        source='bugs4_local_fixture', externally_billable=False,",
    "        entitlement_overrides_json=json.loads(os.environ['BUGS4_OVERRIDES'])))",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: {
      ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: database, BUGS4_COMPANY_ID: actor.company.id,
      BUGS4_SLUG: slug, BUGS4_OWNER_ID: actor.membership.id, BUGS4_OVERRIDES: overrides,
      PYTHONPATH: path.join(repoRoot, "apps/api/src"),
    },
  });
  expect(result.status, "Local full-IP fixture grant failed; process output omitted.").toBe(0);
}

/**
 * Local only: one issued SaaS invoice on this runtime's fresh tenant, for the
 * tenant billing page's Invoices table. Only the platform operator issues SaaS
 * invoices (the operator console, behind its own sign-in and MFA), so there is
 * no tenant-facing path to drive; the row mirrors what that path writes.
 * Restricted to the exact tenant this runtime bootstrapped on a loopback database.
 */
export function seedLocalSaasInvoice(rt: TesterRuntime, invoiceNumber: string) {
  if (!rt.local || !rt.credentials.slug.startsWith("bugs4-") || rt.actor.company.slug !== rt.credentials.slug) {
    throw new Error("Local SaaS invoice fixture requires the exact freshly bootstrapped tenant.");
  }
  const { database, python } = localDatabase();
  const script = [
    "import datetime, os",
    "from caseops_api.db.models import BillingManualInvoice, Company",
    "from caseops_api.db.session import get_session_factory",
    "with get_session_factory()() as session:",
    "    company = session.get(Company, os.environ['BUGS4_COMPANY_ID'])",
    "    assert company and company.slug == os.environ['BUGS4_SLUG'] and company.slug.startswith('bugs4-')",
    "    session.add(BillingManualInvoice(company_id=company.id, invoice_number=os.environ['BUGS4_INVOICE'],",
    "        amount_minor=1250000, tax_amount_minor=225000, currency='INR', status='issued',",
    "        issued_on=datetime.date.today(), due_on=datetime.date.today() + datetime.timedelta(days=30),",
    "        metadata_json={'reason': 'bugs4 local layout fixture'}))",
    "    session.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot, encoding: "utf8", timeout: 60_000,
    env: {
      ...process.env, ...e2eEnv, CASEOPS_DATABASE_URL: database, BUGS4_COMPANY_ID: rt.actor.company.id,
      BUGS4_SLUG: rt.credentials.slug, BUGS4_INVOICE: invoiceNumber, PYTHONPATH: path.join(repoRoot, "apps/api/src"),
    },
  });
  expect(result.status, "Local SaaS invoice fixture failed; process output omitted.").toBe(0);
}

async function configureLocalWorkspace(request: APIRequestContext, api: URL, headers: Record<string, string>, actor: TesterActor) {
  const configured = await json(await request.put(`${api.origin}/api/ip/workspace/configuration`, { headers, data: {
    expected_version: null, enabled_asset_types: ["trademark"], jurisdictions: ["IN"], offices: ["IP India"],
    timezone: "Asia/Kolkata", holiday_calendar_key: CENTRAL_HOLIDAY_CALENDAR, working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
    document_taxonomy_version: "ip-taxonomy-2026.1", event_catalog_version: "ip-events-v1", deadline_rule_versions: { IN: "2026.1" },
    notification_channels: ["in_app"], critical_event_policy: { escalation_after_minutes: 30 },
    escalation_owner_membership_id: actor.membership.id, provider_keys: [], provider_terms_version: null, accept_provider_terms: false,
  } }), "Local IP workspace configuration");
  await json(await request.post(`${api.origin}/api/ip/workspace/enable`, { headers,
    data: { expected_config_version: configured.configuration.version, enabled_automations: [] } }), "Local IP workspace enablement");
}

/** Signs in through the real form. Never reuse an API helper's cookie for the browser. */
export async function signIn(page: Page, rt: Pick<TesterRuntime, "web">, credentials: TesterCredentials) {
  await page.setExtraHTTPHeaders(localTransportHeaders(rt.web.origin));
  await page.goto(`${rt.web.origin}/sign-in`);
  await page.locator("#company-slug").fill(credentials.slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

/** Callers must disable traces/screenshots/video: returned credentials never belong in evidence. */
export async function prepareTester(
  page: Page, request: APIRequestContext, baseURL: string | undefined,
  viewport: { width: number; height: number } = { width: 1440, height: 900 },
): Promise<TesterRuntime> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const api = new URL(loopback(web)
    ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}` : required("PROD_API_BASE_URL"));
  if (![web, api].every(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password)
    || loopback(web) !== loopback(api)) throw new Error("Unsafe or mixed tester origins.");
  const local = loopback(web);
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote tester acceptance requires the canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("Tester acceptance requires the exact expected 40-hex release.");
  const release = async () => {
    await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  };
  await release();
  const run = stamp("B4");
  const credentials: TesterCredentials = local
    ? { slug: `bugs4-${randomUUID()}`, email: `ram-${randomUUID()}@example.com`, password: `Synthetic!${randomUUID()}` }
    : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (!local && credentials.slug !== "test-legal") throw new Error("Production batch-4 acceptance is test-legal only.");
  let freshId: string | undefined;
  if (local) {
    const fresh = await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: `Test Legal LLP ${run}`, company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Ram Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    freshId = fresh.company.id;
  }
  const actor = await json<TesterActor>(await request.post(`${api.origin}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password },
  }), "Tester API login");
  if (!uuid.test(actor.company.id) || !uuid.test(actor.membership.id) || !actor.access_token
    || actor.company.slug !== credentials.slug || (local && actor.company.id !== freshId)) {
    throw new Error("Authenticated tenant identity did not match the intended tester.");
  }
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
  if (local) {
    grantLocalFullIp(actor, credentials.slug);
    await configureLocalWorkspace(request, api, headers, actor);
  }
  const readiness = await json(await request.get(`${api.origin}/api/ip/readiness`, { headers }), "Tester IP readiness");
  expect(readiness.workspace_available, "The tester's IP workspace must be available").toBe(true);
  await page.setViewportSize(viewport);
  await signIn(page, { web }, credentials);
  await release();
  return { web, api, local, run, actor, credentials, headers, release };
}

/**
 * Local only: a second same-company actor created through the product's own
 * user-management endpoint (no DB shortcut), for separation-of-duties steps.
 */
export async function addLocalColleague(
  rt: TesterRuntime, request: APIRequestContext, role: "admin" | "partner" | "member", fullName: string,
): Promise<{ credentials: TesterCredentials; membershipId: string }> {
  if (!rt.local) throw new Error("Creating colleagues is local-only; production uses existing test-legal members.");
  const email = `${role}-${randomUUID()}@example.com`;
  const password = `Synthetic!${randomUUID()}`;
  await json(await request.post(`${rt.api.origin}/api/companies/current/users`, { headers: rt.headers,
    data: { full_name: fullName, email, password, role } }), `Create local ${role}`, 200);
  // The login sets the colleague's session cookie on the context it runs in.
  // Run it in a throwaway context so the caller's context stays the tester's.
  const isolated = await playwrightRequest.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
  let login: TesterActor;
  try {
    login = await json<TesterActor>(await isolated.post(`${rt.api.origin}/api/auth/login`, {
      data: { company_slug: rt.credentials.slug, email, password },
    }), `Local ${role} login`);
  } finally {
    await isolated.dispose();
  }
  expect(login.company.id).toBe(rt.actor.company.id);
  return { credentials: { slug: rt.credentials.slug, email, password }, membershipId: login.membership.id };
}

/** Asserts the element is inside the visual viewport right now, with no scroll in between. */
export async function expectOnScreen(locator: Locator, message: string) {
  await expect(locator, message).toBeInViewport({ ratio: 0.5 });
}

export type PopoverOffender = { reason: string; detail: string };

/**
 * Geometry of every open Radix popper / listbox: inside the viewport with a
 * gutter, height bounded by the viewport, scrollable when it overflows, and no
 * option text clipped horizontally.
 */
export async function collectOpenPopoverOffenders(page: Page, gutter = 4): Promise<PopoverOffender[]> {
  return page.evaluate((g) => {
    const offenders: { reason: string; detail: string }[] = [];
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const roots = Array.from(document.querySelectorAll<HTMLElement>("[data-radix-popper-content-wrapper], [role=listbox]"))
      .filter(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0);
    for (const root of roots) {
      const box = root.getBoundingClientRect();
      if (box.left < -g || box.top < -g || box.right > vw + g || box.bottom > vh + g) {
        offenders.push({ reason: "outside-viewport", detail: `${Math.round(box.left)},${Math.round(box.top)} ${Math.round(box.width)}x${Math.round(box.height)} in ${vw}x${vh}` });
      }
      const scroller = root.querySelector<HTMLElement>("[data-radix-select-viewport]") ?? root;
      if (scroller.scrollHeight > scroller.clientHeight + 1) {
        const style = getComputedStyle(scroller);
        if (!/(auto|scroll)/.test(style.overflowY)) offenders.push({ reason: "overflow-not-scrollable", detail: style.overflowY });
      }
      for (const option of Array.from(root.querySelectorAll<HTMLElement>("[role=option]"))) {
        if (option.scrollWidth > option.clientWidth + 2) {
          offenders.push({ reason: "option-text-clipped", detail: (option.textContent ?? "").slice(0, 80) });
        }
      }
    }
    return offenders;
  }, gutter);
}

/** No horizontal page overflow at the current viewport. */
export async function expectNoPageOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1),
    "The page must not overflow the viewport horizontally").toBe(true);
}

/** A control the user can see must never be an enabled select whose only options are placeholders. */
export async function deadSelects(page: Page, scope?: Locator): Promise<string[]> {
  const root = scope ?? page.locator("body");
  return root.evaluate((element) => {
    const out: string[] = [];
    for (const select of Array.from(element.querySelectorAll<HTMLSelectElement>("select"))) {
      const box = select.getBoundingClientRect();
      if (box.width === 0 || box.height === 0 || select.disabled) continue;
      const real = Array.from(select.options).filter(o => o.value !== "" && !o.disabled);
      if (real.length === 0) {
        const label = select.labels?.[0]?.innerText || select.getAttribute("aria-label") || select.id || select.name || "unlabelled";
        out.push(label.trim().split("\n")[0]);
      }
    }
    return out;
  });
}
