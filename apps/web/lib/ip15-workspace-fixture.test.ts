import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

const root = path.resolve(__dirname, "../../..");
const source = readFileSync(path.join(root, "tests/e2e/support/ip15-workspace.ts"), "utf8");
const companyId = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";
const ownerId = "33333333-3333-4333-8333-333333333333";
const marker = { "X-CaseOps-Automated-Test": "no-paid-providers" };
const sha = "c".repeat(40);
const actor = { company: { id: companyId, slug: `ip15-${run}` }, membership: { id: ownerId }, access_token: "offline-only-token" };

function fixture(overrides: Record<string, string> = {}, ready = true, returnedSha = sha, loginId = companyId) {
  const ast = ts.createSourceFile("ip15-workspace.ts", source, ts.ScriptTarget.Latest, true);
  const body = ast.statements.filter(statement => ts.isFunctionDeclaration(statement)
    || ts.isVariableStatement(statement) && statement.declarationList.declarations.some(declaration =>
      ts.isIdentifier(declaration.name) && ["loopback", "uuid"].includes(declaration.name.text)),
  ).map(statement => statement.getText(ast)).join("\n");
  const spawnSync = vi.fn(() => ({ status: 0 }));
  const context = vm.createContext({ URL, path, expect, spawnSync, repoRoot: root, exports: {},
    process: { platform: process.platform, env: { CASEOPS_EXPECTED_RELEASE_SHA: sha,
      CASEOPS_RAM_PROD_EMAIL: "offline@example.com", CASEOPS_RAM_PROD_PASSWORD: "offline-password", ...overrides } },
    e2eEnv: { CASEOPS_RELEASE_SHA: sha, CASEOPS_ENV: "e2e",
      CASEOPS_DATABASE_URL: `sqlite+pysqlite:///${path.join(root, "caseops-e2e.db").replaceAll("\\", "/")}` },
    randomUUID: () => run, noPaidProviderHeaders: marker });
  vm.runInContext(ts.transpileModule(body, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS } }).outputText, context);
  const helper = context as unknown as {
    prepareIp15Workspace: (...args: unknown[]) => Promise<Record<string, unknown>>;
    createIp15ManualTrademark: (...args: unknown[]) => Promise<unknown>;
  };
  const events: string[] = [];
  const response = (data: unknown, status = 200) => ({ status: () => status, json: async () => data });
  const request = {
    get: vi.fn(async (url: string, options: { headers: Record<string, string> }) => {
      expect(options.headers).toMatchObject(marker);
      events.push(new URL(url).pathname);
      return response(url.endsWith("/readiness") ? { workspace_available: ready, manual_docketing_available: ready,
        configuration_status: { configuration: { workspace_enabled: ready, enabled_automations_json: [], timezone: "Asia/Kolkata" } } }
        : { release_sha: returnedSha });
    }),
    post: vi.fn(async (url: string, options: { headers: Record<string, string>; data: { company_slug?: string } }) => {
      expect(options.headers).toMatchObject(marker);
      events.push(new URL(url).pathname);
      if (url.endsWith("/bootstrap/company")) return response(actor);
      if (url.endsWith("/auth/login")) return response({ ...actor, company: { id: loginId, slug: options.data.company_slug } });
      if (url.endsWith("/trademark-applications/manual")) return response({ docket: { id: ownerId, company_id: companyId }, application: { id: run } }, 201);
      return response({});
    }),
    put: vi.fn(async (_url: string, options: { headers: Record<string, string> }) => {
      expect(options.headers).toMatchObject(marker);
      return response({ configuration: { version: 7 } });
    }),
  };
  const control = () => ({ fill: vi.fn(async () => {}), click: vi.fn(async () => {}) });
  const page = { setViewportSize: vi.fn(async () => {}), setExtraHTTPHeaders: vi.fn(async () => {}), goto: vi.fn(async () => {}),
    locator: control, getByRole: control, waitForURL: vi.fn(async () => {}) };
  return { helper, request, page, spawnSync, events,
    run: (base = "http://127.0.0.1:3100") => helper.prepareIp15Workspace(page, request, base, 393) };
}

describe("IP15 shared workspace fixture boundaries", () => {
  it("prepares only a fresh local tenant, manual workspace and two exact-release identity pairs", async () => {
    const f = fixture();
    const result = await f.run();
    expect(f.spawnSync).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({ actor, local: true, run, timezone: "Asia/Kolkata" });
    expect(typeof result.release).toBe("function");
    expect(f.page.setExtraHTTPHeaders).toHaveBeenCalledWith(marker);
    expect(f.events.slice(0, 2)).toEqual(["/api/build", "/api/release-identity"]);
    expect(f.events.slice(-2)).toEqual(["/api/build", "/api/release-identity"]);
    expect(f.request.put).toHaveBeenCalledWith(expect.stringMatching(/configuration$/), expect.objectContaining({ data: expect.objectContaining({
      provider_keys: [], accept_provider_terms: false, provider_terms_version: null, timezone: "Asia/Kolkata",
    }) }));
    const args = f.spawnSync.mock.calls[0] as unknown as [string, string[], { env: Record<string, string> }];
    expect(args[1][1]).toContain("owner.role=='owner'");
    expect(args[1][1]).toContain("company.slug==os.environ['IP15_SLUG']");
    expect(args[1][1]).toContain("externally_billable=False");
    expect(args[1][1]).not.toContain("owner.role.value");
  });

  it("uses persistent production test-legal without bootstrap, grant, configuration or enablement", async () => {
    const f = fixture({ PROD_API_BASE_URL: "https://api.caseops.ai" });
    const result = await f.run("https://caseops.ai");
    expect(result).toMatchObject({ local: false, actor: { company: { slug: "test-legal" } } });
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
    expect(f.request.post.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(["/api/auth/login"]);
  });

  it.each([
    ["https://evil.invalid", "https://api.caseops.ai"],
    ["https://caseops.ai", "http://127.0.0.1:8000"],
    ["https://user:password@caseops.ai", "https://api.caseops.ai"],
  ])("rejects unsafe or mixed origins %s before any request", async (web, api) => {
    const f = fixture({ PROD_API_BASE_URL: api });
    await expect(f.run(web)).rejects.toThrow(/origin/i);
    expect(f.request.get).not.toHaveBeenCalled();
    expect(f.request.post).not.toHaveBeenCalled();
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it.each(["main", "c".repeat(39), "C".repeat(40)])("rejects malformed expected release %s", async release => {
    const f = fixture({ CASEOPS_RELEASE_SHA: release });
    await expect(f.run()).rejects.toThrow(/40-hex/);
    expect(f.request.get).not.toHaveBeenCalled();
  });

  it("rejects mismatched serving identity before authentication or grant", async () => {
    const f = fixture({}, true, "d".repeat(40));
    await expect(f.run()).rejects.toThrow();
    expect(f.request.post).not.toHaveBeenCalled();
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it.each([
    "postgresql+psycopg://test:test@remote.invalid/caseops",
    "postgresql+psycopg://test:test@127.0.0.1/caseops?host=remote.invalid",
    "sqlite+pysqlite:///:memory:",
    `sqlite+pysqlite:///${path.resolve(root, "../unowned.db").replaceAll("\\", "/")}`,
  ])("rejects unowned database %s before direct grant/configuration", async database => {
    const f = fixture({ CASEOPS_E2E_DATABASE_URL: database });
    await expect(f.run()).rejects.toThrow(/database|SQLite|PostgreSQL/);
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
    expect(f.request.post).not.toHaveBeenCalled();
  });

  it("rejects a foreign login identity before direct local grant", async () => {
    const f = fixture({}, true, sha, run);
    await expect(f.run()).rejects.toThrow(/tenant identity/);
    expect(f.spawnSync).not.toHaveBeenCalled();
  });

  it("fails unavailable production readiness without trying a grant or reconfiguration", async () => {
    const f = fixture({ PROD_API_BASE_URL: "https://api.caseops.ai" }, false);
    await expect(f.run("https://caseops.ai")).rejects.toThrow();
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.request.put).not.toHaveBeenCalled();
  });

  it("creates a uniquely named manual word application between exact-release checks", async () => {
    const f = fixture();
    const workspace = await f.run();
    await f.helper.createIp15ManualTrademark(workspace, f.request, "Synthetic source dates");
    const call = f.request.post.mock.calls.find(([url]) => url.endsWith("/trademark-applications/manual"));
    expect(call?.[1]).toMatchObject({ headers: marker, data: {
      title: `Synthetic source dates ${run}`, jurisdiction: "IN", office: "IP India", filing_phase: "pre_filing",
      particulars: { mark_kind: "word", representation: { evidence_reference: `fixture:ip15-mark:${run}` } },
    } });
    expect(f.events.slice(-5)).toEqual(["/api/build", "/api/release-identity", "/api/ip/trademark-applications/manual", "/api/build", "/api/release-identity"]);
  });
});
