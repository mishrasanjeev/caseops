import assert from "node:assert/strict";
import test from "node:test";
import { createNativePreparationDiagnostics, nativePickedDomain, nativePreparationFailureStep } from "./native-preparation-diagnostics.ts";

test("native preparation diagnostics are explicitly off by default and never replace the original error", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(false, value => emitted.push(value));
  const original = new Error("private URI and content must never be reported");
  assert.throws(() => diagnostic.sync("source-open", () => { throw original; }), error => error === original);
  diagnostic.report(); assert.deepEqual(emitted, []);
});
test("QA preparation failure reports only its fixed first failing operation even when cleanup also fails", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  diagnostic.begin();
  assert.throws(() => diagnostic.sync("source-open", () => { throw new Error("secret source path"); }));
  assert.throws(() => diagnostic.sync("target-close", () => { throw new Error("secret target path"); }));
  diagnostic.report();
  assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "source-open" }]);
});
test("asynchronous native read failures retain identity and expose no exception message or file bytes", async () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  const original = new Error("file:///private/source?secret=value");
  await assert.rejects(diagnostic.async("source-read", async () => { throw original; }), error => error === original);
  diagnostic.report();assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "source-read" }]);
});
test("a new preparation clears the earlier failure and successful operations keep their original results", async () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  diagnostic.failed("source-read"); diagnostic.begin();
  assert.equal(diagnostic.sync("selected-size", () => 24000), 24000);
  assert.equal(await diagnostic.async("digest", async () => "synthetic digest"), "synthetic digest");
  diagnostic.report();assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "preparation-policy" }]);
});
test("unexpected runtime diagnostic values are rejected instead of reflecting a supplied string", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  assert.throws(() => diagnostic.failed("file:///private/path" as never), /Invalid preparation diagnostic/);
  assert.deepEqual(emitted, []);
});
test("diagnostics observe and return the original native promise without adding an await boundary", async () => {
  const diagnostic = createNativePreparationDiagnostics(true, () => {});
  const pending = Promise.resolve(new Uint8Array([1, 2, 3]));
  assert.equal(diagnostic.async("source-read", () => pending), pending);
  assert.deepEqual(await pending, new Uint8Array([1, 2, 3]));
});
test("QA failure steps remain memory-only and never mutate or serialize the original exception", async () => {
  const error = Object.freeze(new Error("file:///private/source?token=secret"));
  const diagnostic = createNativePreparationDiagnostics(true, () => {});
  diagnostic.failed("source-open");diagnostic.report(error);
  assert.equal(nativePreparationFailureStep(error), "source-open");
  assert.deepEqual(Object.keys(error), []);
  const ordinary = new Error("another private value"), disabled = createNativePreparationDiagnostics(false, () => assert.fail());
  disabled.failed("source-read");disabled.report(ordinary);
  assert.equal(nativePreparationFailureStep(ordinary), undefined);
  assert.equal(nativePreparationFailureStep("source-open"), undefined);
});

const roots = { imports: "file:///app/tmp/ai.caseops.mobile.dev-Inbox/", cache: "file:///app/Library/Caches/", documents: "file:///app/Documents/" };
const picked = `${roots.imports}private.txt`;
test("passive picked domains use normalized exact Inbox files and directory boundaries", () => {
  for (const [uri, expected] of [[picked, "import"], [`${roots.cache}DocumentPicker/copy.txt`, "cache"],
    [`${roots.documents}copy.txt`, "documents"], ["file:///provider/copy.txt", "external-file"],
    ["content://provider/item", "content"], ["https://example.invalid/file", "other"],
    [`${roots.imports}nested/copy.txt`, "external-file"], ["file:///app/Library/Caches-foreign/copy.txt", "external-file"],
    ["file:///app/Documents-other/copy.txt", "external-file"], ["file:///app/Library/Caches/../private.txt", "other"],
    ["file://foreign/app/private.txt", "other"], [`${picked}?secret=value`, "other"],
    [`${roots.cache}nested%2fprivate.txt`, "other"], ["file:///app/private%00.txt", "other"]] as const) {
    assert.equal(nativePickedDomain(uri, roots), expected);
  }
  assert.equal(nativePickedDomain("content://android/provider", { cache: roots.cache, documents: roots.documents }), "content");
});
test("begin preserves the exact picked reference and successful owned deletion trace", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  diagnostic.selected(picked, "import"); diagnostic.deleted(picked); diagnostic.begin(); diagnostic.unavailable(picked); diagnostic.report();
  assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "selected-unavailable-import-deleted" }]);
  assert.equal(JSON.stringify(emitted).includes("private.txt"), false);
});
test("different leaf deletion and sibling root deletion cannot mark the selected reference deleted", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  diagnostic.selected(picked, "import"); diagnostic.deleted(`${roots.imports}other.txt`);
  diagnostic.deletedUnder("file:///app/tmp/ai.caseops.mobile.dev-Inbox-other/");
  diagnostic.begin(); diagnostic.unavailable(picked); diagnostic.report();
  assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "selected-unavailable-import" }]);
});
test("a successful owned-directory deletion marks only a normalized child path", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  const uri = `${roots.cache}caseops-matter-files-v1/copy.txt`;
  diagnostic.selected(uri, "cache"); diagnostic.deletedUnder(`${roots.cache}caseops-matter-files-v1/`);
  diagnostic.begin(); diagnostic.unavailable(uri); diagnostic.report();
  assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "selected-unavailable-cache-deleted" }]);
});
test("each new selection resets deletion evidence even when the URI string is reused", () => {
  const emitted: unknown[] = [], diagnostic = createNativePreparationDiagnostics(true, value => emitted.push(value));
  diagnostic.selected(picked, "import"); diagnostic.deleted(picked);
  diagnostic.selected(picked, "import"); diagnostic.begin(); diagnostic.unavailable(picked); diagnostic.report();
  diagnostic.begin(); diagnostic.unavailable(`${roots.imports}unregistered.txt`); diagnostic.report();
  assert.deepEqual(emitted, [{ event: "caseops-file-preparation-failed", step: "selected-unavailable-import" },
    { event: "caseops-file-preparation-failed", step: "selected-exists" }]);
});
test("disabled diagnostics retain no selected trace or failure association and reject unknown enums", () => {
  const diagnostic = createNativePreparationDiagnostics(false, () => assert.fail());
  const error = Object.freeze(new Error("private path"));
  diagnostic.selected(picked, "import"); diagnostic.deleted(picked); diagnostic.deletedUnder(roots.imports);
  diagnostic.begin(); diagnostic.unavailable(picked); diagnostic.report(error);
  assert.equal(nativePreparationFailureStep(error), undefined);
  assert.throws(() => diagnostic.selected(picked, "private-value" as never), /Invalid preparation domain/);
  assert.throws(() => diagnostic.failed("selected-unavailable-unknown" as never), /Invalid preparation diagnostic/);
});
