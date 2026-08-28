"use client";

import { useEffect, useRef } from "react";

export function useSequencedQuerySettled({
  enabled,
  identity,
  settled,
  onSettled,
}: {
  enabled: boolean;
  identity: string;
  settled: boolean;
  onSettled?: () => void;
}) {
  const reportedIdentity = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || !settled || reportedIdentity.current === identity) return;
    reportedIdentity.current = identity;
    onSettled?.();
  }, [enabled, identity, onSettled, settled]);
}
