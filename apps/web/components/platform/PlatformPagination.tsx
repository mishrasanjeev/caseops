import { ChevronLeft, ChevronRight } from "lucide-react";

export function PlatformPagination({ page, pending, hasNext, onPrevious, onNext }: {
  page: number; pending: boolean; hasNext: boolean; onPrevious: () => void; onNext: () => void;
}) {
  return <nav aria-label="Report pagination" className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--color-line)] pt-4 text-sm">
    <span aria-live="polite">Page {page + 1}</span>
    <div className="flex gap-2">
      <button type="button" aria-label="Previous page" title="Previous page" disabled={pending || page === 0} onClick={onPrevious}
        className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-[var(--color-line)] disabled:opacity-40"><ChevronLeft className="h-4 w-4" aria-hidden /></button>
      <button type="button" aria-label="Next page" title="Next page" disabled={pending || !hasNext} onClick={onNext}
        className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-[var(--color-line)] disabled:opacity-40"><ChevronRight className="h-4 w-4" aria-hidden /></button>
    </div>
  </nav>;
}
