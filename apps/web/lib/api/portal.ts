/**
 * Phase C-1 (2026-04-24, MOD-TS-014) — portal client helpers.
 *
 * The portal surface lives at /portal/* on the web side and talks to
 * /api/portal/* on the API side. Reuses the existing ``apiRequest``
 * because it already runs ``credentials: 'include'`` and the browser
 * sends every cookie regardless of name.
 *
 * Codex H1 (2026-04-24): portal MUTATIONS now require a paired
 * portal-CSRF token (caseops_portal_csrf cookie + X-Portal-CSRF-Token
 * header). The portal sign-in surface (request-link / verify-link /
 * logout) stays exempt server-side. Helpers below add the header on
 * POST/PUT/PATCH/DELETE; reads stay header-free.
 */
import { API_BASE_URL } from "@/lib/api/config";
import { apiRequest } from "@/lib/api/client";

const PORTAL_CSRF_COOKIE = "caseops_portal_csrf";
const PORTAL_CSRF_HEADER = "X-Portal-CSRF-Token";

function readPortalCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie
    .split(";")
    .map((c) => c.trim())
    .find((c) => c.startsWith(`${PORTAL_CSRF_COOKIE}=`));
  if (!match) return null;
  return decodeURIComponent(match.slice(PORTAL_CSRF_COOKIE.length + 1));
}

async function portalMutate<T>(path: string, body: unknown): Promise<T> {
  const csrf = readPortalCsrfCookie();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (csrf) headers[PORTAL_CSRF_HEADER] = csrf;
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = "Portal request failed.";
    try {
      const data = await resp.json();
      if (data?.detail) detail = data.detail;
    } catch {
      /* ignore */
    }
    throw Object.assign(new Error(detail), {
      name: "ApiError",
      detail,
      status: resp.status,
      data: null,
    });
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export type PortalUserRole = "client" | "outside_counsel";

export type PortalUserProfile = {
  id: string;
  company_id: string;
  email: string;
  full_name: string;
  role: PortalUserRole;
  last_signed_in_at: string | null;
};

export type PortalGrant = {
  id: string;
  matter_id: string;
  role: PortalUserRole;
  scope_json: { can_upload?: boolean; can_invoice?: boolean; can_reply?: boolean } | null;
  granted_at: string;
  revoked_at: string | null;
};

export type PortalSession = {
  portal_user: PortalUserProfile;
  grants: PortalGrant[];
};

export type PortalRequestLinkResult = {
  delivered: true;
  /** NON-prod helper. In prod the magic link is sent via AutoMail and
   * this field is always null. */
  debug_token: string | null;
};

export async function requestPortalMagicLink(input: {
  companySlug: string;
  email: string;
}): Promise<PortalRequestLinkResult> {
  return apiRequest<PortalRequestLinkResult>(
    "/api/portal/auth/request-link",
    {
      method: "POST",
      body: { company_slug: input.companySlug, email: input.email },
    },
  );
}

export async function verifyPortalMagicLink(token: string): Promise<PortalSession> {
  return apiRequest<PortalSession>(
    "/api/portal/auth/verify-link",
    { method: "POST", body: { token } },
  );
}

export async function logoutPortal(): Promise<void> {
  await apiRequest<void>("/api/portal/auth/logout", { method: "POST" });
}

export async function fetchPortalSession(): Promise<PortalSession> {
  return apiRequest<PortalSession>("/api/portal/me");
}

// ---------- Phase C-2 (MOD-TS-015) — client portal matter surface ----------

export type PortalMatter = {
  id: string;
  title: string;
  matter_code: string | null;
  status: string;
  practice_area: string | null;
  forum_level: string | null;
  court_name: string | null;
  next_hearing_on: string | null;
};

export async function fetchPortalMatters(): Promise<{ matters: PortalMatter[] }> {
  return apiRequest<{ matters: PortalMatter[] }>("/api/portal/matters");
}

export async function fetchPortalMatter(matterId: string): Promise<PortalMatter> {
  return apiRequest<PortalMatter>(`/api/portal/matters/${matterId}`);
}

export type PortalCommunication = {
  id: string;
  direction: "inbound" | "outbound";
  channel: string;
  subject: string | null;
  body: string;
  occurred_at: string;
  status: string;
  posted_by_portal_user: boolean;
};

export async function fetchPortalMatterCommunications(
  matterId: string,
): Promise<{ communications: PortalCommunication[] }> {
  return apiRequest<{ communications: PortalCommunication[] }>(
    `/api/portal/matters/${matterId}/communications`,
  );
}

export async function postPortalMatterReply(
  matterId: string,
  body: string,
): Promise<PortalCommunication> {
  return portalMutate<PortalCommunication>(
    `/api/portal/matters/${matterId}/communications`,
    { body },
  );
}

export type PortalHearing = {
  id: string;
  hearing_on: string;
  forum_name: string;
  judge_name: string | null;
  purpose: string;
  status: string;
  outcome_note: string | null;
};

export async function fetchPortalMatterHearings(
  matterId: string,
): Promise<{ hearings: PortalHearing[] }> {
  return apiRequest<{ hearings: PortalHearing[] }>(
    `/api/portal/matters/${matterId}/hearings`,
  );
}

export type PortalMatterClient = {
  id: string;
  name: string;
  client_type: string;
  kyc_status: string;
  kyc_submitted_at: string | null;
};

export async function fetchPortalMatterClients(
  matterId: string,
): Promise<{ clients: PortalMatterClient[] }> {
  return apiRequest<{ clients: PortalMatterClient[] }>(
    `/api/portal/matters/${matterId}/clients`,
  );
}

export type PortalKycDocument = { name: string; note?: string | null };

export async function submitPortalMatterKyc(
  matterId: string,
  clientId: string,
  documents: PortalKycDocument[],
): Promise<{
  matter_id: string;
  client_id: string;
  submitted_at: string;
}> {
  return portalMutate(
    `/api/portal/matters/${matterId}/kyc`,
    { client_id: clientId, documents },
  );
}
