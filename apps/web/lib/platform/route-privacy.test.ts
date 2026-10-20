import { describe, expect, it, vi } from "vitest";

import { fetchCache, metadata, revalidate } from "@/app/platform/layout";
import sitemap from "@/app/sitemap";
import { proxy } from "@/proxy";

vi.mock("next/server", () => ({ NextResponse: { next: () => ({ headers: new Headers() }) } }));

describe("platform route privacy integration", () => {
  it.each(["/platform/sign-in", "/platform/reports", "/platform/admins", "/platform/security", "/platform/setup", "/platform/reset-password"])("sets actual proxy response headers for %s", (path) => {
    const result = proxy({ nextUrl: new URL(`http://localhost${path}`), headers: new Headers() } as Parameters<typeof proxy>[0]);
    expect(result.headers.get("Cache-Control")).toContain("no-store");
    expect(result.headers.get("Referrer-Policy")).toBe("no-referrer");
    expect(result.headers.get("X-Robots-Tag")).toBe("noindex, nofollow, noarchive");
  });
  it("does not change public caching through the platform privacy branch", () => {
    const result = proxy({ nextUrl: new URL("http://localhost/pricing"), headers: new Headers() } as Parameters<typeof proxy>[0]);
    expect(result.headers.has("Cache-Control")).toBe(false);
    expect(result.headers.get("Content-Security-Policy")).toBeTruthy();
  });
  it("disables metadata indexing and route-data caching without tenant providers", () => {
    expect(metadata.robots).toMatchObject({ index: false, follow: false, noarchive: true });
    expect(metadata.referrer).toBe("no-referrer");
    expect(revalidate).toBe(0); expect(fetchCache).toBe("force-no-store");
  });
  it("never advertises a private platform page in the public sitemap", () => {
    expect(sitemap().some((row) => new URL(row.url).pathname.startsWith("/platform"))).toBe(false);
  });
});
