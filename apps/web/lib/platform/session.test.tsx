import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleError, PLATFORM_SESSION_INVALIDATED, platformApi } from "./client";
import { PlatformSessionProvider, usePlatformSession } from "./session";

vi.mock("./client", async (load) => {
  const actual = await load<typeof import("./client")>();
  return { ...actual, platformApi: { session: vi.fn(), logout: vi.fn() } };
});
const auth = { state: "authenticated" as const, admin: { id: "viewer", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" as const }, expires_at: "2099-01-01T00:00:00Z", recovery_codes: ["TEST-RECOVERY-CODE"] };
function Consumer() {
  const session = usePlatformSession();
  return <><output aria-label="Session">{JSON.stringify({ status: session.status, auth: session.auth })}</output>
    <button onClick={() => session.accept(auth)}>Accept login</button>
    <button onClick={() => void session.signOut().catch(() => undefined)}>Sign out</button></>;
}
describe("independent platform session lifecycle", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.useRealTimers(); });
  it("keeps recovery codes out of shared session state and clears on realm invalidation", async () => {
    vi.mocked(platformApi.session).mockResolvedValue(auth);
    render(<PlatformSessionProvider><Consumer /></PlatformSessionProvider>);
    expect(await screen.findByText(/viewer@example.invalid/)).not.toHaveTextContent("TEST-RECOVERY-CODE");
    act(() => window.dispatchEvent(new Event(PLATFORM_SESSION_INVALIDATED)));
    expect(screen.getByLabelText("Session")).toHaveTextContent('"status":"anonymous","auth":null');
  });
  it("cannot overwrite a newer login with a stale session read", async () => {
    let resolve!: (value: typeof auth) => void;
    vi.mocked(platformApi.session).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<PlatformSessionProvider><Consumer /></PlatformSessionProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Accept login" }));
    await act(async () => resolve({ ...auth, admin: { ...auth.admin, id: "stale", email: "stale@example.invalid" } }));
    expect(screen.getByLabelText("Session")).toHaveTextContent("viewer@example.invalid");
    expect(screen.getByLabelText("Session")).not.toHaveTextContent("stale@example.invalid");
  });
  it("releases all cached report identity after local expiry", async () => {
    vi.useFakeTimers();
    vi.mocked(platformApi.session).mockResolvedValue({ ...auth, expires_at: new Date(Date.now() + 1000).toISOString() });
    render(<PlatformSessionProvider><Consumer /></PlatformSessionProvider>);
    await act(async () => {});
    expect(screen.getByLabelText("Session")).toHaveTextContent("viewer@example.invalid");
    await act(async () => vi.advanceTimersByTime(1000));
    expect(screen.getByLabelText("Session")).toHaveTextContent('"status":"anonymous","auth":null');
  });
  it("still clears local identity after an unconfirmed logout without replay", async () => {
    vi.mocked(platformApi.session).mockResolvedValue(auth);
    vi.mocked(platformApi.logout).mockRejectedValue(new ConsoleError(503, "unavailable"));
    render(<PlatformSessionProvider><Consumer /></PlatformSessionProvider>);
    await screen.findByText(/viewer@example.invalid/);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText(/"status":"anonymous"/)).toHaveTextContent('"auth":null');
    expect(platformApi.logout).toHaveBeenCalledTimes(1);
  });
});
