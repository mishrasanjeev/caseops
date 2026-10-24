import { test } from "node:test";
import assert from "node:assert/strict";
import {
  checkedApiPath,
  checkedOrigin,
  JsonTransport,
  MobileApiError,
} from "./http.ts";

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
