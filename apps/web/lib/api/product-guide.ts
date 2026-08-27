import { apiRequest } from "@/lib/api/client";

export type ProductGuideSearchResult = {
  kind: "guide" | "command";
  id: string;
  title: string;
  summary: string;
  href: string;
  required_capabilities: string[];
};

export type ProductGuidePermission = {
  required_capabilities: string[];
  message: string;
};

export type ProductGuideSearchResponse = {
  status: "matched" | "permission_required" | "no_match";
  version_status: "current" | "stale";
  content_version: string;
  catalog_fingerprint: string;
  query: string;
  results: ProductGuideSearchResult[];
  permission: ProductGuidePermission | null;
  suggested_queries: string[];
};

export function searchProductGuide(
  query: string,
  options: { clientVersion: string; limit?: number; signal?: AbortSignal },
): Promise<ProductGuideSearchResponse> {
  const params = new URLSearchParams({
    q: query.trim(),
    client_version: options.clientVersion,
    limit: String(options.limit ?? 8),
  });
  return apiRequest<ProductGuideSearchResponse>(`/api/product-guide/search?${params}`, {
    signal: options.signal,
    timeoutMs: 15_000,
  });
}
