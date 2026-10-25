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
  assert.deepEqual(parseGrant(fixture), fixture);
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

test("grant identity rejects empty principals and missing role", () => {
  for (const partial of [
    { company: { ...fixture.company, id: "" } },
    { user: { ...fixture.user, id: " " } },
    { membership: { id: fixture.membership.id } },
    { membership: { ...fixture.membership, role: null } },
  ])
    assert.throws(() => parseGrant({ ...fixture, ...partial }));
});

test("malformed revalidation cannot replace trusted identity or capabilities", async () => {
  for (const partial of [
    { capabilities: "matter.write" },
    { membership: { ...fixture.membership, role: null } },
    { user: { ...fixture.user, email: null } },
  ]) {
    const { store, current } = memoryStore();
    let revoked = 0;
    const session = new NativeSession(
      new JsonTransport("https://caseops.ai", false, true, async (url) => {
        if (url.endsWith("/token")) return Response.json(fixture);
        if (url.endsWith("/logout")) {
          revoked++;
          return new Response(null, { status: 204 });
        }
        return Response.json({ ...fixture, ...partial });
      }),
      store,
    );
    await session.exchange(exchange);
    await assert.rejects(
      session.revalidate(),
      /identity could not be verified/,
    );
    assert.equal(session.identity, null);
    assert.equal(current(), null);
    assert.equal(revoked, 1);
  }
});

test("an identity snapshot cannot mutate the session's authority", async () => {
  const { store } = memoryStore();
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async () =>
      Response.json(fixture),
    ),
    store,
  );
  await session.exchange(exchange);
  const snapshot = session.identity!;
  snapshot.company.id = "other-tenant";
  snapshot.user.id = "other-person";
  snapshot.membership.role = "untrusted";
  snapshot.capabilities.push("injected");
  assert.equal(session.identity!.company.id, fixture.company.id);
  assert.equal(session.identity!.user.id, fixture.user.id);
  assert.equal(session.identity!.membership.role, fixture.membership.role);
  assert.deepEqual(session.identity!.capabilities, fixture.capabilities);
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

test("logout still clears retained credentials when secure-store read throws and reports uncertain revocation truthfully", async () => {
  const { store, current } = memoryStore();
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async () =>
      Response.json(fixture),
    ),
    store,
  );
  await session.exchange(exchange);
  store.read = async () => {
    throw new Error("Synthetic storage read failure");
  };
  let clears = 0;
  const clear = store.clear;
  store.clear = async () => {
    clears++;
    await clear();
  };
  let failure: unknown;
  try {
    await session.signOut();
  } catch (error) {
    failure = error;
  }
  assert.equal(clears, 1);
  assert.equal(current(), null);
  assert.equal(session.identity, null);
  assert(failure instanceof Error);
  assert.match(failure.message, /revocation could not be confirmed/);
  assert.doesNotMatch(failure.message, /Synthetic storage read failure/);
});

const privatePath =
  "/api/matters/11111111-1111-4111-8111-111111111111/attachments/22222222-2222-4222-8222-222222222222/download";
function bytesResponse() {
  return new Response(new Uint8Array([7, 8]), {
    headers: {
      "Content-Type": "application/pdf",
      "Cache-Control": "private, no-store",
    },
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test("sessionKey is nonsecret, viewer-safe, changes for sign-in/logout and stays stable through revalidation/refresh", async () => {
  const { store } = memoryStore();
  let now = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/logout")) return new Response(null, { status: 204 });
      if (url.endsWith("/refresh"))
        return Response.json({
          ...fixture,
          access_token: "rotated-access",
          refresh_token: "rotated-refresh",
        });
      return Response.json(fixture);
    },
  );
  const session = new NativeSession(transport, store, () => now);
  const initial = session.sessionKey;
  await session.exchange(exchange);
  const signedIn = session.sessionKey;
  assert.notEqual(signedIn, initial);
  assert.match(signedIn, /^[a-zA-Z0-9_-]{1,200}$/);
  assert(
    !signedIn.includes(fixture.access_token) &&
      !signedIn.includes(fixture.refresh_token) &&
      !signedIn.includes(fixture.session_id),
  );
  await session.revalidate();
  assert.equal(session.sessionKey, signedIn);
  now = 300_001;
  await session.request("/api/auth/me");
  assert.equal(session.sessionKey, signedIn);
  await session.signOut();
  const ended = session.sessionKey;
  assert.notEqual(ended, signedIn);
  await session.exchange(exchange);
  assert.notEqual(session.sessionKey, ended);
  assert.notEqual(new NativeSession(transport, store).sessionKey, initial);
});

test("private bytes preflight rejects invalid paths/caps and cancellation without refreshing or reading stored credentials", async () => {
  let calls = 0,
    reads = 0;
  const { store } = memoryStore();
  store.read = async () => {
    reads++;
    return null;
  };
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async () => {
      calls++;
      return bytesResponse();
    }),
    store,
  );
  await assert.rejects(session.requestBytes("/api/auth/me", { maxBytes: 1 }));
  await assert.rejects(
    session.requestBytes(privatePath, { maxBytes: 52_428_801 }),
  );
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(
    session.requestBytes(privatePath, { maxBytes: 1, signal: abort.signal }),
  );
  assert.equal(calls, 0);
  assert.equal(reads, 0);
});

test("session private bytes preserve exact metadata and do not expose credentials or invent access", async () => {
  const { store } = memoryStore();
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async (url, init) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      assert.equal(
        new Headers(init.headers).get("Authorization"),
        "Bearer fixture-access",
      );
      assert.equal(
        new Headers(init.headers).get("X-CaseOps-Automated-Test"),
        "no-paid-providers",
      );
      return bytesResponse();
    }),
    store,
  );
  await session.exchange(exchange);
  const key = session.sessionKey;
  const response = await session.requestBytes(privatePath, { maxBytes: 2 });
  assert.deepEqual(response, {
    bytes: new Uint8Array([7, 8]),
    contentType: "application/pdf",
    status: 200,
    contentRange: null,
    cacheControl: "private, no-store",
  });
  assert.equal(session.sessionKey, key);
  response.bytes.fill(0);
});

test("source 401 clears local session/keychain; source 403 remains fail-closed without ending the authorized workspace", async () => {
  for (const status of [401, 403]) {
    const { store, current } = memoryStore();
    let invalidated = 0,
      calls = 0,
      cancelled = 0;
    const session = new NativeSession(
      new JsonTransport("https://caseops.ai", false, true, async (url) => {
        if (url.endsWith("/token")) return Response.json(fixture);
        calls++;
        return new Response(
          new ReadableStream({
            cancel() {
              cancelled++;
            },
          }),
          { status },
        );
      }),
      store,
      Date.now,
      () => invalidated++,
    );
    await session.exchange(exchange);
    const key = session.sessionKey;
    await assert.rejects(
      session.requestBytes(privatePath, { maxBytes: 2 }),
      (error) => error instanceof MobileApiError && error.status === status,
    );
    assert.equal(calls, 1);
    assert.equal(cancelled, 1);
    assert.equal(invalidated, status === 401 ? 1 : 0);
    if (status === 401) {
      assert.equal(current(), null);
      assert.equal(session.identity, null);
      assert.notEqual(session.sessionKey, key);
    } else {
      assert.notEqual(current(), null);
      assert.notEqual(session.identity, null);
      assert.equal(session.sessionKey, key);
    }
  }
});

test("logout during a private stream cancels the body immediately and zeros already delivered native chunks", async () => {
  const { store, current } = memoryStore();
  const reading = deferred<void>();
  const chunk = new Uint8Array([3, 4]);
  let cancelled = 0;
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      if (url.endsWith("/logout")) return new Response(null, { status: 204 });
      return new Response(
        new ReadableStream(
          {
            start(controller) {
              controller.enqueue(chunk);
            },
            pull() {
              reading.resolve();
              return new Promise<void>(() => {});
            },
            cancel() {
              cancelled++;
            },
          },
          { highWaterMark: 0 },
        ),
        { headers: { "Content-Type": "application/pdf" } },
      );
    }),
    store,
  );
  await session.exchange(exchange);
  const rejection = assert.rejects(
    session.requestBytes(privatePath, { maxBytes: 10 }),
    (error) =>
      error instanceof MobileApiError && error.code === "native_session_ended",
  );
  await reading.promise;
  await session.signOut();
  await rejection;
  assert.equal(cancelled, 1);
  assert.deepEqual(chunk, new Uint8Array(2));
  assert.equal(session.identity, null);
  assert.equal(current(), null);
});

test("logout after stream EOF but before session return zeros the assembled result instead of exposing stale bytes", async () => {
  const { store } = memoryStore();
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      if (url.endsWith("/logout")) return new Response(null, { status: 204 });
      return bytesResponse();
    },
  );
  const session = new NativeSession(transport, store);
  await session.exchange(exchange);
  const read = transport.requestBytes.bind(transport);
  let owned: Uint8Array | undefined;
  transport.requestBytes = async (...args) => {
    const result = await read(...args);
    owned = result.bytes;
    await session.signOut();
    return result;
  };
  await assert.rejects(
    session.requestBytes(privatePath, { maxBytes: 2 }),
    (error) =>
      error instanceof MobileApiError && error.code === "native_session_ended",
  );
  assert.deepEqual(owned, new Uint8Array(2));
});

test("expiry is rechecked after streaming and expired-session output is zeroed before local invalidation", async () => {
  const { store, current } = memoryStore();
  let now = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url) =>
      url.endsWith("/token") ? Response.json(fixture) : bytesResponse(),
  );
  const session = new NativeSession(transport, store, () => now);
  await session.exchange(exchange);
  const read = transport.requestBytes.bind(transport);
  let owned: Uint8Array | undefined;
  transport.requestBytes = async (...args) => {
    const result = await read(...args);
    owned = result.bytes;
    now = 300_000;
    return result;
  };
  await assert.rejects(
    session.requestBytes(privatePath, { maxBytes: 2 }),
    (error) =>
      error instanceof MobileApiError &&
      error.code === "native_session_expired",
  );
  assert.deepEqual(owned, new Uint8Array(2));
  assert.equal(current(), null);
  assert.equal(session.identity, null);
});

test("JSON and byte preflights share one rotating refresh without changing sessionKey", async () => {
  const { store } = memoryStore();
  let now = 0,
    refreshes = 0;
  const refresh = deferred<void>();
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url, init) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      if (url.endsWith("/refresh")) {
        refreshes++;
        await refresh.promise;
        return Response.json({
          ...fixture,
          access_token: "rotated-access",
          refresh_token: "rotated-refresh",
        });
      }
      assert.equal(
        new Headers(init.headers).get("Authorization"),
        "Bearer rotated-access",
      );
      return url.includes("/download")
        ? bytesResponse()
        : Response.json({ ok: true });
    },
  );
  const session = new NativeSession(transport, store, () => now);
  await session.exchange(exchange);
  const key = session.sessionKey;
  now = 300_001;
  const pending = Promise.all([
    session.requestBytes(privatePath, { maxBytes: 2 }),
    session.request("/api/auth/me"),
  ]);
  refresh.resolve();
  await pending;
  assert.equal(refreshes, 1);
  assert.equal(session.sessionKey, key);
});

test("viewer cancellation interrupts its refresh wait without replay or cancelling another session reader", async () => {
  const { store } = memoryStore();
  const refreshing = deferred<void>(),
    release = deferred<void>();
  let now = 0,
    downloads = 0,
    refreshes = 0;
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async (url) => {
      if (url.endsWith("/token")) return Response.json(fixture);
      if (url.endsWith("/refresh")) {
        refreshes++;
        refreshing.resolve();
        await release.promise;
        return Response.json(fixture);
      }
      if (url.includes("/download")) {
        downloads++;
        return bytesResponse();
      }
      return Response.json({ ok: true });
    }),
    store,
    () => now,
  );
  await session.exchange(exchange);
  now = 300_001;
  const controller = new AbortController();
  const rejected = assert.rejects(
    session.requestBytes(privatePath, {
      maxBytes: 2,
      signal: controller.signal,
    }),
    (error) =>
      error instanceof MobileApiError && error.code === "request_aborted",
  );
  await refreshing.promise;
  const other = session.request("/api/auth/me");
  controller.abort();
  await rejected;
  assert.equal(downloads, 0);
  release.resolve();
  await other;
  assert.equal(refreshes, 1);
  assert.notEqual(session.identity, null);
});

test("late JSON 401 from an older generation cannot clear a newer sign-in or its secure credentials", async () => {
  const { store, current } = memoryStore();
  const old = deferred<Response>();
  let signIns = 0;
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async (url) => {
      if (url.endsWith("/token"))
        return Response.json({
          ...fixture,
          refresh_token: `fixture-refresh-${++signIns}`,
        });
      return old.promise;
    }),
    store,
  );
  await session.exchange(exchange);
  const rejection = assert.rejects(
    session.request("/api/auth/me"),
    (error) => error instanceof MobileApiError && error.status === 401,
  );
  await session.exchange(exchange);
  const key = session.sessionKey;
  old.resolve(
    Response.json(
      { detail: "Synthetic old-session rejection" },
      { status: 401 },
    ),
  );
  await rejection;
  assert.equal(session.sessionKey, key);
  assert.notEqual(session.identity, null);
  assert.equal(current()?.refreshToken, "fixture-refresh-2");
});

test("sign-out still attempts server revocation after clear failure and never claims stale credentials were removed", async () => {
  const { store, current } = memoryStore();
  let revoked = 0;
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async (url) => {
      if (url.endsWith("/logout")) {
        revoked++;
        return new Response(null, { status: 204 });
      }
      return Response.json(fixture);
    }),
    store,
  );
  await session.exchange(exchange);
  store.clear = async () => {
    throw new Error("Synthetic clear failure");
  };
  await assert.rejects(
    session.signOut(),
    /secure credentials could not be cleared/,
  );
  assert.equal(revoked, 1);
  assert.equal(session.identity, null);
  assert.notEqual(current(), null);
});

test("read and notification failures cannot bypass sign-out's best-effort secure-store clear", async () => {
  const { store, current } = memoryStore();
  const session = new NativeSession(
    new JsonTransport("https://caseops.ai", false, true, async () =>
      Response.json(fixture),
    ),
    store,
    Date.now,
    () => {
      throw new Error("Synthetic view cleanup failure");
    },
  );
  await session.exchange(exchange);
  store.read = async () => {
    throw new Error("Synthetic read failure");
  };
  await assert.rejects(session.signOut(), /revocation could not be confirmed/);
  assert.equal(current(), null);
  assert.equal(session.identity, null);
});
