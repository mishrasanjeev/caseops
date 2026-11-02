export type NativeAuthorization = {
  code_challenge: string;
  state: string;
  platform: "android" | "ios";
  redirect_uri: string;
};

export function prepareNativeHandoff(
  request: NativeAuthorization,
  response: unknown,
  policy: NativeLinkPolicy = DISABLED_NATIVE_LINK_POLICY,
): { callback: string; expiresIn: number } {
  const value =
    response && typeof response === "object" && !Array.isArray(response)
      ? (response as Record<string, unknown>)
      : {};
  if (
    !allowsNativeRedirect(request.redirect_uri, policy) ||
    value.redirect_uri !== request.redirect_uri ||
    value.state !== request.state ||
    typeof value.code !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(value.code) ||
    typeof value.expires_in !== "number" ||
    !Number.isInteger(value.expires_in) ||
    value.expires_in < 15 ||
    value.expires_in > 120
  )
    throw new Error("Invalid native handoff response.");
  const callback = new URL(request.redirect_uri);
  callback.searchParams.set("code", value.code);
  callback.searchParams.set("state", request.state);
  return { callback: callback.href, expiresIn: value.expires_in };
}

export function openNativeApp(callback: string, policy: NativeLinkPolicy = DISABLED_NATIVE_LINK_POLICY): void {
  const target = new URL(callback);
  if (
    !allowsNativeRedirect(`${target.protocol}//${target.host}${target.pathname}`, policy) ||
    target.username ||
    target.password ||
    target.port ||
    target.hash ||
    [...target.searchParams.keys()].sort().join(",") !== "code,state" ||
    !/^[A-Za-z0-9_-]{43}$/.test(target.searchParams.get("code") || "") ||
    !/^[A-Za-z0-9._~-]{32,128}$/.test(target.searchParams.get("state") || "")
  )
    throw new Error("Invalid native callback.");
  window.location.assign(target.href);
}

export function parseNativeAuthorization(
  query: string,
  policy: NativeLinkPolicy = DISABLED_NATIVE_LINK_POLICY,
): NativeAuthorization | null {
  const values = new URLSearchParams(query);
  const allowed = ["code_challenge", "state", "platform", "redirect_uri"];
  if (
    [...values.keys()].some((key) => !allowed.includes(key)) ||
    allowed.some((key) => values.getAll(key).length !== 1)
  )
    return null;
  const challenge = values.get("code_challenge") || "";
  const state = values.get("state") || "";
  const platform = values.get("platform");
  const redirect = values.get("redirect_uri") || "";
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(challenge) ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(state) ||
    !["android", "ios"].includes(platform || "") ||
    !allowsNativeRedirect(redirect, policy)
  )
    return null;
  return {
    code_challenge: challenge,
    state,
    platform: platform as "android" | "ios",
    redirect_uri: redirect,
  };
}
import { allowsNativeRedirect, DISABLED_NATIVE_LINK_POLICY, type NativeLinkPolicy } from './native-link-policy.cjs';
