import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleError, platformApi } from "@/lib/platform/client";

import { PlatformAccountLink } from "./PlatformAccountLink";
import { PlatformLinkBoundary } from "./PlatformLinkBoundary";

const { accept, replace } = vi.hoisted(() => ({ accept: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/platform/session", () => ({ usePlatformSession: () => ({ accept }) }));
vi.mock("@/lib/platform/client", async (load) => {
  const actual = await load<typeof import("@/lib/platform/client")>();
  return { ...actual, platformApi: { acceptInvitation: vi.fn(), resendInvitation: vi.fn(), startReset: vi.fn(), completeReset: vi.fn() } };
});

describe("setup link recovery", () => {
  beforeEach(() => { vi.clearAllMocks(); Object.values(platformApi).forEach((method) => vi.mocked(method).mockReset()); });
  afterEach(() => window.history.replaceState(null, "", "/"));
  it("offers explicit resend on a missing setup link without sending automatically", () => {
    window.history.replaceState(null, "", "/platform/setup");
    render(<PlatformLinkBoundary><PlatformAccountLink mode="setup" /></PlatformLinkBoundary>);
    expect(screen.getByRole("form", { name: "Resend setup email" })).toBeVisible();
    expect(platformApi.resendInvitation).not.toHaveBeenCalled();
    expect(platformApi.acceptInvitation).not.toHaveBeenCalled();
  });
  it("offers the same explicit command after a server rejects an expired one-use link", async () => {
    window.history.replaceState(null, "", `/platform/setup#token=${"x".repeat(40)}`);
    vi.mocked(platformApi.acceptInvitation).mockRejectedValue(new ConsoleError(401, "unauthorized"));
    vi.mocked(platformApi.resendInvitation).mockResolvedValue({ status: "accepted" });
    render(<PlatformLinkBoundary><PlatformAccountLink mode="setup" /></PlatformLinkBoundary>);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Recipient" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "ephemeral-input" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "ephemeral-input" } });
    fireEvent.submit(screen.getByRole("form", { name: "Accept invitation" }));
    const resend = await screen.findByRole("form", { name: "Resend setup email" });
    expect(screen.queryByRole("form", { name: "Accept invitation" })).not.toBeInTheDocument();
    expect(platformApi.resendInvitation).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "recipient@example.invalid" } });
    fireEvent.submit(resend);
    expect(await screen.findByRole("status")).toHaveTextContent("If this account is eligible");
    expect(platformApi.acceptInvitation).toHaveBeenCalledTimes(1);
    expect(platformApi.resendInvitation).toHaveBeenCalledExactlyOnceWith("recipient@example.invalid");
    expect(window.location.hash).toBe("");
  });
  it("does not request a new invitation automatically on a transport failure", async () => {
    window.history.replaceState(null, "", `/platform/setup#token=${"x".repeat(40)}`);
    vi.mocked(platformApi.acceptInvitation).mockRejectedValue(new TypeError("sensitive transport detail"));
    render(<PlatformLinkBoundary><PlatformAccountLink mode="setup" /></PlatformLinkBoundary>);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Recipient" } });
    fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "ephemeral-input" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "ephemeral-input" } });
    fireEvent.submit(screen.getByRole("form", { name: "Accept invitation" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("sensitive transport detail");
    expect(platformApi.acceptInvitation).toHaveBeenCalledTimes(1);
    expect(platformApi.resendInvitation).not.toHaveBeenCalled();
  });
});

describe("fresh setup/reset links without a page reload", () => {
  const freshAuth = { state: "mfa_enrollment_required" as const, admin: null, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null };
  const oldToken = "a".repeat(40);
  const freshToken = "b".repeat(40);
  beforeEach(() => { vi.clearAllMocks(); Object.values(platformApi).forEach((method) => vi.mocked(method).mockReset()); });
  afterEach(() => window.history.replaceState(null, "", "/"));
  function fill(mode: "setup" | "reset", password = "form-input") {
    if (mode === "setup") fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Fresh recipient" } });
    fireEvent.change(screen.getByLabelText(mode === "setup" ? "Password" : "New password", { exact: true }), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: password } });
  }
  function submit(mode: "setup" | "reset") {
    fireEvent.submit(screen.getByRole("form", { name: mode === "setup" ? "Accept invitation" : "Platform password reset" }));
  }
  async function freshLink(mode: "setup" | "reset") {
    act(() => { window.location.hash = `token=${freshToken}`; });
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(screen.getByRole("form", { name: mode === "setup" ? "Accept invitation" : "Platform password reset" })).toBeVisible();
    expect(screen.getByLabelText(mode === "setup" ? "Password" : "New password", { exact: true })).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(freshToken);
  }
  it.each(["setup", "reset"] as const)("clears rejected %s form state and uses the new token", async (mode) => {
    const path = mode === "setup" ? "setup" : "reset-password";
    window.history.replaceState(null, "", `/platform/${path}#token=${oldToken}`);
    vi.mocked(platformApi.acceptInvitation).mockRejectedValueOnce(new ConsoleError(401, "unauthorized")).mockResolvedValue(freshAuth);
    vi.mocked(platformApi.completeReset).mockRejectedValueOnce(new ConsoleError(401, "unauthorized")).mockResolvedValue({ status: "complete" });
    render(<PlatformLinkBoundary><PlatformAccountLink mode={mode} /></PlatformLinkBoundary>);
    fill(mode); submit(mode);
    await screen.findByRole("alert");
    if (mode === "setup") {
      vi.mocked(platformApi.resendInvitation).mockResolvedValue({ status: "accepted" });
      fireEvent.change(screen.getByLabelText("Email"), { target: { value: "recipient@example.invalid" } });
      fireEvent.submit(screen.getByRole("form", { name: "Resend setup email" }));
      await screen.findByRole("status");
    }
    await freshLink(mode);
    fill(mode); submit(mode);
    if (mode === "setup") await waitFor(() => expect(replace).toHaveBeenCalledExactlyOnceWith("/platform/security"));
    else expect(await screen.findByRole("status")).toHaveTextContent("Password reset complete");
    const calls = mode === "setup" ? vi.mocked(platformApi.acceptInvitation).mock.calls : vi.mocked(platformApi.completeReset).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[1][0].token).toBe(freshToken);
    expect(document.body.textContent).not.toContain(oldToken);
  });
  it.each([
    ["setup", "success"], ["setup", "failure"], ["reset", "success"], ["reset", "failure"],
  ] as const)("ignores an old %s %s response after a fresh link arrived", async (mode, outcome) => {
    let finish!: () => void;
    let fail!: (reason: unknown) => void;
    const pending = new Promise<void>((resolve, reject) => { finish = resolve; fail = reject; });
    vi.mocked(platformApi.acceptInvitation).mockImplementationOnce(async () => { await pending; return freshAuth; }).mockResolvedValue(freshAuth);
    vi.mocked(platformApi.completeReset).mockImplementationOnce(async () => { await pending; return { status: "complete" }; }).mockResolvedValue({ status: "complete" });
    window.history.replaceState(null, "", `/platform/${mode === "setup" ? "setup" : "reset-password"}#token=${oldToken}`);
    render(<PlatformLinkBoundary><PlatformAccountLink mode={mode} /></PlatformLinkBoundary>);
    fill(mode); submit(mode);
    await freshLink(mode);
    const oldCall = mode === "setup" ? vi.mocked(platformApi.acceptInvitation).mock.calls[0] : vi.mocked(platformApi.completeReset).mock.calls[0];
    expect(oldCall[1]).toBeInstanceOf(AbortSignal);
    expect(oldCall[1]?.aborted).toBe(true);
    fill(mode, "new-form-input");
    await act(async () => { if (outcome === "success") finish(); else fail(new ConsoleError(401, "unauthorized")); await pending.catch(() => undefined); });
    expect(accept).not.toHaveBeenCalled(); expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText(mode === "setup" ? "Password" : "New password", { exact: true })).toHaveValue("new-form-input");
    submit(mode);
    if (mode === "setup") await waitFor(() => expect(accept).toHaveBeenCalledExactlyOnceWith(freshAuth));
    else expect(await screen.findByRole("status")).toHaveTextContent("Password reset complete");
  });
});
