/** Mock-only transport; this fixture must never forward a real browser request. */
export function requestMockContractPreview(
  input: RequestInfo | URL, init: RequestInit | undefined, mockTransport: unknown,
): Promise<Response> {
  if (typeof document !== "undefined" || typeof window === "undefined"
    || Object.getPrototypeOf(window) !== Object.prototype
    || typeof mockTransport !== "function" || Reflect.get(mockTransport, "_isMockFunction") !== true) {
    throw new Error("Contract preview mock fixture requires its owned mock window.");
  }
  return window.fetch(input, init);
}

/** The owned browser context supplies and verifies the actual transport marker. */
export async function readOfflineContractPreview(target: string): Promise<number[]> {
  const refusal = "Offline contract preview fixture requires its own loopback source.";
  let url: URL;
  try { url = new URL(target); } catch { throw new Error(refusal); }
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    || url.origin !== new URL(location.href).origin || url.username || url.password || url.search || url.hash
    || !/^\/api\/contracts\/[a-f0-9-]{36}\/attachments\/[a-f0-9-]{36}\/preview$/.test(url.pathname)) {
    throw new Error(refusal);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5_000);
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    // Omit headers in JavaScript init deliberately: the real browser transport's
    // received-header assertion proves that the observer cannot infer them here.
    const response = await fetch(url.href, { signal: controller.signal });
    if (response.status !== 200 || response.headers.get("content-type")?.split(";", 1)[0] !== "application/pdf") {
      throw new Error("Offline contract preview fixture response refused.");
    }
    reader = response.body?.getReader();
    if (!reader) throw new Error("Offline contract preview fixture stream is absent.");
    const bytes: number[] = [];
    while (true) {
      const next = await reader.read();
      if (next.done) return bytes;
      if (bytes.length + next.value.byteLength > 65_536) {
        throw new Error("Offline contract preview fixture body exceeds its bound.");
      }
      for (const byte of next.value) bytes.push(byte);
    }
  } finally {
    clearTimeout(timer);
    controller.abort();
    if (reader) { void reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
}
