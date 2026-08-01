"use client";

import { ExternalLink, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { API_BASE_URL } from "@/lib/api/config";

export type SourceActionState =
  | "available"
  | "missing"
  | "unverified"
  | "blocked"
  | "quarantined";

export type SourceActionContract = {
  state: SourceActionState;
  label: string;
  open_url: string | null;
  source_reference: string | null;
  reason: string | null;
  opens_new_tab: boolean;
};

export function SourceAction({
  action,
  compact = false,
}: {
  action: SourceActionContract | null | undefined;
  compact?: boolean;
}) {
  if (action?.state === "available" && action.open_url) {
    const href = action.open_url.startsWith("/api/")
      ? `${API_BASE_URL}${action.open_url}`
      : action.open_url;
    return (
      <a
        href={href}
        target={action.opens_new_tab ? "_blank" : undefined}
        rel="noopener noreferrer"
        referrerPolicy="no-referrer"
        data-testid="source-action-open"
      >
        <Button size="sm" variant="outline" type="button">
          <ExternalLink className="h-4 w-4" aria-hidden />
          {compact ? "Source" : action.label}
        </Button>
      </a>
    );
  }

  const state = action?.state ?? "missing";
  const reason = action?.reason ?? "No verified source is available.";
  return (
    <span
      className="inline-flex max-w-64 items-start gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900"
      role="status"
      data-testid={`source-action-${state}`}
      title={reason}
    >
      <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{compact ? state.replaceAll("_", " ") : reason}</span>
    </span>
  );
}
