"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type StoredContext,
  clearSession,
  getStoredContext,
  getStoredToken,
  subscribeSession,
} from "@/lib/session";

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

  const signOut = useCallback(() => {
    clearSession();
  }, []);

  return { ...state, signOut };
}
