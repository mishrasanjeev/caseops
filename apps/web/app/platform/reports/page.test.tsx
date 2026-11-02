import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { activityFixture } from "@/lib/platform/activity-fixture.test-data";
import { PLATFORM_SESSION_INVALIDATED } from "@/lib/platform/client";
import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("platform reports page entry", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let sessionResponse: ReturnType<typeof deferredResponse>;
  let activityResponse: ReturnType<typeof deferredResponse>;
  const reportCalls = () => fetcher.mock.calls.filter(([url]) => String(url).includes("/reports/"));
  const completeSession = async (state: "anonymous" | "mfa_challenge_required" | "authenticated") => {
    await act(async () => {
      sessionResponse.resolve(new Response(JSON.stringify({
        state,
        admin: state === "authenticated" ? { id: "viewer", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" } : null,
        expires_at: "2099-01-01T00:00:00Z",
        recovery_codes: null,
      }), { status: state === "anonymous" ? 401 : 200 }));
      await sessionResponse.promise;
    });
  };
  const completeActivity = async () => {
    await act(async () => {
      activityResponse.resolve(new Response(JSON.stringify(activityFixture())));
      await activityResponse.promise;
    });
  };
  beforeEach(() => {
    sessionResponse = deferredResponse();
    activityResponse = deferredResponse();
    fetcher = vi.fn((url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return sessionResponse.promise;
      if (url.endsWith("/reports/activity")) return activityResponse.promise;
      throw new Error("Unexpected report request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("keeps report components and reads behind the anonymous entry gate", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(screen.getByText("Checking platform access...")).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(reportCalls()).toHaveLength(0);
    await completeSession("anonymous");
    expect(screen.getByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in to platform reports" })).toHaveAttribute("href", "/platform/sign-in");
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    expect(reportCalls()).toHaveLength(0);
  });
  it("requires MFA before mounting the report tab surface", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(screen.getByText("Checking platform access...")).toBeVisible();
    expect(reportCalls()).toHaveLength(0);
    await completeSession("mfa_challenge_required");
    expect(screen.getByRole("heading", { name: "Verification required" })).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    expect(reportCalls()).toHaveLength(0);
  });
  it("renders all six views and canonical activity for a verified reports-only viewer", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Platform reports");
    expect(screen.getByText("Checking platform access...")).toBeVisible();
    expect(reportCalls()).toHaveLength(0);
    await completeSession("authenticated");
    expect(screen.getByText("Loading account activity...")).toBeVisible();
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    expect(reportCalls()).toHaveLength(1);
    await completeActivity();
    expect(screen.getByText("Test-legal law firm")).toBeVisible();
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    expect(screen.getByText("All registered accounts")).toBeVisible();
    expect(screen.getByText("No recorded activity for 30 days (1)")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Administrators" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/reports/activity"))).toHaveLength(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("keeps a late activity response hidden after session invalidation without another read", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(screen.getByText("Checking platform access...")).toBeVisible();
    expect(reportCalls()).toHaveLength(0);
    await completeSession("authenticated");
    expect(screen.getByText("Loading account activity...")).toBeVisible();
    expect(reportCalls()).toHaveLength(1);
    act(() => { window.dispatchEvent(new Event(PLATFORM_SESSION_INVALIDATED)); });
    expect(screen.getByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    await completeActivity();
    expect(screen.getByRole("heading", { name: "Sign in required" })).toBeVisible();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByText("Test-legal law firm")).not.toBeInTheDocument();
    expect(reportCalls()).toHaveLength(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
