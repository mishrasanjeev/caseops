import Link from "next/link";

import { cn } from "@/lib/cn";

export function Logo({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      className={cn(
        "inline-flex items-center gap-2.5 text-[var(--color-ink)] transition-opacity hover:opacity-80",
        className,
      )}
      aria-label="CaseOps home"
    >
      <span
        aria-hidden
        className="relative inline-flex h-8 w-8 items-center justify-center rounded-[10px] bg-[var(--color-ink)] text-white shadow-[var(--shadow-soft)]"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
          <path
            d="M4 6.5C4 5.67 4.67 5 5.5 5H14l6 6v7.5c0 .83-.67 1.5-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-12Z"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinejoin="round"
          />
          <path d="M14 5v5.5c0 .28.22.5.5.5H20" stroke="currentColor" strokeWidth="1.75" />
          <path
            d="M8 13h8M8 16h5"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
          />
        </svg>
      </span>
      <span className="text-[0.95rem] font-semibold tracking-tight">CaseOps</span>
    </Link>
  );
}
