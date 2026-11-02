import { test } from "node:test";
import assert from "node:assert/strict";
import { JsonTransport } from "../network/http.ts";
import type { AuthorizedRequest } from "../domain/repository.ts";
import { createMatterFilesApi, nativeMultipart } from "./api.ts";
import type { NativeFilePart } from "./api.ts";
import {
  attachmentFixture,
  bytes,
  filesWorkspaceFixture,
  hash,
  scope,
} from "./test-fixtures.ts";

test("MOB-22 native multipart appends one Expo File-like body and the observed lifecycle version", async () => {
  const calls: {
    name: string;
    value:
      | { name: string; type: string; bytes: () => Promise<Uint8Array> }
      | string;
  }[] = [];
  const original = globalThis.FormData;
  class NativeFormDataFixture {
    append(
      name: string,
      value:
        | { name: string; type: string; bytes: () => Promise<Uint8Array> }
        | string,
    ) {
      calls.push({ name, value });
    }
  }
  globalThis.FormData = NativeFormDataFixture as unknown as typeof FormData;
  try {
    const part = {
      uri: "file:///synthetic-cache/owned.txt",
      name: "synthetic.txt",
      type: "text/plain",
    };
    const body = nativeMultipart(part, 7, async () => bytes, bytes.length);
    assert.ok(body instanceof NativeFormDataFixture);
    assert.equal(calls[0].name, "file");
    const sent = calls[0].value as {
      name: string;
      type: string;
      bytes: () => Promise<Uint8Array>;
    };
    assert.equal(sent.name, part.name);
    assert.equal(sent.type, part.type);
    assert.equal(Object.hasOwn(sent, "uri"), false);
    assert.deepEqual(await sent.bytes(), bytes);
    assert.deepEqual(calls[1], {
      name: "expected_lifecycle_version",
      value: "7",
    });
  } finally {
    globalThis.FormData = original;
  }
});

test("MOB-22 exact redirect-free parent paths, one multipart file, canonical response, no invented fields", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  const part = {
    uri: "file:///synthetic-cache/owned.txt",
    name: "synthetic.txt",
    type: "text/plain",
  };
  let receivedPart: NativeFilePart | undefined;
  let receivedVersion: number | undefined;
  const body = new FormData();
  const request: AuthorizedRequest = async <T>(
    path: string,
    init?: RequestInit,
  ) => {
    calls.push({ path, init });
    return (
      init?.method === "POST" ? attachmentFixture() : filesWorkspaceFixture()
    ) as T;
  };
  const api = createMatterFilesApi(request, scope, (value, version) => {
    receivedPart = value;
    receivedVersion = version;
    return body;
  });
  const signal = new AbortController().signal;
  await api.workspace(signal);
  await api.upload(
    { part, sha256: hash, size: bytes.length, dispose() {} },
    7,
    signal,
  );
  assert.deepEqual(
    calls.map((call) => call.path),
    [
      "/api/matters/matter-test/workspace",
      "/api/matters/matter-test/attachments",
    ],
  );
  assert.equal(receivedPart, part);
  assert.equal(receivedVersion, 7);
  assert.equal(calls[1].init?.body, body);
  assert.equal(calls[1].init?.signal, signal);
  assert.equal(calls[1].init?.headers, undefined);
  assert.deepEqual(Object.keys(calls[1].init!).sort(), [
    "body",
    "method",
    "signal",
  ]);
});

test("MOB-22 existing session JSON transport forwards multipart unchanged with native/no-paid/no-store/auth fences", async () => {
  const body = new FormData();
  body.append(
    "file",
    new Blob([bytes], { type: "text/plain" }),
    "synthetic.txt",
  );
  body.append("expected_lifecycle_version", "0");
  let count = 0;
  const transport = new JsonTransport(
    "http://127.0.0.1:8000",
    true,
    true,
    { platform: "ios", version: "0.1.0" },
    async (url, init) => {
      count++;
      assert.equal(
        url,
        "http://127.0.0.1:8000/api/matters/matter-test/attachments",
      );
      assert.equal(init.body, body);
      const headers = new Headers(init.headers);
      assert.equal(headers.has("Content-Type"), false);
      assert.equal(headers.get("Authorization"), "Bearer synthetic-token");
      assert.equal(
        headers.get("X-CaseOps-Automated-Test"),
        "no-paid-providers",
      );
      assert.equal(headers.get("Cache-Control"), "no-store");
      assert.equal(init.credentials, "omit");
      assert.equal(init.redirect, "error");
      return Response.json(attachmentFixture());
    },
  );
  const request: AuthorizedRequest = (path, init) =>
    transport.request(path, init, "synthetic-token");
  const api = createMatterFilesApi(request, scope, () => body);
  const saved = await api.upload(
    {
      part: {
        uri: "file:///synthetic-cache/owned.txt",
        name: "synthetic.txt",
        type: "text/plain",
      },
      sha256: hash,
      size: bytes.length,
      dispose() {},
    },
    0,
    new AbortController().signal,
  );
  assert.equal(saved.sha256_hex, hash);
  assert.equal(count, 1);
});

test("MOB-23 invalid lifecycle versions never build multipart or send a request", async () => {
  let requests = 0,
    builds = 0;
  const request: AuthorizedRequest = async <T>() => {
    requests++;
    return attachmentFixture() as T;
  };
  const api = createMatterFilesApi(request, scope, () => {
    builds++;
    return new FormData();
  });
  const file = {
    part: {
      uri: "file:///synthetic.txt",
      name: "synthetic.txt",
      type: "text/plain",
    },
    size: bytes.length,
    sha256: hash,
    dispose() {},
  };
  for (const version of [
    -1,
    1.5,
    NaN,
    Infinity,
    Number.MAX_SAFE_INTEGER + 1,
    undefined,
    "0",
  ]) {
    await assert.rejects(() =>
      api.upload(file, version as number, new AbortController().signal),
    );
    assert.throws(() => nativeMultipart(file.part, version as number));
  }
  assert.equal(requests, 0);
  assert.equal(builds, 0);
});

test("MOB-21 identities are path encoded and unsupported response aliases fail closed", async () => {
  let path = "";
  const request: AuthorizedRequest = async <T>(value: string) => {
    path = value;
    return filesWorkspaceFixture({
      matter: { ...filesWorkspaceFixture().matter, id: "matter/a?b" },
    }) as T;
  };
  await createMatterFilesApi(request, {
    ...scope,
    matterId: "matter/a?b",
  }).workspace();
  assert.equal(path, "/api/matters/matter%2Fa%3Fb/workspace");
  assert.throws(() =>
    createMatterFilesApi(request, { ...scope, sessionKey: "" }),
  );
});
