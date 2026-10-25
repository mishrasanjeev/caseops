import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { pdfjsAssets, pdfjsVersion } from "./generated/pdfjs-assets.ts";
import {
  buildAssets,
  INTEGRITY,
  unpack,
  VERSION,
} from "../../../../scripts/mobile/prepare-viewer-assets.mjs";

test("native-viewer assets: exact stable package, complete 194-input hash/license inventory", async () => {
  const manifest = JSON.parse(
    await readFile(
      new URL("./generated/manifest.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(pdfjsVersion, "6.4.299");
  assert.equal(VERSION, pdfjsVersion);
  assert.equal(manifest.integrity, INTEGRITY);
  assert.equal(manifest.files.length, 194);
  assert.equal(
    manifest.files.filter((file: { path: string }) =>
      file.path.endsWith(".bcmap"),
    ).length,
    168,
  );
  assert.equal(Object.keys(pdfjsAssets).length, manifest.files.length);
  for (const file of manifest.files) {
    const bytes = Buffer.from(pdfjsAssets[file.path], "base64");
    assert.equal(bytes.length, file.bytes, file.path);
    assert.equal(
      createHash("sha256").update(bytes).digest("hex"),
      file.sha256,
      file.path,
    );
  }
  const licenses = await readFile(
    new URL("./generated/LICENSES.txt", import.meta.url),
    "utf8",
  );
  for (const path of Object.keys(pdfjsAssets).filter((path) =>
    path.includes("LICENSE"),
  )) {
    assert.ok(licenses.includes(path));
    assert.ok(
      licenses.includes(Buffer.from(pdfjsAssets[path], "base64").toString()),
    );
  }
});
test("native-viewer assets: byte-identical regeneration and fail-closed altered closure", async () => {
  const files = new Map(
    Object.entries(pdfjsAssets).map(([path, base64]) => [
      path,
      Buffer.from(base64, "base64"),
    ]),
  );
  files.set(
    "package.json",
    Buffer.from(
      JSON.stringify({
        name: "pdfjs-dist",
        version: VERSION,
        license: "Apache-2.0",
      }),
    ),
  );
  const outputs = buildAssets(files);
  for (const [name, value] of Object.entries(outputs))
    assert.equal(
      value,
      await readFile(new URL(`./generated/${name}`, import.meta.url), "utf8"),
    );
  const changed = new Map(files);
  changed.set("cmaps/Adobe-CNS1-0.bcmap", Buffer.from("tampered"));
  assert.throws(() => buildAssets(changed), /closure/);
  const missing = new Map(files);
  missing.delete("cmaps/Adobe-CNS1-0.bcmap");
  assert.throws(() => buildAssets(missing), /closure/);
  const wrongVersion = new Map(files);
  wrongVersion.set(
    "package.json",
    Buffer.from(
      '{"name":"pdfjs-dist","version":"5.4.296","license":"Apache-2.0"}',
    ),
  );
  assert.throws(() => buildAssets(wrongVersion), /exact reviewed/);
  assert.throws(
    () => unpack(Buffer.from("not the pinned archive")),
    /integrity/,
  );
});
