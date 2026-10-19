// @vitest-environment node
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import ts from "typescript";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ newContext: vi.fn() }));
vi.mock("@playwright/test", () => ({ request: mocks, expect: undefined }));
import { assertPublicReleaseIdentity } from "../../../tests/e2e/support/public-release-identity";
import { localTransportHeaders, noPaidProviderHeaders } from "../../../tests/e2e/support/cost-controls";

const sha = "c".repeat(40);
const endpoints = ["http://127.0.0.1:8000/api/build", "http://127.0.0.1:3100/api/release-identity"] as const;
const root = path.resolve(__dirname, "../../..");
const clients: Array<{ get: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> = [];

beforeEach(() => {
  clients.length = 0;
  mocks.newContext.mockReset().mockImplementation(async () => {
    const client = { get: vi.fn(async () => ({ status: () => 200, json: async () => ({ release_sha: sha }) })),
      dispose: vi.fn(async () => {}) };
    clients.push(client);
    return client;
  });
});

describe("public release identity admission and cleanup", () => {
  it("uses distinct empty public jars, exact endpoints and a single GET attempt without a timeout override", async () => {
    await assertPublicReleaseIdentity(endpoints, sha);
    expect(mocks.newContext).toHaveBeenCalledTimes(2);
    for (const [index, client] of clients.entries()) {
      expect(mocks.newContext.mock.calls[index]).toEqual([{
        storageState: { cookies: [], origins: [] }, httpCredentials: undefined,
        extraHTTPHeaders: localTransportHeaders(endpoints[index]), clientCertificates: [],
      }]);
      expect(client.get).toHaveBeenCalledExactlyOnceWith(endpoints[index], {
        headers: localTransportHeaders(endpoints[index]), maxRetries: 0, maxRedirects: 0,
      });
      expect(client.dispose).toHaveBeenCalledExactlyOnceWith();
    }
  });

  it.each(["context", "transport", "status", "JSON", "SHA", "cleanup"])("rejects %s failures without propagating raw details", async stage => {
    const raw = new Error("synthetic private transport detail");
    const client = { get: vi.fn(async () => {
      if (stage === "transport") throw raw;
      return { status: () => stage === "status" ? 503 : 200, json: async () => {
        if (stage === "JSON") throw raw;
        return { release_sha: stage === "SHA" ? "d".repeat(40) : sha };
      } };
    }), dispose: vi.fn(async () => { if (stage === "cleanup") throw raw; }) };
    mocks.newContext.mockImplementation(async () => { if (stage === "context") throw raw; return client; });
    const error = await assertPublicReleaseIdentity(endpoints, sha).catch(error => error);
    expect(error.message).toBe(`Public API release identity ${stage} failed; private details omitted.`);
    expect(error.cause).toBeUndefined();
    expect(mocks.newContext).toHaveBeenCalledTimes(1);
    expect(client.get).toHaveBeenCalledTimes(stage === "context" ? 0 : 1);
    expect(client.dispose).toHaveBeenCalledTimes(stage === "context" ? 0 : 1);
  });

  it.each([null, [], "not an object", {}, { release_sha: 123 }, { release_sha: sha.toUpperCase() }])("rejects malformed identity %# and disposes its context", async identity => {
    mocks.newContext.mockImplementation(async () => {
      const client = { get: vi.fn(async () => ({ status: () => 200, json: async () => identity })), dispose: vi.fn(async () => {}) };
      clients.push(client); return client;
    });
    await expect(assertPublicReleaseIdentity(endpoints, sha)).rejects.toThrow("identity SHA failed");
    expect(clients).toHaveLength(1);
    expect(clients[0].dispose).toHaveBeenCalledExactlyOnceWith();
  });

  it("retains API success and rejects a changed web SHA with both contexts disposed", async () => {
    let count = 0;
    mocks.newContext.mockImplementation(async () => {
      const current = ++count;
      const client = { get: vi.fn(async () => ({ status: () => 200, json: async () => ({ release_sha: current === 1 ? sha : "d".repeat(40) }) })),
        dispose: vi.fn(async () => {}) };
      clients.push(client); return client;
    });
    await expect(assertPublicReleaseIdentity(endpoints, sha)).rejects.toThrow("Public web release identity SHA failed");
    expect(clients).toHaveLength(2);
    for (const client of clients) expect(client.dispose).toHaveBeenCalledExactlyOnceWith();
  });

  it.each([
    "http://user:private@127.0.0.1:8000/api/build", "file:///api/build", "not a URL",
    "http://127.0.0.1:8000/api/build?private=value", "http://127.0.0.1:8000/api/build#private",
    "http://127.0.0.1:8000/api/auth/login", "http://127.0.0.1:8000/api/build/",
  ])("rejects an unsafe or wrong-path endpoint before creating any context (%#)", async endpoint => {
    await expect(assertPublicReleaseIdentity([endpoint, endpoints[1]], sha)).rejects.toThrow("Invalid public release identity endpoint.");
    expect(mocks.newContext).not.toHaveBeenCalled();
  });

  it.each(["main", "c".repeat(39), "C".repeat(40)])("rejects malformed expected SHA %# before creating any context", async expected => {
    await expect(assertPublicReleaseIdentity(endpoints, expected)).rejects.toThrow("40-hex");
    expect(mocks.newContext).not.toHaveBeenCalled();
  });

  it.each([
    ["http://127.0.0.1:3210", true], ["http://localhost:3210", true], ["http://[::1]:3210", true],
    ["https://127.0.0.1:3210", false], ["https://caseops.ai", false], ["http://remote.invalid", false],
    ["http://localhost.remote.invalid", false], ["https://api.caseops.ai", false],
  ] as const)("adds close only to HTTP loopback: %s", (origin, close) => {
    expect(localTransportHeaders(origin)).toEqual({ ...noPaidProviderHeaders, ...(close ? { Connection: "close" } : {}) });
  });
});

describe("adjacent shared public reader bindings", () => {
  it.each([
    "ram-2026-10-15-ip-controls.spec.ts", "ram-2026-10-15-ip-renewal-tracker.spec.ts",
    "ram-2026-10-17-ip-reminders.spec.ts", "ram-2026-10-17-ip-tracker.spec.ts",
    "ram-2026-10-17-calendar-readiness.spec.ts",
  ])("resolves the IP15 header option from baseURL, not an always-close global: %s", async file => {
    const source = readFileSync(path.join(root, "tests/e2e", file), "utf8");
    const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
    const statement = ast.statements.find(statement => ts.isExpressionStatement(statement)
      && ts.isCallExpression(statement.expression) && statement.expression.expression.getText(ast) === "test.use") as ts.ExpressionStatement;
    const call = statement.expression as ts.CallExpression;
    const settings = call.arguments[0] as ts.ObjectLiteralExpression;
    const property = settings.properties.find(property => property.name?.getText(ast) === "extraHTTPHeaders") as ts.PropertyAssignment;
    expect(ts.isArrowFunction(property.initializer)).toBe(true);
    const context = vm.createContext({ localTransportHeaders });
    vm.runInContext(ts.transpileModule(`globalThis.option = (${property.initializer.getText(ast)});`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText, context);
    for (const baseURL of ["http://127.0.0.1:3210", "http://localhost:3210", "https://caseops.ai"]) {
      const use = vi.fn(async () => {});
      await context.option({ baseURL }, use);
      expect(use).toHaveBeenCalledExactlyOnceWith(localTransportHeaders(baseURL));
    }
    await expect(context.option({}, vi.fn())).rejects.toThrow("configured baseURL");
  });

  it("notice release checks ignore the actor context without changing API/web endpoints or expected SHA", async () => {
    const source = readFileSync(path.join(root, "tests/e2e/support/notice-upload-access.ts"), "utf8");
    const ast = ts.createSourceFile("notice.ts", source, ts.ScriptTarget.Latest, true);
    const owner = ast.statements.find(ts.isClassDeclaration)!;
    const method = owner.members.find(member => ts.isMethodDeclaration(member) && member.name.getText(ast) === "assertRelease")!;
    const assertPublicReleaseIdentity = vi.fn(async () => {});
    const context = vm.createContext({ assertPublicReleaseIdentity });
    vm.runInContext(ts.transpileModule(`class Binding { ${method.getText(ast)} }; globalThis.Binding = Binding;`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText, context);
    const Binding = context.Binding as { prototype: { assertRelease: (...args: unknown[]) => Promise<void> } };
    const actor = { get: vi.fn(() => { throw new Error("Actor public read forbidden"); }) };
    await Binding.prototype.assertRelease.call({ expectedSha: sha, apiUrl: "http://127.0.0.1:8000", webUrl: "http://127.0.0.1:3100" }, actor);
    expect(assertPublicReleaseIdentity).toHaveBeenCalledExactlyOnceWith([...endpoints], sha);
    expect(actor.get).not.toHaveBeenCalled();
    assertPublicReleaseIdentity.mockClear();
    await Binding.prototype.assertRelease.call({}, actor);
    expect(assertPublicReleaseIdentity).not.toHaveBeenCalled();
  });

  it("patent existing-QA release checks retain production endpoints, SHA and local branch without actor reads", async () => {
    const source = readFileSync(path.join(root, "tests/e2e/support/patent-acceptance.ts"), "utf8");
    const ast = ts.createSourceFile("patent.ts", source, ts.ScriptTarget.Latest, true);
    const functions = ast.statements.filter(statement => ts.isFunctionDeclaration(statement)
      && ["required", "assertPatentRelease"].includes(statement.name?.text ?? "")).map(statement => statement.getText(ast)).join("\n");
    const assertPublicReleaseIdentity = vi.fn(async () => {});
    const context = vm.createContext({ exports: {}, expect, existingQa: true, apiBaseUrl: "https://api.caseops.ai", assertPublicReleaseIdentity,
      process: { env: { CASEOPS_EXPECTED_RELEASE_SHA: sha, PROD_BASE_URL: "https://caseops.ai" } } });
    vm.runInContext(ts.transpileModule(functions, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, context);
    const actor = { get: vi.fn(() => { throw new Error("Actor public read forbidden"); }) };
    await context.assertPatentRelease(actor);
    expect(assertPublicReleaseIdentity).toHaveBeenCalledExactlyOnceWith(["https://api.caseops.ai/api/build", "https://caseops.ai/api/release-identity"], sha);
    expect(actor.get).not.toHaveBeenCalled();
    context.existingQa = false;
    assertPublicReleaseIdentity.mockClear();
    await context.assertPatentRelease(actor);
    expect(assertPublicReleaseIdentity).not.toHaveBeenCalled();
  });
});
