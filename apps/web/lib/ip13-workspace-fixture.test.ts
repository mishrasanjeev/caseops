// Execute the dated spec's actual setup functions without loading Playwright or launching its Python/API.
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

const root = path.resolve(__dirname, "../../..");
const source = readFileSync(path.join(root, "tests/e2e/ram-2026-10-13-ip-portfolio.spec.ts"), "utf8");
const tenantId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const slug = `ip13-${runId}`;
const actor = { company: { id: tenantId, slug }, membership: { id: "owner-membership" }, access_token: "offline-token" };
type FixtureActor = typeof actor;
const marker = { "X-CaseOps-Automated-Test": "no-paid-providers" };
const database = `sqlite+pysqlite:///${path.join(root, "caseops-e2e.db").replaceAll("\\", "/")}`;

function fixture(overrides: Record<string, string> = {}, ready = true, loginCompanyId = tenantId,
  configurationTimezone: unknown = "Asia/Kolkata") {
  const functions = new Set(["required", "grantLocalPortfolioEntitlement", "preparePortfolioWorkspace", "preparePortfolio"]);
  const ast = ts.createSourceFile("dated-fixture.ts", source, ts.ScriptTarget.Latest, true);
  const body = ast.statements.filter(statement =>
    ts.isFunctionDeclaration(statement) && statement.name && functions.has(statement.name.text)
    || ts.isVariableStatement(statement) && statement.declarationList.declarations.some(declaration =>
      ts.isIdentifier(declaration.name) && declaration.name.text === "loopback"),
  ).map(statement => statement.getText(ast)).join("\n");
  const spawnSync = vi.fn(() => ({ status: 0, stderr: "" }));
  const env = { CASEOPS_RELEASE_SHA: "c".repeat(40), CASEOPS_EXPECTED_RELEASE_SHA: "c".repeat(40),
    CASEOPS_RAM_PROD_EMAIL: "offline@example.com", CASEOPS_RAM_PROD_PASSWORD: "offline-password", ...overrides };
  const context = vm.createContext({ URL, path, expect, spawnSync, repoRoot: root,
    process: { env, platform: process.platform }, e2eEnv: { CASEOPS_DATABASE_URL: database, CASEOPS_ENV: "e2e" },
    randomUUID: () => runId, noPaidProviderHeaders: marker });
  vm.runInContext(ts.transpileModule(body, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS } }).outputText, context);
  const helper = context as unknown as {
    grantLocalPortfolioEntitlement: (web: URL, api: URL, actor: FixtureActor, slug: string) => void;
    preparePortfolio: (...args: unknown[]) => Promise<unknown>;
  };
  const events: string[] = [];
  const response = (data: unknown) => ({ status: () => 200, json: async () => data, text: async () => "offline response" });
  const request = {
    get: vi.fn(async (url: string) => {
      events.push(new URL(url).pathname);
      return url.endsWith("/readiness") ? response({ workspace_available: ready, manual_docketing_available: ready,
        features: ["workspace_core", "manual_docketing"].map(feature_id => ({ feature_id,
          available: ready, entitled: ready, rollout_enabled: true, reason: ready ? "available" : "missing_entitlement" })),
        configuration_status: { configuration: { workspace_enabled: ready, enabled_automations_json: [],
          timezone: configurationTimezone },
          enablement_blockers: ready ? [] : ["workspace_configuration_missing"] } }) : response({ release_sha: "c".repeat(40) });
    }),
    put: vi.fn(async (url: string, options: { headers: Record<string, string>; data: Record<string, unknown> }) => {
      expect(options.headers).toMatchObject(marker);
      events.push(new URL(url).pathname); return response({ configuration: { version: 7 } });
    }),
    post: vi.fn(async (url: string, options: { data: { company_slug?: string } }) => {
      events.push(new URL(url).pathname);
      if (url.endsWith("/bootstrap/company")) return response(actor);
      if (url.endsWith("/auth/login")) return response({ ...actor, company: { id: loginCompanyId,
        slug: options.data.company_slug } });
      return response({ configuration: { workspace_enabled: true } });
    }),
  };
  const locator = () => ({ fill: vi.fn(async () => {}), click: vi.fn(async () => {}) });
  const page = { setViewportSize: vi.fn(async () => {}), goto: vi.fn(async () => {}),
    locator, getByRole: locator, waitForURL: vi.fn(async () => {}) };
  return { helper, spawnSync, request, page, events,
    run: (base = "http://127.0.0.1:3100") => helper.preparePortfolio(page, request, base, 1280) };
}

describe("IP13 fresh workspace fixture boundaries", () => {
  it("grants only the fresh fixture, configures/enables manual workspace and reads actual readiness", async () => {
    const python = path.join(root, "apps/api/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const f = fixture({ CASEOPS_E2E_PYTHON: python });
    const result = await f.run() as { timezone: string };
    expect(result.timezone).toBe("Asia/Kolkata");
    expect(f.spawnSync).toHaveBeenCalledTimes(1);
    const [executable, args, options] = f.spawnSync.mock.calls[0] as unknown as [string, string[], { env: Record<string, string> }];
    expect(executable).toBe(python);
    expect(args[0]).toBe("-c");
    expect(args[1]).toContain("company.slug==os.environ['CASEOPS_E2E_COMPANY_SLUG']");
    expect(args[1]).toContain("owner.company_id==company.id");
    expect(args[1]).toContain("owner.role=='owner'");
    expect(args[1]).not.toContain("owner.role.value");
    expect(args[1]).toContain("status='manual_active'");
    expect(args[1]).toContain("externally_billable=False");
    expect(args[1]).toContain("entitlement_overrides_json={'ip_workspace': True}");
    expect(options.env).toMatchObject({ CASEOPS_E2E_COMPANY_ID: tenantId, CASEOPS_E2E_COMPANY_SLUG: slug,
      CASEOPS_DATABASE_URL: database });
    expect(f.events.slice(-3)).toEqual(["/api/ip/workspace/configuration", "/api/ip/workspace/enable", "/api/ip/readiness"]);
    expect(f.request.put.mock.calls[0][1]).toMatchObject({ headers: marker, data: {
      jurisdictions: ["IN"], offices: ["IP India"], timezone: "Asia/Kolkata", provider_keys: [],
      accept_provider_terms: false, provider_terms_version: null, escalation_owner_membership_id: actor.membership.id } });
    expect(f.request.post.mock.calls.at(-1)?.[1]).toMatchObject({ headers: marker,
      data: { expected_config_version: 7, enabled_automations: [] } });
  });

  it.each([
    "postgresql+psycopg://test:test@remote.invalid/caseops",
    "postgresql+psycopg://test:test@127.0.0.1/caseops?host=remote.invalid",
    "sqlite+pysqlite:////server/share/private.db",
    `sqlite+pysqlite:///${path.resolve(root, "../outside.db").replaceAll("\\", "/")}`,
    "sqlite+pysqlite:///:memory:",
  ])("rejects unsafe database %s before any grant or configuration", async databaseUrl => {
    const f = fixture({ CASEOPS_E2E_DATABASE_URL: databaseUrl });
    await expect(f.run()).rejects.toThrow(/database/i);
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
  });

  it("rejects foreign candidate Python before the grant", async () => {
    const f = fixture({ CASEOPS_E2E_PYTHON: path.resolve(root, "../unowned/python.exe") });
    await expect(f.run()).rejects.toThrow("Python must belong to this candidate");
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it("rejects a login for a different company before the grant", async () => {
    const f = fixture({}, true, "33333333-3333-4333-8333-333333333333");
    await expect(f.run()).rejects.toThrow();
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it("rejects a direct remote-origin or wrong-slug grant even if the caller mislabels it local", () => {
    const f = fixture();
    expect(() => f.helper.grantLocalPortfolioEntitlement(new URL("https://caseops.ai"),
      new URL("https://api.caseops.ai"), actor, slug)).toThrow("loopback origins");
    expect(() => f.helper.grantLocalPortfolioEntitlement(new URL("http://127.0.0.1"),
      new URL("http://127.0.0.1"), actor, "test-legal")).toThrow("newly bootstrapped");
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it("uses read-only readiness on canonical production and never grants/configures/enables", async () => {
    const f = fixture({ PROD_API_BASE_URL: "https://api.caseops.ai" }, true, tenantId, "Europe/London");
    const result = await f.run("https://caseops.ai") as { timezone: string };
    expect(result.timezone).toBe("Europe/London");
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
    expect(f.request.post.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(["/api/auth/login"]);
    expect(f.events.at(-1)).toBe("/api/ip/readiness");
  });

  it.each([null, 17])("rejects malformed production timezone %s without workspace mutation", async timezone => {
    const f = fixture({ PROD_API_BASE_URL: "https://api.caseops.ai" }, true, tenantId, timezone);
    await expect(f.run("https://caseops.ai")).rejects.toThrow();
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
    expect(f.request.post.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(["/api/auth/login"]);
  });

  it("fails remote readiness with its real entitlement/configuration reasons, without mutation", async () => {
    const f = fixture({ PROD_API_BASE_URL: "https://api.caseops.ai" }, false);
    await expect(f.run("https://caseops.ai")).rejects.toThrow(/missing_entitlement.*workspace_configuration_missing/);
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
    expect(f.request.post).toHaveBeenCalledTimes(1);
  });

  it("keeps all four journeys independent, with zero retries and exact imported-docket navigation", () => {
    expect(source).toContain('test.describe.configure({ retries: 0, mode: "default" })');
    expect(source).toContain('await sourceRow.getByRole("link", { name: mark, exact: true }).click()');
    expect(source).toContain('toHaveURL(`${web.origin}/app/ip?docket=${saved.rows[0].created_docket_id}`)');
    expect(source).not.toContain('getByRole("link", { name: mark, exact: true }).first().click()');
    expect(source.match(/await preparePortfolio\(page, request, baseURL, width\)/g)).toHaveLength(2);
  });
});
