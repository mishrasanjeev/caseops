import { test } from "node:test";
import assert from "node:assert/strict";
import { NativeSession } from "../auth/session.ts";
import type { NativeGrant, StoredCredential } from "../auth/types.ts";
import { JsonTransport, MobileApiError } from "../network/http.ts";
import { ContractError } from "./contracts.ts";
import { readFailure } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";
import {
  createDeviceSessionRevocation,
  createDeviceSessionsRepository,
  decodeDeviceSession,
  decodeDeviceSessions,
  deviceSessionInstant,
  MAX_DEVICE_SESSIONS,
} from "./device-sessions.ts";
import type { DeviceSession } from "./device-sessions.ts";

// Exact NativeSessionRecord fields, not a token-grant or browser-session DTO.
const current: DeviceSession = {
  id: "f1a272e3-436e-4b21-a96f-762789b862a2",
  platform: "android",
  created_at: "2026-10-24T10:00:00Z",
  last_used_at: "2026-10-25T11:30:00.123456Z",
  expires_at: "2026-11-23T10:00:00+00:00",
  revoked_at: null,
  current: true,
};
const other: DeviceSession = {
  ...current,
  id: "51ad2540-e375-4705-a606-031b39a3a5b8",
  platform: "ios",
  current: false,
};
function setup(
  handler: (
    path: string,
    init?: RequestInit,
  ) => unknown | Promise<unknown> = () => undefined,
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ): Promise<T> => {
    calls.push({ path, init });
    return (await handler(path, init)) as T;
  };
  return { calls, repository: createDeviceSessionsRepository(request) };
}

test("MOB-04 canonical sessions retain exact order, identities, platform, nullable revoke and server current flag", () => {
  assert.deepEqual(decodeDeviceSessions({ sessions: [other, current] }), [
    other,
    current,
  ]);
  assert.deepEqual(
    decodeDeviceSession({ ...other, revoked_at: "2026-10-25T12:00:00Z" })
      .revoked_at,
    "2026-10-25T12:00:00Z",
  );
});
test("empty and all-noncurrent canonical responses do not invent a current session", () => {
  assert.deepEqual(decodeDeviceSessions({ sessions: [] }), []);
  assert.equal(decodeDeviceSessions({ sessions: [other] })[0].current, false);
});
test("unknown additive fields including secrets and device metadata are discarded recursively", () => {
  const decoded = decodeDeviceSessions({
    access_token: "synthetic-secret",
    sessions: [
      {
        ...current,
        refresh_token: "synthetic-secret",
        device: { ip: "private-address" },
        user_agent: "private-agent",
      },
    ],
  });
  assert.deepEqual(decoded, [current]);
  assert.doesNotMatch(
    JSON.stringify(decoded),
    /synthetic-secret|private-address|private-agent/,
  );
});
for (const field of Object.keys(current)) {
  test(`required session field ${field} cannot silently disappear`, () => {
    const fixture: Record<string, unknown> = { ...current };
    delete fixture[field];
    assert.throws(
      () => decodeDeviceSessions({ sessions: [fixture] }),
      ContractError,
    );
  });
}
const invalid: Record<string, unknown>[] = [
  { id: null },
  { id: "" },
  { id: " " },
  { id: " leading" },
  { id: "bad\nidentity" },
  { id: "." },
  { id: ".." },
  { id: "x".repeat(201) },
  { id: 42 },
  { platform: "web" },
  { platform: "Android" },
  { platform: null },
  { current: "false" },
  { current: 1 },
  { current: null },
  { created_at: "2026-02-30T00:00:00Z" },
  { created_at: "2026-10-25" },
  { last_used_at: "2026-10-25T24:00:00Z" },
  { expires_at: "2026-10-25T00:60:00Z" },
  { revoked_at: false },
  { revoked_at: "2026-10-25T00:00:00+24:00" },
  { expires_at: 1792922400 },
  { expires_at: "not-a-timestamp" },
];
for (const [index, patch] of invalid.entries()) {
  test(`strict native record rejects malformed canonical field case ${index + 1}`, () => {
    assert.throws(
      () => decodeDeviceSession({ ...current, ...patch }),
      ContractError,
    );
  });
}
for (const [index, fixture] of [
  null,
  [],
  {},
  { sessions: null },
  { sessions: {} },
  { sessions: [current, {}] },
  { sessions: [null] },
].entries()) {
  test(`malformed list case ${index + 1} fails closed rather than empty or partial success`, () => {
    assert.throws(() => decodeDeviceSessions(fixture), ContractError);
  });
}
test("twenty sessions are accepted without truncation; twenty-one are rejected", () => {
  const sessions = Array.from({ length: MAX_DEVICE_SESSIONS }, (_, index) => ({
    ...other,
    id: `session-${index}`,
  }));
  assert.equal(MAX_DEVICE_SESSIONS, 20);
  assert.deepEqual(decodeDeviceSessions({ sessions }), sessions);
  assert.throws(
    () => decodeDeviceSessions({ sessions: [...sessions, current] }),
    ContractError,
  );
});
test("duplicate identities, conflicting current flags and unsupported continuation fail closed", () => {
  for (const sessions of [
    [other, other],
    [current, { ...other, current: true }],
  ])
    assert.throws(() => decodeDeviceSessions({ sessions }), ContractError);
  assert.throws(
    () => decodeDeviceSessions({ sessions: [current], next_cursor: "more" }),
    ContractError,
  );
});
test("SQLite UTC-naive and PostgreSQL offset/microsecond timestamps represent the same instant", () => {
  const utc = deviceSessionInstant("2026-10-25T10:00:00.123456Z");
  assert.equal(deviceSessionInstant("2026-10-25T10:00:00.123456"), utc);
  assert.equal(deviceSessionInstant("2026-10-25T15:30:00.123456+05:30"), utc);
  assert.equal(
    deviceSessionInstant("2024-02-29T00:00:00Z"),
    Date.UTC(2024, 1, 29),
  );
});
test("decoder errors never echo server-provided values", () => {
  assert.throws(
    () => decodeDeviceSession({ ...current, platform: "synthetic-secret" }),
    (error: unknown) => {
      assert.ok(error instanceof ContractError);
      assert.doesNotMatch(error.message, /synthetic-secret/);
      return true;
    },
  );
});
test("repository uses the exact bounded GET without invented pagination or identity parameters and forwards abort", async () => {
  const { repository, calls } = setup(() => ({ sessions: [other, current] }));
  const controller = new AbortController();
  assert.deepEqual(await repository.list(controller.signal), [other, current]);
  assert.deepEqual(calls, [
    {
      path: "/api/auth/native/sessions",
      init: { method: "GET", signal: controller.signal },
    },
  ]);
});
test("repository propagates malformed reads and aborted reads without retry or cached data", async () => {
  const malformed = setup(() => ({
    sessions: [{ ...current, current: "true" }],
  }));
  await assert.rejects(malformed.repository.list(), ContractError);
  assert.equal(malformed.calls.length, 1);
  const controller = new AbortController();
  controller.abort();
  const aborted = setup((_path, init) => {
    init?.signal?.throwIfAborted();
  });
  await assert.rejects(aborted.repository.list(controller.signal), {
    name: "AbortError",
  });
  assert.equal(aborted.calls.length, 1);
});
test("read failures remain error states with sanitized copy, never empty sessions", async () => {
  for (const error of [
    new MobileApiError("synthetic-secret", 403, "denied"),
    new TypeError("synthetic-secret"),
    new ContractError("device sessions"),
  ]) {
    const { repository, calls } = setup(() => {
      throw error;
    });
    await assert.rejects(
      repository.list(),
      (actual: unknown) => actual === error,
    );
    assert.doesNotMatch(JSON.stringify(readFailure(error)), /synthetic-secret/);
    assert.equal(calls.length, 1);
  }
});
test("DELETE encodes the exact opaque server identity, sends no body and expects the 204 acknowledgement", async () => {
  const { repository, calls } = setup();
  await repository.revoke("opaque/id?query#fragment");
  assert.deepEqual(calls, [
    {
      path: "/api/auth/native/sessions/opaque%2Fid%3Fquery%23fragment",
      init: { method: "DELETE" },
    },
  ]);
});
test("invalid revoke identity is rejected before transport", async () => {
  const { repository, calls } = setup();
  for (const id of ["", " ", ".", "..", "x".repeat(201)])
    await assert.rejects(repository.revoke(id), ContractError);
  assert.equal(calls.length, 0);
});
test("confirmation creates no request before invocation and repeated invocation owns one DELETE", async () => {
  let finish!: () => void;
  const { repository, calls } = setup(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  let purges = 0;
  const confirm = createDeviceSessionRevocation(repository, other, async () => {
    purges++;
  });
  assert.equal(calls.length, 0);
  const first = confirm();
  assert.equal(confirm(), first);
  finish();
  assert.deepEqual(await first, {
    state: "revoked",
    current: false,
    signOutFailed: false,
    message: "Session revoked.",
  });
  assert.equal((await confirm()).state, "revoked");
  assert.equal(calls.length, 1);
  assert.equal(purges, 0);
});
test("current-session notification runs once only after DELETE is acknowledged", async () => {
  const sequence: string[] = [];
  const { repository } = setup(async () => {
    sequence.push("delete");
  });
  const confirm = createDeviceSessionRevocation(
    repository,
    current,
    async () => {
      sequence.push("purge");
    },
  );
  const result = await confirm();
  await confirm();
  assert.deepEqual(sequence, ["delete", "purge"]);
  assert.equal(result.state, "revoked");
  assert.equal(result.current, true);
});
test("confirmation captures a decoded identity/current snapshot, not a mutable row or list position", async () => {
  const target = { ...current };
  const { repository, calls } = setup();
  let purges = 0;
  const confirm = createDeviceSessionRevocation(
    repository,
    target,
    async () => {
      purges++;
    },
  );
  target.id = other.id;
  target.current = false;
  await confirm();
  assert.equal(calls[0].path, `/api/auth/native/sessions/${current.id}`);
  assert.equal(purges, 1);
});
for (const status of [400, 401, 403, 404, 409, 429]) {
  test(`HTTP ${status} rejection does not revoke another session, purge or retry`, async () => {
    const { repository, calls } = setup(() => {
      throw new MobileApiError("synthetic-secret", status, "synthetic-denial");
    });
    let purges = 0;
    const confirm = createDeviceSessionRevocation(
      repository,
      current,
      async () => {
        purges++;
      },
    );
    const result = await confirm();
    assert.equal(result.state, "rejected");
    assert.doesNotMatch(result.message, /synthetic-secret/);
    await confirm();
    assert.equal(calls.length, 1);
    assert.equal(purges, 0);
  });
}
for (const [index, error] of [
  new TypeError("synthetic-secret"),
  new MobileApiError("synthetic-secret", 0, "network_error", "unknown"),
  new MobileApiError("synthetic-secret", 500, "server_error"),
  new MobileApiError("synthetic-secret", 403, "invalid_response", "unknown"),
].entries()) {
  test(`uncertain revoke case ${index + 1} stays unknown and requires reload without replay`, async () => {
    const { repository, calls } = setup(() => {
      throw error;
    });
    let purges = 0;
    const confirm = createDeviceSessionRevocation(
      repository,
      other,
      async () => {
        purges++;
      },
    );
    const result = await confirm();
    assert.equal(result.state, "unknown");
    assert.match(result.message, /Reload sessions/);
    assert.doesNotMatch(result.message, /synthetic-secret/);
    await confirm();
    assert.equal(calls.length, 1);
    assert.equal(purges, 0);
  });
}
test("uncertain self-revocation still notifies parent to fail closed locally, once", async () => {
  const { repository, calls } = setup(() => {
    throw new MobileApiError("lost receipt", 0, "network_error", "unknown");
  });
  let purges = 0;
  const confirm = createDeviceSessionRevocation(
    repository,
    current,
    async () => {
      purges++;
    },
  );
  assert.equal((await confirm()).state, "unknown");
  await confirm();
  assert.equal(purges, 1);
  assert.equal(calls.length, 1);
});
test("malformed successful acknowledgement is unknown, never a revoked success", async () => {
  for (const value of [null, {}, { revoked: true }, "success"]) {
    const { repository, calls } = setup(() => value);
    const result = await createDeviceSessionRevocation(
      repository,
      other,
      async () => assert.fail("must not purge sibling"),
    )();
    assert.equal(result.state, "unknown");
    assert.equal(calls.length, 1);
  }
});
test("parent purge failure preserves known server revocation and never retries DELETE", async () => {
  const { repository, calls } = setup();
  const confirm = createDeviceSessionRevocation(
    repository,
    current,
    async () => {
      throw new Error("synthetic-secret");
    },
  );
  const result = await confirm();
  assert.equal(result.state, "revoked");
  assert.equal(result.signOutFailed, true);
  assert.match(result.message, /Sign out again/);
  assert.doesNotMatch(result.message, /synthetic-secret/);
  await confirm();
  assert.equal(calls.length, 1);
});
test("MOB-04/05 real NativeSession/JsonTransport integration purges current authority and credentials using offline transport only", async () => {
  const grant: NativeGrant = {
    access_token: "synthetic-access",
    refresh_token: "synthetic-refresh",
    session_id: current.id,
    expires_in: 300,
    company: {
      id: "company-test",
      name: "Synthetic Legal",
      slug: "synthetic-legal",
    },
    user: {
      id: "user-test",
      email: "user@example.test",
      full_name: "Synthetic User",
    },
    membership: { id: "membership-test", role: "owner" },
    capabilities: [],
  };
  let credential: StoredCredential | null = null;
  let invalidations = 0;
  const calls: { url: string; init: RequestInit }[] = [];
  const transport = new JsonTransport(
    "https://caseops.invalid",
    false,
    true,
    { platform: "ios", version: "0.1.0" },
    async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith("/token")) return Response.json(grant);
      if (url.endsWith("/sessions") && init.method === "GET")
        return Response.json({ sessions: [other, current] });
      if (url.endsWith(`/sessions/${current.id}`) && init.method === "DELETE")
        return new Response(null, { status: 204 });
      if (url.endsWith("/logout")) return new Response(null, { status: 204 });
      assert.fail("Unexpected offline transport request");
    },
  );
  const native = new NativeSession(
    transport,
    {
      read: async () => credential,
      write: async (value) => {
        credential = value;
      },
      clear: async () => {
        credential = null;
      },
    },
    Date.now,
    () => {
      invalidations++;
    },
  );
  await native.exchange({
    code: "c".repeat(43),
    code_verifier: "v".repeat(64),
    redirect_uri: "caseops://oauth/callback",
    platform: "android",
  });
  const repository = createDeviceSessionsRepository(
    native.request.bind(native),
  );
  const sessions = await repository.list();
  assert.deepEqual(sessions, [other, current]);
  assert.ok(credential);
  const result = await createDeviceSessionRevocation(
    repository,
    sessions[1],
    () => native.signOut(),
  )();
  assert.equal(result.state, "revoked");
  assert.equal(result.signOutFailed, false);
  assert.equal(credential, null);
  assert.equal(native.identity, null);
  assert.equal(invalidations, 1);
  assert.deepEqual(
    calls.map(({ url }) => new URL(url).pathname),
    [
      "/api/auth/native/token",
      "/api/auth/native/sessions",
      `/api/auth/native/sessions/${current.id}`,
      "/api/auth/native/logout",
    ],
  );
  for (const { init } of calls) {
    const headers = new Headers(init.headers);
    assert.equal(headers.get("X-CaseOps-Automated-Test"), "no-paid-providers");
    assert.equal(headers.has("Cookie"), false);
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
  }
  assert.equal(
    new Headers(calls[1].init.headers).get("Authorization"),
    "Bearer synthetic-access",
  );
  assert.equal(calls[2].init.body, undefined);
  assert.equal(new Headers(calls[3].init.headers).has("Authorization"), false);
});
