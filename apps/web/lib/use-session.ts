"use client";

import { useCallback, useEffect, useState } from "react";

import { refreshAccessToken } from "@/lib/api/client";
import {
  type StoredContext,
  clearSession,
  getStoredContext,
  getStoredToken,
  subscribeSession,
} from "@/lib/session";

// Pre-emptive refresh cadence. Access token TTL is 120 min (api settings).
// Refreshing every 45 min keeps the session alive indefinitely while the
// tab is open, and leaves a comfortable margin for clock skew + retries.
const REFRESH_INTERVAL_MS = 45 * 60 * 1000;

export type SessionState = {
  status: "loading" | "authenticated" | "anonymous";
  token: string | null;
  context: StoredContext | null;
};

export function useSession(): SessionState & { signOut: () => void } {
  const [state, setState] = useState<SessionState>({
    status: "loading",
    token: null,
    context: null,
  });

  const read = useCallback(() => {
    const token = getStoredToken();
    const context = getStoredContext();
    setState({
      token,
      context,
      status: token && context ? "authenticated" : "anonymous",
    });
  }, []);

  useEffect(() => {
    read();
    const unsub = subscribeSession(read);
    return unsub;
  }, [read]);

  // Keep the bearer token fresh while the tab is open. Without this the
  // 120-min JWT silently expires mid-session and every subsequent API
  // call returns 401 with no recovery — the exact failure Sanjeev hit
  // in prod on 2026-04-20.
  useEffect(() => {
    if (state.status !== "authenticated") return;
    const id = window.setInterval(() => {
      void refreshAccessToken();
    }, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [state.status]);

  const signOut = useCallback(() => {
    clearSession();
  }, []);

  return { ...state, signOut };
}
