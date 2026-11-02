import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import {
  nativeMultipart,
  stagedMultipartUri,
  createMatterFilesApi,
  multipartFilename,
} from "./api.ts";
import { MAX_NATIVE_UPLOAD_BYTES } from "./contracts.ts";
import { bytes, hash, scope } from "./test-fixtures.ts";
import type { AuthorizedRequest } from "../domain/repository.ts";

function sdkConverter() {
  const source = readFileSync(
    new URL(
      "../../node_modules/expo/src/winter/fetch/convertFormData.ts",
      import.meta.url,
    ),
    "utf8",
  );
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const exports: Record<string, unknown> = {};
  vm.runInNewContext(output.outputText, {
    exports,
    Blob,
    Uint8Array,
    TextEncoder,
    require: (name: string) => {
      assert.equal(name, "../../utils/blobUtils");
      return { blobToArrayBufferAsync: (blob: Blob) => blob.arrayBuffer() };
    },
  });
  return exports.convertFormDataAsync as (
    form: { entries: () => Iterable<[string, unknown]> },
    boundary: string,
  ) => Promise<{ body: Uint8Array; boundary: string }>;
}

const part = {
  uri: "file:///private-cache/caseops-matter-files-v1/12345678-1234-1234-1234-123456789abc.txt",
  name: "Original synthetic file.txt",
  type: "text/plain",
};

test("MOB-22 pinned Expo encoder rejects legacy RN URI parts before transport", async () => {
  await assert.rejects(
    sdkConverter()({ entries: () => [["file", part]] }, "unit-boundary"),
    /Unsupported FormDataPart implementation/,
  );
});

test("MOB-22 actual pinned Expo encoder preserves owned bytes, original filename, MIME and lifecycle field", async () => {
  const original = globalThis.FormData;
  class FormFixture {
    parts: [string, unknown][] = [];
    append(name: string, value: unknown) {
      this.parts.push([name, value]);
    }
    entries() {
      return this.parts.values();
    }
  }
  globalThis.FormData = FormFixture as unknown as typeof FormData;
  let reads = 0;
  try {
    const form = nativeMultipart(
      part,
      9,
      async () => {
        reads++;
        return bytes;
      },
      bytes.length,
    ) as unknown as FormFixture;
    assert.equal(reads, 0);
    const encoded = await sdkConverter()(form, "unit-boundary");
    const text = new TextDecoder().decode(encoded.body);
    assert.equal(reads, 1);
    assert.ok(
      text.includes('name="file"; filename="Original_synthetic_file.txt"'),
    );
    assert.ok(text.includes("content-type: text/plain"));
    assert.ok(text.includes(new TextDecoder().decode(bytes)));
    assert.ok(text.includes('name="expected_lifecycle_version"\r\n\r\n9\r\n'));
    assert.equal(text.includes("file:///"), false);
  } finally {
    globalThis.FormData = original;
  }
});

test("MOB-22 filename handling agrees with the actual canonical server function, including spaces, percent signs and Unicode", () => {
  const cases = [
    "Court Order.pdf",
    "Tax%20paper.txt",
    "\u00c5 Tax.pdf",
    "  original.txt  ",
    "a__b---1.pdf",
  ];
  const server = fileURLToPath(
    new URL(
      "../../../api/src/caseops_api/services/document_storage.py",
      import.meta.url,
    ),
  );
  const code =
    "import ast,json,re,sys\nfrom pathlib import Path\ntree=ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8'))\nkeep=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='sanitize_filename' or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_FILENAME_SANITIZER' for t in n.targets)]\nassert len(keep)==2\nns={'re':re,'Path':Path}\nexec(compile(ast.Module(body=keep,type_ignores=[]),sys.argv[1],'exec'),ns)\nprint(json.dumps([ns['sanitize_filename'](v) for v in json.loads(sys.stdin.read())]))";
  const result = spawnSync(
    process.env.PYTHON || "python",
    ["-B", "-c", code, server],
    {
      input: JSON.stringify(cases),
      encoding: "utf8",
      windowsHide: true,
      timeout: 10000,
    },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(cases.map(multipartFilename), JSON.parse(result.stdout));
  for (const name of [
    "../file.txt",
    "folder\\file.txt",
    "unsafe\r\n.txt",
    " ",
    "a".repeat(256),
  ])
    assert.throws(() => multipartFilename(name));
});

test("MOB-22 native multipart requires an explicit byte reader and bounded exact staged size", async () => {
  for (const size of [
    0,
    -1,
    1.5,
    Infinity,
    MAX_NATIVE_UPLOAD_BYTES + 1,
    undefined,
  ])
    assert.throws(() => nativeMultipart(part, 0, async () => bytes, size));
  assert.throws(() => nativeMultipart(part, 0));
  const original = globalThis.FormData;
  let file: { bytes(): Promise<Uint8Array> } | undefined;
  globalThis.FormData = class {
    append(name: string, value: unknown) {
      if (name === "file") file = value as typeof file;
    }
  } as unknown as typeof FormData;
  try {
    nativeMultipart(part, 0, async () => bytes, bytes.length + 1);
    await assert.rejects(file!.bytes(), /native multipart staged bytes/);
  } finally {
    globalThis.FormData = original;
  }
});

test("MOB-22 no default URI fallback can dispatch an upload without its installed native multipart adapter", async () => {
  let calls = 0;
  const request: AuthorizedRequest = async <T>() => {
    calls++;
    return {} as T;
  };
  await assert.rejects(
    createMatterFilesApi(request, scope).upload(
      { part, size: bytes.length, sha256: hash, dispose() {} },
      0,
      new AbortController().signal,
    ),
    /native multipart adapter required/,
  );
  assert.equal(calls, 0);
});

test("MOB-22 native transport can read only the canonical owned UUID staging file", () => {
  const root = "file:///private-cache/caseops-matter-files-v1";
  assert.equal(stagedMultipartUri(part.uri, root), part.uri);
  for (const value of [
    "content://picker/original.txt",
    "https://example.com/source.txt",
    part.uri + "?x=1",
    part.uri + "#x",
    part.uri.replace("/12345678", "/../12345678"),
    part.uri.replace(
      "12345678-1234-1234-1234-123456789abc.txt",
      "original.txt",
    ),
    part.uri.replace("/private-cache/", "/other-cache/"),
  ])
    assert.throws(() => stagedMultipartUri(value, root));
});
