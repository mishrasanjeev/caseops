import { isApiErrorShape, isNetworkError } from "@/lib/api/config";

const TRANSIENT_READ_STATUSES = new Set([408, 429, 500, 502, 503, 504]);

export function showIpListError(query: {
  isError: boolean;
  isFetchNextPageError: boolean;
  data: unknown;
  error: unknown;
}): boolean {
  if (!query.isError) return false;
  if (!query.data || !query.isFetchNextPageError) return true;
  // Retain cached pages only for known availability failures, never access denials.
  if (isNetworkError(query.error)) return false;
  return !(
    isApiErrorShape(query.error) && TRANSIENT_READ_STATUSES.has(query.error.status)
  );
}
