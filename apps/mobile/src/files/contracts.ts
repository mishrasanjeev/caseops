import {
  array,
  ContractError,
  dateOnly,
  decodeMatter,
  object,
  string,
} from "../domain/contracts.ts";
import type { Matter } from "../domain/contracts.ts";

export type MatterFileAsset = Readonly<{
  uri: string;
  name: string;
  mimeType?: string;
  size?: number;
}>;
export type MatterFileSelection = Readonly<{
  companyId: string;
  userId: string;
  matterId: string;
  sessionKey: string;
  expectedLifecycleVersion: number;
  asset: MatterFileAsset;
}>;
export type FilesScope = Readonly<{
  companyId: string;
  userId: string;
  matterId: string;
  sessionKey: string;
}>;
export type MatterFile = {
  id: string;
  matter_id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256_hex: string;
  processing_status: "pending" | "indexed" | "needs_ocr" | "failed";
  extracted_char_count: number;
  extraction_error: string | null;
  processed_at: string | null;
  uploaded_by_name: string | null;
  created_at: string;
  document_type: string | null;
  lifecycle_stage: string | null;
  document_date: string | null;
  linked_court_order_id: string | null;
  hearing_id: string | null;
};
export type UploadPolicy = {
  company_id: string;
  max_upload_size_bytes: number;
  remaining_bytes: number | null;
  state: "unlimited" | "ok" | "warning" | "hard_limit";
};
export type FilesWorkspace = {
  matter: Matter;
  attachments: MatterFile[];
  storage: UploadPolicy;
};

export function identity(value: unknown, field = "file identity"): string {
  const result = string(value, field, 200);
  if (!result.trim()) throw new ContractError(field);
  return result;
}
function integer(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw new ContractError(field);
  return value;
}
function nullable(value: unknown, field: string): string | null {
  if (value === null) return null;
  return string(value, field);
}
function timestamp(value: unknown, field: string): string {
  const result = string(value, field, 100);
  if (!result || !Number.isFinite(Date.parse(result)))
    throw new ContractError(field);
  return result;
}
export function decodeMatterFile(value: unknown, matterId: string): MatterFile {
  const row = object(value, "matter attachment");
  if (identity(row.matter_id, "file parent") !== matterId)
    throw new ContractError("file parent");
  if (
    !["pending", "indexed", "needs_ocr", "failed"].includes(
      String(row.processing_status),
    )
  )
    throw new ContractError("file processing state");
  const hash = string(row.sha256_hex, "source hash", 64);
  if (!/^[a-f0-9]{64}$/.test(hash)) throw new ContractError("source hash");
  const filename = string(row.original_filename, "original filename", 255);
  if (!filename.trim()) throw new ContractError("original filename");
  const optionalMetadata = (key: string) =>
    row[key] == null ? null : string(row[key], key);
  return {
    id: identity(row.id),
    matter_id: matterId,
    original_filename: filename,
    content_type: nullable(row.content_type, "content type"),
    size_bytes: integer(row.size_bytes, "file size"),
    sha256_hex: hash,
    processing_status: row.processing_status as MatterFile["processing_status"],
    extracted_char_count: integer(
      row.extracted_char_count,
      "extracted character count",
    ),
    extraction_error: nullable(row.extraction_error, "extraction error"),
    processed_at:
      row.processed_at === null
        ? null
        : timestamp(row.processed_at, "processing timestamp"),
    uploaded_by_name: nullable(row.uploaded_by_name, "uploader"),
    created_at: timestamp(row.created_at, "upload timestamp"),
    document_type: optionalMetadata("document_type"),
    lifecycle_stage: optionalMetadata("lifecycle_stage"),
    document_date:
      row.document_date == null ? null : dateOnly(row.document_date),
    linked_court_order_id: optionalMetadata("linked_court_order_id"),
    hearing_id: optionalMetadata("hearing_id"),
  };
}
export function decodeFilesWorkspace(
  value: unknown,
  scope: Pick<FilesScope, "matterId" | "companyId">,
): FilesWorkspace {
  const row = object(value, "files workspace");
  const matter = decodeMatter(row.matter);
  if (matter.id !== scope.matterId) throw new ContractError("workspace parent");
  const storage = object(row.storage_governance, "storage policy");
  if (storage.company_id !== scope.companyId)
    throw new ContractError("storage workspace");
  if (
    !["unlimited", "ok", "warning", "hard_limit"].includes(
      String(storage.state),
    )
  )
    throw new ContractError("storage state");
  const attachments = array(row.attachments, "matter files", (item) =>
    decodeMatterFile(item, scope.matterId),
  );
  if (new Set(attachments.map((file) => file.id)).size !== attachments.length)
    throw new ContractError("duplicate file identity");
  return {
    matter,
    attachments,
    storage: {
      company_id: scope.companyId,
      max_upload_size_bytes: integer(
        storage.max_upload_size_bytes,
        "upload limit",
      ),
      remaining_bytes:
        storage.remaining_bytes === null
          ? null
          : integer(storage.remaining_bytes, "storage remaining"),
      state: storage.state as UploadPolicy["state"],
    },
  };
}
export function matchesSelection(
  selection: MatterFileSelection,
  scope: FilesScope,
): boolean {
  return (
    selection.companyId === scope.companyId &&
    selection.userId === scope.userId &&
    selection.sessionKey === scope.sessionKey &&
    selection.matterId === scope.matterId
  );
}
export function uploadRestriction(
  workspace: FilesWorkspace,
  capabilities: readonly string[],
): string | null {
  if (!capabilities.includes("documents:upload"))
    return "This account cannot upload documents.";
  if (!["intake", "active", "on_hold"].includes(workspace.matter.status))
    return "This matter is read-only. Uploads are unavailable.";
  if (
    workspace.storage.state === "hard_limit" ||
    workspace.storage.remaining_bytes === 0
  )
    return "Workspace storage is full. An administrator must free space before uploading.";
  if (workspace.storage.max_upload_size_bytes === 0)
    return "Uploads are unavailable under the current storage policy.";
  return null;
}
