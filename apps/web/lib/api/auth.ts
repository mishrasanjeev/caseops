// Narrow auth-only API module.
//
// Extracted from the monolithic ``lib/api/endpoints.ts`` so the
// ``/sign-in`` + ``/new-workspace`` pages do not pull the whole
// 1,250-line endpoints file into their bundle.
//
// This file is also **zod-free on purpose**: importing the zod
// schemas from ``./schemas`` would re-introduce the entire 60-schema
// graph + zod's runtime (~30 kB min+gz) for nothing — a successful
// response from our own ``/api/auth/login`` has a known shape, and
// any mismatch is a backend contract bug that a zod check can only
// mask. Types come from ``./schema-types`` which is declaration-only
// and compiles to zero JS.
import { apiRequest } from "./client";
import type { AuthContext, AuthSession } from "./schema-types";

export async function signIn(input: {
  email: string;
  password: string;
  companySlug: string;
}): Promise<AuthSession> {
  return apiRequest<AuthSession>("/api/auth/login", {
    method: "POST",
    body: {
      email: input.email,
      password: input.password,
      company_slug: input.companySlug,
    },
    token: null,
  });
}

export async function bootstrapCompany(input: {
  companyName: string;
  companySlug: string;
  companyType: "law_firm" | "corporate_legal" | "solo";
  ownerFullName: string;
  ownerEmail: string;
  ownerPassword: string;
}): Promise<AuthSession> {
  return apiRequest<AuthSession>("/api/bootstrap/company", {
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
}

export async function fetchAuthContext(
  token?: string | null,
): Promise<AuthContext> {
  return apiRequest<AuthContext>("/api/auth/me", { token });
}
