export const NATIVE_CALLBACK = "caseops://oauth/callback";
export type Handoff = {
  state: string;
  verifier: string;
  challenge: string;
  platform: "android" | "ios";
};

export function authorizationUrl(webOrigin: string, handoff: Handoff): string {
  const url = new URL("/native/sign-in", webOrigin);
  url.searchParams.set("code_challenge", handoff.challenge);
  url.searchParams.set("state", handoff.state);
  url.searchParams.set("platform", handoff.platform);
  url.searchParams.set("redirect_uri", NATIVE_CALLBACK);
  return url.href;
}

export function parseCallback(value: string, expectedState: string): string {
  const url = new URL(value);
  if (
    `${url.protocol}//${url.host}${url.pathname}` !== NATIVE_CALLBACK ||
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
