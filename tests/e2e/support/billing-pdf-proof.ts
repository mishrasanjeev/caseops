/**
 * ENH-001: read a downloaded billing PDF the way a person would.
 *
 * The page is rendered with pdfjs on a browser canvas. From that raster we
 * measure every text run's ink contrast against its own background, count the
 * images the page paints (logo, signature, watermark, QR code), and hand the
 * pixels to jsQR so the QR code is decoded from what is actually printed, not
 * from the link text beside it.
 */
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BrowserContext } from "@playwright/test";

import { repoRoot } from "./env";
import { loadJsQR } from "./external-journey-loaders";

export type RasterRun = { page: number; text: string; contrast: number; inside: boolean };
export type BillingPdfProof = {
  pages: number;
  text: string;
  runs: RasterRun[];
  /** Image paint operations per page, in page order. */
  imagesPerPage: number[];
  /** The QR code decoded from page pixels, or null when none was found. */
  qr: string | null;
  sha256: string;
};

export const compact = (value: string) => value.replace(/\s+/g, "");

export async function pdfText(data: Buffer): Promise<string[]> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const document = await pdfjs.getDocument({ data: new Uint8Array(data), useSystemFonts: false }).promise;
  const pages: string[] = [];
  for (let number = 1; number <= document.numPages; number += 1) {
    const content = await (await document.getPage(number)).getTextContent();
    pages.push(content.items.map(item => ("str" in item ? item.str : "")).join(" "));
  }
  return pages;
}

export async function proveBillingPdf(context: BrowserContext, data: Buffer): Promise<BillingPdfProof> {
  const origin = "https://pdf-raster.invalid";
  const files: Record<string, string> = { "/pdf.mjs": "pdf.min.mjs", "/pdf.worker.mjs": "pdf.worker.min.mjs" };
  const raster = await context.newPage();
  try {
    await raster.route(`${origin}/**`, async (route) => {
      const name = new URL(route.request().url()).pathname;
      if (name === "/") return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>raster</title>" });
      const file = files[name];
      if (!file) return route.fulfill({ status: 404, body: "" });
      return route.fulfill({ contentType: "text/javascript",
        body: await readFile(path.join(repoRoot, "node_modules/pdfjs-dist/build", file)) });
    });
    await raster.goto(`${origin}/`);
    const result = await raster.evaluate(async ({ base64, scale }) => {
      const pdfjs = await import(`${location.origin}/pdf.mjs`);
      (globalThis as any).pdfjsWorker = await import(`${location.origin}/pdf.worker.mjs`);
      const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
      const doc = await pdfjs.getDocument({ data: bytes, isEvalSupported: false }).promise;
      const channel = (v: number) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
      const lum = (r: number, g: number, b: number) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      const runContrast = (ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number) => {
        const w = x1 - x0;
        const h = y1 - y0;
        if (w < 2 || h < 2) return 1;
        const px = ctx.getImageData(x0, y0, w, h).data;
        const counts = new Map<number, number>();
        for (let i = 0; i < px.length; i += 4) {
          const key = (px[i] << 16) | (px[i + 1] << 8) | px[i + 2];
          counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        let background = 0;
        let most = -1;
        for (const [key, count] of counts) if (count > most) { most = count; background = key; }
        const backgroundLum = lum((background >> 16) & 255, (background >> 8) & 255, background & 255);
        const insetX = Math.floor(w / 10);
        const insetY = Math.floor(h / 5);
        let best = 1;
        for (let y = insetY; y < h - insetY; y += 1) {
          for (let x = insetX; x < w - insetX; x += 1) {
            const i = (y * w + x) * 4;
            const value = lum(px[i], px[i + 1], px[i + 2]);
            const ratio = (Math.max(value, backgroundLum) + 0.05) / (Math.min(value, backgroundLum) + 0.05);
            if (ratio > best) best = ratio;
          }
        }
        return best;
      };
      const runs: Array<{ page: number; text: string; contrast: number; inside: boolean }> = [];
      const imagesPerPage: number[] = [];
      const texts: string[] = [];
      let lastPage: { width: number; height: number; rgba: string } | null = null;
      for (let number = 1; number <= doc.numPages; number += 1) {
        const page = await doc.getPage(number);
        const viewport = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvas, canvasContext: ctx, viewport }).promise;
        const operators = await page.getOperatorList();
        imagesPerPage.push(operators.fnArray.filter((fn: number) =>
          fn === pdfjs.OPS.paintImageXObject || fn === pdfjs.OPS.paintInlineImageXObject).length);
        const [, , pageWidth, pageHeight] = page.view;
        const content = await page.getTextContent();
        texts.push(content.items.map((item: any) => ("str" in item ? item.str : "")).join(" "));
        for (const item of content.items as any[]) {
          if (!("str" in item) || !item.str.trim()) continue;
          const [, , c, d, e, f] = pdfjs.Util.transform(viewport.transform, item.transform);
          const size = Math.hypot(c, d);
          const x0 = Math.max(0, Math.floor(e));
          const x1 = Math.min(canvas.width, Math.ceil(e + item.width * scale));
          const y0 = Math.max(0, Math.floor(f - size * 0.8));
          const y1 = Math.min(canvas.height, Math.ceil(f + size * 0.2));
          const [, , , , tx, ty] = item.transform;
          runs.push({
            page: number, text: item.str, contrast: runContrast(ctx, x0, y0, x1, y1),
            inside: tx >= 0 && tx + item.width <= pageWidth + 0.5 && ty >= 0 && ty <= pageHeight,
          });
        }
        // The closing block (and its QR code) is on the last page.
        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let binary = "";
        for (let i = 0; i < pixels.length; i += 0x8000) {
          binary += String.fromCharCode(...pixels.subarray(i, i + 0x8000));
        }
        lastPage = { width: canvas.width, height: canvas.height, rgba: btoa(binary) };
      }
      return { pages: doc.numPages, runs, imagesPerPage, text: texts.join("\n"), lastPage };
    }, { base64: data.toString("base64"), scale: 200 / 72 });
    let qr: string | null = null;
    if (result.lastPage) {
      const rgba = new Uint8ClampedArray(Buffer.from(result.lastPage.rgba, "base64"));
      qr = loadJsQR()(rgba, result.lastPage.width, result.lastPage.height, { inversionAttempts: "dontInvert" })?.data ?? null;
    }
    return {
      pages: result.pages, text: result.text, runs: result.runs, imagesPerPage: result.imagesPerPage, qr,
      sha256: createHash("sha256").update(data).digest("hex"),
    };
  } finally {
    await raster.close();
  }
}

/** The link printed under the QR code ("Verification link: <url>"). */
export function printedVerificationLink(text: string): string | null {
  return /Verification\s*link:\s*(https?:\/\/\S+?\/verify\/[A-Za-z0-9_-]{43})/.exec(text)?.[1] ?? null;
}
