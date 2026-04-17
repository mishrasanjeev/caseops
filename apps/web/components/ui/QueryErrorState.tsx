"use client";

import { AlertTriangle, RefreshCw, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { isNetworkError } from "@/lib/api/config";

type QueryErrorStateProps = {
  error: unknown;
  /** Falls back to "We couldn't load this yet." when the caller doesn't
   * supply a title — but prefer supplying one that names the surface
   * (e.g. "Could not load matters"), it's what screen-reader users hear. */
  title?: string;
  /** Called when the user clicks "Try again". Usually the react-query
   * `refetch` returned by the hook; we await it and disable the button
   * while it's in flight. */
  onRetry?: () => Promise<unknown> | unknown;
  /** Extra content rendered next to (or instead of) the retry button —
   * e.g. a "Back to portfolio" link when retrying the failed query is
   * pointless (404, forbidden). */
  secondaryAction?: ReactNode;
  className?: string;
};

function fallbackMessage(err: unknown): string {
  if (isNetworkError(err)) {
    return err.message;
  }
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Please try again.";
}

export function QueryErrorState({
  error,
  title,
  onRetry,
  secondaryAction,
  className,
}: QueryErrorStateProps) {
  const [retrying, setRetrying] = useState(false);
  const network = isNetworkError(error);
  const resolvedTitle =
    title ?? (network ? "Workspace is offline" : "We couldn't load this");
  const icon = network ? WifiOff : AlertTriangle;

  const handleRetry = async () => {
    if (!onRetry) return;
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <EmptyState
      icon={icon}
      title={resolvedTitle}
      description={fallbackMessage(error)}
      className={className}
      action={
        onRetry || secondaryAction ? (
          <div className="flex flex-wrap items-center justify-center gap-2">
            {onRetry ? (
              <Button
                variant="outline"
                onClick={handleRetry}
                disabled={retrying}
                data-testid="query-error-retry"
              >
                <RefreshCw
                  className={retrying ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                  aria-hidden
                />
                {retrying ? "Retrying…" : "Try again"}
              </Button>
            ) : null}
            {secondaryAction}
          </div>
        ) : null
      }
    />
  );
}
