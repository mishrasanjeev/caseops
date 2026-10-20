import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

describe("platform security page entry", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let enrollment: boolean;
  beforeEach(() => {
    enrollment = false;
    document.cookie = "caseops_console_csrf=security-console-proof; Path=/";
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return new Response(JSON.stringify({ state: "mfa_enrollment_required", admin: null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null }), { status: enrollment ? 200 : 401 });
      if (url.endsWith("/auth/mfa/enroll")) return new Response(JSON.stringify({ secret: "TESTONLYSETUPKEY", otpauth_url: "otpauth://totp/CaseOps:fixture?secret=TESTONLYSETUPKEY" }));
      throw new Error("Unexpected security request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); document.cookie = "caseops_console_csrf=; Max-Age=0; Path=/"; });

  it("shows independent sign-in recovery without mounting MFA for anonymous users", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Platform account security");
    expect(await screen.findByText("Sign in to manage your platform account.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Platform sign in" })).toHaveAttribute("href", "/platform/sign-in");
    expect(screen.queryByRole("button", { name: "Set up authenticator" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls).toHaveLength(1);
  });
  it("composes manual enrollment only after an explicit limited-session command", async () => {
    enrollment = true;
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    const button = await screen.findByRole("button", { name: "Set up authenticator" });
    expect(fetcher.mock.calls).toHaveLength(1);
    fireEvent.click(button);
    expect(await screen.findByLabelText("Authenticator setup key")).toHaveValue("TESTONLYSETUPKEY");
    expect(screen.getByLabelText("Six-digit code")).toBeVisible();
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/mfa/enroll"));
    expect(calls).toHaveLength(1);
    expect((calls[0][1] as RequestInit).headers).toHaveProperty("X-Console-CSRF-Token", "security-console-proof");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reset password" })).toHaveAttribute("href", "/platform/reset-password");
  });
});
