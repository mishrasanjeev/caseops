import { allowsNativeRedirect, DISABLED_NATIVE_LINK_POLICY, type NativeLinkPolicy } from "../../../web/lib/native-link-policy.cjs";
export const NATIVE_CALLBACK = "caseops://oauth/callback";
export type Handoff = {
  state: string;
  verifier: string;
  challenge: string;
  platform: "android" | "ios";
};

export function authSessionCallback(policy: NativeLinkPolicy, platform: string, osVersion: unknown): { redirectUri: string; options: { preferEphemeralSession: true; preferUniversalLinks?: true } } {
  if (policy.mode === "disabled" || !allowsNativeRedirect(policy.redirectUri, policy)) throw new Error("NATIVE_SIGN_IN_NOT_CONFIGURED");
  if (!["ios", "android"].includes(platform)) throw new Error("NATIVE_PLATFORM_REQUIRED");
  if (policy.mode === "https" && platform === "ios") {
    const version = typeof osVersion === "string" && /^(\d+)\.(\d+)(?:\.\d+)*$/.exec(osVersion);
    if (!version || Number(version[1]) < 17 || (Number(version[1]) === 17 && Number(version[2]) < 4))
      throw new Error("IOS_HTTPS_CALLBACK_REQUIRES_17_4");
    return { redirectUri: policy.redirectUri, options: { preferEphemeralSession: true, preferUniversalLinks: true } };
  }
  return { redirectUri: policy.redirectUri, options: { preferEphemeralSession: true } };
}

export function authorizationUrl(webOrigin: string, handoff: Handoff, policy: NativeLinkPolicy = DISABLED_NATIVE_LINK_POLICY): string {
  if (policy.mode === "disabled" || !allowsNativeRedirect(policy.redirectUri, policy)) throw new Error("NATIVE_SIGN_IN_NOT_CONFIGURED");
  const url = new URL("/native/sign-in", webOrigin);
  url.searchParams.set("code_challenge", handoff.challenge);
  url.searchParams.set("state", handoff.state);
  url.searchParams.set("platform", handoff.platform);
  url.searchParams.set("redirect_uri", policy.redirectUri);
  return url.href;
}

export function parseCallback(value: string, expectedState: string, policy: NativeLinkPolicy = DISABLED_NATIVE_LINK_POLICY): string {
  const url = new URL(value);
  if (
    !allowsNativeRedirect(`${url.protocol}//${url.host}${url.pathname}`, policy) ||
    url.hash ||
    url.username ||
    url.password ||
    url.port
  )
    throw new Error("The sign-in callback is not valid.");
  if (
    url.searchParams.getAll("state").length !== 1 ||
    url.searchParams.get("state") !== expectedState
  ) {
    throw new Error("This sign-in belongs to another request. Start again.");
  }
  if (
    url.searchParams.getAll("code").length !== 1 ||
    !/^[A-Za-z0-9_-]{32,256}$/.test(url.searchParams.get("code") || "")
  ) {
    throw new Error(
      "The sign-in did not return a valid single-use code. Start again.",
    );
  }
  if (
    [...url.searchParams.keys()].some((key) => !["state", "code"].includes(key))
  ) {
    throw new Error("The sign-in callback contains unsupported parameters.");
  }
  return url.searchParams.get("code")!;
}
