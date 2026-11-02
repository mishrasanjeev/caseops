import test from "node:test";
import assert from "node:assert/strict";
import {
  VIEWER_LIMITS,
  attachmentViewerSource,
  decodeDocxText,
  imageDimensions,
  originalPath,
  sourcePath,
  validateBytes,
  validateSource,
  viewerFormat,
} from "./contracts.ts";
import { source } from "./test-fixtures.ts";
import { encodeBase64, decodeBase64 } from "./encoding.ts";

test("native-viewer contracts: exact authorized routes and no invented source action", () => {
  assert.equal(
    sourcePath(source),
    "/api/matters/matter-1/attachments/file-1/download?inline=true",
  );
  assert.equal(
    sourcePath({ ...source, filename: "a.txt", contentType: "text/plain" }),
    "/api/matters/matter-1/attachments/file-1/download",
  );
  const docx = {
    ...source,
    filename: "a.docx",
    contentType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };
  assert.equal(
    sourcePath(docx),
    "/api/matters/matter-1/attachments/file-1/preview",
  );
  assert.equal(
    originalPath(docx),
    "/api/matters/matter-1/attachments/file-1/download",
  );
});
test("native-viewer contracts: source binding rejects wrong parent, unbounded metadata and path injection", () => {
  assert.throws(() => validateSource({ ...source, matterId: "../other" }));
  assert.throws(() => validateSource({ ...source, sha256: "wrong" }));
  assert.throws(() => validateSource({ ...source, sizeBytes: 0 }));
  assert.throws(() => validateSource({ ...source, filename: "x".repeat(256) }));
  assert.throws(() =>
    attachmentViewerSource(source, { matter_id: "other" } as never),
  );
  assert.ok(Object.isFrozen(validateSource(source)));
});
test("native-viewer contracts: supported extension and MIME must agree, never HTML/SVG/DOC fallback", () => {
  for (const extension of ["html", "svg", "doc", "gif", "webp", "zip"])
    assert.equal(viewerFormat({ ...source, filename: `a.${extension}` }), null);
  assert.equal(viewerFormat({ ...source, contentType: "text/html" }), null);
  assert.equal(viewerFormat({ ...source, contentType: null })?.kind, "pdf");
  assert.equal(
    viewerFormat({
      ...source,
      filename: "A.PDF",
      contentType: "application/pdf; x=y",
    })?.kind,
    "pdf",
  );
});
test("native-viewer contracts: bytes and pixel limits reject bombs before image decoding", () => {
  assert.throws(() =>
    validateBytes(new Uint8Array([1]), "pdf", "application/pdf"),
  );
  assert.throws(() =>
    validateBytes(
      new Uint8Array(VIEWER_LIMITS.maxBytes + 1),
      "text",
      "text/plain",
    ),
  );
  const png = new Uint8Array(24);
  png.set([137, 80, 78, 71, 13, 10, 26, 10]);
  png.set([73, 72, 68, 82], 12);
  const view = new DataView(png.buffer);
  view.setUint32(16, 100);
  view.setUint32(20, 200);
  assert.deepEqual(imageDimensions(png, "image/png"), {
    width: 100,
    height: 200,
  });
  view.setUint32(16, 100_000);
  assert.throws(() => validateBytes(png, "image", "image/png"));
  const jpeg = new Uint8Array([255, 216, 255, 192, 0, 8, 8, 0, 10, 0, 20, 1]);
  assert.deepEqual(imageDimensions(jpeg, "image/jpeg"), {
    width: 20,
    height: 10,
  });
  assert.throws(() => imageDimensions(jpeg.subarray(0, 8), "image/jpeg"));
});
test("native-viewer contracts: DOCX preview binds real DTO and enforces combined text/table bounds", () => {
  const row = {
    attachment_id: source.attachmentId,
    filename: source.filename,
    content_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    paragraphs: ["<script>inert</script>"],
    table_rows: [["cell"]],
  };
  assert.deepEqual(decodeDocxText(row, source), {
    paragraphs: row.paragraphs,
    tableRows: row.table_rows,
  });
  assert.throws(() =>
    decodeDocxText({ ...row, attachment_id: "other" }, source),
  );
  assert.throws(() =>
    decodeDocxText({ ...row, paragraphs: ["a".repeat(500_001)] }, source),
  );
  assert.throws(() =>
    decodeDocxText({ ...row, table_rows: [["a".repeat(10_001)]] }, source),
  );
  assert.throws(() =>
    decodeDocxText(
      { ...row, paragraphs: ["a".repeat(499_999)], table_rows: [["ab"]] },
      source,
    ),
  );
});
test("native-viewer contracts: base64 byte-exact across padding and chunk boundaries", () => {
  for (const size of [0, 1, 2, 3, 255, 49_152]) {
    const bytes = Uint8Array.from({ length: size }, (_, i) => i % 256);
    assert.equal(encodeBase64(bytes), Buffer.from(bytes).toString("base64"));
    assert.deepEqual(decodeBase64(encodeBase64(bytes)), bytes);
  }
  for (const invalid of ["a", "====", "A===", "!!!!", "Zg==="])
    assert.throws(() => decodeBase64(invalid));
});
