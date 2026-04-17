import { getStoredToken } from "@/lib/session";

import { API_BASE_URL, ApiError, NetworkError } from "./config";

export type ApiRequestInit = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  token?: string | null;
  signal?: AbortSignal;
};

function resolveUrl(path: string): string {
  if (path.startsWith("http")) return path;
  if (!path.startsWith("/")) return `${API_BASE_URL}/${path}`;
  return `${API_BASE_URL}${path}`;
}

function extractDetail(data: unknown, fallback: string): string {
  if (typeof data === "string") return data;
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    const detail = obj.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            const msg = (item as Record<string, unknown>).msg;
            if (typeof msg === "string") return msg;
          }
          return JSON.stringify(item);
        })
        .join(", ");
    }
  }
  return fallback;
}

export async function apiRequest<TResponse>(
  path: string,
  init: ApiRequestInit = {},
): Promise<TResponse> {
  const { method = "GET", body, headers = {}, signal } = init;
  const resolvedToken = init.token !== undefined ? init.token : getStoredToken();

  const requestHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  const hasBody = body !== undefined && body !== null;
  if (hasBody && !(body instanceof FormData) && !requestHeaders["Content-Type"]) {
    requestHeaders["Content-Type"] = "application/json";
  }
  if (resolvedToken) {
    requestHeaders["Authorization"] = `Bearer ${resolvedToken}`;
  }

  const serializedBody = hasBody
    ? body instanceof FormData
      ? body
      : JSON.stringify(body)
    : undefined;

  let response: Response;
  try {
    response = await fetch(resolveUrl(path), {
      method,
      headers: requestHeaders,
      body: serializedBody,
      signal,
    });
  } catch (err) {
    // fetch throws TypeError for DNS / offline / CORS preflight failure.
    // AbortError also reaches here but is re-thrown untouched so callers
    // can distinguish a user-initiated cancellation.
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    throw new NetworkError(
      "Could not reach the workspace API. Check your connection and try again.",
      err,
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  let parsed: unknown = null;
  if (contentType.includes("application/json")) {
    parsed = await response.json().catch(() => null);
  } else {
    const text = await response.text().catch(() => "");
    parsed = text;
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      extractDetail(parsed, `Request failed (${response.status}).`),
      parsed,
    );
  }
  return parsed as TResponse;
}
