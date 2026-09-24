"use client";

import { ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";

type Props = {
  blob: Blob;
  filename: string;
};

const frameDocument = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; object-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'; frame-src 'none'"><meta name="viewport" content="width=device-width, initial-scale=1"><style>
@media (max-width: 600px) {
  .docx-wrapper { align-items: flex-start !important; box-sizing: border-box !important; width: 100% !important; overflow-x: auto !important; padding: 12px !important; }
  .docx-wrapper > section.docx { flex: none !important; margin-left: 0 !important; margin-right: 0 !important; }
}
</style></head><body style="margin:0;background:#f3f4f6"><div id="styles"></div><div id="pages"></div></body></html>`;

export function DocxViewer({ blob, filename }: Props): React.JSX.Element {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [frameReady, setFrameReady] = useState(false);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    const pages = frameRef.current?.contentDocument?.getElementById("pages");
    if (pages) pages.style.zoom = String(zoom);
  }, [frameReady, zoom]);

  useEffect(() => {
    if (!frameReady) return;
    const frame = frameRef.current;
    const frameDoc = frame?.contentDocument;
    const body = frameDoc?.getElementById("pages");
    const styles = frameDoc?.getElementById("styles");
    if (!body || !styles) {
      setState("error");
      return;
    }
    let cancelled = false;
    setState("loading");
    import("docx-preview")
      .then(({ renderAsync }) =>
        renderAsync(blob, body, styles, {
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          renderAltChunks: false,
          renderComments: false,
          renderChanges: false,
          useBase64URL: true,
        }),
      )
      .then(() => {
        if (cancelled) return;
        body.querySelectorAll("a").forEach((link) => {
          link.removeAttribute("href");
          link.removeAttribute("target");
          link.tabIndex = -1;
        });
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [blob, frameReady]);

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex h-8 shrink-0 items-center justify-end gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-8 px-0"
          aria-label="Zoom out"
          title="Zoom out"
          disabled={zoom <= 0.5}
          onClick={() => setZoom((value) => Math.max(0.5, +(value - 0.15).toFixed(2)))}
        >
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="w-12 text-center text-xs tabular-nums">{Math.round(zoom * 100)}%</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-8 px-0"
          aria-label="Zoom in"
          title="Zoom in"
          disabled={zoom >= 2}
          onClick={() => setZoom((value) => Math.min(2, +(value + 0.15).toFixed(2)))}
        >
          <ZoomIn className="h-4 w-4" />
        </Button>
      </div>
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden rounded-md border border-[var(--color-line)] bg-white">
        <iframe
          ref={frameRef}
          title={`DOCX preview: ${filename}`}
          data-testid="docx-preview-frame"
          className="h-full w-full border-0"
          sandbox="allow-same-origin"
          srcDoc={frameDocument}
          onLoad={() => {
            setFrameReady(true);
            setZoom((frameRef.current?.contentDocument?.documentElement.clientWidth ?? 999) < 600 ? 0.65 : 1);
          }}
        />
        {state !== "ready" ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white p-4 text-center text-sm" role="status">
            {state === "error"
              ? "This DOCX could not be rendered safely. Download the original file to continue."
              : "Rendering document…"}
          </div>
        ) : null}
      </div>
    </div>
  );
}
