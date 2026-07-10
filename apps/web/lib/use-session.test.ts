import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api/config";
import { storeSession } from "./session";
import { useSession } from "./use-session";

const { apiRequestMock, refreshAccessToken } = vi.hoisted(() => ({
  apiRequestMock: vi.fn(),
  refreshAccessToken: vi.fn(() => Promise.resolve("new-token")),
}));

vi.mock("./api/client", () => ({
  apiRequest: apiRequestMock,
  refreshAccessToken: () => refreshAccessToken(),
}));

function buildSession() {
  return {
    access_token: "test-token",
    token_type: "bearer" as const,
    company: {
      id: "00000000-0000-0000-0000-000000000001",
      slug: "test-co",
      name: "Test Co",
      company_type: "law_firm" as const,
      tenant_key: "tenant-test-co",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
    },
    user: {
      id: "00000000-0000-0000-0000-000000000002",
      email: "test@test-co.in",
      full_name: "Test User",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
    },
    membership: {
      id: "00000000-0000-0000-0000-000000000003",
      role: "admin" as const,
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
    },
    mfa_required: false,
    mfa_challenge_required: false,
    mfa_enrollment_required: false,
    mfa_challenge_reason: null,
  };
}

describe("useSession", () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiRequestMock.mockReset();
    apiRequestMock.mockResolvedValue(undefined);
    refreshAccessToken.mockClear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("starts in anonymous status when storage is empty", () => {
    const { result } = renderHook(() => useSession());
    expect(result.current.status).toBe("anonymous");
    expect(result.current.token).toBeNull();
    expect(result.current.context).toBeNull();
  });

  it("reports authenticated when a session is stored before mount", () => {
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());

    expect(result.current.status).toBe("authenticated");
    // EG-001 (2026-04-23): the access token now lives in an HttpOnly
    // cookie that JS cannot read. ``state.token`` is always null in
    // the cookie era; auth status is derived from stored context.
    expect(result.current.token).toBeNull();
    expect(result.current.context?.company.slug).toBe("test-co");
    expect(result.current.context?.user.email).toBe("test@test-co.in");
  });

  it("transitions to authenticated when storeSession fires mid-lifecycle", () => {
    const { result } = renderHook(() => useSession());
    expect(result.current.status).toBe("anonymous");

    act(() => {
      storeSession(buildSession());
    });

    expect(result.current.status).toBe("authenticated");
    // EG-001 (2026-04-23): the access token now lives in an HttpOnly
    // cookie that JS cannot read. ``state.token`` is always null in
    // the cookie era; auth status is derived from stored context.
    expect(result.current.token).toBeNull();
  });

  it("signOut uses the shared API client, then clears local state", async () => {
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());
    expect(result.current.status).toBe("authenticated");

    await act(async () => {
      await result.current.signOut();
    });

    expect(apiRequestMock).toHaveBeenCalledWith("/api/auth/logout", {
      method: "POST",
    });
    expect(result.current.status).toBe("anonymous");
    expect(window.localStorage.getItem("caseops.session.token")).toBeNull();
    expect(window.localStorage.getItem("caseops.session.context")).toBeNull();
  });

  it("propagates a rejected logout while still clearing local state", async () => {
    apiRequestMock.mockRejectedValue(
      new ApiError(403, "CSRF token did not match.", null, "csrf_failed"),
    );
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());
    let logoutError: unknown;

    await act(async () => {
      try {
        await result.current.signOut();
      } catch (error) {
        logoutError = error;
      }
    });

    expect(logoutError).toMatchObject({
      status: 403,
      detail: "CSRF token did not match.",
      problemType: "csrf_failed",
    });
    expect(result.current.status).toBe("anonymous");
    expect(window.localStorage.getItem("caseops.session.context")).toBeNull();
  });

  it("schedules a 45-minute refresh while authenticated", () => {
    storeSession(buildSession());
    renderHook(() => useSession());

    // No refresh until the interval fires.
    expect(refreshAccessToken).not.toHaveBeenCalled();

    // Advance past the 45-min cadence — the interval should fire once.
    act(() => {
      vi.advanceTimersByTime(45 * 60 * 1000 + 50);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);

    // And again after another 45 minutes — the interval keeps firing.
    act(() => {
      vi.advanceTimersByTime(45 * 60 * 1000 + 50);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(2);
  });

  it("does not schedule a refresh while anonymous", () => {
    renderHook(() => useSession());
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 60 * 1000);
    });
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("cancels the refresh interval after signOut", async () => {
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());

    act(() => {
      vi.advanceTimersByTime(45 * 60 * 1000 + 50);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.signOut();
    });

    // After sign-out, no further refresh should fire even if hours pass.
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 60 * 1000);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
  });
});
