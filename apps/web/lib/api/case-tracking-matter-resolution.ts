import { apiRequest } from "@/lib/api/client";
import type { CaseTrackingSearchResult } from "@/lib/api/endpoints";

export type MatterCaseResolutionResponse = {
  provider: string;
  status: "matched" | "multiple_matches" | "no_match" | "insufficient_identifiers";
  results: CaseTrackingSearchResult[];
};

export async function resolveMatterCase(matterId: string): Promise<MatterCaseResolutionResponse> {
  return apiRequest(`/api/case-tracking/matters/${encodeURIComponent(matterId)}/resolve`, {
    method: "POST",
  });
}
