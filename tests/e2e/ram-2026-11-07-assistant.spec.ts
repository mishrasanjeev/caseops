import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import type { AssistantCitation, AssistantSessionRecord, AssistantTurnPage } from "../../apps/web/lib/api/workspace-assistant";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { requireFixtureDatabaseUrl } from "./support/fixture-database";
import { runId } from "./support/run-id";

// Local: one fresh synthetic tenant, 52 history turns, no model calls.
// Production: only retained, independently hash-pinned QA evidence; no bootstrap/config writes.
test.use({ trace: "off", screenshot: "off", video: "off" });
type TurnProof = {
  id: string;
  sequence: number;
  content_sha256: string;
  citations: Array<Pick<AssistantCitation, "id" | "source_type" | "source_id" | "source_version" | "source_sha256" | "source_url">>;
};
type Evidence = {
  schema_version: number;
  fixture_kind: string;
  company_id: string;
  membership_id: string;
  matter_id: string;
  history_session_id: string;
  other_session_id: string;
  sessions: Record<string, TurnProof[]>;
};
const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
const sha256 = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for retained assistant acceptance.`);
  return value;
}

function localRuntime() {
  if (Object.keys(process.env).some((key) => key.toUpperCase().startsWith("PG"))) {
    throw new Error("Assistant fixtures refuse ambient libpq overrides.");
  }
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  const ownedSqlite = process.env.CASEOPS_E2E_DOCKER_PROJECT ? ""
    : "sqlite+pysqlite:///" + path.join(repoRoot, "caseops-e2e.db").replaceAll("\\", "/");
  requireFixtureDatabaseUrl(database, ownedSqlite);
  if (database.startsWith("postgresql+psycopg:")) {
    const target = new URL(database);
    if (!process.env.CASEOPS_E2E_DOCKER_PROJECT || target.username !== "caseops" || target.password !== "caseops"
      || target.pathname !== "/caseops" || Number(target.port) < 20000 || Number(target.port) > 49999) {
      throw new Error("Assistant fixtures require the isolated Docker acceptance database.");
    }
  }
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(repoRoot, "apps/api/.venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  if (!path.isAbsolute(python) || !fs.statSync(python).isFile()) throw new Error("Assistant fixture Python is unavailable.");
  return { database, python };
}

function retainedEvidence(): Evidence {
  const file = required("CASEOPS_ASSISTANT_QA_MANIFEST_PATH");
  const expected = required("CASEOPS_ASSISTANT_QA_MANIFEST_SHA256");
  const metadata = fs.lstatSync(file);
  if (!/^[a-f0-9]{64}$/.test(expected) || !metadata.isFile() || metadata.isSymbolicLink()
    || metadata.size < 1 || metadata.size > 131072) throw new Error("Invalid retained assistant evidence file.");
  const bytes = fs.readFileSync(file);
  if (bytes.length < 1 || bytes.length > 131072) throw new Error("Retained assistant evidence exceeded its read bound.");
  expect(sha256(bytes), "retained evidence edition").toBe(expected);
  const evidence = JSON.parse(bytes.toString("utf8")) as Evidence;
  expect(evidence.fixture_kind, "production must not relabel local synthetic history").toBe("retained_qa");
  return evidence;
}

function verifyPage(evidence: Evidence, id: string, page: AssistantTurnPage) {
  const actual = page.items.map((turn): TurnProof => ({
    id: turn.id,
    sequence: turn.sequence,
    content_sha256: sha256(turn.content),
    citations: turn.citations.map((citation) => ({
      id: citation.id, source_type: citation.source_type, source_id: citation.source_id,
      source_version: citation.source_version, source_sha256: citation.source_sha256, source_url: citation.source_url,
    })),
  }));
  expect(actual, "retained content/citation/source versions match their pinned evidence")
    .toEqual(evidence.sessions[id].slice(page.offset, page.offset + page.limit));
  expect(page.has_more).toBe(page.offset + page.items.length < evidence.sessions[id].length);
}

async function signIn(page: Page, baseURL: string | undefined) {
  if (!baseURL) throw new Error("The Playwright project must configure its browser baseURL.");
  const web = new URL(baseURL);
  const local = loopback(web);
  const apiUrl = new URL(process.env.CASEOPS_ASSISTANT_QA_API_URL?.trim()
    || (local ? apiBaseUrl : required("PROD_API_BASE_URL")));
  if (![web, apiUrl].every((url) => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password
    && url.pathname === "/" && !url.search && !url.hash) || loopback(apiUrl) !== local
    || (local && (web.protocol !== "http:" || apiUrl.protocol !== "http:"))
    || (!local && (web.origin !== "https://caseops.ai" || apiUrl.origin !== "https://api.caseops.ai"))) {
    throw new Error("Assistant fixture/retained acceptance refuses unsafe or mixed origins.");
  }
  // Validate the database and executable before the very first local API write.
  const runtime = local ? localRuntime() : null;
  const api = apiUrl.origin;
  const sha = local ? (process.env.CASEOPS_EXPECTED_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  expect(sha).toMatch(/^[0-9a-f]{40}$/);
  await page.context().setExtraHTTPHeaders(noPaidProviderHeaders);
  const apiBuild = await page.request.get(`${api}/api/build`, { headers: noPaidProviderHeaders });
  const webBuild = await page.request.get(new URL("/api/release-identity", baseURL).href, { headers: noPaidProviderHeaders });
  expect(apiBuild.status(), "exact API release").toBe(200);
  expect(webBuild.status(), "exact web release").toBe(200);
  expect((await apiBuild.json()).release_sha).toBe(sha);
  expect((await webBuild.json()).release_sha).toBe(sha);
  const run = runId();
  const credentials = local
    ? { company_slug: `assistant-history-${run}`, email: `assistant-${run}@example.com`, password: `Assistant!${randomUUID()}` }
    : { company_slug: required("CASEOPS_IP_QA_SLUG"), email: required("CASEOPS_IP_QA_EMAIL"), password: required("CASEOPS_IP_QA_PASSWORD") };
  let companyId: string | undefined;
  if (local) {
    const bootstrap = await page.request.post(`${api}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders,
      data: { company_name: `Synthetic assistant history ${run}`, company_slug: credentials.company_slug,
        company_type: "law_firm", owner_full_name: "Local assistant fixture owner",
        owner_email: credentials.email, owner_password: credentials.password },
    });
    expect(bootstrap.status(), "fresh loopback-only assistant tenant").toBe(200);
    const fresh = await bootstrap.json();
    expect(fresh.company.slug).toBe(credentials.company_slug);
    companyId = fresh.company.id;
  }
  const login = await page.request.post(`${api}/api/auth/login`, {
    headers: noPaidProviderHeaders,
    data: credentials,
  });
  expect(login.status(), local ? "fresh local assistant owner sign-in" : "dedicated existing QA sign-in").toBe(200);
  const identity = await login.json();
  expect(identity.company.slug).toBe(credentials.company_slug);
  if (local) expect(identity.company.id).toBe(companyId);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };
  let evidence: Evidence;
  if (runtime) {
    const policy = await page.request.get(`${api}/api/admin/tenant-ai-policy`, { headers });
    expect(policy.status()).toBe(200);
    const enabled = await page.request.patch(`${api}/api/admin/tenant-ai-policy`, { headers,
      data: { expected_version: (await policy.json()).policy_version, workspace_assistant_enabled: true,
        allowed_models_assistant: ["caseops-mock-1"], assistant_retention_days: 30 } });
    expect(enabled.status(), "only the new synthetic tenant's assistant policy").toBe(200);
    const createdMatter = await page.request.post(`${api}/api/matters/`, { headers,
      data: { matter_code: `AIH-${run}`, title: `Synthetic assistant Matter ${run}`,
        description: "Synthetic local factual history fixture. No legal authority or model output.",
        practice_area: "Civil", forum_level: "high_court" } });
    expect(createdMatter.status()).toBe(200);
    const matter = await createdMatter.json();
    const ids: string[] = [];
    for (const name of ["history", "other"]) {
      const created = await page.request.post(`${api}/api/workspace-assistant/sessions`, { headers,
        data: { title: `Synthetic ${name} ${run}`, scopes: [{ scope_type: "matter", scope_id: matter.id }] } });
      expect(created.status()).toBe(201);
      ids.push((await created.json()).id);
    }
    const env: NodeJS.ProcessEnv = { ...e2eEnv, CASEOPS_ENV: "e2e", CASEOPS_DATABASE_URL: runtime.database,
      CASEOPS_LLM_PROVIDER: "mock", CASEOPS_EMBEDDING_PROVIDER: "mock",
      CASEOPS_E2E_DOCKER_PROJECT: process.env.CASEOPS_E2E_DOCKER_PROJECT || "" };
    for (const key of ["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"]) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    const seeded = spawnSync(runtime.python, ["-I", "-B", "-u", path.join(repoRoot, "tests/e2e/support/assistant_history_fixture.py")], {
      cwd: repoRoot, env, encoding: "utf8", timeout: 60000, maxBuffer: 131072, windowsHide: true,
      input: JSON.stringify({ web: web.origin, api, run_id: run, company_id: identity.company.id,
        membership_id: identity.membership.id, user_id: identity.user.id, matter_id: matter.id,
        history_session_id: ids[0], other_session_id: ids[1] }),
    });
    expect(seeded.error, "local assistant fixture process failed; no retry").toBeUndefined();
    const safeStage = seeded.stderr.trim().split(/\r?\n/).reverse().find((line) =>
      /^Local assistant fixture failed at (validate|scope|persist|verify|commit) \([A-Za-z]+\); no retry\.$/.test(line),
    ) || "Private process output omitted; no recognized fixture stage.";
    expect(seeded.status, safeStage).toBe(0);
    evidence = JSON.parse(seeded.stdout) as Evidence;
    expect(evidence.fixture_kind).toBe("synthetic_local_factual_history_no_model");
  } else {
    evidence = retainedEvidence();
    expect(evidence.history_session_id).toBe(required("CASEOPS_ASSISTANT_QA_HISTORY_SESSION_ID"));
    expect(evidence.other_session_id).toBe(required("CASEOPS_ASSISTANT_QA_OTHER_SESSION_ID"));
  }
  expect(evidence.schema_version).toBe(1);
  expect(evidence.company_id).toBe(identity.company.id);
  expect(evidence.membership_id).toBe(identity.membership.id);
  const historyId = evidence.history_session_id;
  const otherId = evidence.other_session_id;
  expect(historyId).not.toBe(otherId);
  for (const id of [historyId, otherId]) {
    const proof = evidence.sessions[id];
    expect(Array.isArray(proof)).toBe(true);
    expect(proof.length).toBeGreaterThanOrEqual(id === historyId ? 52 : 1);
    expect(proof.length).toBeLessThanOrEqual(200);
    expect(new Set(proof.map((turn) => turn.id)).size).toBe(proof.length);
    expect(proof.map((turn) => turn.sequence)).toEqual(Array.from({ length: proof.length }, (_, index) => index + 1));
    for (const turn of proof) {
      expect(turn.content_sha256).toMatch(/^[a-f0-9]{64}$/);
      for (const citation of turn.citations) {
        expect(citation.source_sha256).toMatch(/^[a-f0-9]{64}$/);
        expect(citation.source_version).toBeTruthy();
      }
    }
  }
  const session = async (id: string): Promise<AssistantSessionRecord> => {
    const response = await page.request.get(`${api}/api/workspace-assistant/sessions/${id}`, { headers });
    expect(response.status(), `retained session ${id}`).toBe(200);
    return response.json();
  };
  const turns = async (id: string, offset = 0): Promise<AssistantTurnPage> => {
    const response = await page.request.get(`${api}/api/workspace-assistant/sessions/${id}/turns?limit=50&offset=${offset}`, { headers });
    expect(response.status(), `retained turns ${id} at ${offset}`).toBe(200);
    const result = await response.json() as AssistantTurnPage;
    verifyPage(evidence, id, result);
    return result;
  };
  const history = await session(historyId);
  const other = await session(otherId);
  const first = await turns(historyId);
  expect(first.items).toHaveLength(50);
  expect(first.offset).toBe(0);
  expect(first.has_more).toBe(true);
  await page.goto("/");
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: identity.company,
    user: identity.user,
    membership: identity.membership,
    capabilities: identity.capabilities,
  });
  await page.goto("/app/assistant");
  await expect(page.getByRole("heading", { name: "Ask this Workspace" })).toBeVisible();
  // Both fixtures must be discoverable in the actual recent-conversation UI.
  await expect(page.getByRole("button", { name: history.title, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: other.title, exact: true })).toBeVisible();
  const release = async () => {
    for (const url of [`${api}/api/build`, new URL("/api/release-identity", baseURL).href]) {
      const response = await page.request.get(url, { headers: noPaidProviderHeaders });
      expect(response.status(), "release identity after the journey").toBe(200);
      expect((await response.json()).release_sha).toBe(sha);
    }
  };
  return { api, headers, history, other, first, turns, release };
}

async function visibleTurnIds(page: Page) {
  return page.getByTestId("assistant-turns").locator("[data-turn-id]").evaluateAll(
    (rows) => rows.map((row) => row.getAttribute("data-turn-id")),
  );
}

test("retained assistant history continues beyond 50 and opens only its reauthorized destination", async ({ page, baseURL }) => {
  const fixture = await signIn(page, baseURL);
  await page.getByRole("button", { name: fixture.history.title, exact: true }).click();
  await expect.poll(() => visibleTurnIds(page)).toEqual(fixture.first.items.map((turn) => turn.id));
  const expected = [...fixture.first.items];
  let cursor = fixture.first;
  for (let index = 0; cursor.has_more && index < 3; index += 1) {
    const offset = cursor.offset + cursor.items.length;
    cursor = await fixture.turns(fixture.history.id, offset);
    expect(cursor.offset).toBe(offset);
    expect(cursor.limit).toBe(50);
    expect(cursor.items.length).toBeGreaterThan(0);
    expect(cursor.items.length).toBeLessThanOrEqual(50);
    const response = page.waitForResponse((value) => {
      const url = new URL(value.url());
      return url.pathname.endsWith(`/sessions/${fixture.history.id}/turns`)
        && url.searchParams.get("offset") === String(offset);
    });
    await page.getByRole("button", { name: "Load more messages", exact: true }).click();
    expect((await response).status()).toBe(200);
    expected.push(...cursor.items);
    await expect.poll(() => visibleTurnIds(page)).toEqual(expected.map((turn) => turn.id));
  }
  expect(cursor.has_more, "retained session stays within its 200-turn bound").toBe(false);
  expect(expected.length).toBeGreaterThanOrEqual(52);
  expect(new Set(expected.map((turn) => turn.id)).size).toBe(expected.length);
  await expect(page.getByRole("button", { name: "Load more messages", exact: true })).toHaveCount(0);
  const citedTurn = expected.find((turn) => turn.render_status === "visible" && turn.citations.length > 0);
  expect(citedTurn, "retained fixture requires an authorized factual answer with a citation").toBeTruthy();
  const citation = citedTurn!.citations[0];
  const opened = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname.endsWith(`/sessions/${fixture.history.id}/citations/${citation.id}/open`));
  await page.locator(`[data-turn-id="${citedTurn!.id}"]`).getByRole("button", { name: `Open source: ${citation.label}`, exact: true }).click();
  const openResponse = await opened;
  expect(openResponse.status(), "real audited citation opening").toBe(200);
  expect(openResponse.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
  const target = await openResponse.json();
  expect(target.citation_id).toBe(citation.id);
  expect(target.source_url).toBeTruthy();
  await expect(page).toHaveURL(new URL(target.source_url, baseURL).href);

  await page.goto("/app/assistant");
  await page.getByRole("button", { name: fixture.history.title, exact: true }).click();
  await expect.poll(() => visibleTurnIds(page)).toEqual(fixture.first.items.map((turn) => turn.id));
  await expect(page.getByRole("button", { name: "Load more messages", exact: true })).toBeVisible();
  await fixture.release();
});

test("a delayed real history page cannot contaminate another retained session", async ({ page, baseURL }) => {
  const fixture = await signIn(page, baseURL);
  const otherPage = await fixture.turns(fixture.other.id);
  expect(otherPage.items.length).toBeGreaterThan(0);
  expect(otherPage.items.some((turn) => fixture.first.items.some((old) => old.id === turn.id))).toBe(false);
  let release!: () => void;
  let captured!: () => void;
  let captureFailed!: (reason: unknown) => void;
  let delivered!: () => void;
  const hold = new Promise<void>((resolve) => { release = resolve; });
  const ready = new Promise<void>((resolve, reject) => { captured = resolve; captureFailed = reject; });
  const complete = new Promise<void>((resolve) => { delivered = resolve; });
  // Hold the real request; no UI response or provider result is fabricated.
  await page.route(`**/api/workspace-assistant/sessions/${fixture.history.id}/turns?*`, async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("offset") !== "50") return route.continue();
    try {
      captured();
      await hold;
      await route.continue();
    } catch (error) {
      captureFailed(error);
      throw error;
    } finally {
      delivered();
    }
  });
  try {
    await page.getByRole("button", { name: fixture.history.title, exact: true }).click();
    await expect.poll(() => visibleTurnIds(page)).toEqual(fixture.first.items.map((turn) => turn.id));
    await page.getByRole("button", { name: "Load more messages", exact: true }).click();
    await ready;
    await page.getByRole("button", { name: fixture.other.title, exact: true }).click();
    await expect.poll(() => visibleTurnIds(page)).toEqual(otherPage.items.map((turn) => turn.id));
    const resumed = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname.endsWith(`/sessions/${fixture.history.id}/turns`)
        && url.searchParams.get("offset") === "50";
    });
    release();
    await complete;
    await (await resumed).finished();
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }));
    await expect.poll(() => visibleTurnIds(page)).toEqual(otherPage.items.map((turn) => turn.id));
    // Next's empty route announcer lives outside the workspace main content.
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    await fixture.release();
  } finally {
    release();
  }
});
