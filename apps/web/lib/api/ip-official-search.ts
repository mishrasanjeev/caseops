import { apiRequest } from "./client";

export type IpOfficialSearchReviewItem = { field: string; reason: string };

export type IpOfficialSearchMatch = {
  docket_id: string;
  docket_title: string;
  application_id: string;
  application_number: string;
};

export type IpOfficialSearchImport = {
  id: string;
  source_kind: "ipindia_estatus" | "ipindia_eregister" | "ipindia_public_search";
  official_url: string;
  search_query: Record<string, unknown>;
  original_filename: string;
  content_kind: "html" | "pdf";
  byte_size: number;
  file_sha256: string;
  parser_version: string;
  parse_status: "parsed" | "needs_review" | "unreadable";
  fields: Record<string, unknown>;
  published_values: Record<string, string>;
  review_items: IpOfficialSearchReviewItem[];
  attribution: string;
  resolution_status: "pending" | "linked" | "staged_new_record" | "dismissed";
  resolution_reason: string | null;
  linked_docket_id: string | null;
  linked_application_id: string | null;
  registry_snapshot_id: string | null;
  import_job_id: string | null;
  uploaded_by_membership_id: string;
  uploaded_by_label: string | null;
  uploaded_at: string;
  resolved_at: string | null;
  version: number;
  matches: IpOfficialSearchMatch[];
};

export type IpOfficialSearchImportPage = {
  records: IpOfficialSearchImport[];
  total: number;
  limit: number;
  offset: number;
};

const BASE = "/api/ip/official-search/imports";

export async function listIpOfficialSearchImports(): Promise<IpOfficialSearchImportPage> {
  return apiRequest(`${BASE}?limit=25`);
}

export async function uploadIpOfficialSearchPage(input: {
  metadata: Record<string, unknown>;
  file: File;
}): Promise<{ record: IpOfficialSearchImport; duplicate_upload: boolean }> {
  const body = new FormData();
  body.append("metadata_json", JSON.stringify(input.metadata));
  body.append("upload", input.file);
  return apiRequest(BASE, { method: "POST", body });
}

export async function linkIpOfficialSearchImport(input: {
  importId: string;
  expectedVersion: number;
  applicationId: string;
}): Promise<{ record: IpOfficialSearchImport; registry_link_id: string; diff_count: number; no_change: boolean }> {
  return apiRequest(`${BASE}/${encodeURIComponent(input.importId)}/link`, {
    method: "POST",
    body: { expected_version: input.expectedVersion, application_id: input.applicationId },
  });
}

export async function stageIpOfficialSearchImport(input: {
  importId: string;
  expectedVersion: number;
}): Promise<IpOfficialSearchImport> {
  return apiRequest(`${BASE}/${encodeURIComponent(input.importId)}/stage-new-record`, {
    method: "POST",
    body: { expected_version: input.expectedVersion },
  });
}

export async function dismissIpOfficialSearchImport(input: {
  importId: string;
  expectedVersion: number;
  reason: string;
}): Promise<IpOfficialSearchImport> {
  return apiRequest(`${BASE}/${encodeURIComponent(input.importId)}/dismiss`, {
    method: "POST",
    body: { expected_version: input.expectedVersion, reason: input.reason },
  });
}
