"use client";

import type { AuthSession } from "@/lib/api/schemas";

const TOKEN_KEY = "caseops.session.token";
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

export function getStoredToken(): string | null {
  if (!hasStorage()) return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
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
    window.localStorage.setItem(TOKEN_KEY, session.access_token);
    window.localStorage.setItem(CONTEXT_KEY, JSON.stringify(context));
    window.dispatchEvent(new Event(EVENT_NAME));
  } catch {
    // Ignore storage errors — the caller will treat the session as unset.
  }
}

export function clearSession(): void {
  if (!hasStorage()) return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
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
