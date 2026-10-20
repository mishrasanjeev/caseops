import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformApi } from "@/lib/platform/client";
import { usePlatformSession } from "@/lib/platform/session";

import { PlatformMfa } from "./PlatformMfa";

const { accept, replace } = vi.hoisted(() => ({ accept: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/platform/session", () => ({ usePlatformSession: vi.fn() }));
vi.mock("@/lib/platform/client", () => ({ platformApi: { enroll: vi.fn(), verify: vi.fn() }, consoleErrorMessage: () => "Verification was refused." }));

describe("platform MFA without tenant authentication", () => {
  const admin = { id: "viewer", email: "fixture@example.invalid", full_name: "Fixture", role: "viewer" as const };
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(usePlatformSession).mockReturnValue({ status: "ready", auth: { state: "mfa_enrollment_required", admin: null, expires_at: "2099-01-01T00:00:00Z" }, error: null, accept, refresh: vi.fn(), signOut: vi.fn() });
  });
  it("enrolls only on command and accepts the canonical manual setup DTO", async () => {
    vi.mocked(platformApi.enroll).mockResolvedValue({ secret: "TESTONLYSETUPKEY", otpauth_url: "otpauth://totp/CaseOps:fixture?secret=TESTONLYSETUPKEY" });
    vi.mocked(platformApi.verify).mockResolvedValue({ state: "authenticated", admin, expires_at: "2099-01-01T00:00:00Z", recovery_codes: ["TEST-RECOVERY-CODE"] });
    render(<PlatformMfa />);
    expect(platformApi.enroll).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Set up authenticator" }));
    expect(await screen.findByLabelText("Authenticator setup key")).toHaveValue("TESTONLYSETUPKEY");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Six-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify MFA" }));
    expect(await screen.findByRole("list", { name: "Recovery codes" })).toHaveTextContent("TEST-RECOVERY-CODE");
    expect(platformApi.verify).toHaveBeenCalledExactlyOnceWith({ code: "123456" });
    expect(screen.queryByDisplayValue("TESTONLYSETUPKEY")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue to reports" }));
    expect(screen.queryByText("TEST-RECOVERY-CODE")).not.toBeInTheDocument();
    expect(replace).toHaveBeenCalledExactlyOnceWith("/platform/reports");
  });
  it("uses only the chosen recovery factor and does not enroll a challenge session", async () => {
    vi.mocked(usePlatformSession).mockReturnValue({ status: "ready", auth: { state: "mfa_challenge_required", admin: null, expires_at: "2099-01-01T00:00:00Z" }, error: null, accept, refresh: vi.fn(), signOut: vi.fn() });
    vi.mocked(platformApi.verify).mockResolvedValue({ state: "authenticated", admin, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null });
    render(<PlatformMfa />);
    expect(screen.queryByRole("button", { name: "Set up authenticator" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recovery code" }));
    fireEvent.change(screen.getByLabelText("Recovery code", { selector: "input" }), { target: { value: "TEST-RECOVERY-CODE" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify MFA" }));
    expect(await screen.findByText("MFA verified")).toBeVisible();
    expect(platformApi.verify).toHaveBeenCalledExactlyOnceWith({ recovery_code: "TEST-RECOVERY-CODE" });
    expect(platformApi.enroll).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Recovery codes" })).not.toBeInTheDocument();
  });
  it("clears a refused factor without retrying or displaying private errors", async () => {
    vi.mocked(usePlatformSession).mockReturnValue({ status: "ready", auth: { state: "mfa_challenge_required", admin: null, expires_at: "2099-01-01T00:00:00Z" }, error: null, accept, refresh: vi.fn(), signOut: vi.fn() });
    vi.mocked(platformApi.verify).mockRejectedValue(new Error("private-response"));
    render(<PlatformMfa />);
    fireEvent.change(screen.getByLabelText("Six-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify MFA" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Verification was refused");
    expect(screen.getByLabelText("Six-digit code")).toHaveValue("");
    expect(platformApi.verify).toHaveBeenCalledTimes(1);
    expect(accept).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("private-response");
  });
});
