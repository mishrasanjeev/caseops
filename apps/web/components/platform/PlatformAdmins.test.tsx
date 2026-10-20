import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformApi } from "@/lib/platform/client";

import { PlatformAdmins } from "./PlatformAdmins";

const principal = vi.hoisted(() => ({ role: "manager" }));
vi.mock("@/lib/platform/session", () => ({ usePlatformSession: () => ({ status: "ready", auth: { state: "authenticated", admin: { id: "manager-id", role: principal.role }, expires_at: "2099-01-01T00:00:00Z" }, signOut: vi.fn() }) }));
vi.mock("@/lib/platform/client", () => ({ platformApi: { admins: vi.fn(), invite: vi.fn(), revoke: vi.fn() }, ConsoleError: class extends Error {}, consoleErrorMessage: () => "Request refused." }));
const manager = { id: "manager-id", email: "manager@example.invalid", full_name: "Manager", role: "manager" as const, status: "active" as const, created_at: "2026-10-20T00:00:00Z" };
const viewer = { ...manager, id: "viewer-id", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" as const };
describe("explicit report administrator management", () => {
  beforeEach(() => {
    vi.clearAllMocks(); principal.role = "manager";
    vi.mocked(platformApi.admins).mockResolvedValue({ items: [manager, viewer], next_cursor: null });
  });
  it("does not load the directory for a delegated viewer", async () => {
    principal.role = "viewer"; render(<PlatformAdmins />);
    expect(screen.getByRole("alert")).toHaveTextContent("manager access");
    expect(platformApi.admins).not.toHaveBeenCalled();
  });
  it("invites only explicit email/name and qualifies transport acceptance", async () => {
    vi.mocked(platformApi.invite).mockResolvedValue({ admin: { ...viewer, status: "pending" }, delivery_status: "accepted" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "New viewer" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Invite report administrator" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Inbox delivery is not confirmed");
    expect(platformApi.invite).toHaveBeenCalledExactlyOnceWith({ email: "new@example.invalid", full_name: "New viewer" });
  });
  it("requires a reason and explicit confirmation for revoke; manager self-revoke is disabled", async () => {
    vi.mocked(platformApi.revoke).mockResolvedValue({ ...viewer, status: "revoked" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    const buttons = screen.getAllByRole("button", { name: "Revoke" });
    expect(buttons[0]).toBeDisabled();
    fireEvent.click(buttons[1]);
    expect(platformApi.revoke).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Access no longer required" } });
    fireEvent.submit(screen.getByRole("form", { name: "Revoke administrator access" }));
    await waitFor(() => expect(platformApi.revoke).toHaveBeenCalledExactlyOnceWith("viewer-id", "Access no longer required"));
  });
  it("does not automatically resend an unknown delivery outcome", async () => {
    vi.mocked(platformApi.invite).mockResolvedValue({ admin: { ...viewer, status: "pending" }, delivery_status: "outcome_unknown" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "New viewer" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Invite report administrator" }));
    expect(await screen.findByRole("status")).toHaveTextContent("outcome is unknown");
    expect(screen.getByRole("button", { name: "Invite viewer" })).toBeDisabled();
    expect(platformApi.invite).toHaveBeenCalledTimes(1);
  });
});
