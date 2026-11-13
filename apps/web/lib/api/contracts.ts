import { apiBlobDataRequest, apiRequest } from "./client";
import { ApiError } from "./config";
import type { ContractTypeKey } from "./endpoints";

export type EditableContractMetadata = {
  title: string;
  counterparty_name: string | null;
  contract_type: string;
  contract_type_key: ContractTypeKey | null;
  contract_type_notes: string | null;
  effective_on: string | null;
  expires_on: string | null;
  renewal_on: string | null;
  auto_renewal: boolean;
  summary: string | null;
  updated_at: string;
};

export function updateContractDetails(
  contractId: string,
  fields: Partial<Omit<EditableContractMetadata, "updated_at">> & { expected_updated_at: string },
) {
  return apiRequest<EditableContractMetadata>(`/api/contracts/${contractId}/metadata`, {
    method: "PATCH", body: fields,
  });
}

export type ContractAttachmentSource = {
  original_filename: string; content_type: string | null; size_bytes: number; sha256_hex: string;
};

export const CONTRACT_PREVIEW_MAX_BYTES = 32 * 1024 * 1024;
export const CONTRACT_ORIGINAL_MAX_BYTES = 50 * 1024 * 1024;
const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function sourceMime(source: ContractAttachmentSource): string | null {
  const declared = source.content_type?.split(";", 1)[0].trim().toLowerCase() || null;
  const name = source.original_filename.toLowerCase();
  if (name.endsWith(".pdf")) return !declared || declared === "application/pdf" ? "application/pdf" : null;
  if (name.endsWith(".docx")) return !declared || [DOCX_MIME, "application/octet-stream", "application/zip"].includes(declared) ? DOCX_MIME : null;
  return declared ?? "application/octet-stream";
}

export async function fetchContractAttachmentBlob(
  contractId: string, attachmentId: string, source: ContractAttachmentSource,
  signal?: AbortSignal, preview = false,
) {
  const limit = preview ? CONTRACT_PREVIEW_MAX_BYTES : CONTRACT_ORIGINAL_MAX_BYTES;
  const expectedMime = sourceMime(source);
  if (Number.isSafeInteger(source.size_bytes) && source.size_bytes > limit) {
    throw new ApiError(413, preview
      ? "This document exceeds the private viewer limit; download the original instead."
      : "This document exceeds the admitted original-download limit.", null);
  }
  if (!Number.isSafeInteger(source.size_bytes) || source.size_bytes <= 0
    || expectedMime === null
    || !/^[0-9a-f]{64}$/.test(source.sha256_hex)) {
    throw new ApiError(409, "The attachment source changed. Reload the contract.", null);
  }
  const { blob, headers } = await apiBlobDataRequest(
    `/api/contracts/${contractId}/attachments/${attachmentId}/${preview ? "preview" : "download"}`,
    { signal, maxBytes: source.size_bytes, headers: { Accept: expectedMime } },
  );
  signal?.throwIfAborted();
  const mime = headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  signal?.throwIfAborted();
  if (blob.size !== source.size_bytes || digest !== source.sha256_hex
    || mime !== expectedMime
    || preview && !["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"].includes(mime ?? "")) {
    throw new ApiError(409, "The attachment source changed. Reload the contract.", null);
  }
  return blob;
}
