export type SessionIdentity = {
  company: { id: string; name: string; slug: string };
  user: { id: string; email: string; full_name: string };
  membership: { id: string; role: string };
  capabilities: string[];
};

export type NativeGrant = SessionIdentity & {
  access_token: string;
  refresh_token: string;
  session_id: string;
  expires_in: number;
};

export type StoredCredential = { refreshToken: string; sessionId: string };
export type CredentialStore = {
  read: () => Promise<StoredCredential | null>;
  write: (credential: StoredCredential) => Promise<void>;
  clear: () => Promise<void>;
};

export function parseGrant(value: unknown): NativeGrant {
  if (!value || typeof value !== "object")
    throw new Error("Invalid native session response.");
  const grant = value as NativeGrant;
  if (
    typeof grant.access_token !== "string" ||
    !grant.access_token ||
    typeof grant.refresh_token !== "string" ||
    !grant.refresh_token ||
    typeof grant.session_id !== "string" ||
    !grant.session_id ||
    !Number.isFinite(grant.expires_in) ||
    grant.expires_in < 1 ||
    grant.expires_in > 3600 ||
    !grant.company ||
    typeof grant.company.id !== "string" ||
    typeof grant.company.name !== "string" ||
    typeof grant.company.slug !== "string" ||
    !grant.user ||
    typeof grant.user.id !== "string" ||
    typeof grant.user.email !== "string" ||
    typeof grant.user.full_name !== "string" ||
    !grant.membership ||
    typeof grant.membership.id !== "string" ||
    !Array.isArray(grant.capabilities) ||
    !grant.capabilities.every((c) => typeof c === "string")
  ) {
    throw new Error("Invalid native session response.");
  }
  return grant;
}
