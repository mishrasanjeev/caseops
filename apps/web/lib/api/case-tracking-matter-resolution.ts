import { apiRequest } from "@/lib/api/client";
import type {
  CaseTrackingBookmarkRecord,
  CaseTrackingSearchInput,
  CaseTrackingSearchResult,
} from "@/lib/api/endpoints";

export type MatterCaseCandidate = CaseTrackingSearchResult & { link_token: string };
export type MatterAwareSearchResult = CaseTrackingSearchResult & { link_token?: string | null };
export type MatterAwareSearchResponse = {
  provider: string;
  results: MatterAwareSearchResult[];
};

export type MatterCaseResolutionResponse = {
  provider: string;
  status: "matched" | "multiple_matches" | "no_match" | "insufficient_identifiers";
  results: MatterCaseCandidate[];
};

export async function resolveMatterCase(matterId: string): Promise<MatterCaseResolutionResponse> {
  return apiRequest(`/api/case-tracking/matters/${encodeURIComponent(matterId)}/resolve`, {
    method: "POST",
  });
}

export async function searchMatterCases({
  matterId,
  input,
}: {
  matterId: string;
  input: CaseTrackingSearchInput;
}): Promise<MatterAwareSearchResponse> {
  return apiRequest("/api/case-tracking/search", {
    method: "POST",
    body: { ...input, matter_id: matterId },
  });
}

export async function linkMatterCase({
  matterId,
  linkToken,
}: {
  matterId: string;
  linkToken: string;
}): Promise<CaseTrackingBookmarkRecord> {
  return apiRequest(`/api/case-tracking/matters/${encodeURIComponent(matterId)}/link`, {
    method: "POST",
    body: { link_token: linkToken },
  });
}
