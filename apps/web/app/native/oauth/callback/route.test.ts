import { afterEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { GET, dynamic } from "./route";

describe("inert native HTTPS callback fallback", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("permits only the fixed URL scrub while remaining dynamic, uncacheable, unindexed and without referrers", async () => {
    const response = GET();
    expect(dynamic).toBe("force-dynamic");
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/html; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(response.headers.get("x-robots-tag")).toBe("noindex, nofollow");
    const scrub = 'history.replaceState(null,"","/native/oauth/callback");';
    const hash = createHash("sha256").update(scrub).digest("base64");
    expect(response.headers.get("content-security-policy")).toBe(`default-src 'none'; script-src 'sha256-${hash}'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
    const document = new DOMParser().parseFromString(await response.text(), "text/html");
    expect(document.title).toBe("Sign-in not completed");
    expect(document.body.textContent).toBe("The app did not receive this sign-in. Return to CaseOps and start sign-in again.");
    expect([...document.scripts].map(script => script.textContent)).toEqual([scrub]);
    expect(document.querySelectorAll("[src],a,form,iframe,object")).toHaveLength(0);
  });

  it.each([
    "code=synthetic-sensitive-code&state=synthetic-sensitive-state&access_token=synthetic-bearer",
    "redirect_uri=caseops%3A%2F%2Foauth%2Fcallback&return_to=https%3A%2F%2Fattacker.invalid",
    "code=first&code=second&state=first&state=second&error_description=synthetic-sensitive-error",
  ])("returns the same static body without reflecting or exchanging callback/query material %#", async (query) => {
    const fetch = vi.fn(() => { throw new Error("CALLBACK_NETWORK_FORBIDDEN"); });
    vi.stubGlobal("fetch", fetch);
    const baseline = await GET().text();
    const request = new Request(`https://native.invalid/native/oauth/callback?${query}`);
    const response = Reflect.apply(GET, undefined, [request]) as Response;
    const body = await response.text();
    expect(body).toBe(baseline);
    for (const value of new URL(request.url).searchParams.values()) expect(body).not.toContain(value);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not even read caller URL, headers or cookies to construct a fallback", async () => {
    const request = new Proxy({}, { get: () => { throw new Error("PRIVATE_CALLBACK_REQUEST_READ_FORBIDDEN"); } });
    const response = Reflect.apply(GET, undefined, [request]) as Response;
    expect(await response.text()).toContain("Return to CaseOps and start sign-in again.");
    expect(response.headers.get("location")).toBeNull();
  });
});
