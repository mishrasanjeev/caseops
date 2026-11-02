import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  createStagingArea,
  copyBounded,
  isOwnedStagingUri,
  MAX_STAGING_AGE_MS,
  TempCleanupError,
  uploadByteLimit,
  validateAsset,
} from "./staging.ts";
import { decodeFilesWorkspace } from "./contracts.ts";
import {
  bytes,
  filesWorkspaceFixture,
  hash,
  scope,
  selection,
} from "./test-fixtures.ts";

const rootUri = "file:///synthetic-cache/caseops-matter-files-v1";
const ownedUri = `${rootUri}/12345678-1234-1234-1234-123456789abc.txt`;
const policy = decodeFilesWorkspace(filesWorkspaceFixture(), scope).storage;
function fakeDisk(
  options: {
    copy?: () => Promise<void>;
    digest?: () => Promise<void>;
    now?: () => number;
    refuseDelete?: boolean;
  } = {},
) {
  const files = new Map<string, Buffer>([[selection.asset.uri, bytes]]);
  const deleted: string[] = [];
  let roots = 0;
  const area = createStagingArea(
    {
      rootUri,
      ensureRoot() {
        roots++;
      },
      uniqueUri() {
        return ownedUri;
      },
      file(uri) {
        return {
          get exists() {
            return files.has(uri);
          },
          get size() {
            return files.get(uri)?.length ?? 0;
          },
          async copyTo(target) {
            await options.copy?.();
            files.set(target, Buffer.from(files.get(uri)!));
          },
          async digest() {
            await options.digest?.();
            return createHash("sha256").update(files.get(uri)!).digest("hex");
          },
          delete() {
            if (options.refuseDelete)
              throw new Error("Synthetic deletion failure");
            deleted.push(uri);
            files.delete(uri);
          },
        };
      },
      purgeRoot() {
        for (const uri of files.keys())
          if (isOwnedStagingUri(uri, rootUri)) {
            deleted.push(uri);
            files.delete(uri);
          }
      },
    },
    options.now,
  );
  return { area, files, deleted, roots: () => roots };
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

test("MOB-24 picker formats and configured size/quota limits match the server allowlist; no invented URI sources", () => {
  const names = [
    "a.pdf",
    "a.docx",
    "a.doc",
    "a.txt",
    "a.png",
    "a.jpg",
    "a.jpeg",
    "a.PDF",
  ];
  for (const name of names)
    assert.ok(
      validateAsset({ ...selection.asset, name, mimeType: undefined }, policy)
        .mime,
    );
  for (const asset of [
    { ...selection.asset, name: "a.exe" },
    { ...selection.asset, name: "a.gif" },
    { ...selection.asset, name: "a.webp" },
    { ...selection.asset, name: "a.xlsx" },
    { ...selection.asset, name: "no-extension" },
    { ...selection.asset, name: ".txt" },
    { ...selection.asset, name: "../../a.txt" },
    { ...selection.asset, name: "a\\b.txt" },
    { ...selection.asset, name: "a\u0000.txt" },
    { ...selection.asset, name: "x".repeat(256) + ".txt" },
    { ...selection.asset, name: "a.pdf", mimeType: "image/png" },
    { ...selection.asset, uri: "https://example.invalid/private.txt" },
    { ...selection.asset, uri: "file://foreign-host/share/private.txt" },
    { ...selection.asset, uri: "data:text/plain,synthetic" },
    { ...selection.asset, uri: "content://provider/item#fragment" },
    { ...selection.asset, size: -1 },
    { ...selection.asset, size: policy.max_upload_size_bytes + 1 },
  ])
    assert.throws(() => validateAsset(asset, policy));
  assert.equal(
    uploadByteLimit({ ...policy, max_upload_size_bytes: 100_000_000 }),
    50 * 1024 * 1024,
  );
  assert.equal(uploadByteLimit({ ...policy, remaining_bytes: 12 }), 12);
  assert.throws(() =>
    validateAsset(selection.asset, { ...policy, remaining_bytes: 0 }),
  );
});

test("MOB-22 explicit preparation hashes an owned copy, retains the provider original and cleans idempotently", async () => {
  const disk = fakeDisk();
  assert.equal(disk.roots(), 0);
  const prepared = await disk.area.prepare(
    selection.asset,
    policy,
    new AbortController().signal,
  );
  assert.equal(prepared.sha256, hash);
  assert.equal(prepared.size, bytes.length);
  assert.deepEqual(prepared.part, {
    uri: ownedUri,
    name: "synthetic.txt",
    type: "text/plain",
  });
  assert.equal(disk.files.has(selection.asset.uri), true);
  prepared.dispose();
  prepared.dispose();
  assert.deepEqual(disk.deleted, [ownedUri]);
  assert.equal(disk.files.has(selection.asset.uri), true);
});

test("MOB-24 unknown picker size is checked against actual bytes; empty and oversized originals are refused before copying", async () => {
  const disk = fakeDisk();
  const { size: _size, ...unknownSize } = selection.asset;
  const prepared = await disk.area.prepare(
    unknownSize,
    policy,
    new AbortController().signal,
  );
  assert.equal(prepared.size, bytes.length);
  prepared.dispose();
  await assert.rejects(
    disk.area.prepare(
      { ...unknownSize, size: 1 },
      { ...policy, remaining_bytes: 2 },
      new AbortController().signal,
    ),
  );
  disk.files.set(selection.asset.uri, Buffer.alloc(0));
  await assert.rejects(
    disk.area.prepare(unknownSize, policy, new AbortController().signal),
  );
  assert.equal(disk.files.has(ownedUri), false);
});

test("MOB-25 cancel during native copy deletes only the late owned result, never the provider original", async () => {
  const copy = deferred();
  const disk = fakeDisk({ copy: () => copy.promise });
  const abort = new AbortController();
  const pending = disk.area.prepare(selection.asset, policy, abort.signal);
  abort.abort();
  copy.resolve();
  await assert.rejects(pending);
  assert.equal(disk.files.has(ownedUri), false);
  assert.equal(disk.files.has(selection.asset.uri), true);
});

test("MOB-25 sign-out purge fences a native copy that completes after directory cleanup", async () => {
  const copy = deferred();
  const disk = fakeDisk({ copy: () => copy.promise });
  const pending = disk.area.prepare(
    selection.asset,
    policy,
    new AbortController().signal,
  );
  disk.area.purge();
  copy.resolve();
  await assert.rejects(pending);
  assert.equal(disk.files.has(ownedUri), false);
  assert.equal(disk.files.has(selection.asset.uri), true);
});

test("MOB-25 staging expiry is enforced at the boundary and removes retained partial bytes", async () => {
  for (const elapsed of [
    MAX_STAGING_AGE_MS - 1,
    MAX_STAGING_AGE_MS,
    MAX_STAGING_AGE_MS + 1,
  ]) {
    let now = 0;
    const disk = fakeDisk({
      now: () => now,
      digest: async () => {
        now = elapsed;
      },
    });
    const pending = disk.area.prepare(
      selection.asset,
      policy,
      new AbortController().signal,
    );
    if (elapsed < MAX_STAGING_AGE_MS) (await pending).dispose();
    else await assert.rejects(pending);
    assert.equal(disk.files.has(ownedUri), false);
  }
});

test("MOB-26 clear/cancel/startup cleanup never deletes provider files, siblings, traversal paths or other cache owners", () => {
  const disk = fakeDisk();
  disk.files.set(ownedUri, bytes);
  const foreign = [
    selection.asset.uri,
    "file:///picked-original.txt",
    `${rootUri}-sibling/12345678-1234-1234-1234-123456789abc.txt`,
    `${rootUri}/../private.txt`,
    `${rootUri}/%2e%2e/private.txt`,
    `${rootUri}/folder/private.txt`,
    `${ownedUri}?token=synthetic`,
    `${ownedUri}#fragment`,
  ];
  for (const uri of foreign) {
    disk.files.set(uri, bytes);
    assert.equal(isOwnedStagingUri(uri, rootUri), false);
    disk.area.cleanupPickedFile({ ...selection.asset, uri });
    assert.equal(disk.files.has(uri), true);
  }
  disk.area.cleanupPickedFile({ ...selection.asset, uri: ownedUri });
  assert.deepEqual(disk.deleted, [ownedUri]);
  disk.files.set(ownedUri, bytes);
  disk.area.purge();
  assert.equal(disk.files.has(ownedUri), false);
  for (const uri of foreign) assert.equal(disk.files.has(uri), true);
});

test("MOB-25 cleanup failure before preparation returns is typed and cannot masquerade as safe removal", async () => {
  const disk = fakeDisk({
    digest: () => Promise.reject(new Error("Synthetic digest failure")),
    refuseDelete: true,
  });
  await assert.rejects(
    disk.area.prepare(selection.asset, policy, new AbortController().signal),
    TempCleanupError,
  );
  assert.equal(disk.files.has(ownedUri), true);
  assert.equal(disk.files.has(selection.asset.uri), true);
});

test("MOB-24 native copy bounds bytes stored and per-read allocation, including a source that understates its size", async () => {
  const limit = 2 * 1024 * 1024;
  let read = 0,
    written = 0;
  const reads: number[] = [];
  await assert.rejects(
    copyBounded(
      async (length) => {
        reads.push(length);
        read += length;
        return new Uint8Array(length);
      },
      async (chunk) => {
        written += chunk.length;
      },
      limit,
      () => {},
    ),
  );
  assert.equal(written, limit);
  assert.equal(read, limit + 1);
  assert.deepEqual(reads, [1024 * 1024, 1024 * 1024, 1]);
  let ended = false;
  assert.equal(
    await copyBounded(
      async () => {
        if (ended) return new Uint8Array();
        ended = true;
        return new Uint8Array(10);
      },
      async () => {},
      20,
      () => {},
    ),
    10,
  );
});

test("MOB-25 cancellation during a native read is checked before any private bytes are written", async () => {
  let cancelled = false,
    writes = 0;
  await assert.rejects(
    copyBounded(
      async () => {
        cancelled = true;
        return new Uint8Array(10);
      },
      async () => {
        writes++;
      },
      20,
      () => {
        if (cancelled) throw new Error("Synthetic cancellation");
      },
    ),
  );
  assert.equal(writes, 0);
});
