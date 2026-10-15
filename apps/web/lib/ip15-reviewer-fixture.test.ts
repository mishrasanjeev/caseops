import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

const root = path.resolve(__dirname, "../../..");
const source = readFileSync(path.join(root, "tests/e2e/ram-2026-10-15-ip-controls.spec.ts"), "utf8");
const companyId = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";
const ownerId = "33333333-3333-4333-8333-333333333333";
const legalId = "44444444-4444-4444-8444-444444444444";
const reviewerId = "55555555-5555-4555-8555-555555555555";
const otherId = "66666666-6666-4666-8666-666666666666";
const marker = { "X-CaseOps-Automated-Test": "no-paid-providers" };
const legalToken = "synthetic-memory-only-legal-token";

type Identity = {
  company: { id: string; slug: string; is_active: boolean };
  membership: { id: string; role: string; is_active: boolean };
  capabilities: string[];
};
type Session = Identity & { access_token: unknown; token_type: string };
type Options = {
  local?: boolean;
  login?: (actor: Session) => unknown;
  current?: (actor: Identity) => unknown;
  loginStatus?: number;
  currentStatus?: number;
  loginFailure?: Error;
  currentFailure?: Error;
  releaseFailure?: Error;
  authenticationDisposeFailure?: Error;
  legalCreationFailure?: Error;
  duplicateMemberIds?: boolean;
};

function fixture(options: Options = {}) {
  const ast = ts.createSourceFile("ip-controls.spec.ts", source, ts.ScriptTarget.Latest, true);
  const declarations = ast.statements.filter(statement => ts.isFunctionDeclaration(statement)
    && ["json", "prepare"].includes(statement.name?.text ?? ""));
  expect(declarations).toHaveLength(2);
  const body = declarations.map(statement => statement.getText(ast)).join("\n");
  const identity: Identity = { company: { id: companyId, slug: `ip15-${run}`, is_active: true },
    membership: { id: legalId, role: "admin", is_active: true }, capabilities: ["ip:read", "ip:rules_activate"] };
  const login: Session = { ...identity, access_token: legalToken, token_type: "bearer" };
  const events: string[] = [];
  const response = (data: unknown, status = 200) => ({ status: () => status, json: async () => data });
  const authentication = {
    post: vi.fn(async (url: string) => {
      expect(new URL(url).pathname).toBe("/api/auth/login");
      events.push("login");
      if (options.loginFailure) throw options.loginFailure;
      return response(options.login ? options.login(structuredClone(login)) : login, options.loginStatus);
    }),
    dispose: vi.fn(async () => {
      events.push("authentication-dispose");
      if (options.authenticationDisposeFailure) throw options.authenticationDisposeFailure;
    }),
  };
  let legalHeaders: Record<string, string> = {};
  const activationRequests: Array<{ path: string; correctBearer: boolean; noPaid: boolean }> = [];
  const legal = {
    get: vi.fn(async (url: string) => {
      expect(new URL(url).pathname).toBe("/api/auth/me");
      events.push("current-identity");
      if (options.currentFailure) throw options.currentFailure;
      return response(options.current ? options.current(structuredClone(identity)) : identity, options.currentStatus);
    }),
    post: vi.fn(async (url: string) => {
      activationRequests.push({ path: new URL(url).pathname,
        correctBearer: legalHeaders.Authorization === `Bearer ${legalToken}`,
        noPaid: legalHeaders["X-CaseOps-Automated-Test"] === "no-paid-providers" });
      return response({ status: "active" });
    }),
    dispose: vi.fn(async () => { events.push("legal-dispose"); }),
  };
  let contextsCreated = 0;
  const newContext = vi.fn(async (settings: { extraHTTPHeaders: Record<string, string> }) => {
    contextsCreated += 1;
    if (contextsCreated === 1) return authentication;
    if (options.legalCreationFailure) throw options.legalCreationFailure;
    legalHeaders = settings.extraHTTPHeaders;
    return legal;
  });
  const release = vi.fn(async () => {
    events.push("release");
    if (options.releaseFailure) throw options.releaseFailure;
  });
  const workspace = {
    web: new URL(options.local === false ? "https://caseops.ai" : "http://127.0.0.1:3100"),
    api: new URL(options.local === false ? "https://api.caseops.ai" : "http://127.0.0.1:8000"),
    local: options.local !== false, run, timezone: "Asia/Kolkata", release,
    actor: { company: { id: companyId, slug: `ip15-${run}` }, membership: { id: ownerId } },
    headers: { ...marker, Authorization: "Bearer synthetic-owner-token" },
  };
  let memberCount = 0;
  const request = { post: vi.fn(async (url: string) => {
    const route = new URL(url).pathname;
    if (route.endsWith("/proceedings")) return response({}, 201);
    expect(route).toBe("/api/companies/current/users");
    memberCount += 1;
    return response({ membership_id: options.duplicateMemberIds || memberCount === 1 ? legalId : reviewerId });
  }) };
  const spawnSync = vi.fn(() => ({ status: 0 }));
  const prepareIp15Workspace = vi.fn(async () => workspace);
  const createIp15ManualTrademark = vi.fn(async () => ({ docket: { id: run }, application: { id: otherId } }));
  const context = vm.createContext({ URL, path, expect, spawnSync, repoRoot: root,
    process: { platform: process.platform, env: {} }, e2eEnv: { CASEOPS_DATABASE_URL: "postgresql+psycopg://fixture:fixture@127.0.0.1/fixture" },
    randomUUID: () => run, noPaidProviderHeaders: marker, prepareIp15Workspace, createIp15ManualTrademark,
    playwrightRequest: { newContext } });
  vm.runInContext(ts.transpileModule(body, { compilerOptions: { target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS } }).outputText, context);
  const helper = context as unknown as { prepare: (...args: unknown[]) => Promise<{
    legal: typeof legal | null; reviewerId: string; docketId: string;
  }> };
  return { run: () => helper.prepare({}, request, workspace.web.origin, 393), authentication, legal, newContext,
    request, release, spawnSync, events, activationRequests, workspace, prepareIp15Workspace, createIp15ManualTrademark,
    headers: () => legalHeaders };
}

describe("IP15 independent reviewer fixture authentication", () => {
  it("uses a separate Bearer context for the exact legal actor and both activations", async () => {
    const f = fixture();
    const result = await f.run();
    expect(f.newContext).toHaveBeenCalledTimes(2);
    expect(f.newContext.mock.calls[0][0]).toEqual({ extraHTTPHeaders: marker });
    expect(Object.keys(f.newContext.mock.calls[1][0])).toEqual(["extraHTTPHeaders"]);
    expect(Object.keys(f.headers()).sort()).toEqual(["Authorization", "X-CaseOps-Automated-Test"]);
    expect(f.headers().Authorization === `Bearer ${legalToken}`).toBe(true);
    expect(f.headers()["X-CaseOps-Automated-Test"]).toBe("no-paid-providers");
    expect(f.authentication.dispose).toHaveBeenCalledExactlyOnceWith();
    expect(f.legal.get).toHaveBeenCalledExactlyOnceWith("http://127.0.0.1:8000/api/auth/me");
    expect(f.legal.dispose).not.toHaveBeenCalled();
    expect(f.release).toHaveBeenCalledExactlyOnceWith();
    expect(result.legal).toBe(f.legal);
    expect(result.reviewerId).toBe(reviewerId);
    expect(result.docketId).toBe(run);
    expect(f.events.indexOf("current-identity")).toBeLessThan(f.events.indexOf("release"));
    for (const route of ["working-calendars", "deadline-rules"]) {
      await result.legal!.post(`http://127.0.0.1:8000/api/ip/${route}/${run}/activate`);
    }
    expect(f.activationRequests).toEqual(["working-calendars", "deadline-rules"].map(route => ({
      path: `/api/ip/${route}/${run}/activate`, correctBearer: true, noPaid: true,
    })));
    await result.legal!.dispose();
  });

  it.each([undefined, null, "", "   ", 42])("rejects blank/non-string login token case %# before creating a legal context", async token => {
    const f = fixture({ login: actor => ({ ...actor, access_token: token }) });
    await expect(f.run()).rejects.toThrow();
    expect(f.newContext).toHaveBeenCalledTimes(1);
    expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
    expect(f.legal.get).not.toHaveBeenCalled();
    expect(f.release).not.toHaveBeenCalled();
  });

  const identityChanges: Array<[string, (actor: Identity) => Identity]> = [
    ["foreign company", actor => ({ ...actor, company: { ...actor.company, id: otherId } })],
    ["foreign slug", actor => ({ ...actor, company: { ...actor.company, slug: "foreign-fixture" } })],
    ["foreign member", actor => ({ ...actor, membership: { ...actor.membership, id: otherId } })],
    ["owner instead of legal member", actor => ({ ...actor, membership: { ...actor.membership, id: ownerId } })],
    ["wrong role", actor => ({ ...actor, membership: { ...actor.membership, role: "member" } })],
    ["inactive member", actor => ({ ...actor, membership: { ...actor.membership, is_active: false } })],
    ["inactive company", actor => ({ ...actor, company: { ...actor.company, is_active: false } })],
  ];
  it.each(identityChanges)("rejects login %s and disposes authentication", async (_name, change) => {
    const f = fixture({ login: actor => ({ ...change(actor), access_token: actor.access_token, token_type: actor.token_type }) });
    await expect(f.run()).rejects.toThrow();
    expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
    expect(f.newContext).toHaveBeenCalledTimes(1);
    expect(f.legal.get).not.toHaveBeenCalled();
  });

  it.each(identityChanges)("rejects current %s and disposes the Bearer context", async (_name, change) => {
    const f = fixture({ current: change });
    await expect(f.run()).rejects.toThrow();
    expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
    expect(f.legal.get).toHaveBeenCalledTimes(1);
    expect(f.legal.dispose).toHaveBeenCalledTimes(1);
    expect(f.release).not.toHaveBeenCalled();
  });

  it("rejects current missing activation capability despite the admin role", async () => {
    const f = fixture({ current: actor => ({ ...actor, capabilities: ["ip:read"] }) });
    await expect(f.run()).rejects.toThrow();
    expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
    expect(f.legal.dispose).toHaveBeenCalledTimes(1);
    expect(f.release).not.toHaveBeenCalled();
  });

  it("rejects a non-Bearer login token type before legal creation", async () => {
    const f = fixture({ login: actor => ({ ...actor, token_type: "cookie" }) });
    await expect(f.run()).rejects.toThrow();
    expect(f.newContext).toHaveBeenCalledTimes(1);
    expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
  });

  it("preserves independent creator, legal actor and reviewer identities", async () => {
    const f = fixture({ duplicateMemberIds: true });
    await expect(f.run()).rejects.toThrow();
    expect(f.newContext).not.toHaveBeenCalled();
  });

  it.each(["login transport", "login HTTP", "current transport", "current HTTP", "release", "authentication disposal", "legal creation"])(
    "cleans up after %s failure without returning a context", async boundary => {
      const failure = new Error("Synthetic fixture boundary failure");
      const f = fixture({
        ...(boundary === "login transport" ? { loginFailure: failure } : {}),
        ...(boundary === "login HTTP" ? { loginStatus: 401 } : {}),
        ...(boundary === "current transport" ? { currentFailure: failure } : {}),
        ...(boundary === "current HTTP" ? { currentStatus: 403 } : {}),
        ...(boundary === "release" ? { releaseFailure: failure } : {}),
        ...(boundary === "authentication disposal" ? { authenticationDisposeFailure: failure } : {}),
        ...(boundary === "legal creation" ? { legalCreationFailure: failure } : {}),
      });
      await expect(f.run()).rejects.toThrow();
      expect(f.authentication.dispose).toHaveBeenCalledTimes(1);
      if (["current transport", "current HTTP", "release"].includes(boundary)) {
        expect(f.legal.dispose).toHaveBeenCalledTimes(1);
      } else {
        expect(f.legal.dispose).not.toHaveBeenCalled();
      }
    },
  );

  it("does not create local actors, role mutations or request contexts in production", async () => {
    const f = fixture({ local: false });
    const result = await f.run();
    expect(result).toMatchObject({ legal: null, reviewerId: "", docketId: run });
    expect(f.request.post.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([`/api/ip/dockets/${run}/proceedings`]);
    expect(f.spawnSync).not.toHaveBeenCalled();
    expect(f.newContext).not.toHaveBeenCalled();
    expect(f.release).not.toHaveBeenCalled();
  });
});
