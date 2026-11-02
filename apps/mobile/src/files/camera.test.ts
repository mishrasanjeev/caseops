import assert from "node:assert/strict";
import test from "node:test";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  CameraCaptureError,
  cameraCacheRoot,
  createCameraCache,
  createPhotoCapture,
  isCameraCopy,
} from "./camera.ts";
import { MAX_NATIVE_UPLOAD_BYTES } from "./contracts.ts";
import { TempCleanupError } from "./staging.ts";
import { createFilePickerCoordinator } from "../domain/file-picker.ts";
import { cameraLicences } from "./camera-notices.ts";

const root = "file:///synthetic-app/cache/ImagePicker/";
const uri = `${root}00000000-0000-0000-0000-000000000001.jpeg`;
const orphan = `${root}00000000-0000-0000-0000-000000000002.jpg`;
const original = "content://provider/original.jpg";
const asset = { uri, type: "image", mimeType: "image/jpeg", fileSize: 4 };
const intent = {
  companyId: "company",
  userId: "user",
  membershipId: "member",
  sessionKey: "session",
  matterId: "matter",
  expectedLifecycleVersion: 7,
};
const identity = {
  company: { id: "company", name: "Synthetic", slug: "synthetic" },
  user: { id: "user", email: "synthetic@example.test", full_name: "Synthetic" },
  membership: { id: "member", role: "admin" },
  capabilities: [],
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function setup(
  options: {
    permission?: () => Promise<{ granted: boolean }>;
    launch?: () => Promise<any>;
    removeFails?: boolean;
  } = {},
) {
  const disk = new Map<string, number>([[original, 100]]);
  const events: string[] = [];
  const file = (name: string) => ({
    uri: name,
    get exists() {
      return disk.has(name);
    },
    delete() {
      events.push(`delete:${name}`);
      if (options.removeFails) throw new Error("Synthetic removal failure");
      disk.delete(name);
    },
  });
  const cache = createCameraCache({
    rootUri: root,
    file,
    listFiles: () =>
      [...disk.keys()].filter((name) => name.startsWith(root)).map(file),
  });
  const capture = createPhotoCapture({
    cacheRootUri: root,
    async requestPermission() {
      events.push("permission");
      return options.permission ? options.permission() : { granted: true };
    },
    async launch() {
      events.push("camera");
      if (options.launch) return options.launch();
      disk.set(uri, 4);
      return { canceled: false, assets: [asset] };
    },
    inspect(name) {
      events.push("inspect");
      return { exists: disk.has(name), size: disk.get(name) ?? 0 };
    },
    purge() {
      events.push("purge");
      cache.purge();
    },
    retainOnly: cache.retainOnly,
  });
  return { disk, events, capture, cache };
}

test("explicit capture requests only camera permission, retains one private result and never uploads", async () => {
  const f = setup();
  assert.deepEqual(f.events, []);
  assert.deepEqual(await f.capture(), {
    uri,
    name: "capture.jpeg",
    mimeType: "image/jpeg",
    size: 4,
  });
  assert.deepEqual(f.events, ["purge", "permission", "camera", "inspect"]);
  assert.deepEqual([...f.disk.keys()], [original, uri]);
});

test("camera denial cleans orphans, performs no camera action and leaves file-picker fallback usable", async () => {
  const f = setup({ permission: async () => ({ granted: false }) });
  f.disk.set(orphan, 3);
  let files = 0;
  const picker = createFilePickerCoordinator(
    async () => {
      files++;
      return { uri: original, name: "source.jpg" };
    },
    f.cache.cleanupPickedFile,
    () => {},
    f.capture,
  );
  await assert.rejects(
    picker.choose(intent, "camera"),
    (error) =>
      error instanceof CameraCaptureError &&
      error.reason === "permission" &&
      error.message.includes("Choose file"),
  );
  assert.equal(f.events.includes("camera"), false);
  assert.deepEqual([...f.disk.keys()], [original]);
  await picker.choose(intent);
  assert.equal(files, 1);
  assert.equal(
    picker.snapshot(identity, "session")?.selection?.asset.uri,
    original,
  );
});

test("raw SDK permission and camera exceptions never reflect secret or URI values", async () => {
  for (const stage of ["permission", "camera"] as const) {
    const fail = async () => {
      throw new Error("PRIVATE_TOKEN file:///private/location.jpg");
    };
    const f = setup(
      stage === "permission" ? { permission: fail } : { launch: fail },
    );
    await assert.rejects(
      f.capture(),
      (error) =>
        error instanceof CameraCaptureError &&
        !error.message.includes("PRIVATE_TOKEN") &&
        !error.message.includes("file:"),
    );
    assert.deepEqual([...f.disk.keys()], [original]);
  }
});

test("OS cancellation removes partial SDK output without touching provider originals", async () => {
  const f = setup({
    launch: async () => {
      f.disk.set(orphan, 2);
      return { canceled: true, assets: null };
    },
  });
  assert.equal(await f.capture(), null);
  assert.deepEqual([...f.disk.keys()], [original]);
});

test("oversize capture is rejected by actual private-file size and all SDK copies are removed", async () => {
  const f = setup({
    launch: async () => {
      f.disk.set(uri, MAX_NATIVE_UPLOAD_BYTES + 1);
      f.disk.set(orphan, 1);
      return { canceled: false, assets: [{ ...asset, fileSize: 1 }] };
    },
  });
  await assert.rejects(f.capture(), CameraCaptureError);
  assert.deepEqual([...f.disk.keys()], [original]);
});

test("malformed results, MIME/size mismatch, foreign and nested URLs cannot become a selection", async () => {
  for (const result of [
    { canceled: false, assets: [] },
    { canceled: false, assets: [asset, asset] },
    { canceled: false, assets: [{ ...asset, type: "video" }] },
    { canceled: false, assets: [{ ...asset, mimeType: "image/png" }] },
    { canceled: false, assets: [{ ...asset, fileSize: 3 }] },
    { canceled: false, assets: [{ ...asset, uri: original }] },
    {
      canceled: false,
      assets: [{ ...asset, uri: `${root}nested/${uri.split("/").at(-1)}` }],
    },
    { assets: [asset] },
  ]) {
    const f = setup({
      launch: async () => {
        f.disk.set(uri, 4);
        return result;
      },
    });
    await assert.rejects(f.capture(), CameraCaptureError);
    assert.deepEqual([...f.disk.keys()], [original]);
  }
});

test("rapid direct capture rejects before purge or second permission request", async () => {
  const permission = deferred<{ granted: boolean }>();
  const f = setup({ permission: () => permission.promise });
  const first = f.capture();
  f.disk.set(orphan, 2); // Simulate an active native output that must survive the second command.
  const before = [...f.events];
  await assert.rejects(
    f.capture(),
    (error) => error instanceof CameraCaptureError && error.reason === "busy",
  );
  assert.deepEqual(f.events, before);
  assert.equal(f.disk.has(orphan), true);
  permission.resolve({ granted: true });
  await first;
  assert.deepEqual([...f.disk.keys()], [original, uri]);
});

test("the existing coordinator shares one synchronous lease across capture and file fallback", async () => {
  const permission = deferred<{ granted: boolean }>();
  const f = setup({ permission: () => permission.promise });
  let files = 0;
  const picker = createFilePickerCoordinator(
    async () => {
      files++;
      return null;
    },
    f.cache.cleanupPickedFile,
    () => {},
    f.capture,
  );
  const first = picker.choose(intent, "camera");
  await assert.rejects(picker.choose(intent), /Finish the current/);
  await assert.rejects(picker.choose(intent, "camera"), /Finish the current/);
  assert.equal(files, 0);
  permission.resolve({ granted: true });
  await first;
  assert.equal(
    picker.snapshot(identity, "session")?.selection?.expectedLifecycleVersion,
    7,
  );
  assert.deepEqual([...f.disk.keys()], [original, uri]);
});

test("sign-out while permission is pending prevents camera launch and selection reuse", async () => {
  const permission = deferred<{ granted: boolean }>();
  const f = setup({ permission: () => permission.promise });
  const picker = createFilePickerCoordinator(
    async () => null,
    f.cache.cleanupPickedFile,
    () => {},
    f.capture,
  );
  const pending = picker.choose(intent, "camera");
  picker.clear();
  permission.resolve({ granted: true });
  await pending;
  assert.equal(f.events.includes("camera"), false);
  assert.equal(picker.snapshot(identity, "session"), null);
});

test("late successful capture after sign-out is purged and cannot queue an upload", async () => {
  const result = deferred<any>();
  const f = setup({ launch: () => result.promise });
  const picker = createFilePickerCoordinator(
    async () => null,
    f.cache.cleanupPickedFile,
    () => {},
    f.capture,
  );
  const pending = picker.choose(intent, "camera");
  await Promise.resolve();
  assert.equal(f.events.includes("camera"), true);
  picker.clear();
  f.disk.set(uri, 4);
  result.resolve({ canceled: false, assets: [asset] });
  await pending;
  assert.equal(picker.snapshot(identity, "session"), null);
  assert.deepEqual([...f.disk.keys()], [original]);
});

test("cleanup failures remain actionable and cannot report cancellation or success", async () => {
  const f = setup({
    removeFails: true,
    launch: async () => {
      f.disk.set(uri, 4);
      return { canceled: true };
    },
  });
  await assert.rejects(f.capture(), TempCleanupError);
  assert.equal(f.disk.has(uri), true);
});

test("cache admission validates UUID direct-child identities before any deletion", () => {
  assert.equal(
    cameraCacheRoot("file:///app/cache/"),
    root.replace("synthetic-app", "app"),
  );
  assert.equal(
    cameraCacheRoot("file:///app/Library/Caches/"),
    "file:///app/Library/Caches/ImagePicker/",
  );
  for (const invalid of [
    "content://provider/cache/",
    "file://foreign/app/cache/",
    "file:///app/Documents/",
    "file:///app/cache/?private=1",
    "file:///app/cache/\n",
  ])
    assert.throws(() => cameraCacheRoot(invalid), TempCleanupError);
  for (const invalid of [
    original,
    root,
    `${root}not-a-uuid.jpg`,
    `${root}../source.jpg`,
    `${uri}?token=secret`,
    `${uri}\n`,
    `${root}nested%2f${uri.split("/").at(-1)}`,
    `${root}00000000-0000-0000-0000-000000000001.mov`,
  ])
    assert.equal(isCameraCopy(invalid, root), false);
  const f = setup();
  f.disk.set(uri, 4);
  f.disk.set(`${root}foreign.jpg`, 4);
  assert.throws(() => f.cache.purge(), TempCleanupError);
  assert.equal(f.events.length, 0);
  assert.equal(f.disk.has(uri), true);
  f.cache.cleanupPickedFile({ uri: original });
  assert.equal(f.disk.has(original), true);
});

test("real private-cache cleanup preserves root inode and provider originals across startup/clear/repeated purge", (t) => {
  const base = mkdtempSync(path.join(tmpdir(), "caseops-camera-"));
  t.after(() => rmSync(base, { recursive: true, force: true }));
  const dir = path.join(base, "cache", "ImagePicker");
  mkdirSync(dir, { recursive: true });
  const filename = "00000000-0000-0000-0000-000000000001.jpg";
  const local = path.join(dir, filename),
    provider = path.join(base, "original.jpg");
  writeFileSync(local, "test");
  writeFileSync(provider, "original");
  const inode = statSync(dir).ino;
  const entry = (uri: string) => ({
    uri,
    get exists() {
      try {
        return statSync(new URL(uri)).isFile();
      } catch {
        return false;
      }
    },
    delete() {
      unlinkSync(new URL(uri));
    },
  });
  const area = createCameraCache({
    rootUri: pathToFileURL(`${dir}/`).href,
    file: entry,
    listFiles: () =>
      readdirSync(dir).map((name) =>
        entry(pathToFileURL(path.join(dir, name)).href),
      ),
  });
  area.cleanupPickedFile({ uri: pathToFileURL(provider).href });
  area.cleanupPickedFile({ uri: pathToFileURL(local).href });
  writeFileSync(local, "orphan");
  area.purge();
  area.purge();
  assert.equal(statSync(dir).ino, inode);
  assert.equal(readFileSync(provider, "utf8"), "original");
  assert.deepEqual(readdirSync(dir), []);
});

test("both exact installed MIT licences are retained in the app's displayed camera notices", () => {
  assert.equal(
    cameraLicences,
    readFileSync(new URL("../../CAMERA_NOTICES.txt", import.meta.url), "utf8"),
  );
  for (const name of ["expo-image-picker", "expo-image-loader"]) {
    const licence = readFileSync(
      new URL(`../../node_modules/${name}/LICENSE`, import.meta.url),
      "utf8",
    );
    assert.ok(cameraLicences.includes(licence));
  }
  for (const name of ["GLIDE-LICENSE.txt", "ANDROID-IMAGE-CROPPER-LICENSE.txt"])
    assert.ok(
      cameraLicences.includes(
        readFileSync(
          new URL(`../../vendor/camera-sdk58/${name}`, import.meta.url),
          "utf8",
        ),
      ),
    );
});
