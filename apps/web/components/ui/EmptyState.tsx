import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type EmptyStateProps = {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-[var(--color-line)] bg-white px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
      ) : null}
      <h3 className="text-base font-semibold tracking-tight text-[var(--color-ink)]">{title}</h3>
      {description ? (
        <p className="max-w-md text-sm leading-relaxed text-[var(--color-mute)]">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
