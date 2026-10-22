import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformApi } from "@/lib/platform/client";

import { PlatformAdmins } from "./PlatformAdmins";

const principal = vi.hoisted(() => ({ role: "manager" }));
vi.mock("@/lib/platform/session", () => ({ usePlatformSession: () => ({ status: "ready", auth: { state: "authenticated", admin: { id: "manager-id", role: principal.role }, expires_at: "2099-01-01T00:00:00Z" }, signOut: vi.fn() }) }));
vi.mock("@/lib/platform/client", () => ({ platformApi: { managedAdmins: vi.fn(), invite: vi.fn(), revoke: vi.fn(), removeAdmin: vi.fn(), resendAdminInvitation: vi.fn() }, ConsoleError: class extends Error {}, consoleErrorMessage: () => "Request refused." }));
const manager = { id: "manager-id", email: "manager@example.invalid", full_name: "Manager", role: "manager" as const, status: "active" as const, created_at: "2026-10-20T00:00:00Z", version: 3, removed_at: null, can_manage: false };
const viewer = { ...manager, id: "viewer-id", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" as const, can_manage: true };
describe("explicit report administrator management", () => {
  beforeEach(() => {
    vi.clearAllMocks(); principal.role = "manager";
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, viewer], next_cursor: null });
  });
  it("does not load the directory for a delegated viewer", async () => {
    principal.role = "viewer"; render(<PlatformAdmins />);
    expect(screen.getByRole("alert")).toHaveTextContent("manager access");
    expect(platformApi.managedAdmins).not.toHaveBeenCalled();
  });
  it("invites only explicit email/name and qualifies transport acceptance", async () => {
    vi.mocked(platformApi.invite).mockResolvedValue({ admin: { ...viewer, status: "pending" }, delivery_status: "accepted" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "New viewer" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Invite report administrator" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Inbox delivery is not confirmed");
    expect(platformApi.invite).toHaveBeenCalledExactlyOnceWith({ email: "new@example.invalid", full_name: "New viewer", reinvite_revoked: true });
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
    await waitFor(() => expect(platformApi.revoke).toHaveBeenCalledExactlyOnceWith("viewer-id", "Access no longer required", 3));
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
  it("offers explicit resend for a pending invitation in the manager directory", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, { ...viewer, status: "pending" }], next_cursor: null });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    expect(screen.getByRole("button", { name: "Resend invitation for Viewer" })).toBeEnabled();
  });
  it("allows a revoked viewer to populate a deliberate fresh invitation", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, { ...viewer, status: "revoked" }], next_cursor: null });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Invite Viewer again" }));
    expect(screen.getByLabelText("Full name")).toHaveValue("Viewer");
    expect(screen.getByLabelText("Email")).toHaveValue("viewer@example.invalid");
    expect(platformApi.invite).not.toHaveBeenCalled();
  });
  it("offers confirmed report-access deletion without silently removing an account", async () => {
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Delete report access for Viewer" }));
    expect(screen.getByRole("form", { name: "Delete administrator access" })).toBeVisible();
    expect(screen.getByText("Tenant accounts and audit history will be retained.", { exact: true })).toBeVisible();
    expect(platformApi.removeAdmin).not.toHaveBeenCalled();
  });
  it("resends once with the current version and preserves unknown transport truth", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, { ...viewer, status: "pending" }], next_cursor: null });
    vi.mocked(platformApi.resendAdminInvitation).mockResolvedValue({ admin: { ...viewer, status: "pending" }, delivery_status: "outcome_unknown" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Resend invitation for Viewer" }));
    expect(await screen.findByRole("status")).toHaveTextContent("outcome is unknown");
    expect(platformApi.resendAdminInvitation).toHaveBeenCalledExactlyOnceWith("viewer-id", 3);
  });
  it("confirms deletion against the observed version and reloads the retained directory", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValueOnce({ items: [manager, viewer], next_cursor: null })
      .mockResolvedValue({ items: [manager], next_cursor: null });
    vi.mocked(platformApi.removeAdmin).mockResolvedValue({ ...viewer, status: "revoked" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Delete report access for Viewer" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Remove report-only access" } });
    fireEvent.submit(screen.getByRole("form", { name: "Delete administrator access" }));
    await waitFor(() => expect(platformApi.removeAdmin).toHaveBeenCalledExactlyOnceWith("viewer-id", "Remove report-only access", 3));
    await waitFor(() => expect(screen.queryByText("viewer@example.invalid")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Tenant accounts and audit history were retained");
  });
  it("does not delete or resend manager/self access", async () => {
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    expect(screen.getByRole("button", { name: "Delete report access for Manager" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Resend invitation for Manager" })).not.toBeInTheDocument();
    expect(platformApi.removeAdmin).not.toHaveBeenCalled();
    expect(platformApi.resendAdminInvitation).not.toHaveBeenCalled();
  });
  it("respects server-owned protection even when the record has a viewer role", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, { ...viewer, status: "pending", can_manage: false }], next_cursor: null });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    expect(screen.getByRole("button", { name: "Delete report access for Viewer" })).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "Revoke" })[1]).toBeDisabled();
    expect(screen.getByRole("button", { name: "Resend invitation for Viewer" })).toBeDisabled();
  });
  it("requires a deliberate submit after preparing a revoked email", async () => {
    vi.mocked(platformApi.managedAdmins).mockResolvedValue({ items: [manager, { ...viewer, status: "revoked" }], next_cursor: null });
    vi.mocked(platformApi.invite).mockResolvedValue({ admin: { ...viewer, status: "pending" }, delivery_status: "accepted" });
    render(<PlatformAdmins />); await screen.findByText("viewer@example.invalid");
    fireEvent.click(screen.getByRole("button", { name: "Invite Viewer again" }));
    expect(platformApi.invite).not.toHaveBeenCalled();
    fireEvent.submit(screen.getByRole("form", { name: "Invite report administrator" }));
    await waitFor(() => expect(platformApi.invite).toHaveBeenCalledExactlyOnceWith({
      email: "viewer@example.invalid", full_name: "Viewer", reinvite_revoked: true,
    }));
  });
});
