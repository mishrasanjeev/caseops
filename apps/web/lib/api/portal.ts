/**
 * Phase C-1 (2026-04-24, MOD-TS-014) — portal client helpers.
 *
 * The portal surface lives at /portal/* on the web side and talks to
 * /api/portal/* on the API side. Reuses the existing ``apiRequest``
 * because it already runs ``credentials: 'include'`` and the browser
 * sends every cookie regardless of name. CSRF is intentionally not
 * enforced server-side for /api/portal/* (see core/csrf.py) so the
 * helpers here never need to read a CSRF cookie.
 */
import { apiRequest } from "@/lib/api/client";

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
  return apiRequest<PortalCommunication>(
    `/api/portal/matters/${matterId}/communications`,
    { method: "POST", body: { body } },
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

export type PortalKycDocument = { name: string; note?: string | null };

export async function submitPortalMatterKyc(
  matterId: string,
  documents: PortalKycDocument[],
): Promise<{
  matter_id: string;
  affected_client_ids: string[];
  submitted_at: string;
}> {
  return apiRequest(
    `/api/portal/matters/${matterId}/kyc`,
    { method: "POST", body: { documents } },
  );
}
