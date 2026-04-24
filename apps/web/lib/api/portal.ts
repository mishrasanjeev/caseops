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
