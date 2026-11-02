import assert from "node:assert/strict";
import test from "node:test";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createPrivateImportArea, iosImportRoot, iosPickerCacheRoot, isPrivateImportUri, pickPrivateIosCopy, runPrivateFileCleanup } from "./private-imports.ts";
import { TempCleanupError } from "./staging.ts";
import { createFilePickerCoordinator } from "../domain/file-picker.ts";

const documents = "file:///simulator/Containers/Data/Application/current/Documents/";
const root = iosImportRoot(documents, "ai.caseops.mobile.dev.simulatoracceptance");
const imported = `${root}CaseOps%20source.txt`;

test("iOS import cleanup derives only the current app's own temporary Inbox", () => {
  assert.equal(root, "file:///simulator/Containers/Data/Application/current/tmp/ai.caseops.mobile.dev.simulatoracceptance-Inbox/");
  assert.equal(iosImportRoot(documents.slice(0, -1), "ai.caseops.mobile.dev"),
    "file:///simulator/Containers/Data/Application/current/tmp/ai.caseops.mobile.dev-Inbox/");
  for (const [uri, id] of [[documents, "../foreign"], [documents, "*"], [documents, ""],
    ["content://provider/Documents", "ai.caseops.mobile.dev"], ["file:///app/Other/", "ai.caseops.mobile.dev"],
    ["file://foreign/app/Documents/", "ai.caseops.mobile.dev"]]) {
    assert.throws(() => iosImportRoot(uri, id), TempCleanupError);
  }
});

test("selected import cleanup never deletes a provider original, sibling app or nested path", () => {
  assert.equal(isPrivateImportUri(imported, root), true);
  const rejected = ["content://provider/original.txt", "file:///provider/File%20Provider%20Storage/original.txt",
    `${root}../original.txt`, `${root}%2e%2e/original.txt`, `${root}nested%2foriginal.txt`,
    `${root}nested/original.txt`, `${root}bad%5cname.txt`, `${root}bad%00name.txt`, `${root}bad%zz.txt`,
    `${root}file.txt?secret=1`, `${root}file.txt#fragment`, root, root.replace("current", "old") + "original.txt",
    root.replace("-Inbox/", "-Inbox-other/") + "original.txt"];
  for (const uri of rejected) assert.equal(isPrivateImportUri(uri, root), false, uri);
  const files = new Set([imported, ...rejected]); const deleted: string[] = [];
  const area = createPrivateImportArea({ rootUri: root, file: uri => ({ exists: files.has(uri), delete() { files.delete(uri); deleted.push(uri); } }), listFiles: () => [] });
  for (const uri of rejected) area.cleanupPickedFile({ uri });
  area.cleanupPickedFile({ uri: imported }); area.cleanupPickedFile({ uri: imported });
  assert.deepEqual(deleted, [imported]);
  assert.deepEqual([...files], rejected);
});

test("cold-start purge removes orphan imports only in the dedicated Inbox", () => {
  const orphan = `${root}orphan.txt`, original = "file:///provider/source.txt";
  const files = new Set([orphan, original]);
  const file = (uri: string) => ({ uri, get exists() { return files.has(uri); }, delete() { files.delete(uri); } });
  const area = createPrivateImportArea({ rootUri: root, file,
    listFiles() { return [...files].filter(uri => isPrivateImportUri(uri, root)).map(file); } });
  area.purge(); assert.deepEqual([...files], [original]);
});

test("failed selected import and startup cleanup cannot report success", () => {
  const area = createPrivateImportArea({ rootUri: root, file() { return { exists: true, delete() { throw new Error("denied"); } }; },
    listFiles() { throw new Error("denied"); } });
  assert.throws(() => area.cleanupPickedFile({ uri: imported }), TempCleanupError);
  assert.throws(() => area.purge(), TempCleanupError);
});

test("selected-file deletion failure cannot prevent orphan and staging purge attempts at logout", () => {
  const calls: string[] = [];
  assert.throws(() => runPrivateFileCleanup([
    () => { calls.push("selected"); throw new TempCleanupError(); },
    () => { calls.push("staging"); throw new TempCleanupError(); },
    () => { calls.push("inbox"); },
  ]), TempCleanupError);
  assert.deepEqual(calls, ["selected", "staging", "inbox"]);
});
test("real filesystem orphan cleanup preserves the OS Inbox inode and every provider original across repeated purges", (t) => {
  const directory = mkdtempSync(path.join(tmpdir(), "caseops-inbox-identity-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const docs = path.join(directory, "Documents");mkdirSync(docs);
  const inboxUri = iosImportRoot(pathToFileURL(`${docs}/`).href, "ai.caseops.mobile.dev.simulatoracceptance");
  const inbox = fileURLToPath(inboxUri);mkdirSync(inbox, { recursive: true });
  const original = path.join(directory, "provider-original.txt");writeFileSync(original, "Unchanged synthetic provider original.");
  writeFileSync(path.join(inbox, "orphan.txt"), "Synthetic private copy.");
  const file = (uri: string) => ({ uri, get exists() { return existsSync(fileURLToPath(uri)); }, delete() { unlinkSync(fileURLToPath(uri)); } });
  const area = createPrivateImportArea({ rootUri: inboxUri, file, listFiles: () => readdirSync(inbox).map(name => file(pathToFileURL(path.join(inbox, name)).href)) });
  const inode = lstatSync(inbox).ino;
  area.purge();area.purge();
  assert.equal(lstatSync(inbox).ino, inode);assert.deepEqual(readdirSync(inbox), []);
  assert.equal(readFileSync(original, "utf8"), "Unchanged synthetic provider original.");
});
test("Inbox purge rejects foreign, nested or duplicate entries before deleting any file", () => {
  for (const uris of [["file:///provider/original.txt"], [`${root}nested/file.txt`], [imported, imported]]) {
    let deletes = 0;
    const area = createPrivateImportArea({ rootUri: root, file: () => { throw new Error(); }, listFiles: () => uris.map(uri => ({ uri, exists: true, delete() { deletes++; } })) });
    assert.throws(() => area.purge(), TempCleanupError);assert.equal(deletes, 0);
  }
});
test("purge confirms an empty listing and continues independent leaf cleanup after one deletion fails", () => {
  const retained = `${root}retained.txt`, removable = `${root}removable.txt`, files = new Set([retained, removable]);
  const area = createPrivateImportArea({ rootUri: root, file: () => { throw new Error(); }, listFiles: () => [...files].map(uri => ({ uri, exists: true, delete() { if (uri === retained) throw new Error("denied"); files.delete(uri); } })) });
  assert.throws(() => area.purge(), TempCleanupError);assert.deepEqual([...files], [retained]);
  const inaccessible = createPrivateImportArea({ rootUri: root, file: () => { throw new Error(); }, listFiles: () => [{ uri: retained, exists: false, delete() { assert.fail(); } }] });
  assert.throws(() => inaccessible.purge(), TempCleanupError);
});

test("iOS picker cache ownership derives only the current app Library/Caches directory", () => {
  assert.equal(iosPickerCacheRoot("file:///app/Library/Caches"), "file:///app/Library/Caches/DocumentPicker/");
  for (const uri of ["file:///provider/Caches/", "content://provider/Library/Caches/", "file://foreign/app/Library/Caches/", "file:///app/Library/Caches/?query=1"]) {
    assert.throws(() => iosPickerCacheRoot(uri), TempCleanupError);
  }
});

function iosCopyFlow() {
  const cache = iosPickerCacheRoot("file:///app/Library/Caches/"), inbox = iosImportRoot("file:///app/Documents/", "ai.caseops.mobile.dev");
  const original = "file:///provider/original.txt", files = new Map<string, number>([[original, 8]]), deleted: string[] = [];
  const entry = (uri: string) => ({ uri, get exists() { return files.has(uri); }, delete() { files.delete(uri); deleted.push(uri); } });
  const area = (rootUri: string) => createPrivateImportArea({ rootUri, file: entry, listFiles: () => [...files.keys()].filter(uri => isPrivateImportUri(uri, rootUri)).map(entry) });
  const cached = area(cache), imported = area(inbox), inspect = (uri: string) => ({ exists: files.has(uri), size: files.get(uri) ?? 0 });
  const purge = () => runPrivateFileCleanup([cached.purge, imported.purge]);
  const asset = (id = "one") => ({ uri: `${cache}${id}.txt`, name: "original.txt", mimeType: "text/plain", size: 8 });
  return { cache, inbox, original, files, deleted, cached, imported, inspect, purge, asset };
}

test("readable iOS SDK copy retains only the admitted cache file until selected cleanup and preserves the provider original", async () => {
  const f = iosCopyFlow(), asset = f.asset();f.files.set(`${f.cache}orphan.txt`, 3);
  const result = await pickPrivateIosCopy(async () => {
    f.files.set(asset.uri, 8);f.files.set(`${f.inbox}original.txt`, 8);return asset;
  }, f.cache, 16, f.inspect, f.purge, f.imported.purge);
  assert.deepEqual(result, asset);assert.deepEqual([...f.files.keys()], [f.original, asset.uri]);
  f.cached.cleanupPickedFile(asset);assert.deepEqual([...f.files.keys()], [f.original]);
  assert.equal(f.deleted.includes(f.original), false);
});

test("iOS picker cancellation and native copy failure purge partial SDK and Inbox files", async () => {
  for (const rejects of [false, true]) {
    const f = iosCopyFlow(), failure = new Error("native failure with private path");
    const pending = pickPrivateIosCopy(async () => {
      f.files.set(`${f.cache}partial.txt`, 4);f.files.set(`${f.inbox}original.txt`, 8);
      if (rejects) throw failure;return null;
    }, f.cache, 16, f.inspect, f.purge, f.imported.purge);
    if (rejects) await assert.rejects(pending, error => error === failure);else assert.equal(await pending, null);
    assert.deepEqual([...f.files.keys()], [f.original]);
  }
});

test("iOS copied results reject foreign or nested URIs before metadata access and never delete their originals", async () => {
  for (const bad of ["file:///provider/original.txt", "file:///other/Library/Caches/DocumentPicker/file.txt", "file:///app/Library/Caches/DocumentPicker/nested/file.txt"]) {
    const f = iosCopyFlow();let reads = 0;
    await assert.rejects(pickPrivateIosCopy(async () => {
      f.files.set(`${f.cache}partial.txt`, 4);return { ...f.asset(), uri: bad };
    }, f.cache, 16, () => { reads++;throw new Error(); }, f.purge, f.imported.purge));
    assert.equal(reads, 0);assert.deepEqual([...f.files.keys()], [f.original]);
  }
});

test("iOS copied results promptly reject and clean unavailable, incomplete, empty or globally oversized cache files", async () => {
  for (const [reported, actual] of [[8, undefined], [8, 7], [0, 0], [17, 17], [undefined, 8]]) {
    const f = iosCopyFlow(), asset = { ...f.asset(), size: reported };
    await assert.rejects(pickPrivateIosCopy(async () => {
      if (actual !== undefined) f.files.set(asset.uri, actual);
      f.files.set(`${f.inbox}original.txt`, 8);return asset;
    }, f.cache, 16, f.inspect, f.purge, f.imported.purge));
    assert.deepEqual([...f.files.keys()], [f.original]);
  }
});

test("iOS cleanup failures prevent presentation or selection acceptance and still attempt independent private cleanup", async () => {
  const f = iosCopyFlow();let picks = 0;
  await assert.rejects(pickPrivateIosCopy(async () => { picks++;return f.asset(); }, f.cache, 16, f.inspect, () => { throw new TempCleanupError(); }, f.imported.purge), TempCleanupError);
  assert.equal(picks, 0);
  const asset = f.asset();
  await assert.rejects(pickPrivateIosCopy(async () => { f.files.set(asset.uri, 8);return asset; }, f.cache, 16, f.inspect, f.purge, () => { throw new TempCleanupError(); }), TempCleanupError);
  assert.deepEqual([...f.files.keys()], [f.original]);
});

test("select, clear and reselect from the same provider preserves only the fresh SDK copy", async () => {
  const f = iosCopyFlow();
  for (const id of ["first", "second"]) {
    const asset = f.asset(id);
    const selected = await pickPrivateIosCopy(async () => { f.files.set(asset.uri, 8);f.files.set(`${f.inbox}original.txt`, 8);return asset; }, f.cache, 16, f.inspect, f.purge, f.imported.purge);
    assert.deepEqual([...f.files.keys()], [f.original, asset.uri]);
    f.cached.cleanupPickedFile(selected!);assert.deepEqual([...f.files.keys()], [f.original]);
  }
});

test("a late iOS picker result after invalidation removes its completed SDK copy without adopting it", async () => {
  const f = iosCopyFlow(), asset = f.asset("late");let release!: () => void;
  const ready = new Promise<void>(resolve => { release = resolve; });
  const coordinator = createFilePickerCoordinator(() => pickPrivateIosCopy(async () => {
    await ready;f.files.set(asset.uri, 8);f.files.set(`${f.inbox}original.txt`, 8);return asset;
  }, f.cache, 16, f.inspect, f.purge, f.imported.purge), f.cached.cleanupPickedFile, () => {});
  const pending = coordinator.choose({ companyId: "company", userId: "user", membershipId: "member", sessionKey: "session", matterId: "matter", expectedLifecycleVersion: 1 });
  coordinator.clear();release();await pending;
  assert.deepEqual([...f.files.keys()], [f.original]);assert.equal(coordinator.picking, false);
});
