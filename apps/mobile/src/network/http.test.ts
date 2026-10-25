import { test } from "node:test";
import assert from "node:assert/strict";
import {
  checkedApiPath,
  checkedOrigin,
  JsonTransport,
  MobileApiError,
  MAX_PRIVATE_BYTES,
  createExpoFetchAdapter,
} from "./http.ts";
import type { JsonFetch } from "./http.ts";

const expoFetchCompatible: typeof import("expo/fetch").fetch extends JsonFetch
  ? true
  : false = true;
test("installed Expo fetch signature is directly assignable to JsonFetch (type-only compatibility)", () => {
  assert.equal(expoFetchCompatible, true);
});
const expoAdapterCompatible: typeof import("expo/fetch").fetch extends Parameters<
  typeof createExpoFetchAdapter
>[0]
  ? true
  : false = true;
test("typed Expo adapter preserves auth/body/signal and omits unsupported native cache option without casts", async () => {
  assert.equal(expoAdapterCompatible, true);
  const signal = new AbortController().signal;
  let calls = 0;
  const adapter = createExpoFetchAdapter(async (url, init) => {
    calls++;
    assert.equal(url, "https://caseops.ai/api/auth/native/refresh");
    assert.equal(init.credentials, "omit");
    assert.equal(init.redirect, "error");
    assert.equal("cache" in init, false);
    assert.equal(init.signal, signal);
    assert.equal(init.body, "synthetic-body");
    const headers = new Headers(init.headers);
    assert.equal(headers.get("Authorization"), "Bearer fixture-token");
    assert.equal(headers.get("Cache-Control"), "no-store");
    assert.equal(headers.get("Pragma"), "no-cache");
    assert.equal(headers.get("X-CaseOps-Automated-Test"), "no-paid-providers");
    return Response.json({ ok: true });
  });
  await adapter("https://caseops.ai/api/auth/native/refresh", {
    method: "POST",
    body: "synthetic-body",
    signal,
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
    headers: {
      Authorization: "Bearer fixture-token",
      "X-CaseOps-Automated-Test": "no-paid-providers",
    },
  });
  assert.throws(() =>
    adapter("https://caseops.ai/api/auth/me", {
      credentials: "include",
      redirect: "follow",
    }),
  );
  assert.equal(calls, 1);
});

test("only HTTPS or local development origins are accepted", () => {
  assert.equal(
    checkedOrigin("https://caseops.ai", false),
    "https://caseops.ai",
  );
  assert.equal(
    checkedOrigin("http://10.0.2.2:8090", true),
    "http://10.0.2.2:8090",
  );
  for (const origin of [
    "http://caseops.ai",
    "https://user:password@caseops.ai",
    "https://caseops.ai/path",
    "https://caseops.ai?token=a",
    "https://caseops.ai#x",
    "javascript:alert(1)",
  ]) {
    assert.throws(() => checkedOrigin(origin, true));
  }
  assert.throws(() => checkedOrigin("http://localhost:8090", false));
});

test("API path cannot escape origin, realm or traversal", () => {
  assert.equal(checkedApiPath("/api/matters/?q=read"), "/api/matters/?q=read");
  for (const path of [
    "//attacker.test/api/x",
    "https://attacker.test/api/x",
    "/api/../secret",
    "/api/portal/matters",
    "/api/platform/reports",
    "/api\\example",
    "/api/x#secret",
    "/api/x\r\nCookie: a",
  ]) {
    assert.throws(() => checkedApiPath(path), path);
  }
});

test("request owns auth, omits cookies, refuses redirects and carries automated marker", async () => {
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (url, init) => {
      calls++;
      assert.equal(url, "https://caseops.ai/api/auth/me");
      assert.equal(init.credentials, "omit");
      assert.equal(init.redirect, "error");
      const headers = new Headers(init.headers);
      assert.equal(
        headers.get("X-CaseOps-Automated-Test"),
        "no-paid-providers",
      );
      assert.equal(headers.get("Authorization"), "Bearer fixture-token");
      return Response.json({ ok: true });
    },
  );
  assert.deepEqual(
    await transport.request("/api/auth/me", {}, "fixture-token"),
    { ok: true },
  );
  await assert.rejects(
    transport.request("/api/auth/me", {
      headers: { Authorization: "Bearer attacker" },
    }),
    /session owns/,
  );
  await assert.rejects(
    transport.request("/api/auth/me", {
      headers: { Cookie: "browser=another-principal" },
    }),
    /session owns/,
  );
  assert.equal(calls, 1);
});

test("human mode does not automatically assert an automated request", async () => {
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    false,
    async (_url, init) => {
      assert.equal(
        new Headers(init.headers).has("X-CaseOps-Automated-Test"),
        false,
      );
      return Response.json({ ok: true });
    },
  );
  await transport.request("/api/auth/me");
});

test("lost mutation acknowledgement is unknown with no retry", async () => {
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => {
      calls++;
      throw new Error("socket closed");
    },
  );
  await assert.rejects(
    transport.request("/api/matters/fixture/notes", {
      method: "POST",
      body: "{}",
    }),
    (error: unknown) =>
      error instanceof MobileApiError && error.outcome === "unknown",
  );
  assert.equal(calls, 1);
});

test("malformed successful mutation response is unknown, not saved", async () => {
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => new Response("not json", { status: 200 }),
  );
  await assert.rejects(
    transport.request("/api/matters/fixture/notes", {
      method: "POST",
      body: "{}",
    }),
    (error: unknown) =>
      error instanceof MobileApiError &&
      error.code === "invalid_response" &&
      error.outcome === "unknown",
  );
});

test("server denial is a rejection, not an unknown save", async () => {
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      Response.json({ detail: "Matter is disposed." }, { status: 409 }),
  );
  await assert.rejects(
    transport.request("/api/matters/fixture/notes", {
      method: "POST",
      body: "{}",
    }),
    (error: unknown) =>
      error instanceof MobileApiError &&
      error.status === 409 &&
      error.outcome === "rejected" &&
      error.message === "Matter is disposed.",
  );
});

test("pending reads abort under the transport deadline", async () => {
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener(
          "abort",
          () => reject(new Error("aborted")),
          { once: true },
        );
      }),
    15,
  );
  await assert.rejects(
    transport.request("/api/auth/me"),
    (error: unknown) =>
      error instanceof MobileApiError && error.code === "request_aborted",
  );
});

test("deadline remains active after headers during response body consumption", async () => {
  let headersReturned = false;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (_url, init) => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('{"unfinished":'));
          init.signal?.addEventListener(
            "abort",
            () => controller.error(new Error("body aborted")),
            { once: true },
          );
        },
      });
      headersReturned = true;
      return new Response(stream, { status: 200 });
    },
    15,
  );
  await assert.rejects(
    transport.request("/api/matters/a/notes", { method: "POST", body: "{}" }),
    (error: unknown) =>
      error instanceof MobileApiError &&
      error.code === "request_aborted" &&
      error.outcome === "unknown",
  );
  assert.equal(headersReturned, true);
});

const privatePath =
  "/api/matters/11111111-1111-4111-8111-111111111111/attachments/22222222-2222-4222-8222-222222222222/download";
function byteResponse(
  values = [new Uint8Array([1, 2, 3])],
  init: ResponseInit = {},
): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const value of values) controller.enqueue(value);
        controller.close();
      },
    }),
    {
      ...init,
      headers: {
        "Content-Type": "application/pdf",
        "Cache-Control": "private, no-store",
        ...init.headers,
      },
    },
  );
}
function byteError(code: string) {
  return (error: unknown) =>
    error instanceof MobileApiError &&
    error.code === code &&
    error.outcome === "rejected";
}

test("private bytes use injected GET-only native fetch, owned auth, no cookies/redirect/cache and authoritative automated marker", async () => {
  for (const automated of [false, true]) {
    const controller = new AbortController();
    const source = new Uint8Array([1, 2, 3]);
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      automated,
      async (url, init) => {
        assert.equal(url, `https://caseops.ai${privatePath}?inline=true`);
        assert.equal(init.method, "GET");
        assert.equal(init.body, undefined);
        assert.equal(init.credentials, "omit");
        assert.equal(init.redirect, "error");
        assert.equal(init.cache, "no-store");
        assert.equal(init.signal?.aborted, false);
        const headers = new Headers(init.headers);
        assert.equal(headers.get("Authorization"), "Bearer fixture-access");
        assert.equal(headers.has("Cookie"), false);
        assert.equal(headers.get("Cache-Control"), "no-store");
        assert.equal(
          headers.get("X-CaseOps-Automated-Test"),
          automated ? "no-paid-providers" : null,
        );
        assert.equal(headers.has("Range"), false);
        return byteResponse([source]);
      },
    );
    const value = await transport.requestBytes(
      `${privatePath}?inline=true`,
      { signal: controller.signal, maxBytes: 3 },
      "fixture-access",
    );
    assert.deepEqual(value, {
      bytes: new Uint8Array([1, 2, 3]),
      contentType: "application/pdf",
      status: 200,
      contentRange: null,
      cacheControl: "private, no-store",
    });
    assert.deepEqual(source, new Uint8Array(3));
    value.bytes.fill(0);
  }
});

test("private byte allowlist rejects non-UUID, escaped, cross-realm and altered download paths before any fetch", async () => {
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => {
      calls++;
      return byteResponse();
    },
  );
  for (const path of [
    "https://caseops.ai" + privatePath,
    "//attacker.test" + privatePath,
    privatePath + "/",
    privatePath + "?inline=false",
    privatePath + "?inline=true&inline=true",
    privatePath + "?inline=true&other=1",
    privatePath + "?inline=%74rue",
    privatePath + "#fragment",
    privatePath + "\n",
    privatePath.replace("/download", "/policy"),
    privatePath.replace("11111111-", "%311111111-"),
    privatePath.replace("/attachments/", "/attachments/../attachments/"),
    "/api/matters/fixture/attachments/fixture/download",
    "/api/portal/matters/fixture/download",
    privatePath.replace("attachments", "files"),
  ]) {
    await assert.rejects(
      transport.requestBytes(path, { maxBytes: 10 }, "fixture-access"),
    );
  }
  assert.equal(calls, 0);
});

test("private byte options reject caller headers/method/URL and invalid caps before transport; cap cannot exceed 50 MiB", async () => {
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => {
      calls++;
      return byteResponse([]);
    },
  );
  for (const maxBytes of [0, -1, 0.5, NaN, Infinity, MAX_PRIVATE_BYTES + 1])
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes }, "fixture-access"),
    );
  for (const extra of [
    { headers: { Cookie: "private" } },
    { method: "POST" },
    { url: "https://attacker.test" },
    { cache: "force-cache" },
  ]) {
    const options = { maxBytes: 10, ...extra };
    await assert.rejects(
      transport.requestBytes(privatePath, options, "fixture-access"),
    );
  }
  assert.equal(calls, 0);
  assert.equal(
    (
      await transport.requestBytes(
        privatePath,
        { maxBytes: MAX_PRIVATE_BYTES },
        "fixture-access",
      )
    ).bytes.length,
    0,
  );
  assert.equal(MAX_PRIVATE_BYTES, 52_428_800);
});

test("private stream counts each chunk before copying, rejects dishonest length/overflow and cancels/zeros abandoned bytes", async () => {
  for (const length of [null, "2"]) {
    let cancelled = 0;
    let signal: AbortSignal | null | undefined;
    const chunks = [new Uint8Array([4, 5]), new Uint8Array([6, 7])];
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async (_url, init) => {
        signal = init.signal;
        const headers = new Headers({ "Content-Type": "application/pdf" });
        if (length !== null) headers.set("Content-Length", length);
        return new Response(
          new ReadableStream({
            start(controller) {
              chunks.forEach((chunk) => controller.enqueue(chunk));
            },
            cancel() {
              cancelled++;
            },
          }),
          { headers },
        );
      },
    );
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes: 3 }, "fixture-access"),
      byteError("private_bytes_too_large"),
    );
    assert.equal(cancelled, 1);
    assert.equal(signal?.aborted, true);
    for (const chunk of chunks) assert.deepEqual(chunk, new Uint8Array(2));
  }
});

test("oversized/invalid declared lengths cancel before reading or allocating a private body", async () => {
  for (const length of ["4", "9007199254740992", "-1", "3.0", "garbage"]) {
    let reads = 0,
      cancelled = 0;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async () =>
        new Response(
          new ReadableStream(
            {
              pull() {
                reads++;
              },
              cancel() {
                cancelled++;
              },
            },
            { highWaterMark: 0 },
          ),
          {
            headers: {
              "Content-Type": "application/pdf",
              "Content-Length": length,
            },
          },
        ),
    );
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes: 3 }, "fixture-access"),
    );
    assert.equal(reads, 0);
    assert.equal(cancelled, 1);
  }
  const truncated = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      byteResponse([new Uint8Array([1])], {
        headers: { "Content-Length": "2" },
      }),
  );
  await assert.rejects(
    truncated.requestBytes(privatePath, { maxBytes: 3 }, "fixture-access"),
    byteError("invalid_byte_response"),
  );
});

test("one-byte range probe requires exact 206, bytes 0-0/positive-total and exactly one streamed byte", async () => {
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async (_url, init) => {
      assert.equal(new Headers(init.headers).get("Range"), "bytes=0-0");
      return byteResponse([new Uint8Array([9])], {
        status: 206,
        headers: { "Content-Range": "bytes 0-0/123456", "Content-Length": "1" },
      });
    },
  );
  const result = await transport.requestBytes(
    privatePath,
    { maxBytes: 1, rangeProbe: true },
    "fixture-access",
  );
  assert.equal(result.status, 206);
  assert.equal(result.contentRange, "bytes 0-0/123456");
  assert.deepEqual(result.bytes, new Uint8Array([9]));
  for (const range of [
    null,
    "bytes 0-1/10",
    "bytes 1-1/10",
    "bytes 0-0/*",
    "bytes 0-0/0",
    "bytes 0-0/9007199254740992",
    "items 0-0/10",
  ]) {
    const invalid = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async () =>
        byteResponse([new Uint8Array([1])], {
          status: 206,
          headers: range === null ? {} : { "Content-Range": range },
        }),
    );
    await assert.rejects(
      invalid.requestBytes(
        privatePath,
        { maxBytes: 5, rangeProbe: true },
        "fixture-access",
      ),
      byteError("invalid_byte_range"),
    );
  }
  for (const values of [[], [new Uint8Array([1, 2])]]) {
    const invalid = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async () =>
        byteResponse(values, {
          status: 206,
          headers: { "Content-Range": "bytes 0-0/10" },
        }),
    );
    await assert.rejects(
      invalid.requestBytes(
        privatePath,
        { maxBytes: 5, rangeProbe: true },
        "fixture-access",
      ),
    );
  }
  const ignored = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => byteResponse(),
  );
  await assert.rejects(
    ignored.requestBytes(
      privatePath,
      { maxBytes: 5, rangeProbe: true },
      "fixture-access",
    ),
    byteError("invalid_byte_response"),
  );
});

test("redirect status, redirected flag and changed same-origin source identity all cancel without accepting bytes", async () => {
  for (const redirect of ["status", "flag", "same-origin", "cross-origin"]) {
    let cancelled = 0;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async (_url, init) => {
        assert.equal(init.redirect, "error");
        const response = new Response(
          new ReadableStream({
            cancel() {
              cancelled++;
            },
          }),
          {
            status: redirect === "status" ? 302 : 200,
            headers: { "Content-Type": "application/pdf" },
          },
        );
        if (redirect === "flag")
          Object.defineProperty(response, "redirected", { value: true });
        if (redirect === "same-origin")
          Object.defineProperty(response, "url", {
            value: "https://caseops.ai/api/different-private-source",
          });
        if (redirect === "cross-origin")
          Object.defineProperty(response, "url", {
            value: "https://attacker.test/private",
          });
        return response;
      },
    );
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes: 10 }, "fixture-access"),
      byteError("unsafe_redirect"),
    );
    assert.equal(cancelled, 1);
  }
});

test("HTTP refusals never parse JSON/text/arrayBuffer error bodies or expose their private content", async () => {
  for (const status of [401, 403, 404, 429, 500]) {
    let cancelled = 0,
      consumed = 0;
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async () => {
        const response = new Response(
          new ReadableStream({
            cancel() {
              cancelled++;
            },
          }),
          { status },
        );
        response.json = async () => {
          consumed++;
          throw new Error("Private error body");
        };
        response.text = async () => {
          consumed++;
          throw new Error("Private error body");
        };
        response.arrayBuffer = async () => {
          consumed++;
          throw new Error("Private error body");
        };
        return response;
      },
    );
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes: 10 }, "fixture-access"),
      (error) =>
        error instanceof MobileApiError &&
        error.status === status &&
        !error.message.includes("Private error body"),
    );
    assert.equal(consumed, 0);
    assert.equal(cancelled, 1);
  }
});

test("private deadline includes body; cancelling a stalled reader cancels its stream and zeros consumed chunks", async () => {
  let cancelled = 0;
  const chunk = new Uint8Array([1, 2]);
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(chunk);
          },
          cancel() {
            cancelled++;
          },
        }),
        { headers: { "Content-Type": "application/pdf" } },
      ),
    10,
  );
  await assert.rejects(
    transport.requestBytes(privatePath, { maxBytes: 10 }, "fixture-access"),
    byteError("request_aborted"),
  );
  assert.equal(cancelled, 1);
  assert.deepEqual(chunk, new Uint8Array(2));
});

test("caller abort is bounded even for a fetcher ignoring its signal; late response is cancelled", async () => {
  let release!: (response: Response) => void;
  let cancelled = 0;
  const abort = new AbortController();
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  const rejection = assert.rejects(
    transport.requestBytes(
      privatePath,
      { maxBytes: 10, signal: abort.signal },
      "fixture-access",
    ),
    byteError("request_aborted"),
  );
  abort.abort();
  await rejection;
  release(
    new Response(
      new ReadableStream({
        cancel() {
          cancelled++;
        },
      }),
    ),
  );
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(cancelled, 1);
});

test("private pre-aborted requests never fetch and successful metadata remains literal rather than fabricated", async () => {
  const abort = new AbortController();
  abort.abort();
  let calls = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () => {
      calls++;
      return new Response(new Uint8Array([1]), {
        headers: { "Content-Type": "application/pdf" },
      });
    },
  );
  await assert.rejects(
    transport.requestBytes(
      privatePath,
      { maxBytes: 1, signal: abort.signal },
      "fixture-access",
    ),
    byteError("request_aborted"),
  );
  assert.equal(calls, 0);
  const result = await transport.requestBytes(
    privatePath,
    { maxBytes: 1 },
    "fixture-access",
  );
  assert.equal(result.cacheControl, null);
  assert.equal(result.contentRange, null);
});

test("private cap and range mode are snapshotted before asynchronous fetch returns", async () => {
  let release!: (response: Response) => void;
  const options = { maxBytes: 1, rangeProbe: false };
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  const rejection = assert.rejects(
    transport.requestBytes(privatePath, options, "fixture-access"),
    byteError("private_bytes_too_large"),
  );
  options.maxBytes = MAX_PRIVATE_BYTES;
  options.rangeProbe = true;
  release(byteResponse([new Uint8Array([1, 2])]));
  await rejection;
});

test("tiny/empty stream chunks do not create an unbounded retained chunk inventory or corrupt output", async () => {
  let offset = 0;
  const transport = new JsonTransport(
    "https://caseops.ai",
    false,
    true,
    async () =>
      new Response(
        new ReadableStream({
          pull(controller) {
            if (offset === 10_000) {
              controller.close();
              return;
            }
            controller.enqueue(new Uint8Array(0));
            controller.enqueue(new Uint8Array([offset++ % 251]));
          },
        }),
        { headers: { "Content-Type": "application/pdf" } },
      ),
  );
  const result = await transport.requestBytes(
    privatePath,
    { maxBytes: 10_000 },
    "fixture-access",
  );
  assert.equal(result.bytes.length, 10_000);
  for (let i = 0; i < result.bytes.length; i++)
    assert.equal(result.bytes[i], i % 251);
});

test("missing body/type and unexpected partial responses fail closed without falling back to unbounded consumers", async () => {
  for (const response of [
    new Response(null),
    new Response(new Uint8Array([1])),
    byteResponse([new Uint8Array([1])], { status: 206 }),
    byteResponse([new Uint8Array([1])], {
      headers: { "Content-Range": "bytes 0-0/10" },
    }),
  ]) {
    const transport = new JsonTransport(
      "https://caseops.ai",
      false,
      true,
      async () => response,
    );
    await assert.rejects(
      transport.requestBytes(privatePath, { maxBytes: 10 }, "fixture-access"),
    );
  }
});
