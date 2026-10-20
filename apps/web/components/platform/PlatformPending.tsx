import { Skeleton } from "@/components/ui/Skeleton";

export function PlatformPending({ title, label }: { title: string; label: string }) {
  return (
    <section className="min-w-0" aria-busy="true" aria-label={title}>
      <h1 className="border-b border-[var(--color-line)] pb-4 text-2xl font-bold">{title}</h1>
      <p role="status" className="py-4 text-sm text-[var(--color-mute)]">{label}</p>
      <div aria-hidden className="space-y-3 border-y border-[var(--color-line)] py-4">
        {[0, 1, 2, 3, 4].map((row) => (
          <div key={row} className="grid min-w-0 grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-6 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
            <Skeleton className="h-5 w-full max-w-64" />
            <Skeleton className="h-5 w-full max-w-28" />
            <Skeleton className="hidden h-5 w-full max-w-36 sm:block" />
          </div>
        ))}
      </div>
    </section>
  );
}
