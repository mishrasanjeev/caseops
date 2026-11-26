import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * The one reading column for long-form documents inside the app shell
 * (research answers today). It is centred in `<main>` so the margins balance
 * at every width, and its children share its two edges: do not give a child
 * its own `max-w-*`.
 *
 * Width: 70ch of the 16px body face, the middle of the 65-75ch band in
 * `.impeccable.md` and between the house `text-prose` (65ch) and
 * `text-prose-wide` (75ch) utilities. `text-base` is set here because `ch`
 * resolves against this element's font size; body copy inside stays at
 * `text-base` so the measure holds.
 */
export function ReadingColumn({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mx-auto w-full min-w-0 max-w-[70ch] text-base", className)} {...props} />;
}
