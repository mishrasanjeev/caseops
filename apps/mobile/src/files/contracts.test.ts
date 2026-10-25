import { test } from "node:test";
import assert from "node:assert/strict";
import { ContractError } from "../domain/contracts.ts";
import {
  decodeFilesWorkspace,
  decodeMatterFile,
  matchesSelection,
  uploadRestriction,
} from "./contracts.ts";
import {
  attachmentFixture,
  filesWorkspaceFixture,
  scope,
  selection,
} from "./test-fixtures.ts";
import { matterFixture } from "../domain/test-fixtures.ts";

test("MOB-21 exact workspace attachments retain original source metadata without inventing versions or scan facts", () => {
  const file = attachmentFixture({
    original_filename: "x".repeat(251) + ".txt",
    document_type: "notice",
    document_date: "2026-10-25",
    lifecycle_stage: "pre_litigation",
    linked_court_order_id: "order-test",
  });
  const result = decodeFilesWorkspace(
    filesWorkspaceFixture({ attachments: [file] }),
    scope,
  );
  assert.equal(result.attachments[0].original_filename, file.original_filename);
  assert.equal(result.attachments[0].document_date, "2026-10-25");
  assert.equal(result.attachments[0].linked_court_order_id, "order-test");
  assert.equal(result.attachments[0].processing_status, "pending");
  assert.equal("scan_status" in result.attachments[0], false);
  assert.equal("current_version_id" in result.attachments[0], false);
  assert.deepEqual(
    decodeFilesWorkspace(filesWorkspaceFixture(), scope).attachments,
    [],
  );
});

test("MOB-21 missing, duplicate, foreign and malformed canonical file fields are errors, not empty lists", () => {
  const invalid = [
    { attachments: undefined },
    { attachments: null },
    { documents: [], attachments: undefined },
    { matter: matterFixture({ id: "other-matter" }) },
    { storage_governance: { company_id: "other-company" } },
    { attachments: [attachmentFixture(), attachmentFixture()] },
    ...[
      { matter_id: "other-matter" },
      { original_filename: 1 },
      { original_filename: "" },
      { content_type: undefined },
      { processing_status: "clean" },
      { processing_status: null },
      { size_bytes: -1 },
      { size_bytes: "42" },
      { sha256_hex: "unknown" },
      { uploaded_by_name: undefined },
      { processed_at: undefined },
      { created_at: "not a date" },
      { document_date: "2026-02-30" },
    ].map((change) => ({ attachments: [attachmentFixture(change)] })),
  ];
  for (const change of invalid)
    assert.throws(
      () => decodeFilesWorkspace(filesWorkspaceFixture(change), scope),
      ContractError,
    );
  assert.throws(
    () =>
      decodeFilesWorkspace(
        filesWorkspaceFixture({
          attachments: Array.from({ length: 1001 }, (_, i) =>
            attachmentFixture({ id: `synthetic-${i}` }),
          ),
        }),
        scope,
      ),
    ContractError,
  );
});

test("MOB-22..23 processing failures are retained metadata, never a clean malware verdict", () => {
  for (const processing_status of [
    "pending",
    "indexed",
    "needs_ocr",
    "failed",
  ]) {
    const file = decodeMatterFile(
      attachmentFixture({
        processing_status,
        extraction_error: "Synthetic extraction failure",
      }),
      scope.matterId,
    );
    assert.equal(file.processing_status, processing_status);
    assert.equal(file.extraction_error, "Synthetic extraction failure");
  }
});

test("MOB-23 terminal, unknown lifecycle, capability and quota states block upload while preserving retained list reads", () => {
  for (const status of ["disposed", "archived", "unknown", "Active"]) {
    const workspace = decodeFilesWorkspace(
      filesWorkspaceFixture({
        matter: matterFixture({ status }),
        attachments: [attachmentFixture()],
      }),
      scope,
    );
    assert.match(
      uploadRestriction(workspace, ["documents:upload"])!,
      /read-only/,
    );
    assert.equal(workspace.attachments.length, 1);
  }
  const workspace = decodeFilesWorkspace(filesWorkspaceFixture(), scope);
  assert.match(
    uploadRestriction(workspace, ["matters:write"])!,
    /cannot upload/,
  );
  assert.match(
    uploadRestriction(
      { ...workspace, storage: { ...workspace.storage, state: "hard_limit" } },
      ["documents:upload"],
    )!,
    /storage is full/,
  );
  for (const status of ["intake", "active", "on_hold"])
    assert.equal(
      uploadRestriction(
        { ...workspace, matter: { ...workspace.matter, status } },
        ["documents:upload"],
      ),
      null,
    );
});

test("MOB-26 selected asset must match all externally coordinated account and Matter identities", () => {
  assert.equal(matchesSelection(selection, scope), true);
  for (const change of [
    { userId: "other-user" },
    { companyId: "other-company" },
    { matterId: "other-matter" },
    { sessionKey: "other-sign-in-generation" },
  ])
    assert.equal(matchesSelection({ ...selection, ...change }, scope), false);
});
