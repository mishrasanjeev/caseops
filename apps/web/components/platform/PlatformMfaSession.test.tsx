import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PLATFORM_SESSION_INVALIDATED } from "@/lib/platform/client";
import { PlatformSessionProvider, usePlatformSession } from "@/lib/platform/session";

import { PlatformSecurity } from "./PlatformSecurity";

const challenge = { state: "mfa_challenge_required", admin: null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null };
const authenticated = { ...challenge, state: "authenticated", admin: { id: "viewer", email: "viewer@example.invalid", full_name: "Report viewer", role: "viewer" } };
const problem = (code: string) => new Response(JSON.stringify({
  type: code, code, status: 401, title: "Unauthorized", detail: "private-factor-error-must-not-be-reflected",
  instance: "/api/platform-console/auth/mfa/verify",
}), { status: 401, headers: { "Content-Type": "application/problem+json" } });
const success = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
function StateProbe() {
  const session = usePlatformSession();
  return <output aria-label="Session state">{session.auth?.state ?? session.status}</output>;
}
function SecurityEntry() {
  return <PlatformSessionProvider><PlatformSecurity /><StateProbe /></PlatformSessionProvider>;
}

describe("MFA refusals through the real platform client and session", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  const invalidated = vi.fn();
  beforeEach(() => {
    invalidated.mockClear();
    document.cookie = "caseops_console_csrf=mfa-session-proof; Path=/";
    window.addEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => {
    window.removeEventListener(PLATFORM_SESSION_INVALIDATED, invalidated);
    vi.unstubAllGlobals();
    document.cookie = "caseops_console_csrf=; Max-Age=0; Path=/";
  });
  it.each(["recovery", "authenticator"])("retains the limited session after an invalid %s code and permits only an explicit fresh attempt", async (factor) => {
    let attempts = 0;
    fetcher.mockImplementation(async (url: string) => {
      if (url.endsWith("/auth/session")) return success(challenge);
      if (url.endsWith("/auth/mfa/verify")) return ++attempts === 1 ? problem("console_mfa_invalid") : success(authenticated);
      throw new Error("Unexpected platform request");
    });
    const user = userEvent.setup();
    render(<SecurityEntry />);
    await screen.findByRole("region", { name: "Multi-factor verification" });
    if (factor === "recovery") await user.click(screen.getByRole("button", { name: "Recovery code" }));
    const label = factor === "recovery" ? "Recovery code" : "Six-digit code";
    await user.type(screen.getByLabelText(label, { selector: "input" }), factor === "recovery" ? "USED-RECOVERY-CODE" : "123456");
    await user.click(screen.getByRole("button", { name: "Verify MFA" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Session state")).toHaveTextContent(/^mfa_challenge_required$/);
    expect(await screen.findByRole("alert")).toHaveTextContent("The MFA code is invalid or was already used.");
    expect(screen.getByLabelText(label, { selector: "input" })).toHaveValue("");
    expect(screen.queryByRole("link", { name: "Platform sign in" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Administrators" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("private-factor-error-must-not-be-reflected");
    expect(invalidated).not.toHaveBeenCalled();
    expect(attempts).toBe(1);
    await user.type(screen.getByLabelText(label, { selector: "input" }), factor === "recovery" ? "FRESH-RECOVERY-CODE" : "654321");
    await user.click(screen.getByRole("button", { name: "Verify MFA" }));
    expect(await screen.findByText("MFA verified")).toBeVisible();
    expect(screen.getByLabelText("Session state")).toHaveTextContent(/^authenticated$/);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(attempts).toBe(2);
  });
  it("still clears and unmounts MFA for the canonical expired/revoked-session refusal", async () => {
    fetcher.mockImplementation(async (url: string) => url.endsWith("/auth/session") ? success(challenge) : problem("console_session_invalid"));
    const user = userEvent.setup();
    render(<SecurityEntry />);
    await screen.findByRole("region", { name: "Multi-factor verification" });
    await user.type(screen.getByLabelText("Six-digit code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify MFA" }));
    expect(await screen.findByRole("link", { name: "Platform sign in" })).toBeVisible();
    expect(screen.getByLabelText("Session state")).toHaveTextContent(/^anonymous$/);
    expect(screen.queryByRole("region", { name: "Multi-factor verification" })).not.toBeInTheDocument();
    expect(invalidated).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
