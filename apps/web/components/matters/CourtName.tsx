import { ExternalLink, Landmark } from "lucide-react";
import type { KeyboardEvent, MouseEvent } from "react";

import { cn } from "@/lib/cn";

/**
 * The one way a matter's court is shown. The server resolves
 * `court_website_url` from the matter's catalogue identity (never from this
 * display text); when it is present the name opens the court's official
 * website in a new tab, otherwise the name is plain text so no surface shows
 * a dead link or an external-link icon that does nothing.
 */
export function courtWebsiteHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

// A court link inside a clickable table row must not also activate the row.
function stop(event: MouseEvent | KeyboardEvent) {
  event.stopPropagation();
}

export function CourtName({
  name,
  websiteUrl,
  fallback = "—",
  variant = "inline",
  className,
  testId = "court-name",
}: {
  name: string | null | undefined;
  websiteUrl: string | null | undefined;
  fallback?: string;
  variant?: "badge" | "inline";
  className?: string;
  testId?: string;
}) {
  const label = name?.trim();
  const href = label ? courtWebsiteHref(websiteUrl) : null;
  const badge =
    "inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--color-line)] bg-white px-3 py-1.5 text-xs";
  if (!href) {
    return (
      <span
        className={cn(
          variant === "badge" ? cn(badge, "text-[var(--color-mute)]") : "",
          className,
        )}
        data-testid={testId}
        data-court-link="none"
      >
        {variant === "badge" ? (
          <Landmark className="h-3.5 w-3.5 shrink-0" aria-hidden />
        ) : null}
        <span className={variant === "badge" ? "truncate" : undefined}>{label || fallback}</span>
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Open ${label} website (opens in new tab)`}
      title={`Open ${label} website (opens in new tab)`}
      onClick={stop}
      onKeyDown={stop}
      data-testid={testId}
      data-court-link="official"
      className={cn(
        variant === "badge"
          ? cn(
              badge,
              "font-medium text-[var(--color-ink-2)] hover:border-[var(--color-brand-500)] hover:text-[var(--color-ink)]",
            )
          : "inline-flex items-center gap-1 text-[var(--color-ink-2)] underline decoration-[var(--color-line)] underline-offset-2 hover:text-[var(--color-ink)] hover:decoration-[var(--color-ink-3)]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]",
        className,
      )}
    >
      {variant === "badge" ? <Landmark className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
      <span className={variant === "badge" ? "truncate" : undefined}>{label}</span>
      <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}
