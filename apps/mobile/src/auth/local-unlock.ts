import type {
  LocalSessionBinding,
  ServerSessionBinding,
  SessionIdentity,
} from "./types.ts";

export type LocalUnlockPolicy = Readonly<{
  version: 1;
  state: "pending" | "enabled";
  installationId: string;
  nonce: string;
  binding: ServerSessionBinding;
}>;
export type LocalUnlockStore = {
  readPolicy: () => Promise<unknown>;
  writePolicy: (policy: LocalUnlockPolicy) => Promise<void>;
  writeMarker: (value: string) => Promise<void>;
  clearMarker: () => Promise<void>;
  readMarker: () => Promise<string | null>;
  clear: () => Promise<void>;
  supported: () => boolean;
  nonce: () => string;
};
export type LocalUnlockSnapshot = Readonly<{
  status:
    | "initializing"
    | "off"
    | "locked"
    | "prompting"
    | "unlocked"
    | "clearing";
  enabled: boolean;
  busy: boolean;
  message: string;
}>;
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
export const LOCAL_FOREGROUND_SETTLE_MS = 2000;
const text = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length > 0 &&
  value.length <= 200 &&
  value.trim() === value &&
  !/[\x00-\x1f\x7f]/.test(value);
const bindingKeys = [
  "userId",
  "companyId",
  "membershipId",
  "sessionId",
] as const;
export function sameServerBinding(
  left: ServerSessionBinding,
  right: ServerSessionBinding,
) {
  return bindingKeys.every(
    (key) => text(left[key]) && left[key] === right[key],
  );
}
function sameIdentity(
  binding: ServerSessionBinding,
  identity: SessionIdentity,
) {
  return (
    identity.user.id === binding.userId &&
    identity.company.id === binding.companyId &&
    identity.membership.id === binding.membershipId
  );
}
export function parseLocalUnlockPolicy(
  input: unknown,
  installationId: string,
): LocalUnlockPolicy | null {
  if (installationId.length !== 36 || !uuid.test(installationId))
    throw new Error("Local device binding is unavailable.");
  if (input === null) return null;
  if (!input || typeof input !== "object" || Array.isArray(input))
    throw new Error("Local lock policy is unavailable.");
  const p = input as Record<string, unknown>;
  const b = p.binding;
  if (
    Object.keys(p).sort().join() !==
      "binding,installationId,nonce,state,version" ||
    p.version !== 1 ||
    !["pending", "enabled"].includes(String(p.state)) ||
    p.installationId !== installationId ||
    !uuid.test(installationId) ||
    typeof p.nonce !== "string" ||
    p.nonce.length !== 36 ||
    !uuid.test(p.nonce) ||
    !b ||
    typeof b !== "object" ||
    Array.isArray(b) ||
    Object.keys(b).sort().join() !== [...bindingKeys].sort().join() ||
    !bindingKeys.every((key) => text((b as Record<string, unknown>)[key]))
  )
    throw new Error("Local lock policy is unavailable.");
  return {
    version: 1,
    state: p.state as "pending" | "enabled",
    installationId,
    nonce: p.nonce,
    binding: Object.fromEntries(
      bindingKeys.map((key) => [key, (b as Record<string, string>)[key]]),
    ) as ServerSessionBinding,
  };
}
export function localUnlockMarker(policy: LocalUnlockPolicy): string {
  return JSON.stringify({
    version: 1,
    installationId: policy.installationId,
    nonce: policy.nonce,
    binding: Object.fromEntries(
      bindingKeys.map((key) => [key, policy.binding[key]]),
    ),
  });
}

// The lease is claimed synchronously before the first store/prompt await. A
// reset waits for any unknown native completion; no second prompt is replayed.
export function createLocalUnlock(
  installationId: string,
  store: LocalUnlockStore,
  authority: {
    current: () => LocalSessionBinding | null;
    revalidate: () => Promise<SessionIdentity>;
  },
  cover: () => Promise<void>,
  changed: () => void,
) {
  if (installationId.length !== 36 || !uuid.test(installationId))
    throw new Error("Local device binding is unavailable.");
  let policy: LocalUnlockPolicy | null = null;
  let epoch = 0,
    foreground = true,
    loaded = false,
    authorized = false;
  let authorizedBinding: LocalSessionBinding | null = null;
  let snapshot: LocalUnlockSnapshot = {
    status: "initializing",
    enabled: false,
    busy: false,
    message: "",
  };
  let running: Promise<SessionIdentity | null> | null = null;
  let resetting: Promise<void> | null = null;
  const activeWaiters = new Set<() => void>();
  const publish = (status: LocalUnlockSnapshot["status"], message = "") => {
    snapshot = {
      status,
      enabled: policy?.state === "enabled",
      busy: running !== null || resetting !== null,
      message,
    };
    changed();
  };
  const current = (owner: number, expected?: LocalSessionBinding | null) => {
    if (owner !== epoch) throw new Error("Local unlock was cancelled.");
    if (expected) {
      const live = authority.current();
      if (
        !live ||
        live.sessionKey !== expected.sessionKey ||
        !sameServerBinding(expected, live)
      )
        throw new Error("Local unlock was cancelled.");
    }
  };
  const active = async (
    owner: number,
    expected?: LocalSessionBinding | null,
  ) => {
    current(owner, expected);
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
    current(owner, expected);
    if (!foreground) throw new Error("Return to CaseOps to unlock.");
  };
  const start = (
    body: (owner: number) => Promise<SessionIdentity | null>,
  ): Promise<SessionIdentity | null> => {
    if (running || resetting) return Promise.resolve(null);
    const owner = epoch;
    authorized = false;
    // Deferring the body publishes the lease before cover/store callbacks.
    const result = Promise.resolve()
      .then(() => body(owner))
      .catch(() => {
        if (owner === epoch)
          publish(
            policy || !loaded ? "locked" : "off",
            policy || !loaded
              ? "Local lock policy or authentication could not be confirmed. Retry, or sign out and use secure sign-in."
              : "Workspace access could not be verified. Recheck it, or sign out and use secure sign-in.",
          );
        return null;
      })
      .finally(() => {
        if (running === result) {
          running = null;
          publish(
            authorized ? "unlocked" : policy || !loaded ? "locked" : "off",
            snapshot.message,
          );
        }
      });
    running = result;
    publish(policy || !loaded ? "prompting" : "off");
    return result;
  };
  const readCurrentPolicy = async (
    owner: number,
    expected?: LocalSessionBinding | null,
  ) => {
    current(owner, expected);
    const input = await store.readPolicy();
    current(owner, expected);
    const fresh = parseLocalUnlockPolicy(input, installationId);
    if (policy && (!fresh || JSON.stringify(policy) !== JSON.stringify(fresh)))
      throw new Error("Local lock policy changed.");
    policy = fresh;
    loaded = true;
    return fresh;
  };
  const controller = {
    getSnapshot: () => snapshot,
    get required() {
      return policy !== null || !loaded;
    },
    get busy() {
      return running !== null || resetting !== null;
    },
    get commandEpoch() {
      return epoch;
    },
    commandCurrent(
      expectedEpoch: number,
      expected: LocalSessionBinding | null,
    ): boolean {
      if (!foreground || expectedEpoch !== epoch) return false;
      const live = authority.current();
      return expected === null
        ? live === null
        : !!live &&
            live.sessionKey === expected.sessionKey &&
            sameServerBinding(expected, live);
    },
    allows(binding: LocalSessionBinding | null) {
      return (
        authorized &&
        foreground &&
        !!binding &&
        !!authorizedBinding &&
        authorizedBinding.sessionKey === binding.sessionKey &&
        sameServerBinding(authorizedBinding, binding) &&
        (!policy || sameServerBinding(policy.binding, binding))
      );
    },
    visibility(state: "active" | "inactive" | "background") {
      foreground = state === "active";
      if (state === "inactive" && authorized && !running && !resetting) ++epoch;
      if (state === "background") {
        ++epoch;
        authorized = false;
      }
      if (!foreground) {
        authorized = false;
        publish(policy || !loaded ? "locked" : "off");
      }
      if (foreground) for (const waiter of [...activeWaiters]) waiter();
    },
    invalidate() {
      ++epoch;
      authorized = false;
      publish(policy || !loaded ? "locked" : "off");
    },
    initialize() {
      return start(async (owner) => {
        await readCurrentPolicy(owner);
        publish(
          policy ? "locked" : "off",
          policy?.state === "pending"
            ? "Biometric setup was not completed. Sign out and use secure sign-in."
            : "",
        );
        return null;
      });
    },
    resume(openServerSession: () => Promise<SessionIdentity | null>) {
      if (controller.allows(authority.current())) return Promise.resolve(null);
      return start(async (owner) => {
        const initial = authority.current();
        await readCurrentPolicy(owner, initial);
        if (policy) {
          publish("locked");
          return null;
        }
        await cover();
        current(owner, initial);
        const identity = await openServerSession();
        current(owner, initial);
        const binding = authority.current();
        await active(owner, binding);
        if (identity && binding && sameIdentity(binding, identity)) {
          authorizedBinding = binding;
          authorized = true;
          publish("unlocked");
        } else return null;
        return identity;
      });
    },
    unlock(openServerSession: () => Promise<SessionIdentity | null>) {
      if (controller.allows(authority.current())) return Promise.resolve(null);
      return start(async (owner) => {
        const initial = authority.current();
        current(owner, initial);
        await cover();
        current(owner, initial);
        const required = await readCurrentPolicy(owner, initial);
        if (!required || required.state !== "enabled")
          throw new Error("Biometric setup is not complete.");
        const marker = await store.readMarker();
        current(owner, initial);
        await active(owner, initial);
        if (marker !== localUnlockMarker(required))
          throw new Error("Local marker is missing or invalidated.");
        const identity = await openServerSession();
        current(owner, initial);
        const binding = authority.current();
        if (
          !identity ||
          !binding ||
          !sameIdentity(binding, identity) ||
          !sameServerBinding(required.binding, binding)
        )
          throw new Error("Session binding changed.");
        await active(owner, binding);
        authorizedBinding = binding;
        authorized = true;
        publish("unlocked");
        return identity;
      });
    },
    enable() {
      if (running || resetting) return Promise.resolve(null);
      if (!loaded || policy || !foreground || !authority.current())
        return Promise.resolve(null);
      try {
        if (!store.supported()) {
          publish(
            snapshot.status,
            "Biometric unlock is unavailable on this device. You can continue using secure sign-in.",
          );
          return Promise.resolve(null);
        }
      } catch {
        publish(
          snapshot.status,
          "Biometric availability could not be checked. Try again when ready.",
        );
        return Promise.resolve(null);
      }
      return start(async (owner) => {
        const binding = authority.current();
        if (!loaded || policy || !foreground || !binding)
          throw new Error("Biometric setup is unavailable.");
        await readCurrentPolicy(owner, binding);
        if (policy) throw new Error("Local lock policy changed.");
        await cover();
        current(owner, binding);
        await authority.revalidate();
        current(owner, binding);
        await store.clearMarker();
        current(owner, binding);
        const pending: LocalUnlockPolicy = {
          version: 1,
          state: "pending",
          installationId,
          nonce: store.nonce(),
          binding: {
            userId: binding.userId,
            companyId: binding.companyId,
            membershipId: binding.membershipId,
            sessionId: binding.sessionId,
          },
        };
        parseLocalUnlockPolicy(pending, installationId);
        policy = pending;
        await store.writePolicy(pending);
        current(owner, binding);
        await store.writeMarker(localUnlockMarker(pending));
        current(owner, binding);
        await active(owner, binding);
        const marker = await store.readMarker();
        current(owner, binding);
        await active(owner, binding);
        if (marker !== localUnlockMarker(pending))
          throw new Error("Biometric read-back failed.");
        const identity = await authority.revalidate();
        current(owner, binding);
        if (!sameIdentity(binding, identity))
          throw new Error("Session binding changed.");
        const enabled: LocalUnlockPolicy = { ...pending, state: "enabled" };
        await store.writePolicy(enabled);
        current(owner, binding);
        await active(owner, binding);
        policy = enabled;
        authorizedBinding = binding;
        authorized = true;
        publish("unlocked");
        return identity;
      });
    },
    reset(): Promise<void> {
      if (resetting) return resetting;
      ++epoch;
      authorized = false;
      const previous = running;
      resetting = (async () => {
        await previous;
        await cover();
        await store.clear();
        policy = null;
        loaded = true;
      })().finally(() => {
        resetting = null;
        publish(policy || !loaded ? "locked" : "off", snapshot.message);
      });
      publish("clearing");
      return resetting;
    },
  };
  return controller;
}
export type LocalUnlockController = ReturnType<typeof createLocalUnlock>;
