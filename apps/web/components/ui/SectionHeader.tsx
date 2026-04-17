import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type SectionHeaderProps = {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  align?: "left" | "center";
  className?: string;
};

export function SectionHeader({
  eyebrow,
  title,
  description,
  align = "center",
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4",
        align === "center" ? "items-center text-center" : "items-start text-left",
        "max-w-3xl",
        align === "center" && "mx-auto",
        className,
      )}
    >
      {eyebrow ? (
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-brand-600)]">
          {eyebrow}
        </span>
      ) : null}
      <h2 className="text-balance text-3xl font-semibold leading-[1.1] tracking-tight text-[var(--color-ink)] md:text-[2.75rem]">
        {title}
      </h2>
      {description ? (
        <p className="text-pretty text-base leading-relaxed text-[var(--color-mute)] md:text-lg">
          {description}
        </p>
      ) : null}
    </div>
  );
}
