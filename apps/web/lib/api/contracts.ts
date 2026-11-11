import { apiBlobRequest, apiRequest } from "./client";
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

export async function fetchContractAttachmentBlob(contractId: string, attachmentId: string, signal?: AbortSignal) {
  const response = await apiBlobRequest(`/api/contracts/${contractId}/attachments/${attachmentId}/download`, { signal });
  return response.blob();
}

export function validateContractDocxPreview(contractId: string, attachmentId: string, signal?: AbortSignal) {
  return apiRequest(`/api/contracts/${contractId}/attachments/${attachmentId}/preview`, { signal });
}
