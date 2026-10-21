import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

describe("platform leads page entry", () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  it("composes the protected directory without reading leads for an anonymous session", async () => {
    const fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/auth/session");
      return new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401 });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Platform leads");
    expect(await screen.findByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in to platform reports" })).toHaveAttribute("href", "/platform/sign-in");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
