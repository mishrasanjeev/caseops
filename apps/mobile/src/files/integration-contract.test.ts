import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path: string) =>
  readFileSync(new URL(path, import.meta.url), "utf8");
test("MOB-22 source contract: real upload remains multipart file and response remains MatterAttachmentRecord", () => {
  const routes = read("../../../api/src/caseops_api/api/routes/matters.py");
  const upload = routes.slice(
    routes.indexOf("def post_current_company_matter_attachment("),
    routes.indexOf(
      "async def patch_current_company_matter_attachment_metadata(",
    ),
  );
  assert.match(upload, /file: Annotated\[UploadFile, File\(\.\.\.\)\]/);
  assert.match(upload, /context: DocumentUploader/);
  assert.match(upload, /\) -> MatterAttachmentRecord:/);
  assert.match(
    upload,
    /expected_lifecycle_version: Annotated\[int \| None, Form\(ge=0\)\] = None/,
  );
  assert.match(upload, /expected_lifecycle_version=expected_lifecycle_version/);
  const api = read("./api.ts");
  assert.match(
    api,
    /body\.append\("expected_lifecycle_version", String\(expectedLifecycleVersion\)\)/,
  );
  const controller = read("./controller.ts");
  assert.match(
    controller,
    /api\.upload\(\s*prepared,\s*selection\.expectedLifecycleVersion,/,
  );
  const schemas = read("../../../api/src/caseops_api/schemas/matters.py");
  const attachment = schemas.slice(
    schemas.indexOf("class MatterAttachmentRecord("),
    schemas.indexOf("class MatterAttachmentPreviewResponse("),
  );
  assert.match(attachment, /sha256_hex: str/);
  assert.match(
    attachment,
    /processing_status: Literal\["pending", "indexed", "needs_ocr", "failed"\]/,
  );
  assert.equal(
    attachment.includes("scan_status:"),
    false,
    "Adopt a real scan receipt if the server gains one",
  );
  assert.match(schemas, /attachments: list\[MatterAttachmentRecord\]/);
  assert.match(schemas, /storage_governance: StorageUploadPolicy/);
});

test("MOB-25 root-owned picker owns the readable iOS SDK copy; Android keeps its URI and neither exports private bytes", () => {
  const native = read("./native.ts");
  assert.match(native, /copyToCacheDirectory: Platform\.OS === "ios"/);
  assert.match(native, /pickPrivateIosCopy\(/);
  assert.match(native, /privatePickerCopies\.cleanupPickedFile\(asset\)/);
  assert.match(native, /privatePickerCopies\.purge\(\)/);
  assert.match(native, /multiple: false/);
  assert.match(native, /base64: false/);
  const screen = read("../application/screens/FilesScreen.tsx");
  assert.match(
    screen,
    /onChooseFile: \(expectedLifecycleVersion: number\) => void/,
  );
  assert.match(screen, /onChooseFile\(workspace\.matter\.lifecycle_version\)/);
  assert.match(screen, /selectedFile: MatterFileSelection \| null/);
  assert.match(screen, /AppState\.addEventListener/);
  assert.match(screen, /controller\.dispose\(\)/);
  assert.equal(screen.includes("pickFile("), false);
  assert.equal(screen.includes("getDocumentAsync"), false);
  for (const forbidden of [
    "File.preview(",
    "File.canPreview(",
    "Linking.openURL",
    "Share.share",
    "WebBrowser",
    "WebView",
    "downloadFileAsync",
    "Authorization",
    "access_token",
  ]) {
    assert.equal(`${screen}\n${native}`.includes(forbidden), false, forbidden);
  }
});

test("MOB-21..26 planned native selectors exist independently of UI automation infrastructure", () => {
  const screen = read("../application/screens/FilesScreen.tsx");
  for (const id of [
    "matter-files",
    "files-inactive",
    "files-loading",
    "files-restricted",
    "files-error",
    "files-empty",
    "files-list",
    "files-count",
    "files-more",
    "files-matter-code",
    "files-matter-title",
    "files-matter-status",
    "files-scan-evidence",
    "files-upload-restricted",
    "files-selection",
    "files-upload",
    "files-selection-clear",
    "files-selection-error",
    "files-choose",
    "files-upload-cancel",
    "files-cleanup-error",
    "files-reload",
  ]) {
    assert.ok(screen.includes(`"${id}"`), `Missing native testID ${id}`);
  }
  for (const prefix of [
    "files-row-",
    "files-name-",
    "files-processing-",
    "files-source-",
    "files-source-details-",
    "files-hash-",
    "files-viewer-unavailable-",
    "files-upload-",
  ])
    assert.ok(
      screen.includes(prefix),
      `Missing native testID prefix ${prefix}`,
    );
});
