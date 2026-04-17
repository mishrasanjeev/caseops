"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/Button";

export default function AppSegmentError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.error("/app segment boundary caught:", error);
    }
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 px-6 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-danger-500)]/10 text-[var(--color-danger-500)]">
        <AlertTriangle className="h-5 w-5" aria-hidden />
      </span>
      <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)]">
        Something went wrong in your workspace
      </h1>
      <p className="max-w-lg text-sm leading-relaxed text-[var(--color-mute)]">
        {error.message ||
          "An unexpected error stopped this screen from rendering. Try again — if it keeps happening, please share the error reference below with support."}
      </p>
      {error.digest ? (
        <p className="text-xs tabular text-[var(--color-mute-2)]">
          Reference: <span className="font-mono">{error.digest}</span>
        </p>
      ) : null}
      <div className="mt-3 flex items-center gap-2">
        <Button onClick={reset} data-testid="error-boundary-reset">
          <RefreshCw className="h-4 w-4" aria-hidden /> Try again
        </Button>
        <Button href="/app" variant="outline">
          Back to workspace home
        </Button>
        <Link
          href="mailto:support@caseops.ai?subject=Workspace%20error"
          className="text-xs font-medium text-[var(--color-brand-700)] underline-offset-4 hover:underline"
        >
          Contact support
        </Link>
      </div>
    </div>
  );
}
