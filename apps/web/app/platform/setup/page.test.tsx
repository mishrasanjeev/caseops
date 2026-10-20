import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
describe("platform invitation page composition", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let accepted: boolean;
  beforeEach(() => {
    replace.mockReset(); accepted = true;
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return new Response("{}", { status: 401 });
      if (url.endsWith("/auth/invitations/complete")) {
        expect(window.location.hash).toBe("");
        return new Response(JSON.stringify({ state: "mfa_enrollment_required", admin: null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null }), { status: accepted ? 200 : 401 });
      }
      throw new Error("Unexpected setup request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });
  function fill() {
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Invitee" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "form-input" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "form-input" } });
    fireEvent.submit(screen.getByRole("form", { name: "Accept invitation" }));
  }
  it("gives a missing link explicit resend recovery without accepting or sending", () => {
    window.history.replaceState(null, "", "/platform/setup");
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Accept report administrator invitation");
    expect(screen.getByRole("form", { name: "Resend setup email" })).toBeVisible();
    expect(screen.queryByRole("form", { name: "Accept invitation" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith("/auth/session"))).toBe(true);
  });
  it("scrubs the fragment before posting one-use setup and still routes through MFA", async () => {
    const token = "x".repeat(40);
    window.history.replaceState(null, "", `/platform/setup#token=${token}`);
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(window.location.hash).toBe("");
    fill();
    await waitFor(() => expect(replace).toHaveBeenCalledExactlyOnceWith("/platform/security"));
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/invitations/complete"));
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String((calls[0][1] as RequestInit).body))).toEqual({ token, password: "form-input", full_name: "Invitee" });
    expect(document.body.textContent).not.toContain(token);
    expect(screen.getByLabelText("Password", { exact: true })).toHaveValue("");
  });
  it("exposes explicit recovery when a well-formed link has expired, without automatic resend", async () => {
    accepted = false;
    window.history.replaceState(null, "", `/platform/setup#token=${"x".repeat(40)}`);
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    fill();
    expect(await screen.findByRole("form", { name: "Resend setup email" })).toBeVisible();
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/auth/invitations/complete"))).toHaveLength(1);
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/auth/invitations/resend"))).toBe(false);
    expect(replace).not.toHaveBeenCalled();
  });
});
