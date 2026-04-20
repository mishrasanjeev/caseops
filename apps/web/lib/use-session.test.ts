import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSession, storeSession } from "./session";
import { useSession } from "./use-session";

const refreshAccessToken = vi.fn(() => Promise.resolve("new-token"));

vi.mock("./api/client", () => ({
  refreshAccessToken: (...args: unknown[]) => refreshAccessToken(...args),
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
  };
}

describe("useSession", () => {
  beforeEach(() => {
    window.localStorage.clear();
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
    expect(result.current.token).toBe("test-token");
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
    expect(result.current.token).toBe("test-token");
  });

  it("signOut clears storage and transitions back to anonymous", () => {
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());
    expect(result.current.status).toBe("authenticated");

    act(() => {
      result.current.signOut();
    });

    expect(result.current.status).toBe("anonymous");
    expect(window.localStorage.getItem("caseops.session.token")).toBeNull();
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

  it("cancels the refresh interval after signOut", () => {
    storeSession(buildSession());
    const { result } = renderHook(() => useSession());

    act(() => {
      vi.advanceTimersByTime(45 * 60 * 1000 + 50);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.signOut();
    });

    // After sign-out, no further refresh should fire even if hours pass.
    act(() => {
      vi.advanceTimersByTime(2 * 60 * 60 * 1000);
    });
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
  });
});
