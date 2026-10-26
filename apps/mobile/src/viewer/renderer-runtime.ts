// This function is serialized into an isolated WebView. It must have no imports,
// credential access, dynamic code execution or dependency on the native JS realm.
export function rendererMain(config: {
  id: string;
  limits: {
    maxBytes: number;
    maxPages: number;
    maxCanvasPixels: number;
    maxImagePixels: number;
    maxPageTextCharacters: number;
    chunkBytes: number;
    renderMs: number;
  };
  assets: Record<string, string>;
}) {
  const host = window as unknown as Record<string, any>;
  const pdfjs = host.pdfjsLib;
  const root = document.getElementById("content")!;
  const status = document.getElementById("status")!;
  const canvas = document.getElementById("page") as HTMLCanvasElement;
  const text = document.getElementById("page-text")!;
  let payload: Uint8Array | null = null;
  let offset = 0,
    sequence = 0,
    pageNumber = 1,
    pageCount = 1,
    zoom = 1;
  let kind = "",
    mime = "",
    closed = false,
    rendering = false,
    renderAgain = false;
  let expiry = 0,
    timer: ReturnType<typeof setTimeout>,
    renderTimer: ReturnType<typeof setTimeout>;
  let task: any = null,
    pdf: any = null,
    renderTask: any = null;
  let image: HTMLImageElement | null = null,
    objectUrl = "";
  type TextRead = {
    reader: ReadableStreamDefaultReader<any>;
    strings: string[];
    cancelled: boolean;
    released: boolean;
  };
  let textRead: TextRead | null = null;
  const finishTextRead = (active: TextRead, cancel: boolean) => {
    if (textRead === active) textRead = null;
    active.strings.length = 0;
    const release = () => {
      if (active.released) return;
      try {
        active.reader.releaseLock();
        active.released = true;
      } catch {
        // A pending cancellation gets one further release after settling.
      }
    };
    if (cancel && !active.cancelled) {
      active.cancelled = true;
      try {
        void active.reader.cancel().then(release, release);
      } catch {
        // Cancellation failure cannot retain collected private text.
      }
    }
    release();
    return active.released;
  };
  const seenEvents = new WeakSet<Event>();
  const send = (type: string, extra: Record<string, unknown> = {}) =>
    host.ReactNativeWebView?.postMessage(
      JSON.stringify({ id: config.id, type, ...extra }),
    );
  const decode = (value: string) =>
    Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
  const expired = () => closed || (expiry !== 0 && Date.now() >= expiry);
  const clear = () => {
    closed = true;
    clearTimeout(timer);
    clearTimeout(renderTimer);
    payload?.fill(0);
    payload = null;
    if (textRead) finishTextRead(textRead, true);
    renderTask?.cancel();
    void task?.destroy();
    pdf = null;
    task = null;
    if (image) {
      image.src = "";
      image = null;
    }
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = "";
    canvas.width = canvas.height = 0;
    text.textContent = "";
    root.hidden = true;
    status.textContent = "Private document cleared";
  };
  const fail = () => {
    clear();
    status.textContent = "This document could not be safely displayed";
    send("error");
  };
  const requireLive = () => {
    if (expired()) {
      clear();
      throw new Error("Expired renderer");
    }
  };
  class BundledBinaryDataFactory {
    async fetch({
      kind: assetKind,
      filename,
    }: {
      kind: string;
      filename: string;
    }) {
      requireLive();
      if (!/^[A-Za-z0-9_.-]{1,100}$/.test(filename))
        throw new Error("Invalid public asset");
      const folder =
        assetKind === "cMapUrl"
          ? "cmaps"
          : assetKind === "standardFontDataUrl"
            ? "standard_fonts"
            : "";
      const data = config.assets[`${folder}/${filename}`];
      if (!folder || !data) throw new Error("Unsupported document resource");
      return decode(data);
    }
  }
  const render = async () => {
    if (rendering) {
      renderAgain = true;
      renderTask?.cancel();
      if (textRead) finishTextRead(textRead, true);
      return;
    }
    rendering = true;
    renderTimer = setTimeout(fail, config.limits.renderMs);
    try {
      do {
        renderAgain = false;
        requireLive();
        root.hidden = true;
        text.textContent = "";
        const chosenPage = pageNumber,
          chosenZoom = zoom;
        let width: number,
          height: number,
          page: any = null;
        if (pdf) {
          page = await pdf.getPage(chosenPage);
          requireLive();
          const viewport = page.getViewport({ scale: 1 });
          width = viewport.width;
          height = viewport.height;
        } else {
          width = image!.naturalWidth;
          height = image!.naturalHeight;
        }
        if (
          !Number.isFinite(width) ||
          !Number.isFinite(height) ||
          width <= 0 ||
          height <= 0
        )
          throw new Error("Invalid page dimensions");
        const scale = Math.max(
          0.01,
          (Math.min(window.innerWidth - 24, 1000) / width) * chosenZoom,
        );
        const cssWidth = width * scale,
          cssHeight = height * scale;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        if (
          cssWidth * cssHeight * ratio * ratio >
            config.limits.maxCanvasPixels ||
          cssWidth * ratio > 16384 ||
          cssHeight * ratio > 16384
        )
          throw new Error("Page exceeds pixel budget");
        canvas.width = Math.ceil(cssWidth * ratio);
        canvas.height = Math.ceil(cssHeight * ratio);
        canvas.style.width = `${cssWidth}px`;
        canvas.style.height = `${cssHeight}px`;
        const context = canvas.getContext("2d", { alpha: false })!;
        if (pdf) {
          renderTask = page.render({
            canvasContext: context,
            canvas,
            viewport: page.getViewport({ scale: scale * ratio }),
            annotationMode: pdfjs.AnnotationMode.DISABLE,
          });
          try {
            await renderTask.promise;
          } catch (error) {
            if (!renderAgain) throw error;
          }
          renderTask = null;
          requireLive();
          if (renderAgain) {
            page.cleanup();
            continue;
          }
          const active: TextRead = {
            reader: page
              .streamTextContent({ disableNormalization: false })
              .getReader(),
            strings: [],
            cancelled: false,
            released: false,
          };
          textRead = active;
          let complete = false,
            chars = 0,
            reads = 0,
            items = 0;
          try {
            for (;;) {
              requireLive();
              if (active.cancelled || renderAgain) break;
              if (++reads > config.limits.maxPageTextCharacters + 1)
                throw new Error("Page text stream exceeds budget");
              const chunk = await active.reader.read();
              requireLive();
              if (active.cancelled || renderAgain) break;
              if (typeof chunk.done !== "boolean")
                throw new Error("Invalid page text completion");
              if (chunk.done) {
                complete = true;
                break;
              }
              if (!chunk.value || !Array.isArray(chunk.value.items))
                throw new Error("Invalid page text stream");
              for (const item of chunk.value.items) {
                requireLive();
                if (++items > config.limits.maxPageTextCharacters + 1)
                  throw new Error("Page text items exceed budget");
                if (typeof item.str !== "string") continue;
                chars += item.str.length + 1;
                if (chars > config.limits.maxPageTextCharacters)
                  throw new Error("Page text exceeds budget");
                active.strings.push(item.str, item.hasEOL ? "\n" : " ");
              }
            }
            if (complete && !renderAgain)
              text.textContent =
                active.strings.join("") ||
                "No embedded text is available on this page.";
          } finally {
            const released = finishTextRead(active, !complete);
            if (complete && !released) {
              finishTextRead(active, true);
              throw new Error("Page text reader could not be released");
            }
          }
          page.cleanup();
        } else {
          context.drawImage(image!, 0, 0, canvas.width, canvas.height);
          text.textContent =
            "Image document. No text alternative was supplied by the source.";
        }
        requireLive();
        if (chosenPage !== pageNumber || chosenZoom !== zoom)
          renderAgain = true;
      } while (renderAgain);
      root.hidden = false;
      status.textContent = "";
      canvas.setAttribute("aria-label", `Page ${pageNumber} of ${pageCount}`);
      send("page", { page: pageNumber, pages: pageCount, zoom });
    } catch {
      if (!closed) fail();
    } finally {
      rendering = false;
      clearTimeout(renderTimer);
    }
  };
  const load = async () => {
    requireLive();
    renderTimer = setTimeout(fail, config.limits.renderMs);
    const bytes = payload!;
    payload = null;
    try {
      if (kind === "pdf") {
        task = pdfjs.getDocument({
          data: bytes,
          isEvalSupported: false,
          enableScripting: false,
          enableXfa: false,
          useWasm: false,
          useWorkerFetch: false,
          useSystemFonts: false,
          disableFontFace: true,
          disableAutoFetch: true,
          disableStream: true,
          disableRange: true,
          isOffscreenCanvasSupported: false,
          isImageDecoderSupported: false,
          enableHWA: false,
          stopAtErrors: true,
          maxImageSize: config.limits.maxImagePixels,
          canvasMaxAreaInBytes: config.limits.maxCanvasPixels * 4,
          cMapPacked: true,
          BinaryDataFactory: BundledBinaryDataFactory,
          cMapUrl: "bundled-cmaps/",
          standardFontDataUrl: "bundled-fonts/",
          verbosity: 0,
        });
        task.onPassword = () => fail();
        pdf = await task.promise;
        requireLive();
        pageCount = pdf.numPages;
        if (
          !Number.isInteger(pageCount) ||
          pageCount < 1 ||
          pageCount > config.limits.maxPages ||
          pdf.isPureXfa
        )
          throw new Error("Unsupported PDF");
        pageNumber = Math.min(pageNumber, pageCount);
      } else {
        image = new Image();
        objectUrl = URL.createObjectURL(
          new Blob([new Uint8Array(bytes).buffer], { type: mime }),
        );
        await new Promise<void>((resolve, reject) => {
          image!.onload = () => resolve();
          image!.onerror = () => reject(new Error("Invalid image"));
          image!.src = objectUrl;
        });
        requireLive();
        if (
          image.naturalWidth * image.naturalHeight >
          config.limits.maxImagePixels
        )
          throw new Error("Image exceeds budget");
      }
      clearTimeout(renderTimer);
      await render();
    } catch {
      if (!closed) fail();
    } finally {
      if (bytes.byteLength) bytes.fill(0);
    }
  };
  const receive = (event: MessageEvent) => {
    if (seenEvents.has(event)) return;
    seenEvents.add(event);
    try {
      if (
        typeof event.data !== "string" ||
        event.data.length > config.limits.chunkBytes * 2
      )
        throw new Error("Invalid message");
      const message = JSON.parse(event.data);
      if (message.id !== config.id || closed) return;
      if (message.type === "purge") {
        clear();
        return;
      }
      if (message.type === "begin") {
        if (
          payload ||
          task ||
          image ||
          expiry ||
          !["pdf", "image"].includes(message.kind) ||
          !["application/pdf", "image/png", "image/jpeg"].includes(
            message.mime,
          ) ||
          !Number.isSafeInteger(message.length) ||
          message.length < 1 ||
          message.length > config.limits.maxBytes ||
          !Number.isFinite(message.ttl) ||
          message.ttl <= 0 ||
          message.ttl > 15_000
        )
          throw new Error("Invalid admission");
        expiry = Date.now() + message.ttl;
        timer = setTimeout(() => {
          clear();
          send("expired");
        }, message.ttl);
        kind = message.kind;
        mime = message.mime;
        pageNumber =
          Number.isSafeInteger(message.page) && message.page > 0
            ? Math.min(message.page, config.limits.maxPages)
            : 1;
        zoom = [0.5, 0.75, 1, 1.25, 1.5, 2].includes(message.zoom)
          ? message.zoom
          : 1;
        payload = new Uint8Array(message.length);
        send("ack", { sequence: -1 });
        return;
      }
      requireLive();
      if (message.type === "chunk") {
        if (message.sequence === sequence - 1) return;
        if (
          !payload ||
          message.sequence !== sequence ||
          typeof message.data !== "string" ||
          message.data.length > Math.ceil(config.limits.chunkBytes / 3) * 4
        )
          throw new Error("Invalid chunk");
        const chunk = decode(message.data);
        if (
          !chunk.length ||
          chunk.length > config.limits.chunkBytes ||
          offset + chunk.length > payload.length
        )
          throw new Error("Invalid transfer size");
        payload.set(chunk, offset);
        offset += chunk.length;
        chunk.fill(0);
        send("ack", { sequence: sequence++ });
        return;
      }
      if (message.type === "end") {
        if (!payload || offset !== payload.length)
          throw new Error("Incomplete transfer");
        void load();
        return;
      }
      if (message.type === "navigate") {
        if (!pdf && !image) return;
        if (
          !Number.isSafeInteger(message.page) ||
          message.page < 1 ||
          message.page > pageCount ||
          ![0.5, 0.75, 1, 1.25, 1.5, 2].includes(message.zoom)
        )
          throw new Error("Invalid position");
        pageNumber = message.page;
        zoom = message.zoom;
        void render();
        return;
      }
      throw new Error("Unknown renderer command");
    } catch {
      if (!closed) fail();
    }
  };
  window.addEventListener("message", receive);
  document.addEventListener("message", receive as EventListener);
  for (const type of [
    "click",
    "auxclick",
    "contextmenu",
    "dragstart",
    "drop",
    "submit",
  ])
    document.addEventListener(type, (event) => event.preventDefault(), true);
  window.addEventListener("pagehide", clear);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clear();
  });
  // CSP is the network fence. These also make accidental API use fail visibly.
  host.fetch = () => Promise.reject(new Error("Network disabled"));
  for (const name of [
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "Worker",
    "SharedWorker",
  ])
    host[name] = function () {
      throw new Error("Network and workers disabled");
    };
  host.open = () => null;
  host.print = () => {};
  send("ready");
}
