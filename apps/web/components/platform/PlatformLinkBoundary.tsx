"use client";

import { createContext, Fragment, useContext, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { consumePlatformLink } from "@/lib/platform/privacy";

type LinkState = ReturnType<typeof consumePlatformLink> & { signal: AbortSignal };
type LinkSnapshot = { link: LinkState; lifetime: AbortController; generation: number };
const LinkContext = createContext<LinkState | null>(null);

export function PlatformLinkBoundary({ children }: { children: ReactNode }) {
  const captured = useRef<LinkSnapshot | null>(null);
  const [current, setCurrent] = useState<LinkSnapshot | null>(null);
  useLayoutEffect(() => {
    function consume() {
      // Fence old requests synchronously, before React commits the new form.
      captured.current?.lifetime.abort();
      const link = consumePlatformLink(window.location.href);
      window.history.replaceState(window.history.state, "", link.cleanUrl);
      const lifetime = new AbortController();
      const snapshot = { link: { ...link, signal: lifetime.signal }, lifetime, generation: (captured.current?.generation ?? 0) + 1 };
      captured.current = snapshot;
      setCurrent(snapshot);
    }
    function navigation() {
      const url = new URL(window.location.href);
      // A popstate/hashchange pair may follow the same navigation; the first
      // event already scrubbed it, so the second must not erase its token.
      if (url.hash || url.searchParams.has("token")) consume();
    }
    if (!captured.current) consume();
    window.addEventListener("hashchange", navigation);
    window.addEventListener("popstate", navigation);
    return () => {
      window.removeEventListener("hashchange", navigation);
      window.removeEventListener("popstate", navigation);
    };
  }, []);
  if (!current) return <p role="status" className="p-5 text-sm text-[var(--color-mute)]">Opening secure account page...</p>;
  return <LinkContext.Provider value={current.link}><Fragment key={current.generation}>{children}</Fragment></LinkContext.Provider>;
}

export function usePlatformLink() {
  return useContext(LinkContext);
}
