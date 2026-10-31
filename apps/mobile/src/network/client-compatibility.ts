import { MobileApiError } from "./http.ts";
import {
  checkedClientMetadata,
  clientVersionParts,
  compareClientVersions,
} from "./client-version.ts";
import type { NativeClientMetadata } from "./client-version.ts";
import { LOCAL_FOREGROUND_SETTLE_MS } from "../auth/local-unlock.ts";

export type ClientCompatibility = Readonly<{
  protocol_version: 1;
  platform: "android" | "ios";
  client_version: string;
  minimum_supported_version: string | null;
  status: "supported" | "update_required";
}>;
type CompatibilityState = Readonly<{
  status: "checking" | "supported" | "update_required" | "unavailable";
  minimum: string | null;
  message: string;
}>;
export type CompatibilitySnapshot = CompatibilityState &
  Readonly<{ busy: boolean }>;

export function parseClientCompatibility(
  input: unknown,
  client: NativeClientMetadata,
): ClientCompatibility {
  if (!input || typeof input !== "object" || Array.isArray(input))
    throw new Error("Compatibility could not be verified.");
  const p = input as Record<string, unknown>;
  if (
    Object.keys(p).sort().join() !==
      "client_version,minimum_supported_version,platform,protocol_version,status" ||
    p.protocol_version !== 1 ||
    p.platform !== client.platform ||
    p.client_version !== client.version ||
    (p.minimum_supported_version !== null &&
      typeof p.minimum_supported_version !== "string")
  )
    throw new Error("Compatibility could not be verified.");
  const minimum = p.minimum_supported_version as string | null;
  if (minimum !== null) clientVersionParts(minimum);
  const status =
    minimum !== null && compareClientVersions(client.version, minimum) < 0
      ? "update_required"
      : "supported";
  if (p.status !== status)
    throw new Error("Compatibility could not be verified.");
  return {
    protocol_version: 1,
    platform: client.platform,
    client_version: client.version,
    minimum_supported_version: minimum,
    status,
  };
}

export function isCompatibilityExit(path: string, method: string): boolean {
  return (
    (method === "GET" &&
      ["/api/auth/security", "/api/auth/native/sessions"].includes(path)) ||
    (method === "DELETE" &&
      /^\/api\/auth\/native\/sessions\/[a-f0-9-]{36}$/i.test(path)) ||
    (method === "POST" &&
      ["/api/auth/native/refresh", "/api/auth/native/logout"].includes(path))
  );
}

export function createClientCompatibility(
  metadata: { platform: unknown; version: unknown },
  request: (path: string) => Promise<unknown>,
  principal: () => string,
  blockPrivate: (status: CompatibilityState["status"]) => void,
  changed: () => void,
) {
  let client: NativeClientMetadata | null = null;
  try {
    client = checkedClientMetadata(metadata);
  } catch {
    /* Fail closed without a request. */
  }
  let epoch = 0,
    foreground = true;
  let state: CompatibilityState = {
    status: client ? "checking" : "unavailable",
    minimum: null,
    message: client
      ? "App compatibility must be checked before continuing."
      : "This app build's version could not be verified.",
  };
  let running: { owner: number; result: Promise<boolean> } | null = null;
  const activeWaiters = new Set<() => void>();
  const path = client
    ? `/api/auth/native/compatibility?platform=${client.platform}&client_version=${encodeURIComponent(client.version)}`
    : null;
  const publish = (next: CompatibilityState) => {
    state = next;
    if (state.status !== "supported") blockPrivate(state.status);
    changed();
  };
  const controller = {
    getSnapshot: (): CompatibilitySnapshot => ({
      ...state,
      busy: running?.owner === epoch,
    }),
    get supported() {
      return foreground && state.status === "supported";
    },
    get epoch() {
      return epoch;
    },
    visibility(active: boolean, background: boolean) {
      foreground = active;
      if (background) controller.invalidate();
      if (foreground) for (const done of [...activeWaiters]) done();
    },
    invalidate() {
      ++epoch;
      for (const done of [...activeWaiters]) done();
      publish({
        status: "checking",
        minimum: null,
        message: "App compatibility must be checked before continuing.",
      });
    },
    admit(apiPath: string, method: string) {
      if (apiPath === path && method === "GET") return;
      if (isCompatibilityExit(apiPath, method)) return;
      if (!controller.supported)
        throw new MobileApiError(
          state.status === "update_required"
            ? "Update CaseOps before continuing."
            : "App compatibility must be checked before continuing.",
          state.status === "update_required" ? 426 : 503,
          state.status === "update_required"
            ? "native_client_update_required"
            : "native_compatibility_unavailable",
        );
    },
    incompatible(input: unknown) {
      ++epoch; // A policy read started before this refusal cannot clear it.
      let minimum: string | null = null;
      if (
        client &&
        input &&
        typeof input === "object" &&
        !Array.isArray(input)
      ) {
        const p = input as Record<string, unknown>;
        try {
          if (
            p.code === "native_client_update_required" &&
            p.platform === client.platform &&
            (p.status === undefined || p.status === 426) &&
            typeof p.minimum_supported_version === "string" &&
            compareClientVersions(client.version, p.minimum_supported_version) <
              0
          )
            minimum = p.minimum_supported_version;
        } catch {
          /* No reflected input or guessed floor. */
        }
      }
      publish(
        minimum
          ? {
              status: "update_required",
              minimum,
              message:
                "Install the current CaseOps app before continuing. This check does not sign you out.",
            }
          : {
              status: "unavailable",
              minimum: null,
              message:
                "The service requires an app compatibility check. Retry when connected. This check does not sign you out.",
            },
      );
    },
    refresh(): Promise<boolean> {
      if (!client || !path) return Promise.resolve(false);
      if (running?.owner === epoch) return running.result;
      const owner = ++epoch,
        identity = principal();
      publish({ status: "checking", minimum: null, message: "" });
      const result = Promise.resolve()
        .then(() => request(path))
        .then(async (input) => {
          if (owner !== epoch) return false;
          if (!foreground)
            await new Promise<void>((resolve) => {
              const timer = setTimeout(done, LOCAL_FOREGROUND_SETTLE_MS);
              function done() {
                clearTimeout(timer);
                activeWaiters.delete(done);
                resolve();
              }
              activeWaiters.add(done);
            });
          if (owner !== epoch) return false;
          if (!foreground || principal() !== identity) {
            publish({
              status: "unavailable",
              minimum: null,
              message:
                "App compatibility must be checked again before continuing.",
            });
            return false;
          }
          const policy = parseClientCompatibility(input, client!);
          publish({
            status: policy.status,
            minimum: policy.minimum_supported_version,
            message:
              policy.status === "update_required"
                ? "Install the current CaseOps app before continuing. This check does not sign you out."
                : "",
          });
          return policy.status === "supported";
        })
        .catch((error: unknown) => {
          if (owner === epoch && foreground && principal() === identity)
            publish({
              status: "unavailable",
              minimum: null,
              message:
                error instanceof MobileApiError && error.status === 404
                  ? "This service has not made app compatibility information available. Retry later, or sign out."
                  : "App compatibility could not be checked. Check your connection and retry. This check does not sign you out.",
            });
          return false;
        })
        .finally(() => {
          if (running?.result === result) {
            running = null;
            changed();
          }
        });
      running = { owner, result };
      return result;
    },
  };
  return controller;
}
