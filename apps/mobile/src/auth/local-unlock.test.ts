import assert from "node:assert/strict";
import test from "node:test";
import {
  createLocalUnlock,
  localUnlockMarker,
  parseLocalUnlockPolicy,
  LOCAL_FOREGROUND_SETTLE_MS,
} from "./local-unlock.ts";
import type { LocalUnlockPolicy, LocalUnlockStore } from "./local-unlock.ts";
import type { LocalSessionBinding, SessionIdentity } from "./types.ts";
import { NativeSession } from "./session.ts";
import { JsonTransport } from "../network/http.ts";

const installationId = "00000000-0000-4000-8000-000000000001";
const nonce = "00000000-0000-4000-8000-000000000002";
const identity: SessionIdentity = {
  user: {
    id: "person",
    full_name: "Synthetic",
    email: "synthetic@example.test",
  },
  company: { id: "company", slug: "synthetic", name: "Synthetic" },
  membership: { id: "member", role: "admin" },
  capabilities: [],
};
const binding: LocalSessionBinding = {
  userId: "person",
  companyId: "company",
  membershipId: "member",
  sessionId: "server-session",
  sessionKey: "process-generation-1",
};
const policy: LocalUnlockPolicy = {
  version: 1,
  state: "enabled",
  installationId,
  nonce,
  binding: {
    userId: binding.userId,
    companyId: binding.companyId,
    membershipId: binding.membershipId,
    sessionId: binding.sessionId,
  },
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function until(predicate: () => boolean) {
  for (let n = 0; n < 100 && !predicate(); n++) await Promise.resolve();
  assert.ok(predicate(), "Expected the finite synthetic stage");
}
function fixture(
  initial: unknown = null,
  current: LocalSessionBinding | null = binding,
) {
  let persisted = structuredClone(initial),
    marker = initial ? localUnlockMarker(policy) : null;
  let live = current ? { ...current } : null;
  const events: string[] = [];
  let revalidations = 0,
    serverOpens = 0;
  const store: LocalUnlockStore = {
    async readPolicy() {
      events.push("policy-read");
      return structuredClone(persisted);
    },
    async writePolicy(value) {
      events.push(`policy-write:${value.state}`);
      persisted = structuredClone(value);
    },
    async clearMarker() {
      events.push("marker-clear");
      marker = null;
    },
    async writeMarker(value) {
      events.push("marker-write");
      marker = value;
    },
    async readMarker() {
      events.push("biometric-read");
      return marker;
    },
    async clear() {
      events.push("all-clear");
      persisted = null;
      marker = null;
    },
    supported: () => true,
    nonce: () => nonce,
  };
  const authority = {
    current: () => (live ? { ...live } : null),
    async revalidate() {
      events.push("server-revalidate");
      revalidations++;
      return identity;
    },
  };
  const gate = createLocalUnlock(
    installationId,
    store,
    authority,
    async () => {
      events.push("cover");
    },
    () => {},
  );
  const open = async () => {
    serverOpens++;
    events.push("server-open");
    return identity;
  };
  return {
    gate,
    store,
    authority,
    events,
    open,
    setLive(value: LocalSessionBinding | null) {
      live = value;
    },
    setPolicy(value: unknown) {
      persisted = value;
    },
    setMarker(value: string | null) {
      marker = value;
    },
    persisted: () => persisted,
    marker: () => marker,
    counts: () => ({ revalidations, serverOpens }),
  };
}

test("disabled-by-default local gate preserves normal server revalidation and publishes only its exact binding", async () => {
  const f = fixture();
  await f.gate.initialize();
  assert.equal(f.gate.required, false);
  assert.deepEqual(await f.gate.resume(f.open), identity);
  assert.equal(f.gate.allows(binding), true);
  assert.equal(f.events.includes("biometric-read"), false);
  assert.equal(
    f.gate.allows({ ...binding, sessionKey: "another-generation" }),
    false,
  );
  assert.equal(f.gate.allows({ ...binding, userId: "foreign" }), false);
});

test("rendered local commands cannot transfer across lock periods, logout or another principal", async () => {
  const f = fixture();
  await f.gate.initialize();
  await f.gate.resume(f.open);
  const renderedEpoch = f.gate.commandEpoch;
  assert.equal(f.gate.commandCurrent(renderedEpoch, binding), true);
  assert.equal(
    await f.gate.resume(f.open),
    null,
    "An acknowledged reopen cannot replay before rerender",
  );
  f.gate.visibility("inactive");
  f.gate.visibility("active");
  assert.equal(f.gate.commandCurrent(renderedEpoch, binding), false);
  const lockedEpoch = f.gate.commandEpoch;
  assert.equal(f.gate.commandCurrent(lockedEpoch, binding), true);
  f.gate.invalidate();
  f.setLive({ ...binding, userId: "foreign", sessionKey: "new-generation" });
  assert.equal(f.gate.commandCurrent(lockedEpoch, binding), false);
  assert.equal(f.gate.commandCurrent(f.gate.commandEpoch, binding), false);
});

test("enable persists pending intent, authenticates a fresh protected marker read-back, revalidates server and only then enables", async () => {
  const f = fixture();
  await f.gate.initialize();
  assert.deepEqual(await f.gate.enable(), identity);
  assert.deepEqual(f.events, [
    "policy-read",
    "policy-read",
    "cover",
    "server-revalidate",
    "marker-clear",
    "policy-write:pending",
    "marker-write",
    "biometric-read",
    "server-revalidate",
    "policy-write:enabled",
  ]);
  assert.deepEqual(f.persisted(), policy);
  assert.equal(f.gate.getSnapshot().enabled, true);
  assert.equal(f.gate.allows(binding), true);
});

test("a successful protected write without read-back is never accepted as biometric proof", async () => {
  const f = fixture();
  await f.gate.initialize();
  f.store.readMarker = async () => null;
  assert.equal(await f.gate.enable(), null);
  assert.equal((f.persisted() as LocalUnlockPolicy).state, "pending");
  assert.equal(f.gate.required, true);
  assert.equal(f.gate.getSnapshot().enabled, false);
  assert.equal(f.gate.allows(binding), false);
  assert.equal(f.events.includes("policy-write:enabled"), false);
});

test("cold enabled policy refuses automatic restore; explicit biometric success precedes any server credential callback", async () => {
  const f = fixture(policy, null);
  await f.gate.initialize();
  assert.equal(await f.gate.resume(f.open), null);
  assert.equal(f.counts().serverOpens, 0);
  const pending = deferred<string | null>();
  f.store.readMarker = () => {
    f.events.push("biometric-read");
    return pending.promise;
  };
  const unlock = f.gate.unlock(async () => {
    f.events.push("server-open");
    f.setLive(binding);
    return identity;
  });
  await until(() => f.events.includes("biometric-read"));
  assert.equal(f.events.includes("server-open"), false);
  pending.resolve(localUnlockMarker(policy));
  assert.deepEqual(await unlock, identity);
  assert.equal(f.gate.allows(binding), true);
});

test("missing or invalidated protected marker never invokes refresh/private profile or disables the policy", async () => {
  for (const marker of [null, "wrong-installation-marker"]) {
    const f = fixture(policy, null);
    await f.gate.initialize();
    f.setMarker(marker);
    assert.equal(await f.gate.unlock(f.open), null);
    assert.equal(f.counts().serverOpens, 0);
    assert.equal(f.gate.required, true);
    assert.equal(f.gate.allows(binding), false);
    assert.deepEqual(f.persisted(), policy);
  }
});

test("native cancellation, lockout and storage errors stay locked without reflecting native body values", async () => {
  for (const label of ["cancel", "lockout", "storage"]) {
    const f = fixture(policy);
    await f.gate.initialize();
    f.store.readMarker = async () => {
      throw new Error(`${label}: PRIVATE_SUBJECT_AND_TOKEN`);
    };
    assert.equal(await f.gate.unlock(f.open), null);
    assert.equal(f.gate.allows(binding), false);
    assert.equal(f.counts().serverOpens, 0);
    assert.equal(f.gate.getSnapshot().message.includes("PRIVATE"), false);
    assert.equal(f.gate.getSnapshot().status, "locked");
  }
});

test("rapid unlock taps share one lease and never replay an unresolved biometric command", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  const pending = deferred<string | null>();
  let prompts = 0;
  f.store.readMarker = () => {
    prompts++;
    return pending.promise;
  };
  const first = f.gate.unlock(f.open);
  await until(() => prompts === 1);
  assert.equal(await f.gate.unlock(f.open), null);
  assert.equal(await f.gate.enable(), null);
  assert.equal(prompts, 1);
  pending.resolve(localUnlockMarker(policy));
  await first;
  assert.equal(f.gate.allows(binding), true);
});

test("background then foreground cannot publish a late successful prompt", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  const pending = deferred<string | null>();
  let prompts = 0;
  f.store.readMarker = () => {
    prompts++;
    return pending.promise;
  };
  const first = f.gate.unlock(f.open);
  await until(() => prompts === 1);
  f.gate.visibility("background");
  f.gate.visibility("active");
  pending.resolve(localUnlockMarker(policy));
  await first;
  assert.equal(f.gate.allows(binding), false);
  assert.equal(f.counts().serverOpens, 0);
});

test("temporary inactive system prompt covers UI while preserving only the same foreground completion epoch", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  const pending = deferred<string | null>();
  let prompts = 0;
  f.store.readMarker = () => {
    prompts++;
    return pending.promise;
  };
  const first = f.gate.unlock(f.open);
  await until(() => prompts === 1);
  f.gate.visibility("inactive");
  assert.equal(f.gate.allows(binding), false);
  pending.resolve(localUnlockMarker(policy));
  await Promise.resolve();
  f.gate.visibility("active");
  await first;
  assert.equal(f.gate.allows(binding), true);
});

test("completed prompt without a foreground acknowledgement remains locked under the fixed settle bound", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  let started = false;
  const pending = deferred<string | null>();
  f.store.readMarker = () => {
    started = true;
    return pending.promise;
  };
  const unlock = f.gate.unlock(f.open);
  await until(() => started);
  f.gate.visibility("inactive");
  const begin = performance.now();
  pending.resolve(localUnlockMarker(policy));
  assert.equal(await unlock, null);
  assert.ok(performance.now() - begin >= LOCAL_FOREGROUND_SETTLE_MS - 20);
  assert.equal(f.counts().serverOpens, 0);
  assert.equal(f.gate.allows(binding), false);
});

test("new principal/workspace/membership/session/generation at prompt completion cannot reuse local proof", async () => {
  for (const key of [
    "userId",
    "companyId",
    "membershipId",
    "sessionId",
    "sessionKey",
  ] as const) {
    const f = fixture(policy);
    await f.gate.initialize();
    const pending = deferred<string | null>();
    let read = false;
    f.store.readMarker = () => {
      read = true;
      return pending.promise;
    };
    const first = f.gate.unlock(f.open);
    await until(() => read);
    f.setLive({ ...binding, [key]: "another" });
    pending.resolve(localUnlockMarker(policy));
    await first;
    assert.equal(f.gate.allows({ ...binding, [key]: "another" }), false, key);
    assert.equal(f.counts().serverOpens, 0, key);
  }
});

test("stale enable acknowledgements at each protected/policy await cannot enable another authority", async () => {
  for (const stage of [
    "clearMarker",
    "pending",
    "writeMarker",
    "readMarker",
    "enabled",
  ] as const) {
    const f = fixture();
    await f.gate.initialize();
    const paused = deferred<void>();
    let reached = false;
    if (stage === "pending" || stage === "enabled") {
      const original = f.store.writePolicy;
      f.store.writePolicy = async (value) => {
        if (value.state === stage) {
          reached = true;
          await paused.promise;
        }
        await original(value);
      };
    } else if (stage === "readMarker") {
      const original = f.store.readMarker;
      f.store.readMarker = async () => {
        reached = true;
        await paused.promise;
        return original();
      };
    } else {
      const original = f.store[stage];
      f.store[stage] = async (...args: [string?]) => {
        reached = true;
        await paused.promise;
        return (original as (...args: any[]) => Promise<void>)(...args);
      };
    }
    const first = f.gate.enable();
    await until(() => reached);
    f.gate.invalidate();
    f.setLive({ ...binding, userId: "foreign", sessionKey: "new" });
    const clearing = f.gate.reset();
    assert.equal(await f.gate.enable(), null);
    paused.resolve();
    await first;
    await clearing;
    assert.equal(f.persisted(), null, stage);
    assert.equal(f.marker(), null, stage);
    assert.equal(f.gate.allows(binding), false, stage);
    assert.equal(
      f.gate.allows({ ...binding, userId: "foreign", sessionKey: "new" }),
      false,
      stage,
    );
  }
});

test("reset waits for pending native acknowledgement, clears locally once and cannot publish a new unlock", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  const pending = deferred<string | null>();
  let read = false;
  f.store.readMarker = () => {
    read = true;
    return pending.promise;
  };
  const unlock = f.gate.unlock(f.open);
  await until(() => read);
  const clear = f.gate.reset();
  assert.equal(f.gate.reset(), clear);
  assert.equal(f.events.includes("all-clear"), false);
  assert.equal(await f.gate.unlock(f.open), null);
  pending.resolve(localUnlockMarker(policy));
  await unlock;
  await clear;
  assert.equal(f.events.filter((x) => x === "all-clear").length, 1);
  assert.equal(f.gate.required, false);
  assert.equal(f.gate.allows(binding), false);
});

test("unsupported optional biometric setup does not destroy an already revalidated normal session", async () => {
  const f = fixture();
  await f.gate.initialize();
  await f.gate.resume(f.open);
  f.store.supported = () => false;
  const before = [...f.events];
  assert.equal(await f.gate.enable(), null);
  assert.deepEqual(f.events, before);
  assert.equal(f.gate.allows(binding), true);
  assert.equal(f.persisted(), null);
});

test("malformed or foreign installation policies are fail-closed before protected reads or server restore", async () => {
  for (const input of [
    { ...policy, installationId: "foreign" },
    { ...policy, binding: { ...policy.binding, sessionId: "" } },
    { ...policy, unexpected: "PRIVATE" },
    { ...policy, state: "verified" },
    [],
    "PRIVATE",
    { ...policy, nonce: "../foreign" },
    { ...policy, nonce: `${nonce}\n` },
  ]) {
    const f = fixture(input);
    await f.gate.initialize();
    assert.equal(await f.gate.resume(f.open), null);
    assert.equal(f.gate.required, true);
    assert.equal(f.counts().serverOpens, 0);
    assert.equal(f.events.includes("biometric-read"), false);
    assert.equal(f.gate.getSnapshot().message.includes("PRIVATE"), false);
  }
});

test("known enabled policy cannot silently fall back to disabled when policy storage disappears", async () => {
  const f = fixture(policy);
  await f.gate.initialize();
  f.setPolicy(null);
  assert.equal(await f.gate.unlock(f.open), null);
  assert.equal(f.events.includes("biometric-read"), false);
  assert.equal(f.counts().serverOpens, 0);
  assert.equal(f.gate.required, true);
});

test("a pending interrupted setup never authenticates or refreshes on restart", async () => {
  const f = fixture({ ...policy, state: "pending" }, null);
  await f.gate.initialize();
  assert.equal(await f.gate.resume(f.open), null);
  assert.equal(await f.gate.unlock(f.open), null);
  assert.equal(f.events.includes("biometric-read"), false);
  assert.equal(f.counts().serverOpens, 0);
  assert.equal(f.gate.required, true);
});

test("resource purge and server read completions cannot unlock a later background epoch", async () => {
  for (const stage of ["purge", "server"] as const) {
    const f = fixture();
    await f.gate.initialize();
    const pending = deferred<void>();
    let reached = false;
    const gate =
      stage === "purge"
        ? createLocalUnlock(
            installationId,
            f.store,
            f.authority,
            async () => {
              reached = true;
              await pending.promise;
            },
            () => {},
          )
        : f.gate;
    if (gate !== f.gate) await gate.initialize();
    const first = gate.resume(async () => {
      reached = true;
      if (stage === "server") await pending.promise;
      return identity;
    });
    await until(() => reached);
    gate.visibility("background");
    gate.visibility("active");
    pending.resolve();
    await first;
    assert.equal(gate.allows(binding), false, stage);
  }
});

test("server revocation or changed restored session identity always defeats positive biometrics", async () => {
  for (const changed of [false, true]) {
    const f = fixture(policy, null);
    await f.gate.initialize();
    assert.equal(
      await f.gate.unlock(async () => {
        if (!changed) throw new Error("Synthetic revoked session");
        f.setLive({ ...binding, sessionId: "another-server-session" });
        return identity;
      }),
      null,
    );
    assert.equal(f.gate.allows(binding), false);
  }
});

test("policy parsing copies only the exact bounded principal/session binding", () => {
  const value = structuredClone(policy) as any;
  const parsed = parseLocalUnlockPolicy(value, installationId)!;
  value.binding.userId = "changed";
  assert.equal(parsed.binding.userId, "person");
  assert.equal(localUnlockMarker(parsed).includes("refresh"), false);
  assert.equal(localUnlockMarker(parsed).includes("access_token"), false);
});

test("composed real NativeSession cold restore reads refresh credential only after protected proof and retains exact server-session binding", async () => {
  const events: string[] = [];
  let saved = {
    refreshToken: "synthetic-refresh",
    sessionId: "server-session",
  };
  const grant = {
    ...identity,
    access_token: "synthetic-access",
    refresh_token: "synthetic-rotated",
    session_id: "server-session",
    expires_in: 300,
  };
  const session = new NativeSession(
    new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      { platform: "ios", version: "0.1.0" },
      async (url) => {
        if (url.endsWith("/logout")) {
          events.push("logout");
          return new Response(null, { status: 204 });
        }
        events.push(url.endsWith("/refresh") ? "refresh" : "me");
        return Response.json(url.endsWith("/refresh") ? grant : identity);
      },
    ),
    {
      async read() {
        events.push("credential-read");
        return saved;
      },
      async write(value) {
        saved = value;
      },
      async clear() {
        saved = null as any;
      },
    },
  );
  const f = fixture(policy, null);
  f.store.readMarker = async () => {
    events.push("protected-proof");
    return localUnlockMarker(policy);
  };
  const gate = createLocalUnlock(
    installationId,
    f.store,
    {
      current: () => session.localBinding,
      revalidate: () => session.revalidate(),
    },
    async () => {},
    () => {},
  );
  await gate.initialize();
  const open = async () => {
    if (!session.identity) await session.restore();
    return session.revalidate();
  };
  await gate.resume(open);
  assert.deepEqual(events, []);
  assert.deepEqual(await gate.unlock(open), identity);
  assert.deepEqual(events, [
    "protected-proof",
    "credential-read",
    "refresh",
    "me",
  ]);
  assert.equal(session.localBinding?.sessionId, "server-session");
  assert.equal(gate.allows(session.localBinding), true);
  const bindingCopy = session.localBinding!;
  Object.assign(bindingCopy, { sessionId: "tampered" });
  assert.equal(session.localBinding?.sessionId, "server-session");
  gate.invalidate();
  await session.signOut();
  assert.equal(session.localBinding, null);
  assert.equal(gate.allows(null), false);
});

test("real NativeSession refresh acknowledgement after sign-out cannot republish private UI or restore a cleared credential", async () => {
  let now = 0,
    saved: { refreshToken: string; sessionId: string } | null = null;
  const refresh = deferred<Response>();
  let refreshStarted = false;
  const revocations: string[] = [];
  const grant = {
    ...identity,
    access_token: "synthetic-access",
    refresh_token: "synthetic-original",
    session_id: "server-session",
    expires_in: 60,
  };
  let gate: ReturnType<typeof createLocalUnlock> | null = null;
  const session = new NativeSession(
    new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      { platform: "ios", version: "0.1.0" },
      async (url, init) => {
        if (url.endsWith("/token")) return Response.json(grant);
        if (url.endsWith("/refresh")) {
          refreshStarted = true;
          return refresh.promise;
        }
        if (url.endsWith("/logout")) {
          revocations.push(JSON.parse(String(init?.body)).refresh_token);
          return new Response(null, { status: 204 });
        }
        return Response.json(identity);
      },
    ),
    {
      async read() {
        return saved;
      },
      async write(value) {
        saved = value;
      },
      async clear() {
        saved = null;
      },
    },
    () => now,
    () => gate?.invalidate(),
  );
  await session.exchange({
    code: "c".repeat(43),
    code_verifier: "v".repeat(64),
    redirect_uri: "caseops://oauth/callback",
    platform: "android",
  });
  const f = fixture(policy);
  gate = createLocalUnlock(
    installationId,
    f.store,
    {
      current: () => session.localBinding,
      revalidate: () => session.revalidate(),
    },
    async () => {},
    () => {},
  );
  await gate.initialize();
  now = 70_000;
  const unlock = gate.unlock(() => session.revalidate());
  await until(() => refreshStarted);
  await session.signOut();
  refresh.resolve(
    Response.json({ ...grant, refresh_token: "synthetic-rotated" }),
  );
  assert.equal(await unlock, null);
  assert.equal(saved, null);
  assert.equal(session.localBinding, null);
  assert.equal(gate.allows(binding), false);
  assert.deepEqual(revocations, ["synthetic-original", "synthetic-rotated"]);
});
