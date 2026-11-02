const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "10.0.2.2"]);

// System-browser native sign-in cannot inherit Playwright's request headers.
export function localAcceptanceRequest(
  input: RequestInfo | URL,
  init: RequestInit,
  enabled: boolean,
  browserOrigin: string | null,
): RequestInit {
  if (!enabled) return init;
  const reject = () => new Error("Local acceptance is restricted to the isolated workstation API.");
  if (!browserOrigin) throw reject();
  const browser = new URL(browserOrigin);
  const request = typeof Request !== "undefined" && input instanceof Request ? input : null;
  const target = new URL(request ? request.url : String(input), browser);
  if (
    !LOCAL_HOSTS.has(browser.hostname) || !LOCAL_HOSTS.has(target.hostname) ||
    browser.username || browser.password || target.username || target.password ||
    !["http:", "https:"].includes(browser.protocol) ||
    !["http:", "https:"].includes(target.protocol) ||
    !target.pathname.startsWith("/api/")
  ) throw reject();
  const headers = new Headers(init.headers ?? request?.headers);
  headers.set("X-CaseOps-Automated-Test", "no-paid-providers");
  return { ...init, headers };
}
