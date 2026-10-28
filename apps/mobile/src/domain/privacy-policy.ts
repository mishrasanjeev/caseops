export type PrivacyPolicy = Readonly<{
  url: string;
  version: string;
  sha256: string;
}>;
export const PRIVACY_POLICY_OPEN_TIMEOUT_MS = 10_000;
export function decodePrivacyPolicy(
  value: unknown,
  webOrigin: unknown,
): PrivacyPolicy | null {
  if (value === null || value === undefined) return null;
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(",") !== "sha256,url,version"
  )
    throw Error("Privacy policy unavailable");
  const p = value as Record<string, unknown>;
  try {
    if (
      typeof p.url !== "string" ||
      p.url.length > 2048 ||
      !/^[\x21-\x7e]+$/.test(p.url) ||
      p.url.includes("\\") ||
      p.url.includes("?") ||
      p.url.includes("#") ||
      typeof webOrigin !== "string" ||
      typeof p.version !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(p.version) ||
      typeof p.sha256 !== "string" ||
      !/^[a-f0-9]{64}$/.test(p.sha256)
    )
      throw Error();
    const u = new URL(p.url),
      base = new URL(webOrigin);
    if (
      u.protocol !== "https:" ||
      u.port ||
      u.username ||
      u.password ||
      u.search ||
      u.hash ||
      u.href !== p.url ||
      u.origin !== webOrigin ||
      base.origin !== webOrigin ||
      base.href !== webOrigin + "/"
    )
      throw Error();
    return Object.freeze({ url: p.url, version: p.version, sha256: p.sha256 });
  } catch {
    throw Error("Privacy policy unavailable");
  }
}
export type PrivacyPolicyState = Readonly<{
  status:
    | "unconfigured"
    | "unavailable"
    | "ready"
    | "opening"
    | "opened"
    | "unknown";
  message: string;
}>;
export function createPrivacyPolicyOpener(
  input: unknown,
  webOrigin: unknown,
  deps: {
    openUrl: (url: string) => Promise<unknown>;
    allowed: () => boolean;
    changed: (state: PrivacyPolicyState) => void;
    setTimer?: (callback: () => void, delay: number) => unknown;
    clearTimer?: (handle: unknown) => void;
  },
) {
  let policy: PrivacyPolicy | null = null,
    disposed = false,
    busy = false,
    uncertain = false;
  let state: PrivacyPolicyState;
  try {
    policy = decodePrivacyPolicy(input, webOrigin);
    state = {
      status: policy ? "ready" : "unconfigured",
      message: policy
        ? "Opens in your web browser."
        : "A privacy policy link has not been configured for this build.",
    };
  } catch {
    state = {
      status: "unavailable",
      message: "The privacy policy link is unavailable in this build.",
    };
  }
  const setTimer =
    deps.setTimer || ((callback, delay) => setTimeout(callback, delay));
  const clearTimer =
    deps.clearTimer ||
    ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  let timer: unknown;
  const publish = (next: PrivacyPolicyState) => {
    if (!disposed) {
      state = next;
      deps.changed(next);
    }
  };
  return {
    snapshot: () => state,
    open() {
      if (!policy || disposed || busy || uncertain || !deps.allowed())
        return false;
      busy = true;
      publish({ status: "opening", message: "Opening privacy policy…" });
      if (disposed || !deps.allowed()) {
        if (!disposed)
          publish({ status: "ready", message: "Opens in your web browser." });
        busy = false;
        return false;
      }
      let finished = false;
      const finish = (success: boolean) => {
        if (finished || disposed) return;
        finished = true;
        clearTimer(timer);
        busy = false;
        uncertain = !success;
        publish(
          success
            ? {
                status: "opened",
                message: "Opened in your browser.",
              }
            : {
                status: "unknown",
                message:
                  "Could not confirm the privacy policy opened. Check your browser or contact the publisher.",
              },
        );
      };
      timer = setTimer(() => finish(false), PRIVACY_POLICY_OPEN_TIMEOUT_MS);
      try {
        Promise.resolve(deps.openUrl(policy.url)).then(
          () => finish(true),
          () => finish(false),
        );
      } catch {
        finish(false);
      }
      return true;
    },
    dispose() {
      disposed = true;
      clearTimer(timer);
    },
  };
}
