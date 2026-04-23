import { clearSession, getStoredContext, storeSession } from "@/lib/session";
import type { AuthSession } from "@/lib/api/schemas";

import { API_BASE_URL, ApiError, NetworkError } from "./config";

const REFRESH_PATH = "/api/auth/refresh";

// EG-001 (2026-04-23): cookie name + header pair for the
// double-submit CSRF check. Must match core/cookies.py and
// core/csrf.py on the server.
const CSRF_COOKIE = "caseops_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  // The CSRF cookie is intentionally NOT HttpOnly so we can read it
  // here. We never echo the session cookie itself — the browser
  // handles that via credentials: 'include'.
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  if (!match) return null;
  return decodeURIComponent(match.slice(CSRF_COOKIE.length + 1));
}

// Single-flight refresh: many components may hit a 401 simultaneously;
// we want exactly one POST to /auth/refresh per expiry window, and all
// queued requests to await that same promise.
let inflightRefresh: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (inflightRefresh) return inflightRefresh;
  // Cookie-first refresh: if we have any context at all, the browser
  // will send the session cookie with credentials: 'include'. We no
  // longer need to read the access token from JS.
  const haveContext = getStoredContext() !== null;
  if (!haveContext) return null;
  inflightRefresh = (async () => {
    try {
      const res = await fetch(resolveUrl(REFRESH_PATH), {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          // /refresh is exempt from CSRF (see core/csrf.py) but the
          // browser will still send the session cookie. The server
          // returns a fresh cookie + a new CSRF cookie value.
        },
      });
      if (!res.ok) {
        // Refresh itself unauthorized → the cookie is hard-expired.
        // Clear local context so the next /sign-in redirect is clean.
        if (res.status === 401) clearSession();
        return null;
      }
      const body = (await res.json()) as AuthSession;
      storeSession(body);
      // The body still carries access_token for one release as
      // bearer-fallback compat. The cookie path is what callers use.
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
  // EG-001 (2026-04-23): cookie-first auth. We only attach a Bearer
  // header when the caller explicitly passes ``token`` — that path
  // exists for SDK-style usage (tests, scripts, embedded automation)
  // and as a one-release fallback for in-flight web bundles deployed
  // before the cookie cutover. The default browser path now relies
  // entirely on ``credentials: 'include'`` for the session cookie
  // and the X-CSRF-Token header below for state-changing requests.
  const explicitToken = init.token;

  const requestHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  const hasBody = body !== undefined && body !== null;
  if (hasBody && !(body instanceof FormData) && !requestHeaders["Content-Type"]) {
    requestHeaders["Content-Type"] = "application/json";
  }
  if (explicitToken) {
    requestHeaders["Authorization"] = `Bearer ${explicitToken}`;
  }
  // CSRF: every state-changing request from the cookie path must
  // echo the JS-readable caseops_csrf cookie as the X-CSRF-Token
  // header. Skip when the caller passes an explicit bearer token —
  // the bearer path is exempt server-side too.
  const upperMethod = method.toUpperCase();
  if (
    !explicitToken &&
    MUTATING_METHODS.has(upperMethod) &&
    !requestHeaders[CSRF_HEADER]
  ) {
    const csrf = readCsrfCookie();
    if (csrf) {
      requestHeaders[CSRF_HEADER] = csrf;
    }
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
      // credentials: 'include' makes the browser send the session
      // cookie cross-origin (web: caseops.ai → api: api.caseops.ai).
      // CORSMiddleware on the server already sets
      // Access-Control-Allow-Credentials: true to allow this.
      credentials: "include",
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

    // Auto-refresh on expired-token 401. One retry, no recursion on
    // the refresh endpoint itself. The cookie path drives this for
    // browser callers; the bearer-token path also benefits when the
    // caller passed an explicit ``token`` (the refresh response will
    // include a fresh access_token in the body).
    if (
      !_retry &&
      response.status === 401 &&
      problemType === "invalid_token" &&
      !path.endsWith(REFRESH_PATH)
    ) {
      const fresh = await refreshAccessToken();
      if (fresh || explicitToken === undefined) {
        // Cookie path: just retry — the browser now holds a fresh
        // session cookie. Bearer path: pass the new token so the
        // header is rebuilt with it.
        return apiRequest<TResponse>(
          path,
          fresh ? { ...init, token: fresh } : init,
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
