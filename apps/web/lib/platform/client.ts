import { z } from "zod";

import { consumeResponseWithTimeout } from "@/lib/api/client";
import { API_BASE_URL, NetworkError } from "@/lib/api/config";

import { activityReport } from "./activity-schema";
import {
  consoleAccepted, consoleAdminRecord, consoleAdminsResponse, consoleAuthState, consoleComplete,
  consoleEnrollmentResponse, consoleInvitationResponse, consoleOverview, consoleReportPage, consoleSignedOut,
} from "./schemas";

const PREFIX = "/api/platform-console";
export const PLATFORM_SESSION_INVALIDATED = "caseops:platform-session-invalidated";
let authEpoch = 0;
export function advancePlatformSessionEpoch() { authEpoch += 1; }
const PREAUTH = new Set(["/auth/login", "/auth/invitations/complete", "/auth/invitations/resend", "/auth/password-reset/start", "/auth/password-reset/complete"]);

export class ConsoleError extends Error {
  constructor(public readonly status: number, public readonly kind: "unauthorized" | "forbidden" | "invalid" | "unavailable" | "csrf" | "contract" | "mfa_invalid") {
    super(kind);
    this.name = "ConsoleError";
  }
}

function csrfCookie(): string | null {
  const value = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("caseops_console_csrf="));
  if (!value) return null;
  try { return decodeURIComponent(value.slice("caseops_console_csrf=".length)); } catch { return null; }
}

async function isInvalidMfaFactor(response: Response): Promise<boolean> {
  if ((response.headers.get("Content-Type") ?? "").split(";")[0].trim().toLowerCase() !== "application/problem+json") return false;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    reader = response.body?.getReader();
    if (!reader) return false;
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let text = "";
    let bytes = 0;
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > 4096) { await reader.cancel(); return false; }
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    const problem: unknown = JSON.parse(text);
    if (typeof problem !== "object" || problem === null || Array.isArray(problem)) return false;
    const fields = problem as Record<string, unknown>;
    return fields.type === "console_mfa_invalid" && fields.code === "console_mfa_invalid" && fields.status === 401 &&
      fields.instance === "/api/platform-console/auth/mfa/verify";
  } catch { return false; }
  finally { reader?.releaseLock(); }
}

async function request<T>(path: string, schema: z.ZodType<T>, options: { body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//") || /[\r\n#]/.test(path)) throw new ConsoleError(0, "invalid");
  const mutation = options.body !== undefined;
  const requestEpoch = authEpoch;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (mutation) {
    headers["Content-Type"] = "application/json";
    if (!PREAUTH.has(path)) {
      const csrf = csrfCookie();
      if (!csrf) throw new ConsoleError(0, "csrf");
      headers["X-Console-CSRF-Token"] = csrf;
    }
  }
  try {
    return await consumeResponseWithTimeout(`${API_BASE_URL.replace(/\/$/, "")}${PREFIX}${path}`, {
      method: mutation ? "POST" : "GET", credentials: "include", cache: "no-store", referrerPolicy: "no-referrer",
      headers, body: mutation ? JSON.stringify(options.body) : undefined, signal: options.signal,
    }, 30_000, async (response, signal) => {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (!response.ok) {
        // A rejected factor is not revocation of the limited console session.
        const invalidFactor = response.status === 401 && mutation && path === "/auth/mfa/verify" && await isInvalidMfaFactor(response);
        if (signal.aborted) throw new DOMException("Aborted", "AbortError");
        if (invalidFactor) throw new ConsoleError(401, "mfa_invalid");
        if (response.status === 401 && requestEpoch === authEpoch && typeof window !== "undefined") window.dispatchEvent(new Event(PLATFORM_SESSION_INVALIDATED));
        throw new ConsoleError(response.status, response.status === 401 ? "unauthorized" : response.status === 403 ? "forbidden" : response.status < 500 ? "invalid" : "unavailable");
      }
      const text = await response.text();
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (text.length > 2_000_000) throw new ConsoleError(0, "contract");
      let data: unknown;
      try { data = JSON.parse(text); } catch { throw new ConsoleError(0, "contract"); }
      const parsed = schema.safeParse(data);
      if (!parsed.success) throw new ConsoleError(0, "contract");
      return parsed.data;
    });
  } catch (error) {
    // Keep console cancellation semantics; the shared deadline reports NetworkError.
    if (options.signal?.aborted || error instanceof NetworkError) throw new DOMException("Aborted", "AbortError");
    throw error;
  }
}

function pageQuery(cursor?: string | null, limit = 25) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  return `?${query}`;
}

export const platformApi = {
  session: (signal?: AbortSignal) => request("/auth/session", consoleAuthState, { signal }),
  login: (body: { email: string; password: string }) => request("/auth/login", consoleAuthState, { body }),
  enroll: () => request("/auth/mfa/enroll", consoleEnrollmentResponse, { body: {} }),
  verify: (body: { code: string } | { recovery_code: string }) => request("/auth/mfa/verify", consoleAuthState, { body }),
  logout: () => request("/auth/logout", consoleSignedOut, { body: {} }),
  acceptInvitation: (body: { token: string; password: string; full_name: string }, signal?: AbortSignal) => request("/auth/invitations/complete", consoleAuthState, { body, signal }),
  resendInvitation: (email: string) => request("/auth/invitations/resend", consoleAccepted, { body: { email } }),
  startReset: (email: string, signal?: AbortSignal) => request("/auth/password-reset/start", consoleAccepted, { body: { email }, signal }),
  completeReset: async (body: { token: string; password: string }, signal?: AbortSignal) => {
    const result = await request("/auth/password-reset/complete", consoleComplete, { body, signal });
    if (!signal?.aborted && typeof window !== "undefined") window.dispatchEvent(new Event(PLATFORM_SESSION_INVALIDATED));
    return result;
  },
  admins: (cursor?: string | null, signal?: AbortSignal) => request(`/admins${pageQuery(cursor)}`, consoleAdminsResponse, { signal }),
  invite: (body: { email: string; full_name: string }) => request("/admins/invitations", consoleInvitationResponse, { body }),
  revoke: (id: string, reason: string) => request(`/admins/${encodeURIComponent(id)}/revoke`, consoleAdminRecord, { body: { reason } }),
  overview: (signal?: AbortSignal) => request("/reports/overview", consoleOverview, { signal }),
  activity: (signal?: AbortSignal) => request("/reports/activity", activityReport, { signal }),
  report: (kind: "usage" | "profit" | "company-profitability" | "revenue", cursor?: string | null, signal?: AbortSignal) => request(`/reports/${kind}${pageQuery(cursor)}`, consoleReportPage, { signal }),
};

export function consoleErrorMessage(error: unknown): string {
  if (!(error instanceof ConsoleError)) return "The request could not be completed. No automatic retry was made.";
  switch (error.kind) {
    case "mfa_invalid": return "The MFA code is invalid or was already used. Enter a fresh code or another recovery code.";
    case "unauthorized": return "Your platform session has ended. Sign in again.";
    case "forbidden": return "Access was refused. Check your permissions or verify MFA again before an administrator change.";
    case "csrf": return "The security check is missing. Reload this page and sign in again.";
    case "contract": return "The report response could not be verified. No data is shown.";
    case "invalid": return "The request was not accepted. Check the supplied details or request a fresh link.";
    default: return "The request outcome could not be confirmed. Check the current state before trying again.";
  }
}
