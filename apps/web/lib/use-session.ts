"use client";

import { useCallback, useEffect, useState } from "react";

import { refreshAccessToken } from "@/lib/api/client";
import {
  type StoredContext,
  clearSession,
  getStoredContext,
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
    // EG-001 (2026-04-23): the access token now lives in an HttpOnly
    // cookie that JS cannot read, so we derive auth status from
    // whether we have stored context (workspace + user + membership)
    // alone. ``token`` stays in the state shape for back-compat with
    // call sites that still read ``state.token``; it is always null.
    const context = getStoredContext();
    setState({
      token: null,
      context,
      status: context ? "authenticated" : "anonymous",
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
    // EG-001 (2026-04-23): the session credential lives in an
    // HttpOnly cookie that JS cannot delete. Hitting /api/auth/logout
    // makes the server respond with Set-Cookie max-age=0 to wipe
    // both the session and CSRF cookies. Local context goes too so
    // the next /sign-in is clean. Fire-and-forget — even if the API
    // is unreachable we still clear local state so the UI shows the
    // signed-out shell immediately.
    void fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/auth/logout`,
      {
        method: "POST",
        credentials: "include",
      },
    ).catch(() => undefined);
    clearSession();
  }, []);

  return { ...state, signOut };
}
