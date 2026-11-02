import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";
import {
  checkedClientMetadata,
  clientVersionParts,
  compareClientVersions,
} from "./client-version.ts";
import {
  createClientCompatibility,
  isCompatibilityExit,
  parseClientCompatibility,
} from "./client-compatibility.ts";
import { JsonTransport, MobileApiError } from "./http.ts";
import { NativeSession } from "../auth/session.ts";
import type { StoredCredential } from "../auth/types.ts";
import { LOCAL_FOREGROUND_SETTLE_MS } from "../auth/local-unlock.ts";

const client = { platform: "ios" as const, version: "1.10.0" };
const supported = {
  protocol_version: 1,
  platform: "ios",
  client_version: "1.10.0",
  minimum_supported_version: "1.2.0",
  status: "supported",
};
const required = {
  code: "native_client_update_required",
  status: 426,
  platform: "ios",
  minimum_supported_version: "2.0.0",
  detail: "SYNTHETIC_PRIVATE_ERROR",
};
const grant = {
  access_token: "synthetic-access",
  refresh_token: "synthetic-refresh",
  session_id: "synthetic-device",
  expires_in: 300,
  company: {
    id: "company",
    name: "Synthetic private workspace",
    slug: "synthetic",
  },
  user: {
    id: "person",
    email: "synthetic@example.test",
    full_name: "Synthetic private person",
  },
  membership: { id: "member", role: "owner" },
  capabilities: ["matters:read"],
};
const exchange = {
  code: "c".repeat(43),
  code_verifier: "v".repeat(64),
  redirect_uri: "caseops://oauth/callback",
  platform: "ios" as const,
};
const download =
  "/api/matters/00000000-0000-4000-8000-000000000001/attachments/00000000-0000-4000-8000-000000000002/download";
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function control(
  request: (path: string) => Promise<unknown> = async () => supported,
) {
  let principal = "one",
    blocks = 0,
    changes = 0;
  const gate = createClientCompatibility(
    client,
    request,
    () => principal,
    () => {
      ++blocks;
    },
    () => {
      ++changes;
    },
  );
  return {
    gate,
    blocks: () => blocks,
    changes: () => changes,
    principal: (value: string) => {
      principal = value;
    },
  };
}

test("client build versions retain exact ASCII triples and independent numeric ordering", () => {
  assert.deepEqual(clientVersionParts("999999999.0.42"), [999999999, 0, 42]);
  assert.equal(compareClientVersions("1.10.0", "1.2.99"), 1);
  assert.equal(compareClientVersions("1.2.0", "1.2.0"), 0);
  assert.equal(compareClientVersions("0.99.9", "1.0.0"), -1);
  for (const version of [
    null,
    true,
    1,
    "1.2",
    "01.2.3",
    "1.2.3-beta",
    "1.2.3+1",
    "١.٢.٣",
    "1.2.3\n",
    " 1.2.3",
    "1000000000.0.0",
  ])
    assert.throws(() => clientVersionParts(version));
  assert.throws(() =>
    checkedClientMetadata({ platform: "web", version: "1.2.3" }),
  );
});

test("policy decoder requires exact protocol, own platform/version, floor and internally consistent status", () => {
  assert.deepEqual(parseClientCompatibility(supported, client), supported);
  assert.equal(
    parseClientCompatibility(
      { ...supported, minimum_supported_version: null },
      client,
    ).status,
    "supported",
  );
  assert.equal(
    parseClientCompatibility(
      {
        ...supported,
        minimum_supported_version: "2.0.0",
        status: "update_required",
      },
      client,
    ).status,
    "update_required",
  );
  for (const change of [
    { protocol_version: "1" },
    { protocol_version: 2 },
    { platform: "android" },
    { client_version: "1.9.0" },
    { status: "update_required" },
    { status: "ready" },
    { minimum_supported_version: 2 },
    { minimum_supported_version: "2.0.0" },
    { minimum_supported_version: "1.2.0\n" },
    { future: true },
  ])
    assert.throws(() =>
      parseClientCompatibility({ ...supported, ...change }, client),
    );
  const missing = { ...supported } as Record<string, unknown>;
  delete missing.minimum_supported_version;
  assert.throws(() => parseClientCompatibility(missing, client));
  for (const input of [null, [], "supported", true])
    assert.throws(() => parseClientCompatibility(input, client));
});

test("unsupported build metadata makes zero public or private requests and never becomes supported", async () => {
  let calls = 0;
  const gate = createClientCompatibility(
    { platform: "ios", version: "0.1" },
    async () => {
      ++calls;
      return supported;
    },
    () => "none",
    () => {},
    () => {},
  );
  assert.equal(await gate.refresh(), false);
  assert.equal(gate.getSnapshot().status, "unavailable");
  assert.throws(() => gate.admit("/api/matters/", "GET"));
  assert.equal(calls, 0);
});

test("404 rollout, malformed, unavailable and offline policies never masquerade as supported or an update floor", async () => {
  for (const request of [
    async () => {
      throw new MobileApiError("SYNTHETIC_PRIVATE_ERROR", 404, "not_found");
    },
    async () => {
      throw new Error("SYNTHETIC_PRIVATE_ERROR");
    },
    async () => ({ ...supported, platform: "android" }),
    async () => null,
  ]) {
    const { gate } = control(request);
    assert.equal(await gate.refresh(), false);
    assert.equal(gate.getSnapshot().status, "unavailable");
    assert.equal(gate.getSnapshot().minimum, null);
    assert.equal(gate.getSnapshot().busy, false);
    assert.doesNotMatch(gate.getSnapshot().message, /SYNTHETIC_PRIVATE/);
  }
});

test("policy refresh is single-flight and a later explicit successful retry clears an update decision", async () => {
  const pending = deferred<unknown>();
  let calls = 0;
  const { gate } = control(async () => {
    ++calls;
    return pending.promise;
  });
  const a = gate.refresh(),
    b = gate.refresh();
  assert.equal(a, b);
  assert.equal(gate.getSnapshot().busy, true);
  pending.resolve(supported);
  assert.equal(await a, true);
  assert.equal(calls, 1);
  gate.incompatible(required);
  assert.equal(gate.getSnapshot().status, "update_required");
  assert.equal(await gate.refresh(), true);
  assert.equal(calls, 2);
});

test("a late supported result cannot clear a newer 426, background epoch, or changed principal", async () => {
  for (const reason of ["426", "background", "principal"] as const) {
    const pending = deferred<unknown>(),
      f = control(() => pending.promise),
      result = f.gate.refresh();
    if (reason === "426") f.gate.incompatible(required);
    if (reason === "background") f.gate.visibility(false, true);
    if (reason === "principal") f.principal("two");
    pending.resolve(supported);
    assert.equal(await result, false);
    assert.equal(f.gate.supported, false);
    if (reason === "426")
      assert.equal(f.gate.getSnapshot().status, "update_required");
    assert.equal(f.gate.getSnapshot().busy, false);
  }
});

test("an owned browser return can settle active before policy publication without private requests or another policy GET", async () => {
  let calls = 0;
  const { gate } = control(async () => {
    ++calls;
    return supported;
  });
  gate.visibility(false, false);
  const result = gate.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(gate.supported, false);
  assert.equal(gate.getSnapshot().busy, true);
  gate.visibility(true, false);
  assert.equal(await result, true);
  assert.equal(calls, 1);
});

test("foreground settling keeps the existing exact two-second bound and cannot publish while still inactive", async (context) => {
  assert.equal(LOCAL_FOREGROUND_SETTLE_MS, 2000);
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const { gate } = control();
  gate.visibility(false, false);
  const result = gate.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  context.mock.timers.tick(1999);
  assert.equal(gate.getSnapshot().busy, true);
  context.mock.timers.tick(1);
  assert.equal(await result, false);
  assert.equal(gate.supported, false);
  assert.equal(gate.getSnapshot().status, "unavailable");
  context.mock.timers.reset();
});

test("security exits stay admitted below floor, without granting business access or a different method", () => {
  const { gate } = control();
  gate.incompatible(required);
  for (const [path, method] of [
    ["/api/auth/security", "GET"],
    ["/api/auth/native/sessions", "GET"],
    [
      "/api/auth/native/sessions/00000000-0000-4000-8000-000000000001",
      "DELETE",
    ],
    ["/api/auth/native/logout", "POST"],
    ["/api/auth/native/refresh", "POST"],
  ]) {
    assert.equal(isCompatibilityExit(path, method), true);
    assert.doesNotThrow(() => gate.admit(path, method));
  }
  for (const [path, method] of [
    ["/api/matters/", "GET"],
    ["/api/auth/me", "GET"],
    ["/api/auth/security", "POST"],
    ["/api/auth/native/token", "POST"],
    [download, "GET"],
  ])
    assert.throws(() => gate.admit(path, method));
});

test("JSON, multipart and byte transports use the immutable actual-build version and reject caller overrides", async () => {
  const metadata = { platform: "ios", version: "1.10.0" };
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    metadata,
    async (_url, init) => {
      ++calls;
      const headers = new Headers(init.headers);
      assert.equal(headers.get("X-CaseOps-Client-Version"), "1.10.0");
      assert.equal(
        headers.get("X-CaseOps-Automated-Test"),
        "no-paid-providers",
      );
      assert.equal(init.credentials, "omit");
      return headers.get("Accept")?.includes("octet-stream")
        ? new Response(new Uint8Array([1]), {
            headers: { "Content-Type": "image/png", "Content-Length": "1" },
          })
        : Response.json({ ok: true });
    },
  );
  metadata.version = "99.0.0";
  await transport.request("/api/auth/native/refresh", {
    method: "POST",
    body: "{}",
  });
  await transport.request(
    "/api/matters/",
    { method: "POST", body: new FormData() },
    "synthetic-access",
  );
  const bytes = await transport.requestBytes(
    download,
    { maxBytes: 1 },
    "synthetic-access",
  );
  assert.deepEqual([...bytes.bytes], [1]);
  bytes.bytes.fill(0);
  await assert.rejects(
    transport.request("/api/matters/", {
      headers: { "x-caseops-client-version": "99.0.0" },
    }),
  );
  assert.equal(calls, 3);
});

function sessionPipeline(
  fetcher: (url: string, init: RequestInit) => Promise<Response>,
) {
  let stored: StoredCredential | null = null,
    reads = 0,
    clears = 0,
    now = 0,
    blocks = 0;
  let gate!: ReturnType<typeof createClientCompatibility>;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    client,
    fetcher,
    20_000,
    {
      admit: (p, m) => gate.admit(p, m),
      incompatible: (b) => gate.incompatible(b),
    },
  );
  const session = new NativeSession(
    transport,
    {
      async read() {
        ++reads;
        return stored;
      },
      async write(v) {
        stored = v;
      },
      async clear() {
        ++clears;
        stored = null;
      },
    },
    () => now,
    () => {},
    (p, m) => gate.admit(p, m),
  );
  gate = createClientCompatibility(
    client,
    (p) => transport.request(p),
    () => JSON.stringify(session.localBinding),
    () => {
      ++blocks;
    },
    () => {},
  );
  return {
    session,
    gate,
    stored: () => stored,
    reads: () => reads,
    clears: () => clears,
    blocks: () => blocks,
    expire: () => {
      now = 300_001;
    },
  };
}

test("actual native JSON 426 preserves principal and credentials, blocks retained work before refresh, and never replays a mutation", async () => {
  const calls: string[] = [];
  const f = sessionPipeline(async (url) => {
    calls.push(url);
    if (url.includes("/compatibility?")) return Response.json(supported);
    if (url.endsWith("/token")) return Response.json(grant);
    if (url.endsWith("/logout")) return new Response(null, { status: 204 });
    return Response.json(required, { status: 426 });
  });
  await f.gate.refresh();
  await f.session.exchange(exchange);
  const before = f.stored();
  await assert.rejects(
    f.session.request("/api/matters/", { method: "POST", body: "{}" }),
    (e: unknown) =>
      e instanceof MobileApiError &&
      e.status === 426 &&
      e.outcome === "rejected" &&
      !e.message.includes("SYNTHETIC_PRIVATE"),
  );
  assert.equal(f.gate.getSnapshot().status, "update_required");
  assert.equal(f.session.identity?.user.id, "person");
  assert.deepEqual(f.stored(), before);
  assert.equal(f.clears(), 0);
  f.expire();
  const reads = f.reads();
  const count = calls.length;
  await assert.rejects(f.session.request("/api/matters/"));
  await assert.rejects(f.session.requestBytes(download, { maxBytes: 1 }));
  assert.equal(f.reads(), reads);
  assert.equal(calls.length, count);
  assert.equal(calls.filter((x) => x.endsWith("/api/matters/")).length, 1);
  await f.session.signOut();
  assert.equal(f.stored(), null);
  assert.equal(f.session.identity, null);
  assert.equal(calls.filter((x) => x.endsWith("/logout")).length, 1);
});

test("byte 426 cancels its body without parsing private error text; malformed or foreign JSON requires an honest public recheck", async () => {
  for (const body of [
    null,
    { ...required, platform: "android" },
    { ...required, minimum_supported_version: "1.10.0" },
  ]) {
    const f = control();
    f.gate.incompatible(body);
    assert.equal(f.gate.getSnapshot().status, "unavailable");
    assert.equal(f.gate.getSnapshot().minimum, null);
  }
  let cancelled = 0,
    jsonReads = 0;
  const f = sessionPipeline(async (url) => {
    if (url.includes("/compatibility?")) return Response.json(supported);
    if (url.endsWith("/token")) return Response.json(grant);
    const response = new Response(
      new ReadableStream({
        cancel() {
          ++cancelled;
        },
      }),
      { status: 426 },
    );
    response.json = async () => {
      ++jsonReads;
      assert.fail("No private error body parse");
    };
    return response;
  });
  await f.gate.refresh();
  await f.session.exchange(exchange);
  await assert.rejects(
    f.session.requestBytes(download, { maxBytes: 1 }),
    (e: unknown) => e instanceof MobileApiError && e.status === 426,
  );
  assert.equal(f.gate.getSnapshot().status, "unavailable");
  assert.equal(jsonReads, 0);
  assert.equal(cancelled, 1);
  assert.equal(f.clears(), 0);
});

test("an explicit refresh 426 also preserves its valid credential and does not replay a rotating refresh", async () => {
  let refreshes = 0;
  const f = sessionPipeline(async (url) => {
    if (url.includes("/compatibility?")) return Response.json(supported);
    if (url.endsWith("/token")) return Response.json(grant);
    assert.ok(url.endsWith("/refresh"));
    ++refreshes;
    return Response.json(required, { status: 426 });
  });
  await f.gate.refresh();
  await f.session.exchange(exchange);
  const saved = f.stored();
  f.expire();
  await assert.rejects(
    f.session.request("/api/matters/"),
    (e: unknown) => e instanceof MobileApiError && e.status === 426,
  );
  assert.deepEqual(f.stored(), saved);
  assert.equal(f.clears(), 0);
  assert.equal(f.session.identity?.user.id, "person");
  await assert.rejects(f.session.request("/api/matters/"));
  assert.equal(refreshes, 1);
});

test("a concurrent policy refusal cannot expose a late mutation result or replay it; dispatched outcome stays unknown", async () => {
  const pending = deferred<Response>();
  let mutations = 0;
  const f = sessionPipeline(async (url) => {
    if (url.includes("/compatibility?")) return Response.json(supported);
    if (url.endsWith("/token")) return Response.json(grant);
    ++mutations;
    return pending.promise;
  });
  await f.gate.refresh();
  await f.session.exchange(exchange);
  const result = f.session.request("/api/matters/", {
    method: "POST",
    body: "{}",
  });
  await Promise.resolve();
  f.gate.incompatible(required);
  pending.resolve(Response.json({ private_result: "SYNTHETIC_PRIVATE" }));
  await assert.rejects(
    result,
    (e: unknown) => e instanceof MobileApiError && e.outcome === "unknown",
  );
  assert.equal(mutations, 1);
  assert.equal(f.clears(), 0);
  assert.equal(f.session.identity?.user.id, "person");
});

test("actual compatibility panel has honest unavailable/update/checking states, explicit signout and no fabricated store destination", () => {
  const jsx = (type: unknown, props: unknown) => ({ type, props });
  const bindings: Record<string, unknown> = {
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react-native": { ScrollView: "ScrollView", Text: "Text" },
    "react-native-safe-area-context": { SafeAreaView: "SafeAreaView" },
    "./NativeControls": { NativeButton: "Button", NativeProgress: "Progress" },
    "./theme": {
      styles: { fill: {}, content: {}, title: {}, body: {}, muted: {} },
    },
  };
  const code = ts.transpileModule(
    readFileSync(
      new URL("../components/ClientCompatibilityPanel.tsx", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = {
    exports: {} as { ClientCompatibilityPanel: (props: unknown) => unknown },
  };
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), name);
      return bindings[name];
    },
    module,
    module.exports,
  );
  for (const status of [
    "checking",
    "unavailable",
    "update_required",
  ] as const) {
    let retries = 0,
      exits = 0;
    const tree = module.exports.ClientCompatibilityPanel({
      state: {
        status,
        minimum: status === "update_required" ? "2.0.0" : null,
        message: "Fixed public guidance.",
        busy: status === "checking",
      },
      onRetry: () => {
        ++retries;
      },
      onSignOut: () => {
        ++exits;
      },
    });
    const buttons: {
      testID: string;
      disabled?: boolean;
      onPress: () => void;
    }[] = [];
    const visit = (node: any) => {
      if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === "object") {
        if (node.type === "Button") buttons.push(node.props);
        visit(node.props?.children);
      }
    };
    visit(tree);
    assert.equal(buttons.length, 2);
    assert.equal(retries, 0);
    assert.equal(exits, 0);
    assert.equal(
      buttons.find((b) => b.testID === "compatibility-retry")?.disabled,
      status === "checking",
    );
    buttons.find((b) => b.testID === "compatibility-sign-out")!.onPress();
    assert.equal(exits, 1);
    assert.doesNotMatch(
      JSON.stringify(tree),
      /https?:\/\/|apps\.apple|play\.google|Synthetic private/,
    );
    if (status === "update_required")
      assert.match(JSON.stringify(tree), /Update CaseOps|2\.0\.0/);
  }
});
