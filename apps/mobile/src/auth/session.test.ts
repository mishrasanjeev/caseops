import { test } from "node:test";
import assert from "node:assert/strict";
import { JsonTransport, MobileApiError } from "../network/http.ts";
import { NativeSession } from "./session.ts";
import { parseGrant } from "./types.ts";
import type {
  CredentialStore,
  NativeGrant,
  StoredCredential,
} from "./types.ts";

const fixture: NativeGrant = {
  access_token: "fixture-access",
  refresh_token: "fixture-refresh",
  session_id: "device-one",
  expires_in: 300,
  company: { id: "company-a", name: "Example Legal", slug: "fixture-legal" },
  user: {
    id: "person-a",
    email: "person@example.test",
    full_name: "Example Person",
  },
  membership: { id: "membership-a", role: "owner" },
  capabilities: ["matter.read"],
};
const exchange = {
  code: "c".repeat(43),
  code_verifier: "v".repeat(64),
  redirect_uri: "caseops://oauth/callback",
  platform: "android" as const,
};
function memoryStore() {
  let value: StoredCredential | null = null;
  const store: CredentialStore = {
    async read() {
      return value;
    },
    async write(next) {
      value = next;
    },
    async clear() {
      value = null;
    },
  };
  return { store, current: () => value };
}

test("grant contract rejects missing identity, capabilities and unsafe token lifetime", () => {
  assert.equal(parseGrant(fixture), fixture);
  for (const partial of [
    { expires_in: 0 },
    { expires_in: 7200 },
    { company: null },
    { capabilities: [null] },
    { refresh_token: "" },
    { user: {} },
  ]) {
    assert.throws(() => parseGrant({ ...fixture, ...partial }));
  }
});

test("only rotating refresh/session identity are stored; access stays in memory", async () => {
  const { store, current } = memoryStore();
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => Response.json(fixture),
  );
  const session = new NativeSession(transport, store);
  await session.exchange(exchange);
  assert.deepEqual(current(), {
    refreshToken: fixture.refresh_token,
    sessionId: fixture.session_id,
  });
  assert.equal(JSON.stringify(current()).includes(fixture.access_token), false);
  assert.equal(session.identity?.user.id, "person-a");
  assert.equal(
    JSON.stringify(session.identity).includes(fixture.access_token),
    false,
  );
  assert.equal(
    JSON.stringify(session.identity).includes(fixture.refresh_token),
    false,
  );
});

test("expired access triggers one single-flight refresh before concurrent reads", async () => {
  const { store } = memoryStore();
  let now = 0;
  let refreshCalls = 0;
  let readCalls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url, init) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      if (url.endsWith("/refresh")) {
        refreshCalls++;
        await new Promise((resolve) => setTimeout(resolve, 5));
        return Response.json({
          ...fixture,
          access_token: "rotated-access",
          refresh_token: "rotated-refresh",
        });
      }
      readCalls++;
      assert.equal(
        new Headers(init.headers).get("Authorization"),
        "Bearer rotated-access",
      );
      return Response.json({ id: "matter-a" });
    },
  );
  const session = new NativeSession(transport, store, () => now);
  await session.exchange(exchange);
  now = 300_001;
  const results = await Promise.all([
    session.request("/api/matters/a"),
    session.request("/api/matters/b"),
  ]);
  assert.equal(results.length, 2);
  assert.equal(refreshCalls, 1);
  assert.equal(readCalls, 2);
});

test("app restart refreshes without a still-valid access credential", async () => {
  const { store } = memoryStore();
  await store.write({
    refreshToken: "retained-refresh",
    sessionId: "device-one",
  });
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url, init) => {
      assert.ok(url.endsWith("/refresh"));
      assert.equal(new Headers(init.headers).has("Authorization"), false);
      return Response.json(fixture);
    },
  );
  const session = new NativeSession(transport, store);
  assert.equal((await session.restore())?.company.id, "company-a");
});

test("401 clears private identity and refresh without replaying the request", async () => {
  const { store, current } = memoryStore();
  let calls = 0;
  let invalidated = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      calls++;
      return Response.json({ detail: "Revoked session." }, { status: 401 });
    },
  );
  const session = new NativeSession(
    transport,
    store,
    Date.now,
    () => invalidated++,
  );
  await session.exchange(exchange);
  await assert.rejects(
    session.request("/api/matters/a"),
    (error: unknown) => error instanceof MobileApiError && error.status === 401,
  );
  assert.equal(calls, 1);
  assert.equal(invalidated, 1);
  assert.equal(current(), null);
  assert.equal(session.identity, null);
});

test("an unknown mutation is not refreshed or resubmitted", async () => {
  const { store } = memoryStore();
  let saves = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      saves++;
      throw new Error("lost acknowledgement");
    },
  );
  const session = new NativeSession(transport, store);
  await session.exchange(exchange);
  await assert.rejects(
    session.request("/api/matters/a/notes", { method: "POST", body: "{}" }),
    (error: unknown) =>
      error instanceof MobileApiError && error.outcome === "unknown",
  );
  assert.equal(saves, 1);
});

test("secure-storage failure revokes the freshly issued device and keeps no identity", async () => {
  let revoked = false;
  const { store } = memoryStore();
  store.write = async () => {
    throw new Error("keychain unavailable");
  };
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/logout")) {
        revoked = true;
        return new Response(null, { status: 204 });
      }
      return Response.json(fixture);
    },
  );
  const session = new NativeSession(transport, store);
  await assert.rejects(session.exchange(exchange), /Secure device storage/);
  assert.equal(revoked, true);
  assert.equal(session.identity, null);
});

test("logout purges locally even if server revocation is unavailable, without false confirmation", async () => {
  const { store, current } = memoryStore();
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      throw new Error("offline");
    },
  );
  const session = new NativeSession(transport, store);
  await session.exchange(exchange);
  await assert.rejects(session.signOut(), /revocation could not be confirmed/);
  assert.equal(session.identity, null);
  assert.equal(current(), null);
});

test("logout wins a concurrent late token exchange and revokes the orphan grant", async () => {
  const { store, current } = memoryStore();
  let release: (() => void) | undefined;
  let revoked = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/token")) {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return Response.json(fixture);
      }
      revoked++;
      return new Response(null, { status: 204 });
    },
  );
  const session = new NativeSession(transport, store);
  const pending = session.exchange(exchange);
  await session.signOut();
  release!();
  await assert.rejects(pending, /cancelled/);
  assert.equal(revoked, 1);
  assert.equal(session.identity, null);
  assert.equal(current(), null);
});
