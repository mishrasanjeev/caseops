// Narrow auth-only API module.
//
// Extracted from the monolithic ``lib/api/endpoints.ts`` so the
// ``/sign-in`` + ``/new-workspace`` pages do not pull the whole
// 1,250-line endpoints file (every matter / draft / contract /
// payment / recommendation / intake wrapper) into their bundle. Those
// pages only need three calls — ``signIn``, ``bootstrapCompany``, and
// ``fetchAuthContext`` — plus a minimal schema subset.
//
// Leaving ``endpoints.ts`` intact so authenticated pages keep their
// existing import path; the auth pages import from this module
// instead. Next.js can then tree-shake / code-split the auth route
// aggressively.
import { apiRequest } from "./client";
import { type AuthContext, type AuthSession, authContext, authSession } from "./schemas";

export async function signIn(input: {
  email: string;
  password: string;
  companySlug: string;
}): Promise<AuthSession> {
  const data = await apiRequest<unknown>("/api/auth/login", {
    method: "POST",
    body: {
      email: input.email,
      password: input.password,
      company_slug: input.companySlug,
    },
    token: null,
  });
  return authSession.parse(data);
}

export async function bootstrapCompany(input: {
  companyName: string;
  companySlug: string;
  companyType: "law_firm" | "corporate_legal" | "solo";
  ownerFullName: string;
  ownerEmail: string;
  ownerPassword: string;
}): Promise<AuthSession> {
  const data = await apiRequest<unknown>("/api/bootstrap/company", {
    method: "POST",
    body: {
      company_name: input.companyName,
      company_slug: input.companySlug,
      company_type: input.companyType,
      owner_full_name: input.ownerFullName,
      owner_email: input.ownerEmail,
      owner_password: input.ownerPassword,
    },
    token: null,
  });
  return authSession.parse(data);
}

export async function fetchAuthContext(token?: string | null): Promise<AuthContext> {
  const data = await apiRequest<unknown>("/api/auth/me", { token });
  return authContext.parse(data);
}
