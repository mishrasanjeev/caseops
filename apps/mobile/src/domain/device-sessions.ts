import { array, ContractError, dateOnly, object, string } from "./contracts.ts";
import { errorStatus } from "./repository.ts";
import type { AuthorizedRequest } from "./repository.ts";

// NativeSessionsResponse / NativeSessionRecord in schemas/native_auth.py.
export const MAX_DEVICE_SESSIONS = 20;
const path = "/api/auth/native/sessions";

export type DeviceSession = {
  id: string;
  platform: "android" | "ios";
  created_at: string;
  last_used_at: string;
  expires_at: string;
  revoked_at: string | null;
  current: boolean;
};

function sessionId(value: unknown): string {
  const id = string(value, "device session identity", 200);
  if (
    !id.trim() ||
    id !== id.trim() ||
    /[\x00-\x1f\x7f]/.test(id) ||
    [".", ".."].includes(id)
  )
    throw new ContractError("device session identity");
  return id;
}

export function deviceSessionInstant(value: string): number {
  const match =
    /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$/.exec(
      value,
    );
  if (!match) throw new ContractError("device session timestamp");
  dateOnly(match[1]);
  const zone = match[5];
  if (
    Number(match[2]) > 23 ||
    Number(match[3]) > 59 ||
    Number(match[4]) > 59 ||
    (zone &&
      zone !== "Z" &&
      (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59))
  )
    throw new ContractError("device session timestamp");
  // The service treats timezone-naive SQLite timestamps as UTC, too.
  const instant = Date.parse(zone ? value : `${value}Z`);
  if (!Number.isFinite(instant))
    throw new ContractError("device session timestamp");
  return instant;
}

function timestamp(value: unknown): string {
  const text = string(value, "device session timestamp", 40);
  deviceSessionInstant(text);
  return text;
}

export function decodeDeviceSession(value: unknown): DeviceSession {
  const row = object(value, "device session");
  if (
    (row.platform !== "android" && row.platform !== "ios") ||
    typeof row.current !== "boolean"
  )
    throw new ContractError("device session");
  return {
    id: sessionId(row.id),
    platform: row.platform,
    created_at: timestamp(row.created_at),
    last_used_at: timestamp(row.last_used_at),
    expires_at: timestamp(row.expires_at),
    revoked_at: row.revoked_at === null ? null : timestamp(row.revoked_at),
    current: row.current,
  };
}

export function decodeDeviceSessions(value: unknown): DeviceSession[] {
  const row = object(value, "device sessions");
  if (row.next_cursor != null)
    throw new ContractError("device session continuation");
  const sessions = array(
    row.sessions,
    "device sessions",
    decodeDeviceSession,
    MAX_DEVICE_SESSIONS,
  );
  if (
    new Set(sessions.map((session) => session.id)).size !== sessions.length ||
    sessions.filter((session) => session.current).length > 1
  )
    throw new ContractError("device session identities");
  return sessions;
}

export function createDeviceSessionsRepository(request: AuthorizedRequest) {
  return {
    list: async (signal?: AbortSignal) =>
      decodeDeviceSessions(
        await request<unknown>(path, { method: "GET", signal }),
      ),
    revoke: async (id: string) => {
      const acknowledgement = await request<unknown>(
        `${path}/${encodeURIComponent(sessionId(id))}`,
        { method: "DELETE" },
      );
      if (acknowledgement !== undefined)
        throw new ContractError("device session revocation");
    },
  };
}
export type DeviceSessionsRepository = ReturnType<
  typeof createDeviceSessionsRepository
>;

export type DeviceSessionRevocation = {
  state: "revoked" | "rejected" | "unknown";
  current: boolean;
  signOutFailed: boolean;
  message: string;
};

// One confirmation owns one attempt, including duplicate taps and lost receipts.
export function createDeviceSessionRevocation(
  repository: DeviceSessionsRepository,
  target: DeviceSession,
  onCurrentSessionRevoked: () => Promise<void>,
): () => Promise<DeviceSessionRevocation> {
  const session = decodeDeviceSession(target);
  let attempt: Promise<DeviceSessionRevocation> | undefined;
  return () =>
    (attempt ??= (async () => {
      let state: DeviceSessionRevocation["state"] = "revoked";
      let message = session.current
        ? "This session was revoked. Sign in again to continue."
        : "Session revoked.";
      try {
        await repository.revoke(session.id);
      } catch (error) {
        const status = errorStatus(error);
        const uncertain =
          !!error &&
          typeof error === "object" &&
          (error as Record<string, unknown>).outcome === "unknown";
        state =
          !uncertain && status !== null && status >= 400 && status < 500
            ? "rejected"
            : "unknown";
        message =
          state === "unknown"
            ? "Revocation could not be confirmed. Reload sessions before trying again."
            : status === 404
              ? "This session is no longer available. Reload sessions."
              : status === 401 || status === 403
                ? "Session access has changed. Sign in again or reload sessions."
                : "The session could not be revoked. Reload sessions before trying again.";
      }
      let signOutFailed = false;
      // An uncertain self-revoke may already have ended authority: purge locally.
      if (session.current && state !== "rejected") {
        try {
          await onCurrentSessionRevoked();
          if (state === "unknown")
            message =
              "Revocation could not be confirmed. Sign in again before continuing.";
        } catch {
          signOutFailed = true;
          message =
            state === "revoked"
              ? "This session was revoked, but device sign-out could not be confirmed. Sign out again."
              : "Revocation and device sign-out could not be confirmed. Sign out again.";
        }
      }
      return { state, current: session.current, signOutFailed, message };
    })());
}
