import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";

test("native-viewer integration: native component supplies selectors, memory-only bridge and privacy exits", async () => {
  const source = await readFile(
    new URL("./PrivateDocumentViewer.tsx", import.meta.url),
    "utf8",
  );
  for (const id of [
    "private-document-viewer",
    "viewer-close",
    "viewer-filename",
    "viewer-toolbar",
    "viewer-position",
    "viewer-previous",
    "viewer-next",
    "viewer-zoom-in",
    "viewer-zoom-out",
    "viewer-text-reader",
    "viewer-isolated-renderer",
  ])
    assert.ok(source.includes(`\"${id}\"`), id);
  for (const marker of [
    "useLayoutEffect",
    "hiddenCommit.current",
    'controller.purge("background")',
    'controller.purge("closed")',
    "controller.dispose()",
    "postMessage(JSON.stringify",
    "onFileDownload",
    "onOpenWindow",
    "onRenderProcessGone",
  ])
    assert.ok(source.includes(marker), marker);
  assert.doesNotMatch(
    source,
    /injectJavaScript|Linking|FileSystem|File\.preview|Sharing|writeAsString|downloadAsync|useAllowScreenCapture|FLAG_SECURE/,
  );
});
test("native-viewer integration: backend routes are real visibility-gated retained reads, not invented metadata", async () => {
  const routes = await readFile(
    new URL(
      "../../../api/src/caseops_api/api/routes/matters.py",
      import.meta.url,
    ),
    "utf8",
  );
  const services = await readFile(
    new URL(
      "../../../api/src/caseops_api/services/matters.py",
      import.meta.url,
    ),
    "utf8",
  );
  assert.ok(
    routes.includes('"/{matter_id}/attachments/{attachment_id}/download"'),
  );
  assert.ok(
    routes.includes('"/{matter_id}/attachments/{attachment_id}/preview"'),
  );
  const download = services.slice(
    services.indexOf("def get_matter_attachment_download("),
    services.indexOf("def _validate_docx_preview_archive("),
  );
  assert.match(
    download,
    /_get_matter_model\(session, context=context, matter_id=matter_id\)/,
  );
  assert.match(download, /MatterAttachment\.matter_id == matter\.id/);
});
test("native-viewer integration: explicit local test-file inventory remains reconciled", async () => {
  const actual = (await readdir(new URL(".", import.meta.url)))
    .filter((name) => name.endsWith(".test.ts"))
    .sort();
  assert.deepEqual(actual, [
    "assets.test.ts",
    "contracts.test.ts",
    "controller.test.ts",
    "integration-contract.test.ts",
    "pdf-stream.test.ts",
    "renderer-readiness.test.ts",
    "renderer.test.ts",
    "security.test.ts",
  ]);
});
