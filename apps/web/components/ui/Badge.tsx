import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type BadgeProps = {
  tone?: "neutral" | "brand" | "success" | "warning";
  className?: string;
  children: ReactNode;
};

const tones: Record<NonNullable<BadgeProps["tone"]>, string> = {
  neutral: "bg-[var(--color-bg-2)] text-[var(--color-ink-2)] border-[var(--color-line)]",
  brand: "bg-[var(--color-brand-50)] text-[var(--color-brand-700)] border-[var(--color-brand-100)]",
  success: "bg-green-50 text-green-800 border-green-100",
  warning: "bg-amber-50 text-amber-800 border-amber-100",
};

export function Badge({ tone = "neutral", className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium tracking-tight",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
