import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NativeSignIn } from "./NativeSignIn";

const mocks = vi.hoisted(() => ({
  query: "",
  api: vi.fn(),
  mfa: vi.fn(),
  open: vi.fn(),
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
vi.mock("@/components/marketing/Logo", () => ({
  Logo: () => <span>CaseOps</span>,
}));
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
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("waits for an explicit app-opening gesture after one acknowledged grant", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockResolvedValueOnce({
      code: "c".repeat(43),
      state: "b".repeat(64),
      redirect_uri: "caseops://oauth/callback",
      expires_in: 60,
    });
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const open = await screen.findByRole("button", { name: "Open CaseOps" });
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
      render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    const view = render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    mocks.query = query.replace(
      "state=" + "b".repeat(64),
      "state=" + "d".repeat(64),
    );
    view.rerender(<NativeSignIn />);
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
    const view = render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    await screen.findByRole("button", { name: "Open CaseOps" });
    mocks.query = query.replace(
      "state=" + "b".repeat(64),
      "state=" + "d".repeat(64),
    );
    view.rerender(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    const view = render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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

  it("recovers a typed native MFA refusal with the existing verifier and never reconnects automatically", async () => {
    mocks.api
      .mockResolvedValueOnce(identity)
      .mockRejectedValueOnce({
        name: "ApiError",
        status: 403,
        problemType: "native_mfa_required",
        detail: "Verify your authenticator.",
        data: null,
      })
      .mockResolvedValueOnce(identity);
    mocks.mfa.mockResolvedValue({
      status: "verified",
      expires_at: "2026-10-25T12:00:00Z",
    });
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    const field = await screen.findByLabelText("Six-digit code");
    expect(
      screen.queryByRole("button", { name: "Connect app" }),
    ).not.toBeInTheDocument();
    fireEvent.change(field, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Code verified",
    );
    expect(mocks.mfa).toHaveBeenCalledExactlyOnceWith({ code: "123456" });
    expect(mocks.api.mock.calls.map((call) => call[0])).toEqual([
      "/api/auth/me",
      "/api/auth/native/authorize",
      "/api/auth/me",
    ]);
    expect(screen.getByRole("button", { name: "Connect app" })).toBeEnabled();
  });

  it("does not mistake an ordinary forbidden response for an MFA challenge", async () => {
    mocks.api.mockResolvedValueOnce(identity).mockRejectedValueOnce({
      name: "ApiError",
      status: 403,
      problemType: "native_scope_forbidden",
      detail: "Access denied.",
      data: null,
    });
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    const verify = screen.getByRole("button", { name: "Verify code" });
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
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
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
    const view = render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
    mocks.query = new URLSearchParams({
      code_challenge: "c".repeat(43),
      state: "d".repeat(64),
      platform: "android",
      redirect_uri: "caseops://oauth/callback",
    }).toString();
    view.rerender(<NativeSignIn />);
    expect(
      await screen.findByRole("button", { name: "Connect app" }),
    ).toBeVisible();
    finish({ status: "verified", expires_at: "2099-01-01T00:00:00Z" });
    await waitFor(() =>
      expect(screen.queryByText(/Code verified/)).not.toBeInTheDocument(),
    );
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
    render(<NativeSignIn />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect app" }));
    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Verify code" }));
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
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
    render(<NativeSignIn />);
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
});
