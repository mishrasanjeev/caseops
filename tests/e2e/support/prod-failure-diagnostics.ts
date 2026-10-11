const routes: Array<[RegExp, string]> = [
  [/^\/api\/auth\/(?:login|refresh)$/, "auth/session"],
  [/^\/api\/matters\/bulk-update\/(?:preview|apply)$/, "matter/bulk-update"],
  [/^\/api\/matters\/[^/]+\/attachments$/, "matter/attachment"],
  [/^\/api\/notices\/[^/]+\/attachments$/, "notice/attachment"],
  [/^\/api\/ip\/dockets\/[^/]+\/title-interests$/, "ip/title-interest"],
  [/^\/api\/ip\/patents\/applications$/, "ip/application"],
  [/^\/sign-in\/?$/, "web/sign-in"],
  [/^\/app(?:\/|$)/, "web/app-navigation"],
];

const problemTypes = new Set([
  "database_lock_timeout", "database_busy", "database_unavailable",
  "invalid_token", "missing_bearer_token", "rate_limited",
  "capability_required", "role_required", "step_up_required",
  "mfa_enrollment_required", "validation_error",
]);

const transportCodes = new Set([
  "net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_CLOSED",
  "net::ERR_CONNECTION_REFUSED", "net::ERR_TIMED_OUT",
  "net::ERR_ABORTED", "net::ERR_FAILED", "net::ERR_INTERNET_DISCONNECTED",
  "net::ERR_NAME_NOT_RESOLVED", "net::ERR_SSL_PROTOCOL_ERROR",
]);

export function diagnosticRoute(rawUrl: string, origins: readonly string[]): string | null {
  try {
    const url = new URL(rawUrl);
    if (!origins.includes(url.origin)) return null;
    return routes.find(([pattern]) => pattern.test(url.pathname))?.[1] ?? null;
  } catch {
    return null;
  }
}

export function diagnosticRequestId(value: unknown): string | null {
  return typeof value === "string" && (value.length === 32 || value.length === 36)
    && /^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(value)
    ? value : null;
}

export function diagnosticProblem(value: unknown): { requestId: string | null; problemType: string | null } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return { requestId: null, problemType: null };
  const payload = value as Record<string, unknown>;
  const problemType = typeof payload.type === "string"
    ? [...problemTypes].find((code) => payload.type === code || (payload.type as string).endsWith(`/${code}`) || (payload.type as string).endsWith(`:${code}`)) ?? null
    : null;
  return { requestId: diagnosticRequestId(payload.request_id), problemType };
}

export function diagnosticTransport(value: unknown): string {
  return typeof value === "string" && transportCodes.has(value) ? value : "unclassified_transport_failure";
}
