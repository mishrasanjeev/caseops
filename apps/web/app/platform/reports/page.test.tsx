import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { activityFixture } from "@/lib/platform/activity-fixture.test-data";
import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

describe("platform reports page entry", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let state: "anonymous" | "mfa_challenge_required" | "authenticated";
  beforeEach(() => {
    state = "anonymous";
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return new Response(JSON.stringify({ state, admin: state === "authenticated" ? { id: "viewer", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" } : null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null }), { status: state === "anonymous" ? 401 : 200 });
      if (url.endsWith("/reports/activity")) return new Response(JSON.stringify(activityFixture()));
      throw new Error("Unexpected report request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("keeps report components and reads behind the anonymous entry gate", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(await screen.findByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in to platform reports" })).toHaveAttribute("href", "/platform/sign-in");
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/reports/"))).toHaveLength(0);
  });
  it("requires MFA before mounting the report tab surface", async () => {
    state = "mfa_challenge_required";
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(await screen.findByRole("heading", { name: "Verification required" })).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/reports/"))).toHaveLength(0);
  });
  it("renders all six views and canonical activity for a verified reports-only viewer", async () => {
    state = "authenticated";
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Platform reports");
    expect(await screen.findByText("Test-legal law firm")).toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    expect(screen.getByText("All registered accounts")).toBeVisible();
    expect(screen.getByText("No recorded activity for 30 days (1)")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Administrators" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/reports/activity"))).toHaveLength(1);
  });
});
