import { cn } from "@/lib/cn";

const PALETTE: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  intake: "bg-sky-50 text-sky-700 border-sky-200",
  on_hold: "bg-amber-50 text-amber-800 border-amber-200",
  closed: "bg-slate-100 text-slate-700 border-slate-200",
  draft: "bg-slate-100 text-slate-700 border-slate-200",
  issued: "bg-sky-50 text-sky-700 border-sky-200",
  partially_paid: "bg-amber-50 text-amber-800 border-amber-200",
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
  void: "bg-rose-50 text-rose-700 border-rose-200",
  pending: "bg-amber-50 text-amber-800 border-amber-200",
  created: "bg-sky-50 text-sky-700 border-sky-200",
  failed: "bg-rose-50 text-rose-700 border-rose-200",
  expired: "bg-rose-50 text-rose-700 border-rose-200",
  cancelled: "bg-slate-100 text-slate-700 border-slate-200",
  unknown: "bg-slate-100 text-slate-700 border-slate-200",
};

const DEFAULT = "bg-[var(--color-bg-2)] text-[var(--color-ink-2)] border-[var(--color-line)]";

export function StatusBadge({
  status,
  className,
}: {
  status: string | null | undefined;
  className?: string;
}) {
  const key = (status ?? "").toLowerCase();
  const label = key.replace(/_/g, " ") || "unknown";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize",
        PALETTE[key] ?? DEFAULT,
        className,
      )}
    >
      {label}
    </span>
  );
}
