import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformGate } from "./PlatformGate";

const session = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("@/lib/platform/session", () => ({ usePlatformSession: () => session.current }));

describe("platform view authorization", () => {
  beforeEach(() => { session.current = { status: "anonymous", auth: null, error: null, refresh: vi.fn() }; });
  it("does not mount report content for anonymous access", () => {
    render(<PlatformGate><p>Private account data</p></PlatformGate>);
    expect(screen.queryByText("Private account data")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in to platform reports" })).toHaveAttribute("href", "/platform/sign-in");
  });
  it.each(["mfa_enrollment_required", "mfa_challenge_required"])("does not mount report content before %s", (state) => {
    session.current = { status: "ready", auth: { state, admin: null }, error: null };
    render(<PlatformGate><p>Private account data</p></PlatformGate>);
    expect(screen.queryByText("Private account data")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Complete multi-factor/ })).toBeVisible();
  });
  it("allows report reading but denies administrator management to a viewer", () => {
    session.current = { status: "ready", auth: { state: "authenticated", admin: { id: "viewer", role: "viewer" }, expires_at: "2099-01-01T00:00:00Z" } };
    const view = render(<PlatformGate><p>Private account data</p></PlatformGate>);
    expect(screen.getByText("Private account data")).toBeVisible();
    view.rerender(<PlatformGate managerOnly><p>Manage administrators</p></PlatformGate>);
    expect(screen.queryByText("Manage administrators")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("manager access");
  });
});
