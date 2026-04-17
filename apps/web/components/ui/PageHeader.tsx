import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type PageHeaderProps = {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex flex-col gap-3 border-b border-[var(--color-line)] pb-6 md:flex-row md:items-end md:justify-between md:gap-8",
        className,
      )}
    >
      <div className="flex flex-col gap-1.5">
        {eyebrow ? (
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-mute-2)]">
            {eyebrow}
          </span>
        ) : null}
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)] md:text-3xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-2xl text-sm leading-relaxed text-[var(--color-mute)] md:text-base">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
