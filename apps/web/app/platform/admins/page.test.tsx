import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformSessionProvider } from "@/lib/platform/session";

import Page, { metadata } from "./page";

describe("report administrators page authority", () => {
  let fetcher: ReturnType<typeof vi.fn>;
  let role: "manager" | "viewer";
  const record = { id: "manager", email: "manager@example.invalid", full_name: "Manager", role: "manager", status: "active", created_at: "2026-10-20T00:00:00Z" };
  beforeEach(() => {
    role = "manager";
    document.cookie = "caseops_console_csrf=page-console-proof; Path=/";
    fetcher = vi.fn(async (url: string) => {
      expect(url).toContain("/api/platform-console/");
      if (url.endsWith("/auth/session")) return new Response(JSON.stringify({ state: "authenticated", admin: { id: "manager", email: record.email, full_name: record.full_name, role }, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null }));
      if (new URL(url).pathname.endsWith("/admins")) return new Response(JSON.stringify({ items: [record], next_cursor: null }));
      if (url.endsWith("/admins/invitations")) return new Response(JSON.stringify({ admin: { ...record, id: "pending", email: "invitee@example.invalid", full_name: "Invitee", role: "viewer", status: "pending" }, delivery_status: "accepted" }));
      throw new Error("Unexpected administrator request");
    });
    vi.stubGlobal("fetch", fetcher);
  });
  afterEach(() => { vi.unstubAllGlobals(); document.cookie = "caseops_console_csrf=; Max-Age=0; Path=/"; });

  it("does not load the directory or invite form for a delegated viewer", async () => {
    role = "viewer";
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("manager access");
    expect(screen.queryByRole("form", { name: "Invite report administrator" })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => String(url).endsWith("/auth/session"))).toBe(true);
  });
  it("renders the real manager directory and protects manager self-revocation", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    expect(metadata.title).toBe("Report administrators");
    expect(await screen.findByRole("heading", { name: "Report administrators" })).toBeVisible();
    const region = await screen.findByRole("region", { name: "Administrator directory" });
    expect(within(region).getByText(record.email)).toBeVisible();
    expect(within(region).getByRole("button", { name: "Revoke" })).toBeDisabled();
  });
  it("posts one explicit viewer invitation with the separate CSRF fence", async () => {
    render(<PlatformSessionProvider><Page /></PlatformSessionProvider>);
    await screen.findByRole("form", { name: "Invite report administrator" });
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Invitee" } });
    fireEvent.change(screen.getByLabelText("Email", { exact: true }), { target: { value: "invitee@example.invalid" } });
    fireEvent.submit(screen.getByRole("form", { name: "Invite report administrator" }));
    expect(await screen.findByText(/Inbox delivery is not confirmed/)).toBeVisible();
    const calls = fetcher.mock.calls.filter(([url]) => String(url).endsWith("/admins/invitations"));
    expect(calls).toHaveLength(1);
    const init = calls[0][1] as RequestInit;
    expect(init.headers).toHaveProperty("X-Console-CSRF-Token", "page-console-proof");
    expect(JSON.parse(String(init.body))).toEqual({ email: "invitee@example.invalid", full_name: "Invitee" });
  });
});
