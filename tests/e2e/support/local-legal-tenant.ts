import type { APIRequestContext, APIResponse } from "@playwright/test";

import { apiBaseUrl } from "./env";

export const LOCAL_LEGAL_COMPANY_SLUG = "legal";
export const LOCAL_LEGAL_OWNER_EMAIL = "hari.gupta@gmail.com";
export const LOCAL_LEGAL_PASSWORD =
  process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() || "RamLocalRegression0715!";

type BootstrapProfile = {
  companyName: string;
  ownerFullName: string;
};

type AuthPayload = {
  access_token?: unknown;
};

async function accessToken(
  response: APIResponse,
  label: string,
): Promise<string> {
  const payload = (await response.json()) as AuthPayload;
  if (typeof payload.access_token !== "string" || !payload.access_token) {
    throw new Error(`${label} returned no access token.`);
  }
  return payload.access_token;
}

async function responseFailure(
  response: APIResponse,
  label: string,
): Promise<Error> {
  return new Error(
    `${label}: expected HTTP 200, received ${response.status()} ${await response.text()}`,
  );
}

async function login(api: APIRequestContext): Promise<APIResponse> {
  return api.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: LOCAL_LEGAL_COMPANY_SLUG,
      email: LOCAL_LEGAL_OWNER_EMAIL,
      password: LOCAL_LEGAL_PASSWORD,
    },
  });
}

/**
 * Authenticate the shared local `legal` tenant, creating it only when absent.
 *
 * July 15 and July 22 are discovered in the same Playwright database. An
 * unconditional bootstrap made whichever file ran second fail with HTTP 409.
 * Login-first is idempotent; the post-409 retry also makes a concurrent
 * bootstrap race safe without mutating an existing user's password or data.
 */
export async function authenticateOrBootstrapLocalLegalTenant(
  api: APIRequestContext,
  profile: BootstrapProfile,
): Promise<string> {
  const existing = await login(api);
  if (existing.status() === 200) {
    return accessToken(existing, "local legal tenant login");
  }
  if (existing.status() !== 401) {
    throw await responseFailure(existing, "local legal tenant login");
  }

  const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: profile.companyName,
      company_slug: LOCAL_LEGAL_COMPANY_SLUG,
      company_type: "law_firm",
      owner_full_name: profile.ownerFullName,
      owner_email: LOCAL_LEGAL_OWNER_EMAIL,
      owner_password: LOCAL_LEGAL_PASSWORD,
    },
  });
  if (bootstrap.status() === 200) {
    return accessToken(bootstrap, "bootstrap local legal tenant");
  }
  if (bootstrap.status() !== 409) {
    throw await responseFailure(bootstrap, "bootstrap local legal tenant");
  }

  const racedLogin = await login(api);
  if (racedLogin.status() === 200) {
    return accessToken(
      racedLogin,
      "local legal tenant login after bootstrap race",
    );
  }
  throw await responseFailure(
    racedLogin,
    "local legal tenant login after bootstrap conflict",
  );
}
