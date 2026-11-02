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
export type ServerSessionBinding = Readonly<{
  userId: string;
  companyId: string;
  membershipId: string;
  sessionId: string;
}>;
export type LocalSessionBinding = ServerSessionBinding &
  Readonly<{ sessionKey: string }>;
export type CredentialStore = {
  read: () => Promise<StoredCredential | null>;
  write: (credential: StoredCredential) => Promise<void>;
  clear: () => Promise<void>;
};

export function parseIdentity(value: unknown): SessionIdentity {
  const record = (input: unknown): Record<string, unknown> => {
    if (!input || typeof input !== "object" || Array.isArray(input))
      throw new Error("The workspace identity could not be verified.");
    return input as Record<string, unknown>;
  };
  const text = (input: unknown, max: number): string => {
    if (typeof input !== "string" || !input.trim() || input.length > max)
      throw new Error("The workspace identity could not be verified.");
    return input;
  };
  const row = record(value);
  const company = record(row.company),
    user = record(row.user),
    membership = record(row.membership);
  if (!Array.isArray(row.capabilities) || row.capabilities.length > 2048)
    throw new Error("The workspace identity could not be verified.");
  return {
    company: {
      id: text(company.id, 200),
      name: text(company.name, 300),
      slug: text(company.slug, 100),
    },
    user: {
      id: text(user.id, 200),
      email: text(user.email, 320),
      full_name: text(user.full_name, 300),
    },
    membership: {
      id: text(membership.id, 200),
      role: text(membership.role, 100),
    },
    capabilities: row.capabilities.map((capability) => text(capability, 200)),
  };
}

export function parseGrant(value: unknown): NativeGrant {
  const identity = parseIdentity(value);
  const grant = value as NativeGrant;
  if (
    typeof grant.access_token !== "string" ||
    !grant.access_token ||
    typeof grant.refresh_token !== "string" ||
    !grant.refresh_token ||
    typeof grant.session_id !== "string" ||
    !grant.session_id ||
    !Number.isSafeInteger(grant.expires_in) ||
    grant.expires_in < 1 ||
    grant.expires_in > 3600 ||
    grant.access_token.length > 16384 ||
    grant.refresh_token.length > 16384 ||
    grant.session_id.length > 200
  ) {
    throw new Error("Invalid native session response.");
  }
  return {
    ...identity,
    access_token: grant.access_token,
    refresh_token: grant.refresh_token,
    session_id: grant.session_id,
    expires_in: grant.expires_in,
  };
}
