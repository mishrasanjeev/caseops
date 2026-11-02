import test from "node:test";
import assert from "node:assert/strict";
import { PrivateViewerController } from "./controller.ts";
import { VIEWER_LIMITS } from "./contracts.ts";
import {
  deferred,
  fixture,
  pdfBytes,
  settle,
  source,
} from "./test-fixtures.ts";

test("native-viewer controller: hash, exact bytes and two current-access probes precede render", async () => {
  const f = fixture();
  await f.controller.open();
  assert.equal(f.controller.getSnapshot().phase, "ready");
  assert.deepEqual(f.calls, [
    "metadata",
    "probe:/api/matters/matter-1/attachments/file-1/download?inline=true",
    "body:/api/matters/matter-1/attachments/file-1/download?inline=true",
    "hash",
    "metadata",
    "probe:/api/matters/matter-1/attachments/file-1/download?inline=true",
  ]);
  const copy = f.controller.copyContent()!;
  assert.deepEqual(copy.bytes, pdfBytes);
  copy.bytes.fill(0);
  assert.deepEqual(f.controller.copyContent()!.bytes, pdfBytes);
  f.controller.dispose();
  assert.ok(f.issued.every((bytes) => bytes.every((byte) => byte === 0)));
  assert.ok(f.isUnsubscribed());
});
test("native-viewer controller: clears before renewal and waits for native removal acknowledgement", async () => {
  const f = fixture();
  await f.controller.open();
  f.calls.length = 0;
  f.clock.advance(VIEWER_LIMITS.leaseMs);
  await settle();
  assert.equal(f.controller.getSnapshot().phase, "renewing");
  assert.equal(f.controller.copyContent(), null);
  assert.deepEqual(f.calls, ["clear-visible"]);
  f.clear.resolve();
  await settle();
  assert.equal(f.controller.getSnapshot().phase, "ready");
  assert.deepEqual(f.calls, [
    "clear-visible",
    "metadata",
    "probe:/api/matters/matter-1/attachments/file-1/download?inline=true",
  ]);
  f.controller.dispose();
});
test("native-viewer controller: absent display fence refuses lease refresh without network", async () => {
  const f = fixture();
  const controller = new PrivateViewerController(source, f.ports, f.clock);
  await controller.open();
  f.calls.length = 0;
  f.clock.advance(VIEWER_LIMITS.leaseMs);
  await settle();
  assert.equal(controller.getSnapshot().phase, "blocked");
  assert.deepEqual(f.calls, []);
  controller.dispose();
  f.controller.dispose();
});
for (const reason of [
  "background",
  "logout",
  "revoked",
  "source-changed",
  "closed",
] as const) {
  test(`native-viewer controller: ${reason} synchronously removes content and wipes owned byte arrays`, async () => {
    const f = fixture();
    await f.controller.open();
    f.invalidate(reason);
    assert.equal(f.controller.copyContent(), null);
    assert.ok(f.issued.every((bytes) => bytes.every((byte) => byte === 0)));
    f.calls.length = 0;
    f.clock.advance(30_000);
    await settle();
    assert.deepEqual(f.calls, []);
    f.controller.dispose();
  });
}
test("native-viewer controller: source change after transfer rejects late bytes without render", async () => {
  let reads = 0;
  const f = fixture({
    revalidate: async () =>
      ++reads === 1 ? source : { ...source, sha256: "b".repeat(64) },
  });
  await f.controller.open();
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  assert.equal(f.controller.copyContent(), null);
  assert.ok(f.issued.every((bytes) => bytes.every((byte) => byte === 0)));
  f.controller.dispose();
});
test("native-viewer controller: denial during renewal wipes retained source, no automatic retry", async () => {
  let denied = false;
  const f = fixture({
    revalidate: async () => {
      if (denied)
        throw Object.assign(new Error("private error"), { status: 403 });
      return source;
    },
  });
  await f.controller.open();
  denied = true;
  f.clock.advance(15_000);
  f.clear.resolve();
  await settle();
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  assert.doesNotMatch(f.controller.getSnapshot().message, /private error/);
  assert.ok(f.issued.every((bytes) => bytes.every((byte) => byte === 0)));
  f.controller.dispose();
});
test("native-viewer controller: purge while bytes are in flight aborts and discards late transport", async () => {
  const pending =
    deferred<
      Awaited<ReturnType<ReturnType<typeof fixture>["ports"]["requestBytes"]>>
    >();
  const f = fixture();
  const original = f.ports.requestBytes;
  let signal: AbortSignal | undefined;
  f.ports.requestBytes = (path, options) => {
    if (options.rangeProbe) return original(path, options);
    signal = options.signal;
    return pending.promise;
  };
  const opening = f.controller.open();
  await settle();
  f.invalidate("logout");
  assert.equal(signal?.aborted, true);
  const bytes = pdfBytes.slice();
  pending.resolve({
    bytes,
    status: 200,
    contentType: "application/pdf",
    contentRange: null,
    cacheControl: "no-store",
  });
  await opening;
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  assert.ok(bytes.every((byte) => byte === 0));
  f.controller.dispose();
});
test("native-viewer controller: hard deadline rejects an abort-ignoring metadata port", async () => {
  const pending = deferred<typeof source>();
  const f = fixture({ revalidate: () => pending.promise });
  const opening = f.controller.open();
  f.clock.advance(15_000);
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  pending.resolve(source);
  await opening;
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  assert.deepEqual(f.calls, []);
  f.controller.dispose();
});
for (const alteration of [
  "status",
  "range",
  "size",
  "mime",
  "cache",
] as const) {
  test(`native-viewer controller: invalid ${alteration} range proof fails before body request`, async () => {
    const f = fixture();
    const original = f.ports.requestBytes;
    f.ports.requestBytes = async (path, options) => {
      const reply = await original(path, options);
      if (alteration === "status") reply.status = 200;
      if (alteration === "range") reply.contentRange = "bytes 0-0/999";
      if (alteration === "size") reply.bytes = new Uint8Array([1, 2]);
      if (alteration === "mime") reply.contentType = "text/html";
      if (alteration === "cache") reply.cacheControl = null;
      return reply;
    };
    await f.controller.open();
    assert.equal(f.controller.getSnapshot().phase, "blocked");
    assert.equal(
      f.calls.some((call) => call.startsWith("body")),
      false,
    );
    f.controller.dispose();
  });
}
test("native-viewer controller: payload hash mismatch blocks without weakening source identity", async () => {
  const f = fixture({ sha256: async () => "c".repeat(64) });
  await f.controller.open();
  assert.equal(f.controller.getSnapshot().phase, "blocked");
  assert.equal(f.controller.copyContent(), null);
  f.controller.dispose();
});
test("native-viewer controller: unsupported type and over-limit sources do not request bytes", async () => {
  for (const input of [
    { ...source, filename: "a.doc", contentType: "application/msword" },
    { ...source, sizeBytes: VIEWER_LIMITS.maxBytes + 1 },
  ]) {
    const f = fixture({}, input);
    await f.controller.open();
    assert.equal(f.controller.getSnapshot().phase, "unsupported");
    assert.deepEqual(f.calls, []);
    f.controller.dispose();
  }
});
test("native-viewer controller: optional DOCX uses real preview JSON port, never bytes-port preview URL", async () => {
  const docx = {
    ...source,
    filename: "a.docx",
    contentType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };
  const unavailable = fixture({}, docx);
  await unavailable.controller.open();
  assert.equal(unavailable.controller.getSnapshot().phase, "unsupported");
  unavailable.controller.dispose();
  const f = fixture(
    {
      requestDocxPreview: async (path) => {
        assert.equal(path, "/api/matters/matter-1/attachments/file-1/preview");
        return {
          cacheControl: "private, no-store",
          value: {
            attachment_id: docx.attachmentId,
            filename: docx.filename,
            content_type: docx.contentType,
            paragraphs: ["Actual extracted paragraph"],
            table_rows: [["Actual cell"]],
          },
        };
      },
    },
    docx,
  );
  await f.controller.open();
  assert.equal(f.controller.getSnapshot().phase, "ready");
  assert.match(
    new TextDecoder().decode(f.controller.copyContent()!.bytes),
    /Actual extracted paragraph/,
  );
  assert.equal(
    f.calls.some((call) => call.includes("/preview")),
    false,
  );
  f.controller.dispose();
});
test("native-viewer controller: renderer failure purges instead of offering an unsafe fallback", async () => {
  const f = fixture();
  await f.controller.open();
  f.controller.rendererFailed();
  assert.equal(f.controller.getSnapshot().phase, "unsupported");
  assert.equal(f.controller.copyContent(), null);
  f.controller.dispose();
});
test("native-viewer controller: constructor has no subscription effects and effect replay rechecks access", async () => {
  let subscriptions = 0,
    unsubscriptions = 0;
  const f = fixture({
    subscribeInvalidation: () => {
      subscriptions++;
      return () => {
        unsubscriptions++;
      };
    },
  });
  assert.equal(subscriptions, 0);
  await f.controller.open();
  assert.equal(subscriptions, 1);
  f.controller.dispose();
  assert.equal(unsubscriptions, 1);
  f.calls.length = 0;
  await f.controller.open();
  assert.equal(subscriptions, 2);
  assert.ok(f.calls.includes("metadata"));
  assert.ok(f.calls.includes("hash"));
  f.controller.dispose();
  assert.equal(unsubscriptions, 2);
});
