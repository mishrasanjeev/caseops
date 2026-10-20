"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { PLATFORM_SESSION_INVALIDATED, ConsoleError, advancePlatformSessionEpoch, consoleErrorMessage, platformApi } from "./client";
import type { ConsoleAuth } from "./schemas";

type SafeAuth = Omit<ConsoleAuth, "recovery_codes">;
type State = { status: "loading" | "ready" | "anonymous" | "error"; auth: SafeAuth | null; error: string | null };
type Context = State & { accept: (auth: ConsoleAuth) => void; refresh: () => Promise<void>; signOut: () => Promise<void> };
const Session = createContext<Context | null>(null);

export function PlatformSessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading", auth: null, error: null });
  const requestId = useRef(0);
  const accept = useCallback((auth: ConsoleAuth) => {
    advancePlatformSessionEpoch();
    requestId.current += 1;
    setState({ status: "ready", auth: { state: auth.state, admin: auth.admin, expires_at: auth.expires_at }, error: null });
  }, []);
  const clear = useCallback(() => {
    advancePlatformSessionEpoch();
    requestId.current += 1;
    setState({ status: "anonymous", auth: null, error: null });
  }, []);
  const refresh = useCallback(async () => {
    const current = ++requestId.current;
    try {
      const auth = await platformApi.session();
      if (current === requestId.current) accept(auth);
    } catch (error) {
      if (current !== requestId.current) return;
      if (error instanceof ConsoleError && error.status === 401) clear();
      else setState({ status: "error", auth: null, error: consoleErrorMessage(error) });
    }
  }, [accept, clear]);
  useEffect(() => {
    void refresh();
    window.addEventListener(PLATFORM_SESSION_INVALIDATED, clear);
    return () => { requestId.current += 1; window.removeEventListener(PLATFORM_SESSION_INVALIDATED, clear); };
  }, [refresh, clear]);
  useEffect(() => {
    if (!state.auth) return;
    const remaining = Date.parse(state.auth.expires_at) - Date.now();
    if (remaining <= 0) { clear(); return; }
    const timer = window.setTimeout(clear, Math.min(remaining, 2_147_483_647));
    return () => window.clearTimeout(timer);
  }, [state.auth, clear]);
  const signOut = useCallback(async () => {
    try { await platformApi.logout(); } finally { clear(); }
  }, [clear]);
  return <Session.Provider value={{ ...state, accept, refresh, signOut }}>{children}</Session.Provider>;
}

export function usePlatformSession() {
  const value = useContext(Session);
  if (!value) throw new Error("Platform session provider is required.");
  return value;
}
