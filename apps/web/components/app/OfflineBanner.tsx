"use client";

import { useQueryClient } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

import { isNetworkError } from "@/lib/api/config";

/** A thin stripe at the top of the authenticated shell shown when:
 *  - the browser reports it's offline (`navigator.onLine === false`), or
 *  - the most recent query in the react-query cache failed with a
 *    `NetworkError` (the API host is unreachable from our browser even
 *    if the device thinks it's online — happens on corporate networks
 *    behind split-horizon DNS or when the API pod is draining).
 *
 *  It auto-hides the moment either condition clears. Kept intentionally
 *  understated so a momentary blip doesn't scream "red banner" at the
 *  user — the sign that things are fine is the banner disappearing. */
export function OfflineBanner() {
  const client = useQueryClient();
  const [browserOffline, setBrowserOffline] = useState(false);
  const [apiUnreachable, setApiUnreachable] = useState(false);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setBrowserOffline(!navigator.onLine);
    }
    const on = () => setBrowserOffline(false);
    const off = () => setBrowserOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    const unsubscribe = client.getQueryCache().subscribe(() => {
      const queries = client.getQueryCache().getAll();
      const anyNetworkError = queries.some(
        (q) => q.state.status === "error" && isNetworkError(q.state.error),
      );
      const anyFreshSuccess = queries.some(
        (q) =>
          q.state.status === "success" &&
          q.state.dataUpdatedAt > Date.now() - 5_000,
      );
      // Only flip on if we have an outstanding network-flavoured error
      // AND no query has succeeded in the last 5 seconds. That keeps the
      // banner off during normal per-request blips.
      setApiUnreachable(anyNetworkError && !anyFreshSuccess);
    });
    return unsubscribe;
  }, [client]);

  if (!browserOffline && !apiUnreachable) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-banner"
      className="flex items-center justify-center gap-2 border-b border-[var(--color-warning-500)]/40 bg-[var(--color-warning-500)]/10 px-4 py-1.5 text-xs font-medium text-[var(--color-ink)]"
    >
      <WifiOff className="h-3.5 w-3.5" aria-hidden />
      {browserOffline
        ? "You're offline. Changes won't save until your connection comes back."
        : "Workspace API is unreachable. Retrying…"}
    </div>
  );
}
