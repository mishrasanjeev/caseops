import { cn } from "@/lib/cn";
import type { RenditionTone } from "@/lib/renditions";

const TONES: Record<RenditionTone, string> = {
  neutral: "border-[var(--color-line)] bg-[var(--color-bg-2)] text-[var(--color-ink-2)]",
  brand: "border-[var(--color-brand-100)] bg-[var(--color-brand-50)] text-[var(--color-brand-700)]",
  success:
    "border-[var(--color-success-300)] bg-[var(--color-success-50)] text-[var(--color-success-700)]",
  warning: "border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] text-[var(--color-warn-text)]",
  danger:
    "border-[var(--color-danger-border)] bg-[var(--color-danger-bg)] text-[var(--color-danger-text)]",
};

/** A text status chip; the words carry the meaning, colour only reinforces it. */
export function RenditionStatusBadge({
  label,
  tone,
  className,
  ...props
}: {
  label: string;
  tone: RenditionTone;
  className?: string;
} & Omit<React.HTMLAttributes<HTMLSpanElement>, "children">) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    >
      {label}
    </span>
  );
}
