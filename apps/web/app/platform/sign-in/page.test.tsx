import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("platform sign-in page composition", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    replace.mockReset();
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return json({}, 401);
      if (url.endsWith("/auth/login")) return json({ state: "mfa_challenge_required", admin: null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null });
      if (url.endsWith("/auth/invitations/resend")) return json({ status: "accepted" });
      throw new Error("Unexpected console request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("renders the independent entry form without a tenant/workspace credential", () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Platform sign in");
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(screen.getByRole("form", { name: "Platform sign in" })).toBeVisible();
    expect(screen.queryByLabelText(/workspace|tenant/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/platform/reset-password");
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith("/auth/session"))).toBe(true);
  });

  it("submits once to the console realm and enters MFA rather than tenant reports", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    fireEvent.change(within(screen.getByRole("form", { name: "Platform sign in" })).getByLabelText("Email", { exact: true }), { target: { value: "viewer@example.invalid" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "form-input" } });
    fireEvent.submit(screen.getByRole("form", { name: "Platform sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledExactlyOnceWith("/platform/security"));
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/login"));
    expect(calls).toHaveLength(1);
    const init = calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ email: "viewer@example.invalid", password: "form-input" });
    expect(init.credentials).toBe("include");
    expect(init.headers).not.toHaveProperty("Authorization");
    expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
  });

  it("makes setup-email recovery an explicit generic command, not a login side effect", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    fireEvent.click(screen.getByText("Resend setup email", { selector: "summary" }));
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/auth/invitations/resend"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Email", { selector: "#platform-resend-email" }), { target: { value: "viewer@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Resend setup email" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If this account is eligible");
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/invitations/resend"))).toHaveLength(1);
  });
});
