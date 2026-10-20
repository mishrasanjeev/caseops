import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

describe("platform password reset page composition", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return new Response("{}", { status: 401 });
      if (url.endsWith("/auth/password-reset/start")) return new Response(JSON.stringify({ status: "accepted" }));
      if (url.endsWith("/auth/password-reset/complete")) {
        expect(window.location.hash).toBe("");
        return new Response(JSON.stringify({ status: "complete" }));
      }
      throw new Error("Unexpected password reset request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

  it("requests a reset explicitly with an existence-neutral response", async () => {
    window.history.replaceState(null, "", "/platform/reset-password");
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Reset platform password");
    expect(screen.getByRole("heading", { name: "Request password reset" })).toBeVisible();
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith("/auth/session"))).toBe(true);
    fireEvent.change(screen.getByLabelText("Email", { exact: true }), { target: { value: "viewer@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Platform password reset" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If this account is eligible");
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/password-reset/start"));
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String((calls[0][1] as RequestInit).body))).toEqual({ email: "viewer@example.invalid" });
  });
  it("scrubs a fragment token before completion and does not fabricate an authenticated session", async () => {
    const token = "x".repeat(40);
    window.history.replaceState(null, "", `/platform/reset-password#token=${token}`);
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(window.location.hash).toBe("");
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "form-input" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "form-input" } });
    fireEvent.submit(screen.getByRole("form", { name: "Platform password reset" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Sign in again and complete MFA");
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/password-reset/complete"));
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String((calls[0][1] as RequestInit).body))).toEqual({ token, password: "form-input" });
    expect(screen.getByLabelText("New password")).toHaveValue("");
    expect(document.body.textContent).not.toContain(token);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/reports/") || String(url).includes("/mfa/verify"))).toBe(false);
  });
  it("rejects query-token ambiguity without attempting a reset mutation", () => {
    window.history.replaceState(null, "", "/platform/reset-password?token=query#token=fragment");
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(screen.getByRole("alert")).toHaveTextContent("invalid, expired or already used");
    expect(screen.queryByRole("form", { name: "Platform password reset" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a fresh reset link" })).toHaveAttribute("href", "/platform/reset-password");
    expect(window.location.hash).toBe("");
    expect(window.location.search).toBe("");
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith("/auth/session"))).toBe(true);
  });
});
