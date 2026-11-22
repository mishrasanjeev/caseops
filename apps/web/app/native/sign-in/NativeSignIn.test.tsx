import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NativeSignIn } from "./NativeSignIn";
import type { ComponentProps } from "react";

const mocks = vi.hoisted(() => ({
  query: "",
  api: vi.fn(),
  mfa: vi.fn(),
  open: vi.fn(),
  connectCallbacks: [] as Array<() => void>,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.api }));
vi.mock("@/lib/api/auth", () => ({ completeMfaLoginChallenge: mocks.mfa }));
vi.mock("@/lib/native-authorization", async (original) => ({
  ...(await original<typeof import("@/lib/native-authorization")>()),
  openNativeApp: mocks.open,
}));
// Retain the actual page callback while rendering the original Button. A
// detached React DOM button would not dispatch its old synthetic handler.
vi.mock("@/components/ui/Button", async (original) => {
  const actual = await original<typeof import("@/components/ui/Button")>();
  const { createElement } = await import("react");
  return { ...actual, Button(props: ComponentProps<typeof actual.Button>) {
    const children = Array.isArray(props.children) ? props.children : [props.children];
    if (children.includes("Connect app") && props.onClick)
      mocks.connectCallbacks.push(props.onClick as () => void);
    return createElement(actual.Button, props);
  } };
});
vi.mock("@/components/marketing/Logo", () => ({
  Logo: () => <span>CaseOps</span>,
}));
const LOCAL_POLICY = { mode: "local", redirectUri: "caseops://oauth/callback" } as const;
const HTTPS_POLICY = { mode: "https", redirectUri: "https://native.invalid/native/oauth/callback", configSha256: "a".repeat(64) } as const;
const identity = {
  user: {
    id: "person-one",
    full_name: "Example Person",
    email: "person@example.test",
  },
  company: { id: "company-one", name: "Example Legal", slug: "fixture-legal" },
  membership: { id: "membership-one" },
  capabilities: [],
};
const query = new URLSearchParams({
  code_challenge: "a".repeat(43),
  state: "b".repeat(64),
  platform: "ios",
  redirect_uri: "caseops://oauth/callback",
}).toString();

describe("native browser handoff consent", () => {
  beforeEach(() => {
    mocks.query = query;
    mocks.api.mockReset();
    mocks.mfa.mockReset();
    mocks.open.mockReset();
    mocks.connectCallbacks.length = 0;
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("focuses the initial verified consent control without submitting authorization", async () => {
    mocks.api.mockResolvedValueOnce(identity);
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    const connect = await screen.findByRole("button", { name: "Connect app" });
    expect(connect).toHaveFocus();
    expect(connect).toBeEnabled();
    expect(screen.getByText(identity.user.email)).toBeVisible();
    expect(mocks.api.mock.calls.map(([route]) => route)).toEqual(["/api/auth/me"]);
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("does not focus or display a late identity from an earlier authorization request", async () => {
    let finish!: (value: unknown) => void;
    mocks.api
      .mockImplementationOnce(() => new Promise((done) => { finish = done; }))
      .mockRejectedValueOnce({ name: "ApiError", status: 401, problemType: "unauthorized", detail: "Sign in.", data: null });
    const view = render(<NativeSignIn policy={LOCAL_POLICY} />);
    mocks.query = new URLSearchParams({ code_challenge: "c".repeat(43), state: "d".repeat(64), platform: "android", redirect_uri: "caseops://oauth/callback" }).toString();
    view.rerender(<NativeSignIn policy={LOCAL_POLICY} />);
    const signIn = await screen.findByRole("link", { name: "Sign in securely" });
    signIn.focus();
    await act(async () => { finish(identity); });
    expect(signIn).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Connect app" })).not.toBeInTheDocument();
    expect(screen.queryByText(identity.user.email)).not.toBeInTheDocument();
    expect(mocks.api.mock.calls.map(([route]) => route)).toEqual(["/api/auth/me", "/api/auth/me"]);
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("waits for an explicit app-opening gesture after one acknowledged grant", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 60,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const open = await screen.findByRole("button", { name: "Open CaseOps" });
    expect(open).toHaveAccessibleDescription(
      "Sign-in is ready. Open CaseOps to finish.",
    );
    expect(mocks.open).not.toHaveBeenCalled();
    expect(document.querySelector('a[href^="caseops:"]')).toBeNull();
    expect(document.body.innerHTML).not.toContain("c".repeat(43));
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
    expect(
      mocks.api.mock.calls.filter(
        ([route]) => route === "/api/auth/native/authorize",
      ),
    ).toHaveLength(1);
    fireEvent.click(open);
    fireEvent.click(open);
    expect(mocks.open).toHaveBeenCalledExactlyOnceWith(
      `caseops://oauth/callback?code=${"c".repeat(43)}&state=${"b".repeat(64)}`,
      LOCAL_POLICY,
    );
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });

  it.each([undefined, 0, 14, 121, 60.5, "60"])(
    "rejects an absent or invalid server handoff lifetime: %s",
    async (expires_in) => {
      mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
        code: "c".repeat(43),
        state: "b".repeat(64),
        redirect_uri: "caseops://oauth/callback",
        expires_in,
      });
      render(<NativeSignIn policy={LOCAL_POLICY} />);
      fireEvent.click(
        await screen.findByRole("button", { name: "Connect app" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "could not be completed",
      );
      expect(
        screen.queryByRole("button", { name: "Open CaseOps" }),
      ).not.toBeInTheDocument();
      expect(mocks.open).not.toHaveBeenCalled();
    },
  );

  it("expires the held handoff without replaying its grant or launching the app", async () => {
    vi.useFakeTimers();
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 15,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect app" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("button", { name: "Open CaseOps" })).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });

  it("charges response latency against the server lifetime and rejects an already expired grant", async () => {
    vi.useFakeTimers();
    let finish: (value: unknown) => void = () => {};
    mocks.api.mockResolvedValueOnce(identity).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect app" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    await act(async () => {
      finish({
        code: "c".repeat(43),
        state: "b".repeat(64),
        redirect_uri: "caseops://oauth/callback",
        expires_in: 15,
      });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("ignores a late grant after the authorization query changes", async () => {
    let finish: (value: unknown) => void = () => {};
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(identity);
    const view = render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    mocks.query = query.replace(
      "state=" + "b".repeat(64),
      "state=" + "d".repeat(64),
    );
    view.rerender(<NativeSignIn policy={LOCAL_POLICY} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Connect app" })).toBeEnabled(),
    );
    await act(async () => {
      finish({
        code: "c".repeat(43),
        state: "b".repeat(64),
        redirect_uri: "caseops://oauth/callback",
        expires_in: 60,
      });
    });
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("clears an already prepared handoff immediately when the query changes", async () => {
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockResolvedValueOnce({
        code: "c".repeat(43),
        state: "b".repeat(64),
        redirect_uri: "caseops://oauth/callback",
        expires_in: 60,
      })
      .mockResolvedValue(identity);
    const view = render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    await screen.findByRole("button", { name: "Open CaseOps" });
    mocks.query = query.replace(
      "state=" + "b".repeat(64),
      "state=" + "d".repeat(64),
    );
    view.rerender(<NativeSignIn policy={LOCAL_POLICY} />);
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    await screen.findByRole("button", { name: "Connect app" });
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("clears the held callback when the browser becomes hidden", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 60,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    await screen.findByRole("button", { name: "Open CaseOps" });
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    fireEvent(document, new Event("visibilitychange"));
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("clears the grant timer on unmount without browser persistence", async () => {
    vi.useFakeTimers();
    const store = vi.spyOn(Storage.prototype, "setItem");
    const timers = vi.spyOn(globalThis, "setTimeout");
    const clears = vi.spyOn(globalThis, "clearTimeout");
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 60,
    });
    const view = render(<NativeSignIn policy={LOCAL_POLICY} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect app" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("button", { name: "Open CaseOps" })).toBeVisible();
    const expiryTimers = timers.mock.calls.flatMap((call, index) =>
      typeof call[1] === "number" && call[1] > 59_990 && call[1] <= 60_000
        ? [timers.mock.results[index].value]
        : [],
    );
    expect(expiryTimers).toHaveLength(1);
    view.unmount();
    expect(clears).toHaveBeenCalledWith(expiryTimers[0]);
    expect(store).not.toHaveBeenCalled();
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("discards a prepared handoff on pagehide and does not restore its secret on return", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 60,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    await screen.findByRole("button", { name: "Open CaseOps" });
    fireEvent(window, new Event("pagehide"));
    expect(
      screen.queryByRole("button", { name: "Open CaseOps" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
    expect(
      screen.queryByText("Sign-in is ready. Open CaseOps to finish."),
    ).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });

  it("verifies MFA and prepares one native handoff within the explicit continue action", async () => {
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required",
        detail: "Complete MFA in this browser session before native sign-in.", data: null })
      .mockResolvedValueOnce(identity)
      .mockResolvedValueOnce({ code: "c".repeat(43), state: "b".repeat(64),
        redirect_uri: "caseops://oauth/callback", expires_in: 60 });
    mocks.mfa.mockResolvedValue({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const field = await screen.findByLabelText("Six-digit code");
    await waitFor(() => { expect(field).toBeEnabled(); expect(field).toHaveFocus(); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Enter the six-digit code from your authenticator. Verify and continue connects this account to CaseOps.");
    expect(screen.queryByRole("button", { name: "Connect app" })).not.toBeInTheDocument();
    fireEvent.change(field, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    const open = await screen.findByRole("button", { name: "Open CaseOps" });
    await waitFor(() => { expect(open).toBeEnabled(); expect(open).toHaveFocus(); });
    expect(mocks.mfa).toHaveBeenCalledExactlyOnceWith({ code: "123456" });
    expect(mocks.api.mock.calls.map((call) => call[0])).toEqual([
      "/api/auth/me", "/api/auth/native/authorize", "/api/auth/me", "/api/auth/native/authorize",
    ]);
    expect(open).toHaveAccessibleDescription("Sign-in is ready. Open CaseOps to finish.");
    expect(mocks.open).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Connect app" })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("c".repeat(43));
  });

  it("holds one synchronous verification lease through identity and authorization completion", async () => {
    let finishMfa!: (value: unknown) => void, finishIdentity!: (value: unknown) => void,
      finishGrant!: (value: unknown) => void;
    mocks.api.mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required", detail: "Verify.", data: null })
      .mockImplementationOnce(() => new Promise(resolve => { finishIdentity = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { finishGrant = resolve; }));
    mocks.mfa.mockImplementationOnce(() => new Promise(resolve => { finishMfa = resolve; }));
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const field = await screen.findByLabelText("Six-digit code");
    fireEvent.change(field, { target: { value: "123456" } });
    const verify = screen.getByRole("button", { name: "Verify and continue" });
    act(() => { fireEvent.click(verify); fireEvent.click(verify); });
    expect(mocks.mfa).toHaveBeenCalledTimes(1);
    await act(async () => { finishMfa({ status: "verified", expires_at: "2099-01-01T00:00:00Z" }); });
    expect(verify).toBeDisabled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
    await act(async () => { finishIdentity(identity); });
    expect(verify).toBeDisabled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(2);
    fireEvent.click(verify);
    expect(mocks.mfa).toHaveBeenCalledTimes(1);
    await act(async () => { finishGrant({ code: "c".repeat(43), state: "b".repeat(64), redirect_uri: "caseops://oauth/callback", expires_in: 60 }); });
    expect(await screen.findByRole("button", { name: "Open CaseOps" })).toBeEnabled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(2);
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("keeps retained Connect blocked after MFA succeeds but the fresh identity read fails", async () => {
    mocks.api.mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required", detail: "Verify.", data: null })
      .mockRejectedValueOnce(new Error("Synthetic identity read unavailable"))
      .mockResolvedValue({ code: "c".repeat(43), state: "b".repeat(64), redirect_uri: "caseops://oauth/callback", expires_in: 60 });
    mocks.mfa.mockResolvedValue({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    await screen.findByRole("button", { name: "Connect app" });
    const retainedConnect = mocks.connectCallbacks.at(-1)!;
    await act(async () => { retainedConnect(); });
    fireEvent.change(await screen.findByLabelText("Six-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("security check could not be verified");
    await act(async () => { retainedConnect(); });
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
  });

  it.each(["rejected code", "unknown verification acknowledgement"])("consumes the code before a retained Verify callback can replay after %s", async failure => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required", detail: "Verify.", data: null });
    mocks.mfa.mockRejectedValue(failure === "rejected code"
      ? { name: "ApiError", status: 403, problemType: "forbidden", detail: "The code was not accepted.", data: null }
      : new Error("Synthetic verification acknowledgement unknown"));
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), { target: { value: "123456" } });
    // The form's real submit callback is retained after the code-bearing render.
    const form = screen.getByRole("button", { name: "Verify and continue" }).closest("form")!;
    const reactKey = Object.keys(form).find(key => key.startsWith("__reactProps$"))!;
    const retainedSubmit = (form as unknown as Record<string, { onSubmit: (event: { preventDefault(): void }) => void }>)[reactKey].onSubmit;
    await act(async () => { retainedSubmit({ preventDefault() {} }); });
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByLabelText("Six-digit code")).toHaveValue("");
    await act(async () => { retainedSubmit({ preventDefault() {} }); });
    expect(mocks.mfa).toHaveBeenCalledTimes(1);
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
  });

  it.each(["expired browser session", "changed identity"])("invalidates retained Connect after %s during the fresh MFA identity read", async failure => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required", detail: "Verify.", data: null });
    if (failure === "expired browser session") mocks.api.mockRejectedValueOnce({ name: "ApiError", status: 401, problemType: "invalid_token", detail: "Sign in again.", data: null });
    else mocks.api.mockResolvedValueOnce({ ...identity, user: { ...identity.user, id: "different-person" } });
    mocks.api.mockResolvedValue({ code: "c".repeat(43), state: "b".repeat(64), redirect_uri: "caseops://oauth/callback", expires_in: 60 });
    mocks.mfa.mockResolvedValue({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    await screen.findByRole("button", { name: "Connect app" });
    const retainedConnect = mocks.connectCallbacks.at(-1)!;
    await act(async () => { retainedConnect(); });
    fireEvent.change(await screen.findByLabelText("Six-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("link", { name: "Sign in securely" })).toBeVisible();
    await act(async () => { retainedConnect(); });
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
  });

  it("invalidates a retained initial Connect callback after an unknown grant acknowledgement", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce(new Error("Synthetic grant acknowledgement unknown"));
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    await screen.findByRole("button", { name: "Connect app" });
    const connect = mocks.connectCallbacks.at(-1)!;
    expect(connect).toBeTypeOf("function");
    await act(async () => { connect(); });
    expect(await screen.findByRole("alert")).toHaveTextContent("start sign-in again");
    expect(screen.queryByRole("button", { name: "Connect app" })).not.toBeInTheDocument();
    await act(async () => { connect(); connect(); });
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(mocks.mfa).not.toHaveBeenCalled();
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("does not replay an unknown grant acknowledgement as another verification or authorization", async () => {
    mocks.api.mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({ name: "ApiError", status: 403, problemType: "native_mfa_required", detail: "Verify.", data: null })
      .mockResolvedValueOnce(identity).mockRejectedValueOnce(new Error("Synthetic grant acknowledgement unknown"));
    mocks.mfa.mockResolvedValue({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("start sign-in again");
    expect(screen.queryByLabelText("Six-digit code")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect app" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
    expect(mocks.mfa).toHaveBeenCalledTimes(1);
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(2);
    expect(mocks.open).not.toHaveBeenCalled();
  });

  it("does not mistake an ordinary forbidden response for an MFA challenge", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({
      name: "ApiError",
      status: 403,
      problemType: "native_scope_forbidden",
      detail: "Access denied.",
      data: null,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Access denied");
    expect(screen.queryByLabelText("Six-digit code")).not.toBeInTheDocument();
    expect(mocks.mfa).not.toHaveBeenCalled();
  });

  it("retains the challenge after a rejected code and prevents a double submission", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({
      name: "ApiError",
      status: 403,
      problemType: "native_mfa_required",
      detail: "Verify.",
      data: null,
    });
    let reject!: (error: unknown) => void;
    mocks.mfa.mockImplementation(
      () =>
        new Promise((_done, failed) => {
          reject = failed;
        }),
    );
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    const verify = screen.getByRole("button", { name: "Verify and continue" });
    fireEvent.click(verify);
    fireEvent.click(verify);
    expect(mocks.mfa).toHaveBeenCalledTimes(1);
    reject({
      name: "ApiError",
      status: 400,
      detail: "The code was not accepted.",
      data: null,
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("not accepted");
    expect(screen.getByLabelText("Six-digit code")).toHaveValue("");
    expect(
      mocks.api.mock.calls.filter(
        (call) => call[0] === "/api/auth/native/authorize",
      ),
    ).toHaveLength(1);
  });

  it("ends consent when the browser identity changes during MFA", async () => {
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({
        name: "ApiError",
        status: 403,
        problemType: "native_mfa_required",
        detail: "Verify.",
        data: null,
      })
      .mockResolvedValueOnce({
        ...identity,
        membership: { id: "other-membership" },
      });
    mocks.mfa.mockResolvedValue({
      status: "verified",
      expires_at: "2026-10-25T12:00:00Z",
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "browser account changed",
    );
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "Sign in securely" }),
    ).toBeVisible();
  });

  it("does not adopt a late MFA result after the authorization request changed", async () => {
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({
        name: "ApiError",
        status: 403,
        problemType: "native_mfa_required",
        detail: "Verify.",
        data: null,
      })
      .mockResolvedValueOnce(identity);
    let finish!: (value: unknown) => void;
    mocks.mfa.mockImplementation(
      () =>
        new Promise((done) => {
          finish = done;
        }),
    );
    const view = render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    mocks.query = new URLSearchParams({
      code_challenge: "c".repeat(43),
      state: "d".repeat(64),
      platform: "android",
      redirect_uri: "caseops://oauth/callback",
    }).toString();
    view.rerender(<NativeSignIn policy={LOCAL_POLICY} />);
    expect(
      await screen.findByRole("button", { name: "Connect app" }),
    ).toBeVisible();
    // The new request may focus its own initial consent control. A late MFA
    // result from the old request must still preserve the user's later focus.
    const anotherAccount = screen.getByRole("link", { name: "Use another account" });
    anotherAccount.focus();
    await act(async () => {
      finish({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    });
    await waitFor(() =>
      expect(screen.queryByText("Sign-in is ready. Open CaseOps to finish.")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Connect app" })).not.toHaveFocus();
    expect(anotherAccount).toHaveFocus();
    expect(mocks.api.mock.calls.map((call) => call[0])).toEqual([
      "/api/auth/me",
      "/api/auth/native/authorize",
      "/api/auth/me",
    ]);
  });

  it("removes the old account when the browser session expires during MFA", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({
      name: "ApiError",
      status: 403,
      problemType: "native_mfa_required",
      detail: "Verify.",
      data: null,
    });
    mocks.mfa.mockRejectedValue({
      name: "ApiError",
      status: 401,
      detail: "Sign in again.",
      data: null,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(
      await screen.findByRole("link", { name: "Sign in securely" }),
    ).toBeVisible();
    expect(screen.queryByText("person@example.test")).not.toBeInTheDocument();
    expect(
      mocks.api.mock.calls.filter(
        (call) => call[0] === "/api/auth/native/authorize",
      ),
    ).toHaveLength(1);
  });

  it("rejects malformed input before requesting or exposing the browser identity", async () => {
    mocks.query += "&redirect_uri=https://attacker.test";
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid or incomplete",
    );
    expect(mocks.api).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
  });

  it("names the actual person and workspace and does not authorize on page load", async () => {
    mocks.api.mockResolvedValue(identity);
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    expect(await screen.findByText("person@example.test")).toBeVisible();
    expect(screen.getByText("Example Legal / fixture-legal")).toBeVisible();
    expect(mocks.api.mock.calls.map((call) => call[0])).toEqual([
      "/api/auth/me",
    ]);
    expect(screen.getByRole("button", { name: "Connect app" })).toBeEnabled();
  });

  it("offers the exact safe return path after anonymous browser authentication", async () => {
    mocks.api.mockRejectedValue({
      name: "ApiError",
      status: 401,
      detail: "Sign in.",
      data: null,
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    const link = await screen.findByRole("link", { name: "Sign in securely" });
    expect(link).toHaveAttribute(
      "href",
      `/sign-in?next=${encodeURIComponent(`/native/sign-in?${query}`)}`,
    );
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
  });

  it("does not follow a forged returned redirect and preserves a visible recovery error", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "https://attacker.test",
    });
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be completed",
    );
    expect(
      mocks.api.mock.calls.filter(
        (call) => call[0] === "/api/auth/native/authorize",
      ),
    ).toHaveLength(1);
    expect(mocks.api.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: { state: "b".repeat(64), platform: "ios" },
    });
  });

  it("deduplicates a double-click and renders typed errors without class-identity assumptions", async () => {
    let fail: (error: unknown) => void = () => {};
    mocks.api.mockResolvedValueOnce(identity).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          fail = reject;
        }),
    );
    render(<NativeSignIn policy={LOCAL_POLICY} />);
    const button = await screen.findByRole("button", { name: "Connect app" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(
      mocks.api.mock.calls.filter(
        (call) => call[0] === "/api/auth/native/authorize",
      ),
    ).toHaveLength(1);
    fail({
      name: "ApiError",
      status: 503,
      detail: "Native sign-in is not enabled for this environment.",
      data: null,
    });
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "not enabled for this environment",
      ),
    );
  });

  it("uses the configured HTTPS callback with the same four-field authorize DTO and one explicit opening gesture", async () => {
    mocks.query = new URLSearchParams({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "ios", redirect_uri: HTTPS_POLICY.redirectUri }).toString();
    const code = "r".repeat(43);
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({ code, state: "b".repeat(64), redirect_uri: HTTPS_POLICY.redirectUri, expires_in: 60 });
    render(<NativeSignIn policy={HTTPS_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const open = await screen.findByRole("button", { name: "Open CaseOps" });
    expect(mocks.api.mock.calls[1]).toEqual(["/api/auth/native/authorize", { method: "POST", body: {
      code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "ios", redirect_uri: HTTPS_POLICY.redirectUri,
    } }]);
    expect(mocks.open).not.toHaveBeenCalled();
    expect(document.body.innerHTML).not.toContain(code);
    // The original state remains in the existing same-origin sign-in return
    // link. The newly issued code and grant callback must stay in memory.
    expect(document.body.innerHTML).not.toContain(`${HTTPS_POLICY.redirectUri}?code=`);
    expect(document.querySelector(`a[href^="${HTTPS_POLICY.redirectUri}"]`)).toBeNull();
    fireEvent.click(open); fireEvent.click(open);
    expect(mocks.open).toHaveBeenCalledExactlyOnceWith(`${HTTPS_POLICY.redirectUri}?code=${code}&state=${"b".repeat(64)}`, HTTPS_POLICY);
    expect(mocks.api).toHaveBeenCalledTimes(2);
  });

  it.each([undefined, { mode: "disabled" } as const])("does not request or expose browser identity when native policy is absent or disabled %#", async (policy) => {
    mocks.api.mockResolvedValue(identity);
    render(<NativeSignIn policy={policy} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or incomplete");
    expect(mocks.api).not.toHaveBeenCalled(); expect(mocks.open).not.toHaveBeenCalled();
    expect(screen.queryByText(identity.user.email)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in securely" })).not.toBeInTheDocument();
  });

  it("refuses a custom-scheme request under HTTPS policy before session or grant reads", async () => {
    mocks.api.mockResolvedValue(identity);
    render(<NativeSignIn policy={HTTPS_POLICY} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or incomplete");
    expect(mocks.api).not.toHaveBeenCalled(); expect(mocks.open).not.toHaveBeenCalled();
  });

  it("never converts a drifted HTTPS grant into a local callback or reflects the short-lived code", async () => {
    mocks.query = new URLSearchParams({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "android", redirect_uri: HTTPS_POLICY.redirectUri }).toString();
    const code = "q".repeat(43);
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({ code, state: "b".repeat(64), redirect_uri: LOCAL_POLICY.redirectUri, expires_in: 60 });
    render(<NativeSignIn policy={HTTPS_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be completed");
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(code); expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
  });

  it("discards a prepared HTTPS grant when the exact configuration hash changes even if the query and redirect stay the same", async () => {
    mocks.query = new URLSearchParams({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "ios", redirect_uri: HTTPS_POLICY.redirectUri }).toString();
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({ code: "c".repeat(43), state: "b".repeat(64), redirect_uri: HTTPS_POLICY.redirectUri, expires_in: 60 }).mockResolvedValue(identity);
    const view = render(<NativeSignIn policy={HTTPS_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    await screen.findByRole("button", { name: "Open CaseOps" });
    view.rerender(<NativeSignIn policy={{ ...HTTPS_POLICY, configSha256: "d".repeat(64) }} />);
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Connect app" })).toBeEnabled();
    expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/me")).toHaveLength(2);
  });

  it("does not adopt an in-flight grant from an earlier configuration hash after the policy changes", async () => {
    mocks.query = new URLSearchParams({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "ios", redirect_uri: HTTPS_POLICY.redirectUri }).toString();
    let finish!: (value: unknown) => void;
    mocks.api.mockResolvedValueOnce(identity).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValue(identity);
    const view = render(<NativeSignIn policy={HTTPS_POLICY} />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    view.rerender(<NativeSignIn policy={{ ...HTTPS_POLICY, configSha256: "e".repeat(64) }} />);
    await screen.findByRole("button", { name: "Connect app" });
    await act(async () => finish({ code: "s".repeat(43), state: "b".repeat(64), redirect_uri: HTTPS_POLICY.redirectUri, expires_in: 60 }));
    expect(screen.queryByRole("button", { name: "Open CaseOps" })).not.toBeInTheDocument();
    expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.api.mock.calls.filter(([route]) => route === "/api/auth/native/authorize")).toHaveLength(1);
  });

  it("keeps the anonymous HTTPS sign-in return path exact without leaking policy metadata into it", async () => {
    mocks.query = new URLSearchParams({ code_challenge: "a".repeat(43), state: "b".repeat(64), platform: "android", redirect_uri: HTTPS_POLICY.redirectUri }).toString();
    mocks.api.mockRejectedValue({ name: "ApiError", status: 401, detail: "Sign in.", data: null });
    render(<NativeSignIn policy={HTTPS_POLICY} />);
    const link = await screen.findByRole("link", { name: "Sign in securely" });
    expect(link).toHaveAttribute("href", `/sign-in?next=${encodeURIComponent(`/native/sign-in?${mocks.query}`)}`);
    expect(link.getAttribute("href")).not.toContain(HTTPS_POLICY.configSha256);
    expect(mocks.api.mock.calls.map(([route]) => route)).toEqual(["/api/auth/me"]);
    expect(mocks.open).not.toHaveBeenCalled();
  });

});
