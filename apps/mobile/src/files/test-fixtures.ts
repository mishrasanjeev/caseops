import { createHash } from "node:crypto";
import { matterFixture } from "../domain/test-fixtures.ts";
import type { FilesScope, MatterFileSelection } from "./contracts.ts";

export const scope: FilesScope = {
  companyId: "company-test",
  userId: "user-test",
  matterId: "matter-test",
  sessionKey: "synthetic-sign-in-1",
};
export const bytes = Buffer.from("Synthetic upload fixture. Not legal data.\n");
export const hash = createHash("sha256").update(bytes).digest("hex");
export const selection: MatterFileSelection = {
  ...scope,
  expectedLifecycleVersion: matterFixture().lifecycle_version,
  asset: {
    uri: "content://synthetic-provider/file/1",
    name: "synthetic.txt",
    mimeType: "text/plain",
    size: bytes.length,
  },
};
export function attachmentFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "attachment-test",
    matter_id: scope.matterId,
    uploaded_by_membership_id: "membership-test",
    uploaded_by_name: "Synthetic uploader",
    original_filename: "synthetic.txt",
    content_type: "text/plain",
    size_bytes: bytes.length,
    sha256_hex: hash,
    processing_status: "pending",
    extracted_char_count: 0,
    extraction_error: null,
    processed_at: null,
    latest_job: null,
    document_type: null,
    lifecycle_stage: null,
    document_date: null,
    linked_court_order_id: null,
    hearing_id: null,
    created_at: "2026-10-25T06:00:00Z",
    ...overrides,
  };
}
export function filesWorkspaceFixture(overrides: Record<string, unknown> = {}) {
  return {
    matter: matterFixture(),
    storage_governance: {
      company_id: scope.companyId,
      used_bytes: 0,
      quota_bytes: 104857600,
      remaining_bytes: 104857600,
      max_upload_size_bytes: 52428800,
      state: "ok",
      warning_threshold_percent: 80,
    },
    attachments: [],
    // The production workspace contains these siblings; files does not invent a documents key.
    assignee: null,
    available_assignees: [],
    tasks: [],
    cause_list_entries: [],
    court_orders: [],
    court_sync_runs: [],
    court_sync_jobs: [],
    time_entries: [],
    invoices: [],
    notes: [],
    hearings: [],
    activity: [],
    ...overrides,
  };
}
