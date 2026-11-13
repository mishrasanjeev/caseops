"use client";

import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { Button } from "@/components/ui/Button";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

export default function DraftPdfPages({ file }: { file: Blob }) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [failed, setFailed] = useState(false);
  const [renderedPage, setRenderedPage] = useState(0);
  const [textPage, setTextPage] = useState(0);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return <div className="min-w-0" data-testid="draft-pdf-preview">
    <div className="mb-3 flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="PDF pages">
      <Button variant="ghost" size="sm" title="Previous PDF page" aria-label="Previous PDF page"
        disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft className="h-4 w-4" aria-hidden /></Button>
      <span role="status" className="text-sm tabular-nums" data-testid="draft-pdf-pagination">Page {page} of {total || "..."}</span>
      <Button variant="ghost" size="sm" title="Next PDF page" aria-label="Next PDF page"
        disabled={!total || page >= total} onClick={() => setPage(page + 1)}><ChevronRight className="h-4 w-4" aria-hidden /></Button>
      <Button variant="ghost" size="sm" title="Zoom out" aria-label="Zoom out PDF"
        disabled={zoom <= 1} onClick={() => setZoom(Math.max(1, zoom - 0.25))}><ZoomOut className="h-4 w-4" aria-hidden /></Button>
      <Button variant="ghost" size="sm" title="Zoom in" aria-label="Zoom in PDF"
        disabled={zoom >= 2} onClick={() => setZoom(Math.min(2, zoom + 0.25))}><ZoomIn className="h-4 w-4" aria-hidden /></Button>
      <span className="text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
    </div>
    <div ref={container} className="relative min-w-0 overflow-x-auto bg-[var(--color-bg)]"
      tabIndex={0} role="region" aria-label="PDF page canvas" data-rendered-page={renderedPage} data-text-page={textPage}>
      <Document file={file} onLoadSuccess={({ numPages }) => setTotal(numPages)}
        onLoadError={() => setFailed(true)} loading={<p role="status">Loading PDF pages...</p>}
        error={<p role="alert">PDF pages could not be displayed. The PDF download remains available.</p>}>
        {failed ? <p role="alert">PDF pages could not be displayed. The PDF download remains available.</p>
          : width > 0 && total > 0 ? <Page pageNumber={page} width={Math.min(width, 850) * zoom}
          renderTextLayer renderAnnotationLayer={false} onRenderError={() => setFailed(true)}
          onRenderSuccess={() => setRenderedPage(page)}
          onRenderTextLayerSuccess={() => setTextPage(page)}
          error={<p role="alert">This PDF page could not be displayed.</p>} /> : null}
      </Document>
    </div>
  </div>;
}
