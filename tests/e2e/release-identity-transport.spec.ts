import http from "node:http";
import { once } from "node:events";
import type { Socket } from "node:net";
import { test as base, expect, request, type APIRequestContext } from "@playwright/test";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";

const sha = "a".repeat(40);
type Mode = "normal" | "reset" | "status" | "JSON" | "SHA" | "shape" | "redirect";
type Record = { path: string; connectionId: number; connectionClose: boolean; noPaid: boolean;
  cookiePresent: boolean; authorizationPresent: boolean; method: string };
type Wire = { origin: string; records: Record[]; mode: Mode; failWeb: boolean };

const test = base.extend<{ wire: Wire }>({
  wire: async ({}, use, info) => {
    const sockets = new Set<Socket>();
    const ids = new WeakMap<Socket, number>();
    const uses = new WeakMap<Socket, number>();
    let nextId = 0;
    const wire: Wire = { origin: "", records: [], mode: "normal", failWeb: false };
    const server = http.createServer((req, res) => {
      const route = new URL(req.url!, "http://127.0.0.1").pathname;
      const count = (uses.get(req.socket) ?? 0) + 1;
      uses.set(req.socket, count);
      wire.records.push({ path: route, connectionId: ids.get(req.socket)!, connectionClose: req.headers.connection === "close",
        noPaid: req.headers["x-caseops-automated-test"] === "no-paid-providers", cookiePresent: Boolean(req.headers.cookie),
        authorizationPresent: Boolean(req.headers.authorization), method: req.method! });
      if (route === "/follow" && count > 1) { req.socket.destroy(); return; }
      const mode = !wire.failWeb || route === "/api/release-identity" ? wire.mode : "normal";
      if (mode === "reset") { req.socket.destroy(); return; }
      res.setHeader("Content-Type", "application/json");
      if (route === "/seed" || route === "/api/build") res.setHeader("Set-Cookie", "synthetic_public=not-a-credential; Path=/; HttpOnly");
      if (mode === "redirect") { res.writeHead(302, { Location: "/forbidden-follow" }).end(); return; }
      res.statusCode = mode === "status" ? 503 : 200;
      res.end(mode === "JSON" ? "invalid JSON" : JSON.stringify(mode === "shape" ? [] : { release_sha: mode === "SHA" ? "b".repeat(40) : sha }));
    });
    server.keepAliveTimeout = 5000;
    server.on("connection", socket => {
      ids.set(socket, ++nextId); sockets.add(socket);
      socket.on("error", () => {});
      socket.once("close", () => sockets.delete(socket));
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    wire.origin = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
    try { await use(wire); }
    finally {
      const serverClosed = new Promise<void>(resolve => server.close(() => resolve()));
      await Promise.all([...sockets].map(socket => new Promise<void>(resolve => {
        socket.once("close", () => resolve());
        socket.destroy();
      })));
      await serverClosed;
      await info.attach("public-release-wire", { contentType: "application/json", body: Buffer.from(JSON.stringify({
        records: wire.records, socketsRemaining: sockets.size, serverClosed: !server.listening,
      })) });
      expect(sockets.size).toBe(0);
    }
  },
});
test.use({ storageState: { cookies: [], origins: [] }, trace: "off", screenshot: "off", video: "off",
  extraHTTPHeaders: async ({ baseURL }, use) => {
    if (!baseURL) throw new Error("Protocol regression requires a configured baseURL.");
    await use(localTransportHeaders(baseURL));
  } });
test.describe.configure({ mode: "default", retries: 0 });

async function observePublicRead(work: () => Promise<void>) {
  const original = request.newContext;
  const clients: Array<{ api: APIRequestContext; dispose: () => Promise<void>; calls: number }> = [];
  request.newContext = async options => {
    const api = await original.call(request, options);
    const tracked = { api, dispose: () => api.dispose(), calls: 0 };
    const dispose = api.dispose.bind(api);
    tracked.dispose = () => dispose();
    api.dispose = async options => { tracked.calls++; await dispose(options); };
    clients.push(tracked);
    return api;
  };
  try {
    const error: Error | undefined = await work().then(() => undefined, error => error);
    return { error, disposeCalls: clients.map(client => client.calls) };
  } finally {
    request.newContext = original;
    for (const client of clients) if (!client.calls) await client.dispose();
  }
}

test("fixture defaults retain close when per-call headers contain only the no-paid marker", async ({ request: api, wire }) => {
  for (let index = 0; index < 2; index++) await (await api.get(`${wire.origin}/api/build`, { headers: noPaidProviderHeaders, maxRetries: 0 })).body();
  expect(wire.records.map(record => record.connectionClose)).toEqual([true, true]);
  expect(wire.records[0].connectionId).not.toBe(wire.records[1].connectionId);
});

test.describe("intentional marker-only option negative control", () => {
  test.use({ extraHTTPHeaders: noPaidProviderHeaders });
  test("option override loses close but page headers cannot repair the isolated request fixture", async ({ request: api, page, wire }) => {
    for (let index = 0; index < 2; index++) await (await api.get(`${wire.origin}/api/build`, { headers: noPaidProviderHeaders, maxRetries: 0 })).body();
    expect(wire.records.map(record => record.connectionClose)).toEqual([false, false]);
    expect(wire.records[0].connectionId).toBe(wire.records[1].connectionId);
    await page.context().route("**/*", route => new URL(route.request().url()).origin === wire.origin ? route.continue() : route.abort());
    await page.setExtraHTTPHeaders(localTransportHeaders(wire.origin));
    await page.goto(`${wire.origin}/page`);
    await (await api.get(`${wire.origin}/isolated`, { headers: noPaidProviderHeaders, maxRetries: 0 })).body();
    await (await page.request.get(`${wire.origin}/page-request`, { headers: noPaidProviderHeaders, maxRetries: 0 })).body();
    expect(wire.records.find(record => record.path === "/page")!.connectionClose).toBe(true);
    expect(wire.records.find(record => record.path === "/isolated")!.connectionClose).toBe(false);
    expect(wire.records.find(record => record.path === "/page-request")!.connectionClose).toBe(false);
  });
});

test("public reads strip actor credentials and public response cookies without claiming fresh socket isolation", async ({ wire }) => {
  const actor = await request.newContext({ storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: { ...noPaidProviderHeaders, Authorization: "Bearer synthetic-not-a-credential" } });
  try {
    await (await actor.get(`${wire.origin}/seed`, { maxRetries: 0 })).body();
    await (await actor.get(`${wire.origin}/inherited`, { maxRetries: 0 })).body();
    expect(wire.records[1]).toMatchObject({ cookiePresent: true, authorizationPresent: true });
    const result = await observePublicRead(() => assertPublicReleaseIdentity([`${wire.origin}/api/build`, `${wire.origin}/api/release-identity`], sha));
    expect(result.error).toBeUndefined();
    expect(result.disposeCalls).toEqual([1, 1]);
    const publicRecords = wire.records.slice(2);
    expect(publicRecords.map(record => [record.path, record.method, record.cookiePresent, record.authorizationPresent, record.noPaid, record.connectionClose]))
      .toEqual(["/api/build", "/api/release-identity"].map(path => [path, "GET", false, false, true, true]));
    expect(publicRecords[0].connectionId).toBe(wire.records[1].connectionId);
    expect(publicRecords[1].connectionId).not.toBe(publicRecords[0].connectionId);
  } finally { await actor.dispose(); }
});

test.describe("ambient fixture credential negative control", () => {
  test.use({ extraHTTPHeaders: { ...noPaidProviderHeaders, Authorization: "Bearer synthetic-not-a-credential" },
    httpCredentials: { username: "synthetic", password: "not-a-credential", send: "always" },
    storageState: { cookies: [{ name: "synthetic_actor", value: "not-a-credential", domain: "127.0.0.1", path: "/",
      expires: -1, httpOnly: true, secure: false, sameSite: "Lax" }], origins: [] } });
  test("public factory overrides fixture storage, default authorization and HTTP credentials", async ({ request: actor, wire }) => {
    await (await actor.get(`${wire.origin}/inherited`, { maxRetries: 0 })).body();
    expect(wire.records[0]).toMatchObject({ cookiePresent: true, authorizationPresent: true });
    const result = await observePublicRead(() => assertPublicReleaseIdentity([`${wire.origin}/api/build`, `${wire.origin}/api/release-identity`], sha));
    expect(result.error).toBeUndefined();
    expect(result.disposeCalls).toEqual([1, 1]);
    expect(wire.records.slice(1).map(record => [record.cookiePresent, record.authorizationPresent])).toEqual([[false, false], [false, false]]);
  });
});

for (const mode of ["reset", "status", "JSON", "SHA", "shape", "redirect"] as const) {
  test(`public ${mode} failure is fatal, sanitized, single-attempt and disposes its context`, async ({ wire }) => {
    wire.mode = mode;
    const result = await observePublicRead(() => assertPublicReleaseIdentity([`${wire.origin}/api/build`, `${wire.origin}/api/release-identity`], sha));
    const stage = { reset: "transport", status: "status", JSON: "JSON", SHA: "SHA", shape: "SHA", redirect: "status" }[mode];
    expect(result.error?.message).toBe(`Public API release identity ${stage} failed; private details omitted.`);
    expect(result.error?.cause).toBeUndefined();
    expect(result.disposeCalls).toEqual([1]);
    expect(wire.records).toHaveLength(1);
    expect(wire.records[0]).toMatchObject({ path: "/api/build", method: "GET", cookiePresent: false, authorizationPresent: false, noPaid: true, connectionClose: true });
  });
}

test("web identity changes fail after a successful API read with both contexts disposed", async ({ wire }) => {
  wire.mode = "SHA"; wire.failWeb = true;
  const result = await observePublicRead(() => assertPublicReleaseIdentity([`${wire.origin}/api/build`, `${wire.origin}/api/release-identity`], sha));
  expect(result.error?.message).toContain("Public web release identity SHA failed");
  expect(result.disposeCalls).toEqual([1, 1]);
  expect(wire.records.map(record => record.path)).toEqual(["/api/build", "/api/release-identity"]);
});

test("a harmless reset emulator POST remains one attempt with no mutation retry", async ({ wire }) => {
  wire.mode = "reset";
  const api = await request.newContext({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: localTransportHeaders(wire.origin) });
  try {
    const rejected = await api.post(`${wire.origin}/harmless-post`, { maxRetries: 0 }).then(() => false, () => true);
    expect(rejected).toBe(true);
    expect(wire.records).toHaveLength(1);
    expect(wire.records[0]).toMatchObject({ path: "/harmless-post", method: "POST", cookiePresent: false, authorizationPresent: false, noPaid: true });
  } finally { await api.dispose(); }
});

test("injected reused-socket fault is not retried while a close control uses a successor connection", async ({ wire }) => {
  for (const close of [false, true]) {
    const api = await request.newContext({ storageState: { cookies: [], origins: [] },
      extraHTTPHeaders: close ? localTransportHeaders(wire.origin) : noPaidProviderHeaders });
    try {
      await (await api.get(`${wire.origin}/prime`, { maxRetries: 0 })).body();
      const result = await api.get(`${wire.origin}/follow`, { maxRetries: 0 }).then(async response => {
        await response.body(); return { failed: false };
      }, () => ({ failed: true }));
      expect(result.failed).toBe(!close);
      const pair = wire.records.slice(-2);
      if (close) expect(pair[0].connectionId).not.toBe(pair[1].connectionId);
      else expect(pair[0].connectionId).toBe(pair[1].connectionId);
    } finally { await api.dispose(); }
  }
  expect(wire.records.filter(record => record.path === "/follow")).toHaveLength(2);
});
