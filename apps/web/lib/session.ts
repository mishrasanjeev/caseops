"use client";

import type { AuthSession } from "@/lib/api/schemas";

// EG-001 (2026-04-23): the access token is now an HttpOnly cookie
// the browser handles for us — JavaScript can no longer read or
// store it. We keep ONLY the non-sensitive context (workspace +
// user + role profile) in localStorage, exclusively to hydrate the
// UI shell on first paint without an extra /api/auth/me round-trip.
//
// ``TOKEN_KEY`` is preserved as a constant only so a one-shot
// migration can wipe the legacy entry from any browser that still
// has it. The cookie cutover deliberately logs the user out — the
// next sign-in writes nothing token-shaped to localStorage at all.
const LEGACY_TOKEN_KEY = "caseops.session.token";
const CONTEXT_KEY = "caseops.session.context";
const EVENT_NAME = "caseops:session-change";

type StoredContext = {
  company: AuthSession["company"];
  user: AuthSession["user"];
  membership: AuthSession["membership"];
};

function hasStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

/**
 * Legacy-compat: still exported because a few call sites import it.
 * Always returns null in the cookie era — the browser holds the
 * session token in an HttpOnly cookie that JS cannot read. Bearer
 * callers (tests, SDKs) must pass ``token`` explicitly to ``apiRequest``.
 */
export function getStoredToken(): string | null {
  return null;
}

export function getStoredContext(): StoredContext | null {
  if (!hasStorage()) return null;
  try {
    const raw = window.localStorage.getItem(CONTEXT_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredContext;
  } catch {
    return null;
  }
}

export function storeSession(session: AuthSession): void {
  if (!hasStorage()) return;
  const context: StoredContext = {
    company: session.company,
    user: session.user,
    membership: session.membership,
  };
  try {
    // EG-001: do NOT store the access token. The cookie set by the
    // server response is the authoritative session credential. Wipe
    // the legacy entry on every login so any browser that updated
    // mid-session no longer holds a stale token in localStorage.
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
    window.localStorage.setItem(CONTEXT_KEY, JSON.stringify(context));
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Ignore storage errors — the caller will treat the session as unset.
  }
}

export function clearSession(): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
    window.localStorage.removeItem(CONTEXT_KEY);
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Silent clear.
  }
}

export function subscribeSession(handler: () => void): () => void {
  if (!hasStorage()) return () => undefined;
  const onChange = () => handler();
  window.addEventListener(EVENT_NAME, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT_NAME, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export type { StoredContext };
