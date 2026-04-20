import { clearSession, getStoredToken, storeSession } from "@/lib/session";
import type { AuthSession } from "@/lib/api/schemas";

import { API_BASE_URL, ApiError, NetworkError } from "./config";

const REFRESH_PATH = "/api/auth/refresh";

// Single-flight refresh: many components may hit a 401 simultaneously;
// we want exactly one POST to /auth/refresh per expiry window, and all
// queued requests to await that same promise.
let inflightRefresh: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (inflightRefresh) return inflightRefresh;
  const currentToken = getStoredToken();
  if (!currentToken) return null;
  inflightRefresh = (async () => {
    try {
      const res = await fetch(resolveUrl(REFRESH_PATH), {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${currentToken}`,
        },
      });
      if (!res.ok) {
        // Refresh itself unauthorized → the token is hard-expired.
        // Clear so the next /sign-in redirect is clean.
        if (res.status === 401) clearSession();
        return null;
      }
      const body = (await res.json()) as AuthSession;
      storeSession(body);
      return body.access_token;
    } catch {
      return null;
    } finally {
      // Let the next expiry cycle start a new refresh.
      setTimeout(() => {
        inflightRefresh = null;
      }, 0);
    }
  })();
  return inflightRefresh;
}

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
  _retry = false,
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
    // RFC 7807 responses carry a machine-readable `type` slug; fall
    // back to `null` when the response is a plain {detail: "…"}.
    let problemType: string | null = null;
    if (parsed && typeof parsed === "object") {
      const maybe = (parsed as Record<string, unknown>).type;
      if (typeof maybe === "string" && maybe.length > 0) {
        problemType = maybe;
      }
    }

    // Auto-refresh on expired-token 401. One retry, no recursion on the
    // refresh endpoint itself, and only when a token was present on the
    // original call (an explicit `token: null` override opts out).
    if (
      !_retry &&
      response.status === 401 &&
      problemType === "invalid_token" &&
      resolvedToken &&
      !path.endsWith(REFRESH_PATH)
    ) {
      const fresh = await refreshAccessToken();
      if (fresh) {
        return apiRequest<TResponse>(
          path,
          { ...init, token: fresh },
          true,
        );
      }
    }

    throw new ApiError(
      response.status,
      extractDetail(parsed, `Request failed (${response.status}).`),
      parsed,
      problemType,
    );
  }
  return parsed as TResponse;
}
