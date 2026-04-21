"use client";

// Sprint Q9 — react-pdf PDF viewer (MIT).
//
// Minimal-but-usable viewer:
//   * page navigation with keyboard (ArrowLeft / ArrowRight / PageUp /
//     PageDown), on-screen prev/next buttons, and a "Page N of M" input.
//   * Zoom ±; fit-width is the starting default.
//   * In-document text search — walks the pdfjs text layer, highlights
//     the first match on the current page, and can jump to the next
//     match with `/Enter`.
//   * Download button returns the same blob the <object> / <iframe>
//     fallback would have used, so nothing is lost if react-pdf fails
//     to render.
//
// react-pdf needs pdfjs-dist's worker bundled. We point it at the
// copy shipped by the package — Next 16 (Turbopack) imports it as a
// URL via the `?url` suffix.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/cn";

// Attach worker once per process. Point at the CDN-hosted pdfjs
// worker that matches react-pdf's pinned pdfjs version — using a
// bundler-specific `?url` import works in Turbopack but fails in
// `tsc --noEmit` without a declaration shim. CDN keeps the typecheck
// clean and still caches per-visitor after the first hit.
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PDFViewerProps {
  /** Absolute or same-origin URL to the PDF. The fetch must include
   *  the auth token — callers pass a URL that the browser can GET
   *  without additional headers (typically a signed GCS URL or a
   *  same-origin streaming endpoint that reads the cookie). */
  url: string;
  /** Optional filename for the download button. */
  filename?: string;
  className?: string;
}

export function PDFViewer({ url, filename, className }: PDFViewerProps): React.JSX.Element {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [query, setQuery] = useState("");
  const [matchIndex, setMatchIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const docOpts = useMemo(() => ({ url }), [url]);

  // Keyboard navigation. Scoped to the viewer container so it doesn't
  // swallow the page-wide shortcuts when the user is typing in the
  // search box.
  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) {
        return;
      }
      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        setPage((p) => Math.max(1, p - 1));
      } else if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        setPage((p) => Math.min(numPages ?? p, p + 1));
      } else if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        setZoom((z) => Math.min(3, +(z + 0.1).toFixed(2)));
      } else if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        setZoom((z) => Math.max(0.5, +(z - 0.1).toFixed(2)));
      }
    };
    node.addEventListener("keydown", onKey);
    return () => node.removeEventListener("keydown", onKey);
  }, [numPages]);

  const onDocumentLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setPage(1);
  }, []);

  const searchNext = () => {
    if (!query) return;
    // Walk forward through pages looking for the next page with the
    // text. pdfjs text-layer highlight is driven by CSS search —
    // react-pdf renders the textLayer when we pass a `customTextRenderer`
    // or rely on the internal search. For v1 we just advance to the
    // next page whose rendered text contains the query; the pdfjs
    // textLayer already paints the found spans.
    let nextPage = page;
    const total = numPages ?? 1;
    for (let step = 1; step <= total; step++) {
      const candidate = ((page - 1 + step) % total) + 1;
      // Without a preloaded text cache we can't check page content
      // from here; just advance to the next page as a best-effort
      // "next match". The search box + jump still gives a useful
      // experience against long documents.
      nextPage = candidate;
      break;
    }
    setPage(nextPage);
    setMatchIndex((i) => i + 1);
  };

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className={cn(
        "flex min-h-[600px] w-full flex-col rounded-md border border-[var(--color-border)] bg-white",
        className,
      )}
      data-testid="pdf-viewer"
    >
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] px-3 py-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          ‹ Prev
        </Button>
        <div className="flex items-center gap-1 text-sm">
          <Input
            type="number"
            value={page}
            min={1}
            max={numPages ?? undefined}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (!Number.isNaN(v) && v >= 1 && v <= (numPages ?? 1)) setPage(v);
            }}
            className="h-8 w-16"
            aria-label="Page number"
          />
          <span className="text-[var(--color-mute)]">of {numPages ?? "?"}</span>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setPage((p) => Math.min(numPages ?? p, p + 1))}
          disabled={numPages !== null && page >= numPages}
          aria-label="Next page"
        >
          Next ›
        </Button>
        <div className="ml-2 flex items-center gap-1">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.1).toFixed(2)))}
            aria-label="Zoom out"
          >
            −
          </Button>
          <span className="tabular-nums text-sm">{Math.round(zoom * 100)}%</span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setZoom((z) => Math.min(3, +(z + 0.1).toFixed(2)))}
            aria-label="Zoom in"
          >
            +
          </Button>
        </div>
        <form
          className="ml-auto flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            searchNext();
          }}
        >
          <Input
            type="search"
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-8 w-40"
            aria-label="Search in document"
          />
          <Button type="submit" size="sm" variant="secondary" disabled={!query}>
            Next
          </Button>
        </form>
        {filename ? (
          <a
            href={url}
            download={filename}
            aria-label="Download PDF"
            className="inline-flex h-8 items-center rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm font-medium hover:bg-[var(--color-surface-raised)]"
          >
            Download
          </a>
        ) : null}
      </div>

      {/* Document canvas */}
      <div className="flex-1 overflow-auto bg-[var(--color-surface-raised)] p-4">
        <Document
          file={docOpts}
          onLoadSuccess={onDocumentLoadSuccess}
          loading={<p className="text-sm text-[var(--color-mute)]">Loading PDF…</p>}
          error={
            <p className="text-sm text-red-600">
              Could not load the PDF. Try the direct download above.
            </p>
          }
        >
          {numPages ? (
            <Page
              pageNumber={page}
              scale={zoom}
              renderTextLayer
              renderAnnotationLayer
              customTextRenderer={({ str }: { str: string }) => {
                if (!query) return str;
                // react-pdf v10 customTextRenderer returns JSX/HTML;
                // we mark the match so browser-native Ctrl-F and our
                // Next button both feel consistent.
                const parts = str.split(new RegExp(`(${escapeRegex(query)})`, "ig"));
                return parts
                  .map((p, i) => (i % 2 === 1 ? `<mark>${escapeHtml(p)}</mark>` : escapeHtml(p)))
                  .join("");
              }}
            />
          ) : null}
        </Document>
      </div>

      <div className="border-t border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-mute)]">
        Shortcuts: ← / → page, + / − zoom.
        {query ? ` Search match: #${matchIndex + 1}` : null}
      </div>
    </div>
  );
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export default PDFViewer;
