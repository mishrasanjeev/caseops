import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearSession,
  getStoredContext,
  getStoredToken,
  storeSession,
  subscribeSession,
} from "./session";
import type { AuthSession } from "./api/schemas";

const TOKEN_KEY = "caseops.session.token";
const CONTEXT_KEY = "caseops.session.context";

function buildSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    access_token: "test-token",
    token_type: "bearer",
    company: {
      id: "00000000-0000-0000-0000-000000000001",
      slug: "test-co",
      name: "Test Co",
      company_type: "law_firm",
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
      role: "admin",
      is_active: true,
      created_at: "2026-04-01T00:00:00Z",
    },
    ...overrides,
  };
}

describe("session storage helpers", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("returns null for token and context when storage is empty", () => {
    // EG-001: getStoredToken always returns null in the cookie era.
    expect(getStoredToken()).toBeNull();
    expect(getStoredContext()).toBeNull();
  });

  it("stores ONLY structured context (never the access token)", () => {
    // EG-001 (2026-04-23): the access token now lives in an HttpOnly
    // cookie. The previous implementation wrote it to localStorage,
    // which an XSS could read. The current contract: storeSession
    // stores ONLY the non-sensitive workspace/user/membership context
    // for UI hydration; nothing token-shaped is written.
    const session = buildSession();
    storeSession(session);

    // Token MUST NOT be in localStorage — that's the whole point of
    // the EG-001 migration.
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
    const raw = window.localStorage.getItem(CONTEXT_KEY);
    expect(raw).not.toBeNull();

    const parsed = JSON.parse(raw!);
    expect(parsed.company.slug).toBe("test-co");
    expect(parsed.user.email).toBe("test@test-co.in");
    expect(parsed.membership.role).toBe("admin");
    // Must not leak the access token into the context blob.
    expect(raw).not.toContain("test-token");
  });

  it("getStoredToken always returns null in the cookie era", () => {
    // Even after storeSession, JS cannot read the session credential —
    // it sits behind HttpOnly. Bearer-token callers (tests, SDKs)
    // must pass token explicitly to apiRequest; the browser path
    // relies on credentials: 'include'.
    storeSession(buildSession());
    expect(getStoredToken()).toBeNull();
    const ctx = getStoredContext();
    expect(ctx?.company.slug).toBe("test-co");
    expect(ctx?.user.full_name).toBe("Test User");
  });

  it("storeSession wipes any legacy localStorage token left over from the pre-cookie era", () => {
    // A user mid-session at the time of the cookie cutover may still
    // have caseops.session.token in localStorage from the previous
    // bundle. Each storeSession call must clean that up so the
    // legacy entry never lingers.
    window.localStorage.setItem(TOKEN_KEY, "stale-pre-cookie-token");
    storeSession(buildSession());
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("returns null on malformed JSON context rather than throwing", () => {
    window.localStorage.setItem(CONTEXT_KEY, "{not-json");
    expect(getStoredContext()).toBeNull();
  });

  it("clearSession wipes the context and any legacy token entry", () => {
    storeSession(buildSession());
    // Simulate a legacy token entry left over from the pre-cookie era.
    window.localStorage.setItem(TOKEN_KEY, "legacy-token-from-old-bundle");
    clearSession();
    expect(getStoredToken()).toBeNull();
    expect(getStoredContext()).toBeNull();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem(CONTEXT_KEY)).toBeNull();
  });

  it("dispatches caseops:session-change on store and clear", () => {
    const handler = vi.fn();
    window.addEventListener("caseops:session-change", handler);

    storeSession(buildSession());
    expect(handler).toHaveBeenCalledTimes(1);

    clearSession();
    expect(handler).toHaveBeenCalledTimes(2);

    window.removeEventListener("caseops:session-change", handler);
  });
});

describe("subscribeSession", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("invokes the handler on custom session-change events", () => {
    const handler = vi.fn();
    const unsub = subscribeSession(handler);

    storeSession(buildSession());
    expect(handler).toHaveBeenCalledTimes(1);

    unsub();
    clearSession();
    // After unsubscribe the handler must not be called again.
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("also reacts to cross-tab storage events (localStorage sync)", () => {
    const handler = vi.fn();
    const unsub = subscribeSession(handler);

    // The browser fires a "storage" event when another tab mutates
    // localStorage. Simulate that so we know cross-tab logout works.
    window.dispatchEvent(new StorageEvent("storage", { key: TOKEN_KEY }));
    expect(handler).toHaveBeenCalledTimes(1);

    unsub();
  });
});
